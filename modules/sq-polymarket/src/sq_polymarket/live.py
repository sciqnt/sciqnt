#!/usr/bin/env python3
"""sq-polymarket — LIVE flavour: fetch positions from Polymarket's PUBLIC,
no-auth Data API and present them through the shared tabbed TUI.

The "credential" is just a wallet ADDRESS — public, not secret. For proxy
wallets (Magic / browser-wallet), positions + USDC live at the FUNDER (proxy)
address, NOT the signing EOA — use the funder address you see on your
Polymarket profile. Read-only; trading (CLOB) auth is not implemented.

Endpoint (verified 2026-06-01, live-tested):
  GET https://data-api.polymarket.com/positions?user=<address>
  (no auth; [] if empty; HTTP 400 if `user` omitted; gamma-api 404s this path)
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-polymarket" / "src"))

from sq_schema import PortfolioSnapshot                             # noqa: E402
from sq_secrets import get_secret, load_dotenv                      # noqa: E402
from sq_tui import (fmt_num, fmt_signed, format_kv, format_table,   # noqa: E402
                    pnl, status, tabbed_view)

from sq_polymarket.canonical import to_canonical                    # noqa: E402

SERVICE = "sq-polymarket"
ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"
DATA_API = "https://data-api.polymarket.com"


class CredentialsMissing(RuntimeError):
    """No wallet address configured. RuntimeError (never sys.exit) so the
    aggregated dispatcher downgrades just this source."""


def _wallet_address(account=None):
    load_dotenv(ENV_FILE)
    addr = get_secret(SERVICE, "wallet_address", "POLYMARKET_WALLET", account=account)
    if not addr:
        label = f" --account {account}" if account else ""
        raise CredentialsMissing(
            f"No Polymarket wallet address configured"
            f"{' for account ' + account if account else ''}. "
            f"Set it once with: sciqnt polymarket setup{label} "
            "(the FUNDER address from your Polymarket profile — public, not secret)."
        )
    return addr


def fetch_live(account=None):
    """GET the public positions list for the configured wallet (no auth) +
    read the funder address's on-chain USDC balance. Returns
    {positions: [...], wallet: <addr>, cash_usdc: Decimal|None}."""
    addr = _wallet_address(account)
    qs = urllib.parse.urlencode({"user": addr})
    req = urllib.request.Request(f"{DATA_API}/positions?{qs}",
                                 headers={"User-Agent": "sciqnt/0"})
    status(f"fetching Polymarket positions for {addr[:10]}…")
    with urllib.request.urlopen(req, timeout=20) as r:
        positions = json.load(r)
    if not isinstance(positions, list):
        positions = []

    # Complete the snapshot with on-chain USDC cash at the funder address.
    # Best-effort: None on RPC failure → cash simply isn't shown.
    from sq_polymarket.onchain import fetch_usdc_balance
    cash_usdc = fetch_usdc_balance(addr)
    return {"positions": positions, "wallet": addr, "cash_usdc": cash_usdc}


# ── presentation — number formatting lives in sq_tui (one home);
# thin aliases keep this module's call sites unchanged.
_fmt_num = fmt_num
_fmt_signed = fmt_signed


def _build_tabs(snapshot: PortfolioSnapshot):
    base = snapshot.account.base_currency
    inst_by_id = {i.instrument_id: i for i in snapshot.instruments}
    rows = []
    for pos in snapshot.positions:
        inst = inst_by_id[pos.instrument_id]
        terms = inst.terms or {}
        rows.append([
            (inst.name or "?")[:40],
            terms.get("outcome") or "?",
            pos.quantity,
            (f"{float(pos.last_price_local):.2f}" if pos.last_price_local is not None else "—"),
            _fmt_num(pos.value_base),
            # P/L coloured green/red by sign — same convention as the
            # aggregated tabs.
            pnl(pos.unrealized_pl_base, _fmt_signed(pos.unrealized_pl_base)),
        ])
    positions_body = (format_table(
        ["market", "side", "shares", "price", f"value ({base})", "u.P/L"],
        rows, align=["l", "l", "r", "r", "r", "r"], title="event contracts",
    ) if rows else "  (no open positions)")

    value = sum((p.value_base for p in snapshot.positions), Decimal("0"))
    unreal = sum((p.unrealized_pl_base for p in snapshot.positions), Decimal("0"))
    summary = format_kv([
        ("positions value", f"{_fmt_num(value)} {base}"),
        ("open contracts",  str(len(snapshot.positions))),
        ("unrealised P/L",  pnl(unreal, f"{_fmt_signed(unreal)} {base}")),
    ])
    return {"summary": summary, "positions": positions_body}


def main():
    try:
        raw = fetch_live()
    except CredentialsMissing as e:
        sys.exit(str(e))
    snapshot = to_canonical(raw["positions"], cash_usdc=raw.get("cash_usdc"))
    tabbed_view(_build_tabs(snapshot), title="polymarket · live")


if __name__ == "__main__":
    main()
