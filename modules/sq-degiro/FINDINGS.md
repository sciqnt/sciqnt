# Degiro unit — findings, quirks & conformance notes

Living log for the Degiro source unit (`src/sq_degiro/pnl.py` for the CSV P&L
compute, `canonical.py` for the schema adapter, `live.py` for the API flavour).
**Update this the moment a quirk, caveat, or conformance result is discovered** — it's
the `known_quirks` + conformance section of this unit's eventual manifest/SKILL.md.

## Inputs (CSV exports)
- **transactions.csv** — trades. Cols: Date, Time, Product, ISIN, Reference exchange, Venue,
  Quantity, Price, *(price ccy)*, Local value, *(local ccy)*, Value EUR, Exchange rate,
  AutoFX Fee, Transaction fees EUR, **Total EUR**, Order ID.
- **account.csv** — cash ledger. Cols: Date, Time, Value date, Product, ISIN, Description,
  FX, Change *(ccy, amount)*, Balance *(ccy, amount)*, Order Id. Rows newest-first.

## Resolved issues

- **Fees now flow through `fold_position` → cent-perfect reconciliation with
  pnl.py (resolved).** `Position` gained a `realized_fees_base` field
  (≤ 0); `Lot` carries `fee_per_unit_local` so partial sells release a
  proportional buy-side fee; `_apply_sell` also deducts the sell's own fee.
  Derived `realized_pl_base = product + currency + fees` — now matches
  what a broker shows as "Total P/L". Coupled with a fix to `_derive_fx`
  (which used to derive fx from `|amount|/(qty×price)` for same-currency
  rows — wrong when `amount` is fees-inclusive, since the derived fx then
  drifts away from 1 by exactly the fee ratio, double-counting fees), the
  canonical event-sourcing path now reconciles to pnl.py's direct cash
  summation to the cent on every closed position:

      isin           pnl.py        fold       diff
      DE000A0S9GB0   235.82        235.82     0.00  OK   (4GLD)
      GB00B43G0577   -30.37        -30.38    -0.01  OK   (PMO)
      GB00BLGYGY88   -17.47        -17.48    -0.01  OK   (HBR)
      GB00BMBVGQ36   -50.27        -50.26    +0.01  OK   (HBR non-trad)
      IE0031442068   1386.57       1386.56   -0.01  OK   (IUSA)
      IE00BD1F4M44   -743.81       -743.81    0.00  OK   (QDVI)
      IE00BYXPSP02   -24.87        -24.86    +0.01  OK   (IBTA)
      US0378331005   123.36         123.36    0.00  OK   (AAPL)
      US12618T1051   422.02         422.02    0.00  OK   (CRAI)
      US29977A1051    20.17          20.16   -0.01  OK   (EVR)
      US88160R1014   -74.61         -74.62   -0.01  OK   (TSLA)
      TOTAL          1246.54       1246.51   -0.03   (Decimal rounding)



- **fx_rate direction mismatch in `to_canonical_transactions` (resolved).**
  Degiro's CSV "Exchange rate" column is in the broker's convention:
  `amount_local = amount_base × rate` — so a GBX-priced row settled in EUR
  with rate `86.24` means 1 EUR = 86.24 GBX. Our canonical convention is the
  inverse (`fx_rate` = how many amount-ccy units per ONE instrument-ccy
  unit, i.e. 0.01159 EUR per GBX). The adapter previously wrote the CSV
  value verbatim into `Transaction.fx_rate`; `fold_position` then
  multiplied `price × fx_rate` and over-counted by `fx² ≈ 7,400×` for GBX
  rows, producing -€169k / -€147k / -€256k realized P/L on Premier Oil /
  Harbour Energy / HBR-non-tradeable. After inversion at the adapter
  boundary, per-instrument realized P/L matches Degiro's web view to within
  fees (+€1,296 total realized vs ~+€1,488 from Degiro screen; ~€200 gap
  is fees, since `fold_position.realized_pl_base` is fee-exclusive by
  design). Regression test in `test_csv_canonical.py::TestCrossCurrencyFx
  Direction` pins the inversion + the end-to-end fold.

  **Originally misdiagnosed as a corporate-action problem** because the
  Premier Oil → Harbour Energy merger pair (same date, opposite-sign qty,
  matching EUR amounts) is plausibly where one would expect lot-basis to
  go wrong. But the actual CSV gives non-zero `Total EUR` on each side of
  the merger (the value at merger), so the basis transfers naturally
  through the merger rows without special handling — provided fx is in
  the right direction. A future cleaner model could still distinguish
  `MERGER`/`SPIN_OFF` from plain `BUY`/`SELL` for audit clarity, but the
  numbers are now correct without it.

