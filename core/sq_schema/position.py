"""Position — the load-bearing entity. P/L is pre-decomposed by the adapter
so that consumers (live display, MCP, analytics) NEVER repeat the math.

Money fields are `Decimal` (deterministic-core / money-math protected).
Derived fields (`unrealized_pl_base`, `realized_pl_base`, `total_pl_base`)
are pure addition — no business logic — so they're safe as computed fields.
"""
from decimal import Decimal

from pydantic import computed_field

from .bitemporal import Bitemporal


_ZERO = Decimal("0")


class Position(Bitemporal):
    account_id: str                                # FK -> Account
    instrument_id: str                             # FK -> Instrument
    quantity: Decimal                              # units held; 0 == closed historical
    last_price_local: Decimal | None = None        # in instrument.listing_currency
    value_base: Decimal = _ZERO                    # quantity × price, in account.base_currency
    break_even_price_local: Decimal | None = None  # per-unit cost basis, in listing_currency
    cost_basis_base: Decimal = _ZERO               # total cost in base_currency (positive)

    # P/L decomposed by the adapter — read-only for consumers.
    unrealized_product_pl_base: Decimal = _ZERO    # price-driven unrealized
    unrealized_currency_pl_base: Decimal = _ZERO   # FX-driven unrealized
    realized_product_pl_base: Decimal = _ZERO      # price-driven realized (lifetime)
    realized_currency_pl_base: Decimal = _ZERO     # FX-driven realized (lifetime)
    realized_fees_base: Decimal = _ZERO            # signed (≤0); buy+sell fees on closed lots
                                                   # 0 when adapter has no per-position fee
                                                   # data (e.g. Degiro live API — fees aren't
                                                   # exposed per-position; only the CSV path
                                                   # populates this from Transaction.fee).

    # ── derived ───────────────────────────────────────────────────────────
    @computed_field
    @property
    def unrealized_pl_base(self) -> Decimal:
        return self.unrealized_product_pl_base + self.unrealized_currency_pl_base

    @computed_field
    @property
    def realized_pl_base(self) -> Decimal:
        """Lifetime realised P/L — fees-INCLUSIVE.

        Adapters that have per-position fee data (CSV ledger) populate
        realized_fees_base; adapters that don't (live broker API exposing
        only price-driven realized) leave it at 0, and this property
        falls back to product + currency only — unchanged from before."""
        return (self.realized_product_pl_base
                + self.realized_currency_pl_base
                + self.realized_fees_base)

    @computed_field
    @property
    def total_pl_base(self) -> Decimal:
        return self.unrealized_pl_base + self.realized_pl_base

    @property
    def is_open(self) -> bool:
        return self.quantity != 0
