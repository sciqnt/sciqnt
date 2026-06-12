#!/usr/bin/env python3
"""Minimal market-data source unit: latest + historical prices for a ticker
from Yahoo Finance's public chart endpoint. Stdlib only, text-first,
deterministic — returns whatever the source reports; never invents a price.

Caveat (per research): Yahoo is an unofficial/free source, prices ~15min
delayed and the endpoint can change. Fine for personal unrealized P&L;
swap for a licensed source-unit later behind the same interface if needed.

Usage: python3 price.py TICKER [TICKER ...]
"""
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Yahoo's API returns prices as float64 (e.g. 129.92999267578125). Quantize
# to 8dp at the source boundary so downstream conformance checks (max 12
# fractional digits) never fire on otherwise-correct prices.
_PRICE_QUANTUM = Decimal("0.00000001")


def _quantize_price(v):
    return Decimal(str(v)).quantize(_PRICE_QUANTUM)


def fetch_quote(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&range=5d")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    meta = data["chart"]["result"][0]["meta"]
    return {
        "ticker": ticker,
        "price": _quantize_price(meta["regularMarketPrice"]),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
    }


def fetch_historical_close(ticker, target_date, *, lookback_days=14):
    """Return the closing price on/closest-prior-to `target_date` for
    `ticker`. We request a small window (default 14 trading days) ending
    at target_date so the response covers the date itself and a few
    earlier sessions (markets close on weekends/holidays — we walk
    backward to the most recent session).

    `target_date` accepts a `datetime` (UTC interpreted) or a `date`.

    Returns the same shape as `fetch_quote`:
        {ticker, price, currency, exchange, valid_at}
    `valid_at` is the actual session date Yahoo reported the close for
    (useful when target_date was a weekend → caller knows which Friday).

    Raises on transport / 404 / malformed payload — the YahooProvider
    wrapper catches and degrades to None."""
    if isinstance(target_date, datetime):
        end_dt = target_date
    else:
        end_dt = datetime.combine(target_date, datetime.min.time(),
                                  tzinfo=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    # +1 day to ensure target_date's own session is inclusive (Yahoo's
    # period2 is exclusive of midnight).
    end_unix   = int((end_dt + timedelta(days=1)).timestamp())
    start_unix = int(start_dt.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_unix}&period2={end_unix}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    result = data["chart"]["result"][0]
    meta   = result["meta"]
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0]
              .get("close", []) or [])
    # Walk backward from target_date, find the last non-null close at-or-before.
    # Yahoo's per-session timestamp is the OPEN (e.g. 14:30 UTC for NYSE
    # 09:30 EST), not midnight, so we compare against end-of-day to
    # include the target date's own session.
    chosen_ts = None
    chosen_close = None
    target_epoch = int((end_dt + timedelta(days=1)).timestamp())
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        if ts >= target_epoch:
            break
        chosen_ts, chosen_close = ts, close
    if chosen_close is None:
        raise ValueError(f"no historical close at-or-before {target_date} "
                         f"for {ticker}")
    return {
        "ticker": ticker,
        "price": _quantize_price(chosen_close),
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "valid_at": datetime.fromtimestamp(chosen_ts, tz=timezone.utc),
    }


def fetch_price_series(ticker, start_date, end_date):
    """Fetch every daily close between `start_date` and `end_date`
    (inclusive on the end) for `ticker`. Returns a dict mapping
    `date` → `Decimal` close (quantized to 8dp at the source boundary).

    For multi-date queries this is dramatically cheaper than calling
    `fetch_historical_close` per date — one HTTP request, then
    arbitrary lookups locally."""
    if isinstance(start_date, datetime):
        start_dt = start_date
    else:
        start_dt = datetime.combine(start_date, datetime.min.time(),
                                    tzinfo=timezone.utc)
    if isinstance(end_date, datetime):
        end_dt = end_date
    else:
        end_dt = datetime.combine(end_date, datetime.min.time(),
                                  tzinfo=timezone.utc)
    start_unix = int(start_dt.timestamp())
    # +1 day so end_date's session is included (Yahoo's period2 is exclusive
    # midnight; the session timestamp is intraday)
    end_unix   = int((end_dt + timedelta(days=1)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_unix}&period2={end_unix}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0]
              .get("close", []) or [])
    out: dict = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        session_date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        out[session_date] = _quantize_price(close)
    return out


