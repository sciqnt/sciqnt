#!/usr/bin/env python3
"""Tax-lot detail report.

For every realised gain in your CSV history, emit one row per matched
acquisition lot: when it opened, when it closed, the units, the cost
basis, the proceeds, the P/L decomposition (product / currency / fees),
and the holding period. This is the data a tax return or an accountant
actually needs.

Uses `data/degiro/transactions.csv` if present; otherwise the synthetic
test fixture. The math is identical — the only thing that changes is
the volume.

Run::

    python3 examples/tax_lots_demo.py
"""
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

from sq_analytics import all_tax_lots
from sq_degiro.canonical import to_canonical_transactions


def _pick_csv() -> Path:
    real = ROOT / "data" / "degiro" / "transactions.csv"
    if real.exists():
        return real
    return ROOT / "modules" / "sq-degiro" / "tests" / "fixtures" / "transactions.csv"


def main() -> None:
    csv = _pick_csv()
    print(f"reading {csv.relative_to(ROOT)}")
    trades = to_canonical_transactions(csv, account_id="degiro")

    closures = all_tax_lots(trades, account_id="degiro", base_currency="EUR")
    if not closures:
        print("no realised closures — every position is still open")
        return

    print(f"\n  {len(closures)} closed-lot records\n")
    header = (f"  {'closed':<10}  {'opened':<10}  {'instrument':<34}  "
              f"{'qty':>10}  {'cost €':>12}  {'proceeds €':>12}  "
              f"{'P/L €':>10}  {'days':>5}")
    print(header)
    print("  " + "─" * (len(header) - 2))

    totals_cost     = Decimal("0")
    totals_proceeds = Decimal("0")
    totals_pl       = Decimal("0")
    for c in closures:
        totals_cost     += c.cost_basis_base
        totals_proceeds += c.proceeds_base
        totals_pl       += c.realized_pl_base
        print(f"  {c.closed_at.date().isoformat():<10}  "
              f"{c.opened_at.date().isoformat():<10}  "
              f"{c.instrument_id[:34]:<34}  "
              f"{float(c.quantity):>10,.4f}  "
              f"{float(c.cost_basis_base):>12,.2f}  "
              f"{float(c.proceeds_base):>12,.2f}  "
              f"{float(c.realized_pl_base):>10,.2f}  "
              f"{c.holding_days:>5}")

    print("  " + "─" * (len(header) - 2))
    print(f"  {'TOTAL':<58}  "
          f"{'':>10}  "
          f"{float(totals_cost):>12,.2f}  "
          f"{float(totals_proceeds):>12,.2f}  "
          f"{float(totals_pl):>10,.2f}")


if __name__ == "__main__":
    main()
