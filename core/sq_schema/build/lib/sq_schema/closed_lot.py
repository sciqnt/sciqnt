"""ClosedLot — one matched closure (or partial closure) of a lot.

The audit-trail entity behind `sq_analytics.tax_lots`. Each record describes
a SELL event matching against a specific acquisition lot — the data a tax
return or accountant actually needs.

A single SELL transaction can produce MULTIPLE ClosedLot records when it
matches against multiple lots (FIFO/LIFO). The sell's own fee is allocated
proportionally across the matched closures. Cost-per-unit + fx_at_acquisition
on each record reflect the SPECIFIC lot that was matched (not an avg).

Bitemporal, Decimal-typed, derived P/L sums + holding_days.
"""
from datetime import datetime
from decimal import Decimal

from pydantic import computed_field

from .bitemporal import Bitemporal

_ZERO = Decimal("0")


class ClosedLot(Bitemporal):
    """One matched portion of a SELL against a specific acquisition lot."""

    account_id: str
    instrument_id: str

    opened_at: datetime           # when the matched portion was acquired
    closed_at: datetime           # when the closing SELL happened

    quantity: Decimal             # units closed in THIS matching (≤ original lot qty)

    # Acquisition side (about the SPECIFIC lot matched — not an avg)
    cost_per_unit_local: Decimal      # at acquisition, in instrument.listing_currency
    fx_at_acquisition: Decimal        # instrument_ccy -> base_ccy at acquisition
    cost_basis_base: Decimal          # = quantity × cost_per_unit_local × fx_at_acquisition

    # Disposition side (about THIS SELL)
    sell_price_local: Decimal
    fx_at_sell: Decimal
    proceeds_local: Decimal           # = quantity × sell_price_local
    proceeds_base: Decimal            # = proceeds_local × fx_at_sell

    # Realised P/L decomposition (matches Position's three-way split)
    realized_product_pl_base: Decimal      # price-driven
    realized_currency_pl_base: Decimal     # FX-driven
    realized_fees_base: Decimal            # ≤ 0; matched buy-fee allocation + proportional sell fee

    # ── derived ───────────────────────────────────────────────────────────
    @computed_field
    @property
    def realized_pl_base(self) -> Decimal:
        return (self.realized_product_pl_base
                + self.realized_currency_pl_base
                + self.realized_fees_base)

    @computed_field
    @property
    def holding_days(self) -> int:
        """(closed_at − opened_at).days — for short/long-term tax thresholds.
        Consumers apply jurisdiction-specific rules (US: 365, UK: 30-day, …)."""
        return (self.closed_at - self.opened_at).days
