"""Portfolio-level aggregates from a Position/CashBalance snapshot.

Snapshot-shape inputs (lists or iterables of canonical entities); no I/O.
All money is `Decimal`; outputs are plain dicts."""
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from sq_schema import AssetClass, CashBalance, Instrument, Position

_ZERO = Decimal("0")


def portfolio_summary(
    positions: Iterable[Position],
    *,
    base_currency: str,
) -> dict:
    """Aggregate Position-level metrics into a portfolio-wide summary.

    Money is denominated in `base_currency` (matches the source Positions —
    callers should pass Positions from a single account or filter beforehand
    if they have multiple accounts in different base currencies).

    Returns a dict with::

        {
          "base_currency": str,
          "instrument_count": int,            # unique instrument_id count
          "open_position_count": int,
          "closed_position_count": int,
          "total_cost_basis_base": Decimal,   # sum of open positions' cost basis
          "total_realized_pl_base": Decimal,  # lifetime, across all positions
          "total_realized_product_pl_base": Decimal,
          "total_realized_currency_pl_base": Decimal,
          "total_unrealized_pl_base": Decimal,    # 0 unless adapter populated it
          "total_value_base": Decimal,            # sum of open positions' value_base
        }
    """
    open_count = closed_count = 0
    cost_basis_total = _ZERO
    value_total = _ZERO
    unreal_total = _ZERO
    real_total   = _ZERO
    real_product = _ZERO
    real_currency = _ZERO
    instruments_seen = set()

    for p in positions:
        instruments_seen.add(p.instrument_id)
        if p.is_open:
            open_count += 1
            cost_basis_total += p.cost_basis_base
            value_total      += p.value_base
            unreal_total     += p.unrealized_pl_base
        else:
            closed_count += 1
        real_total    += p.realized_pl_base
        real_product  += p.realized_product_pl_base
        real_currency += p.realized_currency_pl_base

    return {
        "base_currency":                   base_currency,
        "instrument_count":                len(instruments_seen),
        "open_position_count":             open_count,
        "closed_position_count":           closed_count,
        "total_cost_basis_base":           cost_basis_total,
        "total_value_base":                value_total,
        "total_unrealized_pl_base":        unreal_total,
        "total_realized_pl_base":          real_total,
        "total_realized_product_pl_base":  real_product,
        "total_realized_currency_pl_base": real_currency,
    }


def currency_exposure(
    positions: Iterable[Position],
    cash_balances: Iterable[CashBalance],
    instruments: Iterable[Instrument],
    *,
    base_currency: str,
) -> dict:
    """Per-currency exposure breakdown — positions in their instrument's
    LISTING currency, cash in its native currency.

    This answers "what currencies am I actually exposed to?" — different
    from `portfolio_summary` which reports everything in base currency.

    Returns::

        {
          "EUR": {"positions": Decimal, "cash": Decimal, "total": Decimal},
          "USD": {"positions": Decimal, "cash": Decimal, "total": Decimal},
          ...
        }

    Only OPEN positions contribute (closed positions = no current exposure).
    Positions without `last_price_local` fall back to `value_base` (in base
    currency) so they're not silently dropped, but flag them in calling code
    if you care about pure-listing-ccy reporting.
    """
    by_inst = {i.instrument_id: i for i in instruments}
    exposure: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"positions": _ZERO, "cash": _ZERO}
    )

    for p in positions:
        if not p.is_open:
            continue
        inst = by_inst.get(p.instrument_id)
        listing_ccy = inst.listing_currency if inst else base_currency
        if p.last_price_local is not None and p.quantity is not None:
            value_local = p.quantity * p.last_price_local
            exposure[listing_ccy]["positions"] += value_local
        else:
            # No local price — fall back to base-currency value (this row
            # ends up in the base-currency bucket; document the caveat).
            exposure[base_currency]["positions"] += p.value_base

    for c in cash_balances:
        if c.amount == 0:
            continue
        exposure[c.currency]["cash"] += c.amount

    result: dict[str, dict[str, Decimal]] = {}
    for ccy, parts in exposure.items():
        result[ccy] = {**parts, "total": parts["positions"] + parts["cash"]}
    return result


def asset_class_exposure(
    positions: Iterable[Position],
    instruments: Iterable[Instrument],
    *,
    base_currency: str,
) -> dict:
    """Per-AssetClass breakdown — what mix of stocks / ETFs / bonds / etc.

    All money in `base_currency` (positions carry value_base directly).
    Returns::

        {
          "STOCK": {"position_count": int, "value_base": Decimal,
                    "cost_basis_base": Decimal, "realized_pl_base": Decimal},
          "ETF":   {...},
          "BOND":  {...},
          ...
        }

    Closed positions (quantity = 0) still appear in their asset class for
    realized P/L attribution — they contributed historically even if they
    have no current value.
    """
    by_inst = {i.instrument_id: i for i in instruments}
    out: dict[str, dict[str, Decimal]] = defaultdict(lambda: {
        "position_count":   0,
        "value_base":       _ZERO,
        "cost_basis_base":  _ZERO,
        "realized_pl_base": _ZERO,
    })
    for p in positions:
        inst = by_inst.get(p.instrument_id)
        ac = (inst.asset_class.value if inst else AssetClass.OTHER.value)
        out[ac]["position_count"]   += 1
        out[ac]["value_base"]       += p.value_base
        out[ac]["cost_basis_base"]  += p.cost_basis_base
        out[ac]["realized_pl_base"] += p.realized_pl_base
    return dict(out)
