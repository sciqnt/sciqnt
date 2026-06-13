"""sq-degiro — Degiro source unit.

Public surface (the cross-broker contract — every connector implements
the subset it can):

  * `snapshot(asof=None)`  — current live state, OR a CSV-derived PIT
                             snapshot when asof is set
  * `snapshots_at(asof_dates)` — batched historical snapshots in one
                                 chronological pass (much faster than
                                 calling snapshot(asof=X) N times for
                                 TWR/drawdown analytics)
  * `load_history()`       — full canonical Transaction stream from
                             CSV exports (None if no CSVs present)

All three are pure of any UI / rendering concern — the aggregated
landing view in `sq_platform.aggregated` calls them, the per-broker
TUI in `sq_degiro.live` reaches lower-level dialect-aware helpers in
`sq_degiro.canonical` for richer broker-native detail.

Also:
  * `analyze()` — CSV-driven realised P&L + cash reconciliation
    orchestrator (the per-broker drill-down report).
  * `canonical.*` — raw adapters (live API and CSV exports) into
    canonical types.
"""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import sq_secrets

from .pnl import analyze

SERVICE = "sq-degiro"
SECRET_KEYS = ["username", "password", "totp_secret"]
# key → .env fallback variable name. The canonical (key, env) manifest used by
# the `forget` flow to scrub BOTH backends (keychain + .env); kept here as the
# bundle's single source of truth (setup_creds.FIELDS / doctor mirror it).
SECRET_ENV = {"username": "DEGIRO_USERNAME", "password": "DEGIRO_PASSWORD",
              "totp_secret": "DEGIRO_TOTP_SECRET"}
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"   # bundle-local .env fallback

# ── Shared authenticated session (ONE login, not one per request) ───────
# Every fresh `api.connect()` is a brand-new login → Degiro mails the user a
# login alert each time, and a single refresh (live fetch + history sync ×
# accounts) used to fire several. So: one in-process API per account, plus
# the session id persisted via sq_secrets.save_session so the NEXT process
# resumes the same session instead of logging in again. Self-healing: the
# session is validated with a cheap get_client_details() on every borrow;
# if Degiro rejected it (expired ~30 min idle), we fall through to one fresh
# login and re-persist.
#
# COOKIES are part of the persisted state, not just the session id: accounts
# using Degiro's in-app approval get a "remember this device for 30 days"
# cookie when the user ticks it — throw the jar away (as a fresh process
# used to) and every login re-triggers the phone popup no matter what the
# user answered. Persisting the jar is what makes that checkbox real.
_APIS: dict = {}


def restore_device_cookies(api, account: Optional[str]):
    """Load ONLY the persisted cookie jar (the 30-day deviceToken trust)
    into a fresh API object — not the session id. The setup/verify path
    needs exactly this: it must run a REAL login to validate newly-typed
    credentials, but ride the device trust so the in-app popup stays a
    30-day event."""
    saved = sq_secrets.load_session(SERVICE, account=account)
    if not saved:
        return
    jar = api.session_storage.session.cookies
    for c in saved.get("cookies", ()):
        try:
            jar.set(c["name"], c["value"], domain=c.get("domain", ""),
                    path=c.get("path", "/"), expires=c.get("expires"),
                    secure=c.get("secure", False))
        except Exception:                                   # noqa: BLE001
            continue              # one bad cookie must not block the login


def _restore_session_state(api, account: Optional[str]):
    """Load the persisted session id + cookie jar into a fresh API object."""
    saved = sq_secrets.load_session(SERVICE, account=account)
    if saved and saved.get("session_id"):
        api.connection_storage.session_id = saved["session_id"]
    restore_device_cookies(api, account)


def persist_session_state(api, account: Optional[str] = None):
    """Persist session id + cookie jar (drops already-expired cookies)."""
    import time as _time
    now = _time.time()
    cookies = [
        {"name": c.name, "value": c.value, "domain": c.domain,
         "path": c.path, "expires": c.expires, "secure": c.secure}
        for c in api.session_storage.session.cookies
        if c.expires is None or c.expires > now
    ]
    sq_secrets.save_session(
        SERVICE,
        {"session_id": api.connection_storage.session_id, "cookies": cookies},
        account=account)


