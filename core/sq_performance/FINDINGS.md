# sq_performance — findings, quirks & conformance notes

Living log for the performance analytics over a canonical Transaction stream.
No I/O; money is `Decimal`. Update the moment a quirk is discovered.

## What it is
`xirr` (money-weighted/IRR), `total_return`, `twr` (time-weighted), `max_drawdown`.

## Quirks (load-bearing)
- **The two sanctioned `float` sites (P4 boundary):** raising to a fractional power is the
  one thing `Decimal` lacks, so exactly two exponentiations go through `float` — the XIRR
  solver's discount-factor power (in `_xnpv`) and the TWR annualisation (in `twr`). Both
  results are **quantised to 6dp** before return, so float precision never bleeds into
  output. These are the *only* floats in the money layer and are deliberate/documented —
  do not "fix" them to Decimal. (Referenced by function, not line number — line refs rot.)
- **XIRR solver:** bracketed bisection (no scipy dep). Scans for the first sign change from
  0% outward (picks the economically-meaningful root nearest 0%, matching spreadsheet XIRR),
  then bisects. Returns `None` when <2 flows, all-same-sign, or no bracket/convergence.
- **Cash-flow convention:** only DEPOSIT (investor cash out → negative) and WITHDRAWAL
  (cash in → positive) are external flows; terminal value is a positive inflow at `asof`.
  DIVIDEND/INTEREST/FEE/TAX stay inside the account (in the terminal value) — treating them
  as flows would double-count. Cross-ccy flows convert at the flow's executed_at date.
- **TWR strips the boundary cash flow** from each segment's end value (`R_i = (V_end −
  cf_end)/V_start − 1`), so the rate reflects market growth, not contributions. Drawdown is
  computed over the **TWR-index** series (cash-flow-stripped), not raw value — else a large
  withdrawal reads as a "crash".
- **Annualisation:** `twr(annualise=…)`; per GIPS, sub-1-year periods are NOT annualised by
  default (the `annualize_sub_year_returns` config gates this at the rendering boundary).
- **Empty-portfolio performance breaks (2026-06-11).** A portfolio that EMPTIES mid-series
  (full withdrawal, later re-funded) used to make `twr` return None — the LARGEST real
  account showed "—" because one sample was a **−6.98 reconstruction residue** against a
  ~26k peak (fee-timing artifact of the fold after a near-total withdrawal). Rule now:
  |V_start| ≤ 0.5% of the RUNNING peak (`_EMPTY_EPSILON`) = a GIPS-style break — the
  segment compounds at factor 1 and the chain re-links when capital returns; a MATERIALLY
  negative V_start is still corrupt data → None; a series with ONLY breaks → None (nothing
  measured). `twr_index_series` (moved here from the platform) carries FLAT through breaks
  instead of truncating — truncation was hiding every post-break recovery from drawdown.
  Dust balances (€0.03 between funding eras) hit the same rule, so a 1-cent wobble can't
  print as ±33% "growth".
- **Incomplete-export detector (rendering boundary, `aggregated._summary_tab`):** a
  withdrawal surplus the LEDGER's P/L cannot explain (surplus − total_pl > max(5%, €25))
  means the export window misses the funding era — warn, because XIRR/returns are then
  built on missing flows. A surplus the ledger DOES explain is just a profitable closed
  account (no warning). Found live: deposits of a few euros vs ~7k withdrawals on a
  negative ledger.

## Tests
`core/tests/test_performance.py` (xirr/twr/drawdown), `test_performance_settings.py`.
