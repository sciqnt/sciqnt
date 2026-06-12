---
name: sq-news-rss
description: Latest headlines for a ticker from Yahoo Finance's free RSS feed (no key needed). Use to get news context on a holding — works for US and European venue tickers.
---

# sq-news-rss — news source unit

A **source** unit (context in). Flavour: **api** (unofficial public RSS). Read-only, keyless.

## When to use
You want recent headlines about a holding ("what happened to AAPL today?"). Works for venue-suffixed tickers too (`IB01.L`). The portfolio view's news tab is built on this.

## How to use
```bash
python3 src/sq_news_rss/feed.py AAPL IB01.L
```
Or import: `from sq_news_rss import RssNewsProvider` → `get_news(ticker, limit=5)` returns `sq_schema.NewsItem`s, newest first; `[]` on any failure.

## Caveats
Unofficial Yahoo surface — may change without notice (the provider degrades to `[]`, and a keyed rung like Finnhub can sit in front). News is context for reasoning, never an input to the money math. See FINDINGS.md.
