#!/usr/bin/env python3
"""sq-degiro — LIVE flavour: fetch current positions + cash from Degiro and
present them through a tabbed TUI.

Architecture (Milestone 0):
  fetch_live()     does the I/O — calls Degiro's API and returns raw response
  to_canonical()   pure translator (in canonical.py) — raw → PortfolioSnapshot
  _build_tabs()    pure presentation — reads canonical types only

Dialect knowledge ('plBase' / 'realizedProductPl' / dict-form money / the
P/L decomposition formulas / productType mapping) lives in canonical.py.
This file should never grow another `_probe(...)` call — if you find
yourself reaching for one, the field belongs on Position or Instrument.
"""
import pathlib
import re
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))
# The wrapper invokes us with `python live.py`, so only this script's own
# directory is on sys.path by default. We need our bundle's src/ on the
# path so the absolute `from sq_degiro.…` import resolves.
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

import sq_analytics                                                  # noqa: E402
import sq_fx                                                         # noqa: E402
from sq_schema import AssetClass, PortfolioSnapshot                  # noqa: E402
from sq_secrets import NeedsAction, get_secret, load_dotenv          # noqa: E402
from sq_tui import (fmt_num, fmt_pct, fmt_signed, format_kv,          # noqa: E402
                    format_table, pnl, status, tabbed_view)

from sq_degiro.canonical import (                                    # noqa: E402
    extract_base_ccy, to_canonical,
    to_canonical_account_events, to_canonical_transactions,
)

# History tab is conditional on the user having their Degiro CSV exports
# in the account's history dir (sq_degiro.history_dir: flat data/degiro/
# legacy, data/degiro/<account>/ for named accounts).

SERVICE = "sq-degiro"
ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"   # bundle-local fallback


class CredentialsMissing(RuntimeError):
    """Raised (NOT sys.exit) when credentials aren't configured, so the
    aggregated dispatcher downgrades just this broker/account instead of
    the whole process dying. SystemExit is a BaseException — it slips past
    the dispatcher's `except Exception` and would kill the entire view
    (matters now that multi-account makes 'a configured broker missing
    creds' a realistic state)."""


# ── Account resolution (the CLI's --account contract) ──────────────────
# Sentinel returned by _resolve_account when SEVERAL accounts are configured
# and the caller didn't say which — the CLI then offers a picker (TTY) or
# exits 2 with the account list (scripts / pipes).
PICK_ACCOUNT = "__pick_account__"


def _resolve_account(accounts, flag):
    """Map (configured accounts, --account flag) → the account to fetch.

      * flag given        → the flag (trust the user; a wrong name surfaces
                            downstream as a friendly CredentialsMissing)
      * exactly one entry → that entry (None == legacy bare-key creds)
      * none configured   → None (legacy behaviour: bare keys may still
                            exist; if not, CredentialsMissing points at
                            `sciqnt degiro setup`)
      * several, no flag  → PICK_ACCOUNT — the caller must choose.

    Pure (no TTY / IO knowledge) so the contract is unit-testable; the TTY
    picker vs exit-2 decision belongs to main()."""
    if flag:
        return flag
    accounts = list(accounts or [])
    if not accounts:
        return None
    if len(accounts) == 1:
        return accounts[0]
    return PICK_ACCOUNT


def _account_display(name):
    """How an accounts() entry reads in user-facing text (None == the legacy
    unnamed single-account scheme)."""
    return name if name else "default"


# ── Credentials (kept here — credential plumbing belongs to the bundle) ─
def _credentials(account=None):
    """Pull (username, password, optional totp_secret) for `account`.
    `account=None` → legacy unqualified storage (single-account scheme);
    `account="<name>"` → qualified storage (`<name>:username` etc),
    populated via `sciqnt degiro setup --account <name>`.
    Raises CredentialsMissing (a RuntimeError) — never sys.exit."""
    load_dotenv(ENV_FILE)
    from degiro_connector.trading.models.credentials import Credentials
    user = get_secret(SERVICE, "username",    "DEGIRO_USERNAME",    account=account)
    pwd  = get_secret(SERVICE, "password",    "DEGIRO_PASSWORD",    account=account)
    totp = get_secret(SERVICE, "totp_secret", "DEGIRO_TOTP_SECRET", account=account)
    if not user or not pwd:
        label = f" --account {account}" if account else ""
        raise CredentialsMissing(
            f"No credentials found{' for account ' + account if account else ''}. "
            f"Set them once with: sciqnt degiro setup{label} "
            "(or a local .env — see .env.example)."
        )
    kw = {"username": user, "password": pwd}
    if totp:
        kw["totp_secret_key"] = totp
    return Credentials(**kw)


