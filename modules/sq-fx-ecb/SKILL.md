---
name: sq-fx-ecb
description: Get FX rates from the European Central Bank's public daily reference feed. EUR-cross rates, non-EUR pairs triangulated via EUR. Used wherever multi-currency totals are needed.
---

# sq-fx-ecb — ECB FX rate provider

A **source** unit. Implements `sq_schema.FxRateProvider`. Public XML feed, no auth, no rate limits worth fearing — TTL-cached locally so we're polite anyway.

## When to use
Anywhere multi-currency totals are computed:
- `sq-degiro` summary converting non-base-ccy cash for the headline figure
- Any future bundle that needs a quick "convert this amount" call

## How to use
CLI (via the dispatcher):
```bash
sciqnt fx-ecb show EUR USD                 # latest daily
sciqnt fx-ecb show USD GBP --asof 2026-03-15
sciqnt fx-ecb refresh                      # force a cache refresh
```

Programmatic (provider directly):
```python
from sq_fx_ecb import ECBProvider
rate = ECBProvider().get_rate("USD", "EUR")
# rate.rate is Decimal — 1 USD = rate.rate EUR
```

Or via the `sq_fx` substrate (preferred — abstracts the provider so a
future user can swap to `sq-fx-yfinance` without code changes):
```python
from decimal import Decimal
from sq_fx import convert
eur = convert(Decimal("100"), "USD", "EUR")   # 100 USD -> EUR (or None if no provider)
```

## Quirks & caveats
- ECB rates publish weekdays around 16:00 CET. Cache TTL 12h aligns.
- Rates are EUR-cross only; non-EUR pairs are triangulated via EUR.
- Historical limited to last 90 days at v1 (full history endpoint deferred).
- Some currencies excluded (e.g. RUB since 2022) — `get_rate` returns `None`.
- `FINDINGS.md` is the living log of quirks; read + update as you learn things.

## What it does NOT do
- Intra-day rates — ECB ships a daily fixing. For higher-frequency FX use
  `sq-fx-yfinance` (when built) or a paid feed.
- Forward rates / NDFs / illiquid crosses — out of scope.
- Currency conversion that round-trips perfectly — triangulation introduces
  ~1e-10 rounding, well below money-display granularity but visible if you
  divide-and-multiply-back without quantizing.
