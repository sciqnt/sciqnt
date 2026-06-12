"""FxRate — a single bilateral FX observation.

The shape is deliberately minimal: enough to convert money, enough to
audit the source. Real implementations live in connector bundles
(`sq-fx-ecb`, `sq-fx-yfinance`, ...); the protocol below is the contract
they implement.

`rate` semantics: 1 unit of `from_currency` = `rate` units of `to_currency`.
So `FxRate(from='USD', to='EUR', rate=0.92)` means $1 = €0.92.
"""
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import field_validator

from .bitemporal import Bitemporal
from ._validators import assert_currency_code


class FxRate(Bitemporal):
    from_currency: str                  # currency code (fiat or crypto)
    to_currency: str                    # currency code (fiat or crypto)
    rate: Decimal                       # 1 from_currency = `rate` to_currency
    source: str                         # "ecb" / "yfinance" / "manual" / "binance" / ...

    @field_validator("from_currency")
    @classmethod
    def _from_ccy(cls, v: str) -> str:
        return assert_currency_code(v, "from_currency")

    @field_validator("to_currency")
    @classmethod
    def _to_ccy(cls, v: str) -> str:
        return assert_currency_code(v, "to_currency")

    def invert(self) -> "FxRate":
        """Return the reciprocal rate. Useful when the provider only ships
        EUR-cross rates and you need USD->EUR by inverting EUR->USD."""
        if self.rate == 0:
            raise ValueError("cannot invert a zero rate")
        return FxRate(
            valid_at=self.valid_at,
            observed_at=self.observed_at,
            from_currency=self.to_currency,
            to_currency=self.from_currency,
            rate=Decimal(1) / self.rate,
            source=self.source,
        )


@runtime_checkable
class FxRateProvider(Protocol):
    """Contract every FX source implements. Pure read interface.

    `asof`: optional historical date. None = latest available.
    Returns None if the pair isn't known; raising is reserved for genuine
    errors (auth failure, transport, malformed source data)."""

    def get_rate(
        self,
        from_currency: str,
        to_currency: str,
        asof: date | None = None,
    ) -> FxRate | None: ...
