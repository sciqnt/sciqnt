"""Cost-basis booking primitives.

A Lot is a parcel of shares acquired at a specific cost. When you sell, you
match shares against lots per the chosen method (FIFO / LIFO / AVG). The
matched lots determine realized P/L; the remaining quantity is the open
position.

  FIFO  — first-in, first-out. Oldest lots drained first.
  LIFO  — last-in, first-out. Newest lots drained first.
  AVG   — average cost. All shares collapsed into a single weighted lot
          before each sell; realized P/L is computed against the avg cost.

These are the three methods every personal-investing tool supports; matches
Degiro's three options (FIFO / LIFO / BEP) in sq_config.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class CostBasisMethod(str, Enum):
    FIFO = "FIFO"
    LIFO = "LIFO"
    AVG  = "AVG"


_ZERO = Decimal("0")


@dataclass
class Lot:
    """One parcel of acquired units. Mutable: `quantity` shrinks as sells
    consume the lot. The other fields are immutable historical record.

    `fee_per_unit_local` carries the buy-side fee allocation per remaining
    unit in INSTRUMENT currency. On a partial sell, the proportional
    fee flows to realized_fees_base. 0 when the source transaction had no
    fee (Degiro live API, synthetic test data, etc.)."""
    quantity: Decimal                  # units remaining in this lot
    cost_per_unit_local: Decimal       # at acquisition, in instrument.listing_currency
    fx_at_acquisition: Decimal         # instrument_ccy -> base_ccy at acquisition
    acquired_at: datetime
    fee_per_unit_local: Decimal = _ZERO   # buy-side fee allocation per unit (local ccy)

    @property
    def cost_per_unit_base(self) -> Decimal:
        """Cost per unit in the account's base currency at acquisition time."""
        return self.cost_per_unit_local * self.fx_at_acquisition

    @property
    def cost_basis_base(self) -> Decimal:
        """Remaining cost basis of THIS lot in base currency.

        Excludes fees (cost_basis_base tracks the price-side basis only).
        For fees-inclusive remaining basis, add
            self.quantity × self.fee_per_unit_local × self.fx_at_acquisition
        — but adapters typically want them separately so unrealized P/L
        and realised fees can be reported as distinct lines."""
        return self.quantity * self.cost_per_unit_base
