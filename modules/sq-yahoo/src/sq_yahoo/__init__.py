"""sq-yahoo — market-data source unit (latest price + FX from Yahoo's public endpoint).

`fetch_quote(ticker) -> dict` is the original raw interface.
`fetch_chart(ticker, start, end) -> dict` is the full-range fetch: daily
closes + dividend/split events + currency meta in one request.
`YahooProvider` is the `sq_schema.PriceProvider` wrapper for use with
`sq_market_data.overlay_prices`; pass `store=sq_price_store.PriceStore()`
to archive every observation locally (the platform layer does)."""
from .price import fetch_chart, fetch_quote
from .provider import YahooProvider

__all__ = ["fetch_chart", "fetch_quote", "YahooProvider"]
