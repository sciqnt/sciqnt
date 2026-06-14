# sciqnt — Agent Quick Start

> **Read this if you are a code-execution agent (Claude code-execution, smolagents,
> ChatGPT Code Interpreter, Cursor agent, etc.) and you need to use sciqnt.**

sciqnt is a Python-first agent-native cross-asset financial-data layer. The
primary AI surface IS this library — you compose its small typed primitives
inside a code block. There is intentionally no large MCP server with 100
tools and no SaaS API. Pick the imports you need; `from sq_compute import
fold_position` and friends are what you'll actually call.

## What's in the box

| Package                        | Purpose                                                                  |
| ------------------------------ | ------------------------------------------------------------------------ |
| `sq_schema`                    | canonical entities (Account, Instrument, Position, CashBalance, Transaction, FxRate, PortfolioSnapshot) + `AssetClass` / `TransactionType` enums. **Money is `Decimal`** — never `float`. Bitemporal columns on every fact (`valid_at` + `observed_at`). |
| `sq_schema.conformance`        | snapshot invariant checker — call `check_snapshot(snapshot)` to catch duplicate positions, negative cost basis, decimal-precision pollution, etc. Returns a list of `Violation`s (empty list = clean). |
| `sq_compute`                   | pure compute functions over the canonical entities. **No I/O.** `fold_position` derives a Position from a Transaction stream (FIFO/LIFO/AVG). `fold_cash_balances` aggregates by currency. `fold_cash_by_type` breaks down by `TransactionType`. Optional `asof` for PIT-correct historical answers. |
| `sq_performance`               | return analytics over a canonical Transaction stream: `xirr` (money-weighted), `total_return`, `twr` (time-weighted, GIPS-style breaks for emptied portfolios), `twr_index_series` (cash-flow-stripped index), `max_drawdown`. Pure compute, no I/O. |
| `sq_analytics`                 | portfolio analytics: `portfolio_summary` / `currency_exposure` / `asset_class_exposure`, income (`dividend_history`, `fee_history`, `income_summary` — cross-ccy, FX-at-date), `realized_pl_over_time` / `cash_flow_over_time`, and per-closure tax lots (`tax_lots`, `all_tax_lots`). |
| `sq_aggregator`                | cross-broker aggregation substrate: `aggregate_value` / `aggregate_positions` / `aggregate_cash` / `aggregate_currency_exposure` / `aggregate_asset_class_exposure` over per-broker `BrokerSnapshot`s. Pure math, no I/O — the dispatcher provides the I/O. |
| `sq_fx`                        | FX rate access: `convert(amount, from_ccy, to_ccy, asof=None)` returns `Decimal | None`. Discovers the configured provider; `None` means no rate available — degrade visibly. |
| `sq_fmt`                       | zero-dependency formatting leaf — number/table/chart/ANSI helpers (`fmt_num`, `format_table`, `render_chart`, `pnl`, …). Connectors render through THIS, not `sq_tui`, so they stay headless (no prompt-toolkit). `sq_tui` builds on it and re-exports these names for back-compat. |
| `sq_secrets` / `sq_config` / `sq_tui` / `sq_platform` | substrate the bundles use (credentials, user config, interactive terminal UI, dispatcher). `sq_tui` is the *interactive* layer built on `sq_fmt`; pull only `sq_fmt` for headless formatting. You generally don't call these directly. |
| `sq_agents`                    | detect installed coding-agent CLIs (claude/codex/…) + launch the user's preferred one with context (default-browser-style; MRU recency in `agent_recency.json`). The TUI's "SciQnt Agent" component is built on this. |
| `sq_skills`                    | install sciqnt's reusable Agent Skills into the agent (claude → `~/.claude/skills/`, codex → `~/.codex/prompts/`) — one general skill per capability group (`sq-portfolio`, `sq-connectors`). The ONLY place sciqnt writes outside its tree (see its FINDINGS.md). |
| `sq_scaffold`                  | scaffold a new connector bundle: `build(root, broker)` writes a conformance-green skeleton into the `.sq-build/` staging area (discovery contract pre-wired in `__init__.py`); `promote()` moves it into `modules/` once green. |

Per-broker / per-source code lives under `modules/sq-<name>/`:

