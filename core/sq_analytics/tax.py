"""Tax-lot detail reports.

`tax_lots()` replays the canonical Transaction stream and emits one
`ClosedLot` per matched closure — the audit trail behind every realized
gain. A tax return or accountant wants exactly this: opened_at /
closed_at / matched quantity / cost basis / proceeds / fees / holding_days
per closure, not just the aggregate realized P/L on the Position.

The matching logic is shared with `fold_position` via
`sq_compute.match_sell_lots` — the two paths cannot drift on cost-basis
math, by construction.

Per-instrument and account-wide entry points::

    from sq_analytics import tax_lots, all_tax_lots

    closures = tax_lots(
        transactions, account_id="degiro",
        instrument_id="degiro:isin:IE00BGSF1X88",
        base_currency="EUR",
    )

    all_closures = all_tax_lots(transactions, account_id="degiro",
                                base_currency="EUR")
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sq_schema import ClosedLot, Transaction, TransactionType
from sq_compute import CostBasisMethod, Lot, match_sell_lots
from sq_compute.fold import _apply_buy, _apply_split

_ZERO = Decimal("0")


def tax_lots(
    transactions: Iterable[Transaction],
    *,
    account_id: str,
    instrument_id: str,
    base_currency: str,
    method: CostBasisMethod = CostBasisMethod.FIFO,
    asof: Optional[datetime] = None,
) -> list[ClosedLot]:
    """Replay one (account, instrument) slice and emit a `ClosedLot` per
    matched closure. Same `asof` semantics as `fold_position` — only events
    with `executed_at <= asof` participate.

    Sums of the returned ClosedLots match `fold_position(...).realized_*_base`
    cent-for-cent (pinned by tests). If the position is still open, the
    open lots are silently omitted; only matched closures appear here.
    """
    relevant = sorted(
        (t for t in transactions
         if t.account_id == account_id
         and t.instrument_id == instrument_id
         and (asof is None or t.executed_at <= asof)),
        key=lambda t: t.executed_at,
    )

    lots: list[Lot] = []
    observed_at = datetime.now(timezone.utc)
    out: list[ClosedLot] = []

    for t in relevant:
        if t.type in (TransactionType.BUY, TransactionType.DIVIDEND_REINVEST):
            _apply_buy(t, lots, base_currency)
        elif t.type == TransactionType.SELL:
            for c in match_sell_lots(t, lots, base_currency, method):
                proceeds_local = c.matched * (t.price_local or _ZERO)
                proceeds_base  = proceeds_local * c.sell_fx
                cost_basis_base = (c.matched * c.lot_cost_per_unit_local
                                   * c.lot_fx_at_acquisition)
                out.append(ClosedLot(
                    valid_at=t.executed_at,
                    observed_at=observed_at,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    opened_at=c.lot_acquired_at,
                    closed_at=t.executed_at,
                    quantity=c.matched,
                    cost_per_unit_local=c.lot_cost_per_unit_local,
                    fx_at_acquisition=c.lot_fx_at_acquisition,
                    cost_basis_base=cost_basis_base,
                    sell_price_local=(t.price_local or _ZERO),
                    fx_at_sell=c.sell_fx,
                    proceeds_local=proceeds_local,
                    proceeds_base=proceeds_base,
                    realized_product_pl_base=c.realized_product_pl,
                    realized_currency_pl_base=c.realized_currency_pl,
                    realized_fees_base=c.realized_fees_pl,
                ))
        elif t.type == TransactionType.SPLIT:
            _apply_split(t, lots)
        # DIVIDEND / FEE / TAX / INTEREST / cash legs don't touch lots.

    return out


def all_tax_lots(
    transactions: Iterable[Transaction],
    *,
    account_id: str,
    base_currency: str,
    method: CostBasisMethod = CostBasisMethod.FIFO,
    asof: Optional[datetime] = None,
) -> list[ClosedLot]:
    """Account-wide fan-out: tax_lots() across every distinct instrument
    seen in the stream. Returned list is sorted by closed_at then
    instrument_id so consecutive rows for the same SELL stay adjacent.
    """
    txns_list = list(transactions)
    instruments = sorted({
        t.instrument_id for t in txns_list
        if t.account_id == account_id and t.instrument_id is not None
    })
    out: list[ClosedLot] = []
    for inst in instruments:
        out.extend(tax_lots(
            txns_list, account_id=account_id, instrument_id=inst,
            base_currency=base_currency, method=method, asof=asof,
        ))
    out.sort(key=lambda c: (c.closed_at, c.instrument_id, c.opened_at))
    return out
