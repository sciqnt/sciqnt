#!/usr/bin/env python3
"""Parse Degiro CSV exports → canonical Transactions → fold into Positions.

Demonstrates the historical-flavour pipeline end-to-end against the
synthetic fixtures shipped in modules/sq-degiro/tests/fixtures/. Same
shape works on real Degiro CSV exports.

Run::

    python3 examples/csv_to_canonical_demo.py
"""
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

from sq_compute import CostBasisMethod, fold_cash_balances, fold_position
from sq_degiro.canonical import (
    to_canonical_account_events, to_canonical_transactions,
)

FIXTURES = ROOT / "modules" / "sq-degiro" / "tests" / "fixtures"


def main():
    # --- 1) Parse both CSVs into canonical Transactions
    trades = to_canonical_transactions(
        FIXTURES / "transactions.csv", account_id="degiro",
    )
    events = to_canonical_account_events(
        FIXTURES / "account.csv", account_id="degiro",
    )
    all_txns = trades + events
    print(f"  {len(trades)} trade transactions + {len(events)} non-trade events")

    # --- 2) Fold each instrument
    by_inst = defaultdict(list)
    for t in trades:
        by_inst[t.instrument_id].append(t)

    print(f"\n  per-instrument fold (FIFO):")
    for inst_id, inst_txns in sorted(by_inst.items()):
        pos = fold_position(
            account_id="degiro", instrument_id=inst_id,
            base_currency="EUR", transactions=inst_txns,
            method=CostBasisMethod.FIFO,
        )
        status = "OPEN" if pos.is_open else "closed"
        print(
            f"    {inst_id:<28}  qty {str(pos.quantity):>4}  "
            f"cost_basis {float(pos.cost_basis_base):>10,.2f} EUR  "
            f"realized {float(pos.realized_pl_base):>10,.2f} EUR  "
            f"{status}"
        )

    # --- 3) Per-currency cash totals across the entire log
    print(f"\n  per-currency cash totals (trades + events):")
    for ccy, amt in sorted(fold_cash_balances(all_txns).items()):
        print(f"    {ccy}  {float(amt):>10,.2f}")


if __name__ == "__main__":
    main()
