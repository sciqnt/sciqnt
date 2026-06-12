#!/usr/bin/env python3
"""Tiingo EOD daily prices — the OFFICIAL free-key rung of the price chain.

Free Starter tier (verified 2026-06-11 against tiingo.com/about/pricing):
500 unique symbols/month, 50 req/hour, 1k req/day, 30+ years of history,
license "internal use only" — fits bring-your-own-key personal use. The
user creates a free account and stores the token once:

    sciqnt config? no — secrets:  keychain `sq-tiingo` / `api_token`
    (or the TIINGO_API_KEY env var)

Coverage caveat (verified): US & Chinese stocks + ETFs/funds. European
venue listings (.L/.DE/.AS) are NOT in Tiingo's namespace — this rung
only serves plain US-style tickers; the provider gates everything else.

Usage: python3 price.py TICKER [TICKER ...]   (needs the token)
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal

BASE = "https://api.tiingo.com/tiingo/daily"

# Same boundary discipline as sq-yahoo: quantize floats at the source.
_PRICE_QUANTUM = Decimal("0.00000001")


def _quantize(v):
    return Decimal(str(v)).quantize(_PRICE_QUANTUM)


def fetch_chart(ticker, start_date, end_date, *, token):
    """Daily series + dividend/split events for `ticker` — same return
    shape as `sq_yahoo.fetch_chart` so providers/stores compose:

        {"series":    {date: Decimal close},     # AS-TRADED (raw) close
         "dividends": {date: Decimal divCash},
         "splits":    {date: Decimal splitFactor},
         "currency":  "USD",
         "exchange":  None}

    NOTE the series semantics difference vs Yahoo: Tiingo's `close` is
    the as-traded raw close (NOT split-adjusted); Yahoo's series is
    split-adjusted. Identical for any window with no split inside —
    which is the fallback rung's whole job. Declared in FINDINGS.

    Raises on transport / auth / malformed payload — callers degrade."""
    if isinstance(start_date, datetime):
        start_date = start_date.date()
    if isinstance(end_date, datetime):
        end_date = end_date.date()
    url = (f"{BASE}/{urllib.parse.quote(ticker)}/prices"
           f"?startDate={start_date.isoformat()}"
           f"&endDate={end_date.isoformat()}"
           f"&format=json&resampleFreq=daily")
    # Token travels in the Authorization header (Tiingo supports both
    # forms) — keeps the key out of URLs, logs and error messages.
    req = urllib.request.Request(url, headers={
        "User-Agent": "sciqnt/0 (personal portfolio tool)",
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.load(r)

    series: dict = {}
    dividends: dict = {}
    splits: dict = {}
    for row in rows:
        d_raw = row.get("date")
        close = row.get("close")
        if d_raw is None or close is None:
            continue
        d = date.fromisoformat(d_raw[:10])
        series[d] = _quantize(close)
        div = row.get("divCash")
        if div:
            dividends[d] = _quantize(div)
        sf = row.get("splitFactor")
        if sf and Decimal(str(sf)) != 1:
            splits[d] = Decimal(str(sf))

    return {
        "series": series,
        "dividends": dividends,
        "splits": splits,
        # Tiingo's daily feed quotes US-listed instruments in USD; the
        # payload carries no currency field. Declared in FINDINGS.
        "currency": "USD",
        "exchange": None,
    }


if __name__ == "__main__":
    import os
    token = os.environ.get("TIINGO_API_KEY")
    if not token:
        sys.exit("set TIINGO_API_KEY (free account at tiingo.com)")
    today = datetime.now(timezone.utc).date()
    for t in sys.argv[1:] or ["AAPL"]:
        try:
            c = fetch_chart(t, date(1990, 1, 1), today, token=token)
            s = c["series"]
            print(f"{t:8} {len(s)} closes {min(s)} → {max(s)} "
                  f"divs={len(c['dividends'])} splits={len(c['splits'])}")
        except Exception as e:                                 # noqa: BLE001
            print(f"{t:8} ERROR: {type(e).__name__}: {e}")