def login(api, *, notify=None, timeout: float = 120.0, poll: float = 3.0,
          wait_for_approval: bool = True):
    """`api.connect()` that COMPLETES Degiro's in-app approval flow.

    degiro-connector raises on `inAppTOTPNeeded` (status 12) instead of
    finishing the dance: the login response carries an `inAppToken`, the
    user gets a push in the DEGIRO app, and the client is expected to poll
    the `/in-app` login endpoint with that token until the user taps Yes.
    So: catch status 12, tell the user (via `notify`), set
    `credentials.in_app_token` (which routes the connector's next login to
    `/in-app`), and retry every `poll` seconds until approved or `timeout`.
    The "remember this device" cookie is persisted best-effort (see
    persist_session_state) but live evidence says Degiro still re-fires the
    popup on fresh logins — so the UI never promises 30 days; the session
    reuse (one login per sitting) is what actually reduces popups.

    `wait_for_approval`: True only for the EXPLICIT connect/reconnect flow,
    where a human just typed their password and is ready to tap the phone —
    we poll for the tap. False for every AUTOMATIC path (home load, ^R,
    aggregate, `live`/`sync` borrow): a direct/TOTP/device-cookie login still
    self-heals silently, but if Degiro demands an in-app tap we raise
    NeedsAction("approve") IMMEDIATELY instead of blocking the whole refresh
    for two minutes waiting on a phone (the hang this guards against).

    Returns the flow that authenticated: "direct" (password / TOTP / device
    cookie — no human in the loop) or "in-app" (the user had to tap Yes).
    Callers use it to suggest the more robust setup (a TOTP key) when the
    login needed a human."""
    import logging
    import time as _time

    from degiro_connector.core.exceptions import DeGiroConnectionError

    # Their login action logger.fatal()s the raw error dict straight to
    # stderr ("login_error:{'status': 12 …}") — noise in our UI, and the
    # pending-approval poll would repeat it every cycle. fatal == CRITICAL,
    # so the level must sit ABOVE CRITICAL to actually mute it.
    logging.getLogger("degiro_connector").setLevel(logging.CRITICAL + 1)

    def _status(exc):
        return getattr(getattr(exc, "error_details", None), "status", None)

    try:
        api.connect()
        return "direct"
    except DeGiroConnectionError as e:
        if _status(e) != 12:
            raise
        token = getattr(e.error_details, "in_app_token", None)
        if not token:
            raise

    creds = api.credentials
    creds.in_app_token = token
    if not wait_for_approval:
        # Automatic refresh: don't sit on a 2-minute phone-approval poll —
        # surface it fast so one stuck account can't hang the whole view.
        # State the SYMPTOM ("needs re-authentication") rather than prescribing
        # a fix — Degiro asked for an in-app tap, but that isn't always what
        # actually unblocks the account, and we don't want to pigeonhole the
        # user (or the agent) into one guessed remedy. The home recommends the
        # agent for exactly this; it gets the full error and can investigate.
        creds.in_app_token = None
        raise sq_secrets.NeedsAction("needs re-authentication", action="approve")
    if notify:
        notify("Open the DEGIRO app and tap 'Yes' to approve this login…")
    deadline = _time.monotonic() + timeout
    started = _time.monotonic()
    try:
        while True:
            _time.sleep(poll)         # give the user a beat BEFORE each poll
            try:
                api.connect()
                return "in-app"
            except DeGiroConnectionError as e:
                # Pending-approval answers, verified against a live account:
                #   status 12 — in-app still required (token may rotate)
                #   status 3  — "badCredentials" — Degiro's actual reply from
                #               /in-app while the popup is UNANSWERED. Not a
                #               credentials problem: the initial /login just
                #               accepted this exact password (that's what
                #               status 12 means), so during the polling phase
                #               status 3 = "not approved yet", keep waiting.
                st = _status(e)
                if st not in (3, 12):            # a different failure → real
                    raise
                if st == 12:
                    fresh = getattr(e.error_details, "in_app_token", None)
                    if fresh:
                        creds.in_app_token = fresh
                waited = _time.monotonic() - started
                if _time.monotonic() >= deadline:
                    # NeedsAction (not TimeoutError): the platform knows how
                    # to render this — one plain ⚠ line naming what to do.
                    raise sq_secrets.NeedsAction(
                        "approve the login in the DEGIRO app, then refresh",
                        action="approve") from e
                if notify and waited > 10 and int(waited) % 15 < poll:
                    notify(f"still waiting for the in-app approval… "
                           f"({int(waited)}s, gives up at {int(timeout)}s)")
    finally:
        creds.in_app_token = None     # never leak into the NEXT login attempt


