# Milestone 0 — Cross-Asset Validation (paper-sketch second connector)

**Goal:** stress-test the canonical schema before depending on it. If the schema secretly leans on Degiro semantics, we'd find out the hard way when the second real connector lands. Cheaper: sketch two distant connectors on paper, find every gap, fix once.

Two distant connectors stress different axes of the schema:
- **`sq-ibkr`** (Interactive Brokers) — multi-asset (stocks, options, futures, bonds, FX, crypto), real API (Flex Query / Client Portal), mature; the "complex-but-honest" case.
- **`sq-ccxt`** (crypto exchanges via ccxt) — non-ISO currency codes (BTC, ETH, USDT), spot + derivatives, perpetuals, often no FIGI/ISIN; the "non-fiat" case.

If both can fit cleanly into `sq_schema`, the schema isn't Degiro-coloured.

## sq-ibkr — paper sketch

### Input shape (Flex Query XML, simplified)
```
<OpenPositions>
  <OpenPosition
    accountId="U1234567" currency="USD"
    conid="265598" symbol="AAPL" isin="US0378331005"
    securityID="US0378331005" securityIDType="ISIN"
    assetCategory="STK" subCategory="COMMON"
    listingExchange="NASDAQ" multiplier="1"
    position="100" markPrice="195.18" positionValue="19518.00"
    costBasisMoney="14500.00" costBasisPrice="145.00"
    fifoPnlUnrealized="5018.00" mtmPnl="..."
    ... />

  <OpenPosition
    assetCategory="OPT" subCategory="C"
    symbol="SPY 240619C00500000" conid="..." isin=""
    strike="500" expiry="20240619" putCall="C" multiplier="100"
    position="2" markPrice="3.45" positionValue="690.00"
    costBasisPrice="2.10" ... />

  <OpenPosition
    assetCategory="BOND"
    symbol="US TREASURY N/B 4.5 11/15/26" cusip="91282CFB1"
    couponRate="4.500" maturity="2026-11-15"
    accruedInterest="12.34" position="10000" ... />
</OpenPositions>
```

### Translation map → canonical
| IBKR field | Canonical destination |
|---|---|
| `accountId` | `Account.account_id` |
| `currency` (account-level) | `Account.base_currency` |
| `conid` + `isin` + `cusip` + `symbol` | `Instrument.identifiers` (`broker:ibkr`, `isin`, `cusip`, `ticker`) |
| `assetCategory` (`STK`/`OPT`/`FUT`/`BOND`/`CASH`/`CFD`) | `Instrument.asset_class` (mapping table) |
| `listingExchange` | `Instrument.listing_venue` |
| `position` | `Position.quantity` |
| `markPrice` | `Position.last_price_local` |
| `positionValue` | `Position.value_base` (need to confirm IBKR ships this in base, not listing) |
| `costBasisPrice` | `Position.break_even_price_local` |
| `costBasisMoney` | `Position.cost_basis_base` |
| `fifoPnlUnrealized` | sum of `unrealized_product_pl_base` + `unrealized_currency_pl_base` |
| `mtmPnlPositions` | candidate for `unrealized_product_pl_base` |
| `fxTranslationPnl` | candidate for `unrealized_currency_pl_base` |
| `realizedPnl` (from Cash Report) | `realized_*_pl_base` (split where possible) |

### Findings from this sketch

**✅ The 5 entities + the identifier map handle stocks/bonds cleanly.**

**✅ P/L decomposition is *easier* than Degiro** — IBKR ships `mtmPnl` (price portion) and `fxTranslationPnl` (FX portion) separately. The adapter just maps fields; no derivation needed.

**❌ Options need contract terms.** `strike` / `expiry` / `putCall` / `multiplier` have nowhere to live on `Instrument` today. **Gap 1.**

**❌ Bonds need product terms.** `couponRate` / `maturity` / `dayCount` / `accruedInterest` similarly homeless. **Gap 2.**

**❌ Futures need contract specs.** `contractMonth` / `multiplier` / `pointValue`. Same gap class as options.

**❌ `Instrument.listing_currency` is ISO 4217-strict.** Fine for IBKR (stocks/bonds/options in fiat) — but **breaks for ccxt** (see below).

## sq-ccxt — paper sketch

### Input shape (ccxt `fetchBalance` + `fetchPositions`, simplified)
```python
balance = {
    "BTC":  {"free": 0.05, "used": 0.0,  "total": 0.05},
    "ETH":  {"free": 1.20, "used": 0.0,  "total": 1.20},
    "USDT": {"free": 1500.0, "used": 0.0, "total": 1500.0},
}

positions = [
    # spot positions are implied by balance + last trade price
    # derivatives positions explicit:
    {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 0.1,
     "contractSize": 1, "markPrice": 67000, "entryPrice": 65000,
     "unrealizedPnl": 200.0, "leverage": 5, "marginType": "isolated"},
]
```

