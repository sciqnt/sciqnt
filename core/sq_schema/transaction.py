"""Transaction — the immutable event log.

Position-as-a-thing is derived (a fold over Transactions); Transaction is
the actual ground truth. CDM-inspired event-sourcing — a sell N years ago
and a sell yesterday both have the same shape and the same processing rule.

Sign conventions:
  quantity > 0   units flowing INTO the portfolio (BUY, SPLIT up, dividend-as-shares)
  quantity < 0   units flowing OUT             (SELL, withdraw, SPLIT down)
  amount > 0     cash IN  (sell proceeds, dividend, deposit, interest)
  amount < 0     cash OUT (buy cost, fee, tax, withdrawal)
  fee            POSITIVE MAGNITUDE (unsigned) — consumers debit it via
                 -abs(fee) (see sq_analytics.fee_history / income_summary);
                 a FEE-type row instead carries the fee in `amount`, signed.

`amount_currency` is the currency of the cash leg as it hit the account —
often the account's base ccy (Degiro auto-FX'd), sometimes the instrument's
listing ccy (broker holds the foreign cash). The adapter is responsible
for filling this accurately.

`fx_rate` is the broker-reported (or computed) rate from the
instrument's listing currency to the amount currency, at execution time.
Lets fold_position decompose realized P/L into product vs FX components
exactly as Degiro's web detail view does for unrealized.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import field_validator

from .bitemporal import Bitemporal
from .enums import TransactionType
from ._validators import assert_currency_code


class Transaction(Bitemporal):
    """One immutable event affecting the portfolio."""

    transaction_id: str                       # opaque (broker-assigned or generated)
    account_id: str                           # FK -> Account
    instrument_id: Optional[str] = None       # FK -> Instrument; None for cash-only events
    type: TransactionType
    executed_at: datetime                     # when the event happened in the world

    # Security leg (None for pure-cash events: DEPOSIT, FEE not tied to an instrument, etc.)
    quantity: Optional[Decimal] = None        # see sign conventions
    price_local: Optional[Decimal] = None     # per-unit price in instrument.listing_currency

    # Cash leg
    amount: Decimal                           # signed: + IN / - OUT (see conventions)
    amount_currency: str                      # currency of the cash leg
    fee: Optional[Decimal] = None             # optional separated fee; positive magnitude — consumers debit via -abs()

    # Cross-currency context: instrument_currency -> amount_currency at execution
    fx_rate: Optional[Decimal] = None

    # Audit / linking
    description: Optional[str] = None
    related_transaction_ids: list[str] = []   # for multi-leg events (FX swap, spin-off)

    @field_validator("amount_currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return assert_currency_code(v, "amount_currency")
