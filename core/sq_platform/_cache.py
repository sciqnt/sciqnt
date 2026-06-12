"""On-disk cache for things we don't want to refetch every invocation.

Two layers, each with its own TTL discipline:

  1. **Instrument metadata** (24h TTL) — name / asset_class / listing_ccy /
     identifiers per broker. These are ~static facts of the instrument
     (a name change or asset-class re-classification is rare). Used by
     the `--asof` view's display enrichment.

  2. **Current-state snapshot** (60s TTL) — the full live `PortfolioSnapshot`
     per broker. Used by `sciqnt` (no args) so a follow-up invocation
     30 seconds later is instant instead of a fresh 5-10s Degiro API
     round-trip. The age is ALWAYS shown to the user — staleness is
     visible, never hidden. `--fresh` on the dispatcher forces a refetch.

What we explicitly DO NOT cache:
  * The asof PIT snapshot itself — that's CSV-deterministic, cheap
    to recompute, and lives in the user's already-on-disk CSVs.

Files live under `~/.cache/sciqnt/` as plain JSON (inspectable, hand-
editable, deletable). Failure modes are deliberately silent: a
corrupted cache file just results in a miss, never an error to the
user. The cache is a UX optimisation, not a correctness primitive."""
import json
import os
import time
from pathlib import Path
from typing import Optional

from sq_schema import Instrument, PortfolioSnapshot


CACHE_DIR = Path.home() / ".cache" / "sciqnt"
META_CACHE_TTL_SECONDS     = 24 * 3600        # 24h — broker metadata is ~static
SNAPSHOT_CACHE_TTL_SECONDS = 60               # 60s — current-state freshness
OPENFIGI_CACHE_TTL_SECONDS = 30 * 24 * 3600   # 30d — ISIN facts barely change


def _safe_label(broker: str) -> str:
    """Cache filenames mustn't carry path-separator-ish characters. The
    broker label can be a qualified `degiro:work` for multi-account
    setups — rewrite `:` to `__` so filenames stay portable
    (macOS HFS+/APFS tolerate `:` but Finder and shell quoting both
    treat it specially; safer to neutralise)."""
    return broker.replace(":", "__")


def _meta_cache_path(broker: str) -> Path:
    return CACHE_DIR / f"instrument_metadata.{_safe_label(broker)}.json"


def _snapshot_cache_path(broker: str) -> Path:
    return CACHE_DIR / f"snapshot.{_safe_label(broker)}.json"


def load_instrument_metadata(broker: str) -> Optional[list[Instrument]]:
    """Return cached Instruments for `broker`, or None if missing / stale /
    corrupt. Silent on every failure mode — the cache is best-effort."""
    p = _meta_cache_path(broker)
    if not p.is_file():
        return None
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return None
    if age > META_CACHE_TTL_SECONDS:
        return None
    try:
        data = json.loads(p.read_text())
        return [Instrument.model_validate(d) for d in data]
    except Exception:
        return None


def save_instrument_metadata(broker: str, instruments: list[Instrument]) -> None:
    """Write `instruments` to disk as the metadata cache for `broker`.
    Best-effort: any I/O failure is silently swallowed (a write failure
    just means the next run misses the cache and refetches — no harm
    beyond a few extra seconds)."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _meta_cache_path(broker)
        # Pydantic's model_dump(mode="json") handles Decimal → str etc.
        payload = json.dumps(
            [i.model_dump(mode="json") for i in instruments],
            indent=2, sort_keys=True,
        )
        # Atomic write: write to a tempfile then rename so a partial
        # write doesn't leave a corrupt JSON behind on the cache path.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload)
        os.replace(tmp, p)
    except Exception:
        pass


def cache_age_seconds(broker: str) -> Optional[float]:
    """Age of the metadata cache file in seconds, or None if no cache
    exists. Used by the renderer to show "metadata cached Xm ago" so
    users know when they're looking at potentially-stale labels."""
    p = _meta_cache_path(broker)
    if not p.is_file():
        return None
    try:
        return time.time() - p.stat().st_mtime
    except OSError:
        return None