# ── I/O: fetch the raw response from Degiro ─────────────────────────────
def fetch_live(account=None):
    """Calls Degiro's API and returns the raw payload required by
    canonical.to_canonical(). Returns:
        (raw_update, raw_products_data, base_ccy, int_account, raw_total_portfolio)
    where raw_total_portfolio is the broker-native totalPortfolio block
    that we surface separately in the 'detailed' tab (deliberate raw view —
    canonical doesn't normalize broker housekeeping fields)."""
    from degiro_connector.trading.models.account import UpdateOption, UpdateRequest

    # Shared per-account session (in-process singleton + persisted session
    # id) — NOT a fresh connect() per fetch, which made every refresh look
    # like a new device/browser to Degiro and spammed login-alert emails.
    from sq_degiro import connected_api
    api, int_account = connected_api(account)
    raw_client = api.get_client_details()
    try:
        raw_account_info = api.get_account_info()
    except Exception:
        raw_account_info = None

    raw_update = api.get_update(request_list=[
        UpdateRequest(option=UpdateOption.PORTFOLIO,       last_updated=0),
        UpdateRequest(option=UpdateOption.CASH_FUNDS,      last_updated=0),
        UpdateRequest(option=UpdateOption.TOTAL_PORTFOLIO, last_updated=0),
    ], raw=True)

    base_ccy = extract_base_ccy(raw_account_info, raw_client, raw_update)
    status(f"connected · int_account={int_account} · base ccy={base_ccy or '?'}")

    # Resolve every position's productId into the product-info dict
    pids = []
    for row in (raw_update or {}).get("portfolio", {}).get("value", []):
        for kv in row.get("value", []):
            if kv.get("name") == "id":
                try:
                    pids.append(int(kv.get("value")))
                except (TypeError, ValueError):
                    pass
                break
    raw_products_data = {}
    if pids:
        try:
            resp = api.get_products_info(product_list=pids, raw=True)
            raw_products_data = (resp or {}).get("data", {}) or {}
        except Exception as e:
            status(f"product info lookup failed: {type(e).__name__}: {e}")

    raw_total_portfolio = (raw_update or {}).get("totalPortfolio", {})
    return raw_update, raw_products_data, base_ccy, int_account, raw_total_portfolio


# ── Presentation helpers — number formatting lives in sq_tui (one home);
# thin aliases keep this module's call sites unchanged.
_fmt_num = fmt_num
_fmt_signed = fmt_signed
_fmt_pct = fmt_pct


def _camel_to_words(s):
    return re.sub(r"(?<!^)(?=[A-Z])", " ", s).lower()


# AssetClass → display label (display config, NOT dialect — same enum could
# be displayed differently in another UI without changing the canonical
# meaning of AssetClass.STOCK).
_ASSET_CLASS_LABELS = {
    AssetClass.STOCK:   "Shares",
    AssetClass.ETF:     "ETFs / Trackers",
    AssetClass.BOND:    "Bonds",
    AssetClass.FUND:    "Funds",
    AssetClass.OPTION:  "Options",
    AssetClass.FUTURE:  "Futures",
    AssetClass.FX:      "Currency",
    AssetClass.CRYPTO:  "Crypto",
    AssetClass.INDEX:   "Indices",
    AssetClass.WARRANT: "Warrants",
    AssetClass.CFD:     "CFDs",
    AssetClass.CASH:    "Cash",
    AssetClass.OTHER:   "Other",
}


