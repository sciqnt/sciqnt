"""sq-kalshi canonical adapter — fixture-based (no network, no creds).

Fixtures use the verified Kalshi v2 `_fp`/`_dollars` string field shapes
(research/connectors-prediction-markets-and-robinhood.md). Proves the
EVENT-contract mapping: position_fp sign → YES/NO outcome, _dollars → Decimal
money, conformance-clean.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-kalshi" / "src"))

from sq_kalshi.canonical import to_canonical                          # noqa: E402
from sq_schema import AssetClass, conformance                         # noqa: E402


_POSITIONS = {
    "market_positions": [
        # YES position (positive position_fp)
        {"ticker": "INXD-24DEC31-B5000", "position_fp": "100.00",
         "market_exposure_dollars": "55.00", "total_traded_dollars": "55.00",
         "realized_pnl_dollars": "0.00", "fees_paid_dollars": "0.35"},
        # NO position (negative position_fp)
        {"ticker": "FED-24DEC-T5.00", "position_fp": "-50.00",
         "market_exposure_dollars": "20.00", "total_traded_dollars": "20.00",
         "realized_pnl_dollars": "-3.00", "fees_paid_dollars": "0.10"},
        # flat / settled (position_fp 0) — must be skipped from the live view
        {"ticker": "OLD-MARKET", "position_fp": "0.00",
         "market_exposure_dollars": "0.00", "realized_pnl_dollars": "12.00"},
    ],
    "event_positions": [],
    "cursor": "",
}
_BALANCE = {"balance": 7500, "balance_dollars": "75.00", "portfolio_value": "150.00"}
_MARKET_META = {
    "INXD-24DEC31-B5000": {"title": "S&P 500 above 5000 on 2024-12-31",
                           "event_ticker": "INXD-24DEC31",
                           "close_time": "2024-12-31T21:00:00Z"},
}


class TestKalshiMapping(unittest.TestCase):
    def setUp(self):
        self.snap = to_canonical(_POSITIONS, _BALANCE, market_meta=_MARKET_META)

    def test_flat_position_skipped(self):
        ids = {p.instrument_id for p in self.snap.positions}
        self.assertEqual(ids, {"kalshi:INXD-24DEC31-B5000", "kalshi:FED-24DEC-T5.00"})

    def test_yes_position_outcome_and_money(self):
        inst = next(i for i in self.snap.instruments
                    if i.instrument_id == "kalshi:INXD-24DEC31-B5000")
        pos = next(p for p in self.snap.positions
                   if p.instrument_id == "kalshi:INXD-24DEC31-B5000")
        self.assertEqual(inst.asset_class, AssetClass.EVENT)
        self.assertEqual(inst.terms["outcome"], "YES")
        self.assertEqual(inst.terms["event_id"], "INXD-24DEC31")
        self.assertEqual(inst.terms["resolution_date"], "2024-12-31")
        self.assertEqual(inst.name, "S&P 500 above 5000 on 2024-12-31")
        self.assertEqual(pos.quantity,        Decimal("100"))    # magnitude
        self.assertEqual(pos.cost_basis_base, Decimal("55.00000000"))
        self.assertEqual(pos.realized_product_pl_base, Decimal("0"))
        self.assertEqual(pos.realized_fees_base, Decimal("-0.35000000"))
        # realized_pl_base = product + currency + fees = 0 + 0 + (-0.35)
        self.assertEqual(pos.realized_pl_base, Decimal("-0.35000000"))

    def test_no_position_sign_decodes_to_no(self):
        inst = next(i for i in self.snap.instruments
                    if i.instrument_id == "kalshi:FED-24DEC-T5.00")
        pos = next(p for p in self.snap.positions
                   if p.instrument_id == "kalshi:FED-24DEC-T5.00")
        self.assertEqual(inst.terms["outcome"], "NO")            # negative position_fp
        self.assertEqual(pos.quantity, Decimal("50"))            # magnitude
        self.assertEqual(pos.realized_product_pl_base, Decimal("-3.00000000"))
        # event_id falls back to ticker prefix when no meta
        self.assertEqual(inst.terms["event_id"], "FED")

    def test_cash_from_balance_dollars(self):
        self.assertEqual(len(self.snap.cash_balances), 1)
        c = self.snap.cash_balances[0]
        self.assertEqual(c.currency, "USD")
        self.assertEqual(c.amount, Decimal("75.00000000"))

    def test_account_is_kalshi_usd(self):
        self.assertEqual(self.snap.account.broker, "kalshi")
        self.assertEqual(self.snap.account.base_currency, "USD")

    def test_passes_conformance(self):
        violations = conformance.check_snapshot(self.snap)
        self.assertEqual(violations, [],
                         conformance.format_violations(violations))


class TestKalshiEdgeCases(unittest.TestCase):
    def test_balance_cents_fallback(self):
        # Older payload: only integer-cents `balance`, no `balance_dollars`
        snap = to_canonical(
            {"market_positions": [], "event_positions": []},
            {"balance": 12345},
        )
        self.assertEqual(snap.cash_balances[0].amount, Decimal("123.45000000"))

    def test_empty_portfolio(self):
        snap = to_canonical({"market_positions": []}, {"balance_dollars": "0"})
        self.assertEqual(snap.positions, [])
        self.assertEqual(snap.cash_balances, [])
        self.assertEqual(conformance.check_snapshot(snap), [])

    def test_no_market_meta_uses_ticker_labels(self):
        snap = to_canonical(_POSITIONS, _BALANCE)        # no market_meta
        inst = next(i for i in snap.instruments
                    if i.instrument_id == "kalshi:INXD-24DEC31-B5000")
        self.assertEqual(inst.name, "INXD-24DEC31-B5000")   # ticker fallback
        self.assertEqual(conformance.check_snapshot(snap), [])


class TestPriceOverlay(unittest.TestCase):
    """market_prices (YES-side probability in [0,1]) → mark-to-market.
    YES contract values at yes_prob; NO contract at (1 − yes_prob)."""

    def _snap(self, prices):
        return to_canonical(_POSITIONS, _BALANCE, market_meta=_MARKET_META,
                            market_prices=prices)

    def test_yes_position_valued_at_yes_probability(self):
        # YES, 100 contracts, yes_prob 0.70, cost 55 → value 70, unrealized +15
        snap = self._snap({"INXD-24DEC31-B5000": Decimal("0.70")})
        pos = next(p for p in snap.positions
                   if p.instrument_id == "kalshi:INXD-24DEC31-B5000")
        self.assertEqual(pos.last_price_local, Decimal("0.70"))
        self.assertEqual(pos.value_base,       Decimal("70.00000000"))   # 100×0.70
        self.assertEqual(pos.unrealized_product_pl_base, Decimal("15.00000000"))  # 70−55

    def test_no_position_valued_at_one_minus_yes(self):
        # NO, 50 contracts, yes_prob 0.30 → side price 0.70, value 35, cost 20 → +15
        snap = self._snap({"FED-24DEC-T5.00": Decimal("0.30")})
        pos = next(p for p in snap.positions
                   if p.instrument_id == "kalshi:FED-24DEC-T5.00")
        self.assertEqual(pos.last_price_local, Decimal("0.70"))          # 1 − 0.30
        self.assertEqual(pos.value_base,       Decimal("35.00000000"))   # 50×0.70
        self.assertEqual(pos.unrealized_product_pl_base, Decimal("15.00000000"))  # 35−20

    def test_missing_price_stays_cost_only(self):
        snap = self._snap({})              # no prices at all
        pos = next(p for p in snap.positions
                   if p.instrument_id == "kalshi:INXD-24DEC31-B5000")
        self.assertIsNone(pos.last_price_local)
        self.assertEqual(pos.value_base, Decimal("0"))

    def test_overlaid_snapshot_passes_conformance(self):
        # Prices are probabilities in [0,1] → EVENT band check happy
        snap = self._snap({"INXD-24DEC31-B5000": Decimal("0.70"),
                           "FED-24DEC-T5.00": Decimal("0.30")})
        self.assertEqual(conformance.check_snapshot(snap), [])


if __name__ == "__main__":
    unittest.main()