def fetch_chart(ticker, start_date, end_date):
    """One chart request for everything the archive wants: the full daily
    close series PLUS dividend/split events PLUS currency/exchange meta —
    supersedes the fetch_price_series + fetch_quote pair (one round-trip
    instead of two, and events come along free via `events=div,splits`).

    Returns::

        {"series":    {date: Decimal close},
         "dividends": {date: Decimal per-share amount},
         "splits":    {date: Decimal ratio},          # 3:1 → Decimal("3")
         "currency":  str | None,                     # RAW (may be "GBp")
         "exchange":  str | None}

    Raises on transport / malformed payload — callers degrade to None.
    NOTE: Yahoo's series is split-adjusted; after a split the WHOLE
    history shifts. The archive's append-only bitemporal rows are what
    make that honest (the pre-split observations stay readable)."""
    if isinstance(start_date, datetime):
        start_dt = start_date
    else:
        start_dt = datetime.combine(start_date, datetime.min.time(),
                                    tzinfo=timezone.utc)
    if isinstance(end_date, datetime):
        end_dt = end_date
    else:
        end_dt = datetime.combine(end_date, datetime.min.time(),
                                  tzinfo=timezone.utc)
    start_unix = int(start_dt.timestamp())
    end_unix   = int((end_dt + timedelta(days=1)).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_unix}&period2={end_unix}"
           f"&events=div%2Csplits")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    result = data["chart"]["result"][0]
    meta   = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0]
              .get("close", []) or [])
    series: dict = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        series[datetime.fromtimestamp(ts, tz=timezone.utc).date()] = \
            _quantize_price(close)

    events = result.get("events") or {}
    dividends: dict = {}
    for ev in (events.get("dividends") or {}).values():
        if ev.get("amount") is None or ev.get("date") is None:
            continue
        d = datetime.fromtimestamp(ev["date"], tz=timezone.utc).date()
        dividends[d] = _quantize_price(ev["amount"])
    splits: dict = {}
    for ev in (events.get("splits") or {}).values():
        num, den = ev.get("numerator"), ev.get("denominator")
        if not num or not den or ev.get("date") is None:
            continue
        d = datetime.fromtimestamp(ev["date"], tz=timezone.utc).date()
        splits[d] = (Decimal(str(num)) / Decimal(str(den)))

    return {
        "series": series,
        "dividends": dividends,
        "splits": splits,
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
    }


def fetch_intraday(ticker, *, interval="5m", lookback="1d"):
    """Intraday close bars for `ticker` — the 1D-chart feed
    (`interval=5m&range=1d`, the common default; 1m exists but thins).

    Returns `{"bars": {datetime(UTC): Decimal}, "currency": str|None}`.
    Bars are session-time stamps as Yahoo reports them; the trailing bar
    is the in-progress one. Raises on transport/malformed payloads —
    callers degrade."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval={interval}&range={lookback}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    result = data["chart"]["result"][0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    closes = (result.get("indicators", {}).get("quote", [{}])[0]
              .get("close", []) or [])
    bars = {}
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        bars[datetime.fromtimestamp(ts, tz=timezone.utc)] = \
            _quantize_price(close)
    return {"bars": bars, "currency": meta.get("currency")}


if __name__ == "__main__":
    for t in sys.argv[1:] or ["IB01.L", "EURUSD=X"]:
        try:
            q = fetch_quote(t)
            print(f"{q['ticker']:10} {q['price']:>12} {q['currency'] or '':4} "
                  f"{q['exchange'] or ''}")
        except Exception as e:
            print(f"{t:10} ERROR: {type(e).__name__}: {e}")