# ── Tab builders (all read canonical types only) ────────────────────────
def _build_tabs(snapshot: PortfolioSnapshot, raw_total_portfolio: dict,
                account=None):
    base_ccy = snapshot.account.base_currency
    instruments = {i.instrument_id: i for i in snapshot.instruments}

    value_header   = f"value ({base_ccy})"
    pl_eur_header  = f"u.P/L ({base_ccy})"
    total_pl_header = f"total P/L ({base_ccy})"

    # ── Positions, grouped by asset class ──────────────────────────────
    def _row(pos):
        inst = instruments[pos.instrument_id]
        price_cell = (f"{_fmt_num(pos.last_price_local)} {inst.listing_currency}"
                      if pos.last_price_local is not None else "—")
        unrealized_pct = None
        if pos.is_open and pos.cost_basis_base > 0:
            unrealized_pct = float(pos.unrealized_pl_base) / float(pos.cost_basis_base) * 100
        return [
            inst.identifiers.get("ticker") or inst.identifiers.get(f"broker:{snapshot.account.broker}") or "?",
            inst.identifiers.get("isin") or "",
            pos.quantity,
            price_cell,
            _fmt_num(pos.value_base),
            _fmt_num(pos.break_even_price_local) if pos.break_even_price_local is not None else "—",
            # P/L cells routed through sq_tui.pnl — green/red by sign, the
            # same convention as the aggregated tabs.
            pnl(pos.unrealized_product_pl_base,
                _fmt_signed(pos.unrealized_product_pl_base)),
            pnl(pos.unrealized_currency_pl_base,
                _fmt_signed(pos.unrealized_currency_pl_base)),
            pnl(pos.unrealized_pl_base, _fmt_signed(pos.unrealized_pl_base)),
            pnl(unrealized_pct, _fmt_pct(unrealized_pct)),
            pnl(pos.realized_pl_base, _fmt_signed(pos.realized_pl_base)),
            pnl(pos.total_pl_base, _fmt_signed(pos.total_pl_base)),
        ]

    headers = ["ticker", "ISIN", "qty", "price", value_header, "BEP",
               "prod P/L", "fx P/L", "u.P/L", "u.P/L%", "realised", total_pl_header]
    align = ["l", "l", "r", "r", "r", "r", "r", "r", "r", "r", "r", "r"]

    groups: dict[str, list] = {}
    for pos in snapshot.positions:
        label = _ASSET_CLASS_LABELS[instruments[pos.instrument_id].asset_class]
        groups.setdefault(label, []).append(pos)
    chunks = []
    for label in sorted(groups):
        rows = [_row(p) for p in sorted(
            groups[label],
            key=lambda p: (instruments[p.instrument_id].identifiers.get("ticker") or "").lower(),
        )]
        chunks.append(format_table(headers, rows, align=align, title=label))
    positions_body = "\n\n".join(chunks) if chunks else "  (no positions)"

    # ── Summary — top metrics in the ACCOUNT's base ccy ─────────────────
    # A single account is shown in its own currency; the config display
    # currency governs cross-account aggregation only (the platform's home/
    # aggregated view), not this single-broker view. Foreign cash legs are
    # still normalised to the account base (that's the account's own total,
    # not a config-driven display conversion).
    display_ccy = base_ccy
    open_positions   = [p for p in snapshot.positions if p.is_open]
    closed_positions = [p for p in snapshot.positions if not p.is_open]

    # positions value (in account base_ccy = position.value_base)
    positions_value = sum((p.value_base for p in open_positions), Decimal("0"))
    # cash by currency
    cash_by_ccy: dict[str, Decimal] = {}
    for c in snapshot.cash_balances:
        if c.amount == 0:
            continue
        cash_by_ccy[c.currency] = cash_by_ccy.get(c.currency, Decimal("0")) + c.amount

    # Try to compute the whole summary in `display_ccy` via the FX substrate.
    # When the provider can convert every leg, we get a single clean total.
    # When something can't be converted (unknown ccy / no provider installed),
    # we surface that line as-is in its source ccy — we NEVER silently sum
    # across rates we don't have.
    fx_provider = sq_fx.get_provider()
    positions_value_display = sq_fx.convert(
        positions_value, base_ccy, display_ccy, provider=fx_provider)
    cash_total_display = Decimal("0")
    unconverted_cash: list[tuple[str, Decimal]] = []
    for ccy in sorted(cash_by_ccy):
        amt = cash_by_ccy[ccy]
        converted = sq_fx.convert(amt, ccy, display_ccy, provider=fx_provider)
        if converted is None:
            unconverted_cash.append((ccy, amt))
        else:
            cash_total_display += converted

    summary_items: list[tuple] = []
    if positions_value_display is not None and not unconverted_cash:
        # Clean single-currency view — every leg converted.
        total = positions_value_display + cash_total_display
        summary_items += [
            ("total value",     f"{_fmt_num(total)} {display_ccy}"),
            ("positions value", f"{_fmt_num(positions_value_display)} {display_ccy}"),
            ("cash",            f"{_fmt_num(cash_total_display)} {display_ccy}"),
        ]
    else:
        # Partial — some legs couldn't be converted. Show what we have.
        if positions_value_display is not None:
            summary_items.append(("positions value", f"{_fmt_num(positions_value_display)} {display_ccy}"))
        else:
            summary_items.append(("positions value", f"{_fmt_num(positions_value)} {base_ccy} (no rate to {display_ccy})"))
        if cash_total_display:
            summary_items.append(("cash (converted)", f"{_fmt_num(cash_total_display)} {display_ccy}"))
        for ccy, amount in unconverted_cash:
            summary_items.append(
                (f"+ {ccy} cash (no rate)", f"{_fmt_num(amount)} {ccy}"),
            )

    # Lifetime total P/L = sum of every position's total_pl_base (open + closed)
    total_pl_lifetime = sum((p.total_pl_base for p in snapshot.positions), Decimal("0"))
    if snapshot.positions:
        summary_items.append(
            ("total P/L (lifetime)",
             pnl(total_pl_lifetime,
                 f"{_fmt_signed(total_pl_lifetime)} {base_ccy}")),
        )
    summary_items += [
        ("open positions",   str(len(open_positions))),
        ("closed positions", str(len(closed_positions))),
        ("currencies",       f"{len(cash_by_ccy)} ({', '.join(sorted(cash_by_ccy)) or '—'})"),
    ]
    summary_body = format_kv(summary_items)

    # ── Detailed: broker-native totalPortfolio block (the one deliberate
    # peek under the hood — not part of the canonical layer; useful when
    # debugging or when a broker ships a field we don't yet normalize).
    detailed_rows = []
    tp_flat = {kv.get("name"): kv.get("value")
               for kv in (raw_total_portfolio or {}).get("value", [])}
    for k, v in tp_flat.items():
        try:
            numv = float(v)
        except (TypeError, ValueError):
            continue
        if numv == 0:
            continue
        detailed_rows.append([_camel_to_words(k), _fmt_num(numv)])
    detailed_body = (format_table(["metric", "amount"], detailed_rows)
                     if detailed_rows else "  (no broker totals reported)")

    # ── exposure tab: per-currency + per-asset-class via sq_analytics ──
    exposure_body = _build_exposure_tab(snapshot)

    # ── history tab: optional, only when Degiro CSVs are present at the
    # conventional path. We fold transactions there → analytics gives us
    # realized-P/L / dividends / fees / cash-flow buckets by year.
    history_body = _build_history_tab(base_ccy=base_ccy, account=account)

    tabs = {
        "summary":   summary_body,
        "positions": positions_body,
        "exposure":  exposure_body,
    }
    if history_body is not None:
        tabs["history"] = history_body
    tabs["detailed"] = detailed_body
    return tabs


