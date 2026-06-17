"""Aggregated landing view — the `sciqnt` (no args) entry point.

Discovers configured broker bundles, fetches each broker's
`PortfolioSnapshot`, hands the list to `sq_aggregator`, and renders a
tabbed UI of the merged result. With one broker this is structurally
the same view as `sq-degiro live` (positions / cash / exposure / P/L);
with N brokers each row carries its broker tag and totals fold across
the lot in the user's display currency.

Capability-based discovery: any bundle under `modules/sq-*` whose
Python package exposes a callable `snapshot` attribute is automatically
registered as a broker. There is no hard-coded broker list — adding a
connector is `mkdir + write snapshot()`, nothing else touches core.

A schema-level conformance gate runs on every snapshot BEFORE it lands
in the aggregator: snapshots with FK violations / precision pollution /
duplicate positions are surfaced in the "skipped" banner with the
specific violations, never silently folded.

This module is pure orchestration + rendering — the math is in
`sq_aggregator`, the data acquisition is in each bundle's `snapshot()`.
"""
import importlib
import inspect
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable, Optional

import sq_aggregator
import sq_analytics
import sq_config
import sq_fx
import sq_performance
from sq_schema import AssetClass, TransactionType, conformance
from sq_tui import (BOLD, DIM, RST, fmt_num, fmt_signed, format_kv,
                    format_table, pnl, quiet, render_chart,
                    render_history as sq_tui_render_history, render_pl_bars,
                    status, tabbed_view, warn_line)

from . import _cache

# Live-fetch resilience: a broker session can transiently drop (expired
# jsessionid → 401); re-fetching re-auths. Retry a few times before declaring
# the broker degraded.
_LIVE_FETCH_ATTEMPTS = 3
_FETCH_RETRY_DELAY_S = 0.4
_MAX_FETCH_WORKERS = 8                 # brokers fetched concurrently (I/O-bound)
_PRINT_LOCK = threading.Lock()         # serialise status() lines from worker threads


def _cost_basis_method():
    """User's configured lot-matching method as a `CostBasisMethod` (default
    FIFO). Resolved at the rendering boundary so analytics receives an explicit
    method and the pure core never reads config. See
    research/config-settings-cross-asset.md."""
    from sq_compute import CostBasisMethod
    try:
        return CostBasisMethod(sq_config.cost_basis_method(fallback="FIFO"))
    except ValueError:
        return CostBasisMethod.FIFO


def _performance_return_method() -> str:
    """User's headline return method, 'TWR' or 'MWR' (default 'TWR'). Both
    figures are always computed; this only selects which the summary flags as
    primary. Resolved at the rendering boundary; an unrecognised value falls
    back to TWR (GIPS default). See research/config-settings-cross-asset.md."""
    raw = sq_config.performance_return_method(fallback="TWR")
    return raw if raw in ("TWR", "MWR") else "TWR"


def _annualize_sub_year_returns() -> bool:
    """Whether to annualise the TWR for sub-1-year holding periods. Default
    False (GIPS I.5.A.4 prohibits it). Resolved at the rendering boundary."""
    return bool(sq_config.annualize_sub_year_returns())


def _should_annualise(span_days: int, annualize_sub_year: bool) -> bool:
    """Annualise a return only when the holding period is ≥ 1 year, OR the user
    has explicitly opted into annualising sub-year periods. Isolating the
    decision here keeps it unit-testable without building a full snapshot."""
    return annualize_sub_year or span_days >= 365


_ASSET_CLASS_LABELS = {
    AssetClass.STOCK:   "Shares",
    AssetClass.ETF:     "ETFs / Trackers",
    AssetClass.BOND:    "Bonds",
    AssetClass.FUND:    "Funds",
    AssetClass.OPTION:  "Options",
    AssetClass.FUTURE:  "Futures",
    AssetClass.FX:      "Currency",
    AssetClass.CRYPTO:  "Crypto",
    AssetClass.INDEX:   "Indices",
    AssetClass.WARRANT: "Warrants",
    AssetClass.CFD:     "CFDs",
    AssetClass.EVENT:   "Event contracts",
    AssetClass.CASH:    "Cash",
    AssetClass.OTHER:   "Other",
}


def _asset_label(asset_class) -> str:
    """Display label for an asset class. Defensive: an unmapped/new enum
    value falls back to its name rather than KeyError-ing the whole view
    (a positions tab must never crash because a connector introduced a
    class the renderer hasn't a pretty label for yet)."""
    return _ASSET_CLASS_LABELS.get(asset_class, getattr(asset_class, "value", "Other"))


# Number formatting lives in sq_tui (one home for every module); thin aliases
# keep this module's many internal call sites (and external pokes) working.
_fmt_num = fmt_num
_fmt_signed = fmt_signed


# ── broker registry ───────────────────────────────────────────────────────
def _discover_brokers(root) -> list[tuple[str, Callable]]:
    """Walk `modules/sq-*` and register every (broker, account) pair whose
    Python package exposes a callable `snapshot` attribute. Each pair
    becomes a distinct broker entry in the aggregated view.

    Naming convention: `modules/sq-<name>/` → `import sq_<name_with_dashes
    _as_underscores>`. Bundles without `snapshot()` are skipped.

    Account discovery:
      * If the broker exposes `accounts() -> list[str | None]`, we
        iterate that list and bind `snapshot(account=name)` for each.
        `None` means "legacy single-account mode" — the label is the
        bare broker name; otherwise label is `<broker>:<account>`.
      * If the broker has no `accounts()`, we register one entry with
        the bare label and `snapshot()` called without an account kwarg.

    Returns `[(label, fn), …]` where `fn` is a zero-arg-or-asof-only
    callable (the account is closed over), so existing call sites that
    do `fn(asof)` keep working unchanged.
    """
    out: list[tuple[str, Callable]] = []
    from . import bundle_dirs
    for bundle in bundle_dirs(root):
        name = bundle.name.replace("sq-", "", 1)
        mod_name = "sq_" + name.replace("-", "_")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        snap_fn = getattr(mod, "snapshot", None)
        if not callable(snap_fn):
            continue
        accounts_fn = getattr(mod, "accounts", None)
        if callable(accounts_fn):
            # accounts() returns the CONNECTED accounts. An EMPTY list means
            # the broker is available but has no account attached yet — we
            # yield nothing for it (it isn't fetched, so no CredentialsMissing
            # error). It surfaces in `_available_connectors` instead, where
            # the home offers to connect it. NB: no `or [None]` fallback —
            # that would resurrect the error-spam for unconnected brokers.
            try:
                acct_list = accounts_fn()
            except Exception:
                acct_list = []
        else:
            # A connector that doesn't implement the multi-account API at all
            # gets one bare entry (best-effort; it'll fetch or fail visibly).
            acct_list = [None]
        for acct in acct_list:
            label = name if acct is None else f"{name}:{acct}"
            out.append((label, _make_broker_call(mod, acct)))
    return _apply_demo_void_fill(out, sq_config.get("demo_mode", "auto"))


def _apply_demo_void_fill(brokers, mode):
    """The PLATFORM's demo void-fill rule (the bundle can't know about other
    brokers — modularity — so the platform owns it): the sq-demo bundle is the
    first-run experience (synthetic, deterministic, THE public figures) and
    participates ONLY while no REAL account is connected. `mode` is config
    `demo_mode`: 'auto' → demo shows only when alone; 'on' → always; 'off' →
    never. Pure on the (label, fn) broker list. Tested in tests/test_void_fill.py."""
    real = [(lb, fn) for lb, fn in brokers if lb.split(":")[0] != "demo"]
    if mode == "off" or (mode == "auto" and real):
        return real
    return brokers


def _available_connectors(root) -> list[str]:
    """Every broker connector (bundle exposing a callable `snapshot`),
    whether or not it has a connected account. The home uses this to show
    "available to connect" and to drive the connect menu — modularity:
    a connector existing is independent of an account being attached."""
    out: list[str] = []
    from . import bundle_dirs
    for bundle in bundle_dirs(root):
        name = bundle.name.replace("sq-", "", 1)
        mod_name = "sq_" + name.replace("-", "_")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        if callable(getattr(mod, "snapshot", None)):
            # The demo bundle is never "available to connect" — it's the
            # void-filler, not a broker (no credentials, nothing to set up).
            if not getattr(mod, "DEMO", False):
                out.append(name)
    return out


def _broker_label_split(label):
    """Split a broker label into (broker, account_or_None).
    "degiro:work" → ("degiro", "work")
    "degiro"      → ("degiro", None)
    Used by helpers that need the bundle module (broker) AND the account
    qualifier (to pass `account=…` through to load_history / snapshots_at)."""
    if ":" in label:
        broker, account = label.split(":", 1)
        return broker, account
    return label, None


def _make_broker_call(mod, account):
    """Build a callable that invokes `mod.snapshot(asof=…, account=…)`,
    closing over the account so downstream call sites stay account-naïve.
    For brokers whose snapshot() doesn't accept `account` (no
    multi-account support yet), we fall back to no-kwarg invocation
    so the legacy contract is preserved."""
    snap = mod.snapshot
    def _call(asof=None):
        if asof is not None:
            return _call_with_account(snap, account, asof)
        return _call_with_account(snap, account)
    return _call


_PROVIDERS: list = []      # PROCESS-lifetime singleton — see docstring below


def _make_market_data_providers():
    """(price_provider, fx_provider) as PROCESS-lifetime singletons. Returns
    (None, None) when the respective bundle isn't installed — callers silently
    degrade. The singleton is load-bearing twice over: `YahooProvider` caches
    per-ticker daily-bar series in-memory, and a TUI session rebuilds the
    aggregate on every navigation — per-call instances meant EVERY redraw
    re-fetched every ticker's series from the network (seconds of hang per
    keypress once a history-rich account appeared). One instance per process
    → one fetch per ticker per session. Trade-off: 'today's' cached bar can
    lag intraday within a long session (^R doesn't reset it; restarting does)."""
    if _PROVIDERS:
        return _PROVIDERS[0]
    price_provider = None
    fx_provider    = None
    # The app layer composes providers + archive: every fetched series/
    # event/spot is recorded into the local bitemporal price archive, and
    # each provider can serve from it when its source breaks. Bare library
    # use of the providers stays archive-free (opt-in). Reliability comes
    # from the CHAIN: Yahoo (unofficial, broad incl. EU venues) answers
    # first; Tiingo (official, free key, US-listed) takes what Yahoo
    # can't; keyless Tiingo is inert.
    store = None
    try:
        from sq_price_store import PriceStore
        store = PriceStore()
    except Exception:                                  # noqa: BLE001
        pass
    chain = []
    try:
        from sq_yahoo import YahooProvider     # type: ignore
        chain.append(YahooProvider(store=store))
    except ImportError:
        pass
    try:
        from sq_tiingo import TiingoProvider   # type: ignore
        chain.append(TiingoProvider(store=store))
    except ImportError:
        pass
    if chain:
        from sq_market_data import ChainProvider
        price_provider = (chain[0] if len(chain) == 1
                          else ChainProvider(*chain))
    try:
        from sq_fx_ecb import ECBProvider      # type: ignore
        fx_provider = ECBProvider()
    except ImportError:
        pass
    _PROVIDERS.append((price_provider, fx_provider))
    return _PROVIDERS[0]


def _overlay_historical_prices(
    brokers: list[sq_aggregator.BrokerSnapshot],
    asof: datetime,
    *,
    price_provider=None,
    fx_provider=None,
) -> list[sq_aggregator.BrokerSnapshot]:
    """Best-effort overlay of each broker's historical Positions with
    true MTM prices at `asof` via the supplied providers (default: lazy
    `_make_market_data_providers()`). Positions whose ticker can't be
    resolved keep their CSV-fold values."""
    if price_provider is None and fx_provider is None:
        price_provider, fx_provider = _make_market_data_providers()
    if price_provider is None:
        return brokers

    from sq_market_data import overlay_prices

    out: list[sq_aggregator.BrokerSnapshot] = []
    for b in brokers:
        if not b.ok:
            out.append(b)
            continue
        snap = b.snapshot
        base_ccy = snap.account.base_currency
        try:
            new_positions = overlay_prices(
                snap.positions, snap.instruments,
                provider=price_provider,
                base_currency=base_ccy,
                fx_provider=fx_provider,
                asof=asof,
            )
        except Exception:                                       # noqa: BLE001
            out.append(b)
            continue
        out.append(sq_aggregator.BrokerSnapshot(
            broker=b.broker,
            snapshot=snap.model_copy(update={"positions": new_positions}),
            error=None,
        ))
    return out


def _enrich_historical_metadata(
    historical: list[sq_aggregator.BrokerSnapshot],
    instruments_by_broker: dict,
    *,
    openfigi_fallback: bool = True,
) -> list[sq_aggregator.BrokerSnapshot]:
    """For each historical broker, copy name / asset_class / ticker /
    listing_currency from `instruments_by_broker[broker_name]` (matched
    by instrument_id). The fold-from-CSV path produces sparse Instruments
    (ISIN only — `name=f'ISIN {isin}'`, `asset_class=OTHER`); the
    enrichment source is typically a recent live snapshot (or a cache
    of one). Best-effort: any broker without enrichment data keeps its
    sparse metadata.

    Second-pass fallback (when `openfigi_fallback=True`): for instruments
    that the live snapshot doesn't know — typically DELISTED ones that
    aren't in the current broker portfolio but appear in CSV history —
    we query OpenFIGI by ISIN to fill in ticker / name / asset_class.
    Cached on disk for 30 days. Network failure / unknown ISIN silently
    falls back to the sparse label.

    Money fields are NEVER touched here — only display metadata. The
    fold's money is canonical for historical views by construction."""
    out = []
    for hb in historical:
        if not hb.ok:
            out.append(hb)
            continue
        live_insts = instruments_by_broker.get(hb.broker) or []
        live_inst_by_id = {i.instrument_id: i for i in live_insts}
        enriched_instruments = []
        for hist_inst in hb.snapshot.instruments:
            live_inst = live_inst_by_id.get(hist_inst.instrument_id)
            if live_inst is not None:
                merged_identifiers = dict(hist_inst.identifiers)
                merged_identifiers.update(live_inst.identifiers)
                # A bare exchange ticker (e.g. Degiro's 'IB01') is NOT a valid
                # Yahoo symbol — without the suffixed yahoo_ticker the price
                # overlay can't resolve and silently keeps the cost surrogate
                # (which then only moves with FX). Fill it from OpenFIGI
                # (30d disk cache) even for live-known instruments.
                if openfigi_fallback and "yahoo_ticker" not in merged_identifiers:
                    of_meta = _openfigi_lookup(hist_inst)
                    if of_meta and of_meta.get("yahoo_ticker"):
                        merged_identifiers["yahoo_ticker"] = of_meta["yahoo_ticker"]
                enriched_instruments.append(hist_inst.model_copy(update={
                    "name":             live_inst.name,
                    "asset_class":      live_inst.asset_class,
                    "listing_currency": live_inst.listing_currency,
                    "listing_venue":    live_inst.listing_venue,
                    "identifiers":      merged_identifiers,
                }))
                continue
            # Second pass: resolver chain for ISINs the live snapshot
            # didn't know (delisted, foreign-only listings, etc.):
            # OpenFIGI first (has tickers), then ESMA FIRDS (official EU
            # register — names/CFI/currency for delisted instruments
            # OpenFIGI has forgotten; live-proven on Premier Oil).
            if openfigi_fallback:
                meta = _openfigi_lookup(hist_inst) or _firds_lookup(hist_inst)
                if meta is not None:
                    enriched_instruments.append(_apply_resolved_meta(
                        hist_inst, meta))
                    continue
            enriched_instruments.append(hist_inst)
        out.append(sq_aggregator.BrokerSnapshot(
            broker=hb.broker,
            snapshot=hb.snapshot.model_copy(update={
                "instruments": enriched_instruments,
            }),
            error=None,
        ))
    return out


