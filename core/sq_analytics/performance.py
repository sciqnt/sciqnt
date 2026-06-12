"""Time-bucketed performance + cash-flow analytics.

Both functions are deterministic and PIT-honest: the realized-P/L
attribution uses `fold_position` at each sell event so realized gains
are dated to when they actually crystallised, not when the position was
originally opened."""
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from sq_schema import Transaction, TransactionType
from sq_compute import CostBasisMethod, fold_position

_ZERO = Decimal("0")


def _bucket_key(t: Transaction, group_by: str):
    if group_by == "year":
        return t.executed_at.year
    if group_by == "month":
        return (t.executed_at.year, t.executed_at.month)
    raise ValueError(
        f"unknown group_by={group_by!r}; choose 'year' or 'month'"
    )


def realized_pl_over_time(
    transactions: Iterable[Transaction],
    *,
    base_currency: str,
    group_by: str = "year",
    method: CostBasisMethod = CostBasisMethod.FIFO,
) -> dict:
    """Bucket realized P/L by the period it was crystallised in.

    For each SELL event, we fold the position up to (and including) that
    sell using the supplied cost-basis `method`, take the delta in
    realized_pl_base since the previous sell, and attribute that delta to
    the bucket containing the sell's `executed_at`.

    This is more honest than "sum amounts by date of sell" because the
    fold respects FIFO/LIFO/AVG matching — a SELL whose realized P/L
    depends on which lots are matched is attributed correctly.

    Output: ``{bucket_key: Decimal}`` — bucket_key is year (int) or
    (year, month) tuple per `group_by`."""
    txns_list = list(transactions)
    # Group BUY/SELL events by (account_id, instrument_id)
    grouped: dict = defaultdict(list)
    for t in txns_list:
        if t.instrument_id is None:
            continue
        if t.type in (TransactionType.BUY, TransactionType.SELL,
                      TransactionType.DIVIDEND_REINVEST, TransactionType.SPLIT):
            grouped[(t.account_id, t.instrument_id)].append(t)

    out: dict = defaultdict(lambda: _ZERO)
    for (acct, inst), inst_txns in grouped.items():
        inst_sorted = sorted(inst_txns, key=lambda t: t.executed_at)
        previous_realized = _ZERO
        for i, t in enumerate(inst_sorted):
            if t.type != TransactionType.SELL:
                continue
            pos = fold_position(
                account_id=acct, instrument_id=inst,
                base_currency=base_currency,
                transactions=inst_sorted[: i + 1],
                method=method,
                asof=t.executed_at,
            )
            delta = pos.realized_pl_base - previous_realized
            previous_realized = pos.realized_pl_base
            if delta != 0:
                out[_bucket_key(t, group_by)] += delta
    return dict(out)


def cash_flow_over_time(
    transactions: Iterable[Transaction],
    *,
    group_by: str = "year",
    currency: str | None = None,
) -> dict:
    """Per-period × per-TransactionType cash-flow breakdown.

    Returns a nested dict::

        {
          year_or_(year,month): {
            "BUY":        Decimal,
            "SELL":       Decimal,
            "DIVIDEND":   Decimal,
            "FEE":        Decimal,
            "DEPOSIT":    Decimal,
            ...
          },
          ...
        }

    The inner dict only contains keys present in the source data (no
    zero-padded buckets). Filter by `currency` to focus on one denomination
    — particularly useful for multi-currency accounts."""
    out: dict = defaultdict(lambda: defaultdict(lambda: _ZERO))
    for t in transactions:
        if currency is not None and t.amount_currency != currency:
            continue
        out[_bucket_key(t, group_by)][t.type.value] += t.amount
    return {k: dict(v) for k, v in out.items()}
