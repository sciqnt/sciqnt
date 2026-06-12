---
name: sq-tiingo
description: Official Tiingo EOD daily prices for US-listed symbols (free bring-your-own key). Use as the reliable price/history source when Yahoo is down or an official source is preferred — not for European venue tickers.
---

# sq-tiingo — market-data source unit

A **source** unit (data in). Flavour: **api** (official, free key). Read-only.

## When to use
You need daily closes / full price history for a **US-listed** symbol (`AAPL`, `SPY`, `BRK-B`) from an **official documented API**. Pair with **sq-yahoo** for European venue tickers (`.L`/`.DE`/`.AS`) — Tiingo doesn't carry them and this unit refuses them locally.

## Setup (once)
Create a free account at tiingo.com, then either store the token in the keychain (service `sq-tiingo`, key `api_token`) or export `TIINGO_API_KEY`. Keyless use is inert (returns nothing, never errors).

## How to use
```bash
TIINGO_API_KEY=… python3 src/sq_tiingo/price.py AAPL
```
Or import: `from sq_tiingo import TiingoProvider` → a `PriceProvider` (`get_price(ticker, asof=…)`); the platform chains it behind Yahoo automatically.

## Caveats
Free tier: 500 unique symbols/month, 50 req/hr — fine for a personal portfolio, not for scanning. License is "internal use only" (never redistribute the data). EOD only; the series is the as-traded close (not split-adjusted — Yahoo's is; see FINDINGS.md).
