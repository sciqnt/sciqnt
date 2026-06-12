"""sq-polymarket canonical adapter — fixture-based (no network).

Fixtures use the VERIFIED Data API position fields (research/, with the
0-3 REFUTED fields eventId/eventSlug/oppositeOutcome deliberately absent).
Proves the EVENT mapping: probabilities already in [0,1], asset→instrument_id,
conditionId→event_id, conformance-clean.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-polymarket" / "src"))

from sq_polymarket.canonical import to_canonical                     # noqa: E402
from sq_schema import AssetClass, conformance                        # noqa: E402


_POSITIONS = [
    {"asset": "111222333", "conditionId": "0xabc",
     "outcome": "Yes", "outcomeIndex": 0,
     "size": "100", "avgPrice": "0.40", "curPrice": "0.62",
     "initialValue": "40.00", "currentValue": "62.00",
     "realizedPnl": "0", "title": "Will X happen?", "slug": "will-x-happen",
     "endDate": "2025-11-04T00:00:00Z"},
    {"asset": "444555666", "conditionId": "0xdef",
     "outcome": "No", "outcomeIndex": 1,
     "size": "50", "avgPrice": "0.70", "curPrice": "0.55",
     "initialValue": "35.00", "currentValue": "27.50",
     "realizedPnl": "5.00", "title": "Will Y happen?", "slug": "will-y",
     "endDate": "2025-12-31T00:00:00Z"},
    # settled-to-zero loser (curPrice 0) — still held, size>0
    {"asset": "777", "conditionId": "0xghi", "outcome": "Yes",
     "size": "10", "avgPrice": "0.30", "curPrice": "0",
     "initialValue": "3.00", "currentValue": "0",
     "realizedPnl": "0", "title": "Lost bet", "endDate": "2024-01-01T00:00:00Z"},
    # zero size — skipped
    {"asset": "000", "size": "0", "avgPrice": "0.5", "curPrice": "0.5",
     "outcome": "Yes", "title": "flat"},
]


class TestPolymarketMapping(unittest.TestCase):
    def setUp(self):
        self.snap = to_canonical(_POSITIONS, cash_usdc=Decimal("125.50"))

    def test_zero_size_skipped(self):
        ids = {p.instrument_id for p in self.snap.positions}
        self.assertEqual(ids, {"polymarket:111222333", "polymarket:444555666",
                               "polymarket:777"})

    def test_yes_position_math(self):
        pos = next(p for p in self.snap.positions
                   if p.instrument_id == "polymarket:111222333")
        inst = next(i for i in self.snap.instruments
                    if i.instrument_id == "polymarket:111222333")
        self.assertEqual(inst.asset_class, AssetClass.EVENT)
        self.assertEqual(inst.terms["outcome"], "YES")
        self.assertEqual(inst.terms["event_id"], "0xabc")
        self.assertEqual(inst.terms["resolution_date"], "2025-11-04")
        self.assertEqual(inst.name, "Will X happen?")
        self.assertEqual(pos.quantity,             Decimal("100"))
        self.assertEqual(pos.break_even_price_local, Decimal("0.40000000"))
        self.assertEqual(pos.last_price_local,     Decimal("0.62"))
        self.assertEqual(pos.cost_basis_base,      Decimal("40.00000000"))
        self.assertEqual(pos.value_base,           Decimal("62.00000000"))
        self.assertEqual(pos.unrealized_pl_base,   Decimal("22.00000000"))  # 62-40

    def test_no_position_outcome_and_realized(self):
        pos = next(p for p in self.snap.positions
                   if p.instrument_id == "polymarket:444555666")
        inst = next(i for i in self.snap.instruments
                    if i.instrument_id == "polymarket:444555666")
        self.assertEqual(inst.terms["outcome"], "NO")
        self.assertEqual(pos.realized_product_pl_base, Decimal("5.00000000"))
        self.assertEqual(pos.unrealized_pl_base, Decimal("-7.50000000"))    # 27.5-35

    def test_settled_to_zero_loser(self):
        pos = next(p for p in self.snap.positions
                   if p.instrument_id == "polymarket:777")
        self.assertIsNone(pos.last_price_local)         # curPrice 0 → None
        self.assertEqual(pos.value_base, Decimal("0"))
        self.assertEqual(pos.unrealized_pl_base, Decimal("-3.00000000"))  # full loss

    def test_cash_usdc(self):
        self.assertEqual(len(self.snap.cash_balances), 1)
        c = self.snap.cash_balances[0]
        self.assertEqual(c.currency, "USDC")
        self.assertEqual(c.amount, Decimal("125.50000000"))

    def test_account_is_polymarket_usdc(self):
        self.assertEqual(self.snap.account.broker, "polymarket")
        self.assertEqual(self.snap.account.base_currency, "USDC")

    def test_prices_in_probability_band_pass_conformance(self):
        # All curPrice/avgPrice are in [0,1] → the EVENT price check is happy
        self.assertEqual(conformance.check_snapshot(self.snap), [],
                         conformance.format_violations(
                             conformance.check_snapshot(self.snap)))


class TestPolymarketEdges(unittest.TestCase):
    def test_no_cash_when_none(self):
        snap = to_canonical(_POSITIONS)             # cash_usdc=None
        self.assertEqual(snap.cash_balances, [])

    def test_empty_positions(self):
        snap = to_canonical([])
        self.assertEqual(snap.positions, [])
        self.assertEqual(conformance.check_snapshot(snap), [])

    def test_falls_back_to_size_times_price_when_values_absent(self):
        snap = to_canonical([
            {"asset": "z", "size": "10", "avgPrice": "0.25", "curPrice": "0.40",
             "outcome": "Yes", "conditionId": "0xz"},
        ])
        pos = snap.positions[0]
        self.assertEqual(pos.cost_basis_base, Decimal("2.50000000"))   # 10×0.25
        self.assertEqual(pos.value_base,      Decimal("4.00000000"))   # 10×0.40


if __name__ == "__main__":
    unittest.main()
