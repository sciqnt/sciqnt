"""sq-robinhood canonical adapter — fixture-based (no network, no creds).

Pins the robin_stocks dialect → canonical translation. Fixtures are minimal
hand-built copies of the real robin_stocks response shapes (per the verified
research in research/connectors-prediction-markets-and-robinhood.md), with
money as STRINGS (as the library returns them).
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-robinhood" / "src"))

from sq_robinhood.canonical import to_canonical                       # noqa: E402
from sq_schema import AssetClass, conformance                         # noqa: E402


# ── fixtures (real robin_stocks shapes, money as strings) ────────────────
_STOCK_POSITIONS = [
    {"instrument": "https://api.robinhood.com/instruments/aaaa/",
     "quantity": "10.0000", "average_buy_price": "150.0000",
     "account": "x", "created_at": "2024-01-01T00:00:00Z"},
    {"instrument": "https://api.robinhood.com/instruments/bbbb/",
     "quantity": "5.0000",  "average_buy_price": "200.0000"},
    # closed position — must be skipped
    {"instrument": "https://api.robinhood.com/instruments/cccc/",
     "quantity": "0.0000",  "average_buy_price": "99.0000"},
]
_INSTRUMENT_MAP = {
    "https://api.robinhood.com/instruments/aaaa/":
        {"symbol": "AAPL", "simple_name": "Apple", "name": "Apple Inc."},
    "https://api.robinhood.com/instruments/bbbb/":
        {"symbol": "MSFT", "simple_name": "Microsoft", "name": "Microsoft Corp."},
    "https://api.robinhood.com/instruments/cccc/":
        {"symbol": "TSLA", "simple_name": "Tesla", "name": "Tesla Inc."},
}
_PRICE_MAP = {"AAPL": "180.00", "MSFT": "190.00", "TSLA": "250.00"}

_CRYPTO_POSITIONS = [
    {"currency": {"code": "BTC", "name": "Bitcoin"},
     "quantity": "0.50000000",
     "cost_bases": [{"direct_cost_basis": "20000.00", "direct_quantity": "0.50000000"}]},
]
_CRYPTO_PRICE_MAP = {"BTC": "60000.00"}

_ACCOUNT_PROFILE = {"cash": "1000.00", "uncleared_deposits": "250.00",
                    "buying_power": "1250.00"}


class TestStockMapping(unittest.TestCase):
    def setUp(self):
        self.snap = to_canonical(
            _STOCK_POSITIONS, _INSTRUMENT_MAP, _PRICE_MAP,
            [], {}, _ACCOUNT_PROFILE,
        )

    def test_closed_position_skipped(self):
        # AAPL + MSFT open; TSLA (qty 0) dropped
        tickers = {i.identifiers["ticker"] for i in self.snap.instruments}
        self.assertEqual(tickers, {"AAPL", "MSFT"})

    def test_aapl_math_to_the_cent(self):
        aapl = next(p for p in self.snap.positions
                    if p.instrument_id == "robinhood:AAPL")
        self.assertEqual(aapl.quantity,            Decimal("10"))
        self.assertEqual(aapl.break_even_price_local, Decimal("150.00000000"))
        self.assertEqual(aapl.last_price_local,    Decimal("180.00"))
        self.assertEqual(aapl.cost_basis_base,     Decimal("1500.00000000"))   # 10×150
        self.assertEqual(aapl.value_base,          Decimal("1800.00000000"))   # 10×180
        self.assertEqual(aapl.unrealized_pl_base,  Decimal("300.00000000"))    # (180-150)×10
        self.assertEqual(aapl.realized_pl_base,    Decimal("0"))

    def test_instrument_metadata(self):
        aapl = next(i for i in self.snap.instruments
                    if i.instrument_id == "robinhood:AAPL")
        self.assertEqual(aapl.name,             "Apple")
        self.assertEqual(aapl.asset_class,      AssetClass.STOCK)
        self.assertEqual(aapl.listing_currency, "USD")
        self.assertEqual(aapl.identifiers["ticker"], "AAPL")

    def test_account_is_usd_base(self):
        self.assertEqual(self.snap.account.broker, "robinhood")
        self.assertEqual(self.snap.account.base_currency, "USD")

    def test_cash_is_settled_plus_uncleared(self):
        # 1000 + 250 = 1250
        self.assertEqual(len(self.snap.cash_balances), 1)
        c = self.snap.cash_balances[0]
        self.assertEqual(c.currency, "USD")
        self.assertEqual(c.amount, Decimal("1250.00000000"))

    def test_unresolved_symbol_skipped(self):
        # A position whose instrument URL isn't in the map can't be priced
        snap = to_canonical(
            [{"instrument": "https://unknown/", "quantity": "1",
              "average_buy_price": "1"}],
            {}, {}, [], {}, {},
        )
        self.assertEqual(snap.positions, [])

    def test_passes_conformance(self):
        violations = conformance.check_snapshot(self.snap)
        self.assertEqual(violations, [],
                         conformance.format_violations(violations))


class TestCryptoMapping(unittest.TestCase):
    def setUp(self):
        self.snap = to_canonical(
            [], {}, {}, _CRYPTO_POSITIONS, _CRYPTO_PRICE_MAP, {},
        )

    def test_btc_math(self):
        btc = next(p for p in self.snap.positions
                   if p.instrument_id == "robinhood:crypto:BTC")
        self.assertEqual(btc.quantity,             Decimal("0.5"))
        # avg = 20000 / 0.5 = 40000
        self.assertEqual(btc.break_even_price_local, Decimal("40000.00000000"))
        self.assertEqual(btc.last_price_local,     Decimal("60000.00"))
        self.assertEqual(btc.cost_basis_base,      Decimal("20000.00000000"))  # 0.5×40000
        self.assertEqual(btc.value_base,           Decimal("30000.00000000"))  # 0.5×60000
        self.assertEqual(btc.unrealized_pl_base,   Decimal("10000.00000000"))

    def test_crypto_asset_class(self):
        btc = next(i for i in self.snap.instruments
                   if i.instrument_id == "robinhood:crypto:BTC")
        self.assertEqual(btc.asset_class, AssetClass.CRYPTO)
        self.assertEqual(btc.identifiers["ticker"], "BTC")

    def test_passes_conformance(self):
        self.assertEqual(conformance.check_snapshot(self.snap), [])


class TestCombined(unittest.TestCase):
    def test_stocks_and_crypto_together(self):
        snap = to_canonical(
            _STOCK_POSITIONS, _INSTRUMENT_MAP, _PRICE_MAP,
            _CRYPTO_POSITIONS, _CRYPTO_PRICE_MAP, _ACCOUNT_PROFILE,
        )
        # 2 open stocks + 1 crypto = 3 positions, 3 instruments
        self.assertEqual(len(snap.positions), 3)
        self.assertEqual(len(snap.instruments), 3)
        self.assertEqual(conformance.check_snapshot(snap), [])

    def test_empty_everything_is_valid_empty_snapshot(self):
        snap = to_canonical([], {}, {}, [], {}, {})
        self.assertEqual(snap.positions, [])
        self.assertEqual(snap.cash_balances, [])
        self.assertEqual(conformance.check_snapshot(snap), [])


class TestMoneyStringDiscipline(unittest.TestCase):
    def test_handles_six_decimal_strings_without_precision_pollution(self):
        # robin_stocks can return ~6-decimal formatted strings (the
        # equity_change bug). Quantization to 8dp must keep conformance happy.
        snap = to_canonical(
            [{"instrument": "u", "quantity": "3.000000",
              "average_buy_price": "33.333333"}],
            {"u": {"symbol": "XXX"}}, {"XXX": "44.444444"},
            [], {}, {},
        )
        pos = snap.positions[0]
        # All money fields must be ≤ 8 fractional digits (conformance clean)
        for field in ("value_base", "cost_basis_base",
                      "unrealized_product_pl_base", "break_even_price_local"):
            exp = getattr(pos, field).as_tuple().exponent
            self.assertGreaterEqual(exp, -8, f"{field} over-precise")
        self.assertEqual(conformance.check_snapshot(snap), [])


if __name__ == "__main__":
    unittest.main()
