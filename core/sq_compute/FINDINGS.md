# sq_compute — findings, quirks & conformance notes

Living log for the deterministic position/cash fold. **Pure, `Decimal`, no I/O.**
Update the moment a quirk or conformance result is discovered.

## What it is
`fold_position(account_id, instrument_id, base_currency, transactions, method)` →
a `Position` by folding an immutable Transaction log (event-sourcing: a position is
a fold over transactions). Plus `fold_position_series(asof_dates=…)` (all checkpoints
in one chronological pass) and the cash-balance folds.

## Quirks (load-bearing)
- **Cost-basis methods:** `FIFO` / `LIFO` / `AVG`. `AVG` is the pooled weighted-average
  family — average-cost / ACB / UK Section-104 pool / Degiro BEP all collapse to one
  weighted-average lot before matching. **Not implemented:** HIFO, true Specific-ID, and
  the UK same-day + 30-day matching pre-steps (AVG approximates UK as the pool only).
  Selected via config at the adapter boundary — the core never reads config (a `method`
  arg is always passed in).
- **Fees are capitalised into realised P&L** (`realized_pl_base = product + currency +
  fees`); `Lot.fee_per_unit_local` releases a proportional buy-side fee on partial sells,
  and the sell's own fee is deducted. This is what reconciles cent-for-cent with the
  Degiro CSV-summation path (`sq-degiro/FINDINGS.md`).
- **`Decimal` end-to-end** — no `float` in the fold. The determinism boundary (P4) is
  absolute here; if you need a config value, resolve it at the caller, pass it in.
- **Single-pass series:** `fold_position_series` produces every `asof` checkpoint in one
  chronological sweep — O(N_txns + N_dates), not O(N×D). Used by the dispatcher's TWR /
  drawdown value-series build.

## Tests
`core/tests/test_compute*.py`, `test_fold*.py` (+ the degiro CSV-vs-fold reconciliation).