# OpenFIGI's "securityType" string → our AssetClass enum. The sq-openfigi
# bundle returns canonical KEY strings to avoid depending on sq_schema;
# we re-map them here.
_OPENFIGI_ASSET_CLASS_TO_ENUM = {
    "STOCK":   AssetClass.STOCK,
    "ETF":     AssetClass.ETF,
    "FUND":    AssetClass.FUND,
    "BOND":    AssetClass.BOND,
    "FUTURE":  AssetClass.FUTURE,
    "OPTION":  AssetClass.OPTION,
    "WARRANT": AssetClass.WARRANT,
    "CFD":     AssetClass.CFD,
    "INDEX":   AssetClass.INDEX,
}


def _openfigi_lookup(hist_inst):
    """Resolve `hist_inst.identifiers["isin"]` via OpenFIGI, cached.
    Returns the normalized metadata dict from sq_openfigi.resolve_metadata,
    or None on cache miss + network failure / unknown ISIN. A sentinel
    (`{"_negative": True}`) is cached for genuine misses so we don't
    re-hit OpenFIGI for known-unresolvable ISINs."""
    isin = (hist_inst.identifiers or {}).get("isin")
    if not isin:
        return None
    cached = _cache.load_openfigi_metadata(isin)
    if cached is not None:
        return None if cached.get("_negative") else cached
    try:
        from sq_openfigi import resolve_metadata
    except ImportError:
        return None
    try:
        meta = resolve_metadata(isin)
    except Exception:                                          # noqa: BLE001
        return None
    if meta is None:
        _cache.save_openfigi_metadata(isin, {"_negative": True})
        return None
    _cache.save_openfigi_metadata(isin, meta)
    return meta


def _firds_lookup(hist_inst):
    """Resolve `hist_inst.identifiers["isin"]` via ESMA FIRDS, cached —
    the rung AFTER OpenFIGI (official EU register; knows delisted
    instruments OpenFIGI doesn't, but has no tickers). Same 30-day
    cache + negative-sentinel discipline as `_openfigi_lookup`."""
    isin = (hist_inst.identifiers or {}).get("isin")
    if not isin:
        return None
    cached = _cache.load_firds_metadata(isin)
    if cached is not None:
        return None if cached.get("_negative") else cached
    try:
        from sq_firds import resolve_metadata
    except ImportError:
        return None
    try:
        meta = resolve_metadata(isin)
    except Exception:                                          # noqa: BLE001
        return None
    if meta is None:
        _cache.save_firds_metadata(isin, {"_negative": True})
        return None
    _cache.save_firds_metadata(isin, meta)
    return meta


def _apply_resolved_meta(hist_inst, meta):
    """Return a new Instrument with resolver metadata (OpenFIGI or FIRDS)
    applied. Identifiers are merged (additive — existing keys win, the
    resolver adds anything new like 'ticker'). name / asset_class /
    listing_currency only overwrite when the resolver supplied them."""
    merged_ids = dict(hist_inst.identifiers)
    if meta.get("ticker") and "ticker" not in merged_ids:
        merged_ids["ticker"] = meta["ticker"]
    if meta.get("yahoo_ticker") and "yahoo_ticker" not in merged_ids:
        merged_ids["yahoo_ticker"] = meta["yahoo_ticker"]
    updates = {"identifiers": merged_ids}
    # Defensive strip: resolver names can carry trailing whitespace (FIRDS
    # pads some gnr_full_name values) — never let it into display metadata.
    name = (meta.get("name") or "").strip()
    if name:
        updates["name"] = name
    if meta.get("currency"):
        updates["listing_currency"] = meta["currency"]
    enum_cls = _OPENFIGI_ASSET_CLASS_TO_ENUM.get(meta.get("asset_class") or "")
    if enum_cls is not None:
        updates["asset_class"] = enum_cls
    return hist_inst.model_copy(update=updates)


def _collect_snapshots(
    root, asof: Optional[datetime] = None,
    *,
    use_snapshot_cache: bool = True,
    on_update: Optional[Callable[[str, str], None]] = None,
    only: Optional[str] = None,
) -> list[sq_aggregator.BrokerSnapshot]:
    """Fetch a snapshot from every discovered broker, never raising. Failed
    fetches surface in the returned list with `snapshot=None` and an
    error string — the renderer shows them as a status line so users see
    which brokers contributed and which are degraded.

    Conformance gate: each fetched snapshot is validated via
    `sq_schema.conformance.check_snapshot` before being handed downstream.
    A snapshot with hard violations (FK breakage, precision pollution,
    duplicate positions) is downgraded to a failed broker entry with the
    violations listed — never silently aggregated.

    `asof`: when given, each broker's `snapshot(asof=…)` is called for a
    PIT-correct historical view (typically derived from that broker's
    CSV history). Brokers that don't support historical queries raise
    and get downgraded — never silently fall back to "now".

    `use_snapshot_cache`: for asof=None only. When True (default), a
    cached current-state snapshot < `SNAPSHOT_CACHE_TTL_SECONDS` old
    short-circuits the live fetch — the dispatcher labels the age in
    the banner so staleness is visible. When False (the `--fresh` path),
    always fetches live and writes through to the cache.

    `on_update(name, state)`: optional progress callback, invoked from worker
    threads as each broker is fetched (states: "fetching"/"retry N"/"cached"/
    "ok"/"failed"/"skipped"). Used by the loading screen to show live progress.
    When None, progress falls back to `status()` lines (lock-serialised).

    Brokers are fetched CONCURRENTLY (thread pool) — the calls are network
    I/O-bound, so wall-clock ≈ the slowest broker, not the sum. (Shared
    market-data providers are read-mostly; a rare duplicate fetch is harmless.)"""
    brokers = list(_discover_brokers(root))
    if only is not None:
        # Scope the FETCH to one account (`--account` / drill-down) — other
        # brokers are never poked, so a per-login-approval account can't
        # fire phone pushes from a query about a different one.
        want = only.strip().lower()
        hit = [b for b in brokers if b[0].lower() == want]
        if not hit:
            pref = [b for b in brokers if b[0].lower().startswith(want)]
            hit = pref if len(pref) == 1 else []
        brokers = hit

    def emit(name, state):
        if on_update is not None:
            on_update(name, state)
        else:
            with _PRINT_LOCK:
                status(f"{name}: {state}")

    if not brokers:
        return []
    workers = min(_MAX_FETCH_WORKERS, len(brokers))
    by_name: dict = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_fetch_one, name, fn, asof, use_snapshot_cache, emit): name
                for name, fn in brokers}
        for fut in futs:
            name = futs[fut]
            by_name[name] = fut.result()           # _fetch_one never raises
    return [by_name[name] for name, _ in brokers]  # discovery order


def _fetch_one(name, snapshot_fn, asof, use_snapshot_cache, emit
               ) -> sq_aggregator.BrokerSnapshot:
    """Fetch + validate ONE broker; never raises (errors become a degraded
    BrokerSnapshot). Safe to run in a worker thread. `emit(name, state)` reports
    progress. See `_collect_snapshots` for the cache / retry / conformance rules."""
    # Current-state cache hit short-circuits the live fetch.
    if asof is None and use_snapshot_cache:
        cached = _cache.load_snapshot(name)
        if cached is not None:
            age = _cache.snapshot_cache_age_seconds(name) or 0
            emit(name, f"cached ({int(age)}s ago)")
            return sq_aggregator.BrokerSnapshot(broker=name, snapshot=cached, error=None)

    # Capability hook: a FRESH fetch (^R / --fresh) also refreshes the broker's
    # transaction HISTORY when the bundle can do that itself (exposes
    # `sync_history`, e.g. degiro downloading its own CSV reports). Bounded by
    # max_age_hours so repeated ^R doesn't re-login every time; best-effort —
    # a sync failure never blocks the live fetch (the staleness ⚠ still shows).
    if asof is None and not use_snapshot_cache:
        broker_mod, account = _broker_label_split(name)
        try:
            mod = importlib.import_module("sq_" + broker_mod.replace("-", "_"))
            sync = getattr(mod, "sync_history", None)
            if callable(sync):
                emit(name, "syncing history…")
                res = sync(account=account, max_age_hours=6)
                if not (res or {}).get("skipped"):
                    emit(name, f"history through {(res or {}).get('ends', '?')}")
        except Exception as e:                              # noqa: BLE001
            emit(name, f"history sync failed ({type(e).__name__}) — using "
                       f"existing files")

    emit(name, "fetching" + (f" @ {asof.date().isoformat()}" if asof else "") + "…")
    # Live fetches retry a few times — a broker session can transiently 401/drop
    # (e.g. Degiro's jsessionid expires) and a fresh fetch re-auths. asof views
    # are CSV-deterministic (no retry). CredentialsMissing ("not connected") is
    # never retried.
    attempts = _LIVE_FETCH_ATTEMPTS if asof is None else 1
    snap, last_err = None, None
    for attempt in range(attempts):
        try:
            snap = snapshot_fn(asof) if asof is not None else snapshot_fn()
            last_err = None
            break
        except Exception as e:                             # noqa: BLE001
            last_err = e
            # Not retryable: "not connected" (CredentialsMissing) and "the user
            # must act" (NeedsAction — e.g. approve the login in the app). A
            # retry can't fix either, and re-attempting a login would re-fire
            # the in-app push every time. Surface them immediately.
            if type(e).__name__ in ("CredentialsMissing", "NeedsAction"):
                break
            if attempt + 1 < attempts:
                emit(name, f"retry {attempt + 2}/{attempts} ({type(e).__name__})")
                time.sleep(_FETCH_RETRY_DELAY_S)
    if last_err is not None:
        emit(name, f"skipped ({type(last_err).__name__})")
        return sq_aggregator.BrokerSnapshot(
            broker=name, snapshot=None,
            error=f"{type(last_err).__name__}: {last_err}")
    # Conformance gate — silent pass when clean, surface when not.
    violations = conformance.check_snapshot(snap)
    if violations:
        msg = conformance.format_violations(violations)
        emit(name, f"skipped (conformance: {len(violations)} violation(s))")
        return sq_aggregator.BrokerSnapshot(
            broker=name, snapshot=None, error=f"conformance: {msg}")
    # Successful + conformant — current-state snapshots write through to the
    # on-disk cache so the next invocation within the TTL window is instant.
    # Historical (asof) snapshots aren't cached (CSV-deterministic, cheap).
    if asof is None:
        _cache.save_snapshot(name, snap)
    emit(name, "ok")
    return sq_aggregator.BrokerSnapshot(broker=name, snapshot=snap)


def _collect_cached(root):
    """Load whatever cached snapshots exist (ANY age) for the connected brokers —
    for an INSTANT warm render. Returns (broker_snapshots, stale) where `stale`
    is True if any connected broker has no cache or a cache older than the TTL
    (→ a background refresh is warranted). No network; no blocking."""
    discovered = _discover_brokers(root)
    out, stale = [], False
    for label, _ in discovered:
        snap = _cache.load_snapshot(label, max_age=None)
        if snap is None:
            stale = True
            continue
        age = _cache.snapshot_cache_age_seconds(label) or 0
        if age > _cache.SNAPSHOT_CACHE_TTL_SECONDS:
            stale = True
        out.append(sq_aggregator.BrokerSnapshot(broker=label, snapshot=snap))
    return out, stale


