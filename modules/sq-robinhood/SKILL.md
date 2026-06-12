---
name: sq-robinhood
description: Read Robinhood positions + cash (stocks + crypto) into the sciqnt canonical schema, via the unofficial robin_stocks library.
---

# sq-robinhood — Robinhood source unit

Unofficial (robin_stocks). Read-only. USD-base. Reuses the canonical
`STOCK` / `CRYPTO` asset classes — no schema change.

## Setup (one-time)
```
sciqnt robinhood setup                 # single account
sciqnt robinhood setup --account taxable   # named (multi-account)
```
Stores username / password / optional MFA base32 key in the OS keychain
(`.env` fallback). Verified via a real login before storing.

## Use
```
sciqnt                  # aggregated view — Robinhood appears alongside other brokers
sciqnt robinhood live   # per-broker tabbed view (summary / positions)
```

Library use:
```python
import sq_robinhood
snap = sq_robinhood.snapshot()          # PortfolioSnapshot (live positions + cash)
sq_robinhood.accounts()                 # ['taxable', ...] or [None] (legacy single)
```

## Honest gaps
- No history → `load_history()` / `snapshots_at()` absent, `snapshot(asof=…)`
  raises, TWR / drawdown / realised-P&L don't compute. Live snapshot only.
- Unofficial / ToS-grey / fragile. Execution not implemented.

See FINDINGS.md for field mappings + quirks.