## Quirks (load-bearing — get these wrong and numbers break)
1. **Cash-sweep to flatexDEGIRO Bank (NLFLATEXACNT) = INTERNAL transfer.** Idle cash is swept to
   a separate bank sub-account and back. Recorded *asymmetrically*: one leg carries an amount
   ("Degiro Cash Sweep Transfer"), the matching leg is descriptive with an empty Change
   ("Levantamentos da sua Conta Caixa na flatexDEGIRO Bank SE"). A naive sum double-counts these.
   **Must net out for reconciliation** (~€9,717 across this dataset). Detect: desc contains
   "cash sweep" OR product == "FLATEX EURO BANKACCOUNT".
2. **Dividends & interest are paid in the security's currency (USD/GBP), not EUR.** An EUR-only
   categoriser silently misses them (this caused a €188 Total-P/L gap). Handle currency-agnostically
   and convert. Withholding tax row = "Imposto sobre dividendo" (negative). Gross div = "Dividendo".
3. **`Total EUR` (transactions) is the all-in EUR cash impact** = Value EUR + AutoFX Fee +
   transaction fees. For a fully-closed instrument, realized P&L (EUR, fees incl.) = sum of its
   Total EUR rows — no FIFO needed when net qty == 0.
4. **Corporate actions are encoded as transactions.** E.g. Tesla 3:1 split (25-08-2022) = sell 1
   @ 891.29 + buy 3 @ 297.10, net €0 cash, quantity change only. Summing Total EUR handles cash
   correctly; quantity tracking must follow the split.
5. **FX legs** appear in account.csv as "Crédito de divisa" (+foreign) / "Levantamento de divisa"
   (−EUR). Beware categoriser ordering: match "divisa" (FX) BEFORE "levantamento" (withdrawal),
   else FX conversions get mis-bucketed as withdrawals.
6. **Per-currency cash balances interleaved** in the Balance column (Degiro trading cash vs flatex
   bank). Reconcile by summing non-internal Changes per currency vs the latest Balance per currency.
7. **Descriptions are Portuguese** ("Compra"/"Venda"/"Dividendo"/"Comissões de transação"/
   "Custo de Conectividade"/"flatex Deposit"). Categoriser keys off these.
8. **Number format:** comma decimal, optional dot thousands, quoted; sometimes space thousands in
   *description* strings (e.g. "11 159,34 EUR"). Dates DD-MM-YYYY.
9. **transactions.csv column 10 is NOT the cash-leg currency** (2026-06-11). The two unnamed
   currency columns (8 and 10) BOTH carry the LOCAL listing currency (GBX for LSE, USD for
   USD funds); `Value EUR` / `Total EUR` are always account-base EUR with no currency column
   of their own. Labelling the EUR cash amount with col 10 broke every downstream FX join —
   GBX "amounts" hit the income summary unconverted, USD-labelled EUR fees converted as if
   dollars. The adapter now hardcodes the cash leg as EUR. (Found the day the income block
   first rendered — a new consumer is a conformance probe.)
