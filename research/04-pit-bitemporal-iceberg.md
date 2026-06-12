# 04 — Point-in-Time Data on Postgres + Iceberg

## 1. Why Point-in-Time (PIT) Data Matters
PIT data means a query returns only what was *knowable* on a given historical date. Without it, three biases silently corrupt backtests:
- **Look-ahead bias:** using data before it was actually available. Classic case: fundamentals carry a period-end date (31 Mar) but aren't *reported* until ~6 May; a naive store lets a strategy "trade" on numbers it couldn't have had. Bailey/López de Prado estimate this can inflate annualised returns by 100–500 bps.
- **Survivorship bias:** today's universe excludes delisted/merged/bankrupt names, making history look safer/more profitable. Requires storing index/universe *membership over time*.
- **Restatement / revision / adjustment:** fundamentals get restated; membership changes; prices get retroactively split/dividend-adjusted; vendor errors get corrected. A "current snapshot" DB overwrites the original, so you can't reconstruct what a strategy saw — the core reason a single mutable row per fact is unfit for quant research.

Fix: never overwrite; keep both *when a fact was true* and *when you learned it*.

## 2. Bitemporal Data Modeling
SQL:2011 standardised it:
- **Valid time** (application/effective): the period a fact holds in the real world.
- **System/transaction time:** when the fact was recorded/known; append-only, never updated.
Modeled as four timestamps: `valid_from`/`valid_to` + `system_from`/`system_to`. An **"as-of" query** filters on both: "value valid on date D *as known* on date K." Set K = decision time → look-ahead is structurally impossible.

Implementation patterns: SQL:2011 temporal tables (`AS OF SYSTEM TIME`; Postgres does *not* implement system-versioning natively — model with columns/extensions); SCD Type 2 / bitemporal SCD2; **append-only event log / event sourcing** (naturally bitemporal + replayable).

Load-bearing day-one decision: **every fact table append-only with both valid-time and knowledge-time** (e.g. fundamentals keyed on `instrument, period_end, reported_at`; prices carrying adjustment vintage). Independent of storage engine.

## 3. Apache Iceberg
Open table format over object storage (S3/GCS/ADLS) — ACID, columnar, **immutable snapshots**. Relevant features:
- **Time-travel:** query any prior snapshot by ID/timestamp; one-command rollback. *Physical* reproducibility (the table as it physically was), distinct from *logical* bitemporal as-of — you want both.
- **Branching & tagging:** named pointers to snapshots. Tag "research dataset v2026-05-01" for reproducible backtest inputs; branch for isolated ETL/backfill then atomic fast-forward.
- **Schema evolution** by unique column IDs (safe add/rename/drop); **hidden partitioning** (query raw `trade_date`, Iceberg applies transforms; partition layout can evolve).

Maturity (2025/2026): **v2 mature and ubiquitous**. **v3 now "closed"** (finalised) — deletion vectors + **row lineage** (per-row create/modify tracking, useful for CDC/audit) described as ready; AWS support landed Nov 2025. v3 real but adoption uneven — treat v3-specific features as early-adopter.

Catalogs (decoupled, switchable): **REST catalog** (standardised default for new projects); **AWS Glue** (~39% adoption, managed if on AWS); **Project Nessie** (Git-like catalog branches/tags, ~29%); **Apache Polaris** (open REST catalog w/ RBAC + credential vending, ~21%).

## 4. "Postgres Serving + Iceberg Store-of-Record" Pattern
Postgres stays OLTP/serving (live "what's my P&L now"); Iceberg on object storage = cheap, immutable, columnar store-of-record for history/backtesting. Drivers to split: analytical scans punish OLTP + cost balloons; analytics want columnar/vectorized; replayable immutable history that Postgres in-place mutation + VACUUM make brittle.

Bridge tooling, mature → bleeding-edge:
- **DuckDB + Iceberg** (incl. **pg_duckdb**): mature workhorse; reads/writes Parquet/Iceberg/Delta from S3.
- **pg_lake** (Snowflake-Labs, open-sourced Nov 2025, Apache-2.0): standout for this exact pattern — Iceberg v2 protocol w/ transactional create/modify of Iceberg tables from inside Postgres, execution delegated to DuckDB via `pgduck_server`. Battle-tested previously as Crunchy Data Warehouse — most production-credible Postgres↔Iceberg bridge now.
- **pg_mooncake** (Mooncake-Labs; on Neon): columnstore mirror into Iceberg, sub-second freshness via DuckDB. Newer, real-time-analytics focused.
- **pg_analytics / pg_lakehouse** (ParadeDB): **discontinued/archived** — folded into pg_search. **Do not build on it.**
- **Trino / Spark:** mature heavy-lifting over Iceberg. **ClickHouse:** fast Iceberg reads.