# ── tab builders ──────────────────────────────────────────────────────────
def _summary_tab(brokers, agg, display_ccy: str,
                 asof: Optional[datetime] = None):
    """Returns `(body, note)`: the data + actionable ⚠ warnings stay in the
    body; definitional footnotes (headline method, GIPS marker) go to the
    `?` help overlay note (the TUI shows it on demand; dumps print it inline)."""
    items: list[tuple] = []
    note_lines: list[str] = []
    banner = ""
    if asof is not None:
        banner = ("  as-of view: derived from CSV history; open positions "
                  "marked-to-market at that date via Yahoo + ECB best-effort.\n"
                  "  Positions whose ticker can't be resolved fall back "
                  "to cost-basis value (price column shows '—').\n\n")

    if agg.total_value is not None:
        items.append(("total value", f"{_fmt_num(agg.total_value)} {display_ccy}"))
    if agg.positions_value is not None:
        items.append(("positions value",
                      f"{_fmt_num(agg.positions_value)} {display_ccy}"))
    else:
        items.append(("positions value",
                      "— (some legs unconverted)"))
    items.append(("cash (converted)",
                  f"{_fmt_num(agg.cash_value)} {display_ccy}"))
    for broker, ccy, amount in agg.unconverted_cash:
        items.append((f"+ {broker} cash (no rate)",
                      f"{_fmt_num(amount)} {ccy}"))

    if agg.total_pl_lifetime is not None:
        items.append(("total P/L (lifetime)",
                      pnl(agg.total_pl_lifetime,
                          f"{_fmt_signed(agg.total_pl_lifetime)} {display_ccy}")))
    if agg.total_realized_pl is not None:
        items.append(("realised P/L",
                      pnl(agg.total_realized_pl,
                          f"{_fmt_signed(agg.total_realized_pl)} {display_ccy}")))
    if agg.total_unrealized_pl is not None:
        items.append(("unrealised P/L (now)",
                      pnl(agg.total_unrealized_pl,
                          f"{_fmt_signed(agg.total_unrealized_pl)} {display_ccy}")))

    # Income streams (dividends / interest / fees) — previously computed but
    # only visible in the flows tab; material income deserves the headline.
    items += _income_lines(brokers, display_ccy, asof=asof)

    items += [
        ("open positions",   str(agg.open_position_count)),
        ("closed positions", str(agg.closed_position_count)),
        ("accounts",         f"{len([b for b in brokers if b.ok])} ok / "
                              f"{len(brokers)} total"),
    ]

    head = format_kv(items)

    # Per-broker subtotals — each row in that broker's own base ccy.
    # XIRR + total return are computed from the broker's CSV history when
    # available; brokers without `load_history()` (or with no CSVs) show
    # "—" in those columns.
    if agg.per_broker:
        perf_by_broker = _per_broker_performance(brokers, agg, asof=asof)
        # Headline return method: the engine computes both XIRR (money-weighted)
        # and TWR (time-weighted); the user's setting flags which is primary.
        method = _performance_return_method()
        any_period_only = False
        rows = []
        for pb in agg.per_broker:
            perf = perf_by_broker.get(pb["broker"], {})
            dd = perf.get("max_drawdown")
            xirr = perf.get("xirr")
            twr = perf.get("twr")
            ret = perf.get("return_pct")
            # A TWR we left non-annualised (sub-1yr, GIPS) carries a marker so
            # the "/yr" header isn't read as an annual rate for that row.
            period_only = perf.get("twr_period_only", False)
            any_period_only = any_period_only or period_only
            twr_mark = "†" if period_only else ""
            rows.append([
                pb["broker"],
                pb["base_currency"],
                _fmt_num(pb["positions_value_base"]),
                pnl(pb["total_pl_lifetime"]),
                (pnl(float(xirr) * 100, f"{float(xirr) * 100:.2f}%")
                 if xirr is not None else "—"),
                (pnl(float(twr) * 100, f"{float(twr) * 100:.2f}%{twr_mark}")
                 if twr is not None else "—"),
                (pnl(float(ret), f"{float(ret):.2f}%")
                 if ret is not None else "—"),
                # max drawdown is a loss → always red (or '—').
                (pnl(-1, f"-{float(dd['drawdown_pct']) * 100:.1f}%")
                 if dd is not None else "—"),
                f"{pb['open_position_count']}/"
                f"{pb['open_position_count'] + pb['closed_position_count']}",
            ])
        # Flag the headline column in its header (▸ = primary per config).
        xirr_h = ("▸ XIRR/yr" if method == "MWR" else "XIRR/yr")
        twr_h  = ("▸ TWR/yr"  if method == "TWR" else "TWR/yr")
        head += "\n\n" + format_table(
            ["broker", "ccy", "positions", "total P/L",
             xirr_h, twr_h, "total return", "max drawdown", "open/all"],
            rows,
            align=["l", "l", "r", "r", "r", "r", "r", "r", "r"],
            title="per broker (each in its own base ccy)",
        )
        # Definitional footnotes (which return is headline + how to switch,
        # the GIPS non-annualised marker) are REFERENCE info → the ? help note.
        if method == "MWR":
            note_lines.append("▸ headline: money-weighted (XIRR) · "
                              "sciqnt config set performance_return_method TWR")
        else:
            note_lines.append("▸ headline: time-weighted (TWR) · "
                              "sciqnt config set performance_return_method MWR")
        if any_period_only:
            note_lines.append("† under 1yr — cumulative period return, not "
                              "annualised (GIPS); flip annualize_sub_year_returns")
        # Drawdown DATES are reference info (the percentage is already in the
        # table) → the ? help note, one line per broker. The peak/trough
        # values are TWR-index numbers (normalized to 1.0 at series start),
        # not meaningful absolute values, so we surface dates + percentage
        # only. Recovery date is included when the index reclaimed the
        # prior peak. (Dumps print notes inline, so nothing is lost.)
        for pb in agg.per_broker:
            perf = perf_by_broker.get(pb["broker"], {})
            dd = perf.get("max_drawdown")
            if dd is None:
                continue
            recovered = (f", recovered {dd['recovered_at'].date().isoformat()}"
                         if dd.get("recovered_at") else ", not recovered")
            note_lines.append(
                f"{pb['broker']}: max drawdown "
                f"{float(dd['drawdown_pct']) * 100:.1f}% "
                f"from {dd['peak_at'].date().isoformat()} to "
                f"{dd['trough_at'].date().isoformat()}{recovered}"
            )

        # Benchmark comparison — the "is 6.7% good?" context. One line per
        # broker with both a TWR and a benchmark return over ITS window.
        bench_lines = []
        for pb in agg.per_broker:
            perf = perf_by_broker.get(pb["broker"], {})
            bench = perf.get("benchmark")
            tw = perf.get("twr")
            if not bench or tw is None or bench.get("twr") is None:
                continue
            unit = "†" if perf.get("twr_period_only") else "/yr"
            diff_pp = (float(tw) - float(bench["twr"])) * 100
            word = "ahead" if diff_pp >= 0 else "behind"
            bench_lines.append(
                f"  {pb['broker']}: {float(tw) * 100:.2f}%{unit} vs "
                f"{bench['ticker']} {float(bench['twr']) * 100:.2f}%{unit} — "
                + pnl(diff_pp, f"{abs(diff_pp):.2f}pp {word}")
            )
        if bench_lines:
            head += "\n\n" + "\n".join(bench_lines)
            note_lines.append(
                "benchmark = PRICE return over the same period (distributing "
                "dividends not added back; accumulating ETFs compare honestly) "
                "· sciqnt config set benchmark <ticker>|none")

        # History coverage — ACTIONABLE, stays in the body: say WHY a row
        # shows "—" and what to do about it (a missing or stale export must
        # be visible, never a silent dash, never hidden behind ? help).
        # Rendered through warn_line: YELLOW ⚠ = user-fixable severity.
        warns = []
        # A history load or value-series build that RAISED is a failure,
        # not "no data" — say so next to the dash it caused.
        for pb in agg.per_broker:
            err = perf_by_broker.get(pb["broker"], {}).get("series_error")
            if err:
                warns.append(warn_line(
                    f"{pb['broker']}: performance series failed ({err}) "
                    f"— XIRR/TWR may be missing; ^R to retry"))
        # Incomplete-export detector. Withdrawing more than you deposited
        # is fine when the LEDGER explains the surplus (position P/L plus
        # dividend/interest income — an income-funded withdrawal is NOT
        # missing data, audit find 2026-06-11); a surplus the ledger
        # CANNOT explain means the export window misses the funding era
        # and every flow-based number (XIRR, returns) is built on missing
        # data. Found live: €4.72 deposits vs €6,974.51 withdrawals
        # against a −€559.91 ledger.
        _, _fx = _make_market_data_providers()
        for pb in agg.per_broker:
            perf = perf_by_broker.get(pb["broker"], {})
            nc = perf.get("net_contributed")
            ledger_pl = pb.get("total_pl_lifetime")
            if nc is None or nc >= 0 or ledger_pl is None:
                continue
            explained = ledger_pl
            _, txns, _ = _load_broker_history(pb["broker"])
            if txns:
                inc = sq_analytics.income_summary(
                    txns, base_currency=pb["base_currency"],
                    fx_provider=_fx, asof=asof)
                explained += inc["dividends"] + inc["interest"]
            unexplained = (-nc) - explained
            materiality = max(abs(explained) * Decimal("0.05"),
                              Decimal("25"))
            if unexplained > materiality:
                warns.append(
                    f"{pb['broker']}: history export looks incomplete — "
                    f"withdrawals exceed deposits by "
                    f"{_fmt_num(-nc)} {pb['base_currency']} but the ledger "
                    f"only explains {_fmt_signed(explained)} "
                    f"(XIRR/returns unreliable; re-export the FULL history)")
        for label, state, detail in _history_status(brokers):
            if state == "missing":
                where = f" — drop CSV exports into {detail}" if detail else ""
                warns.append(f"{label}: no transaction history "
                             f"(XIRR/TWR/daily show —){where}")
            elif state == "stale":
                warns.append(f"{label}: history export ends "
                             f"{detail.isoformat()} — re-export to refresh")
        if warns:
            head += "\n\n" + "\n".join(f"  {warn_line(n)}" for n in warns)

    # Surface failed accounts explicitly — degrade VISIBLY, but in plain
    # user language with the action, never a raw exception table. The full
    # technical detail goes to the ? help note (progressive disclosure).
    failed = [b for b in brokers if not b.ok]
    if failed:
        lines = [_account_problem(b) for b in failed]
        head += "\n\n" + "\n".join(f"  {ln}" for ln in lines)
        note_lines += [f"{b.broker}: {b.error or '?'}" for b in failed]

    note = ("\n".join(f"  {DIM}{n}{RST}" for n in note_lines)
            if note_lines else "")
    return banner + head, note


def account_problem_text(b) -> str:
    """The plain-language SYMPTOM for a failing account — honest about what we
    OBSERVE, not a prescriptive remedy we can't be sure of. Anything
    non-obvious is best handed to the agent (the home/portfolio recommend it,
    and it gets the full error + the tools — `sciqnt <broker> live --fresh`,
    `doctor` — to investigate) rather than pigeonholing the user into one
    guessed fix. The ONLY action we name outright is the certain one: a
    not-connected account → connect it. Raw exception text never reaches the
    screen — it lives behind the ? detail note (research/connect-experience.md).
    Uncolored — callers style it (home: warning orange; summary tab: ⚠/dim)."""
    err = b.error or ""
    if err.startswith("CredentialsMissing"):
        return (f"{b.broker} isn't connected — "
                f"Portfolio Accounts › Connect new Account")
    if err.startswith("conformance:"):
        # Money-math integrity — fetched but REJECTED, never shown as healthy
        # data (P17); distinct from a fetch failure.
        return (f"{b.broker} data failed integrity checks — "
                f"not shown (? for detail)")
    # Everything else — a dropped/blocked session, an auth challenge, a
    # transient network fault, an unknown error — is a symptom to investigate,
    # not a known fix. Just state it; the agent (recommended above) diagnoses,
    # and the raw cause stays behind the ? detail note. We deliberately stop at
    # "couldn't fetch" rather than guessing a reason or a remedy.
    return f"{b.broker} couldn't fetch"


def _account_problem(b) -> str:
    """account_problem_text styled for the summary tab: ⚠ for user-fixable
    states, dim for transient fetch errors."""
    text = account_problem_text(b)
    fixable = (b.error or "").startswith(
        ("CredentialsMissing", "NeedsAction", "conformance:"))
    if fixable:
        return warn_line(text)
    return f"{DIM}{text}{RST}"


_NEWS_PROVIDER: list = []


class _ChainNews:
    """First-non-empty composition of NewsProviders — the news analogue
    of sq_market_data.ChainProvider. Finnhub (official, keyed, inert
    without a key) answers first; keyless Yahoo RSS is the floor."""

    def __init__(self, *providers):
        self.providers = [p for p in providers if p is not None]

    def get_news(self, ticker: str, *, limit: int = 5) -> list:
        for p in self.providers:
            try:
                items = p.get_news(ticker, limit=limit)
            except Exception:                          # noqa: BLE001
                continue
            if items:
                return items
        return []


def _make_news_provider():
    """Process-lifetime news-provider singleton (same rationale as the
    price providers: per-ticker results cached across TUI redraws).
    None when no news bundle is installed — the tab degrades."""
    if _NEWS_PROVIDER:
        return _NEWS_PROVIDER[0]
    chain = []
    try:
        from sq_finnhub import FinnhubNewsProvider  # type: ignore
        chain.append(FinnhubNewsProvider())
    except ImportError:
        pass
    try:
        from sq_news_rss import RssNewsProvider    # type: ignore
        chain.append(RssNewsProvider())
    except ImportError:
        pass
    provider = None
    if chain:
        provider = chain[0] if len(chain) == 1 else _ChainNews(*chain)
    _NEWS_PROVIDER.append(provider)
    return provider


def _portfolio_news(agg_positions, provider, *, limit_tickers=6,
                    per_ticker=3):
    """The DATA half of the news view: headlines joined to the largest open
    holdings (by exposure), URL-deduped across tickers. Returns
    [(ticker, [NewsItem])] or None when no open position has a ticker.
    Shared by the rendered tab and the `--json --tab news` surface."""
    open_rows = [(broker, pos, inst) for broker, pos, inst in agg_positions
                 if pos.is_open]
    open_rows.sort(key=lambda r: r[1].value_base or Decimal("0"),
                   reverse=True)
    tickers: list[str] = []
    for _, _, inst in open_rows:
        t = inst.identifiers.get("ticker")
        if t and t not in tickers:
            tickers.append(t)
        if len(tickers) >= limit_tickers:
            break
    if not tickers:
        return None
    seen_urls: set = set()
    out = []
    for t in tickers:
        items = provider.get_news(t, limit=per_ticker * 2)
        fresh = []
        for item in items:
            key = item.url or item.headline
            if key in seen_urls:
                continue
            seen_urls.add(key)
            fresh.append(item)
            if len(fresh) >= per_ticker:
                break
        if fresh:
            out.append((t, fresh))
    return out


def _news_tab(agg_positions, *, provider=None,
              limit_tickers: int = 6, per_ticker: int = 3):
    """'What happened to MY portfolio' — headlines joined to holdings,
    ordered by exposure (largest open positions first), deduped by URL
    across tickers (two holdings often surface the same macro story).
    Returns `(body, note)`. News is context for the reader/agent — it
    feeds nothing in the money core."""
    if provider is None:
        provider = _make_news_provider()
    if provider is None:
        return ("  (no news source installed — add the sq-news-rss bundle)",
                "")

    got = _portfolio_news(agg_positions, provider,
                          limit_tickers=limit_tickers, per_ticker=per_ticker)
    if got is None:
        return ("  (no open positions with a known ticker)", "")

    sections = []
    for t, fresh in got:
        lines = [f"  {BOLD}{t}{RST}"]
        for item in fresh:
            ts = item.valid_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"    {DIM}{ts}{RST}  {item.headline}")
        sections.append("\n".join(lines))

    if not sections:
        return ("  (no headlines right now — sources may be unavailable)",
                "")
    note = ("headlines via the installed news sources (newest first, top "
            f"{limit_tickers} holdings by exposure) — context only, "
            "never an input to the numbers")
    return "\n\n".join(sections), note


