#!/usr/bin/env python3
"""sq-robinhood — LIVE flavour: fetch current positions + cash from Robinhood
via the unofficial `robin_stocks` library, then present them through the shared
tabbed TUI.

Architecture mirrors sq-degiro:
  fetch_live()    does the I/O — robin_stocks login + HTTP, returns raw dicts
  to_canonical()  pure translator (canonical.py) — raw → PortfolioSnapshot
  _build_tabs()   pure presentation — reads canonical types only

robin_stocks is UNOFFICIAL / reverse-engineered / subject to Robinhood ToS and
breakage. Credentials (username/password + MFA) are stored locally via the
shared `sq_secrets` substrate (keychain-first, .env fallback) — never the
transcript. Execution is NOT implemented; read-only.
"""
import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-robinhood" / "src"))

import sq_analytics                                                  # noqa: E402
import sq_config                                                     # noqa: E402
import sq_fx                                                         # noqa: E402
from sq_schema import AssetClass, PortfolioSnapshot                  # noqa: E402
from sq_secrets import get_secret, load_dotenv                       # noqa: E402
from sq_fmt import (fmt_num, fmt_signed, format_kv, format_table,    # noqa: E402
                    pnl, status)

from sq_robinhood.canonical import to_canonical                      # noqa: E402

SERVICE = "sq-robinhood"
ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"


# ── Credentials ─────────────────────────────────────────────────────────
class CredentialsMissing(RuntimeError):
    """Raised (NOT sys.exit) when credentials aren't configured, so the
    aggregated dispatcher downgrades just this broker instead of the whole
    process dying. SystemExit is a BaseException — it would slip past the
    dispatcher's `except Exception` and kill the entire view."""


def _credentials(account=None):
    """Pull (username, password, optional MFA/TOTP) for `account`.
    account=None → legacy single-account (bare keychain keys).
    Raises CredentialsMissing (a RuntimeError) — never sys.exit — so the
    library/aggregator path can catch it; the CLI entry presents it nicely."""
    load_dotenv(ENV_FILE)
    user = get_secret(SERVICE, "username",    "ROBINHOOD_USERNAME",    account=account)
    pwd  = get_secret(SERVICE, "password",    "ROBINHOOD_PASSWORD",    account=account)
    mfa  = get_secret(SERVICE, "mfa_secret",  "ROBINHOOD_MFA_SECRET",  account=account)
    if not user or not pwd:
        label = f" --account {account}" if account else ""
        raise CredentialsMissing(
            f"No Robinhood credentials found"
            f"{' for account ' + account if account else ''}. "
            f"Set them once with: sciqnt robinhood setup{label} "
            "(or a local .env — see .env.example)."
        )
    return {"username": user, "password": pwd, "mfa_secret": mfa or None}


# ── I/O: fetch raw responses from Robinhood ──────────────────────────────
def fetch_live(account=None):
    """Log in via robin_stocks and pull the raw shapes to_canonical() needs.

    Returns a dict of raw robin_stocks responses + the resolution maps that
    require extra HTTP (instrument-URL → symbol, symbol → latest price). Pure
    canonical translation happens downstream in to_canonical().

    Raises on auth failure / library absence — callers (the aggregator) wrap
    in try/except so one broker's outage doesn't poison the cross-broker view.
    """
    try:
        import robin_stocks.robinhood as rh
    except ImportError as e:
        raise RuntimeError(
            "robin_stocks not installed — `pip install sq-robinhood[live]` "
            "(or `pip install robin_stocks pyotp`)."
        ) from e
    import pyotp

    creds = _credentials(account)
    mfa_code = None
    if creds["mfa_secret"]:
        mfa_code = pyotp.TOTP(creds["mfa_secret"]).now()
    # store_session=True + a sciqnt-owned pickle dir: robin_stocks then
    # (a) reuses the OAuth token across runs — no login request at all while
    # it's valid — and (b) re-logins with the SAME persisted device_token
    # when it expires. store_session=False generated a brand-new device
    # token per fetch, so Robinhood emailed a "new device" alert every time.
    from sq_secrets import NeedsAction, session_dir
    try:
        rh.login(creds["username"], creds["password"], mfa_code=mfa_code,
                 store_session=True,
                 pickle_path=str(session_dir(SERVICE, account=account)))
    except (EOFError, OSError) as e:
        # robin_stocks blocks on input() when Robinhood demands an SMS/device
        # challenge — in a TUI worker stdin is closed and that surfaces as
        # EOF/OS errors. Translate to the platform's plain-language contract.
        raise NeedsAction(
            "Robinhood wants to verify this device — reconnect via "
            "Connect to Broker Account › robinhood",
            action="reconnect") from e
    status("connected to Robinhood")

    stock_positions = rh.get_open_stock_positions() or []
    # Resolve each position's instrument URL → {symbol, name, ...} and price.
    instrument_map = {}
    price_map = {}
    for p in stock_positions:
        url = p.get("instrument")
        if not url or url in instrument_map:
            continue
        try:
            info = rh.get_instrument_by_url(url) or {}
        except Exception:                                  # noqa: BLE001
            info = {}
        instrument_map[url] = info
        sym = info.get("symbol")
        if sym and sym not in price_map:
            try:
                lp = rh.get_latest_price(sym)
                price_map[sym] = (lp[0] if isinstance(lp, list) and lp else None)
            except Exception:                              # noqa: BLE001
                price_map[sym] = None

    crypto_positions = []
    crypto_price_map = {}
    try:
        crypto_positions = rh.get_crypto_positions() or []
        for c in crypto_positions:
            code = (c.get("currency") or {}).get("code")
            if code and code not in crypto_price_map:
                try:
                    q = rh.get_crypto_quote(code) or {}
                    crypto_price_map[code] = q.get("mark_price") or q.get("ask_price")
                except Exception:                          # noqa: BLE001
                    crypto_price_map[code] = None
    except Exception:                                      # noqa: BLE001
        pass        # crypto is optional; stocks-only accounts still work

    try:
        account_profile = rh.load_account_profile() or {}
    except Exception:                                      # noqa: BLE001
        account_profile = {}

    return {
        "stock_positions":  stock_positions,
        "instrument_map":   instrument_map,
        "price_map":        price_map,
        "crypto_positions": crypto_positions,
        "crypto_price_map": crypto_price_map,
        "account_profile":  account_profile,
    }