| Module           | What                                                                                |
| ---------------- | ----------------------------------------------------------------------------------- |
| `sq-degiro`      | Degiro broker. `to_canonical(...)` for live API → `PortfolioSnapshot`. `to_canonical_transactions(csv)` + `to_canonical_account_events(csv)` for history. `pnl.compute(data_dir)` is the orchestrator for CSV-driven realized P&L + cash reconciliation. |
| `sq-fx-ecb`      | ECB EUR-cross FX provider (the first `FxRateProvider` implementation). Public, no auth. Full daily history since 1999 for `asof`. |
| `sq-openfigi`    | ISIN → ticker resolver via OpenFIGI's free API.                                     |
| `sq-firds`       | ISIN → official EU reference data (name, CFI, asset class, ccy) via ESMA FIRDS — knows delisted instruments OpenFIGI doesn't. No key. |
| `sq-yahoo`       | Prices from the unofficial Yahoo chart endpoint: spot quotes + FULL daily history + dividend/split events (`fetch_chart`). Primary price rung. |
| `sq-tiingo`      | Official EOD daily prices, free BYO key, US-listed symbols only. Second price rung (inert keyless). |
| `sq-news-rss`    | Per-ticker headlines via Yahoo Finance RSS (no key) — the keyless news rung.       |
| `sq-finnhub`     | Official company news, free BYO key — the keyed news rung (inert keyless).         |
| `sq-edgar`       | SEC filings + fundamentals-lite (8-K / Form 4 / 10-K stream, latest-FY figures). Official, no key. Context only. |
| `sq-config`      | User config UI (`sciqnt config show/set`).                                          |

Also in `core/`: **`sq_price_store`** — the append-only bitemporal price
archive every provider writes through (`~/.local/share/sciqnt/price-archive/`);
providers serve from it when their source breaks. **`sq_market_data.
ChainProvider`** composes price rungs (first non-None wins).

## Setup (one-time)

```python
import sys
from pathlib import Path

# Point sys.path at the in-repo packages. (When sciqnt is later pip-installable,
# this step goes away — for now the repo is the install.)
ROOT = Path("~/Projects/sq").expanduser()  # your checkout
sys.path.insert(0, str(ROOT / "core"))
for m in (ROOT / "modules").glob("sq-*"):
    if (m / "src").is_dir():
        sys.path.insert(0, str(m / "src"))
```

(In a code-execution sandbox or future pip-installed flow you skip this.)

## Common compositions

### Fold a Transaction stream into a Position

```python
from decimal import Decimal
from datetime import datetime, timezone
from sq_schema import Transaction, TransactionType
from sq_compute import fold_position, CostBasisMethod

txns = [
    Transaction(
        transaction_id="t1", account_id="A", instrument_id="I",
        type=TransactionType.BUY,
        executed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        quantity=Decimal("10"), price_local=Decimal("100"),
        amount=Decimal("-1000"), amount_currency="EUR",
    ),
    Transaction(
        transaction_id="t2", account_id="A", instrument_id="I",
        type=TransactionType.SELL,
        executed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        quantity=Decimal("-5"), price_local=Decimal("130"),
        amount=Decimal("650"), amount_currency="EUR",
    ),
]
pos = fold_position(
    account_id="A", instrument_id="I", base_currency="EUR",
    transactions=txns, method=CostBasisMethod.FIFO,
)
# pos.quantity == 5  (5 still held after selling half)
# pos.realized_product_pl_base == 150  ((130-100) * 5 = +150 EUR on the sold lot)
# pos.cost_basis_base == 500  (remaining 5 @ 100)
```

### Parse a Degiro CSV → canonical Transactions → fold

```python
from pathlib import Path
from sq_degiro.canonical import (
    to_canonical_transactions, to_canonical_account_events,
)
from sq_compute import fold_position

trades = to_canonical_transactions(
    Path("data/degiro/transactions.csv"), account_id="degiro",
)
events = to_canonical_account_events(
    Path("data/degiro/account.csv"), account_id="degiro",
)
# Fold one instrument
position = fold_position(
    account_id="degiro", instrument_id="degiro:isin:IE00BGSF1X88",
    base_currency="EUR", transactions=trades,
)
```

### Convert money via the FX substrate

```python
from decimal import Decimal
import sq_fx

eur = sq_fx.convert(Decimal("100"), "USD", "EUR")
# None means no provider installed or the pair is unknown — degrade visibly.
if eur is None:
    print("no rate; install sq-fx-ecb or configure another provider")
```

### PIT-correct historical position

