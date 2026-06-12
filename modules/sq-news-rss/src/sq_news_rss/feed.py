#!/usr/bin/env python3
"""Per-ticker headlines from Yahoo Finance's public RSS feed.

The NO-KEY rung of the news chain: works for every user out of the box,
including European venue tickers (live-verified `.L` 2026-06-11). Same
caveats as every unofficial Yahoo surface — can change without notice;
the provider degrades to [] and the keyed rung (Finnhub) takes over.

Stdlib only (xml.etree on RSS 2.0). Text-first.

Usage: python3 feed.py TICKER [TICKER ...]
"""
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
FEED = "https://feeds.finance.yahoo.com/rss/2.0/headline"


def fetch_headlines(ticker: str, *, limit: int = 10) -> list[dict]:
    """Newest-first headlines for `ticker`. Each item:
    `{headline, url, summary, published_at (datetime|None)}`.
    Raises on transport errors; returns [] for an empty feed."""
    url = f"{FEED}?{urllib.parse.urlencode({'s': ticker})}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        xml_bytes = r.read()
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []

    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        published = None
        pub_raw = item.findtext("pubDate")
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                published = None
        out.append({
            "headline": title,
            "url": (item.findtext("link") or "").strip() or None,
            "summary": (item.findtext("description") or "").strip() or None,
            "published_at": published,
        })
    out.sort(key=lambda i: i["published_at"]
             or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:limit]


if __name__ == "__main__":
    for t in sys.argv[1:] or ["AAPL"]:
        try:
            for item in fetch_headlines(t, limit=5):
                ts = (item["published_at"].strftime("%Y-%m-%d %H:%M")
                      if item["published_at"] else "????-??-??")
                print(f"{t:8} {ts}  {item['headline']}")
        except Exception as e:                                 # noqa: BLE001
            print(f"{t:8} ERROR: {type(e).__name__}: {e}")