def _notify(msg):
    """Default in-app-approval notifier — sq_tui.status reaches both the
    terminal and the live TUI progress panel (via stream_output)."""
    try:
        import sq_tui
        sq_tui.status(msg)
    except Exception:                                       # noqa: BLE001
        print(msg)


def connected_api(account: Optional[str] = None):
    """Returns `(api, int_account)` — an authenticated degiro-connector API
    for `account`, reusing the persisted session when still valid."""
    from degiro_connector.trading.api import API as TradingAPI

    from sq_degiro.live import _credentials

    key = account or ""
    api = _APIS.get(key)
    if api is None:
        api = TradingAPI(credentials=_credentials(account))
        api.setup_all_actions()
        _restore_session_state(api, account)
        _APIS[key] = api

    # Borrow-time validation: cheap call doubles as a keep-alive. Two paths
    # land here — resumed-from-disk and long-lived in-process — and both
    # must self-heal the same way when the session has expired server-side.
    try:
        int_account = api.get_client_details()["data"]["intAccount"]
    except Exception:                                       # noqa: BLE001
        # ONE fresh login. This is the AUTOMATIC borrow path (snapshot / live /
        # sync / aggregate), never the interactive connect form — so it
        # self-heals a direct/TOTP/device-cookie session silently but does NOT
        # block on the in-app phone tap (wait_for_approval=False → fast
        # NeedsAction). The explicit `setup` flow runs its own login that does
        # wait. Without this, one account pending approval hangs every refresh.
        login(api, notify=_notify, wait_for_approval=False)
        int_account = api.get_client_details()["data"]["intAccount"]
        persist_session_state(api, account)
    api.credentials.int_account = int_account
    return api, int_account


def reset_api(account: Optional[str] = None):
    """Drop the cached + persisted session (next borrow logs in fresh)."""
    _APIS.pop(account or "", None)
    sq_secrets.clear_session(SERVICE, account=account)


def _resolve_cost_basis_method():
    """The user's configured lot-matching method as a `CostBasisMethod`
    (defaults to FIFO). Resolved HERE, at the adapter boundary, so the
    deterministic core (`sq_compute`) never imports config and stays pure.

    AVG covers the average-cost / ACB / Section-104-pool / Degiro-BEP family.
    See research/config-settings-cross-asset.md for the jurisdiction nuance and
    honest gaps (HIFO & UK same-day/30-day matching are not implemented)."""
    from sq_compute import CostBasisMethod
    import sq_config
    raw = sq_config.cost_basis_method(fallback="FIFO")
    try:
        return CostBasisMethod(raw)
    except ValueError:
        return CostBasisMethod.FIFO


