"""sq-finnhub — official keyed news source (free key, 60 calls/min).

`fetch_company_news(ticker, token=…)` is the raw interface (same item
shape as sq-news-rss). `FinnhubNewsProvider` is the `NewsProvider`
rung the platform puts IN FRONT of the keyless RSS rung; keyless
construction is valid and inert."""
from .news import fetch_company_news
from .provider import FinnhubNewsProvider

__all__ = ["fetch_company_news", "FinnhubNewsProvider"]
