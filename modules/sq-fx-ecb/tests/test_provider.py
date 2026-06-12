"""ECBProvider — `FxRateProvider` conformance, with all HTTP mocked.

These tests pin:
  - identity (same-ccy) short-circuit
  - EUR-to-X direct lookup
  - X-to-EUR inversion (1/rate)
  - X-to-Y triangulation via EUR
  - unknown currency returns None (never raises)
  - asof picks the closest published date ≤ asof
"""
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-fx-ecb" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_fx_ecb import ECBProvider, ECB_DAILY_URL, ECB_HIST_90D_URL   # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
_DAILY = (FIXTURES / "ecb_daily.xml").read_bytes()
_HIST  = (FIXTURES / "ecb_hist90d.xml").read_bytes()


def _fake_fetch(url):
    """Pretend to fetch ECB's URLs; serve from fixtures instead.
    The full-history URL falls back to the same 90d fixture so tests
    don't need a separate large file — content-equivalent for the
    coverage range our tests assert against."""
    from sq_fx_ecb import ECB_HIST_FULL_URL
    if url == ECB_DAILY_URL:
        return _DAILY
    if url in (ECB_HIST_90D_URL, ECB_HIST_FULL_URL):
        return _HIST
    raise AssertionError(f"unexpected URL fetched: {url}")


class TestECBProvider(unittest.TestCase):
    def setUp(self):
        # Per-test tmpdir so cache writes never leak across tests
        self.tmp = tempfile.mkdtemp(prefix="sq-fx-ecb-test-")
        self.provider = ECBProvider(cache_dir=Path(self.tmp), fetch=_fake_fetch)

    # ── identity short-circuit ─────────────────────────────────────────
    def test_same_currency_returns_rate_one(self):
        r = self.provider.get_rate("EUR", "EUR")
        self.assertIsNotNone(r)
        self.assertEqual(r.rate, Decimal("1"))
        self.assertEqual(r.source, "ecb")

    # ── EUR -> X (direct lookup) ───────────────────────────────────────
    def test_eur_to_usd_direct(self):
        r = self.provider.get_rate("EUR", "USD")
        self.assertEqual(r.rate, Decimal("1.1652"))
        self.assertEqual(r.from_currency, "EUR")
        self.assertEqual(r.to_currency,   "USD")
        self.assertEqual(r.source,        "ecb")

    # ── X -> EUR (invert) ──────────────────────────────────────────────
    def test_usd_to_eur_inverted(self):
        r = self.provider.get_rate("USD", "EUR")
        # 1 USD = 1 / 1.1652 EUR ≈ 0.85822...
        self.assertAlmostEqual(float(r.rate), 1 / 1.1652, places=10)

    # ── X -> Y (triangulate via EUR) ───────────────────────────────────
    def test_usd_to_gbp_triangulated(self):
        r = self.provider.get_rate("USD", "GBP")
        # 1 USD = (1/USD_rate) EUR * GBP_rate GBP = 0.8425 / 1.1652
        expected = Decimal("0.8425") / Decimal("1.1652")
        self.assertEqual(r.rate, expected)

    # ── unknown currency ───────────────────────────────────────────────
    def test_unknown_currency_returns_none(self):
        self.assertIsNone(self.provider.get_rate("EUR", "ZZZ"))
        self.assertIsNone(self.provider.get_rate("ZZZ", "USD"))

    # ── asof history lookup ────────────────────────────────────────────
    def test_asof_picks_exact_date(self):
        r = self.provider.get_rate("EUR", "USD", asof=date(2026, 5, 29))
        self.assertEqual(r.rate, Decimal("1.1700"))

    def test_asof_picks_latest_available_on_or_before(self):
        """ECB skips weekends/holidays — asof on a skipped day should fall
        back to the most recent published date ≤ asof."""
        # May 20 not in fixture; latest ≤ is May 15
        r = self.provider.get_rate("EUR", "USD", asof=date(2026, 5, 20))
        self.assertEqual(r.rate, Decimal("1.0950"))

    def test_asof_before_history_window_returns_none(self):
        r = self.provider.get_rate("EUR", "USD", asof=date(2020, 1, 1))
        self.assertIsNone(r)

    # ── cache reuse ────────────────────────────────────────────────────
    def test_subsequent_calls_use_cache_not_fetch(self):
        """After the first fetch, the cache should be hit and the fetcher
        should not be called again."""
        call_count = {"n": 0}
        def counting_fetch(url):
            call_count["n"] += 1
            return _fake_fetch(url)
        p = ECBProvider(cache_dir=Path(self.tmp), fetch=counting_fetch)
        p.get_rate("EUR", "USD")
        p.get_rate("EUR", "USD")
        p.get_rate("EUR", "USD")
        # Daily URL fetched exactly once across three calls
        self.assertEqual(call_count["n"], 1)


if __name__ == "__main__":
    unittest.main()
