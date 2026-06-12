# core — sciqnt's shared substrate

`core/` holds everything cross-cutting that the connector bundles in `../modules/`
build on: the canonical schema, the deterministic compute/analytics, the
cross-broker aggregation, the TUI design substrate, and shared identity.

## What's here now
- **`sq_schema/`** — the canonical cross-asset entities (Pydantic): Instrument,
  Position, Transaction, Cash, FxRate, Price, ClosedLot, the enums, the
  bitemporal fields, and the conformance harness (`conformance.check_snapshot`).
- **`sq_compute/`** — deterministic position/cash folding (`fold_position`,
  `fold_position_series`, cost-basis FIFO/LIFO/AVG). Pure, `Decimal`, no I/O.
- **`sq_analytics/`** — realized-P&L-over-time, dividend/fee/cash-flow history, tax lots.
- **`sq_performance/`** — XIRR (money-weighted), TWR (time-weighted), drawdown, total return.
- **`sq_aggregator/`** — cross-broker value / currency-exposure / asset-class aggregation.
- **`sq_market_data/`** — price/FX overlay onto historical positions (provider-pluggable).
- **`sq_fx/`** — FX provider resolution.
- **`sq_config/`** — schema-driven user config substrate (`~/.config/sciqnt/`).
- **`sq_tui/`** — the one design substrate (theme/accent, full-screen `select_screen` /
  `text_input_screen` / `tabbed_view`, tables); every TUI surface goes through it.
- **`sq_platform/`** — the app layer: bundle discovery, the aggregated view, and the
  interactive home. Composes modules (it imports each bundle's `snapshot()`); modules
  never import each other.
- **`sq_secrets/`** — shared credential substrate: native hidden prompt → OS keychain
  (`keyring`), with `.env`/env fallback. Generic + cross-cutting, so it lives here, not
  inside any one connector (extracted from `sq-degiro` after self-reflection on P11).

## What's deferred (honest gap)
The **formalised, versioned contract** — a frozen schema version + a published verb set
every external connector must conform to — is *not yet pinned*. The working entities in
`sq_schema` are real and used everywhere, but they're free to evolve until external
contributors and real use justify freezing them (P1 value-first; the gap is recorded in
`../research/synthesis.md` + `../FOUNDATION.md`). When pinned, the contract stays **thin**
(P8) — that minimalism is what keeps the modules independent.
