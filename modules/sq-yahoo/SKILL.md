---
name: sq-yahoo
description: Yahoo Finance prices — spot quotes, FULL daily history with dividend/split events, and PIT closes for any Yahoo ticker (stocks, ETFs, indices, FX). The primary price rung; unofficial but free and keyless. Use to value positions, build value series, or convert currencies when a delayed quote is acceptable.
---

# sq-yahoo — market-data source unit

A **source** unit (data in). Flavour: **api** (unofficial public chart endpoint). Read-only. No key, no auth.

## When to use
You have a Yahoo ticker (e.g. `IB01.L`, `AAPL`, `^GSPC`, `EURUSD=X`) and need a spot price, a historical close, or the full daily series (incl. dividends/splits). Pair with **sq-openfigi** (or **sq-firds**) to go from an ISIN to a ticker first. For an official-API alternative on US-listed symbols, chain with **sq-tiingo**.

## How to use
```bash
bin/sq-yahoo quote IB01.L                 # live (delayed) quote
bin/sq-yahoo close AAPL 2024-03-15        # close on/before a date
python3 src/sq_yahoo/price.py IB01.L EURUSD=X
```
Or import:
- `fetch_quote(ticker)` → `{ticker, price (Decimal), currency, exchange}` — spot.
- `fetch_chart(ticker, start, end)` → `{series: {date: Decimal}, dividends, splits, currency, exchange}` — the FULL daily history + events in ONE request (AAPL reaches 1980; `^GSPC` 1970; `EURUSD=X` 2003). Index/FX symbols work through the same endpoint — this is also the benchmark-series path.
- `fetch_historical_close(ticker, target_date)` — close on/before a date (small-window per-date fetch; the provider's fallback path).
- `YahooProvider` — the `sq_schema.PriceProvider` for `sq_market_data.overlay_prices`. `get_price(ticker)` = spot; `get_price(ticker, asof=…)` = PIT close served from a per-process full-range series cache (one fetch per ticker per process). Pass `store=sq_price_store.PriceStore()` for archive **write-through** (every series/event/spot observation recorded locally) and **archive fallback**: when Yahoo breaks, the last archived series is served (`source="yahoo-archive"`) — bounded by a 7-day staleness grace past the last archived close, beyond which it returns `None` rather than presenting an old close as current. The platform wires the store automatically; bare library use stays archive-free.

## Caveats
- **Unofficial and ~15-min delayed**; the endpoint has changed before and can again (a self-heal trigger). ToS-grey for heavy automated use — fine at personal volume.
- **The chart series is SPLIT-ADJUSTED** (contrast sq-tiingo's as-traded close — declared divergence across a split).
- **LSE quotes in pence** (`GBp`/`GBX`) are normalised to GBP (÷100) on every read path — live, series, archive.
- Price is in the **listing's currency** — convert with an FX provider, don't assume the position's base currency.
- Ticker, not ISIN; suffixes matter (`.L`, `.DE`, `.AS`; FX as `EURUSD=X`).

**Read `FINDINGS.md`** — the living log of quirks (pence trap, negative-caching of dead tickers, archive semantics) and conformance results.
