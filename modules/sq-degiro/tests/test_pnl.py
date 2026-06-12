"""Conformance tests for sq-degiro (CSV flavour). Synthetic fixtures only.

Locks in the money-core behaviour the audit said had no test backing it (P17):
realized P&L on a closed position, open-position detection, multi-currency cash
reconciliation, and the cash-sweep netting quirk.
"""
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from sq_degiro.pnl import compute, num, pdate  # noqa: E402

FIXTURES = HERE / "fixtures"


class TestParsers(unittest.TestCase):
    def test_num_european(self):
        self.assertEqual(num("-100,00"), Decimal("-100.00"))
        self.assertEqual(num("1.234,56"), Decimal("1234.56"))   # dot=thousands
        self.assertEqual(num('"114,1000"'), Decimal("114.1000"))
        self.assertIsNone(num(""))
        self.assertIsNone(num(None))

    def test_pdate(self):
        self.assertEqual(pdate("14-01-2024"), date(2024, 1, 14))
        self.assertIsNone(pdate(""))


class TestComputeMoneyCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compute(FIXTURES)

    def test_realized_pnl_on_closed_position(self):
        # bought 10 @ 10 (-100), sold 10 @ 12 (+120) -> +20.00 realized
        self.assertEqual(self.res["realized"], Decimal("20.00"))
        self.assertEqual(len(self.res["closed"]), 1)
        nm, isin, pnl = self.res["closed"][0]
        self.assertEqual(isin, "TEST0000001")
        self.assertEqual(pnl, Decimal("20.00"))

    def test_open_position_detected(self):
        self.assertEqual(len(self.res["open"]), 1)
        nm, isin, qty, cash = self.res["open"][0]
        self.assertEqual(isin, "TEST0000002")
        self.assertEqual(qty, Decimal("5"))

    def test_cash_reconciles_both_currencies(self):
        self.assertTrue(self.res["reconciliation_ok"])
        self.assertEqual(self.res["reconciliation"]["EUR"]["diff"], Decimal("0.00"))
        self.assertEqual(self.res["reconciliation"]["USD"]["diff"], Decimal("0.00"))

    def test_cash_sweep_is_netted_out(self):
        # the +30 sweep is internal; if it were wrongly counted, EUR would be 150 != 120
        self.assertEqual(self.res["categories"]["internal_sweep"], Decimal("30.00"))
        self.assertEqual(self.res["reconciliation"]["EUR"]["computed"], Decimal("120.00"))

    def test_deposit_categorized(self):
        self.assertEqual(self.res["categories"]["deposits"], Decimal("200.00"))


if __name__ == "__main__":
    unittest.main()
