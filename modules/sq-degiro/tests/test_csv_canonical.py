"""sq-degiro CSV → canonical Transactions adapter — conformance + reconciliation.

The headline test: the pre-canonical realised P/L (computed directly from
Total EUR in `pnl.py.compute()`) MUST agree with the event-sourcing path
(`to_canonical_transactions()` → `fold_position()` per closed instrument)
to the cent. Same data, two different code paths, identical answer.

If this ever drifts, one of the two paths has silently introduced a bug.
The schema/event-sourcing path is the long-term truth; pnl.py is the
historical reference. We keep them lockstep so we can trust the migration.
"""
import sys
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_degiro.canonical import to_canonical_transactions           # noqa: E402
from sq_degiro.pnl import compute as pnl_compute                    # noqa: E402
from sq_schema import Transaction, TransactionType                   # noqa: E402
from sq_compute import CostBasisMethod, fold_position                # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _by_instrument(transactions):
    """Group canonical transactions by instrument_id."""
    out = {}
    for t in transactions:
        out.setdefault(t.instrument_id, []).append(t)
    return out


class TestToCanonicalTransactions(unittest.TestCase):
    """Shape-level checks on the adapter output."""

    def setUp(self):
        self.txns = to_canonical_transactions(
            FIXTURES / "transactions.csv",
            account_id="acct-test",
        )

    def test_emits_one_transaction_per_csv_row(self):
        # Fixture has 3 trade rows
        self.assertEqual(len(self.txns), 3)

    def test_buy_vs_sell_classification(self):
        types = sorted(t.type for t in self.txns)
        self.assertEqual(types, [TransactionType.BUY,
                                 TransactionType.BUY,
                                 TransactionType.SELL])

    def test_quantity_signs_match_csv(self):
        by_id = sorted(self.txns, key=lambda t: t.transaction_id)
        self.assertEqual(by_id[0].transaction_id, "order1")  # BUY 10 TestCo
        self.assertEqual(by_id[0].quantity, Decimal("10"))
        self.assertEqual(by_id[1].transaction_id, "order2")  # SELL -10 TestCo
        self.assertEqual(by_id[1].quantity, Decimal("-10"))
        self.assertEqual(by_id[2].transaction_id, "order3")  # BUY 5 OpenCo
        self.assertEqual(by_id[2].quantity, Decimal("5"))

    def test_amount_matches_total_eur_column(self):
        """`Total EUR` in CSV becomes the canonical `amount` (signed, fees-inclusive)."""
        by_id = {t.transaction_id: t for t in self.txns}
        self.assertEqual(by_id["order1"].amount, Decimal("-100.00"))
        self.assertEqual(by_id["order2"].amount, Decimal("120.00"))
        self.assertEqual(by_id["order3"].amount, Decimal("-100.00"))

    def test_instrument_id_uses_broker_isin_scheme(self):
        ids = {t.instrument_id for t in self.txns}
        self.assertIn("degiro:isin:TEST0000001", ids)        # TestCo
        self.assertIn("degiro:isin:TEST0000002", ids)        # OpenCo

    def test_price_local_preserved(self):
        by_id = {t.transaction_id: t for t in self.txns}
        self.assertEqual(by_id["order1"].price_local, Decimal("10"))
        self.assertEqual(by_id["order2"].price_local, Decimal("12"))
        self.assertEqual(by_id["order3"].price_local, Decimal("20"))

    def test_amount_currency_validated_as_eur(self):
        for t in self.txns:
            self.assertEqual(t.amount_currency, "EUR")

    def test_zero_fees_emitted_as_none(self):
        """Fixture has all-zero fees — adapter normalises 0 → None for tidiness."""
        for t in self.txns:
            self.assertIsNone(t.fee)

    def test_order_id_read_from_both_shapes(self):
        """Real exports leave col 16 empty and carry the uuid at 17; older /
        synthetic shapes put it at 16. The fixture has both — every row must
        still get its broker-stable id (regression: ids silently fell back
        to row-N for ALL real exports until 2026-06-11)."""
        ids = {t.transaction_id for t in self.txns}
        self.assertEqual(ids, {"order1", "order2", "order3"})


