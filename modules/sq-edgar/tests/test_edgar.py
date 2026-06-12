"""sq-edgar — parsing + tag-fallback logic, all HTTP mocked.

Pins:
  - ticker→CIK from the SEC map shape
  - filings list: form filter, limit, Archives URL construction
  - fundamentals: us-gaap tag fallback chains, latest-FY pick (10-K/FY
    only, newest end date wins), missing tag → None never a guess
  - the User-Agent carries an email-shaped contact (SEC 403s otherwise)
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-edgar" / "src"))

import sq_edgar.edgar as edgar                                       # noqa: E402

TICKER_MAP = {"0": {"cik_str": 320193, "ticker": "AAPL",
                    "title": "Apple Inc."},
              "1": {"cik_str": 1045810, "ticker": "NVDA",
                    "title": "NVIDIA CORP"}}

SUBMISSIONS = {"name": "Apple Inc.", "filings": {"recent": {
    "form":             ["4", "8-K", "10-Q", "4"],
    "filingDate":       ["2026-05-29", "2026-04-30", "2026-05-01",
                         "2026-05-12"],
    "accessionNumber":  ["0001-26-001", "0001-26-002", "0001-26-003",
                         "0001-26-004"],
    "primaryDocument":  ["a.xml", "b.htm", "c.htm", "d.xml"],
    "primaryDocDescription": ["FORM 4", "8-K", "10-Q", "FORM 4"],
}}}

FACTS = {"entityName": "Apple Inc.", "facts": {"us-gaap": {
    # primary revenue tag ABSENT → fallback "Revenues" must be used
    "Revenues": {"units": {"USD": [
        {"form": "10-K", "fp": "FY", "end": "2024-09-28", "val": 1000},
        {"form": "10-K", "fp": "FY", "end": "2025-09-27", "val": 2000},
        {"form": "10-Q", "fp": "Q1", "end": "2025-12-27", "val": 999},
    ]}},
    "NetIncomeLoss": {"units": {"USD": [
        {"form": "10-K", "fp": "FY", "end": "2025-09-27", "val": 500},
    ]}},
    "EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"form": "10-K", "fp": "FY", "end": "2025-09-27", "val": 7.46},
    ]}},
}}}


def _mock_get(payloads):
    def fake(url, cache_key, ttl):
        for fragment, payload in payloads.items():
            if fragment in url:
                return payload
        raise AssertionError(f"unexpected URL {url}")
    return mock.patch.object(edgar, "_get_json", side_effect=fake)


class TestResolveCik(unittest.TestCase):
    def test_resolves_case_insensitively(self):
        with _mock_get({"company_tickers": TICKER_MAP}):
            self.assertEqual(edgar.resolve_cik("aapl"), 320193)
            self.assertIsNone(edgar.resolve_cik("IB01"))   # not registered


class TestRecentFilings(unittest.TestCase):
    def test_filters_and_builds_urls(self):
        with _mock_get({"company_tickers": TICKER_MAP,
                        "submissions": SUBMISSIONS}):
            out = edgar.recent_filings("AAPL", forms={"4"}, limit=10)
        self.assertEqual([f["form"] for f in out], ["4", "4"])
        self.assertEqual(out[0]["url"],
                         "https://www.sec.gov/Archives/edgar/data/320193/"
                         "000126001/a.xml")

    def test_limit(self):
        with _mock_get({"company_tickers": TICKER_MAP,
                        "submissions": SUBMISSIONS}):
            out = edgar.recent_filings("AAPL", limit=2)
        self.assertEqual(len(out), 2)

    def test_unregistered_ticker_returns_empty(self):
        with _mock_get({"company_tickers": TICKER_MAP}):
            self.assertEqual(edgar.recent_filings("IB01"), [])


class TestFundamentalsLite(unittest.TestCase):
    def test_fallback_chain_and_latest_fy(self):
        with _mock_get({"company_tickers": TICKER_MAP,
                        "companyfacts": FACTS}):
            f = edgar.fundamentals_lite("AAPL")
        self.assertEqual(f["entity"], "Apple Inc.")
        self.assertEqual(f["revenue"], Decimal("2000"))    # newest FY, not Q
        self.assertEqual(f["net_income"], Decimal("500"))
        self.assertEqual(f["eps_diluted"], Decimal("7.46"))
        self.assertIsNone(f["total_assets"])               # tag absent → None
        self.assertEqual(f["fiscal_year_end"], "2025-09-27")

    def test_unregistered_returns_none(self):
        with _mock_get({"company_tickers": TICKER_MAP}):
            self.assertIsNone(edgar.fundamentals_lite("IB01"))


class TestUserAgent(unittest.TestCase):
    def test_contains_email_shaped_contact(self):
        # SEC 403s prose-only UAs (live-verified) — the default must
        # carry an @-token even when SQ_EDGAR_CONTACT is unset.
        import os
        old = os.environ.pop("SQ_EDGAR_CONTACT", None)
        try:
            self.assertIn("@", edgar._ua())
        finally:
            if old is not None:
                os.environ["SQ_EDGAR_CONTACT"] = old


if __name__ == "__main__":
    unittest.main()
