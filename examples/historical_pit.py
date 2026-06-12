#!/usr/bin/env python3
"""PIT-correct historical Position via fold_position(..., asof=...).

Same Transaction stream; different `asof` arguments give different
historical Positions — and the returned Position's `valid_at` mirrors
the asof you asked for (bitemporal honesty).

Run::

    python3 examples/historical_pit.py
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from sq_compute import fold_position
from sq_schema import Transaction, TransactionType


def _ts(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


# A simple life-cycle: buy 100 in Jan, sell all in Aug
TXNS = [
    Transaction(
        transaction_id="b", account_id="A", instrument_id="I",
        type=TransactionType.BUY,
        executed_at=_ts(2024, 1, 15),
        quantity=Decimal("100"), price_local=Decimal("100"),
        amount=Decimal("-10000"), amount_currency="EUR", fx_rate=Decimal("1"),
    ),
    Transaction(
        transaction_id="s", account_id="A", instrument_id="I",
        type=TransactionType.SELL,
        executed_at=_ts(2024, 8, 15),
        quantity=Decimal("-100"), price_local=Decimal("130"),
        amount=Decimal("13000"), amount_currency="EUR", fx_rate=Decimal("1"),
    ),
]


def show(label, asof):
    pos = fold_position(
        account_id="A", instrument_id="I", base_currency="EUR",
        transactions=TXNS, asof=asof,
    )
    print(f"\n  asof = {asof.date() if asof else 'None (latest)'}")
    print(f"    is_open         {pos.is_open}")
    print(f"    quantity        {pos.quantity}")
    print(f"    cost_basis_base {pos.cost_basis_base}")
    print(f"    realized_pl     {pos.realized_pl_base}")
    print(f"    Position.valid_at = {pos.valid_at.date()}  (matches the asof you asked for)")


def main():
    print("Same Transaction log, different historical viewpoints:")
    show("before any trade",  _ts(2024, 1, 1))
    show("after the buy, before the sell", _ts(2024, 5, 1))
    show("after the sell",    _ts(2024, 9, 1))
    show("None = latest",     None)


if __name__ == "__main__":
    main()