class TestForeignListingRows(unittest.TestCase):
    """Foreign-listing trades (GBX/USD local currency, real-export shape).

    Column 10 repeats the LOCAL currency — it is NOT the cash-leg currency.
    The cash leg ('Total EUR') is always account-base EUR; labelling it GBX
    or USD broke every downstream FX join (income summary, XIRR flows).
    Rows are verbatim from a real export, ISINs anonymised."""

    def setUp(self):
        self.txns = to_canonical_transactions(
            FIXTURES / "transactions_foreign.csv",
            account_id="acct-test",
        )
        self.by_id = {t.transaction_id: t for t in self.txns}

    def test_cash_leg_is_eur_not_local_ccy(self):
        for t in self.txns:
            self.assertEqual(t.amount_currency, "EUR")

    def test_amount_is_total_eur(self):
        self.assertEqual(self.by_id["uuid-gbx-sell"].amount,
                         Decimal("104.28"))
        self.assertEqual(self.by_id["uuid-usd-buy"].amount,
                         Decimal("-11159.34"))

    def test_price_stays_in_local_currency(self):
        # price_local remains GBX-denominated; fx_rate (inverted CSV rate)
        # is what converts it — 1/89.21 EUR per GBX.
        self.assertEqual(self.by_id["uuid-gbx-sell"].price_local,
                         Decimal("295.9000"))
        fx = self.by_id["uuid-gbx-sell"].fx_rate
        self.assertEqual(fx, Decimal(1) / Decimal("89.2100"))

    def test_fees_are_magnitudes(self):
        self.assertEqual(self.by_id["uuid-gbx-sell"].fee,
                         Decimal("0.27") + Decimal("4.90"))
        self.assertEqual(self.by_id["uuid-usd-buy"].fee,
                         Decimal("27.82") + Decimal("3.00"))


class TestShortRows(unittest.TestCase):
    def test_sixteen_column_row_still_parses(self):
        """A trade row that ends at Total EUR (col 15) with NO order-id
        columns at all is a valid trade — requiring ≥17 columns silently
        dropped it (audit 2026-06-11). Money completeness must never be
        hostage to a trailing optional column."""
        import tempfile
        header = ("Date,Time,Product,ISIN,Reference exchange,Venue,"
                  "Quantity,Price,,Local value,,Value EUR,Exchange rate,"
                  "AutoFX Fee,Transaction and/or third party fees EUR,"
                  "Total EUR")
        row16 = ('14-01-2024,09:00,TestCo,TEST0000001,XAMS,XAMS,10,'
                 '"10,0000",EUR,"-100,00",EUR,"-100,00",,"0,00","0,00",'
                 '"-100,00"')
        with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                         delete=False) as f:
            f.write(header + "\n" + row16 + "\n")
            path = f.name
        txns = to_canonical_transactions(Path(path), account_id="acct")
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].amount, Decimal("-100.00"))
        self.assertTrue(txns[0].transaction_id.startswith("row-"))


# ───────────────────────────────────────────────────────────────────────────
# THE RECONCILIATION TEST — the whole point of this work
# ───────────────────────────────────────────────────────────────────────────
class TestPnlReconciliation(unittest.TestCase):
    """Realized P/L computed via fold_position over canonical Transactions
    MUST match pnl.py's pre-canonical direct-summation realised P/L for
    every fully-closed position. Same data, two paths, identical answer."""

    def setUp(self):
        self.pnl = pnl_compute(FIXTURES)
        self.txns = to_canonical_transactions(
            FIXTURES / "transactions.csv",
            account_id="acct-test",
        )
        self.by_instrument = _by_instrument(self.txns)

    def test_fixture_has_one_closed_position(self):
        """TestCo: BUY 10 + SELL 10 = net 0 (closed). OpenCo: BUY 5 only (open)."""
        self.assertEqual(len(self.pnl["closed"]), 1)
        self.assertEqual(len(self.pnl["open"]),   1)

    def test_fold_matches_pnl_for_closed_position(self):
        """The headline conformance check: per-instrument realised P/L matches
        between the two paths DIRECTLY. fold_position is now fees-inclusive
        (matches pnl.py's sum-of-Total-EUR semantics), so no adjustment needed."""
        pnl_realized_by_isin = {
            isin: pnl for (_, isin, pnl) in self.pnl["closed"]
        }
        for isin, expected in pnl_realized_by_isin.items():
            instrument_id = f"degiro:isin:{isin}"
            txns_for = self.by_instrument.get(instrument_id, [])
            self.assertTrue(txns_for, f"no canonical txns for {isin}")
            pos = fold_position(
                account_id="acct-test",
                instrument_id=instrument_id,
                base_currency="EUR",
                transactions=txns_for,
                method=CostBasisMethod.FIFO,
            )
            self.assertEqual(
                pos.realized_pl_base, expected,
                f"realised P/L mismatch for {isin}: "
                f"pnl.py={expected} vs fold(canonical)={pos.realized_pl_base}",
            )

    def test_fold_matches_pnl_total_realized(self):
        """Aggregate check — sum across all closed positions agrees DIRECTLY."""
        pnl_total = self.pnl["realized"]
        canon_total = Decimal("0")
        for (_, isin, _expected) in self.pnl["closed"]:
            instrument_id = f"degiro:isin:{isin}"
            txns_for = self.by_instrument.get(instrument_id, [])
            pos = fold_position(
                account_id="acct-test",
                instrument_id=instrument_id,
                base_currency="EUR",
                transactions=txns_for,
                method=CostBasisMethod.FIFO,
            )
            canon_total += pos.realized_pl_base
        self.assertEqual(canon_total, pnl_total)


