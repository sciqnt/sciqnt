---
name: sq-openfigi
description: Resolve an ISIN to candidate exchange tickers (incl. Yahoo symbols) via the free OpenFIGI API. Use to turn an instrument identifier into something a price source can quote.
---

# sq-openfigi — identifier resolver source unit

A **source / reference** unit. Flavour: **api** (free OpenFIGI mapping). Read-only. The identifier spine from the schema research (FIGI).

## When to use
You have an ISIN and need a ticker (e.g. to price it with **sq-yahoo**). Returns candidates across exchanges; the caller picks/validates.

## How to use
```bash
python3 src/sq_openfigi/resolve.py IE00BGSF1X88
```
Or import:
- `resolve_isin(isin)` → list of `{ticker, exchCode, name, yahoo}` (all listings).
- `yahoo_candidates(isin, prefer_suffix=".L")` → **pure** ordered list of Yahoo tickers (preferred venue first). No pricing — keeps this unit independent of any price source. The composition layer validates by trying to fetch each (see `examples/portfolio_value.py`).

## Caveats
OpenFIGI returns *many* listings; OpenFIGI tickers don't always match Yahoo symbols exactly, hence resolve→validate. No key needed at low volume (rate-limited). See FINDINGS.md.