def accounts():
    """Return the user's configured Degiro account names.

    `[None]` is the legacy single-account signal — credentials stored
    under bare keychain keys (`sq-degiro:username` etc) without an
    account qualifier. Once the user calls `setup --account NAME`, the
    registered name appears here and the dispatcher iterates accounts.

    A configured list co-exists with legacy: if both unqualified creds
    AND named accounts are present, both appear (legacy as `None`,
    named explicitly). The dispatcher renders the unqualified entry as
    just "degiro" and named ones as "degiro:NAME".
    """
    named = sq_secrets.list_accounts(SERVICE)
    # "Legacy unqualified creds exist?" — check BOTH backends the live path
    # reads from: the OS keychain AND the bundle .env fallback (load it so a
    # keychain-less / SSH setup still counts as connected). Without the
    # env-var fallback here, an .env-configured user would wrongly show as
    # "not connected".
    sq_secrets.load_dotenv(_ENV_FILE)
    legacy_user = sq_secrets.get_secret(SERVICE, "username", "DEGIRO_USERNAME")
    out = []
    if legacy_user:
        out.append(None)
    out.extend(named)
    # Empty == this broker has NO account connected yet (a normal state, not
    # an error). The dispatcher then lists it as "available to connect"
    # rather than fetching it and surfacing a CredentialsMissing error.
    return out


def snapshot(asof: Optional[datetime] = None, *, account: Optional[str] = None):
    """Return a canonical `PortfolioSnapshot` for this broker.

    `asof=None` (default) → current live state from Degiro's API,
                            ENRICHED with CSV-fold realised P/L when CSVs
                            are present (see "CSV enrichment" below).
    `asof=<datetime>`     → PIT snapshot computed entirely from CSV
                            history (the live API has no historical
                            query). Raises if no CSVs are present.

    ── CSV enrichment (live path) ────────────────────────────────────────
    Degiro's live API does NOT expose per-position fees, so the raw
    `to_canonical()` snapshot has `realized_fees_base = 0` everywhere.
    This understates the realised P/L of every closed position by the
    sum of buy + sell fees on that instrument. When the canonical CSV
    exports are at `data/degiro/`, we fold them via `sq_compute.
    fold_position` (fees-complete) and OVERWRITE the realised P/L
    decomposition on each live Position:

        realized_product_pl_base
        realized_currency_pl_base
        realized_fees_base   ← was 0; now the true fee allocation

    cost_basis_base / break_even_price_local / value_base / unrealised_*
    keep the live API's values — it's authoritative for currently-open
    lots and freshest on quantity. The result: aggregated realised P/L
    matches `tax_lots()` sum cent-for-cent — pinned by tests.

    Honest gap: if CSVs are absent (new install), this enrichment is
    skipped and the snapshot carries the live API's fee-exclusive
    realised P/L (overstated). The summary banner labels the
    enrichment source so users see when CSV-truthful numbers are
    showing."""
    if asof is not None:
        return _historical_snapshot(asof, account=account)
    from .canonical import to_canonical
    from .live import fetch_live
    raw_update, raw_products, base_ccy, int_account, _ = fetch_live(account=account)
    if not base_ccy:
        raise RuntimeError(
            "Could not determine Degiro account base currency — set one via "
            "`sciqnt config set` or rerun to retry discovery."
        )
    snap = to_canonical(raw_update, raw_products, base_ccy, int_account)

    # Enrich realised P/L from CSV history when available.
    txns = load_history(account=account)
    if txns:
        snap = _enrich_realized_from_csv(snap, txns, base_ccy)
    return snap


def _enrich_realized_from_csv(snap, txns, base_ccy):
    """Patch each live Position's realised P/L decomposition with the
    fees-complete value from `sq_compute.fold_position` over the CSV
    transaction stream. Live API still wins on quantity / value /
    unrealised (it's freshest); only the realised portion is swapped.

    Both the live `to_canonical` and CSV `to_canonical_transactions`
    paths produce ISIN-form instrument_ids (`degiro:isin:<ISIN>`), and
    `to_canonical` collapses any Degiro multi-productId splits on the
    same ISIN into a single Position before getting here — so the join
    is one-to-one on instrument_id, no dedup needed.

    Returns a new PortfolioSnapshot — never mutates the input."""
    from sq_compute import fold_position

    by_inst: dict[str, list] = defaultdict(list)
    for t in txns:
        if t.instrument_id is None:
            continue
        by_inst[t.instrument_id].append(t)

    patched_positions = []
    for pos in snap.positions:
        inst_txns = by_inst.get(pos.instrument_id)
        if not inst_txns:
            patched_positions.append(pos)
            continue
        # CSV transactions carry `account_id="degiro"` (the bundle's slug)
        # while the live snapshot has `account_id=<intAccount>` (Degiro's
        # numeric id). fold_position filters by account_id, so we retag
        # the CSV stream to the live account before folding.
        retagged = [t.model_copy(update={"account_id": pos.account_id})
                    for t in inst_txns]
        folded = fold_position(
            account_id=pos.account_id,
            instrument_id=pos.instrument_id,
            base_currency=base_ccy,
            transactions=retagged,
            method=_resolve_cost_basis_method(),
        )
        # Only realised P/L is patched. cost_basis_base / BEP / value /
        # unrealised come from the live API (freshest, authoritative for
        # currently-open lots). Fold's realised is what we want because
        # the live API path zeros realized_fees_base by construction.
        patched_positions.append(pos.model_copy(update={
            "realized_product_pl_base":  folded.realized_product_pl_base,
            "realized_currency_pl_base": folded.realized_currency_pl_base,
            "realized_fees_base":        folded.realized_fees_base,
        }))

    return snap.model_copy(update={"positions": patched_positions})


