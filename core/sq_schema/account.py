"""Account — the unit `Position.value_base` is denominated in.

`broker` is a free-form string (we don't constrain to an enum) because
new connectors can register themselves without a schema migration."""
from pydantic import field_validator

from .bitemporal import Bitemporal
from ._validators import assert_currency_code


class Account(Bitemporal):
    account_id: str             # opaque, broker-assigned (e.g. Degiro int_account)
    broker: str                 # "degiro" / "ibkr" / "trading212" / "ccxt:binance" / ...
    base_currency: str          # currency code — unit of every *_base field;
                                # fiat (EUR/USD/...) or crypto (USDT/USDC/...) per ccxt model
    display_name: str | None = None

    @field_validator("base_currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return assert_currency_code(v, "base_currency")