def _build_exposure_tab(snapshot: PortfolioSnapshot) -> str:
    """Two stacked tables: currency exposure + asset-class exposure.
    Both come from sq_analytics — pure compute over the canonical
    snapshot, no broker dialect."""
    base_ccy = snapshot.account.base_currency

    # Currency exposure — positions in their LISTING ccy, cash in native ccy
    ce = sq_analytics.currency_exposure(
        snapshot.positions, snapshot.cash_balances, snapshot.instruments,
        base_currency=base_ccy,
    )
    ce_rows = [
        [ccy, _fmt_num(parts["positions"]), _fmt_num(parts["cash"]),
         _fmt_num(parts["total"])]
        for ccy, parts in sorted(ce.items())
    ]
    ce_body = (format_table(
        ["ccy", "positions", "cash", "total"], ce_rows,
        align=["l", "r", "r", "r"], title="currency exposure",
    ) if ce_rows else "  (no open positions or cash)")

    # Asset class exposure — values in base_currency
    ace = sq_analytics.asset_class_exposure(
        snapshot.positions, snapshot.instruments, base_currency=base_ccy,
    )
    ac_rows = [
        [ac, str(parts["position_count"]),
         _fmt_num(parts["value_base"]),
         _fmt_num(parts["cost_basis_base"]),
         _fmt_signed(parts["realized_pl_base"])]
        for ac, parts in sorted(ace.items())
    ]
    ac_header = ["asset class", "#", f"value ({base_ccy})",
                 f"cost basis ({base_ccy})", f"realised ({base_ccy})"]
    ac_body = (format_table(
        ac_header, ac_rows, align=["l", "r", "r", "r", "r"],
        title="asset-class exposure",
    ) if ac_rows else "  (no positions classified)")

    return ce_body + "\n\n" + ac_body


