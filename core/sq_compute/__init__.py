"""sq-compute — pure compute over canonical entities.

The deterministic core: same inputs → same outputs, no I/O. The 'money math'
of the project lives here, behind interfaces that bundles call (never the
other way around). All functions accept iterables of `sq_schema.Transaction`
and return canonical types or plain dicts.

Three flagship functions
------------------------

``fold_position(account_id, instrument_id, base_currency, transactions, *, method, asof) -> Position``
    CDM-style event sourcing: a Position is the fold of an immutable
    Transaction log. Cost-basis booking is pluggable (`FIFO | LIFO | AVG`).
    `asof` trims the stream — PIT correctness for free.

``fold_cash_balances(transactions, *, asof) -> dict[currency, Decimal]``
    Per-currency cash ledger. Sum across a complete log = current balance
    per currency.

``fold_cash_by_type(transactions, *, currency, asof) -> dict[type, Decimal]``
    Per-TransactionType breakdown for structural cash reporting
    (deposits / dividends / fees / etc.) without keyword string-matching.

What fold_position populates
----------------------------
On the returned Position:
- ``quantity``, ``break_even_price_local``, ``cost_basis_base``
- ``realized_product_pl_base``, ``realized_currency_pl_base``
- ``realized_fees_base`` (≤ 0 — trade-side fees allocated to lots at buy
  time and applied on sells; derived ``realized_pl_base = product +
  currency + fees``)

What it intentionally does NOT populate:
- ``last_price_local``, ``value_base``, ``unrealized_*_pl_base``

Folding is auditable history. Mark-to-market is a separate concern — overlay
a current price from `sq-yahoo` (or similar) on top of the folded Position.
This separation lets you spot divergence between history and live state,
which is itself a useful conformance signal.

Quick reference
---------------
::

    from decimal import Decimal
    from datetime import datetime, timezone
    from sq_schema import Transaction, TransactionType
    from sq_compute import fold_position, fold_cash_balances, CostBasisMethod

    # Synthetic log: buy 100 @ 100 EUR, sell all at 120 EUR
    txns = [
        Transaction(
            transaction_id="t1", account_id="A", instrument_id="I",
            type=TransactionType.BUY,
            executed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            quantity=Decimal("100"), price_local=Decimal("100"),
            amount=Decimal("-10000"), amount_currency="EUR",
        ),
        Transaction(
            transaction_id="t2", account_id="A", instrument_id="I",
            type=TransactionType.SELL,
            executed_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
            quantity=Decimal("-100"), price_local=Decimal("120"),
            amount=Decimal("12000"), amount_currency="EUR",
        ),
    ]

    pos = fold_position(
        account_id="A", instrument_id="I", base_currency="EUR",
        transactions=txns, method=CostBasisMethod.FIFO,
    )
    # pos.is_open is False; pos.realized_pl_base == 2000 (+20/share × 100)

    # PIT — what did the position look like mid-2024?
    snapshot_at_mid_2024 = fold_position(
        account_id="A", instrument_id="I", base_currency="EUR",
        transactions=txns,
        asof=datetime(2024, 3, 1, tzinfo=timezone.utc),
    )
    # snapshot_at_mid_2024.is_open is True; quantity 100; realized 0;
    # cost_basis_base 10000; valid_at == asof  (bitemporal honesty)

    # Cash ledger
    balances = fold_cash_balances(txns)   # {"EUR": Decimal("2000")}

Cost-basis methods
------------------
- ``CostBasisMethod.FIFO`` — oldest lots drained first on sells.
- ``CostBasisMethod.LIFO`` — newest lots drained first.
- ``CostBasisMethod.AVG``  — collapses all lots to a single weighted-avg lot
  before each sell. Equivalent to Degiro's BEP convention.
"""
from .booking import CostBasisMethod, Lot
from .cash import fold_cash_balances, fold_cash_balances_series, fold_cash_by_type
from .fold import Closure, fold_position, fold_position_series, match_sell_lots

__all__ = [
    "CostBasisMethod", "Lot",
    "Closure", "match_sell_lots",
    "fold_position", "fold_position_series",
    "fold_cash_balances", "fold_cash_balances_series",
    "fold_cash_by_type",
]
