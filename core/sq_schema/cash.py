"""CashBalance — a per-currency cash holding within an Account.

`amount_base` stays `None` until an FX provider (`sq-fx` or similar) exists.
The summary line in any consumer renders that as 'needs FX' rather than
silently using a stale or fabricated rate — correctness over convenience.
"""
from decimal import Decimal

from pydantic import field_validator

from .bitemporal import Bitemporal
from ._validators import assert_currency_code


class CashBalance(Bitemporal):
    account_id: str
    currency: str                            # currency code — fiat OR crypto (ccxt-friendly)
    amount: Decimal                          # in `currency`
    amount_base: Decimal | None = None       # converted to account.base_currency
                                             # — stays None until an FxRateProvider exists

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return assert_currency_code(v, "currency")
