---
name: sq-finnhub
description: Official company-news API rung (free key, 60 calls/min). Use for reliable structured news on a holding when a Finnhub key is configured; the platform chains it ahead of the keyless RSS rung automatically.
---

# sq-finnhub — news source unit

A **source** unit (context in). Flavour: **api** (official, free key). Read-only.

## When to use
You want reliable, structured company news for a holding and have a (free) Finnhub key. Without a key this unit is inert and the news chain serves Yahoo RSS instead — nothing breaks.

## Setup (once)
Free account at finnhub.io → keychain service `sq-finnhub`, key `api_token` (or `export FINNHUB_API_KEY=…`).

## How to use
```bash
FINNHUB_API_KEY=… python3 src/sq_finnhub/news.py AAPL
```
Or import: `from sq_finnhub import FinnhubNewsProvider` → `get_news(ticker, limit=5)` returns `sq_schema.NewsItem`s newest first; `[]` keyless or on failure.

## Caveats
Free tier 60 calls/min (fine for a portfolio news tab). US-centric coverage — EU venue tickers may return nothing; the chain's RSS rung covers them. Context only. See FINDINGS.md.