Verdict: DuckDB+Iceberg and Trino/Spark production-ready; **pg_lake most promising integrated bridge** but months old; pg_mooncake promising-but-young; pg_analytics dead.

## 5. How Real Quant/Data Teams Architect PIT
- **Databento:** PIT/immutable by design — raw data parsed/normalized then immutable until delivery; **point-in-time instrument definitions** updated intraday for IPOs/new strikes. North star for instruments/prices.
- **Man AHL — Arctic → ArcticDB:** MongoDB tick store (40x cheaper, 25x faster than legacy) → rewritten as ArcticDB, a C++ dataframe DB over any S3-like object storage. Confirms trajectory toward object-storage-backed, versioned, append-only stores.
- **Academic CRSP PIT datasets:** canonical reference for survivorship-free, point-in-time-correct research data — the gold standard to reproduce.

Common thread: append-only/immutable storage, explicit knowledge-time, object storage for history, fast serving layer in front.

## 6. Pragmatic Staging Recommendation
**Iceberg-first is likely premature**, but the *modelling* must not be. Keep Postgres as system of record; defer the lake until volume/cost/columnar-perf/replay justify it (below ~20 GB you can skip CDC and use periodic snapshots).

Start **Postgres-only with strict bitemporal/append-only modelling.** Get right on day one to keep the Iceberg door open without painful migration:
1. **Append-only fact tables with valid-time + knowledge-time** (no destructive updates). *The one irreversible-if-skipped decision.*
2. Stable surrogate IDs + monotonic ordering/version token per fact (for later CDC into Iceberg).
3. Columnar-friendly types + normalized schema mapping cleanly to Parquet/Iceberg; additive schema evolution.
4. **Temporal universe/membership tables** (survivorship solved in the model, not at query time).
5. Decide nothing catalog-specific yet — catalogs swappable.

**YAGNI line:** skip Iceberg, branching catalogs, Trino/Spark, streaming CDC until you feel OLTP pain or need reproducible large-scale backtests. Adding Iceberg later is a *physical* migration (snapshot/CDC Postgres → Iceberg), straightforward **iff** the bitemporal schema exists. Retrofitting knowledge-time onto a mutable snapshot DB is effectively impossible — the one mistake expensive to undo.

## Sources
- https://www.pfolio.io/academy/look-ahead-bias · https://www.quantifiedstrategies.com/survivorship-bias-backtesting/ · https://analystprep.com/study-notes/cfa-level-2/problems-in-backtesting/
- https://www.tejwin.com/en/insight/tej-point-in-time-audited-financial-database/
- https://en.wikipedia.org/wiki/Bitemporal_modeling · https://en.wikipedia.org/wiki/Temporal_database · https://en.wikipedia.org/wiki/SQL:2011 · https://en.wikipedia.org/wiki/Slowly_changing_dimension
- https://iceberg.apache.org/docs/latest/branching/ · https://estuary.dev/blog/time-travel-apache-iceberg/
- https://opensource.googleblog.com/2025/09/apache-iceberg-110-maturing-the-v3-spec-the-rest-api-and-google-contributions.html · https://www.databricks.com/blog/apache-icebergtm-v3-moving-ecosystem-towards-unification · https://aws.amazon.com/blogs/big-data/accelerate-data-lake-operations-with-apache-iceberg-v3-deletion-vectors-and-row-lineage/
- https://datalakehousehub.com/blog/2026-02-state-of-the-apache-iceberg-ecosystem/ · https://risingwave.com/blog/iceberg-catalog-comparison-guide/
- https://github.com/Snowflake-Labs/pg_lake · https://github.com/Mooncake-Labs/pg_mooncake · https://github.com/duckdb/pg_duckdb · https://github.com/paradedb/pg_analytics · https://www.theregister.com/2025/11/05/snowflake_postgresql_push/
- https://databento.com/blog/instrument-definitions · https://arcticdb.io/ · https://www.infoq.com/presentations/arcticdb/
- https://www.bauplanlabs.com/post/from-postgres-to-your-first-data-lakehouse
