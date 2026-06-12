"""sq-news-rss — no-key per-ticker headlines (Yahoo Finance RSS).

`fetch_headlines(ticker, limit=…) -> list[dict]` is the raw interface.
`RssNewsProvider` is the `sq_schema.NewsProvider` wrapper — the keyless
rung of the news chain (a keyed rung, e.g. Finnhub, can sit in front)."""
from .feed import fetch_headlines
from .provider import RssNewsProvider

__all__ = ["fetch_headlines", "RssNewsProvider"]