def _positions_tab(agg_positions) -> str:
    """All positions across all brokers, grouped by asset class with a
    `broker` column. Same shape as `sq-degiro live` positions tab; the
    grouping prefers asset class over broker so "all my ETFs" reads as
    one block even across N brokers."""
    if not agg_positions:
        return "  (no positions)"

    groups: dict[str, list] = {}
    for broker, pos, inst in agg_positions:
        label = _asset_label(inst.asset_class)
        groups.setdefault(label, []).append((broker, pos, inst))

    def _dim(s):
        return f"{DIM}{s}{RST}"

    chunks = []
    for label in sorted(groups):
        rows = []
        # Open positions first, then closed; within each, by broker+ticker.
        for broker, pos, inst in sorted(
            groups[label],
            key=lambda t: (not t[1].is_open,
                           t[0], (t[2].identifiers.get("ticker") or "").lower()),
        ):
            closed = not pos.is_open
            unrealized_pct = None
            if pos.is_open and pos.cost_basis_base > 0:
                unrealized_pct = (float(pos.unrealized_pl_base)
                                  / float(pos.cost_basis_base) * 100)
            pct_str = (f"{'+' if (unrealized_pct or 0) > 0 else ''}"
                       f"{unrealized_pct:.2f}%" if unrealized_pct is not None else "—")

            # Context cells are GREYED on a closed position (history, not a live
            # holding); P&L cells stay coloured green/red whether open or closed.
            ctx = _dim if closed else (lambda s: s)
            ticker = (inst.identifiers.get("ticker")
                      or inst.identifiers.get(f"broker:{broker}") or "?")
            price = (f"{_fmt_num(pos.last_price_local)} {inst.listing_currency}"
                     if pos.last_price_local is not None else "—")
            if closed:
                # Unrealised is 0 for a closed position → dim those cells with
                # the rest of the row; only realised + total P/L are coloured.
                prod, fxp, upl = (ctx(_fmt_signed(pos.unrealized_product_pl_base)),
                                  ctx(_fmt_signed(pos.unrealized_currency_pl_base)),
                                  ctx(_fmt_signed(pos.unrealized_pl_base)))
                pct_cell = ctx("—")
            else:
                prod = pnl(pos.unrealized_product_pl_base)   # product-driven (price)
                fxp = pnl(pos.unrealized_currency_pl_base)   # fx-driven (currency)
                upl = pnl(pos.unrealized_pl_base)            # = prod + fx
                pct_cell = (pnl(unrealized_pct, pct_str)
                            if unrealized_pct is not None else "—")
            rows.append([
                ctx(broker),
                ctx(ticker),
                ctx(inst.identifiers.get("isin") or ""),
                ctx(str(pos.quantity)),
                ctx(price),
                ctx(_fmt_num(pos.value_base)),
                prod, fxp, upl, pct_cell,
                pnl(pos.realized_pl_base),                   # coloured open OR closed
                pnl(pos.total_pl_base),
            ])
        chunks.append(format_table(
            ["broker", "ticker", "ISIN", "qty", "price", "value (base)",
             "prod P/L", "fx P/L", "u.P/L", "u.P/L%", "realised", "total P/L"],
            rows,
            align=["l", "l", "l", "r", "r", "r", "r", "r", "r", "r", "r", "r"],
            title=label,
        ))
    return "\n\n".join(chunks)


def _exposure_tab(brokers, display_ccy: str) -> str:
    # Money fields are FX-converted to the display currency INSIDE the
    # aggregator (audit 2026-06-11: mixed-base brokers used to be summed
    # raw); brokers whose base can't convert are excluded and called out.
    _, fx_provider = _make_market_data_providers()
    ce = sq_aggregator.aggregate_currency_exposure(
        brokers, display_currency=display_ccy, fx_provider=fx_provider)
    ce_rows = [
        [ccy, _fmt_num(parts["positions"]), _fmt_num(parts["cash"]),
         _fmt_num(parts["total"])]
        for ccy, parts in sorted(ce.items())
    ]
    ce_body = (format_table(
        ["ccy", "positions", "cash", f"total ({display_ccy})"], ce_rows,
        align=["l", "r", "r", "r"], title="currency exposure",
    ) if ce_rows else "  (no positions or cash)")

    ace, skipped = sq_aggregator.aggregate_asset_class_exposure(
        brokers, display_currency=display_ccy, fx_provider=fx_provider)
    ac_rows = [
        [ac, str(parts["position_count"]),
         _fmt_num(parts["value_base"]),
         _fmt_num(parts["cost_basis_base"]),
         _fmt_signed(parts["realized_pl_base"])]
        for ac, parts in sorted(ace.items())
    ]
    ac_body = (format_table(
        ["asset class", "#", f"value ({display_ccy})", "cost basis",
         "realised"],
        ac_rows, align=["l", "r", "r", "r", "r"],
        title="asset-class exposure",
    ) if ac_rows else "  (no positions classified)")

    body = ce_body + "\n\n" + ac_body
    for broker, base, n in skipped:
        body += (f"\n  {DIM}+ {broker}: {n} position(s) in {base} "
                 f"excluded (no {base}→{display_ccy} rate){RST}")
    return body


