"""sq_market_data.ChainProvider — first-non-None price-source composition."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

from sq_market_data import ChainProvider                 # noqa: E402
from sq_schema import Price, PriceProvider               # noqa: E402

NOW = datetime(2024, 1, 2, tzinfo=timezone.utc)


def _price(px, source):
    return Price(valid_at=NOW, observed_at=NOW, instrument_id=None,
                 last_price_local=Decimal(px), currency="USD", source=source)


class _Stub:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def get_price(self, ticker, *, asof=None):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class TestChainProvider(unittest.TestCase):
    def test_satisfies_protocol(self):
        self.assertIsInstance(ChainProvider(), PriceProvider)

    def test_first_answer_wins(self):
        a, b = _Stub(_price("1", "a")), _Stub(_price("2", "b"))
        out = ChainProvider(a, b).get_price("X")
        self.assertEqual(out.source, "a")
        self.assertEqual(b.calls, 0)                  # never consulted

    def test_falls_through_none(self):
        a, b = _Stub(None), _Stub(_price("2", "b"))
        out = ChainProvider(a, b).get_price("X")
        self.assertEqual(out.source, "b")

    def test_raising_rung_treated_as_none(self):
        a, b = _Stub(RuntimeError("down")), _Stub(_price("2", "b"))
        out = ChainProvider(a, b).get_price("X")
        self.assertEqual(out.source, "b")

    def test_all_dry_returns_none(self):
        self.assertIsNone(ChainProvider(_Stub(None), _Stub(None)).get_price("X"))

    def test_none_providers_skipped_at_construction(self):
        b = _Stub(_price("2", "b"))
        out = ChainProvider(None, b).get_price("X")
        self.assertEqual(out.source, "b")


if __name__ == "__main__":
    unittest.main()
