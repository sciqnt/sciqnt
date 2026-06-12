#!/usr/bin/env python3
"""Compare FIFO / LIFO / AVG on the same Transaction stream.

Demonstrates sq_compute.fold_position with all three cost-basis methods.
Same input, three different lot-matching policies; the realised P/L and
remaining cost basis differ accordingly.

Run::

    python3 examples/fold_position_demo.py
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from sq_compute import CostBasisMethod, fold_position
from sq_schema import Transaction, TransactionType


def _ts(day):
    return datetime(2024, 1, day, tzinfo=timezone.utc)


# BUY 100 @ €100   -> -10,000 EUR
# BUY 100 @ €150   -> -15,000 EUR
# SELL 100 @ €200  -> +20,000 EUR
TXNS = [
    Transaction(
        transaction_id="b1", account_id="A", instrument_id="I",
        type=TransactionType.BUY,
        executed_at=_ts(1),
        quantity=Decimal("100"), price_local=Decimal("100"),
        amount=Decimal("-10000"), amount_currency="EUR", fx_rate=Decimal("1"),
    ),
    Transaction(
        transaction_id="b2", account_id="A", instrument_id="I",
        type=TransactionType.BUY,
        executed_at=_ts(5),
        quantity=Decimal("100"), price_local=Decimal("150"),
        amount=Decimal("-15000"), amount_currency="EUR", fx_rate=Decimal("1"),
    ),
    Transaction(
        transaction_id="s1", account_id="A", instrument_id="I",
        type=TransactionType.SELL,
        executed_at=_ts(10),
        quantity=Decimal("-100"), price_local=Decimal("200"),
        amount=Decimal("20000"), amount_currency="EUR", fx_rate=Decimal("1"),
    ),
]


def main():
    methods = [
        CostBasisMethod.FIFO,
        CostBasisMethod.LIFO,
        CostBasisMethod.AVG,
    ]
    print(f"  {'method':<6} {'qty':>4} {'cost_basis':>12} {'BEP':>8} {'realized':>10}")
    print("  " + "─" * 50)
    for m in methods:
        pos = fold_position(
            account_id="A", instrument_id="I", base_currency="EUR",
            transactions=TXNS, method=m,
        )
        print(
            f"  {m.value:<6} {str(pos.quantity):>4} "
            f"{float(pos.cost_basis_base):>12,.2f} "
            f"{float(pos.break_even_price_local or 0):>8,.2f} "
            f"{float(pos.realized_pl_base):>10,.2f}"
        )
    print()
    print("  FIFO realises +10,000 on the cheap lot, leaves 100 @ €150 (basis 15,000).")
    print("  LIFO realises  +5,000 on the expensive lot, leaves 100 @ €100 (basis 10,000).")
    print("  AVG  realises  +7,500 on a 125-avg lot, leaves 100 @ €125 (basis 12,500).")


if __name__ == "__main__":
    main()