10. **Order ID sits at column 17 in real exports, not 16.** The header says col 16, but data
   rows carry an empty field there and the uuid at 17 (trailing-comma artifact). Reading col
   16 only meant EVERY real transaction silently fell back to synthetic `row-N` ids — the
   broker-stable ids the docstring promised never materialised. Adapter reads 16 then 17.

## Caveats
- **Transactions window may be shorter than the account statement** (here tx 2021–2025 vs account
  2020–2026). Validate: no negative net positions (a negative net = buys before the export window
  → incomplete history).
- **Price source (Yahoo)** is unofficial and ~15-min delayed; fine for personal unrealized.
- **Dividend EUR conversion currently uses *current* FX, not historical** → small FX-timing error
  (see conformance below). A historical-FX source unit would fix it.

## Conformance results
- **Cash reconciliation:** after netting internal sweeps, computed cash matches Degiro's ending
  balance to ≤ €0.01 in EUR, GBP, USD. ✓ (cent drift = per-row rounding over 526 rows)
- **Validated vs live Degiro screen (2026-05-28):** Balance €10,503.78, Portfolio(open bond)
  €10,348.11, EUR cash €155.67 — all match **to the cent** (≤€0.39 live-price drift).
- **Total P/L:** Degiro €624.08. Realized €1,246.54 + unrealized −€810.84 = €435.70 (€188 short);
  adding net dividends (€231.85) + interest (−€16.60) → €650.95, **within €26.87**. Residual =
  FX-timing on dividends + Degiro's likely *money-weighted* (current − net deposits) Total-P/L
  definition. These should become explicit conformance test cases.

