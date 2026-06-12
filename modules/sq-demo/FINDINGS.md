# sq-demo — findings & design notes

Living log. This bundle is synthetic — its "quirks" are design decisions.

- **Determinism contract:** `random.Random(instrument_id)` walks from a
  fixed anchor (2023-01-02); past values NEVER change as the series
  extends to today. Screenshots taken months apart agree on history.
- **EUR-only, offline-only:** no FX, no network — the demo renders
  identically in CI, on a plane, forever. (USD legs were considered and
  rejected: live FX would make the public figures drift.)
- **Fictional tickers (SWRD/SQTC/SBND)** deliberately resolve nowhere:
  Yahoo/OpenFIGI misses are negative-cached and quiet; the 1D intraday
  view falls back to the daily two-point series (honest degradation).
- **Sign conventions** mirror sq-degiro's canonical adapter (BUY qty+/
  amount−, SELL qty−/amount+, income amount+, fee positive-magnitude).
- **Weekends don't exist in demo-land** — the walk has a close every
  calendar day. Harmless for the demo's purpose; noted for honesty.
- **The BUNDLE is offline; the platform isn't necessarily** — the summary
  tab's benchmark line (vs IWDA.AS) does its own live price fetch even in
  demo mode, and degrades gracefully without network. Demo FIGURES stay
  deterministic; the benchmark comparison line may vary/disappear.
- **Live-verified (2026-06-12):** full engine on demo data — TWR
  13.70%/yr, XIRR 9.79%, max drawdown −14.5%, charts, income lines,
  flows, `--json` (net worth €24,121.05 at verification date).