def _accepts_kwarg(fn, name: str):
    """True/False when `fn`'s signature is introspectable; None when it
    isn't (C callables, exotic wrappers) — callers then keep a guarded
    retry. Replaces the old `except TypeError` call-and-retry dance,
    which could misroute a GENUINE internal TypeError into the wrong
    call path (audit 2026-06-11: e.g. silently fetching the DEFAULT
    account's money when the named account's fetch raised one)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return True
    return name in params


def _call_with_account(fn, account, *args):
    """Invoke a connector capability with `account=` when the function
    accepts it (signature-probed; the guarded retry survives only for
    uninspectable callables). One home for the multi-account capability
    probe — see `_accepts_kwarg` for why this replaced `except TypeError`."""
    takes = _accepts_kwarg(fn, "account")
    if takes is False:
        return fn(*args)
    if takes is None:
        try:
            return fn(*args, account=account)
        except TypeError:
            return fn(*args)
    return fn(*args, account=account)


def _get_rate_at(fx_provider, src: str, dst: str, asof_date):
    """`get_rate(src, dst, asof=…)` with the asof kwarg signature-probed
    (older providers without PIT rates degrade to the latest rate)."""
    takes = _accepts_kwarg(fx_provider.get_rate, "asof")
    if takes is False:
        return fx_provider.get_rate(src, dst)
    if takes is None:
        try:
            return fx_provider.get_rate(src, dst, asof=asof_date)
        except TypeError:
            return fx_provider.get_rate(src, dst)
    return fx_provider.get_rate(src, dst, asof=asof_date)


def _load_broker_history(label):
    """(module, transactions, error) for a connected-broker label — the
    one home for the import + `account=` capability probe every call
    site used to duplicate. (None, None, None) = bundle missing;
    (mod, None, None) = no `load_history` capability or empty history;
    (mod, None, "TypeError: …") = the load itself RAISED — callers that
    render coverage must surface that string, never a silent dash."""
    broker, account = _broker_label_split(label)
    try:
        mod = importlib.import_module("sq_" + broker.replace("-", "_"))
    except Exception:                                       # noqa: BLE001
        return None, None, None
    load_history = getattr(mod, "load_history", None)
    if not callable(load_history):
        return mod, None, None
    try:
        return mod, _call_with_account(load_history, account), None
    except Exception as e:                                  # noqa: BLE001
        return mod, None, f"{type(e).__name__}: {e}"


def _income_lines(brokers, display_ccy, *, asof=None):
    """Income block for the summary tab: lifetime + YTD dividends, interest,
    fees — every broker's history concatenated, each flow converted to the
    display currency at its execution date (`sq_analytics.income_summary`).
    Returns a list of kv items; empty when no broker exposes history."""
    txns = []
    for b in brokers:
        if not b.ok:
            continue
        _, t, _ = _load_broker_history(b.broker)
        if t:
            txns.extend(t)
    if not txns:
        return []
    _, fx_provider = _make_market_data_providers()
    life = sq_analytics.income_summary(
        txns, base_currency=display_ccy, fx_provider=fx_provider, asof=asof)
    this_year = (asof or datetime.now(timezone.utc)).year
    ytd = sq_analytics.income_summary(
        txns, base_currency=display_ccy, fx_provider=fx_provider, asof=asof,
        year=this_year)

    items: list[tuple] = []
    if life["dividends"]:
        items.append(("dividends (lifetime)",
                      pnl(life["dividends"],
                          f"{_fmt_signed(life['dividends'])} {display_ccy}")))
        if ytd["dividends"]:
            items.append((f"dividends ({this_year})",
                          pnl(ytd["dividends"],
                              f"{_fmt_signed(ytd['dividends'])} {display_ccy}")))
    if life["interest"]:
        items.append(("interest (lifetime)",
                      pnl(life["interest"],
                          f"{_fmt_signed(life['interest'])} {display_ccy}")))
    if life["fees"]:
        items.append(("fees (lifetime)",
                      pnl(life["fees"],
                          f"{_fmt_signed(life['fees'])} {display_ccy}")))
    # Rates we couldn't resolve must never vanish silently — same pattern
    # as the unconverted-cash lines above the P/L block. Keyed per
    # (stream, ccy) so a dividend and a fee in the same currency can't
    # net to an invisible zero.
    for (stream, ccy), amount in sorted(life["unconverted"].items()):
        items.append((f"+ {stream} (no rate, {ccy})",
                      f"{_fmt_num(amount)} {ccy}"))
    return items


def _benchmark_performance(start, end, *, annualise, price_provider=None):
    """Benchmark return over [start, end] — the SAME TWR engine fed a
    two-sample, zero-flow series, so the comparison shares the
    portfolio's methodology including the annualise decision. This is a
    PRICE return: a distributing fund's dividends aren't added back, so
    prefer accumulating-ETF benchmarks (IWDA.AS, CSPX.AS) for an honest
    comparison — declared in the ? note. Returns
    `{"ticker", "twr", "return_pct"}` or None (disabled / unpriceable)."""
    ticker = sq_config.benchmark()
    if not ticker or str(ticker).lower() == "none":
        return None
    if price_provider is None:
        price_provider, _ = _make_market_data_providers()
    if price_provider is None:
        return None
    try:
        p0 = price_provider.get_price(ticker, asof=start)
        p1 = price_provider.get_price(ticker, asof=end)
    except Exception:                                       # noqa: BLE001
        return None
    if (not p0 or not p1 or p0.last_price_local <= 0
            or p1.last_price_local <= 0):
        return None
    rate = sq_performance.twr(
        [(start, p0.last_price_local), (end, p1.last_price_local)],
        [(start, Decimal("0")), (end, Decimal("0"))],
        annualise=annualise,
    )
    if rate is None:
        return None
    ret_pct = (p1.last_price_local / p0.last_price_local
               - Decimal("1")) * Decimal("100")
    return {"ticker": ticker, "twr": rate, "return_pct": ret_pct}


def _per_broker_performance(brokers, agg, *, asof=None) -> dict:
    """Per-broker XIRR + total-return + TWR + max-drawdown summary.

    Terminal value = positions_value_base (already in broker base ccy)
                     + any cash whose ccy == base ccy. Mixed-currency
                     cash is excluded — XIRR over mixed FX is not
                     well-defined; mention it in the banner if we ever
                     surface it. Cross-currency FLOWS, on the other
                     hand, are converted at-date via the shared FX
                     provider so DEPOSITs in non-base ccy contribute
                     correctly to the IRR.

    TWR + drawdown require a portfolio-value time-series. We build one
    by folding the broker's transaction history at each external
    cash-flow date (DEPOSIT / WITHDRAWAL) and overlaying prices at
    that date via the cached Yahoo + ECB providers. Per-ticker daily
    bars are fetched once and reused across every sample (see
    YahooProvider's in-memory series cache).

    Returns `{broker_name: {xirr, return_pct, twr, max_drawdown,
                            deposits, withdrawals, first_flow_at,
                            last_flow_at}}`."""
    # Shared FX provider so XIRR/total_return can convert mixed-currency
    # flows at-date (e.g. a GBP deposit into a EUR-base account).
    # `_make_market_data_providers` returns (None, None) if the bundle
    # isn't installed — the performance fns silently drop unconvertible
    # flows in that case.
    _, _fx_provider = _make_market_data_providers()
    annualize_sub_year = _annualize_sub_year_returns()
    out: dict[str, dict] = {}
    per_broker_by_name = {pb["broker"]: pb for pb in agg.per_broker}
    for b in brokers:
        if not b.ok:
            continue
        pb = per_broker_by_name.get(b.broker)
        if not pb:
            continue
        base_ccy = pb["base_currency"]

        _, account = _broker_label_split(b.broker)
        _, txns, load_err = _load_broker_history(b.broker)
        if not txns:
            continue

        cash_in_base = sum(
            (c.amount for c in b.snapshot.cash_balances
             if c.currency == base_ccy),
            Decimal("0"),
        )
        terminal = pb["positions_value_base"] + cash_in_base

        rate = sq_performance.xirr(
            txns, terminal_value=terminal, base_currency=base_ccy,
            asof=asof, fx_provider=_fx_provider,
        )
        tr = sq_performance.total_return(
            txns, terminal_value=terminal, base_currency=base_ccy,
            asof=asof, fx_provider=_fx_provider,
        )

        # Build a value series for TWR + drawdown — best-effort; on any
        # failure we just leave those columns as None and move on.
        # Drawdown is computed over a TWR-INDEX series (a normalized
        # cumulative-return index) NOT the raw portfolio value — else
        # a large withdrawal would read as a "99% drop" when in fact
        # the strategy was up. The TWR index strips cash flows away.
        tw_rate = None
        tw_period_only = False
        dd = None
        bench = None
        series_error = None
        try:
            value_series, cash_flows = _build_value_and_flow_series(
                b.broker, txns, base_ccy, asof=asof, account=account,
                live_instruments={b.broker: b.snapshot.instruments},
            )
            if value_series and len(value_series) >= 2:
                span_days = (value_series[-1][0] - value_series[0][0]).days
                annualise = _should_annualise(span_days, annualize_sub_year)
                tw_rate = sq_performance.twr(
                    value_series, cash_flows, annualise=annualise)
                # Flag a value we deliberately left non-annualised so the
                # renderer can mark it (a "/yr" column otherwise lies).
                tw_period_only = tw_rate is not None and not annualise
                index_series = _build_twr_index_series(value_series, cash_flows)
                # An all-breaks series yields an index flat at 1.0 whose
                # "0.0% drawdown" would read as a confident number where
                # the TWR honestly shows "—". Only a series with at least
                # one MEASURED segment gets a drawdown.
                if (len(index_series) >= 2
                        and any(v != Decimal("1") for _, v in index_series)):
                    dd = sq_performance.max_drawdown(index_series)
                # The benchmark over the SAME window with the SAME
                # annualise decision — apples to apples per broker.
                bench = _benchmark_performance(
                    value_series[0][0], value_series[-1][0],
                    annualise=annualise)
        except Exception as e:                             # noqa: BLE001
            # A FAILED series build must be distinguishable from "no
            # data": the summary renders this as a ⚠ warning (audit
            # 2026-06-11 — a regression here used to be an unexplained
            # dash in the TWR column).
            series_error = f"{type(e).__name__}: {e}"

        out[b.broker] = {
            "xirr":            rate,
            "return_pct":      tr["return_pct"],
            "twr":             tw_rate,
            "twr_period_only": tw_period_only,
            "max_drawdown":    dd,
            "benchmark":       bench,
            "series_error":    series_error or load_err,
            "net_contributed": tr["net_contributed"],
            "profit":          tr["profit"],
            "first_flow_at":   tr["first_flow_at"],
            "last_flow_at":    tr["last_flow_at"],
        }
    return out


def _build_twr_index_series(value_series, cash_flows):
    """Thin alias over `sq_performance.twr_index_series` — the index math
    (incl. the empty-portfolio performance-break rule shared with twr)
    lives in the money core, not the platform."""
    return sq_performance.twr_index_series(value_series, cash_flows)


def _build_value_and_flow_series(
    broker_label: str,
    txns,
    base_currency: str,
    *,
    asof: Optional[datetime] = None,
    account: Optional[str] = None,
    live_instruments: Optional[dict] = None,
):
    """Sample the portfolio value at each external cash-flow date.

    Returns `(value_series, cash_flow_series)` — two parallel lists of
    `(datetime, Decimal)` pairs. `value_series[i]` is the portfolio
    value at sample_date i (positions MTM at that date + cash in base
    ccy); `cash_flow_series[i]` is the net DEPOSIT − WITHDRAWAL that
    occurred ON that date (positive = cash in, negative = cash out).
    The final sample is `asof` (or "now") so TWR / drawdown include
    today's value.

    Empty lists are returned when there are no flows in `base_currency`
    or fewer than two samples (TWR / drawdown undefined)."""
    from sq_schema import TransactionType

    relevant_flows = [
        t for t in txns
        if t.type in (TransactionType.DEPOSIT, TransactionType.WITHDRAWAL)
        and t.amount_currency == base_currency
        and (asof is None or t.executed_at <= asof)
    ]
    if not relevant_flows:
        return [], []

    # Honest gap: if a user exports a CSV that doesn't include the
    # account's full history, the first events can be WITHDRAWAL of a
    # pre-existing balance — making any value series starting there
    # degenerate (V_start would already need to "know" the missing
    # prior state). Anchor on the FIRST DEPOSIT: that's the earliest
    # date we can claim full coverage. Everything before is dropped
    # silently — TWR/drawdown over a stream we can't reconstruct
    # cleanly would be misleading.
    first_deposit = next(
        (t.executed_at for t in sorted(relevant_flows,
                                       key=lambda t: t.executed_at)
         if t.type == TransactionType.DEPOSIT),
        None,
    )
    if first_deposit is None:
        return [], []

    flow_by_date: dict = {}
    for t in relevant_flows:
        if t.executed_at < first_deposit:
            continue
        flow_by_date[t.executed_at] = (
            flow_by_date.get(t.executed_at, Decimal("0")) + t.amount
        )

    sample_dates = sorted(flow_by_date.keys())
    from datetime import timezone as _tz
    end = asof if asof is not None else datetime.now(_tz.utc)
    if sample_dates[-1] < end:
        sample_dates.append(end)

    # Reuse the same provider instances across all samples — the
    # per-ticker bar series is fetched once thanks to YahooProvider's
    # in-memory cache. Without this, each sample would be a fresh fetch.
    price_provider, fx_provider = _make_market_data_providers()

    broker, label_account = _broker_label_split(broker_label)
    if account is None:
        account = label_account
    try:
        import importlib
        mod = importlib.import_module("sq_" + broker.replace("-", "_"))
    except Exception:
        return [], []

    snapshot_fn = getattr(mod, "snapshot", None)
    if not callable(snapshot_fn):
        return [], []

    # Prefer the batched `snapshots_at(asof_dates)` capability when the
    # broker exposes it — single chronological pass through CSV history
    # via fold_position_series. Falls back to repeated snapshot(asof=X)
    # when the broker hasn't implemented the batch API yet.
    snapshots_at_fn = getattr(mod, "snapshots_at", None)
    batched: dict = {}
    if callable(snapshots_at_fn):
        try:
            batched = _call_with_account(snapshots_at_fn, account,
                                         sample_dates)
        except Exception:                                       # noqa: BLE001
            batched = {}

    value_series: list[tuple[datetime, Decimal]] = []
    for sd in sample_dates:
        snap = batched.get(sd)
        if snap is None:
            try:
                snap = _call_with_account(snapshot_fn, account, sd)
            except Exception:                                   # noqa: BLE001
                return [], []
        if live_instruments:
            # Enrich sparse CSV instruments (live tickers + OpenFIGI
            # yahoo_ticker) so the overlay can price them — otherwise the
            # series rides cost surrogates and TWR/drawdown go FX-flat.
            snap = _enrich_historical_metadata(
                [sq_aggregator.BrokerSnapshot(broker=broker_label,
                                              snapshot=snap)],
                live_instruments)[0].snapshot
        positions_value, total_cash = _components_at(
            broker_label, snap, sd, base_currency,
            price_provider=price_provider, fx_provider=fx_provider)
        value_series.append((sd, positions_value + total_cash))

    cash_flow_series = [
        (sd, flow_by_date.get(sd, Decimal("0"))) for sd in sample_dates
    ]
    return value_series, cash_flow_series


def _components_at(broker_label, snap, sd, base_currency, *,
                   price_provider, fx_provider):
    """Value ONE broker snapshot at sample date `sd`: MTM-overlay the positions
    and convert ALL cash legs to `base_currency` at that date. Returns
    `(positions_value, total_cash)` as Decimals in `base_currency`.

    Cash is the COMPOSITE across currencies — Degiro's auto-FX can leave
    individual ccy buckets negative while the composite is positive; summing
    only the base bucket would report negative cash that isn't real.
    Unconvertible legs are dropped (rare; declared honestly by callers)."""
    ws = _overlay_historical_prices(
        [sq_aggregator.BrokerSnapshot(broker=broker_label, snapshot=snap)],
        sd,
        price_provider=price_provider,
        fx_provider=fx_provider,
    )[0].snapshot
    positions_value = sum((p.value_base for p in ws.positions), Decimal("0"))
    total_cash = Decimal("0")
    for c in ws.cash_balances:
        if c.amount == 0:
            continue
        if c.currency == base_currency:
            total_cash += c.amount
            continue
        converted = None
        if fx_provider is not None:
            rate = _get_rate_at(fx_provider, c.currency, base_currency,
                                sd.date())
            if rate is not None:
                converted = c.amount * rate.rate
        if converted is not None:
            total_cash += converted
    return positions_value, total_cash


def _export_age_days(broker_label) -> Optional[float]:
    """Days since the broker's history FILES were last written (export/sync) —
    via the bundle's `history_dir` capability. None when unknowable. This — not
    the last-transaction date — is the honest staleness signal: a file synced
    today whose last activity was months ago is CURRENT (a quiet account),
    while an old file is stale regardless of its content."""
    broker, account = _broker_label_split(broker_label)
    try:
        mod = importlib.import_module("sq_" + broker.replace("-", "_"))
    except Exception:                                           # noqa: BLE001
        return None
    hd = getattr(mod, "history_dir", None)
    if not callable(hd):
        return None
    try:
        d = hd(account=account)
        mts = [f.stat().st_mtime for f in d.iterdir()
               if f.is_file() and not f.name.endswith(".bak")]
        if not mts:
            return None
        return (time.time() - max(mts)) / 86400
    except Exception:                                           # noqa: BLE001
        return None


def _history_status(brokers):
    """Per CONNECTED broker: can it provide transaction history, and how fresh?
    Returns [(label, state, detail)] — state ∈ {"ok","stale","missing",
    "unsupported"}; detail = last-txn date (ok/stale) or the expected drop-dir
    (missing, when the bundle exposes `history_dir`). Staleness keys off the
    export FILES' age (`_export_age_days`) when knowable — a freshly synced file
    with old last-activity is ok; the last-txn date is only the fallback signal.
    This drives the VISIBLE warnings in the summary: history powering
    XIRR/TWR/daily must never degrade silently again."""
    from datetime import timedelta, timezone as _tz
    today = datetime.now(_tz.utc).date()
    out = []
    for b in brokers:
        if not b.ok:
            continue
        broker, account = _broker_label_split(b.broker)
        try:
            mod = importlib.import_module("sq_" + broker.replace("-", "_"))
        except Exception:                                       # noqa: BLE001
            continue
        load_history = getattr(mod, "load_history", None)
        if not callable(load_history):
            out.append((b.broker, "unsupported", None))
            continue
        try:
            txns = _call_with_account(load_history, account)
        except Exception:                                       # noqa: BLE001
            txns = None
        if not txns:
            where = None
            hd = getattr(mod, "history_dir", None)
            if callable(hd):
                try:
                    where = str(hd(account=account))
                except Exception:                               # noqa: BLE001
                    where = None
            out.append((b.broker, "missing", where))
            continue
        ends = max(t.executed_at for t in txns).date()
        age = _export_age_days(b.broker)
        # Staleness ("re-export to refresh") only applies to CSV-EXPORT connectors
        # (those with a drop dir): their data ages with the file. A connector that
        # returns LIVE history — an API broker, or the synthetic demo — has no file
        # to refresh, so an old last-transaction just means "no recent activity",
        # not stale. Never nag those.
        has_export = callable(getattr(mod, "history_dir", None))
        if age is not None:
            state = "stale" if age > 7 else "ok"
        elif has_export:
            state = "stale" if ends < today - timedelta(days=7) else "ok"
        else:
            state = "ok"
        out.append((b.broker, state, ends))
    return out


# ── daily portfolio history ─────────────────────────────────────────────────
def _daily_pnl_rows(series, flows_by_day):
    """Pure assembly of the daily-history rows. `series` is an ASCENDING list of
    `(date, net_worth, holdings, cash)` Decimals; `flows_by_day` maps date →
    net external flow (DEPOSIT − WITHDRAWAL) that day. Returns rows for
    series[1:]: `(date, net_worth, holdings, cash, flow, day_pnl)` where

        day_pnl = Δ net_worth − net_flow

    — i.e. the day's INVESTMENT P&L, with contributions/withdrawals stripped
    out (a deposit isn't a gain). The first sample exists only to anchor the
    first Δ and is not emitted."""
    rows = []
    for prev, cur in zip(series, series[1:]):
        d, nw, hold, cash = cur
        flow = flows_by_day.get(d, Decimal("0"))
        rows.append((d, nw, hold, cash, flow, nw - prev[1] - flow))
    return rows


def _sample_dates_daily(days):
    """ASCENDING end-of-day sample datetimes for the last `days` days (+1
    anchor for the first Δ). Today clamps to now ("so far")."""
    from datetime import time as _time, timedelta, timezone as _tz
    now = datetime.now(_tz.utc)
    out = []
    for back in range(days, -1, -1):
        day = (now - timedelta(days=back)).date()
        dt = datetime.combine(day, _time(23, 59, 59), tzinfo=_tz.utc)
        out.append(min(dt, now))
    return out


def _sample_dates_weekly(weeks):
    """ASCENDING end-of-day samples one week apart for the last `weeks`
    weeks (+1 anchor for the first Δ). Today clamps to now."""
    from datetime import time as _time, timedelta, timezone as _tz
    now = datetime.now(_tz.utc)
    out = []
    for back in range(weeks, -1, -1):
        day = (now - timedelta(weeks=back)).date()
        dt = datetime.combine(day, _time(23, 59, 59), tzinfo=_tz.utc)
        out.append(min(dt, now))
    return out


def _month_end(year, month):
    from datetime import time as _time, timedelta, timezone as _tz
    from datetime import date as _date
    first_next = (_date(year + 1, 1, 1) if month == 12
                  else _date(year, month + 1, 1))
    return datetime.combine(first_next - timedelta(days=1),
                            _time(23, 59, 59), tzinfo=_tz.utc)


def _sample_dates_monthly(months):
    """Month-end samples for the last `months` complete months, an anchor
    month-end before them, and `now` (the current month-to-date)."""
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    y, m = now.year, now.month
    out = [now]                                       # current month, partial
    for _ in range(months):                           # complete months + anchor
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(_month_end(y, m))
    return sorted(out)


def _sample_dates_yearly(first_year):
    """Year-end samples from `first_year` (anchored the Dec-31 before it, where
    the portfolio is zero) through last year, plus `now` (year-to-date)."""
    from datetime import timezone as _tz
    now = datetime.now(_tz.utc)
    out = [_month_end(y, 12) for y in range(first_year - 1, now.year)]
    out.append(now)
    return out


def _earliest_txn_year(brokers):
    """First activity year across history-capable brokers (None if none)."""
    years = []
    for b in brokers:
        if not b.ok:
            continue
        broker, account = _broker_label_split(b.broker)
        try:
            mod = importlib.import_module("sq_" + broker.replace("-", "_"))
            lh = getattr(mod, "load_history", None)
            if not callable(lh):
                continue
            txns = _call_with_account(lh, account)
            if txns:
                years.append(min(t.executed_at for t in txns).year)
        except Exception:                                       # noqa: BLE001
            continue
    return min(years) if years else None


def _build_state_series(brokers, display_ccy, dates):
    """Portfolio state at each ASCENDING sample datetime in `dates`, in
    `display_ccy`: `(rows, covered, skipped, ends)` where rows are
    `(date, net_worth, holdings, cash, flow, pnl)` Decimals summed across every
    HISTORY-CAPABLE broker (one exposing `load_history` + `snapshot`;
    `snapshots_at` batched when available). The first sample only anchors the
    first Δ. Brokers without history land in `skipped` — coverage stays honest.

    Each broker-sample is valued in the broker's base ccy (`_components_at`:
    batched fold + MTM overlay via the cached Yahoo/ECB providers) then
    converted to `display_ccy` at that date. P&L per row excludes external
    flows (see `_daily_pnl_rows`); flows convert at their OWN date and bucket
    into the interval `(prev_sample, sample]` — so a granularity is just a
    different `dates` list (daily / month-ends / year-ends)."""
    from bisect import bisect_left
    from sq_schema import TransactionType

    price_provider, fx_provider = _make_market_data_providers()
    # Live instrument metadata (tickers, listing ccy) for enriching the sparse
    # CSV-fold instruments — without it the MTM overlay can't resolve a price
    # and the series silently rides the cost surrogate (FX-only movement).
    live_instruments = {b.broker: b.snapshot.instruments
                        for b in brokers if b.ok}
    nw = {d: Decimal("0") for d in dates}
    hold = dict(nw)
    cash = dict(nw)
    flows: dict = {}
    covered, skipped = [], []
    ends: dict = {}                       # broker → last txn date in its export

    for b in brokers:
        if not b.ok:
            continue
        broker, account = _broker_label_split(b.broker)
        try:
            mod = importlib.import_module("sq_" + broker.replace("-", "_"))
        except Exception:                                       # noqa: BLE001
            skipped.append(b.broker)
            continue
        load_history = getattr(mod, "load_history", None)
        snapshot_fn = getattr(mod, "snapshot", None)
        if not (callable(load_history) and callable(snapshot_fn)):
            skipped.append(b.broker)
            continue
        try:
            txns = _call_with_account(load_history, account)
        except Exception:                                       # noqa: BLE001
            skipped.append(b.broker)
            continue
        if not txns:
            skipped.append(b.broker)
            continue
        base_ccy = b.snapshot.account.base_currency

        snapshots_at_fn = getattr(mod, "snapshots_at", None)
        batched: dict = {}
        if callable(snapshots_at_fn):
            try:
                batched = _call_with_account(snapshots_at_fn, account, dates)
            except Exception:                                   # noqa: BLE001
                batched = {}

        def _disp(amount, sd):
            """Convert `amount` from this broker's base ccy → display, at-date."""
            if base_ccy == display_ccy or amount == 0:
                return amount
            if fx_provider is None:
                return None
            rate = _get_rate_at(fx_provider, base_ccy, display_ccy,
                                sd.date())
            return amount * rate.rate if rate is not None else None

        ok_all = True
        for sd in dates:
            snap = batched.get(sd)
            if snap is None:
                try:
                    snap = _call_with_account(snapshot_fn, account, sd)
                except Exception:                               # noqa: BLE001
                    ok_all = False
                    break
            # Enrich sparse CSV instruments with live metadata (+ OpenFIGI
            # yahoo_ticker) so the overlay can actually price them.
            snap = _enrich_historical_metadata(
                [sq_aggregator.BrokerSnapshot(broker=b.broker, snapshot=snap)],
                live_instruments)[0].snapshot
            pv, tc = _components_at(b.broker, snap, sd, base_ccy,
                                    price_provider=price_provider,
                                    fx_provider=fx_provider)
            pv_d, tc_d = _disp(pv, sd), _disp(tc, sd)
            if pv_d is None or tc_d is None:                    # no FX rate
                ok_all = False
                break
            nw[sd] += pv_d + tc_d
            hold[sd] += pv_d
            cash[sd] += tc_d
        if not ok_all:
            skipped.append(b.broker)
            continue
        covered.append(b.broker)
        ends[b.broker] = max(t.executed_at for t in txns).date()

        # External flows bucket into the interval (prev_sample, sample] —
        # converted to display ccy at their OWN date. Interval (not same-day)
        # bucketing is what makes monthly/yearly P&L correct.
        for t in txns:
            if t.type not in (TransactionType.DEPOSIT,
                              TransactionType.WITHDRAWAL):
                continue
            ts = t.executed_at
            if ts <= dates[0] or ts > dates[-1]:
                continue
            sd = dates[bisect_left(dates, ts)]        # first sample ≥ ts
            amt = t.amount
            if t.amount_currency != display_ccy:
                if fx_provider is None:
                    continue                                   # drop unconvertible
                rate = _get_rate_at(fx_provider, t.amount_currency,
                                    display_ccy, ts.date())
                if rate is None:
                    continue
                amt = amt * rate.rate
            flows[sd] = flows.get(sd, Decimal("0")) + amt

    if not covered:
        return [], covered, sorted(set(skipped)), ends
    series = [(d, nw[d], hold[d], cash[d]) for d in dates]
    return _daily_pnl_rows(series, flows), covered, sorted(set(skipped)), ends


def _state_section(rows, display_ccy, *, title, period_h, label_fn,
                   minimal_header: bool = False) -> str:
    """One granularity's table (most recent first): period, net worth,
    holdings, net cash, flows, P/L. `label_fn(sample_dt, is_partial)` renders
    the period label; the LAST row (sampled at `now`) is the partial period.

    A net-worth area chart + per-period P/L bar strip render ABOVE the
    table (rows are chronological left→right, matching reading order for
    charts even though the table lists most-recent first). Pure text —
    works in dumps, pipes and NO_COLOR."""
    body_rows = []
    last = rows[-1][0]
    for d, nw_v, hold_v, cash_v, flow, p in reversed(rows):
        body_rows.append([
            label_fn(d, d == last),
            f"{nw_v:,.2f}",
            f"{hold_v:,.2f}",
            f"{cash_v:,.2f}",
            (f"{flow:+,.2f}" if flow else "—"),
            pnl(p),
        ])
    chart_block = _chart_block(rows, display_ccy, title, label_fn,
                               minimal=minimal_header)
    table = format_table(
        [period_h, f"net worth ({display_ccy})", "holdings", "net cash",
         "flows", "P/L"],
        body_rows, align=["l", "r", "r", "r", "r", "r"],
        # The chart header carries the title; avoid printing it twice.
        title=None if chart_block else title)
    if not chart_block:
        return table
    return chart_block + "\n\n" + table


def _chart_block(rows, display_ccy, title, label_fn,
                 minimal: bool = False) -> str:
    """The chart half of a history view — net-worth line + per-period
    P/L bars, NO table. Shared by the history sub-tabs and the home
    page's embedded chart. `minimal=True` renders a single all-dim
    header ("net worth (USD) │ daily") — used wherever a range
    selector ABOVE the chart already names the range (home, the
    history sub-tabs); the full bold title stays for the stacked
    `--history` CLI dump where it's the only identity a section has.
    "" when the series is too short to chart."""
    nw_series = [r[1] for r in rows]
    pl_series = [r[5] for r in rows]
    chart = render_chart(
        nw_series,
        x_left=label_fn(rows[0][0], False),
        x_right=label_fn(rows[-1][0], True),
    )
    if not chart:
        return ""
    if minimal:
        freq = title.split("—")[-1].strip()
        head_line = f"  {DIM}net worth ({display_ccy}) │ {freq}{RST}"
    else:
        head_line = (f"  {BOLD}{title}{RST}  "
                     f"{DIM}net worth ({display_ccy}){RST}")
    parts = [
        head_line,
        "",
        chart,
    ]
    bars = render_pl_bars(pl_series)
    if bars:
        parts += ["", f"  {DIM}P/L per period{RST}", bars]
    return "\n".join(parts)


def _coverage_note(covered, skipped) -> str:
    """Reference info for the ? help overlay: which accounts the series covers,
    which are excluded (no history), and the P&L definition."""
    return (f"  {DIM}covers {', '.join(covered)}"
            + (f"\n  no history (excluded): {', '.join(skipped)}" if skipped
               else "")
            + f"\n  P/L = Δ net worth − deposits/withdrawals{RST}")


def _stale_warning(ends) -> str:
    """The ⚠ stale-export warning — ACTIONABLE, so it stays IN the body (never
    hidden behind ? help). Staleness keys off the export FILES' age (a freshly
    synced file with old last-activity is a quiet account, not a stale export);
    empty string when everything is current."""
    from datetime import timedelta as _td, timezone as _tz
    today = datetime.now(_tz.utc).date()
    stale = []
    for b, d in sorted(ends.items()):
        if d >= today - _td(days=7):
            continue                       # recent activity → certainly current
        age = _export_age_days(b)
        if age is not None and age <= 7:
            continue                       # files freshly synced → current,
        stale.append(f"{b} export ends {d.isoformat()}")  # just a quiet account
    if not stale:
        return ""
    return "  " + warn_line(f"{' · '.join(stale)} — later rows are that state "
                            f"marked-to-market; re-export/sync the CSVs to "
                            f"refresh")


# Yahoo-style range selectors for the history sub-tabs. Sampling
# frequency by horizon (owner spec 2026-06-12): DAILY up to 1Y (incl.
# YTD), WEEKLY for 5Y, MONTHLY for All time.
HISTORY_RANGES = ("1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "All")

_DAY_LABEL = lambda d, partial: d.date().isoformat()              # noqa: E731
_MONTH_LABEL = (lambda d, partial: d.strftime("%Y-%m")            # noqa: E731
                + (" (mtd)" if partial else ""))


def _range_spec(kind, brokers):
    """(dates, title, period_h, label_fn) for a history range — the
    Yahoo-style labels, plus the legacy CLI vocabulary (`daily(N)` for
    `--history N`; `monthly`/`yearly` kept for the stacked dump).
    Returns None when the range needs txn history and none exists."""
    from datetime import date as _date, timezone as _tz
    now = datetime.now(_tz.utc)
    daily = {
        "1D": 1, "5D": 5, "1M": 30, "6M": 182, "1Y": 365,
        "YTD": max(1, (now.date() - _date(now.year, 1, 1)).days),
    }
    if kind in daily:
        n = daily[kind]
        return (_sample_dates_daily(n), f"{kind} — daily", "date",
                _DAY_LABEL)
    if kind == "5Y":
        return (_sample_dates_weekly(5 * 52), "5Y — weekly", "week ending",
                _DAY_LABEL)
    if kind == "All":
        first_year = _earliest_txn_year(brokers)
        if first_year is None:
            return None
        months = (now.year - first_year) * 12 + now.month
        return (_sample_dates_monthly(months), "All — monthly", "month",
                _MONTH_LABEL)
    return None


def _intraday_rows(legs, bars_by_ticker, cash_total):
    """Pure intraday net-worth series. `legs` = [(ticker, qty, fx)] with
    fx converting the BAR currency → display; `bars_by_ticker` =
    {ticker: {datetime: Decimal}}. Positions and cash are held CONSTANT
    across the day (transactions are daily-resolution) — the series is
    price movement only, which is exactly what a 1D chart shows.

    Grid = union of bar times from the latest first-bar onward (so every
    leg has a price at every grid point, forward-filled). Returns
    `[(dt, net_worth, holdings, cash, None, day_pnl)]` where day_pnl is
    the Δ vs the previous bar."""
    if not legs or not bars_by_ticker:
        return []
    series = {t: sorted(bars.items()) for t, bars in bars_by_ticker.items()
              if bars}
    if not series or any(t not in series for t, _, _ in legs):
        return []
    start = max(bars[0][0] for bars in series.values())
    grid = sorted({dt for bars in series.values()
                   for dt, _ in bars if dt >= start})
    if len(grid) < 2:
        return []
    idx = {t: 0 for t in series}
    last_px = {t: None for t in series}
    rows = []
    prev_nw = None
    for ts in grid:
        for t, bars in series.items():
            i = idx[t]
            while i < len(bars) and bars[i][0] <= ts:
                last_px[t] = bars[i][1]
                i += 1
            idx[t] = i
        holdings = sum((qty * last_px[t] * fx for t, qty, fx in legs),
                       Decimal("0"))
        nw = holdings + cash_total
        pnl = (nw - prev_nw) if prev_nw is not None else Decimal("0")
        prev_nw = nw
        rows.append((ts, nw, holdings, cash_total, None, pnl))
    return rows


_TIME_LABEL = lambda d, partial: d.strftime("%H:%M")          # noqa: E731


def history_chart_block(brokers, display_ccy, range_label: str):
    """Chart + P/L bars for a history range, NO table — the home page's
    embedded chart. Returns a multi-line ANSI string or None (range
    uncomputable). SLOW for long ranges (builds the value series) —
    callers compute off the paint path and cache.

    Composable-doctrine anchor: builds the `sciqnt.history/v1` DATA
    payload first, then renders it via the `sq_tui.render_history`
    adapter — the home chart consumes the exact surface `--json` ships,
    so a web chart is a peer of this one, not a port."""
    payload = history_json(brokers, display_ccy, range_label)
    if not payload["rows"]:
        return None
    return sq_tui_render_history(payload)


def chart_skeleton(display_ccy, range_label: str) -> str:
    """A dim placeholder with the SAME footprint as the real chart block
    — rendered while the series computes so the home layout doesn't
    jump (seamless-loading skeleton, owner spec 2026-06-12)."""
    freq = {"1D": "5-minute bars", "5Y": "weekly",
            "All": "monthly"}.get(range_label, "daily")
    width, height = 60, 6
    gut = " " * 7
    rows = [f"  {DIM}net worth ({display_ccy}) │ {freq}{RST}", ""]
    mid = height // 2
    for r in range(height):
        edge = "┤" if r in (0, height - 1) else "│"
        fill = ("⠒" * width) if r == mid else (" " * width)
        rows.append(f"  {DIM}{gut}{edge}{fill}{RST}")
    rows.append(f"  {DIM}{gut}╰{'─' * width}{RST}")
    rows.append(f"  {DIM}{gut}  loading {range_label}…{RST}")
    rows.append("")
    rows.append(f"  {DIM}P/L per period{RST}")
    for r in range(4):
        edge = "┤" if r in (0, 3) else "│"
        fill = ("⠂" * width) if r == 1 else (" " * width)
        rows.append(f"  {DIM}{gut}{edge}{fill}{RST}")
    return "\n".join(rows)


def _intraday_legs_and_rows(brokers, display_ccy):
    """Rows-only variant of `_intraday_section` (the home chart needs
    the series without the table/notes). None when unavailable."""
    out = _intraday_section(brokers, display_ccy, rows_only=True)
    return out


def _intraday_section(brokers, display_ccy, rows_only: bool = False):
    """The 1D view: today's OPEN holdings valued across 5-minute bars
    (the common 1D-chart feed). Returns `(body, note)` or None when
    intraday data isn't available — the caller falls back to the daily
    two-point view. Honest model: positions and cash held constant at
    the current snapshot; FX at the current rate (both in the ? note)."""
    price_provider, fx_provider = _make_market_data_providers()
    if price_provider is None or not hasattr(price_provider, "get_intraday"):
        return None
    legs, tickers = [], {}
    cash_total = Decimal("0")
    for b in brokers:
        if not b.ok:
            continue
        inst_by_id = {i.instrument_id: i for i in b.snapshot.instruments}
        for pos in b.snapshot.positions:
            if not pos.is_open:
                continue
            inst = inst_by_id.get(pos.instrument_id)
            if inst is None:
                continue
            ticker = inst.identifiers.get("yahoo_ticker")
            if not ticker:
                # Live snapshots carry the bare exchange ticker (IB01) —
                # not a Yahoo symbol. Resolve the suffixed form via the
                # OpenFIGI disk cache, exactly like the MTM overlay path.
                meta = _openfigi_lookup(inst)
                ticker = ((meta or {}).get("yahoo_ticker")
                          or inst.identifiers.get("ticker"))
            if not ticker:
                continue
            tickers.setdefault(ticker, [])
            tickers[ticker].append(pos.quantity)
        for c in b.snapshot.cash_balances:
            if c.amount == 0:
                continue
            if c.currency == display_ccy:
                cash_total += c.amount
            elif fx_provider is not None:
                rate = fx_provider.get_rate(c.currency, display_ccy)
                if rate is not None:
                    cash_total += c.amount * rate.rate
    if not tickers:
        return None
    bars_by_ticker = {}
    for ticker, qtys in tickers.items():
        got = price_provider.get_intraday(ticker)
        if got is None:
            return None                      # one unpriceable leg → fall back
        bars, ccy = got
        fx = Decimal("1")
        if ccy != display_ccy:
            if fx_provider is None:
                return None
            rate = fx_provider.get_rate(ccy, display_ccy)
            if rate is None:
                return None
            fx = rate.rate
        bars_by_ticker[ticker] = bars
        legs.append((ticker, sum(qtys, Decimal("0")), fx))
    rows = _intraday_rows(legs, bars_by_ticker, cash_total)
    if len(rows) < 2:
        return None
    if rows_only:
        return rows
    body = _state_section(
        rows, display_ccy, title="1D — 5-minute bars", period_h="time",
        label_fn=_TIME_LABEL, minimal_header=True)
    note = (f"  {DIM}intraday model: today's open holdings × 5-min bars; "
            f"positions + cash held constant at the current snapshot "
            f"(intraday trades/flows not reflected); FX at the current "
            f"rate{RST}")
    return body, note


def _history_granularity(brokers, display_ccy, kind, *, days=30, months=12) -> str:
    """ONE history range — the body of a SUB-TAB (1D/5D/1M/6M/YTD/1Y/5Y/
    All), each computed lazily only when opened. The legacy kinds
    (daily/monthly/yearly) remain for the `--history` CLI dump."""
    if kind == "1D":
        intraday = _intraday_section(brokers, display_ccy)
        if intraday is not None:
            return intraday
        # No intraday data (market closed and cache cold, no priceable
        # legs, …) → honest fallback to the daily two-point view.
        spec = _range_spec(kind, brokers)
        dates, title, period_h, label_fn = spec
        title += " (daily fallback — no intraday bars)"
    elif kind == "daily":
        dates = _sample_dates_daily(days)
        title, period_h = f"daily — last {days} days", "date"
        label_fn = _DAY_LABEL
    elif kind == "monthly":
        dates = _sample_dates_monthly(months)
        title, period_h = f"monthly — last {months} months", "month"
        label_fn = _MONTH_LABEL
    elif kind == "yearly":
        first_year = _earliest_txn_year(brokers)
        if first_year is None:
            return ("  (no history — no connected broker exposes transaction "
                    "history yet)", "")
        dates = _sample_dates_yearly(first_year)
        title, period_h = "yearly — all time", "year"
        label_fn = (lambda d, partial: str(d.year)                # noqa: E731
                    + (" (ytd)" if partial else ""))
    else:
        spec = _range_spec(kind, brokers)
        if spec is None:
            return ("  (no history — no connected broker exposes transaction "
                    "history yet)", "")
        dates, title, period_h, label_fn = spec

    rows, covered, skipped, ends = _build_state_series(brokers, display_ccy,
                                                       dates)
    if not rows:
        return ("  (no history — no connected broker exposes transaction "
                "history yet)", "")
    body = _state_section(rows, display_ccy, title=title, period_h=period_h,
                          label_fn=label_fn,
                          minimal_header=kind in HISTORY_RANGES)
    warn = _stale_warning(ends)
    if warn:
        body += "\n\n" + warn
    return body, _coverage_note(covered, skipped)


def _history_state_tab(brokers, display_ccy, *, days=30, months=12) -> str:
    """All three granularities stacked — the NON-INTERACTIVE surface
    (`sciqnt --history`); the TUI shows them as sub-tabs instead."""
    parts = []
    for kind in ("daily", "monthly", "yearly"):
        body, note = _history_granularity(brokers, display_ccy, kind,
                                          days=days, months=months)
        parts.append(body + (("\n\n" + note) if note else ""))
    return "\n\n".join(parts)


def _flows_data(brokers) -> list[dict]:
    """The DATA half of the flows view: per-account year-bucketed deposits /
    withdrawals / dividends / fees / realised P/L (each account in its OWN
    base ccy; foreign-ccy income named, never raw-summed — audit 2026-06-11).
    Capability-based: any broker module exposing `load_history()` is queried.
    Shared by the rendered tab and the `--json --tab flows` surface.
    Entries: {account, base_currency, years: [{year, deposits, withdrawals,
    dividends, fees, realized_pl}], foreign_income_currencies, error?}."""
    out: list[dict] = []
    zero = Decimal("0")
    for b in brokers:
        if not b.ok:
            continue
        broker, account = _broker_label_split(b.broker)
        mod_name = "sq_" + broker.replace("-", "_")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        load_history = getattr(mod, "load_history", None)
        if not callable(load_history):
            continue
        try:
            txns = _call_with_account(load_history, account)
        except Exception as e:                                  # noqa: BLE001
            out.append({"account": b.broker, "base_currency": None,
                        "years": [], "foreign_income_currencies": [],
                        "error": f"{type(e).__name__}: {e}"})
            continue
        if not txns:
            continue

        base_ccy = b.snapshot.account.base_currency
        cf   = sq_analytics.cash_flow_over_time(
            txns, group_by="year", currency=base_ccy)
        divs = sq_analytics.dividend_history(txns, group_by="year",
                                             currency=base_ccy)
        fees = sq_analytics.fee_history(txns, group_by="year",
                                        currency=base_ccy)
        foreign_ccys = sorted({
            t.amount_currency for t in txns
            if t.amount_currency != base_ccy
            and t.type in (TransactionType.DIVIDEND, TransactionType.FEE,
                           TransactionType.INTEREST)
        })
        rpl  = sq_analytics.realized_pl_over_time(
            txns, base_currency=base_ccy, group_by="year",
            method=_cost_basis_method())
        years = sorted(set(cf) | set(divs) | set(fees) | set(rpl))
        if not years:
            continue
        out.append({
            "account": b.broker,
            "base_currency": base_ccy,
            "years": [
                {"year": y,
                 "deposits": (cf.get(y) or {}).get("DEPOSIT", zero),
                 "withdrawals": (cf.get(y) or {}).get("WITHDRAWAL", zero),
                 "dividends": divs.get(y, zero),
                 "fees": fees.get(y, zero),
                 "realized_pl": rpl.get(y, zero)}
                for y in years],
            "foreign_income_currencies": foreign_ccys,
        })
    return out


def _flows_tab(brokers, root) -> str | None:
    """The RENDERED flows view over `_flows_data` — year-bucketed tables per
    account. Returns None if no broker contributed history (tab dropped)."""
    sections: list[str] = []
    for acct in _flows_data(brokers):
        if acct.get("error"):
            sections.append(f"  {acct['account']}: (history load failed: "
                            f"{acct['error']})")
            continue
        years, base_ccy = acct["years"], acct["base_currency"]
        rows = [[str(y["year"]), _fmt_num(y["deposits"]),
                 _fmt_num(y["withdrawals"]), _fmt_num(y["dividends"]),
                 _fmt_num(y["fees"]), _fmt_signed(y["realized_pl"])]
                for y in years]
        zero = Decimal("0")
        rows.append([
            "TOTAL",
            _fmt_num(sum((y["deposits"] for y in years), zero)),
            _fmt_num(sum((y["withdrawals"] for y in years), zero)),
            _fmt_num(sum((y["dividends"] for y in years), zero)),
            _fmt_num(sum((y["fees"] for y in years), zero)),
            _fmt_signed(sum((y["realized_pl"] for y in years), zero)),
        ])
        section = format_table(
            ["year", "deposits", "withdrawals", "dividends", "fees",
             f"realised ({base_ccy})"],
            rows, align=["l", "r", "r", "r", "r", "r"],
            title=f"{acct['account']} — by year ({base_ccy}; "
                  f"from data/{acct['account']}/)",
        )
        if acct["foreign_income_currencies"]:
            section += (f"\n  {DIM}+ income/fees in "
                        f"{', '.join(acct['foreign_income_currencies'])} "
                        f"not in this table — see the summary's income "
                        f"lines (FX-converted){RST}")
        sections.append(section)

    if not sections:
        return None
    return "\n\n".join(sections)


def _detailed_tab(agg) -> str:
    """Per-broker subtotals in long form — same numbers as the summary
    table but laid out one section per broker, easier to read when N is
    large."""
    if not agg.per_broker:
        return "  (no broker contributed data)"
    sections = []
    for pb in agg.per_broker:
        kv = [
            ("base currency",         pb["base_currency"]),
            ("positions value",       f"{_fmt_num(pb['positions_value_base'])} {pb['base_currency']}"),
            ("realised P/L",          f"{_fmt_signed(pb['realized_pl_base'])} {pb['base_currency']}"),
            ("unrealised P/L (now)",  f"{_fmt_signed(pb['unrealized_pl_base'])} {pb['base_currency']}"),
            ("total P/L (lifetime)",  f"{_fmt_signed(pb['total_pl_lifetime'])} {pb['base_currency']}"),
            ("open positions",        str(pb["open_position_count"])),
            ("closed positions",      str(pb["closed_position_count"])),
        ]
        sections.append(f"  {pb['broker']}\n" + format_kv(kv))
    return "\n\n".join(sections)


# ── the view ↔ CLI contract ───────────────────────────────────────────────
# Every tab build_aggregate emits is reproducible non-interactively; this
# DECLARES how. The default surface is `--once --tab {key}`; a tab whose CLI
# asymmetry is real (history has its own flag + sub-ranges) declares its own
# template here. Summon handoffs (home.view_facts) derive from THIS — never
# hand-enumerate the surface elsewhere (`sciqnt --help` is the user-facing
# self-description). A bundle-contributed tab joins by adding its key here
# alongside its build_aggregate entry.
TAB_SURFACES: dict = {
    "history": lambda sub: f"--history {sub or 'YTD'}",
}

# Contributed tabs (declare → derive): anything outside the platform — a
# bundle, a plugin, a user script — joins the portfolio view by REGISTERING,
# never by editing build_aggregate. The builder receives a ctx dict
# (root, brokers, agg, agg_positions, display_ccy, asof) and returns the tab
# body (str | (body, note) | {sub: body} | callable for lazy | None to skip
# this build). Registration order = display order after the core tabs.
TAB_REGISTRY: list = []          # [(key, builder)]


def register_tab(key: str, builder, *, surface=None) -> None:
    """Contribute a portfolio tab. `surface` (optional) declares the tab's
    own CLI template for summon reproduce-commands (sub -> "--flag ...");
    without it the tab gets the generic `--once --tab {key}` surface and
    needs NOTHING else — one declaration, everything derives."""
    TAB_REGISTRY[:] = [(k, b) for k, b in TAB_REGISTRY if k != key]
    TAB_REGISTRY.append((key, builder))
    if surface is not None:
        TAB_SURFACES[key] = surface


def view_command(*, account=None, tab=None, sub=None) -> str:
    """The exact CLI invocation reproducing a TUI view — derived from
    TAB_SURFACES, not hand-branched per screen."""
    if tab is None:
        cmd = "sciqnt --once"
    elif tab in TAB_SURFACES:
        cmd = "sciqnt " + TAB_SURFACES[tab](sub)
    else:
        cmd = f"sciqnt --once --tab {tab}"
    if account:
        import shlex
        cmd += f" --account {shlex.quote(account)}"
    return cmd


# ── the data surfaces (`--json`) ──────────────────────────────────────────
# The DATA-FIRST half of the contract: the same state every renderer draws,
# as versioned, structured JSON. The TUI (tables, braille charts) is ONE
# adapter over this; a web chart, another agent, or a notebook consumes the
# identical surface — presentation is a flavour, never the product. Money
# stays Decimal end-to-end and serialises as STRINGS (precision survives the
# wire; consumers opt into floats knowingly). Schema names are versioned so
# downstream builders can pin.
PORTFOLIO_SCHEMA = "sciqnt.portfolio/v1"
HISTORY_SCHEMA = "sciqnt.history/v1"


def _json_scalar(o):
    """json.dumps default: Decimal → str (NEVER float), dates → ISO."""
    if isinstance(o, Decimal):
        return format(o, "f")     # fixed-point: zero is "0.00000000", not "0E-8"
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"not JSON-serialisable: {type(o).__name__}")


_WIRE_QUANTUM = Decimal("0.00000001")


def _q8(v):
    """Quantize money for the wire — internal series carry full chained
    precision, but the SURFACE boundary ships clean 8dp (same discipline as
    positions; '0E-23' artifacts never reach a consumer)."""
    return v.quantize(_WIRE_QUANTUM) if isinstance(v, Decimal) else v


def portfolio_json(brokers, display_ccy, asof=None) -> dict:
    """The whole-portfolio data surface: totals + per-account subtotals +
    every position/instrument/cash leg in canonical (Pydantic) shape."""
    fx_provider = sq_fx.get_provider()
    agg = sq_aggregator.aggregate_value(
        brokers, display_currency=display_ccy, fx_provider=fx_provider)
    return {
        "schema": PORTFOLIO_SCHEMA,
        "asof": asof,
        "demo": any(b.broker.split(":")[0] == "demo"
                    for b in brokers if b.ok),
        "display_currency": display_ccy,
        "totals": {
            "net_worth": agg.total_value,
            "holdings": agg.positions_value,
            "net_cash": agg.cash_value,
            "realized_pl": agg.total_realized_pl,
            "unrealized_pl": agg.total_unrealized_pl,
            "total_pl_lifetime": agg.total_pl_lifetime,
            "open_positions": agg.open_position_count,
            "closed_positions": agg.closed_position_count,
        },
        "unconverted_cash": [
            {"account": b, "currency": c, "amount": a}
            for b, c, a in agg.unconverted_cash],
        "accounts": agg.per_broker,
        "positions": [
            {"account": broker, "position": p.model_dump(),
             "instrument": i.model_dump()}
            for broker, p, i in sq_aggregator.aggregate_positions(brokers)],
        "cash": [
            {"account": broker, **c.model_dump()}
            for broker, c in sq_aggregator.aggregate_cash(brokers)],
        "degraded": [
            {"account": b.broker, "error": b.error}
            for b in brokers if not b.ok],
    }


def history_json(brokers, display_ccy, kind) -> dict:
    """The history data surface: the SAME state series the TUI charts,
    as rows. `kind` = a HISTORY_RANGES label or int days (legacy daily)."""
    rows = None
    if kind == "1D":
        rows = _intraday_legs_and_rows(brokers, display_ccy)
    if rows is None:
        if isinstance(kind, int):
            dates = _sample_dates_daily(kind)
        else:
            spec = _range_spec(kind, brokers)
            dates = spec[0] if spec else None
        if dates is None:
            return {"schema": HISTORY_SCHEMA, "range": kind, "rows": [],
                    "display_currency": display_ccy,
                    "covers": [], "skipped": []}
        rows, covered, skipped, _ends = _build_state_series(
            brokers, display_ccy, dates)
    else:
        covered = [b.broker for b in brokers if b.ok]
        skipped = []
    return {
        "schema": HISTORY_SCHEMA,
        "range": kind,
        "display_currency": display_ccy,
        "rows": [{"date": r[0], "net_worth": _q8(r[1]),
                  "holdings": _q8(r[2]), "net_cash": _q8(r[3]),
                  "flows": _q8(r[4]), "pl_period": _q8(r[5])}
                 for r in rows],
        "covers": covered,
        "skipped": list(skipped),
    }


EXPOSURE_SCHEMA = "sciqnt.exposure/v1"
NEWS_SCHEMA = "sciqnt.news/v1"
FLOWS_SCHEMA = "sciqnt.flows/v1"


def exposure_json(brokers, display_ccy) -> dict:
    """Currency + asset-class exposure — the data the exposure tab renders."""
    _, fx_provider = _make_market_data_providers()
    ce = sq_aggregator.aggregate_currency_exposure(
        brokers, display_currency=display_ccy, fx_provider=fx_provider)
    ace, skipped = sq_aggregator.aggregate_asset_class_exposure(
        brokers, display_currency=display_ccy, fx_provider=fx_provider)
    return {
        "schema": EXPOSURE_SCHEMA,
        "display_currency": display_ccy,
        "by_currency": [{"currency": ccy, **{k: _q8(v) for k, v in p.items()}}
                        for ccy, p in sorted(ce.items())],
        "by_asset_class": [{"asset_class": ac,
                            **{k: _q8(v) for k, v in p.items()}}
                           for ac, p in sorted(ace.items())],
        "excluded": list(skipped),
    }


def news_json(brokers) -> dict:
    """Portfolio-joined headlines — the data the news tab renders.
    Context only; never an input to the numbers."""
    provider = _make_news_provider()
    agg_positions = sq_aggregator.aggregate_positions(brokers)
    got = (_portfolio_news(agg_positions, provider)
           if provider is not None else None)
    if provider is None:
        note = "no news source installed — add the sq-news-rss bundle"
    elif got is None:
        note = "no open positions with a known ticker"
    elif not got:
        note = "no headlines right now — sources may be unavailable"
    else:
        note = "context only — news feeds nothing in the money core"
    return {
        "schema": NEWS_SCHEMA,
        "by_ticker": [
            {"ticker": t, "items": [i.model_dump() for i in items]}
            for t, items in (got or [])],
        "note": note,
    }


def flows_json(brokers) -> dict:
    """Year-bucketed external flows + income per account — the data the
    flows tab renders. Each account in its OWN base currency."""
    accounts = []
    for acct in _flows_data(brokers):
        accounts.append({
            **{k: v for k, v in acct.items() if k != "years"},
            "years": [{k: (_q8(v) if k != "year" else v)
                       for k, v in y.items()} for y in acct["years"]],
        })
    return {"schema": FLOWS_SCHEMA, "accounts": accounts}


# tab → its data surface (declare → derive: `--json --tab X` dispatches
# from here; a tab absent from this map is either inside portfolio/v1
# already, or has no data form YET — the error says which).
TAB_DATA_SURFACES: dict = {
    "exposure": lambda brokers, ccy: exposure_json(brokers, ccy),
    "news":     lambda brokers, ccy: news_json(brokers),
    "flows":    lambda brokers, ccy: flows_json(brokers),
}


def emit_json(payload: dict) -> None:
    print(json.dumps(payload, default=_json_scalar, indent=1))


# ── entry point ───────────────────────────────────────────────────────────
def normalize_history_spec(spec):
    """Parse the `--history` value: an int / int-string = the legacy
    last-N-days stack; a range label (any case: ytd, 1y, all…) = ONE of the
    TUI's HISTORY_RANGES. Returns int | range-label | None (unrecognised)."""
    if isinstance(spec, int):
        return spec
    s = str(spec).strip()
    if s.isdigit():
        return int(s)
    by_upper = {r.upper(): r for r in HISTORY_RANGES}
    return by_upper.get(s.upper())


def select_account(brokers, account):
    """Filter snapshots to ONE account label (the `--account` CLI surface,
    mirroring the home's drill-down). Case-insensitive; a unique prefix
    also matches (`--account degiro:Dav`). Returns (selected, base_ccy) or
    (None, None) — the caller prints `account_labels()` on a miss."""
    ok = [b for b in brokers if b.ok]
    want = account.strip().lower()
    hit = [b for b in ok if b.broker.lower() == want]
    if not hit:
        pref = [b for b in ok if b.broker.lower().startswith(want)]
        hit = pref if len(pref) == 1 else []
    if not hit:
        return None, None
    return hit, hit[0].snapshot.account.base_currency


def account_labels(brokers) -> list[str]:
    return sorted(b.broker for b in brokers if b.ok)


def run_history(root, spec=30, *, account=None, as_json: bool = False,
                use_snapshot_cache: bool = True) -> int:
    """`sciqnt --history [N | RANGE]` — the non-interactive history surface
    (scripts and agents — the sq-portfolio skill — consume this).

    * `N` (days, default 30): the legacy stack — daily over the last N days,
      monthly over 12 months + mtd, yearly all time + ytd.
    * `RANGE` (1D/5D/1M/6M/YTD/1Y/5Y/All, any case): exactly the TUI's
      history sub-tab for that range — same table, same chart.
    * `account=LABEL`: one account only, in its OWN base currency
      (mirrors the home's account drill-down)."""
    kind = normalize_history_spec(spec)
    if kind is None:
        print(f"  unknown --history value {spec!r} — use a number of days or "
              f"one of: {', '.join(HISTORY_RANGES)}")
        return 2
    if as_json:
        # stdout IS the data surface — fetch chatter must not pollute it
        # (degraded brokers are reported inside the payload instead).
        with quiet():
            brokers = _collect_snapshots(
                root, use_snapshot_cache=use_snapshot_cache, only=account)
    else:
        brokers = _collect_snapshots(
            root, use_snapshot_cache=use_snapshot_cache, only=account)
    if not any(b.ok for b in brokers):
        if account is not None:
            print(f"  no connected account matches {account!r} — configured: "
                  + (", ".join(n for n, _ in _discover_brokers(root))
                     or "none"))
            return 2
        print("\n  No accounts connected yet — nothing to chart.")
        return 1
    display_ccy = sq_config.display_currency()
    if account is not None:
        brokers, display_ccy = select_account(brokers, account)
    if as_json:
        with quiet():
            payload = history_json(brokers, display_ccy, kind)
        emit_json(payload)
        return 0
    print()
    if isinstance(kind, int):
        print(_history_state_tab(brokers, display_ccy, days=kind))
    else:
        out = _history_granularity(brokers, display_ccy, kind)
        body, note = out if isinstance(out, tuple) else (out, "")
        print(body + (("\n\n" + note) if note else ""))
    print()
    return 0


def run_aggregated(
    root, *,
    asof: Optional[datetime] = None,
    account: Optional[str] = None,
    tab: Optional[str] = None,
    as_json: bool = False,
    use_snapshot_cache: bool = True,
) -> int:
    """Fetch + aggregate + render. Returns process exit code.

    When `asof` is given, each broker is asked for a PIT historical
    snapshot rather than current state. Brokers that don't support
    historical queries are downgraded with their reason.

    `account=LABEL` renders ONE account's view in its own base currency
    (the CLI mirror of the home's account drill-down). `tab=NAME` dumps
    just that tab (summary/positions/exposure/news/flows/detailed) —
    together these make every screen of the app reproducible by a script
    or agent.

    `use_snapshot_cache=False` (the `--fresh` CLI path) bypasses the
    current-state cache and always fetches live."""
    if tab is not None and tab.strip().lower() == "history":
        print("  the history tab has its own surface: "
              "sciqnt --history [1D|5D|1M|6M|YTD|1Y|5Y|All|DAYS]")
        return 2
    if as_json and tab is not None and \
            tab.strip().lower() not in TAB_DATA_SURFACES:
        print(f"  no separate data surface for tab {tab!r} — "
              "summary/positions/detailed live inside the whole-portfolio "
              "surface: sciqnt --json  (per-tab: "
              + ", ".join(sorted(TAB_DATA_SURFACES)) + ")")
        return 2
    if not use_snapshot_cache and asof is None:
        # `--fresh` semantics: invalidate any cached snapshot up front
        # so a write-through after this run reflects the live state.
        for name, _ in _discover_brokers(root):
            _cache.invalidate_snapshot(name)
    if as_json:
        with quiet():                      # stdout IS the data surface
            brokers = _collect_snapshots(
                root, asof=asof, use_snapshot_cache=use_snapshot_cache,
                only=account)
    else:
        brokers = _collect_snapshots(root, asof=asof,
                                     use_snapshot_cache=use_snapshot_cache,
                                     only=account)
    if account is not None and not any(b.ok for b in brokers):
        print(f"  no connected account matches {account!r} — configured: "
              + (", ".join(n for n, _ in _discover_brokers(root)) or "none"))
        return 2
    if not any(b.ok for b in brokers):
        # No CONNECTED accounts produced a snapshot. Distinguish "nothing
        # connected yet" (normal first-run) from "configured but all failed".
        available = _available_connectors(root)
        if not brokers:
            print("\n  No accounts connected yet.")
            if available:
                print("  Available connectors: " + ", ".join(available))
                print("  Connect one with:  sciqnt <broker> setup   "
                      "(e.g. sciqnt degiro setup)")
            else:
                print("  No broker bundles found under modules/.")
        else:
            print("\n  No connected broker responded:")
            for b in brokers:
                print(f"    · {b.broker}: {b.error}")
        return 1

    display_ccy = None
    if account is not None:
        brokers, display_ccy = select_account(brokers, account)

    if as_json:
        ccy = display_ccy or sq_config.display_currency()
        with quiet():
            if tab is not None:
                payload = TAB_DATA_SURFACES[tab.strip().lower()](brokers, ccy)
            else:
                payload = portfolio_json(brokers, ccy, asof=asof)
        emit_json(payload)
        return 0

    tabs, title, _agg = build_aggregate(root, brokers, asof=asof,
                                        display_currency=display_ccy)
    if tab is not None:
        by_lower = {k.lower(): k for k in tabs}
        key = by_lower.get(tab.strip().lower())
        if key is None:
            print(f"  unknown tab {tab!r} — one of: {', '.join(tabs)}, history")
            return 2
        tabs = {key: tabs[key]}
    # run_aggregated IS the non-interactive surface (`--once` / pipes / agents)
    # — always the sequential line dump, never the full-screen app.
    tabbed_view(tabs, title=title, interactive=False)
    return 0


def build_aggregate(root, brokers, *, asof: Optional[datetime] = None,
                    display_currency: Optional[str] = None,
                    daily: bool = False):
    """Pure-ish assembly: given collected `brokers`, build the rendered
    tabs dict + the view title + the `AggregatedValue`. Shared by
    `run_aggregated` (dump) and the interactive home (which shows a compact
    headline from the agg + opens the tabs on demand). Does the asof
    metadata-enrichment + price overlay when asof is set.

    `display_currency` overrides the config currency for THIS build — used to
    render a single-account drill-down in that account's OWN base currency
    (config display currency governs cross-account aggregation, not a single
    account's view). Defaults to the configured display currency.
    Returns `(tabs, title, agg)`."""
    # asof views are CSV-derived → sparse Instrument metadata (ISIN only).
    # Best-effort: pull instrument names / asset classes / tickers from
    # each broker's CURRENT live snapshot when available, so positions
    # show "Apple Inc / AAPL / STOCK" instead of "ISIN US0378331005 / OTHER".
    # Money is untouched; this is display enrichment only.
    #
    # Cache discipline: instrument metadata is ~static (names, asset
    # classes don't change intra-day). Use the on-disk cache for any
    # broker whose entry is <24h old; only fall back to a live fetch
    # when the cache misses. The live fetch is then written through
    # so the next run is instant.
    if asof is not None:
        instruments_by_broker: dict = {}
        need_live: list[str] = []
        for b in brokers:
            if not b.ok:
                continue
            cached = _cache.load_instrument_metadata(b.broker)
            if cached is not None:
                instruments_by_broker[b.broker] = cached
                age = _cache.cache_age_seconds(b.broker) or 0
                status(f"{b.broker} metadata: cached ({int(age // 60)}m ago)")
            else:
                need_live.append(b.broker)
        if need_live:
            status(f"fetching live metadata for {', '.join(need_live)}…")
            live = _collect_snapshots(root, asof=None)
            for lb in live:
                if not lb.ok or lb.broker not in need_live:
                    continue
                instruments_by_broker[lb.broker] = lb.snapshot.instruments
                _cache.save_instrument_metadata(
                    lb.broker, lb.snapshot.instruments)
        brokers = _enrich_historical_metadata(brokers, instruments_by_broker)
        # Now that metadata (incl. tickers) is on board, try true MTM at
        # the historical date — Yahoo for prices, ECB for FX. Best-effort:
        # positions without a known ticker keep the cost-basis surrogate
        # set by the historical fold.
        status(f"overlaying prices at {asof.date().isoformat()}…")
        brokers = _overlay_historical_prices(brokers, asof)

    display_ccy = display_currency or sq_config.display_currency()
    fx_provider = sq_fx.get_provider()
    agg = sq_aggregator.aggregate_value(
        brokers, display_currency=display_ccy, fx_provider=fx_provider,
    )
    agg_positions = sq_aggregator.aggregate_positions(brokers)

    # "summary" is LAZY (a callable; tabbed_view memoises): it computes
    # per-broker XIRR/TWR/drawdown over full value-and-flow series — network
    # MTM work that must NOT run on every home redraw / navigation (the home's
    # own headline uses `agg`, not this tab). quiet() keeps provider chatter
    # off the live screen (apps render to the real stdout — sq_tui/FINDINGS).
    # No quiet() here: tabbed_view computes lazy bodies in a worker thread and
    # STREAMS the status/stdout lines into a live progress panel instead.
    def _lazy_summary(_b=brokers, _a=agg, _c=display_ccy, _asof=asof):
        return _summary_tab(_b, _a, _c, asof=_asof)
    # "news" is LAZY too — headline fetches (one RSS hit per top holding)
    # only run when the tab is opened; results are process-cached.
    def _lazy_news(_p=agg_positions):
        return _news_tab(_p)
    tabs = {
        "summary":   _lazy_summary,
        "positions": _positions_tab(agg_positions),
        "exposure":  _exposure_tab(brokers, display_ccy),
        "news":      _lazy_news,
    }
    if daily:
        # LAZY (a callable) — the state folds + MTM only run when the tab is
        # opened (tabbed_view memoises it), so the home stays instant.
        # quiet() keeps provider chatter off the live screen (apps render to
        # the real stdout, so the swap is safe — see sq_tui/FINDINGS.md).
        def _lazy_gran(kind, _brokers=brokers, _ccy=display_ccy):
            def _go():
                return _history_granularity(_brokers, _ccy, kind)
            return _go
        tabs["history"] = {k: _lazy_gran(k) for k in HISTORY_RANGES}
    flows = _flows_tab(brokers, root)
    if flows is not None:
        tabs["flows"] = flows
    tabs["detailed"] = _detailed_tab(agg)
    # Contributed tabs (see register_tab): one ctx, every registered builder
    # gets its shot; None skips. A failing contribution degrades to a visible
    # error body — it must never poison the core view.
    if TAB_REGISTRY:
        ctx = {"root": root, "brokers": brokers, "agg": agg,
               "agg_positions": agg_positions, "display_ccy": display_ccy,
               "asof": asof}
        for key, builder in TAB_REGISTRY:
            try:
                body = builder(ctx)
            except Exception as e:                          # noqa: BLE001
                body = f"  (tab '{key}' failed: {type(e).__name__}: {e})"
            if body is not None:
                tabs[key] = body
    title = "sciqnt · portfolio"
    if asof is not None:
        title += f" · as of {asof.date().isoformat()}"
    if fx_provider is not None and display_ccy:
        title += (f" · {display_ccy} via "
                  f"{fx_provider.__class__.__name__.replace('Provider','').lower()}")
    return tabs, title, agg
