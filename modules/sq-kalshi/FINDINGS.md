# sq-kalshi — findings & quirks

First `AssetClass.EVENT` connector — proves the prediction-market schema
extension end-to-end. Official Kalshi v2 REST API (NOT reverse-engineered).
Read-only. USD-base.

## Architecture
- `canonical.py` — pure `to_canonical(positions_resp, balance_resp, market_meta=…)`
  → `PortfolioSnapshot` of EVENT positions + USD cash. Fixture-tested (9 tests).
- `live.py` — RSA-PSS request signing + signed GETs to `/portfolio/positions`
  and `/portfolio/balance`. `cryptography` does the signing; stdlib urllib the HTTP.
- `__init__.py` — `snapshot(asof=None, *, account=None)` + `accounts()`.

## Auth (verified, research/, 2026-06-01)
RSA-PSS (SHA-256, MGF1 SHA-256, 32-byte salt). Three headers:
`KALSHI-ACCESS-KEY` (key id), `KALSHI-ACCESS-SIGNATURE` (base64 sig),
`KALSHI-ACCESS-TIMESTAMP` (Unix **ms**). Signed message =
`f"{ts_ms}{METHOD}{path}"`, path query-stripped and INCLUDING the
`/trade-api/v2` prefix. Same ts in the message and the header. Host:
`external-api.kalshi.com` (prod), `external-api.demo.kalshi.co` (demo).

## Field mappings + quirks
- **Fixed-point STRING fields**: `_dollars` (money, ≤6dp), `_fp` (counts, 2dp).
  Parse to Decimal. The older cent-integer fields (`total_traded`,
  `market_exposure`, `realized_pnl`, `yes/no_total_cost`) are DEPRECATED — we
  code against `_fp`/`_dollars`. `event_ticker` + `fee_cost` were recently added.
- **`position_fp` is SIGNED**: positive = YES side, negative = NO. We map the
  sign → `terms.outcome` ("YES"/"NO") and store the magnitude as `quantity`.
- **Price is a probability in [0,1]** for EVENT contracts (conformance enforces
  the band). Kalshi quotes cents → divide by 100 if you read a market price.
- **No spot price in `/portfolio/positions`** — the payload has cost + realised
  P&L but not a current mark. cost_basis from `market_exposure_dollars`,
  realised from `realized_pnl_dollars`, fees from `fees_paid_dollars`.
- **Mark-to-market via a PUBLIC market-data overlay** (no auth). `fetch_market_prices()`
  hits `https://api.elections.kalshi.com/trade-api/v2/markets?tickers=…` for the
  held tickers, reads `last_price` (fallback mid of `yes_bid`/`yes_ask`),
  converts Kalshi CENTS → probability (`/100`), and `to_canonical(market_prices=…)`
  applies it: a YES contract values at `yes_prob`, a NO contract at
  `(1 − yes_prob)`; `value_base = qty × side_price`, `unrealized = value − cost`.
  Best-effort — unreachable / unpriced markets stay cost-only (`value_base=0`).
  Fetch path verified reachable + the cents→probability + YES/NO valuation are
  fixture-proven; NOT yet observed against a live-priced market (the accessible
  public host returned thin/zero `last_price` in sampling — Kalshi liquidity).
- **Cash**: `balance_dollars` (with an integer-cents `balance` fallback for
  older payloads → /100).
- **CredentialsMissing is a RuntimeError, never sys.exit** (same fix as
  sq-robinhood/sq-degiro) so the aggregated view downgrades just this broker.

## Honest gaps (also in manifest.yaml)
- no_history: `/portfolio/settlements` exposes resolved-market realised P&L +
  the per-YES `value` (settlement_value) but isn't folded into a canonical
  Transaction ledger yet → no TWR/drawdown for Kalshi.
- no_asof (follows from no_history).
- no_spot_price → value_base=0 until a /markets overlay.
- execution not implemented (read-only; separate higher trust tier).
- pending a real-credentials run (adapter fixture-proven; live signing per
  verified docs, not yet run against a real Kalshi account).
