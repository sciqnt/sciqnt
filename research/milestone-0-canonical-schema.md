# Milestone 0 — Canonical Cross-Asset Schema (v0)

**Status:** in progress (started after the sq-degiro v1 iteration earned the work).
**Owner:** DavideGCosta · **Vehicle:** `core/sq_schema/`

## Why now
Every bug in the sq-degiro iteration was the same shape: *broker dialect leaked into display code*.

| Leak that surfaced | Root cause it proved |
|---|---|
| `15690087` shown instead of ticker | No `Instrument` entity owning the ID↔symbol↔ISIN map |
| Position value bucketed by listing ccy not account base | No explicit `account.base_currency` vs `instrument.listing_currency` distinction |
| `plBase: {'EUR': -11159.34}` rendered literally | No money type; raw dicts crossed the boundary |
| `realizedProductPl` mistaken for total | No pre-decomposed P/L fields on a `Position` |
| `size==0` treated as malformed | No `is_open` semantics — open vs closed is data, not a special case |
| Three rounds of "where is base_currency in the response?" | Adapter logic mixed with display logic |

The fix is **a single normalize step at the connector boundary**. `live.py` consumes the canonical form and never sees a Degiro field name. Every future connector translates *into* the same shape — so a P/L decomposition that's right for Degiro is automatically right for IBKR, ccxt, etc.

## Status (post-step-5)
- **Transaction + cost-basis booking is NOW SHIPPED** (was deferred at v0; landed alongside `sq_compute`). `core/sq_schema/transaction.py` + `core/sq_compute/fold.py`. FIFO / LIFO / AVG methods, cross-currency P/L decomposed exactly as live's unrealised path. Pinned by 13 hand-checked fold tests + 6 schema tests.

## Out of scope for v0 (declared, not silent)
- **Price time series** — `Position.last_price_local` carries the most-recent point; full series belongs to a `sq-market-data` module later.
- **CorporateAction** — implicit in `Transaction` once that arrives. Splits/dividends handled by the broker's reported `breakEvenPrice` for now.
- **FX provider** — `CashBalance.amount_base` stays `None` until `sq-fx` (or similar) is built. The summary already names this gap explicitly with "needs FX".
- **FIGI resolution** — `Instrument.identifiers["figi"]` is optional. Populated later by `sq-openfigi` when that resolution path exists.
- **Persistence engine (Postgres / Iceberg)** — bitemporal columns ARE on every entity from day one (the one irreversible decision from the research), but storage is in-memory Pydantic for v0. Postgres-now / Iceberg-later is a downstream milestone.

These are **earned** deferrals — sq-degiro doesn't need them today. We add each one when a concrete use case demands it, not on speculation.

## Entities (v0)

### `Bitemporal` (mixin)
Every fact carries two timestamps. **The one irreversible decision** the research called out.

```python
class Bitemporal(BaseModel):
    valid_at: datetime           # when this fact represents truth in the world
                                 # (broker timestamp if available, else fetch time)
    observed_at: datetime        # when we recorded/observed it (always = now)
```

Two ingestions of the same `valid_at` with different `observed_at` = correction history. Free at v0 (just two columns); critical when storage arrives.

### `Account`
```python
class Account(Bitemporal):
    account_id: str              # opaque, broker-assigned
    broker: str                  # "degiro" / "ibkr" / "trading212" / "ccxt:binance" / ...
    base_currency: str           # ISO 4217 — the unit Position.value_base is denominated in
    display_name: str | None = None
```

### `Instrument`
```python
class Instrument(Bitemporal):
    instrument_id: str                   # our stable internal UUID
    identifiers: dict[str, str]          # {"figi": "BBG...", "isin": "IE00...", "ticker": "IB01",
                                         #  "broker:degiro": "15690087"} — multi-scheme, lookup-friendly
    name: str
    asset_class: AssetClass              # STOCK | ETF | BOND | FUND | OPTION | FUTURE | FX | CRYPTO | CASH | INDEX
    listing_currency: str                # ISO 4217 — the currency `last_price_local` is in
    listing_venue: str | None = None     # MIC ("XLON") or descriptive ("London Stock Exchange")
```

Identifier strategy: **borrow OpenFIGI as the eventual spine** (per the research); seed with `broker:<name>` IDs until FIGI resolution is wired. Never make ISIN the primary key — FX / crypto / OTC don't have one.