```python
from datetime import datetime, timezone
from sq_compute import fold_position

# What did my position look like on 2024-03-15?
asof = datetime(2024, 3, 15, tzinfo=timezone.utc)
historical = fold_position(
    account_id="A", instrument_id="I", base_currency="EUR",
    transactions=all_txns, asof=asof,
)
```

### Per-closure tax-lot audit trail

```python
from sq_analytics import tax_lots, all_tax_lots

# Per-instrument closures (FIFO by default; LIFO / AVG supported)
closures = tax_lots(
    transactions, account_id="degiro",
    instrument_id="degiro:isin:IE00BGSF1X88",
    base_currency="EUR",
)
for c in closures:
    print(c.opened_at.date(), "→", c.closed_at.date(),
          c.quantity, "units, P/L", c.realized_pl_base,
          f"(held {c.holding_days} days)")

# Account-wide fan-out, sorted by closed_at
for c in all_tax_lots(transactions, account_id="degiro", base_currency="EUR"):
    ...
```

The realized-P/L decomposition (`realized_product_pl_base`,
`realized_currency_pl_base`, `realized_fees_base`) on each `ClosedLot`
sums cent-for-cent to the corresponding `Position.realized_*_base` —
shared matching code in `sq_compute.match_sell_lots` prevents drift.

### Live Degiro snapshot (API path) → canonical

```python
from sq_degiro.live import fetch_live
from sq_degiro.canonical import to_canonical

raw_update, raw_products, base_ccy, int_account, raw_tp = fetch_live()
snapshot = to_canonical(raw_update, raw_products, base_ccy, int_account)
# snapshot.account / snapshot.instruments / snapshot.positions / snapshot.cash_balances
```

### Validate a snapshot

```python
from sq_schema import conformance
violations = conformance.check_snapshot(snapshot)
if violations:
    raise AssertionError(conformance.format_violations(violations))
```

## Bitemporal honesty

Every entity has:
- `valid_at` — when the fact is true in the world
- `observed_at` — when we recorded it (always now-on-creation)

Two ingestions of the same `valid_at` with different `observed_at` = correction
history. `fold_position(transactions, asof=X)` stamps the returned Position
with `valid_at=X` — PIT-correct by construction.

## Where to read next

- **Bundle SKILL.md files** for procedural how-to per source: `modules/sq-degiro/SKILL.md`, `modules/sq-fx-ecb/SKILL.md`, etc.
- **Runnable examples** under `examples/` — each shows one composition.
- **`research/milestone-0-canonical-schema.md`** for the schema design rationale.
- **`research/connector-framework.md`** for the substrate contract that every bundle implements.

## Honest gaps you should know about

- **Mark-to-market is a separate overlay step.** `fold_position` returns `value_base=0` / `last_price_local=None` / `unrealized_*=0` on purpose — folding is auditable history. Use `sq_market_data.overlay_prices(positions, instruments, provider=YahooProvider(), base_currency=...)` to populate the live side on top. Pass an `fx_provider` (e.g. `sq_fx_ecb.ECBProvider()`) when positions span currencies to get an accurate product/currency P/L split; otherwise the overlay falls back to the avg acquisition FX (currency component = 0; honest approximation).
- **No Postgres/Iceberg persistence yet.** Bitemporal columns are present on every entity; persistence is deferred until there's data worth keeping.
- **No second connector yet (IBKR / ccxt / Trading 212).** The shape is proven against `sq-degiro`; the contract is in `research/connector-framework.md`.
- **`Position.realized_pl_base` is fees-INCLUSIVE.** Trade-side fees on `Transaction.fee` are allocated to lots at buy time + applied on sells, surfaced as `Position.realized_fees_base` (≤ 0). The derived `realized_pl_base = product + currency + fees` matches what a broker shows for "Total P/L" on closed positions. Live API path leaves `realized_fees_base = 0` (Degiro's API doesn't expose per-position fees).
- **Symbol-by-name resolution is opportunistic.** Use `sq-openfigi` to canonicalize.

## Principles you can rely on

1. **Money is `Decimal`** at the schema boundary. If you see a float in a `*_base` field, it's a bug.
2. **Pure functions for compute.** No I/O in `sq_compute`. No I/O in `to_canonical*`.
3. **Adapters in `canonical.py`.** All broker-dialect knowledge stops at the adapter boundary; consumers only read canonical types.
4. **Bitemporal everywhere.** `valid_at` + `observed_at` on every fact, no exceptions.
5. **Conformance-checked.** Run `conformance.check_snapshot()` against any new adapter's output to catch semantic violations Pydantic can't.
