# sq-robinhood — findings & quirks

Second broker connector. Its purpose beyond "read my Robinhood account" is to
**prove the canonical schema is broker-agnostic in practice** — it reuses the
existing `STOCK` / `CRYPTO` asset classes with zero schema change, and folds
into the aggregated view alongside Degiro through the same
`snapshot()` / `accounts()` contract.

## Architecture
- `canonical.py` — ALL robin_stocks dialect knowledge; pure `to_canonical()`
  (raw dicts → `PortfolioSnapshot`). Fixture-tested, no network. 13 tests.
- `live.py` — I/O only: robin_stocks login (+ TOTP MFA via pyotp) and the HTTP
  calls; resolves instrument-URL→symbol and symbol→price (the extra calls that
  only the I/O layer can make), then hands raw shapes to `to_canonical()`.
- `__init__.py` — public contract: `snapshot(asof=None, *, account=None)` and
  `accounts()` (multi-account ready via `sq_secrets`).

## Verified field mappings (per research/, 2026-06-01)
`get_open_stock_positions()` → `quantity`, `average_buy_price`, `instrument`(URL).
Resolve URL via `get_instrument_by_url()` → `{symbol, simple_name, name}`; price
via `get_latest_price([symbol])`. Crypto via `get_crypto_positions()` (separate),
avg cost = `cost_bases[0].direct_cost_basis / direct_quantity`, price via
`get_crypto_quote(code).mark_price`. Cash from `load_account_profile()`:
`cash + uncleared_deposits`.

Canonical: `quantity→quantity`, `average_buy_price→break_even_price_local`,
`latest_price→last_price_local`, `qty×avg→cost_basis_base`, `qty×price→value_base`,
`(price−avg)×qty→unrealized_product_pl_base`. USD-base.

## Quirks / gotchas
- **Money fields are STRINGS.** robin_stocks returns money pre-formatted. We
  `Decimal(str(v))` everything and quantize derived values to 8dp. We
  deliberately use the RAW `get_open_stock_positions()` over `build_holdings()`,
  because build_holdings makes many extra HTTP calls AND has a known formatting
  bug: `equity_change` uses `'{0:2f}'` (min-width-2, ~6 decimals) not `'{0:.2f}'`.
  A `test_handles_six_decimal_strings_without_precision_pollution` test pins that
  even 6-decimal inputs stay conformance-clean.
- **Unofficial / ToS-grey / fragile.** robin_stocks reverse-engineers
  Robinhood's private API. Declared `risk: reverse-engineered` in the manifest;
  setup prints a warning. Breakage is expected on Robinhood-side changes.
- **No historical path.** Robinhood exposes no clean CSV export, and
  order-history reconstruction (`get_all_stock_orders` / `get_all_crypto_orders`
  → canonical Transactions) isn't wired yet. Consequences:
  `load_history()`/`snapshots_at()` are NOT implemented, `snapshot(asof=…)`
  raises, and TWR / drawdown / realised-P&L don't compute for Robinhood. The
  LIVE snapshot (positions, cash, unrealised P&L) works. Honest gap — fixing it
  is the obvious next step for this bundle.
- **Real-creds history probe (2026-06-11, user-zero's account):** all history
  endpoints reachable through the persisted session and ALL EMPTY —
  `get_all_stock_orders()` 0, `get_dividends()` 0, `get_all_crypto_orders()` 0
  (consistent with the live view: 0 positions, $0). `get_bank_transfers()`
  **403s** (`/ach/transfers/` — robin_stocks' endpoint looks stale; check the
  library version before relying on it for DEPOSIT/WITHDRAWAL flows).
  Consequence: there are no real payloads to pin fixtures from on this
  account, so the order→Transaction fold stays UNBUILT per the money-core
  rule (never implement money math against guessed shapes). Wire it the day
  the account has a real order to verify against — or a contributor with a
  traded account supplies anonymised payloads.
- **`CredentialsMissing` must be a RuntimeError, never `sys.exit`.** Bug found
  during integration: `_credentials()` originally `sys.exit`-ed when no creds
  were configured. `SystemExit` is a `BaseException`, so it slipped past the
  aggregated dispatcher's `except Exception` and killed the WHOLE view — a
  credential-less Robinhood blanked the working Degiro. Now both sq-robinhood
  and sq-degiro raise `CredentialsMissing(RuntimeError)`; the CLI `main()`
  catches it for a friendly message. Pinned by
  `test_aggregated_discovery.test_other_brokers_survive_one_brokers_failure`.

## Honest gaps (also in manifest.yaml)
- no_history, no_asof, no_realized_pnl (all follow from no order-history wiring)
- execution not implemented (read-only; separate higher trust tier)
- pending a real-credentials run (canonical adapter is fixture-proven; the live
  login + field shapes are per verified research, not yet run against a real account)

- **`store_session=False` = a "new device" email on EVERY fetch.** robin_stocks
  generates a fresh random `device_token` per login; without the pickle each
  fetch is a brand-new OAuth login from an unseen device, so Robinhood sends a
  new-device alert every time. With `store_session=True` + a sciqnt-owned
  `pickle_path` (`sq_secrets.session_dir`, 0700, under the config home) it
  (a) reuses the OAuth token across runs — zero login requests while valid —
  and (b) re-logins with the SAME persisted `device_token` when it expires, so
  sciqnt looks like one long-lived device. The pickle holds the access +
  refresh tokens: treat the dir as a bearer credential (never commit, never
  print).
