"""sq_price_store — the append-only bitemporal price archive.

The contracts that matter:
- append-only: a disagreeing re-fetch APPENDS, never rewrites; reads are
  last-observation-wins (split-adjustment honesty).
- write-side dedup: re-recording identical values appends nothing, so a
  daily refresh stays O(new).
- faithfulness: raw prices + raw currency codes (GBp stays GBp here;
  normalisation is the consumer's job).
- robustness: torn/garbage lines are skipped, never fatal.
"""
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

from sq_price_store import PriceStore, _fname            # noqa: E402


D = Decimal


class TestPriceStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PriceStore(root=Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip(self):
        n = self.store.record_series(
            "IB01.L",
            {date(2024, 1, 2): D("100.5"), date(2024, 1, 3): D("101")},
            currency="GBp", source="yahoo")
        self.assertEqual(n, 2)
        loaded = self.store.load_series("IB01.L")
        self.assertEqual(loaded["series"][date(2024, 1, 2)], D("100.5"))
        self.assertEqual(loaded["currency"], "GBp")     # raw, not normalised

    def test_dedup_on_identical_refetch(self):
        series = {date(2024, 1, 2): D("100.5")}
        self.store.record_series("AAPL", series, currency="USD", source="yahoo")
        n = self.store.record_series("AAPL", series, currency="USD",
                                     source="yahoo")
        self.assertEqual(n, 0)                          # nothing new → no rows
        # and a FRESH store instance (no in-memory index) also dedups
        store2 = PriceStore(root=Path(self._tmp.name))
        n = store2.record_series("AAPL", series, currency="USD", source="yahoo")
        self.assertEqual(n, 0)

    def test_restatement_appends_and_last_wins(self):
        d = date(2024, 1, 2)
        self.store.record_series("TSLA", {d: D("300")}, currency="USD",
                                 source="yahoo")
        # split-adjusted re-fetch disagrees → must append, not rewrite
        n = self.store.record_series("TSLA", {d: D("100")}, currency="USD",
                                     source="yahoo")
        self.assertEqual(n, 1)
        self.assertEqual(self.store.load_series("TSLA")["series"][d], D("100"))
        # both observations remain on disk (bitemporal honesty)
        raw = (Path(self._tmp.name) / _fname("TSLA")).read_text()
        self.assertEqual(raw.count('"d":"2024-01-02"'), 2)

    def test_events_round_trip(self):
        self.store.record_events("AAPL", {date(2024, 2, 9): D("0.24")},
                                 kind="div", source="yahoo")
        self.store.record_events("AAPL", {date(2020, 8, 31): D("4")},
                                 kind="split", source="yahoo")
        self.assertEqual(self.store.load_events("AAPL", kind="div"),
                         {date(2024, 2, 9): D("0.24")})
        self.assertEqual(self.store.load_events("AAPL", kind="split"),
                         {date(2020, 8, 31): D("4")})
        # event rows never leak into the price series
        self.assertIsNone(self.store.load_series("AAPL"))

    def test_awkward_tickers_get_safe_distinct_files(self):
        for t in ("^GSPC", "EURUSD=X", "BRK.B", "IB01.L"):
            self.store.record_series(t, {date(2024, 1, 2): D("1")},
                                     currency="USD", source="yahoo")
        self.assertEqual(self.store.tickers(),
                         sorted(["^GSPC", "EURUSD=X", "BRK.B", "IB01.L"]))
        for p in Path(self._tmp.name).glob("*.jsonl"):
            self.assertNotIn("/", p.stem)
            self.assertNotIn("=", p.stem)

    def test_torn_line_skipped(self):
        self.store.record_series("AAPL", {date(2024, 1, 2): D("100")},
                                 currency="USD", source="yahoo")
        path = Path(self._tmp.name) / _fname("AAPL")
        with open(path, "a") as f:
            f.write('{"t":"price","d":"2024-01-03","v":"10')   # torn write
        loaded = self.store.load_series("AAPL")
        self.assertEqual(len(loaded["series"]), 1)             # bad line skipped

    def test_coverage(self):
        self.assertIsNone(self.store.coverage("NOPE"))
        self.store.record_series(
            "AAPL", {date(2020, 1, 2): D("1"), date(2024, 6, 3): D("2")},
            currency="USD", source="yahoo")
        self.assertEqual(self.store.coverage("AAPL"),
                         (date(2020, 1, 2), date(2024, 6, 3)))

    def test_env_var_default_root(self):
        import os
        old = os.environ.get("SQ_PRICE_ARCHIVE_PATH")
        os.environ["SQ_PRICE_ARCHIVE_PATH"] = self._tmp.name
        try:
            s = PriceStore()
            self.assertEqual(s.root, Path(self._tmp.name))
        finally:
            if old is None:
                del os.environ["SQ_PRICE_ARCHIVE_PATH"]
            else:
                os.environ["SQ_PRICE_ARCHIVE_PATH"] = old


if __name__ == "__main__":
    unittest.main()
