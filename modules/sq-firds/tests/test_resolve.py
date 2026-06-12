"""sq-firds resolver — Solr parsing + CFI mapping, all HTTP mocked.

Pins (fixture rows mirror REAL FIRDS responses, 2026-06-11):
  - tombstone rows (null gnr_full_name) are filtered out
  - the picker prefers non-CANC rows but accepts TERM/CANC-only ISINs
    (fully delisted instruments keep good reference data)
  - CFI → canonical AssetClass key mapping on real codes
  - unknown ISIN → None
"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-firds" / "src"))

from sq_firds import (asset_class_from_cfi, resolve_isin,            # noqa: E402
                      resolve_metadata)


def _solr(docs):
    payload = json.dumps({"response": {"numFound": len(docs),
                                       "docs": docs}}).encode()

    class _Resp:
        def read(self):
            return payload
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    return mock.patch("urllib.request.urlopen", return_value=_Resp())


PREMIER_OIL = [
    # tombstones first (newest valid_from, no attributes) — real shape
    {"isin": "GB00B43G0577", "mic": "AQEA", "status": "CANC"},
    {"isin": "GB00B43G0577", "mic": "SGMY", "status": "TERM",
     "gnr_full_name": "PREMIER OIL", "gnr_cfi_code": "ESVUFR",
     "gnr_notional_curr_code": "GBP", "lei": "21380016E5VGE outdoors"},
]

ETF_ROW = [
    {"isin": "IE00BGSF1X88", "mic": "TPEE", "status": "UNCH",
     "gnr_full_name": "iShares USD Treasury Bond 0-1yr UCITS ETF",
     "gnr_cfi_code": "CEOGBS", "gnr_notional_curr_code": "USD"},
]


class TestCfiMapping(unittest.TestCase):
    def test_real_codes(self):
        self.assertEqual(asset_class_from_cfi("ESVUFR"), "STOCK")
        self.assertEqual(asset_class_from_cfi("CEOGBS"), "ETF")
        self.assertEqual(asset_class_from_cfi("CIOGFS"), "FUND")
        self.assertEqual(asset_class_from_cfi("DBFTFB"), "BOND")
        self.assertIsNone(asset_class_from_cfi(None))
        self.assertIsNone(asset_class_from_cfi("XXXXXX"))


class TestResolve(unittest.TestCase):
    def test_tombstones_filtered(self):
        with _solr(PREMIER_OIL):
            rows = resolve_isin("GB00B43G0577")
        self.assertEqual(len(rows), 1)                  # CANC tombstone gone
        self.assertEqual(rows[0]["gnr_full_name"], "PREMIER OIL")

    def test_delisted_instrument_resolves_from_term_row(self):
        with _solr(PREMIER_OIL):
            meta = resolve_metadata("GB00B43G0577")
        self.assertEqual(meta["name"], "PREMIER OIL")
        self.assertEqual(meta["asset_class"], "STOCK")
        self.assertEqual(meta["currency"], "GBP")
        self.assertEqual(meta["cfi"], "ESVUFR")
        self.assertIsNone(meta["ticker"])               # FIRDS has none

    def test_etf_classified_from_cfi(self):
        with _solr(ETF_ROW):
            meta = resolve_metadata("IE00BGSF1X88")
        self.assertEqual(meta["asset_class"], "ETF")
        self.assertEqual(meta["exch_code"], "TPEE")

    def test_unknown_isin_returns_none(self):
        with _solr([]):
            self.assertIsNone(resolve_metadata("NL0010661914"))

    def test_prefers_non_cancelled_row(self):
        docs = [
            {"isin": "X", "mic": "AAAA", "status": "CANC",
             "gnr_full_name": "Newer but cancelled",
             "gnr_cfi_code": "ESVUFR"},
            {"isin": "X", "mic": "BBBB", "status": "UNCH",
             "gnr_full_name": "Active row", "gnr_cfi_code": "ESVUFR"},
        ]
        with _solr(docs):
            meta = resolve_metadata("X")
        self.assertEqual(meta["name"], "Active row")


if __name__ == "__main__":
    unittest.main()
