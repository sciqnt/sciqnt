# Connector research — Robinhood + prediction markets (Kalshi / Polymarket)

> Deep-research synthesis, 2026-06-01. 5 search angles → 23 sources → 102 claims
> → 25 adversarially verified (23 confirmed, 2 killed). Gates the `AssetClass.EVENT`
> schema decision and the three connectors' field mappings.

## Schema decision (RATIFIED): add `AssetClass.EVENT`

No mature cross-asset schema (OpenBB ODP, and by survey FIX / ISO 10962 / CDM)
ships a prediction-market / event-contract model — OpenBB's 200+ models cover
equities, fixed income, commodities, crypto, currencies, ETFs, futures, options
only. So we add a dedicated asset class, modelled on how Kalshi + Polymarket
natively represent a position (not invented).

**Canonical representation of an event-contract position:**
- `quantity` = signed share/contract count (Kalshi: sign encodes side — +YES / −NO)
- price = probability in `0..1` (Polymarket `avgPrice`/`curPrice`; Kalshi cents/100)
- `value` = shares × price
- settlement = a **money value** (cents, 2dp) — NOT a hard $0/$1 boolean. The
  bare "YES→$1 / NO→$0" claim was REFUTED 1-2: scalar and void outcomes exist,
  and settlement is quoted in cents to 2dp. Model `settlement_value` as Decimal money.

**Event-contract-specific fields (beyond a normal Instrument):**
- `event_id` / `event_ticker` (the event a market belongs to — two-level
  market-within-event hierarchy)
- `outcome` (YES / NO)
- `resolution_date`
- `market_result` enum: `yes | no | scalar | void`
- `settlement_value` (payout per YES contract; money, nullable until resolved)

**Cost basis / realised P&L:** `realized_pnl = settlement_revenue − total_cost_basis − fees`.
Settles to 0 → full cost is the realised loss; settles to 1 → (payout − cost) is
the gain. Both venues expose the components directly (don't infer from price×qty
at settlement — fees and the discrete payout matter).

> Robinhood does NOT need this — it reuses STOCK / CRYPTO / OPTION. The EVENT
> class lands when we build Kalshi (cleanest official API, best vehicle to prove it).

## Robinhood — robin_stocks (unofficial), build FIRST

Auth: username/password + MFA (TOTP or SMS), via `robin_stocks.robinhood.login()`.
Unofficial / reverse-engineered / ToS-grey / fragile — declare it.

**Prefer raw `get_open_stock_positions()` over `build_holdings()`** — build_holdings
is a composite that makes many extra HTTP calls AND returns money as pre-formatted
display strings, including a known bug: `equity_change` uses `'{0:2f}'`
(min-width-2, ~6 decimals) not `'{0:.2f}'`. Parse every string money field to Decimal;
do not assume 2dp.

Read paths + field cheatsheet:
- **Stock positions** — `get_open_stock_positions()` → `{quantity, average_buy_price,
  pending_average_buy_price, instrument (URL), account, created_at, updated_at,
  shares_held_for_*}`. `instrument` is a URL → resolve via `get_instrument_by_url()`
  → `{symbol, simple_name, name, ...}`. Current price via `get_latest_price([symbol])`.
- **Crypto positions** — `get_crypto_positions()` (separate call).
- **Cash** — `load_account_profile()` → `{cash, uncleared_deposits, buying_power}`.
- **Equity** — `load_portfolio_profile()`.
- Canonical mapping: `quantity → quantity`, `average_buy_price → break_even_price_local`
  (avg cost), `latest_price → last_price_local`, `qty × avg → cost_basis_base`,
  `qty × price → value_base`, `(price − avg) × qty → unrealized_product_pl_base`.
  Base currency = USD. Realised P&L = 0 (no settlement events on the live path;
  order-history reconstruction is a future step).
- **OPEN QUESTION (not verified):** transaction/order-history surface
  (`get_all_stock_orders` / `get_all_crypto_orders`) field shapes — so `load_history()`
  returns None for now (no CSV path either). TWR/drawdown won't compute for RH
  until order history is wired; honest gap.

## Kalshi v2 (official) — build SECOND (proves AssetClass.EVENT)

Auth: **RSA-PSS** (SHA-256, MGF1 SHA-256, 32-byte salt). Three headers:
`KALSHI-ACCESS-KEY` (key id), `KALSHI-ACCESS-SIGNATURE` (base64 sig),
`KALSHI-ACCESS-TIMESTAMP` (Unix **ms**). Signed message = `timestamp_ms + METHOD + path`,
query string stripped, `/trade-api/v2` prefix INCLUDED. Host: `external-api.kalshi.com`
(demo: `external-api.demo.kalshi.co`).

