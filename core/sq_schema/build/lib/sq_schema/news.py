"""NewsItem — a single news observation about an instrument.

Same shape-discipline as `Price`/`FxRate`: bitemporal (valid_at = the
PUBLISH time as the source reports it; observed_at = when we fetched),
source-attributed, provider-agnostic. News is CONTEXT, not money — no
Decimal fields, nothing here feeds the deterministic money core. The
portfolio view joins items to holdings ("what happened to MY portfolio
today"); reasoning about them is the LLM's job, never code's.
"""
from typing import Optional, Protocol, runtime_checkable

from .bitemporal import Bitemporal


class NewsItem(Bitemporal):
    """One headline. `valid_at` is the publish time the source reports
    (fetch time when the source omits it — declared per provider)."""

    headline: str
    url: Optional[str] = None
    summary: Optional[str] = None
    ticker: Optional[str] = None           # the symbol the query was about
    instrument_id: Optional[str] = None    # filled by the join layer if known
    source: str                            # "yahoo-rss" / "finnhub" / ...


@runtime_checkable
class NewsProvider(Protocol):
    """Contract every news source implements.

    `get_news(ticker, limit=N)` returns the most recent items for the
    exchange-qualified ticker, newest first, at most `limit`. An empty
    list means "nothing found / source unavailable" — providers degrade
    to [] rather than raising for routine failures."""

    def get_news(self, ticker: str, *, limit: int = 5) -> list: ...