def _historical_snapshot(asof: datetime, *, account: Optional[str] = None):
    """Build a CSV-derived PortfolioSnapshot at `asof`.

    Honest-gap declaration: instrument metadata in the historical snapshot
    is sparse — we have ISIN from each Transaction but not `name` /
    `asset_class` / `listing_currency` (those normally come from the
    live API's product-info call). All instruments are tagged
    `AssetClass.OTHER` and `listing_currency` defaults to the account's
    base currency. The MONEY is correct (fold_position is the canonical
    truth); the asset-class breakdown is degraded."""
    from sq_compute import fold_cash_balances, fold_position
    from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                           PortfolioSnapshot)

    txns = load_history(account=account)
    if not txns:
        raise RuntimeError(
            "No CSV history found — place Degiro CSV exports under "
            "`data/degiro/` (account.csv + transactions.csv) to enable "
            "as-of views."
        )

    base_ccy = "EUR"   # Degiro is EUR-base by construction; CSVs reflect that
    # Account-id qualifier: see snapshots_at for rationale. The legacy
    # single-account path keeps the bare "degiro" id; named accounts get
    # "degiro:<name>" so the aggregator can tell them apart.
    acct_id = "degiro" if account is None else f"degiro:{account}"
    account_entity = Account(account_id=acct_id, broker="degiro",
                              base_currency=base_ccy)

    # Group instrument-bearing transactions
    by_inst: dict[str, list] = defaultdict(list)
    for t in txns:
        if t.instrument_id is None:
            continue
        if t.executed_at <= asof:
            by_inst[t.instrument_id].append(t)

    instruments = []
    positions   = []
    for inst_id in sorted(by_inst):
        # CSV transactions carry the bundle-default account_id ("degiro");
        # retag to the qualified id so fold_position's filter accepts them.
        inst_txns = (
            [t.model_copy(update={"account_id": acct_id})
             for t in by_inst[inst_id]]
            if acct_id != "degiro" else by_inst[inst_id]
        )
        pos = fold_position(
            account_id=acct_id, instrument_id=inst_id,
            base_currency=base_ccy, transactions=inst_txns, asof=asof,
            method=_resolve_cost_basis_method(),
        )
        # Historical "value at cost" — without a price-history overlay we
        # don't know the mark-to-market on `asof`, so the most honest
        # fallback for the value column is each open position's cost
        # basis. Closed positions still carry value_base=0 (correct).
        if pos.is_open and pos.value_base == 0 and pos.cost_basis_base > 0:
            pos = pos.model_copy(update={"value_base": pos.cost_basis_base})
        isin = inst_id.split(":isin:")[-1] if ":isin:" in inst_id else inst_id
        instruments.append(Instrument(
            instrument_id=inst_id,
            identifiers={"isin": isin, "broker:degiro": isin},
            name=f"ISIN {isin}",
            asset_class=AssetClass.OTHER,   # honest gap: not known from CSV
            listing_currency=base_ccy,       # honest gap: same as above
        ))
        positions.append(pos)

    # CASH: the account.csv LEDGER is the truth for cash levels (its cumulative
    # sum reproduces the broker's own stated running Balance to the cent — see
    # canonical.account_csv_cash_ledger). The canonical-txn fold stays as the
    # fallback for histories without an account.csv.
    ledger = _cash_ledger(account)
    if ledger is not None:
        cash_dict = _ledger_balances_at(ledger, asof)
    else:
        cash_txns = ([t.model_copy(update={"account_id": acct_id})
                      for t in txns] if acct_id != "degiro" else txns)
        cash_dict = fold_cash_balances(cash_txns, asof=asof)
    cash_balances = [
        CashBalance(account_id=acct_id, currency=ccy, amount=amount,
                    valid_at=asof, observed_at=datetime.now(asof.tzinfo))
        for ccy, amount in sorted(cash_dict.items())
        if amount != 0
    ]

    return PortfolioSnapshot(
        valid_at=asof,
        observed_at=datetime.now(asof.tzinfo),
        account=account_entity, instruments=instruments,
        positions=positions, cash_balances=cash_balances,
    )