# ── Presentation (reuses the shared TUI; numbers only, no dialect).
# Number formatting lives in sq_tui (one home); thin aliases keep call sites.
_fmt_num = fmt_num
_fmt_signed = fmt_signed


_ASSET_LABELS = {AssetClass.STOCK: "Shares", AssetClass.CRYPTO: "Crypto",
                 AssetClass.OPTION: "Options", AssetClass.ETF: "ETFs / Trackers",
                 AssetClass.OTHER: "Other"}


def _build_tabs(snapshot: PortfolioSnapshot):
    base = snapshot.account.base_currency
    inst_by_id = {i.instrument_id: i for i in snapshot.instruments}

    groups: dict[str, list] = {}
    for pos in snapshot.positions:
        label = _ASSET_LABELS.get(inst_by_id[pos.instrument_id].asset_class, "Other")
        groups.setdefault(label, []).append(pos)
    chunks = []
    headers = ["ticker", "qty", "price", f"value ({base})", "BEP",
               "u.P/L", "u.P/L%"]
    align = ["l", "r", "r", "r", "r", "r", "r"]
    for label in sorted(groups):
        rows = []
        for pos in sorted(groups[label],
                          key=lambda p: inst_by_id[p.instrument_id].identifiers.get("ticker", "")):
            inst = inst_by_id[pos.instrument_id]
            pct = (float(pos.unrealized_pl_base) / float(pos.cost_basis_base) * 100
                   if pos.cost_basis_base else None)
            rows.append([
                inst.identifiers.get("ticker") or "?",
                pos.quantity,
                _fmt_num(pos.last_price_local),
                _fmt_num(pos.value_base),
                _fmt_num(pos.break_even_price_local),
                # P/L cells routed through sq_tui.pnl — green/red by sign,
                # same convention as the aggregated tabs.
                pnl(pos.unrealized_pl_base, _fmt_signed(pos.unrealized_pl_base)),
                (pnl(pct, f"{'+' if pct > 0 else ''}{pct:.2f}%")
                 if pct is not None else "—"),
            ])
        chunks.append(format_table(headers, rows, align=align, title=label))
    positions_body = "\n\n".join(chunks) if chunks else "  (no positions)"

    total_value = sum((p.value_base for p in snapshot.positions), Decimal("0"))
    cash = sum((c.amount for c in snapshot.cash_balances), Decimal("0"))
    unreal = sum((p.unrealized_pl_base for p in snapshot.positions), Decimal("0"))
    summary = format_kv([
        ("total value",      f"{_fmt_num(total_value + cash)} {base}"),
        ("positions value",  f"{_fmt_num(total_value)} {base}"),
        ("cash",             f"{_fmt_num(cash)} {base}"),
        ("unrealised P/L",   pnl(unreal, f"{_fmt_signed(unreal)} {base}")),
        ("open positions",   str(len(snapshot.positions))),
    ])
    return {"summary": summary, "positions": positions_body}


def main():
    try:
        raw = fetch_live()
    except CredentialsMissing as e:
        sys.exit(str(e))                  # friendly message at the CLI boundary
    snapshot = to_canonical(
        raw["stock_positions"], raw["instrument_map"], raw["price_map"],
        raw["crypto_positions"], raw["crypto_price_map"], raw["account_profile"],
    )
    from sq_tui import tabbed_view  # lazy: interactive viewer (prompt-toolkit)
    tabbed_view(_build_tabs(snapshot), title="robinhood · live")


if __name__ == "__main__":
    main()
