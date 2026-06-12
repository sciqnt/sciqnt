"""Tiny on-disk cache for ECB XML.

Daily file: 12h TTL (ECB updates once per weekday around 16:00 CET; 12h
covers every reasonable user query time and survives a re-run).
90-day history: 24h TTL (only rolls daily anyway).

Cache lives under `~/.cache/sciqnt/fx-ecb/` (XDG-style; outside the repo,
survives `git clean -fdx`, user-owned). Tests pass a custom `cache_dir`.

Writes are atomic (tmp + rename) so an interrupted refresh never leaves
a corrupt XML file behind."""
import time
from pathlib import Path
from typing import Callable

DEFAULT_CACHE_DIR = Path.home() / ".cache" / "sciqnt" / "fx-ecb"

TTL_DAILY = 12 * 3600          # 12 hours
TTL_HIST  = 24 * 3600          # 24 hours


def cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.xml"


def is_fresh(path: Path, ttl_seconds: int) -> bool:
    if not path.is_file():
        return False
    return (time.time() - path.stat().st_mtime) < ttl_seconds


def get_or_fetch(
    cache_dir: Path,
    key: str,
    fetcher: Callable[[], bytes],
    ttl_seconds: int,
) -> bytes:
    """Return cached bytes if fresh; otherwise fetch + persist + return.
    Writes atomically via a sibling `.tmp` file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, key)
    if is_fresh(path, ttl_seconds):
        return path.read_bytes()
    data = fetcher()
    tmp = path.with_suffix(".xml.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data