# ───────────────────────────────────────────────────────────────────────────
# Bitemporal stamping on parsed transactions
# ───────────────────────────────────────────────────────────────────────────
class TestBitemporalStamping(unittest.TestCase):
    def setUp(self):
        self.txns = to_canonical_transactions(
            FIXTURES / "transactions.csv",
            account_id="acct-test",
        )

    def test_executed_at_combines_date_and_time(self):
        by_id = {t.transaction_id: t for t in self.txns}
        # order1: 14-01-2024 09:00
        self.assertEqual(by_id["order1"].executed_at.date(),
                         datetime(2024, 1, 14).date())
        self.assertEqual(by_id["order1"].executed_at.hour, 9)
        self.assertEqual(by_id["order1"].executed_at.minute, 0)

    def test_valid_at_equals_executed_at(self):
        for t in self.txns:
            self.assertEqual(t.valid_at, t.executed_at)


class TestCrossCurrencyFxDirection(unittest.TestCase):
    """Regression test for the fx_rate convention bug.

    Degiro's CSV `Exchange rate` column carries the rate in the broker's
    convention: amount_local = amount_base × rate (so 86.24 for a
    GBX-priced row settled in EUR means 1 EUR = 86.24 GBX). Our canonical
    `Transaction.fx_rate` is the INVERSE — how many amount-ccy units per
    one instrument-ccy unit. The adapter must invert at the boundary.

    The original symptom (caught against real Degiro CSV history): GBX-
    priced GB stocks produced realized P/L numbers 7,000× too large
    because fold_position multiplied price × 86.24 instead of × 0.01159.
    """

    def _csv(self, body: str) -> Path:
        import tempfile
        header = (
            "Date,Time,Product,ISIN,Reference exchange,Venue,Quantity,Price,,"
            "Local value,,Value EUR,Exchange rate,AutoFX Fee,"
            "Transaction and/or third party fees EUR,Total EUR,Order ID,\n"
        )
        f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                        encoding="utf-8")
        f.write(header + body)
        f.close()
        return Path(f.name)

    def test_csv_fx_rate_is_inverted_into_canonical_convention(self):
        # USD-listed buy settled in EUR; CSV rate 1.0500 means 1 EUR = 1.05 USD.
        # Canonical fx_rate must be 1/1.05 ≈ 0.9524 EUR per USD.
        csv_path = self._csv(
            '14-01-2024,09:00,TestCo,USTEST,NYSE,NYSE,10,"100,0000",USD,'
            '"-1000,00",EUR,"-952,38","1,0500000","0,00","0,00","-952,38",'
            'order-x,\n'
        )
        try:
            txns = to_canonical_transactions(csv_path, account_id="A")
        finally:
            csv_path.unlink()
        self.assertEqual(len(txns), 1)
        t = txns[0]
        self.assertIsNotNone(t.fx_rate)
        # Expected: 1 / Decimal("1.0500000")
        self.assertEqual(t.fx_rate, Decimal(1) / Decimal("1.0500000"))

    def test_empty_csv_fx_yields_none_for_same_currency_row(self):
        # EUR-listed row (no FX) -> CSV Exchange rate column is empty.
        # Canonical fx_rate must be None so _derive_fx falls through.
        csv_path = self._csv(
            '14-01-2024,09:00,EurCo,EURTEST,XAMS,XAMS,10,"10,0000",EUR,'
            '"-100,00",EUR,"-100,00",,"0,00","0,00","-100,00",order-y,\n'
        )
        try:
            txns = to_canonical_transactions(csv_path, account_id="A")
        finally:
            csv_path.unlink()
        self.assertIsNone(txns[0].fx_rate)

    def test_fold_produces_correct_cost_basis_for_cross_currency(self):
        """End-to-end: a USD-listed buy folded with the corrected adapter
        produces cost_basis_base matching the EUR amount on the CSV
        (within Decimal precision)."""
        csv_path = self._csv(
            '14-01-2024,09:00,TestCo,USTEST,NYSE,NYSE,10,"100,0000",USD,'
            '"-1000,00",EUR,"-952,38","1,0500000","0,00","0,00","-952,38",'
            'order-x,\n'
        )
        try:
            txns = to_canonical_transactions(csv_path, account_id="A")
        finally:
            csv_path.unlink()
        pos = fold_position(
            account_id="A", instrument_id=txns[0].instrument_id,
            base_currency="EUR", transactions=txns,
            method=CostBasisMethod.FIFO,
        )
        # Expected cost basis (10 shares × $100 × (1/1.05) EUR/USD),
        # quantized to fold_position's 8dp money quantum.
        raw = Decimal(10) * Decimal("100") * (Decimal(1) / Decimal("1.0500000"))
        expected = raw.quantize(Decimal("0.00000001"))
        self.assertEqual(pos.cost_basis_base, expected)
        # Sanity vs the CSV's Total EUR (≈ 952.38 EUR)
        self.assertAlmostEqual(float(pos.cost_basis_base), 952.38, places=2)


if __name__ == "__main__":
    unittest.main()