def _build_history_tab(*, base_ccy: str, account=None) -> str | None:
    """If the user has placed their Degiro CSV exports in the account's
    history dir (`data/degiro/` legacy, `data/degiro/<account>/` named —
    see sq_degiro.history_dir), parse them into canonical Transactions and
    surface a few aggregates (realized P/L by year, dividends, fees, cash
    flow). Returns None if no CSVs present — caller drops the tab silently."""
    from sq_degiro import history_dir
    csv_dir = history_dir(account)
    tx_csv = csv_dir / "transactions.csv"
    ac_csv = csv_dir / "account.csv"
    if not (tx_csv.is_file() and ac_csv.is_file()):
        return None

    try:
        trades = to_canonical_transactions(tx_csv, account_id="degiro")
        events = to_canonical_account_events(ac_csv, account_id="degiro")
    except Exception as e:                # noqa: BLE001 — keep tab optional
        return f"  (CSV parsing failed: {type(e).__name__}: {e})"

    all_txns = trades + events
    cf   = sq_analytics.cash_flow_over_time(
        all_txns, group_by="year", currency=base_ccy)
    divs = sq_analytics.dividend_history(all_txns, group_by="year")
    fees = sq_analytics.fee_history(all_txns, group_by="year")
    from . import _resolve_cost_basis_method
    rpl  = sq_analytics.realized_pl_over_time(
        all_txns, base_currency=base_ccy, group_by="year",
        method=_resolve_cost_basis_method())

    years = sorted(set(cf) | set(divs) | set(fees) | set(rpl))
    if not years:
        return f"  (no events found in {csv_dir})"

    rows = []
    for y in years:
        cf_y = cf.get(y, {}) if isinstance(cf.get(y), dict) else {}
        rows.append([
            str(y),
            _fmt_num(cf_y.get("DEPOSIT",    Decimal("0"))),
            _fmt_num(cf_y.get("WITHDRAWAL", Decimal("0"))),
            _fmt_num(divs.get(y, Decimal("0"))),
            _fmt_num(fees.get(y, Decimal("0"))),
            _fmt_signed(rpl.get(y, Decimal("0"))),
        ])
    header = ["year", "deposits", "withdrawals", "dividends", "fees",
              f"realised ({base_ccy})"]
    return format_table(
        header, rows, align=["l", "r", "r", "r", "r", "r"],
        title=f"history (by year, {base_ccy}; from {csv_dir.name}/)",
    )


def main(argv=None):
    """CLI boundary. Contract: NEVER a raw traceback —
      * CredentialsMissing / NeedsAction → one friendly line, exit 1
      * anything else → `fetch failed: <type>: <msg>`, exit 1
      * --account NAME picks an account; omitted → auto when exactly one is
        configured, picker at a TTY when several, exit 2 with the account
        list when several + non-TTY (scripts must be explicit)."""
    import argparse
    p = argparse.ArgumentParser(
        prog="sq-degiro live",
        description="fetch current positions + cash from Degiro (tabbed TUI)")
    p.add_argument("--account", default=None, metavar="NAME",
                   help="account name (as registered via `sciqnt degiro setup "
                        "--account NAME`); omit to auto-pick the only "
                        "configured account, or choose from a list")
    args = p.parse_args(argv)

    try:
        from sq_degiro import accounts as _accounts
        configured = _accounts()
    except Exception:                                       # noqa: BLE001
        configured = []      # registry unreadable → fall back to legacy keys

    account = _resolve_account(configured, args.account)
    if account is PICK_ACCOUNT:
        names = ", ".join(_account_display(a) for a in configured)
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print(f"configured accounts: {names} — pick one with --account",
                  file=sys.stderr)
            sys.exit(2)
        from sq_tui import select_screen
        # Payloads are 1-tuples so the legacy entry (None) stays
        # distinguishable from the QUIT/REFRESH navigation sentinels.
        choice = select_screen(
            [(_account_display(a), (a,)) for a in configured],
            header="degiro · live — which account?",
            footer_hint="↑/↓ move · enter select · esc cancel")
        if not isinstance(choice, tuple):
            sys.exit(0)                          # cancelled — not an error
        account = choice[0]

    try:
        (raw_update, raw_products, base_ccy,
         int_account, raw_total_portfolio) = fetch_live(account=account)
    except CredentialsMissing as e:
        sys.exit(str(e))                  # friendly message at the CLI boundary
    except NeedsAction as e:
        sys.exit(f"⚠ {e}")                # the user must act — say what, plainly
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:                                  # noqa: BLE001
        print(f"fetch failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    if not base_ccy:
        sys.exit("Could not determine account base currency — set one in "
                 "`sciqnt config set`, or rerun to retry the discovery.")
    snapshot = to_canonical(raw_update, raw_products, base_ccy, int_account)
    tabs = _build_tabs(snapshot, raw_total_portfolio, account=account)
    title = ("degiro · live" if account is None
             else f"degiro:{account} · live")
    tabbed_view(tabs, title=title)


if __name__ == "__main__":
    main()
