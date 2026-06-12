"""Price — a single market-price observation for an instrument.

Parallel shape to `FxRate`: bitemporal, Decimal-typed, source-attributed.
Adapters return `Price` from a `PriceProvider.get_price(ticker)` call; the
overlay substrate (`sq_market_data`) consumes them to populate the
mark-to-market fields on a Position (`last_price_local`, `value_base`,
`unrealized_*_pl_base`).

`instrument_id` is OPTIONAL — providers like Yahoo return prices by
ticker without knowing about our canonical instrument identifiers; the
overlay layer fills it in if needed.
"""
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable

from pydantic import field_validator

from .bitemporal import Bitemporal
from ._validators import assert_currency_code


class Price(Bitemporal):
    """A market price observation: `last_price_local` units of `currency`
    per unit of the underlying instrument, observed `valid_at`."""

    instrument_id: Optional[str] = None    # filled by overlay if known
    last_price_local: Decimal              # in `currency`
    currency: str                          # ISO 4217 or crypto code
    source: str                            # "yahoo" / "polygon" / "tiingo" / ...

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return assert_currency_code(v, "currency")


@runtime_checkable
class PriceProvider(Protocol):
    """Contract every market-data source implements.

    Pure read interface. `get_price(ticker, asof=None)` returns:
      * the latest available price observation for the given
        exchange-qualified ticker when `asof` is None, or
      * the closing price on/closest-prior-to `asof` (a datetime) when
        an `asof` is given — for PIT historical views.
    Returns `None` if the ticker is unknown / unreachable / has no
    historical data for the requested date. Raising is reserved for
    genuine errors (auth, transport, malformed source data).

    Existing implementations may not yet accept `asof`; callers that
    need historical prices should `hasattr`-check or just try and
    catch `TypeError` as a graceful fallback."""

    def get_price(
        self, ticker: str, *, asof: "Optional[object]" = None,
    ) -> Optional[Price]: ...