Read paths:
- **Positions** — `GET /trade-api/v2/portfolio/positions` → `market_positions[]
  {ticker, position_fp (signed count), total_traded_dollars, market_exposure_dollars,
  realized_pnl_dollars, fees_paid_dollars, last_updated_ts}` + `event_positions[]
  {event_ticker, total_cost_dollars, event_exposure_dollars, realized_pnl_dollars,
  fees_paid_dollars}` + cursor.
- **Cash** — `GET /trade-api/v2/portfolio/balance` → `{balance, balance_dollars,
  portfolio_value, updated_ts, balance_breakdown}`.
- **Settlements (resolved markets)** — `GET /trade-api/v2/portfolio/settlements` →
  `{ticker, event_ticker, market_result, yes_count_fp, yes_total_cost_dollars,
  no_count_fp, no_total_cost_dollars, revenue, settled_time, fee_cost, value}` + cursor.
- Mapping: `position_fp → quantity` (sign → YES/NO), `market_exposure_dollars →
  cost_basis`, `realized_pnl_dollars → realized_pnl`, `fees_paid_dollars → fees`,
  `balance_dollars → cash`, `ticker/event_ticker → instrument_id/event_id`,
  `market_result → resolution`, `value → settlement_value`.
- **RECENCY FLAG:** Kalshi migrated to fixed-point STRING fields — `_fp` (counts, 2dp)
  / `_dollars` (money, up to 6dp). Older cent-integer fields (`total_traded`,
  `market_exposure`, `realized_pnl`, `yes_total_cost`/`no_total_cost`) are deprecated;
  `event_ticker` + `fee_cost` recently added. Code against `_fp`/`_dollars`, parse to Decimal.
- OPEN: `fills` vs `settlements` vs `orders` boundary for a complete transaction ledger
  (settlements only cover resolved markets, not intermediate fills).

## Polymarket — build THIRD (EVENT + wallet-based source)

Positions read is **public, no auth**: `GET https://data-api.polymarket.com/positions?user={address}`
(`user` required; `[]` if empty; HTTP 400 if omitted). `gamma-api` host 404s for this
path — a WebFetch summary that said otherwise was wrong (live-tested).

Position fields (verified): `size, avgPrice (0..1), curPrice (0..1), initialValue,
currentValue, totalBought, cashPnl, percentPnl, realizedPnl, percentRealizedPnl,
proxyWallet, asset (ERC-1155 token id), conditionId, outcome, outcomeIndex,
oppositeAsset, title, slug, endDate, redeemable, negativeRisk`.
- **REFUTED 0-3:** `eventId`, `eventSlug`, `oppositeOutcome` are NOT present — rely
  on `conditionId / asset / outcome / outcomeIndex / title / slug / endDate`.
- Mapping: `size → quantity`, `avgPrice → avg cost (0..1)`, `curPrice → last_price`,
  `currentValue → value_base`, `realizedPnl → realized_pnl`, `conditionId → market id`,
  `asset → outcome token id`, `outcome → YES/NO`, `endDate → resolution_date`.
- **CRITICAL:** for proxy wallets the funder (proxy) address holds USDC + ERC-1155
  outcome tokens, NOT the signing EOA — read balances at the **funder** address.
- Trading auth (not needed for read): two-level — L1 EIP-712 wallet sig (domain
  `ClobAuthDomain`, chainId 137) + L2 HMAC-SHA256 `{apiKey, secret, passphrase}` via
  `POLY_*` headers. `py-clob-client`: `set_api_creds(create_or_derive_api_creds())`.
  signature_type 0/1/2 (EOA / email-proxy / browser-proxy); a newer type 3 (POLY_1271,
  Magic/Privy embedded, post-EIP-7702) was unsupported in py-clob-client v1 — verify
  SDK support before relying on 0/1/2 only.

## Cross-cutting caveats
- robin_stocks money fields are display strings (+ the `equity_change` 6dp bug) → Decimal everywhere.
- Kalshi `_fp`/`_dollars` migration → parse strings, don't use deprecated cent ints.
- Polymarket positions base host is `data-api`, not `gamma-api`; funder ≠ signer for proxy wallets.
- All read-only; execution is a separate, higher trust tier (not built).