# Module-level memoization of parsed CSV history. Keyed by (resolved
# data_dir, mtime of each CSV) so we re-parse if the user replaces the
# files mid-session. ~50ms CSV parse becomes a dict lookup; meaningful
# when the dispatcher's TWR build calls snapshot(asof=X) 50+ times.
_HISTORY_CACHE: dict = {}
_LEDGER_CACHE: dict = {}


def _cash_ledger(account: Optional[str] = None):
    """The account.csv CASH LEDGER entries (see canonical.account_csv_cash_ledger
    for why this — not the canonical Transaction fold — is the truth for cash
    LEVELS). Returns the [(executed_at, ccy, change)] list, or None when no
    account.csv is present (callers fall back to fold_cash_balances). Memoized
    per (path, mtime)."""
    path = _resolve_history_dir(account) / "account.csv"
    if not path.is_file():
        return None
    key = (str(path), path.stat().st_mtime)
    if key not in _LEDGER_CACHE:
        from .canonical import account_csv_cash_ledger
        _LEDGER_CACHE[key] = account_csv_cash_ledger(path)
    return _LEDGER_CACHE[key]


def _ledger_balances_at(ledger, asof) -> dict:
    """Per-currency cash from ledger entries executed ≤ asof. Pure Decimal."""
    from decimal import Decimal
    out: dict = {}
    for ts, ccy, amt in ledger:
        if ts <= asof:
            out[ccy] = out.get(ccy, Decimal("0")) + amt
    return out


def _ledger_balances_series(ledger, asof_dates) -> dict:
    """Single-pass per-currency cash at every checkpoint (sister of
    sq_compute.fold_cash_balances_series, over ledger entries)."""
    from decimal import Decimal
    sorted_asofs = sorted(set(asof_dates))
    entries = sorted(ledger, key=lambda e: e[0])
    out: dict = {}
    running: dict = {}
    idx = 0
    for ts, ccy, amt in entries:
        while idx < len(sorted_asofs) and sorted_asofs[idx] < ts:
            out[sorted_asofs[idx]] = dict(running)
            idx += 1
        running[ccy] = running.get(ccy, Decimal("0")) + amt
    while idx < len(sorted_asofs):
        out[sorted_asofs[idx]] = dict(running)
        idx += 1
    return out


def _resolve_history_dir(account: Optional[str], base: Optional[Path] = None) -> Path:
    """Resolve the CSV directory for `account`. Canonical layout is
    per-account: `<root>/data/degiro/<account>/`. The legacy single-account
    layout is the flat `<root>/data/degiro/`.

    Transitional fallback (the "new approach" migration): a NAMED account
    whose own subdir has no `transactions.csv` reads the flat layout — but
    ONLY when it is the *sole* connected account (`accounts() == [account]`).
    That guarantees one account can never inherit another account's history
    (no double-counting); the fallback self-disables the moment a second
    account exists. The read is non-destructive — CSVs are never moved.
    Multi-account users keep each account's exports in its own subdir.

    `base` overrides the data root (tests inject a tmp dir)."""
    if base is None:
        base = Path(__file__).resolve().parents[4] / "data" / "degiro"
    if not account:
        return base                                   # legacy single-account
    per_account = base / account
    if (per_account / "transactions.csv").is_file():
        return per_account
    if (base / "transactions.csv").is_file():
        try:
            accts = accounts()
        except Exception:                              # noqa: BLE001
            accts = []
        if accts == [account]:                         # the only account
            return base
    return per_account


