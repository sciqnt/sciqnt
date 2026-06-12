"""CSV enrichment of the live snapshot — math contract.

Pins the iron contract: when a Degiro live snapshot is enriched from
CSV history, the sum of realised P/L decomposition equals the sum from
`sq_analytics.tax_lots()` over the same CSV stream. Without this
enrichment the live API's `realized_fees_base = 0` quietly overstates
realised gains.

The test uses a synthetic Degiro "live" payload (no network) + a
CSV transaction stream that intersects on instrument_id.
"""
import csv
import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

from sq_analytics import all_tax_lots                                       # noqa: E402
from sq_degiro import _enrich_realized_from_csv                             # noqa: E402
from sq_schema import (                                                    # noqa: E402
    Account, AssetClass, CashBalance, Instrument, PortfolioSnapshot, Position,
)
from sq_degiro.canonical import to_canonical_transactions                   # noqa: E402


def _ts(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _write_csv(rows):
    """Write a Degiro-style transactions.csv with synthetic rows. Returns
    the Path; caller cleans up."""
    f = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, encoding="utf-8-sig", newline="")
    w = csv.writer(f)
    # Header — must match the column count to_canonical_transactions expects
    w.writerow([
        "Date", "Time", "Product", "ISIN", "Reference", "Venue",
        "Quantity", "Price", "Price ccy", "Local value", "Local ccy",
        "Total EUR", "Exchange rate", "AutoFX Fee", "Other fees",
        "Total EUR_2", "Order ID", "",
    ])
    for r in rows:
        w.writerow(r)
    f.close()
    return Path(f.name)


def _synth_live_snapshot(realized_product=Decimal("100"),
                         realized_fees=Decimal("0"),
                         qty=Decimal("0"), value=Decimal("0")):
    """Build a synthetic live-shape snapshot for a single closed position.
    Mirrors the live API path's output: realized_fees_base = 0."""
    inst = Instrument(
        instrument_id="degiro:isin:TESTABC123",
        identifiers={"isin": "TESTABC123", "broker:degiro": "TESTABC123",
                     "ticker": "ABC"},
        name="Test Co", asset_class=AssetClass.STOCK, listing_currency="EUR",
    )
    acct = Account(account_id="degiro", broker="degiro", base_currency="EUR")
    pos = Position(
        account_id="degiro", instrument_id=inst.instrument_id,
        quantity=qty, value_base=value, cost_basis_base=Decimal("0"),
        last_price_local=None,
        unrealized_product_pl_base=Decimal("0"),
        unrealized_currency_pl_base=Decimal("0"),
        realized_product_pl_base=realized_product,
        realized_currency_pl_base=Decimal("0"),
        realized_fees_base=realized_fees,           # ← always 0 from live API
    )
    return PortfolioSnapshot(
        account=acct, instruments=[inst], positions=[pos], cash_balances=[],
    )


class TestEnrichmentMath(unittest.TestCase):
    def test_realized_fees_pulled_in_from_csv_fold(self):
        # CSV: BUY 10 @ 100 EUR with €5 fee, SELL 10 @ 130 EUR with €3 fee
        csv_path = _write_csv([
            ['14-01-2024', '09:00', 'Test Co', 'TESTABC123', 'order-1', 'XAMS',
             '10', '"100,0000"', 'EUR', '"-1000,00"', 'EUR',
             '"-1005,00"', '"1,0000"', '"-5,00"', '"0,00"', '"-1005,00"',
             'order-buy', ''],
            ['14-06-2024', '15:00', 'Test Co', 'TESTABC123', 'order-2', 'XAMS',
             '-10', '"130,0000"', 'EUR', '"1300,00"', 'EUR',
             '"1297,00"', '"1,0000"', '"-3,00"', '"0,00"', '"1297,00"',
             'order-sell', ''],
        ])
        try:
            txns = to_canonical_transactions(csv_path, account_id="degiro")
        finally:
            csv_path.unlink()

        # Live snapshot says realised = +300 (price math), fees = 0
        live_snap = _synth_live_snapshot(
            realized_product=Decimal("300"), realized_fees=Decimal("0"),
            qty=Decimal("0"), value=Decimal("0"),
        )

        enriched = _enrich_realized_from_csv(live_snap, txns, "EUR")
        pos = enriched.positions[0]
        # Truth: product = (130-100)*10 = 300 (same as live, unchanged)
        # Fees: buy €5 + sell €3 = €8 total, with sign = -8
        self.assertEqual(pos.realized_product_pl_base, Decimal("300.00000000"))
        self.assertEqual(pos.realized_fees_base,       Decimal("-8.00000000"))
        # Total realised = +300 - 8 = +292 (was +300 in live; correctly reduced)
        self.assertEqual(pos.realized_pl_base, Decimal("292.00000000"))

    def test_aggregated_realized_equals_tax_lots_sum(self):
        """The load-bearing reconciliation: after enrichment, sum of
        Position.realized_pl_base across all positions equals sum of
        ClosedLot.realized_pl_base from tax_lots() — to the cent."""
        csv_path = _write_csv([
            ['10-01-2024', '09:00', 'Test Co', 'TESTABC123', 'order-1', 'XAMS',
             '10', '"100,0000"', 'EUR', '"-1000,00"', 'EUR',
             '"-1005,00"', '"1,0000"', '"-5,00"', '"0,00"', '"-1005,00"',
             'b1', ''],
            ['15-03-2024', '14:00', 'Test Co', 'TESTABC123', 'order-2', 'XAMS',
             '-5', '"120,0000"', 'EUR', '"600,00"', 'EUR',
             '"598,00"', '"1,0000"', '"-2,00"', '"0,00"', '"598,00"',
             's1', ''],
            ['20-06-2024', '11:00', 'Test Co', 'TESTABC123', 'order-3', 'XAMS',
             '-5', '"130,0000"', 'EUR', '"650,00"', 'EUR',
             '"648,00"', '"1,0000"', '"-2,00"', '"0,00"', '"648,00"',
             's2', ''],
        ])
        try:
            txns = to_canonical_transactions(csv_path, account_id="degiro")
        finally:
            csv_path.unlink()

        live_snap = _synth_live_snapshot(
            realized_product=Decimal("250"), realized_fees=Decimal("0"),
        )
        enriched = _enrich_realized_from_csv(live_snap, txns, "EUR")
        positions_sum = sum(
            (p.realized_pl_base for p in enriched.positions), Decimal("0"))
        closures = all_tax_lots(txns, account_id="degiro", base_currency="EUR")
        closures_sum = sum(
            (c.realized_pl_base for c in closures), Decimal("0"))
        self.assertEqual(positions_sum, closures_sum,
                         "after CSV enrichment, sum of Position.realized_pl_base "
                         "must equal sum of ClosedLot.realized_pl_base; if this "
                         "breaks, the live snapshot and tax_lots have drifted")

    def test_position_without_csv_match_passes_through(self):
        """A live Position whose instrument_id doesn't appear in the
        CSV stream is left untouched — never silently wiped."""
        live_snap = _synth_live_snapshot(
            realized_product=Decimal("42"), realized_fees=Decimal("0"),
        )
        # CSV has zero rows for that instrument
        enriched = _enrich_realized_from_csv(live_snap, [], "EUR")
        pos = enriched.positions[0]
        self.assertEqual(pos.realized_product_pl_base, Decimal("42"))
        self.assertEqual(pos.realized_fees_base,       Decimal("0"))


if __name__ == "__main__":
    unittest.main()
