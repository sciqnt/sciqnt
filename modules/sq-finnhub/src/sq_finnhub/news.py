#!/usr/bin/env python3
"""Finnhub company news — the OFFICIAL keyed rung of the news chain.

Free tier: 60 calls/minute with a free account key — generous for a
personal portfolio's news tab. Sits IN FRONT of the keyless Yahoo RSS
rung when a key is configured: deeper coverage, structured payloads,
a real SLA-ish API. Keyless = inert (the chain falls through to RSS).

Key resolution: keychain `sq-finnhub` / `api_token`, env
`FINNHUB_API_KEY` fallback. Never logged, never leaves the machine.

Usage: FINNHUB_API_KEY=… python3 news.py AAPL
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "https://finnhub.io/api/v1/company-news"


def fetch_company_news(ticker: str, *, token: str,
                       days: int = 7) -> list[dict]:
    """Newest-first company news for `ticker` over the last `days`.
    Each item: `{headline, url, summary, published_at (datetime|None)}`
    — the same shape as sq_news_rss.fetch_headlines so providers
    compose. Raises on transport/auth errors; [] when nothing found."""
    today = datetime.now(timezone.utc).date()
    params = {
        "symbol": ticker,
        "from": (today - timedelta(days=days)).isoformat(),
        "to": today.isoformat(),
        "token": token,
    }
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "sciqnt/0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        rows = json.load(r)
    out = []
    for row in rows or []:
        headline = (row.get("headline") or "").strip()
        if not headline:
            continue
        published = None
        ts = row.get("datetime")
        if ts:
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, OSError, OverflowError):
                published = None
        out.append({
            "headline": headline,
            "url": (row.get("url") or "").strip() or None,
            "summary": (row.get("summary") or "").strip() or None,
            "published_at": published,
        })
    out.sort(key=lambda i: i["published_at"]
             or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


if __name__ == "__main__":
    import os
    token = os.environ.get("FINNHUB_API_KEY")
    if not token:
        sys.exit("set FINNHUB_API_KEY (free account at finnhub.io)")
    for t in sys.argv[1:] or ["AAPL"]:
        try:
            for item in fetch_company_news(t, token=token)[:5]:
                ts = (item["published_at"].strftime("%Y-%m-%d %H:%M")
                      if item["published_at"] else "????")
                print(f"{t:8} {ts}  {item['headline'][:80]}")
        except Exception as e:                                 # noqa: BLE001
            print(f"{t:8} ERROR: {type(e).__name__}: {e}")