def sync_history(account: Optional[str] = None, **kw):
    """PUBLIC capability: refresh this account's CSV history straight from
    Degiro over the authenticated API session — no manual web export. Validates
    with the real parser before overwriting; keeps `.bak`s. The platform
    auto-syncs stale history on a fresh (^R / --fresh) fetch when a bundle
    exposes this. See `history_sync.sync_history` for the safety contract."""
    from .history_sync import sync_history as _sync
    return _sync(account=account, **kw)


def history_dir(account: Optional[str] = None) -> Path:
    """PUBLIC: where this account's CSV exports belong (the dir `load_history`
    will read). The platform surfaces this in 'no history' warnings so a user
    knows exactly where to drop `transactions.csv` + `account.csv` — history
    must never degrade silently (the flat→per-account migration trap)."""
    return _resolve_history_dir(account)


def load_history(data_dir: Optional[Path] = None, *,
                 account: Optional[str] = None):
    """Parse this broker's CSV exports into a merged Transaction list.

    Returns the concatenation of trade transactions + account events, or
    None if no CSVs are present at `data_dir`.

    Default `data_dir` is resolved by `_resolve_history_dir(account)`:
      * `account=None` → `<project_root>/data/degiro/` (legacy single-account
        convention; preserved unchanged)
      * `account="<name>"` → `<project_root>/data/degiro/<name>/` so two
        accounts can keep their CSV exports separate. If that subdir has no
        CSVs but the flat `data/degiro/` does AND this is the only connected
        account, the flat layout is read as a transitional fallback (never
        for 2+ accounts — see `_resolve_history_dir`).

    The result is memoized per (data_dir, csv_mtime) for the lifetime of
    this Python process — safe because the canonical Transaction stream
    is a pure function of the CSVs on disk. Replacing either CSV with a
    fresh export invalidates the entry automatically (mtime changes).

    The returned list is the canonical Transaction stream — feed to
    `sq_compute.fold_position`, `sq_analytics.*`, `sq_analytics.tax_lots`,
    etc.
    """
    if data_dir is None:
        data_dir = _resolve_history_dir(account)
    data_dir = Path(data_dir).resolve()
    tx_csv = data_dir / "transactions.csv"
    ac_csv = data_dir / "account.csv"
    if not (tx_csv.is_file() and ac_csv.is_file()):
        return None
    cache_key = (
        str(data_dir),
        tx_csv.stat().st_mtime,
        ac_csv.stat().st_mtime,
    )
    cached = _HISTORY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    from .canonical import to_canonical_account_events, to_canonical_transactions
    trades = to_canonical_transactions(tx_csv, account_id="degiro")
    events = to_canonical_account_events(ac_csv, account_id="degiro")
    result = trades + events
    _HISTORY_CACHE[cache_key] = result
    return result