# ── current-state snapshot cache ──────────────────────────────────────────
# Pydantic v2 includes `@computed_field`s in `model_dump_json` but
# rejects them as "extra inputs" on `model_validate`. The JSON file is
# useful with the computed-field redundancy (human-inspectable values
# for derived P/L), so we keep them in the serialized form and strip
# them on load.
_COMPUTED_POSITION_FIELDS = {
    "unrealized_pl_base", "realized_pl_base", "total_pl_base",
}


def _strip_computed(data: dict) -> dict:
    """Remove computed_field outputs from a snapshot dict before validate."""
    if not isinstance(data, dict):
        return data
    for pos in data.get("positions", []) or []:
        if not isinstance(pos, dict):
            continue
        for f in _COMPUTED_POSITION_FIELDS:
            pos.pop(f, None)
    return data


def load_snapshot(broker: str, *, max_age: Optional[float] = SNAPSHOT_CACHE_TTL_SECONDS
                  ) -> Optional[PortfolioSnapshot]:
    """Return cached current-state PortfolioSnapshot for `broker`, or None if
    missing / corrupt. By default also None if older than the TTL; pass
    `max_age=None` to return it regardless of age (for an instant 'stale-while-
    revalidate' render where the caller refreshes in the background)."""
    p = _snapshot_cache_path(broker)
    if not p.is_file():
        return None
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return None
    if max_age is not None and age > max_age:
        return None
    try:
        data = _strip_computed(json.loads(p.read_text()))
        return PortfolioSnapshot.model_validate(data)
    except Exception:
        return None


def save_snapshot(broker: str, snapshot: PortfolioSnapshot) -> None:
    """Persist the current-state snapshot for `broker`. Best-effort
    (silent on failure). Atomic write."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        p = _snapshot_cache_path(broker)
        payload = snapshot.model_dump_json(indent=2)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload)
        os.replace(tmp, p)
    except Exception:
        pass


def snapshot_cache_age_seconds(broker: str) -> Optional[float]:
    """Age in seconds of the cached snapshot file, or None if missing."""
    p = _snapshot_cache_path(broker)
    if not p.is_file():
        return None
    try:
        return time.time() - p.stat().st_mtime
    except OSError:
        return None


def invalidate_snapshot(broker: str) -> None:
    """Delete the cached snapshot for `broker` (used by `--fresh`).
    Silent on failure (no file → no-op)."""
    try:
        _snapshot_cache_path(broker).unlink()
    except OSError:
        pass


# ── ISIN→metadata caches (one namespace per resolver) ────────────────────
def _metadata_cache_path(namespace: str, isin: str) -> Path:
    # Use a flat sanitized filename — ISINs are always 12 alnum chars so
    # no escaping is needed, but be defensive (some test ISINs are short
    # or contain characters like ':').
    safe = "".join(c if c.isalnum() else "_" for c in isin)
    return CACHE_DIR / namespace / f"{safe}.json"


def _load_metadata(namespace: str, isin: str) -> Optional[dict]:
    p = _metadata_cache_path(namespace, isin)
    if not p.is_file():
        return None
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return None
    if age > OPENFIGI_CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _save_metadata(namespace: str, isin: str, meta: dict) -> None:
    try:
        p = _metadata_cache_path(namespace, isin)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(meta, indent=2, sort_keys=True))
        os.replace(tmp, p)
    except Exception:
        pass


def load_openfigi_metadata(isin: str) -> Optional[dict]:
    """Return cached OpenFIGI metadata for `isin`, or None if missing /
    stale / corrupt. Stale = older than `OPENFIGI_CACHE_TTL_SECONDS`."""
    return _load_metadata("openfigi", isin)


def save_openfigi_metadata(isin: str, meta: dict) -> None:
    """Persist OpenFIGI metadata for `isin` (or a sentinel for misses).
    Atomic write; silent on I/O failure."""
    _save_metadata("openfigi", isin, meta)


def load_firds_metadata(isin: str) -> Optional[dict]:
    """Cached ESMA FIRDS metadata for `isin` (same TTL + sentinel
    conventions as OpenFIGI)."""
    return _load_metadata("firds", isin)


def save_firds_metadata(isin: str, meta: dict) -> None:
    _save_metadata("firds", isin, meta)