### Translation map → canonical
| ccxt field | Canonical destination |
|---|---|
| `balance["BTC"]` | `CashBalance(currency="BTC", amount=…)` — **but BTC isn't ISO 4217** |
| `symbol` ("BTC/USDT") | `Instrument.identifiers["ccxt"]` |
| pair quote (`USDT`) | `Instrument.listing_currency` — **also not ISO 4217** |
| `contractSize` × `markPrice` | `Position.value_base` (in quote ccy) |
| `entryPrice` | `Position.break_even_price_local` |
| `unrealizedPnl` | `Position.unrealized_product_pl_base` |
| derivatives terms (`leverage`, `marginType`, perpetual vs dated futures) | same gap class as options/futures |

### Findings from this sketch

**❌ Currency validator must accept crypto codes.** `BTC` / `ETH` / `USDT` / `USDC` / `BUSD` / `SOL` / `XBT` (some exchanges) aren't ISO 4217. **Gap 3.**

**❌ Account base currency for a crypto exchange is debatable.** Some users hold a mix; the "report me in USD" preference belongs on `sq_config.display_currency()` — the *account* base ccy is whatever the exchange reports trades against (often `USDT`). That works: `Account.base_currency = "USDT"`, `sq_config.display_currency = "USD"`, FX provider bridges.

**❌ Spot positions are derived from balances, not a separate "open positions" list.** The adapter needs to enrich balances with last-trade-prices (calls `fetchTicker(symbol)`) to materialize a `Position`. Same canonical output; just more work in the adapter. No schema impact.

**✅ No FIGI / ISIN / CUSIP.** Identifiers map handles it — `{"ccxt": "binance:BTC/USDT", "symbol": "BTC/USDT"}` is enough. **Confirms identifier strategy is right.**

**❌ Perpetual swap "open positions" carry funding-rate accrual.** Marginal — punt to a future schema rev.

## Summary of gaps → minimum schema changes

| Gap | Impact | Action |
|---|---|---|
| **1. Currency validator too strict (ISO 4217 only)** | Blocks ccxt for cash. Blocks any crypto-aware connector. | Relax to `^[A-Z][A-Z0-9]{1,9}$` (3-letter ISO + 3-5 letter crypto). Tests cover BTC/ETH/USDT. |
| **2. Derivatives lack contract terms (options/futures/bonds)** | Connectors representing these would have to stash `strike` etc. in `identifiers` (wrong) or lose the data. | Add optional `Instrument.terms: dict \| None = None` — untyped extension slot. Document the conventional keys per asset class. **Don't** pre-create typed sub-models (OptionTerms/BondTerms) — add them when a real connector forces the issue. |
| **3. No FX rate type / no provider contract** | Multi-ccy totals can't be computed. `CashBalance.amount_base` stays None forever. | Add `FxRate` Pydantic model + `FxRateProvider` Protocol in `sq_schema`. Real implementations live in connector bundles (`sq-fx-ecb`, `sq-fx-yfinance`). |
| **4. No machine-checkable conformance** | Bundles can ship snapshots that pass Pydantic but violate semantic invariants (duplicates, negative cost basis, etc.) | Add `sq_schema.conformance.check_snapshot()` returning a list of violations. Bundles call it in their tests / runtime. |

**What we are NOT changing:**
- Entity count stays at 5 (+ FxRate as a sixth, narrow-purpose). No premature OptionTerms/BondTerms.
- Pydantic v2 / Decimal money / bitemporal — unchanged.
- Existing identifiers map, P/L decomposition, FK validation — unchanged.

## Still deferred (declared, not silent)
- **Transaction event log + cost-basis booking (FIFO/LIFO/avg).** Needed when CSV-import flavour grows up. Out of M0.
- **Price time series.** `Position.last_price_local` is the spot point; series is a separate `sq-market-data` problem.
- **Typed `OptionTerms`/`BondTerms`/`FutureTerms`.** Wait for a real connector. The `terms: dict \| None` slot avoids a schema migration when they arrive.
- **MCP server exposing the canonical types.** Separate scoped milestone — protocol adapter on top of `to_canonical()`. Trivial wrapper once we want it.
- **Persistence engine (Postgres → Iceberg).** Bitemporal columns present; engine deferred.
- **Real FX provider bundles.** Protocol defined now; `sq-fx-ecb` (ECB daily rates) is a clean follow-up milestone.

## What this validation earns us
- **Confidence that the schema isn't Degiro-shaped** — two distant connectors fit with one extension slot (`terms`) and one validator relaxation (currency).
- **A clear M0 closing list** (changes 1–4 above) instead of speculative scope.
- **A documented sketch for connector #2 implementation** when it lands — most of the design work is done on paper.