## LIVE (api) flavour — `live.py` via `degiro-connector`
Unofficial, reverse-engineered, **against Degiro ToS** — at-your-own-risk, read-only, local creds only. Complements CSV (history) with the live snapshot (current positions/cash).
- **`degiro-connector` ships UNDECLARED deps:** it imports `wrapt` and `google.protobuf` but lists neither. It also uses the **old `wrapt` API** (`from wrapt.decorators import synchronized`) which only exists in **`wrapt<2`** (2.x moved it). Working install: `pip install degiro-connector "wrapt<2" protobuf`. Pinned in `pyproject.toml [live]`.
- **Auth:** `Credentials(username, password, totp_secret_key)`; `int_account` fetched post-connect via `get_client_details()["data"]["intAccount"]`. `totp_secret_key` = the 32-char setup key from enabling 2FA (not the 6-digit code).
- **Credentials are handled by the shared substrate `core/sq_secrets`, not here** (extracted 2026-05-28 after self-reflection — generic credential code doesn't belong in one connector). sq-degiro only *declares its fields* (`setup_creds.py`: username/password/totp_secret) and reads via `sq_secrets.get_secret`. Mechanism: native macOS hidden dialog → OS Keychain (`keyring`, backend `keyring.backends.macOS` confirmed), keychain-first with bundle-local `.env` fallback; secret goes dialog → keychain only (never transcript, even under `!`). macOS may prompt "allow keychain access" on first read → Always Allow.
- **Fetch:** `get_update(request_list=[PORTFOLIO, CASHFUNDS, TOTALPORTFOLIO], raw=True)`. Build with `Update.RequestList().values.extend([Update.Request(option=Update.Option.PORTFOLIO, last_updated=0), …])`. Raw response: each position is `{"value":[{"name":…,"value":…},…]}` (flatten); keep `positionType == "PRODUCT"`.
- **Env caveat:** macOS system Python 3.9 + LibreSSL emits a urllib3 `NotOpenSSLWarning` (harmless so far; watch for TLS issues on live HTTPS).
- **Status: v1, UNTESTED with real creds** — field mapping (position `value` currency, total-portfolio keys, product-name resolution via `get_products_info`) to be confirmed on the first real run, then refined here.
- **TOTP setup-key paste quirks (2026-05-29):** Degiro displays the 32-char base32 setup key in space-grouped or hyphenated form; pasting as-is leaves whitespace/hyphens that make `degiro-connector` raise `binascii.Error: Incorrect padding` inside `base64.b32decode` at connect time. Now mitigated *at setup time*: the `totp_secret` field in `setup_creds.py` declares `normalize` (strip whitespace/hyphens, uppercase) + `validate` (base32 charset + length % 8 == 0) hooks on `prompt_and_store`. Recovery for an already-stored bad value: `sciqnt degiro fix-totp` — inspects + auto-normalizes the `.env` value without ever printing it.
- **degiro-connector 3.x major restructure (2026-05-30):** v3.0.x removed `degiro_connector.trading.models.trading_pb2` (protobuf modules) and split everything into Pydantic modules — `credentials` (Credentials), `account` (UpdateRequest, UpdateOption, AccountUpdate). The TradingAPI is now action-based: `API(credentials=…); api.setup_all_actions(); api.connect()`. Without `setup_all_actions()` you get `AttributeError: 'API' object has no attribute 'connect'`. We surfaced this when migrating the venv to Homebrew Python 3.13 (which installed 3.0.35 vs the older system Python's 2.x). New shape applied across `live.py`, `probe.py`, and `setup_creds.py`'s `_verify_degiro`. **Self-healing-connector exemplar:** exactly the kind of upstream churn sciqnt's generator + conformance harness is meant to absorb automatically; recorded here for the eventual generator regen test.
- **Setup-key value mismatches (2026-05-30):** even a syntactically valid 32-char base32 string may be the *wrong* key — `degiro-connector` then surfaces a **400 Client Error from `…/login/secure/login/totp`**. The setup-time `verify=_verify_degiro` catches this and stores nothing. Use `sciqnt degiro probe` to isolate which value is wrong: it bypasses the stored TOTP secret and lets you log in with a fresh 6-digit code from your authenticator app — success there proves username/password are fine and points the finger at the stored setup key (regenerate 2FA on Degiro to get a fresh one). Failure of probe points at password/username/clock-skew. Probe stores nothing.

## Conformance suite (added 2026-05-28)
`tests/test_pnl.py` + synthetic `tests/fixtures/` lock in the money-core on made-up data
(7 tests): European number parser, date parser, realized P&L on a closed position
(buy 10 @10, sell 10 @12 → +€20.00), open-position detection, multi-currency cash
reconciliation, **cash-sweep netting** (the +€30 internal sweep must be excluded — if
included, reconciliation would silently fail), and EUR deposit categorisation. Run via
`./run_tests.sh` at repo root. Now backs the unit's `status: proof` with actual checks
(was: "no conformance suite backs any status", flagged by the maintenance audit).

Also this turn: **`analyze()` refactored into `compute()` (returns a structured dict) +
`report()` (prints)**. Examples and tests can now consume real computed values instead
of pasted literals — the structural enabler for H1 (examples' hardcoded money figures).
Real-data regression check: unchanged (realized €1,246.54, reconciliation passes to the
cent in EUR/GBP/USD).

## Open issues / TODO (each a real gap surfaced by real data)
- [ ] **Live flavour:** first real-creds run → confirm/refine response field mapping; resolve productId→name; reconcile live positions against the CSV-derived ones.
- [ ] **Rewire examples to consume `compute()`** instead of hardcoding realized/cost/qty (H1 from the audit) — unblocked by the refactor above; treated as a reviewed change since it touches money values, must re-verify against the broker.
- [ ] Fold currency-agnostic **dividends + WHT + interest** into `degiro_pnl.py` compute (closes
      most of the €26.87).
- [ ] **Historical-FX source unit** (rate per dividend/trade date) to close the FX-timing residual.
- [ ] `degiro_pnl.py` should **emit open positions** (qty, cost, currency, venue) so
      `portfolio_value.py` isn't hardcoded.
- [ ] **Derive the Yahoo venue suffix** from the Degiro venue/exchange column instead of hardcoded `.L`.
- [ ] Turn the reconciliation + cash-sweep + dividend-currency rules into a **conformance suite**.

## CSV history & multi-account (2026-06-04)
- **The flat→per-account migration trap:** the legacy single-account layout reads
  CSVs from flat `data/degiro/`; per-account layout is `data/degiro/<account>/`.
  The transitional fallback (named account reads the flat dir) self-disables the
  moment a SECOND account is connected — correct (no cross-account inheritance),
  but it used to degrade SILENTLY: all history features (realised P/L, XIRR, TWR,
  drawdown, daily view, --asof) just showed “—”. Now surfaced: the summary tab
  prints a ⚠ per account with the exact drop-dir (`history_dir(account)`, public),
  `setup` creates the dir + prints the hint, and the daily tab flags coverage.
- **Exports go stale:** the CSVs are a snapshot of the past — rows after the
  export date are that state marked-to-market (missed buys/sells/flows), so the
  daily series can diverge from the live headline. The summary + daily tabs flag
  an export ending >7 days ago; the fix is always “re-export the CSVs”.

## API history sync + open cash-ledger reconciliation gap (2026-06-04)
- **`sciqnt degiro sync [--account X]`** downloads the SAME two CSV reports the
  web UI exports (`/portfolio-reports/secure/v3/{transactionReport,cashAccountReport}/csv`,
  `lang=en`) over the authenticated degiro-connector session. MUST reuse
  `api.session_storage.session` — a bare `requests.Session` is 503-blocked by
  Degiro's WAF (myracloud). Validated by the real parser BEFORE overwriting
  (refuses empty/shrunk downloads); previous files kept as `.bak`. The platform
  auto-syncs on ^R/--fresh via the `sync_history` capability (6h mtime gate).
- **Report localisation:** headers follow the report `lang` param (en), but row
  DESCRIPTIONS follow the account locale (this account: Portuguese —
  "Levantamento/Crédito de divisa" = AutoFX legs, "Dividendo", …). The parser
  maps these; a new locale = new description strings to map.
- **RESOLVED (2026-06-04) — cash-ledger fold ≠ live cash.** CSV-fold cash buckets on
  a real account: large positive EUR / large negative USD / small negative GBX
  (composite ≈ +€1.7k at today's FX) vs a live balance of ~€156. Position qty
  reconciles exactly (100 ✓);
  the cash divergence is the per-currency fold of account.csv — prime suspects:
  the 80 "Degiro Cash Sweep Transfer" rows (flatex money-market sweep) and/or
  AutoFX leg signs, plus converting residual foreign buckets at TODAY's rate
  instead of the executed rate. Affects the DAILY series' cash component (and
  its net worth) — positions/qty and realised P/L are unaffected. Needs the
  cent-level, test-driven reconciliation treatment; do NOT quick-fix.
- **RESOLVED (2026-06-04) — daily MTM vs Degiro price:** Yahoo close for IE00BGSF1X88 values
  the position ~7% above Degiro's own live price (€11,128 vs €10,396) — likely
  the OpenFIGI-picked listing differs from the Degiro listing. Overlay is
  declared best-effort; worth pinning the listing per instrument.

## Cash-ledger resolution (2026-06-04)
- **Cash LEVELS now come from the account.csv ledger itself** —
  `canonical.account_csv_cash_ledger`: every Change row EXCEPT internal mirrors
  (`Degiro Cash Sweep Transfer` descriptions; `flatex euro bankaccount` product
  rows). Order-Id trade legs and AutoFX leg pairs ARE included. Validated on the
  real export: EUR 155.68 vs live/stated 155.67 and USD +0.01 vs 0.00 — the
  residual cent is IN THE BROKER'S OWN FILE (their Change column vs their own
  stated Balance), not our arithmetic. Conformance tolerance: ±0.01/ccy.
- **Why not the canonical fold:** the Transaction stream deliberately carries
  trade consideration in LOCAL ccy (positions/realised-P&L truth) and skips
  Order-Id account rows — a topology that can't also reconcile multi-ccy cash
  (it produced EUR +10,945 / USD −10,693 / GBX −98 phantom buckets). Positions
  fold over transactions; CASH sums the ledger. Each reconciles against its own
  oracle. `fold_cash_balances` remains the fallback when no account.csv exists.
- The CSV's intra-day row order does NOT match Degiro's posting order (stated
  Balance jumps around within same-minute batches) — fine for end-of-day PIT
  sums, but never try to per-row-replay the Balance column.

## MTM overlay resolution (2026-06-04)
- The ~7% "price gap" was NOT a wrong listing — the overlay wasn't pricing at
  all: the CSV-fold snapshots carry SPARSE instruments (ISIN only, no ticker),
  so `overlay_prices` silently kept the cost-basis surrogate, which then moved
  only with FX (the daily P/L was pure EURUSD noise). Two-layer fix in the
  platform: (1) the daily + TWR series now ENRICH sparse instruments from the
  in-scope live snapshot metadata; (2) `_enrich_historical_metadata` also fills
  a missing `yahoo_ticker` via OpenFIGI even for live-known instruments —
  Degiro's bare exchange ticker (e.g. `IB01`) is not a valid Yahoo symbol.
  Verified: IB01.L $120.56 → ECB at-date → €103.9x ≈ Degiro's own €103.96; the
  daily net worth now tracks the live headline within ~0.1% and day P/L shows
  the ETF's real accrual instead of FX noise.
- **Staleness is the FILE's age, not the last transaction's**: a freshly synced
  export whose last activity is months old is a QUIET account, not a stale
  file. `_export_age_days` (via the `history_dir` capability) now gates the
  ⚠ warnings; the last-txn date remains the fallback signal.
- **One login per account, persisted — never `connect()` per fetch.** Every
  fresh `connect()` is a new login: Degiro mails a login alert each time, and
  one ^R used to fire several (live fetch + history sync × accounts). Now
  `sq_degiro.connected_api(account)` is the only way to an authenticated API:
  in-process singleton + session id persisted via `sq_secrets.save_session`
  (0600, under the config home), validated with a cheap `get_client_details()`
  on every borrow (doubles as keep-alive) and self-healing — a server-side
  rejection (sessions die after ~30 min idle) triggers exactly ONE fresh
  login and re-persists. `reset_api(account)` force-drops memory + disk.
  Both `live.fetch_live` and `history_sync._default_fetch` borrow from it —
  a sync must never be an extra login.
- **Degiro's API login has NO device-recognition handle** (verified in
  degiro-connector's `ActionConnect`: the login payload is username +
  password + TOTP/in-app token only — no device token, no trust cookie).
  "Remember this device" doesn't exist for API logins, so the login-alert
  email is per-login and client-unsuppressible; the only lever is fewer
  logins (the persisted-session contract above → one per sitting, bounded
  by Degiro's ~30-min idle expiry). Contrast Robinhood, where the persisted
  `device_token` IS the remember-this-device handle.
- **In-app approval accounts (no TOTP key): status 12 `inAppTOTPNeeded` is a
  DANCE, not an error** — the login response carries an `inAppToken`, Degiro
  pushes a popup to the DEGIRO app, and the client must poll the `/in-app`
  login endpoint with that token until the user taps Yes. degiro-connector
  just raises on status 12 (and `logger.fatal`s the raw error dict to
  stderr — silence `logging.getLogger("degiro_connector")`). `sq_degiro.
  login(api)` completes the flow: set `credentials.in_app_token` (which
  routes the connector's next login to `/in-app`), poll every ~3 s, clear
  the token in a finally (it must never leak into the next login).
- **"Remember this device for 30 days" is a COOKIE.** Ticking it in the app
  popup makes the login response set a device-trust cookie in the HTTP jar;
  a fresh process with an empty jar is a stranger, so the popup re-fires
  every login no matter what the user ticked. `persist_session_state` /
  `_restore_session_state` round-trip the jar (expired cookies dropped)
  alongside the session id — that's what makes the checkbox real. This
  amends the earlier "no device-recognition handle" note: true for the
  TOTP login payload, but the in-app flow DOES have one, cookie-side.
## CLI boundary hardening + account-aware verbs (2026-06-11)
What was wrong (owner report: "sync and doctor seem to have no purpose, live
fails"):
- **Uncaught CredentialsMissing at the CLI boundary.** `sq-degiro live` ran
  `fetch_live()` with NO account → `_credentials(account=None)` → the legacy
  bare-key lookup. A user with only NAMED accounts (the registry at
  `~/.config/sciqnt/accounts.sq-degiro.json`) has no bare keys, so
  CredentialsMissing propagated as a RAW TRACEBACK out of `main()`. The
  exception class was designed to be caught (its whole docstring is about
  that) — the library path (aggregator) did; the bundle's own CLI didn't.
- **`live` was account-blind**: no `--account` flag at all, so a multi-account
  user couldn't reach any of their accounts from this entry point.
- **`sync` synced only the legacy unnamed account** unless you knew to pass
  `--account` — "no purpose" for a named-accounts user.
- **`doctor` with no subcommand just printed usage** — a doctor that doesn't
  examine anything.

New contracts (all in this bundle: `live.py`, `history_sync.py`, `doctor.py`,
`bin/sq-degiro`):
- **No raw tracebacks from any verb.** `live` catches CredentialsMissing and
  `sq_secrets.NeedsAction` → one friendly line (exit 1); any other exception
  → `fetch failed: <type>: <msg>` (exit 1). Same one-line discipline in the
  sync loop.
- **`live [--account NAME]`** — account resolution via `_resolve_account`
  (pure, tested): flag wins; exactly one configured account auto-selects
  (including the legacy `[None]`); none → legacy lookup (friendly
  CredentialsMissing pointing at `sciqnt degiro setup`); several with no
  flag → `PICK_ACCOUNT` sentinel, which main() turns into an sq_tui
  `select_screen` picker at a TTY, or `configured accounts: A, B, C — pick
  one with --account` + **exit 2** when non-TTY (scripts must be explicit).
  The history tab now follows the picked account (`history_dir(account)`,
  not the flat legacy dir).
- **`sync` with no args syncs EVERY configured account** (`run_sync` loop,
  tested with a stubbed syncer): per-account progress lines, per-account
  outcome ("12 new rows (total 526, through …)" / "up to date" — the delta
  of parsed-transaction counts before/after, valid because each download is
  the full history), CredentialsMissing/NeedsAction on one account is a
  friendly line and the OTHERS still run; final one-line summary; exit 0 iff
  all synced. `--account NAME` restricts to one.
- **`doctor` (no subcommand) = read-only health check per account**
  (`doctor.py`): credentials present + which backend (keychain/.env, TOTP
  key vs in-app-approval note), persisted session age (">30 min = likely
  expired, next fetch logs in once"), history CSV presence + export age
  (>7 days → ⚠ re-sync hint). No network, no prompts, nothing stored.
  `probe` / `fix-totp` / `show-creds` unchanged underneath.
- Contracts pinned in `tests/test_cli_accounts.py` (synthetic
  AccountA/B/C names only).

- **While the in-app popup is UNANSWERED, `/in-app` answers status 3
  "badCredentials"** (observed live — it is NOT a credentials problem: the
  initial `/login` had just accepted that exact password, which is what
  status 12 means). During the polling phase treat 3 and 12 both as
  "pending"; status 3 only means bad credentials on the INITIAL login.
  Also: degiro-connector's leak is `logger.fatal` == CRITICAL, so muting
  needs `setLevel(logging.CRITICAL + 1)` — plain CRITICAL still prints.
