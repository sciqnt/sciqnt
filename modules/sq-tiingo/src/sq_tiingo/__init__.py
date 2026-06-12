"""sq-tiingo — official-API EOD price source (free key, US-listed symbols).

`fetch_chart(ticker, start, end, token=…) -> dict` is the raw interface
(same return shape as `sq_yahoo.fetch_chart`).
`TiingoProvider` is the `sq_schema.PriceProvider` wrapper — the official
fallback rung behind Yahoo in the platform's price chain. Keyless
construction is valid and inert (every call returns None)."""
from .price import fetch_chart
from .provider import TiingoProvider

__all__ = ["fetch_chart", "TiingoProvider"]
