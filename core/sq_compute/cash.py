"""Cash-ledger compute over canonical Transactions.

The complement to `fold_position`: where fold_position derives a Position
from per-(account,instrument) events, fold_cash_balances derives the
per-currency cash ledger from the same Transaction stream.

Both are pure functions. Combined-flow reconciliation (positions + cash)
against a broker's reported ending balances is what proves the canonical
adapters are complete + correct."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional

from sq_schema import Transaction

_ZERO = Decimal("0")


def fold_cash_balances(
    transactions: Iterable[Transaction],
    *,
    asof: Optional[datetime] = None,
) -> dict[str, Decimal]:
    """Aggregate net cash change per currency from a Transaction stream.

    For every transaction with `executed_at <= asof` (if given), adds
    `transaction.amount` to the bucket keyed by `amount_currency`. The
    return is a flat dict; consumers compare against the broker-reported
    ending balance per currency to reconcile.

    Sign convention (mirrors Transaction.amount): + = cash IN, - = cash OUT.
    Sum across a complete event log = current balance per currency."""
    out: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for t in transactions:
        if asof is not None and t.executed_at > asof:
            continue
        out[t.amount_currency] += t.amount
    return dict(out)


def fold_cash_balances_series(
    transactions: Iterable[Transaction],
    asof_dates: Iterable[datetime],
) -> dict[datetime, dict[str, Decimal]]:
    """Single-pass cash-ledger snapshot at every requested `asof_date`.

    Sister function to `sq_compute.fold_position_series`: walks the
    transaction stream once in chronological order, emits a per-currency
    balance dict whenever we cross an asof checkpoint. Same dedup
    semantics: duplicate dates collapse to one entry. O(transactions +
    asof_dates) instead of O(transactions × asof_dates)."""
    sorted_asofs = sorted(set(asof_dates))
    if not sorted_asofs:
        return {}
    sorted_txns = sorted(transactions, key=lambda t: t.executed_at)

    out: dict[datetime, dict[str, Decimal]] = {}
    running: dict[str, Decimal] = defaultdict(lambda: _ZERO)

    asof_idx = 0
    for t in sorted_txns:
        while (asof_idx < len(sorted_asofs)
               and sorted_asofs[asof_idx] < t.executed_at):
            out[sorted_asofs[asof_idx]] = dict(running)
            asof_idx += 1
        running[t.amount_currency] += t.amount

    while asof_idx < len(sorted_asofs):
        out[sorted_asofs[asof_idx]] = dict(running)
        asof_idx += 1

    return out


def fold_cash_by_type(
    transactions: Iterable[Transaction],
    *,
    currency: Optional[str] = None,
    asof: Optional[datetime] = None,
) -> dict[str, Decimal]:
    """Aggregate cash change per TransactionType (for a single currency).

    Useful for the kind of breakdown sq-degiro's pnl.py shows:
    'deposits', 'dividends', 'fees', etc. Type is keyed as the enum's
    string value (e.g. 'DIVIDEND')."""
    out: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for t in transactions:
        if asof is not None and t.executed_at > asof:
            continue
        if currency is not None and t.amount_currency != currency:
            continue
        out[t.type.value] += t.amount
    return dict(out)