### `Position`
The load-bearing entity. P/L is **pre-decomposed** so consumers (live, MCP, future analytics) never repeat the math.

```python
class Position(Bitemporal):
    account_id: str                              # FK -> Account
    instrument_id: str                           # FK -> Instrument
    quantity: Decimal                            # number of units held (0 == closed historical)
    last_price_local: Decimal | None             # in instrument.listing_currency
    value_base: Decimal                          # quantity × price, in account.base_currency
    break_even_price_local: Decimal | None       # per-unit cost basis, in instrument.listing_currency
    cost_basis_base: Decimal                     # total cost in base_currency (positive)
    unrealized_product_pl_base: Decimal          # price-driven unrealized P/L
    unrealized_currency_pl_base: Decimal         # FX-driven unrealized P/L
    realized_product_pl_base: Decimal            # price-driven realized P/L (lifetime)
    realized_currency_pl_base: Decimal           # FX-driven realized P/L (lifetime)

    @computed_field
    def unrealized_pl_base(self) -> Decimal:
        return self.unrealized_product_pl_base + self.unrealized_currency_pl_base

    @computed_field
    def realized_pl_base(self) -> Decimal:
        return self.realized_product_pl_base + self.realized_currency_pl_base

    @computed_field
    def total_pl_base(self) -> Decimal:
        return self.unrealized_pl_base + self.realized_pl_base

    @property
    def is_open(self) -> bool:
        return self.quantity != 0
```

**Money types are `Decimal`** (deterministic core / money math protected). Floats only for ratios/percentages.

### `CashBalance`
```python
class CashBalance(Bitemporal):
    account_id: str
    currency: str                # ISO 4217 — currency this balance is held in
    amount: Decimal              # in `currency`
    amount_base: Decimal | None  # converted to account.base_currency; None until sq-fx exists
```

### `PortfolioSnapshot` (the wrapper)
```python
class PortfolioSnapshot(Bitemporal):
    account: Account
    instruments: list[Instrument]
    positions: list[Position]
    cash_balances: list[CashBalance]
```

A snapshot is what a connector returns from a single `live` call. All four entities share the snapshot's `valid_at` by default; individual rows can override (e.g. if a broker stamps each row separately).

## Where things live
| Code | Path | Owns |
|------|------|------|
| Canonical models | `core/sq_schema/` | Entities, validators, enums, derived properties |
| Connector adapters | `modules/sq-<broker>/src/.../canonical.py` | ALL dialect knowledge: field probes, FX math, normalization |
| Consumers | `modules/sq-<broker>/src/.../live.py`, future MCP servers, analytics | Read the canonical types; never see broker JSON |

**The rule:** if your code does `_probe(...)` or `_money_in(...)` or knows the string `"plBase"` exists, you're in an adapter file. If your code says `position.unrealized_currency_pl_base`, you're a consumer.

## Bowing-out invariants (test these)
- `position.unrealized_pl_base == unrealized_product + unrealized_currency`
- `position.total_pl_base == unrealized_pl_base + realized_pl_base`
- For closed positions: `unrealized_*_pl_base == 0`; `realized_pl_base == total_pl_base`
- For same-listing-currency positions: `*_currency_pl_base == 0`
- Every money field is `Decimal`, never `float` (validator-enforced)
- `account.base_currency`, `instrument.listing_currency`, `cash_balance.currency` are ISO 4217 (3 uppercase letters)

## What this milestone *does* unlock
- A canonical `Position` consumed by any agent (MCP, Skills, plain CLI) without re-learning every broker's dialect.
- A clear conformance target for the next connector — "implement `to_canonical()` that produces a `PortfolioSnapshot`; we'll run the same display code against your output."
- A schema for an eventual MCP `get_positions` tool that returns this exact shape — the agent on the other end gets normalized data regardless of which connector served it.

## What this milestone *doesn't* claim
- It is **not** a portfolio engine. No P/L math is performed in `sq_schema` — adapters fill the fields, consumers read them.
- It is **not** persistence. Bitemporal columns exist; storage is a later milestone.
- It is **not** an MCP spec. The MCP serialization is a downstream wrapper.

## Build order in this milestone
1. ✅ Design doc (this file)
2. **Now:** `core/sq_schema/` + entity tests
3. Next: `modules/sq-degiro/src/sq_degiro/canonical.py` (the adapter)
4. Next: refactor `live.py` to consume canonical
5. Next: extend `connector-framework.md` with the canonical contract for future bundles
