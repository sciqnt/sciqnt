"""Conformance tests for the Degiro -> canonical adapter (Milestone 0 step 2).

Three layers:
  1. Dialect helpers (_flatten / _probe / _money_in / _asset_class / _to_decimal)
  2. P/L decomposition (_compute_pl)  — verified against the IB01 real numbers
  3. End-to-end (to_canonical)        — fake Degiro payloads -> PortfolioSnapshot

If any test here breaks, the wrong numbers are reaching the user — these are
the load-bearing money-math invariants of the connector.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_degiro.canonical import (                                  # noqa: E402
    _asset_class, _compute_pl, _flatten, _money_in, _probe,
    _to_decimal, extract_base_ccy, to_canonical,
)
from sq_schema import AssetClass, conformance                       # noqa: E402


# ───────────────────────────────────────────────────────────────────────────
# Layer 1 — dialect helpers
# ───────────────────────────────────────────────────────────────────────────
class TestFlatten(unittest.TestCase):
    def test_extracts_name_value_pairs(self):
        row = {"value": [{"name": "id", "value": "15690087"},
                         {"name": "size", "value": 100},
                         {"name": "value", "value": 10338.72}]}
        self.assertEqual(_flatten(row),
                         {"id": "15690087", "size": 100, "value": 10338.72})

    def test_empty_row(self):
        self.assertEqual(_flatten({"value": []}), {})
        self.assertEqual(_flatten({}), {})


class TestProbe(unittest.TestCase):
    def test_returns_first_non_empty_hit(self):
        d = {"alpha": None, "beta": "", "gamma": "X", "delta": "Y"}
        self.assertEqual(_probe(d, "alpha", "beta", "gamma", "delta"), "X")

    def test_default_when_no_keys_match(self):
        self.assertEqual(_probe({"a": None}, "x", "y", default="fallback"), "fallback")

    def test_handles_none_input(self):
        self.assertIsNone(_probe(None, "a", "b"))


class TestMoneyIn(unittest.TestCase):
    def test_scalar_passthrough(self):
        self.assertEqual(_money_in(42.0, "EUR"), 42.0)
        self.assertIsNone(_money_in(None, "EUR"))

    def test_extracts_base_ccy_from_dict(self):
        self.assertEqual(_money_in({"EUR": -820.81, "USD": -896.0}, "EUR"), -820.81)

    def test_falls_back_to_first_when_base_ccy_missing(self):
        self.assertEqual(_money_in({"USD": 50}, "EUR"), 50)

    def test_empty_dict_returns_none(self):
        self.assertIsNone(_money_in({}, "EUR"))


class TestAssetClassMap(unittest.TestCase):
    def test_known_types_map_correctly(self):
        self.assertEqual(_asset_class("STOCK"), AssetClass.STOCK)
        self.assertEqual(_asset_class("ETF"),   AssetClass.ETF)
        self.assertEqual(_asset_class("BOND"),  AssetClass.BOND)
        self.assertEqual(_asset_class("CURRENCY"), AssetClass.FX)
        self.assertEqual(_asset_class("CRYPTO"),   AssetClass.CRYPTO)

    def test_unknown_or_missing_returns_other(self):
        self.assertEqual(_asset_class("MYSTERY"), AssetClass.OTHER)
        self.assertEqual(_asset_class(""),         AssetClass.OTHER)
        self.assertEqual(_asset_class(None),       AssetClass.OTHER)


class TestToDecimal(unittest.TestCase):
    def test_via_str_avoids_binary_pollution(self):
        # If we used Decimal(float_value), 0.1 + 0.2 territory leaks.
        # Via str, the value round-trips exactly.
        self.assertEqual(_to_decimal(120.54), Decimal("120.54"))

    def test_none_and_empty_become_zero(self):
        self.assertEqual(_to_decimal(None), Decimal("0"))
        self.assertEqual(_to_decimal(""),   Decimal("0"))

    def test_unparseable_is_zero_not_raise(self):
        self.assertEqual(_to_decimal("not-a-number"), Decimal("0"))


# ───────────────────────────────────────────────────────────────────────────
# Layer 2 — _compute_pl (the P/L math, verified to the cent against IB01)
# ───────────────────────────────────────────────────────────────────────────
class TestComputePL(unittest.TestCase):
    def test_open_cross_ccy_matches_degiro_web(self):
        """IB01: value 10338.72, plBase {-11159.34}, realized_product 0,
        realized_fx -3.  Degiro web shows: Product +552.34 / Currency -1370.16 /
        Unrealised -817.81 / Realised -2.99 / Total -820.81 / u.P/L% -7.33."""
        h = {
            "size": 100, "price": 120.54, "value": 10338.72,
            "plBase": {"EUR": -11159.34}, "breakEvenPrice": 114.10,
            "realizedProductPl": {"EUR": 0.0},
            "realizedFxPl":      {"EUR": -3.0},
        }
        info = {"currency": "USD"}
        pl = _compute_pl(h, info, "EUR")
        # Derived total via Position will be value + plBase = -820.62
        # Unrealised = total - realised:
        unrealized = (pl["unrealized_product_pl_base"]
                      + pl["unrealized_currency_pl_base"])
        realized = (pl["realized_product_pl_base"]
                    + pl["realized_currency_pl_base"])
        # _compute_pl now returns Decimal end-to-end (H1); cast for the
        # cent-level numeric comparisons that pin the verified IB01 values.
        self.assertAlmostEqual(float(unrealized), -817.62, places=2)
        self.assertAlmostEqual(float(realized),    -3.00, places=2)
        self.assertAlmostEqual(float(pl["unrealized_product_pl_base"]),   552.36, places=1)
        self.assertAlmostEqual(float(pl["unrealized_currency_pl_base"]), -1369.98, places=1)
        # Cost basis is the absolute negative-plBase
        self.assertAlmostEqual(float(pl["cost_basis"]), 11159.34, places=2)

    def test_open_same_ccy_no_currency_component(self):
        h = {
            "size": 10, "price": 130.0, "value": 1300.0,
            "plBase": {"EUR": -1200.0}, "breakEvenPrice": 120.0,
        }
        pl = _compute_pl(h, {"currency": "EUR"}, "EUR")
        self.assertEqual(pl["unrealized_currency_pl_base"], Decimal("0"))
        self.assertAlmostEqual(float(pl["unrealized_product_pl_base"]), 100.0, places=2)

    def test_closed_position_with_populated_realized_split(self):
        h = {
            "size": 0, "value": 0,
            "plBase": {"EUR": 235.825},
            "realizedProductPl": {"EUR": 200.0},
            "realizedFxPl":      {"EUR": 35.825},
        }
        pl = _compute_pl(h, {"currency": "EUR"}, "EUR")
        self.assertEqual(pl["unrealized_product_pl_base"],  Decimal("0"))
        self.assertEqual(pl["unrealized_currency_pl_base"], Decimal("0"))
        # Honour Degiro's split when it's there
        self.assertAlmostEqual(float(pl["realized_product_pl_base"]),  200.0,   places=3)
        self.assertAlmostEqual(float(pl["realized_currency_pl_base"]),  35.825, places=3)

    def test_closed_position_with_missing_realized_falls_back_to_total(self):
        """If Degiro omits the realised split on a closed row, dump the
        lifetime P/L into realized_product so derived total still holds."""
        h = {"size": 0, "value": 0, "plBase": {"EUR": 128.76}}
        pl = _compute_pl(h, {"currency": "USD"}, "EUR")
        self.assertEqual(pl["realized_product_pl_base"],  Decimal("128.76"))
        self.assertEqual(pl["realized_currency_pl_base"], Decimal("0"))
        self.assertEqual(pl["unrealized_product_pl_base"], Decimal("0"))
        # Sum of all 4 components == value + plBase  (the invariant consumers rely on)
        total = (pl["unrealized_product_pl_base"]
                 + pl["unrealized_currency_pl_base"]
                 + pl["realized_product_pl_base"]
                 + pl["realized_currency_pl_base"])
        self.assertAlmostEqual(float(total), 128.76, places=2)

    def test_decomposition_sum_invariant_cross_ccy(self):
        """For open cross-ccy positions: product + currency = unrealized."""
        h = {
            "size": 50, "price": 200.0, "value": 8500.0,
            "plBase": {"EUR": -9000.0}, "breakEvenPrice": 180.0,
            "realizedProductPl": {"EUR": 10.0},
            "realizedFxPl":      {"EUR": 5.0},
        }
        pl = _compute_pl(h, {"currency": "USD"}, "EUR")
        unrealized = (pl["unrealized_product_pl_base"]
                      + pl["unrealized_currency_pl_base"])
        total_pl = 8500.0 + (-9000.0)
        realized = 10.0 + 5.0
        self.assertAlmostEqual(float(unrealized), total_pl - realized, places=2)

    def test_returns_decimal_not_float(self):
        """H1: money math is Decimal end-to-end — NO field may come back as a
        float (binary-precision pollution in the money-core). Exercises the
        cross-ccy branch, which does the FX-rate back-out divisions."""
        h = {
            "size": 100, "price": 120.54, "value": 10338.72,
            "plBase": {"EUR": -11159.34}, "breakEvenPrice": 114.10,
            "realizedProductPl": {"EUR": 0.0}, "realizedFxPl": {"EUR": -3.0},
        }
        pl = _compute_pl(h, {"currency": "USD"}, "EUR")
        for k, v in pl.items():
            self.assertIsInstance(v, Decimal, f"{k} is {type(v).__name__}, not Decimal")


# ───────────────────────────────────────────────────────────────────────────
# Layer 3 — to_canonical end-to-end (raw payload -> PortfolioSnapshot)
# ───────────────────────────────────────────────────────────────────────────
def _raw_position(*, pid, size, price, value, plbase_eur, bep,
                  realized_product=0.0, realized_fx=0.0, position_type="PRODUCT"):
    """Mint a Degiro-shaped portfolio row from concise kwargs."""
    return {"value": [
        {"name": "id",                "value": str(pid)},
        {"name": "positionType",      "value": position_type},
        {"name": "size",              "value": size},
        {"name": "price",             "value": price},
        {"name": "value",             "value": value},
        {"name": "plBase",            "value": {"EUR": plbase_eur}},
        {"name": "breakEvenPrice",    "value": bep},
        {"name": "realizedProductPl", "value": {"EUR": realized_product}},
        {"name": "realizedFxPl",      "value": {"EUR": realized_fx}},
    ]}


def _raw_cash(*, ccy, amount):
    return {"value": [
        {"name": "id",            "value": ccy},
        {"name": "currencyCode",  "value": ccy},
        {"name": "value",         "value": amount},
    ]}


class TestToCanonicalEndToEnd(unittest.TestCase):
    def setUp(self):
        # One open USD ETF (IB01-shaped) + one closed EUR ETF + EUR cash.
        self.raw_update = {
            "portfolio": {"value": [
                _raw_position(pid=12345, size=100, price=120.54, value=10338.72,
                              plbase_eur=-11159.34, bep=114.10,
                              realized_product=0.0, realized_fx=-3.0),
                _raw_position(pid=67890, size=0, price=126.02, value=0,
                              plbase_eur=235.825, bep=0,
                              realized_product=0, realized_fx=0),
            ]},
            "cashFunds": {"value": [
                _raw_cash(ccy="EUR", amount=155.67),
            ]},
            "totalPortfolio": {"value": [
                {"name": "totalCash", "value": 155.67},
            ]},
        }
        self.raw_products = {
            "12345": {"symbol": "IB01", "isin": "IE00BGSF1X88",
                      "name": "iShares $ Treasury Bond 0-1yr UCITS ETF",
                      "currency": "USD", "productType": "ETF",
                      "exchangeId": "LSE"},
            "67890": {"symbol": "4GLD", "isin": "DE000A0S9GB0",
                      "name": "Xetra-Gold ETC",
                      "currency": "EUR", "productType": "ETF",
                      "exchangeId": "XETRA"},
        }
        self.snapshot = to_canonical(self.raw_update, self.raw_products,
                                     base_ccy="EUR", int_account=12345678)

    def test_account_normalized(self):
        a = self.snapshot.account
        self.assertEqual(a.account_id,    "12345678")
        self.assertEqual(a.broker,        "degiro")
        self.assertEqual(a.base_currency, "EUR")

    def test_instruments_built_once_per_isin(self):
        self.assertEqual(len(self.snapshot.instruments), 2)
        by_id = {i.instrument_id: i for i in self.snapshot.instruments}
        # Canonical id is ISIN-form when ISIN is shipped (cross-source key);
        # productId is still preserved under identifiers["broker:degiro"].
        self.assertIn("degiro:isin:IE00BGSF1X88", by_id)
        self.assertIn("degiro:isin:DE000A0S9GB0", by_id)
        ib01 = by_id["degiro:isin:IE00BGSF1X88"]
        self.assertEqual(ib01.identifiers["ticker"],         "IB01")
        self.assertEqual(ib01.identifiers["isin"],           "IE00BGSF1X88")
        self.assertEqual(ib01.identifiers["broker:degiro"],  "12345")
        self.assertEqual(ib01.asset_class,                   AssetClass.ETF)
        self.assertEqual(ib01.listing_currency,              "USD")

    def test_open_position_p_l_decomposition_to_the_cent(self):
        ib01 = next(p for p in self.snapshot.positions
                    if p.instrument_id == "degiro:isin:IE00BGSF1X88")
        self.assertEqual(ib01.quantity,                Decimal("100"))
        self.assertEqual(ib01.last_price_local,        Decimal("120.54"))
        self.assertEqual(ib01.value_base,              Decimal("10338.72"))
        self.assertEqual(ib01.break_even_price_local,  Decimal("114.10"))
        # Derived fields satisfy the invariants:
        self.assertAlmostEqual(float(ib01.unrealized_pl_base),  -817.62, places=2)
        self.assertAlmostEqual(float(ib01.realized_pl_base),      -3.00, places=2)
        self.assertAlmostEqual(float(ib01.total_pl_base),       -820.62, places=2)
        # And it's open:
        self.assertTrue(ib01.is_open)

    def test_closed_position_is_marked_closed(self):
        glb = next(p for p in self.snapshot.positions
                   if p.instrument_id == "degiro:isin:DE000A0S9GB0")
        self.assertFalse(glb.is_open)
        self.assertEqual(glb.unrealized_pl_base, Decimal("0"))
        # Lifetime total = plBase (since value=0); realized invariant holds:
        self.assertEqual(glb.total_pl_base, glb.realized_pl_base)
        self.assertAlmostEqual(float(glb.total_pl_base), 235.825, places=3)

    def test_cash_balance_normalized(self):
        self.assertEqual(len(self.snapshot.cash_balances), 1)
        c = self.snapshot.cash_balances[0]
        self.assertEqual(c.currency, "EUR")
        self.assertEqual(c.amount,   Decimal("155.67"))
        self.assertIsNone(c.amount_base,
                          "amount_base must be None until sq-fx exists")

    def test_snapshot_fk_integrity_holds_automatically(self):
        # PortfolioSnapshot's validator runs; if FKs were mismatched, this
        # snapshot wouldn't have constructed in the first place.
        self.assertEqual(self.snapshot.positions[0].account_id, "12345678")
        for p in self.snapshot.positions:
            self.assertIn(p.instrument_id,
                          {i.instrument_id for i in self.snapshot.instruments})

    def test_snapshot_passes_conformance(self):
        """Dogfood the conformance harness — a real-shaped snapshot must
        come back clean. If a future to_canonical refactor introduces a
        duplicate Position or a sign error, this test fails immediately."""
        violations = conformance.check_snapshot(self.snapshot)
        self.assertEqual(
            violations, [],
            f"to_canonical produced a non-conformant snapshot:\n"
            f"{conformance.format_violations(violations)}",
        )

    def test_duplicate_isin_productids_collapse_to_one_position(self):
        """Degiro can split one ISIN across multiple productIds (corporate
        actions / venue splits). The canonical contract is one Position
        per (account, instrument), so to_canonical must merge them BEFORE
        emitting — otherwise downstream conformance fires on
        duplicate-position and the position count is artificially
        inflated. Money sums; quantities sum; BEP is qty-weighted."""
        # Two productIds sharing one ISIN — both still trading, with
        # different prices/qty: 5 @ 100 and 3 @ 200 -> merged qty 8,
        # value 1100 (= 500 + 600), cost 800 (= 500 + 300), BEP =
        # (5*100 + 3*200)/8 = 137.5
        raw_dup = dict(self.raw_update)
        raw_dup["portfolio"] = {"value": [
            _raw_position(pid=11111, size=5, price=100, value=500,
                          plbase_eur=0, bep=100),
            _raw_position(pid=22222, size=3, price=200, value=600,
                          plbase_eur=0, bep=200),
        ]}
        raw_prods_dup = {
            "11111": {"symbol": "DUP-A", "isin": "GB00DUPLICATE",
                      "name": "Dup Co class A",
                      "currency": "EUR", "productType": "STOCK"},
            "22222": {"symbol": "DUP-B", "isin": "GB00DUPLICATE",
                      "name": "Dup Co class B",
                      "currency": "EUR", "productType": "STOCK"},
        }
        snap = to_canonical(raw_dup, raw_prods_dup,
                            base_ccy="EUR", int_account=12345678)
        # Exactly one Position on the shared ISIN
        positions_on_isin = [p for p in snap.positions
                             if p.instrument_id == "degiro:isin:GB00DUPLICATE"]
        self.assertEqual(len(positions_on_isin), 1)
        merged = positions_on_isin[0]
        self.assertEqual(merged.quantity,       Decimal("8"))
        self.assertEqual(merged.value_base,     Decimal("1100"))
        self.assertAlmostEqual(float(merged.break_even_price_local),
                               137.5, places=4)
        # Snapshot still passes the conformance gate
        self.assertEqual(conformance.check_snapshot(snap), [])

    def test_skips_non_product_rows(self):
        """positionType != 'PRODUCT' rows (cash hooks, sweeps, etc.) are
        intentionally dropped from positions."""
        raw_with_cash_row = dict(self.raw_update)
        raw_with_cash_row["portfolio"] = {"value": list(self.raw_update["portfolio"]["value"]) + [
            _raw_position(pid=99999, size=100, price=1, value=100,
                          plbase_eur=0, bep=0, position_type="CASH"),
        ]}
        snap = to_canonical(raw_with_cash_row, self.raw_products,
                            base_ccy="EUR", int_account=12345678)
        # Still only the two PRODUCT positions
        self.assertEqual(len(snap.positions), 2)


class TestExtractBaseCcy(unittest.TestCase):
    def test_finds_from_account_info_data_currency(self):
        self.assertEqual(
            extract_base_ccy({"data": {"currency": "EUR"}}, None, None),
            "EUR",
        )

    def test_finds_from_client_details_nested(self):
        self.assertEqual(
            extract_base_ccy(None,
                             {"data": {"intAccountInfo": {"currency": "GBP"}}},
                             None),
            "GBP",
        )

    def test_falls_back_to_cash_heuristic(self):
        """No currency field anywhere — single-ccy cash list wins."""
        ccy = extract_base_ccy(None, None, {
            "cashFunds": {"value": [_raw_cash(ccy="EUR", amount=155.67)]},
        })
        self.assertEqual(ccy, "EUR")

    def test_returns_none_when_multi_ccy_cash_and_no_explicit_field(self):
        ccy = extract_base_ccy(None, None, {
            "cashFunds": {"value": [
                _raw_cash(ccy="EUR", amount=100),
                _raw_cash(ccy="USD", amount=50),
            ]},
        })
        self.assertIsNone(ccy)


if __name__ == "__main__":
    unittest.main()
