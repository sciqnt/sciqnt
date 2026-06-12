"""RssNewsProvider — `sq_schema.NewsProvider` over Yahoo's per-ticker RSS.

Per-ticker results are cached in-memory for the process lifetime (the
TUI rebuilds tabs on navigation; news doesn't move fast enough to
justify a fetch per redraw). Failures degrade to [] — never raise."""
import pathlib
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import NewsItem                                    # noqa: E402

from .feed import fetch_headlines                                 # noqa: E402


class RssNewsProvider:
    """No-key news rung. `get_news(ticker, limit=5)` → newest-first
    `NewsItem`s; [] on any failure (degrade visibly at the view layer,
    never crash a tab over headlines)."""

    def __init__(self, *, fetch: Optional[Callable] = None):
        self._fetch = fetch or fetch_headlines
        self._cache: dict = {}
        self._failed: set = set()

    def get_news(self, ticker: str, *, limit: int = 5) -> list:
        cached = self._cache.get(ticker)
        if cached is None:
            if ticker in self._failed:
                return []
            try:
                raw = self._fetch(ticker, limit=20)
            except Exception:                          # noqa: BLE001
                self._failed.add(ticker)
                return []
            now = datetime.now(timezone.utc)
            cached = [
                NewsItem(
                    valid_at=item.get("published_at") or now,
                    observed_at=now,
                    headline=item["headline"],
                    url=item.get("url"),
                    summary=item.get("summary"),
                    ticker=ticker,
                    source="yahoo-rss",
                )
                for item in raw
            ]
            self._cache[ticker] = cached
        return cached[:limit]