def snapshots_at(asof_dates, *, account: Optional[str] = None):
    """Return `{asof: PortfolioSnapshot}` for each requested historical
    date in a single chronological pass through the CSV history.

    Functionally equivalent to calling `snapshot(asof=X)` for each X,
    but uses `sq_compute.fold_position_series` and
    `fold_cash_balances_series` under the hood — O(N_transactions +
    N_asof_dates) instead of O(N_transactions × N_asof_dates). Built
    for the dispatcher's TWR / max-drawdown value-series construction,
    which samples at every cash-flow date.

    Raises if no CSV history is available (same contract as
    `snapshot(asof=X)`).
    """
    from sq_compute import fold_cash_balances_series, fold_position_series
    from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                           PortfolioSnapshot)

    txns = load_history(account=account)
    if not txns:
        raise RuntimeError(
            "No CSV history found — place Degiro CSV exports under "
            "`data/degiro/` (account.csv + transactions.csv) to enable "
            "historical snapshots."
        )

    base_ccy = "EUR"
    # Account-id is account-qualified so a multi-account aggregator can
    # tell IUSA-held-in-"work" apart from IUSA-held-in-"primary". For
    # the legacy single-account path (account=None) we keep the bare
    # "degiro" id so existing tests / cached snapshots still match.
    acct_id = "degiro" if account is None else f"degiro:{account}"
    account_entity = Account(account_id=acct_id, broker="degiro",
                              base_currency=base_ccy)
    asof_list = list(asof_dates)
    if not asof_list:
        return {}

    # Group transactions by instrument once, fold each instrument's
    # full history as a series across all requested dates.
    by_inst: dict[str, list] = defaultdict(list)
    for t in txns:
        if t.instrument_id is None:
            continue
        by_inst[t.instrument_id].append(t)

    # Per-instrument series → {asof: {inst_id: Position}}. Same
    # account_id retag as _historical_snapshot for the multi-account
    # case (CSV txns are tagged "degiro" by the adapter).
    per_instrument_series: dict[str, dict] = {}
    for inst_id, inst_txns_raw in by_inst.items():
        inst_txns = (
            [t.model_copy(update={"account_id": acct_id}) for t in inst_txns_raw]
            if acct_id != "degiro" else inst_txns_raw
        )
        per_instrument_series[inst_id] = fold_position_series(
            account_id=acct_id, instrument_id=inst_id,
            base_currency=base_ccy, transactions=inst_txns,
            asof_dates=asof_list,
            method=_resolve_cost_basis_method(),
        )

    # Cash balances series in a single pass — LEDGER-first (account.csv is the
    # truth for cash levels; see _cash_ledger), canonical-fold fallback.
    ledger = _cash_ledger(account)
    if ledger is not None:
        cash_series = _ledger_balances_series(ledger, asof_list)
    else:
        cash_txns = ([t.model_copy(update={"account_id": acct_id})
                      for t in txns] if acct_id != "degiro" else txns)
        cash_series = fold_cash_balances_series(cash_txns, asof_list)

    # Build sparse Instruments — historical view doesn't know
    # name / asset_class (those come from the live API). One per ISIN.
    sparse_instruments: dict[str, Instrument] = {}
    for inst_id in by_inst:
        isin = (inst_id.split(":isin:")[-1]
                if ":isin:" in inst_id else inst_id)
        sparse_instruments[inst_id] = Instrument(
            instrument_id=inst_id,
            identifiers={"isin": isin, "broker:degiro": isin},
            name=f"ISIN {isin}",
            asset_class=AssetClass.OTHER,
            listing_currency=base_ccy,
        )

    out: dict = {}
    for asof in sorted(set(asof_list)):
        observed_at = datetime.now(asof.tzinfo)
        positions = []
        for inst_id, series in per_instrument_series.items():
            pos = series.get(asof)
            if pos is None:
                continue
            # "Value at cost" surrogate (no price-history overlay here —
            # the dispatcher applies it as a separate stage, same as in
            # the singular snapshot(asof=X) path).
            if pos.is_open and pos.value_base == 0 and pos.cost_basis_base > 0:
                pos = pos.model_copy(update={"value_base": pos.cost_basis_base})
            positions.append(pos)

        cash_dict = cash_series.get(asof, {})
        cash_balances = [
            CashBalance(account_id=acct_id, currency=ccy, amount=amount,
                        valid_at=asof, observed_at=observed_at)
            for ccy, amount in sorted(cash_dict.items())
            if amount != 0
        ]

        out[asof] = PortfolioSnapshot(
            valid_at=asof,
            observed_at=observed_at,
            account=account_entity,
            instruments=list(sparse_instruments.values()),
            positions=positions,
            cash_balances=cash_balances,
        )
    return out


__all__ = ["analyze", "snapshot", "snapshots_at", "load_history",
           "accounts"]
