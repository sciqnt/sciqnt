#!/usr/bin/env python3
"""sq-kalshi — LIVE flavour: fetch portfolio positions + balance from Kalshi v2
and present them through the shared tabbed TUI.

Auth (verified — research/connectors-prediction-markets-and-robinhood.md):
RSA-PSS request signing. Three headers per request:
  KALSHI-ACCESS-KEY        — the API key id
  KALSHI-ACCESS-SIGNATURE  — base64 RSA-PSS(SHA-256, MGF1 SHA-256, 32B salt)
  KALSHI-ACCESS-TIMESTAMP  — Unix MILLISECONDS
Signed message = f"{timestamp_ms}{METHOD}{path}", path query-stripped and
INCLUDING the /trade-api/v2 prefix. Host: external-api.kalshi.com (prod),
external-api.demo.kalshi.co (demo). Read-only; execution not implemented.
"""
import base64
import json
import pathlib
import sys
import time
import urllib.request
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-kalshi" / "src"))

from sq_schema import AssetClass, PortfolioSnapshot                  # noqa: E402
from sq_secrets import get_secret, load_dotenv                       # noqa: E402
from sq_fmt import (fmt_num, fmt_signed, format_kv, format_table,    # noqa: E402
                    pnl, status)

from sq_kalshi.canonical import to_canonical                         # noqa: E402

SERVICE = "sq-kalshi"
ENV_FILE = pathlib.Path(__file__).resolve().parents[2] / ".env"
PROD_HOST = "https://external-api.kalshi.com"
# Public market-data host (no auth) — current prices for the mark-to-market overlay.
MARKET_HOST = "https://api.elections.kalshi.com"
API_PREFIX = "/trade-api/v2"


class CredentialsMissing(RuntimeError):
    """Raised (never sys.exit) so the aggregated dispatcher downgrades just
    this broker. See sq-degiro/sq-robinhood for the rationale."""


def _credentials(account=None):
    load_dotenv(ENV_FILE)
    key_id  = get_secret(SERVICE, "key_id",      "KALSHI_KEY_ID",      account=account)
    pem     = get_secret(SERVICE, "private_key",  "KALSHI_PRIVATE_KEY", account=account)
    if not key_id or not pem:
        label = f" --account {account}" if account else ""
        raise CredentialsMissing(
            f"No Kalshi credentials found"
            f"{' for account ' + account if account else ''}. "
            f"Set them once with: sciqnt kalshi setup{label} "
            "(API key id + RSA private key)."
        )
    return {"key_id": key_id, "private_key": pem}


def _sign(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    """RSA-PSS sign `timestamp+method+path` → base64. cryptography is an
    install-time dep of the [live] extra."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(
        private_key_pem.encode(), password=None)
    message = f"{timestamp_ms}{method}{path}".encode()
    sig = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(sig).decode()


def _get(creds, path, host=PROD_HOST):
    """Signed GET. `path` must include the /trade-api/v2 prefix and NO query
    string in the signed portion (we sign the path, append query after)."""
    ts = str(int(time.time() * 1000))
    # Sign the path WITHOUT query params; keep the prefix.
    sign_path = path.split("?", 1)[0]
    sig = _sign(creds["private_key"], ts, "GET", sign_path)
    req = urllib.request.Request(host + path, method="GET", headers={
        "KALSHI-ACCESS-KEY":       creds["key_id"],
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "Content-Type":            "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch_market_prices(tickers):
    """Fetch current YES-side probabilities for `tickers` from Kalshi's PUBLIC
    market-data endpoint (no auth). Returns {ticker: Decimal in [0,1]} —
    Kalshi quotes cents (0..100), so we /100. Uses `last_price`, falling back
    to the mid of `yes_bid`/`yes_ask`. Best-effort: unreachable / unpriced
    markets are simply absent from the map (cost-only view for those)."""
    from decimal import Decimal
    out = {}
    tickers = [t for t in (tickers or []) if t]
    if not tickers:
        return out
    # The /markets endpoint accepts a comma-separated `tickers` filter.
    import urllib.parse
    for i in range(0, len(tickers), 100):       # chunk to keep URLs sane
        chunk = tickers[i:i + 100]
        qs = urllib.parse.urlencode({"tickers": ",".join(chunk), "limit": 1000})
        url = f"{MARKET_HOST}{API_PREFIX}/markets?{qs}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sciqnt/0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
        except Exception:                       # noqa: BLE001
            continue
        for m in data.get("markets", []) or []:
            tk = m.get("ticker")
            cents = m.get("last_price")
            if not cents:
                yb, ya = m.get("yes_bid"), m.get("yes_ask")
                if yb and ya:
                    cents = (yb + ya) / 2
            if tk and cents:
                out[tk] = Decimal(str(cents)) / Decimal("100")
    return out


def fetch_live(account=None):
    """Pull positions + balance from Kalshi v2, then overlay current market
    prices from the public market-data endpoint. Returns raw dicts +
    market_prices for to_canonical(). Raises CredentialsMissing / urllib
    errors — the caller wraps so one broker's outage doesn't poison the view."""
    creds = _credentials(account)
    status("connecting to Kalshi…")
    positions_resp = _get(creds, f"{API_PREFIX}/portfolio/positions")
    balance_resp   = _get(creds, f"{API_PREFIX}/portfolio/balance")
    status("connected to Kalshi")
    tickers = [mp.get("ticker")
               for mp in (positions_resp or {}).get("market_positions", []) or []
               if mp.get("ticker")]
    market_prices = fetch_market_prices(tickers)
    return {"positions_resp": positions_resp, "balance_resp": balance_resp,
            "market_prices": market_prices}


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
            inst.identifiers.get("broker:kalshi") or pos.instrument_id,
            terms.get("outcome") or "?",
            pos.quantity,
            _fmt_num(pos.cost_basis_base),
            # P/L coloured green/red by sign — same convention as the
            # aggregated tabs.
            pnl(pos.realized_pl_base, _fmt_signed(pos.realized_pl_base)),
            (terms.get("resolution_date") or "—"),
        ])
    positions_body = (format_table(
        ["market", "side", "qty", f"cost ({base})", f"realised ({base})", "resolves"],
        rows, align=["l", "l", "r", "r", "r", "l"], title="event contracts",
    ) if rows else "  (no open positions)")

    cash = sum((c.amount for c in snapshot.cash_balances), Decimal("0"))
    realised = sum((p.realized_pl_base for p in snapshot.positions), Decimal("0"))
    summary = format_kv([
        ("cash",            f"{_fmt_num(cash)} {base}"),
        ("open contracts",  str(len(snapshot.positions))),
        ("realised P/L",    pnl(realised, f"{_fmt_signed(realised)} {base}")),
    ])
    return {"summary": summary, "positions": positions_body}


def main():
    try:
        raw = fetch_live()
    except CredentialsMissing as e:
        sys.exit(str(e))
    snapshot = to_canonical(raw["positions_resp"], raw["balance_resp"],
                            market_prices=raw.get("market_prices"))
    from sq_tui import tabbed_view  # lazy: interactive viewer (prompt-toolkit)
    tabbed_view(_build_tabs(snapshot), title="kalshi · live")


if __name__ == "__main__":
    main()
