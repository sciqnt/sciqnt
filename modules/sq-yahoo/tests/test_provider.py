"""YahooProvider — `PriceProvider` conformance with all HTTP mocked.

Pins:
  - happy path: fetch_quote dict → canonical Price
  - error path: any exception → None (never raises)
  - missing price: None
  - currency normalisation: lowercase from source becomes uppercase
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-yahoo" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import Price, PriceProvider                          # noqa: E402
from sq_yahoo import YahooProvider                                  # noqa: E402


class TestYahooProvider(unittest.TestCase):
    def test_satisfies_price_provider_protocol(self):
        self.assertIsInstance(YahooProvider(), PriceProvider)

    def test_happy_path_returns_price(self):
        def fake(ticker):
            return {"ticker": "IB01.L", "price": Decimal("120.54"),
                    "currency": "USD", "exchange": "NASDAQ"}
        p = YahooProvider(fetch=fake).get_price("IB01.L")
        self.assertIsInstance(p, Price)
        self.assertEqual(p.last_price_local, Decimal("120.54"))
        self.assertEqual(p.currency, "USD")
        self.assertEqual(p.source, "yahoo")

    def test_currency_uppercased(self):
        def fake(ticker):
            return {"price": Decimal("1"), "currency": "usd"}
        p = YahooProvider(fetch=fake).get_price("X")
        self.assertEqual(p.currency, "USD")

    def test_currency_defaults_to_usd_when_missing(self):
        def fake(ticker):
            return {"price": Decimal("1")}
        p = YahooProvider(fetch=fake).get_price("X")
        self.assertEqual(p.currency, "USD")

    def test_returns_none_on_exception(self):
        def fake(ticker):
            raise RuntimeError("network")
        self.assertIsNone(YahooProvider(fetch=fake).get_price("X"))

    def test_returns_none_when_price_missing(self):
        def fake(ticker):
            return {}
        self.assertIsNone(YahooProvider(fetch=fake).get_price("X"))


class TestYahooProviderHistorical(unittest.TestCase):
    def test_asof_uses_series_cache_when_available(self):
        """When `fetch_series` returns a populated dict, that's the
        cached series — historical lookups use it; fetch_historical is
        NOT consulted (it's the fallback path)."""
        from datetime import date, datetime, timezone
        observed = []

        def fake_series(ticker, start, end):
            observed.append(("series", ticker, start, end))
            return {date(2022, 12, 29): Decimal("128.00"),
                    date(2022, 12, 30): Decimal("129.93")}

        def fake_history(ticker, target_date):
            raise AssertionError("must not be called when series-cache hits")

        def fake_quote(ticker):
            return {"price": Decimal("999"), "currency": "USD",
                    "exchange": "NASDAQ"}

        prov = YahooProvider(fetch=fake_quote, fetch_historical=fake_history,
                             fetch_series=fake_series)
        asof = datetime(2022, 12, 31, tzinfo=timezone.utc)
        p = prov.get_price("AAPL", asof=asof)
        self.assertEqual(p.last_price_local, Decimal("129.93"))
        self.assertEqual(p.currency, "USD")
        # Walked back to the latest session ≤ asof
        self.assertEqual(p.valid_at.date().isoformat(), "2022-12-30")
        # Only ONE series fetch — repeated asof lookups must reuse it
        prov.get_price("AAPL", asof=datetime(2022, 12, 29, tzinfo=timezone.utc))
        self.assertEqual(
            sum(1 for o in observed if o[0] == "series"), 1,
            "the per-ticker series must be fetched ONCE per session — "
            "if this regresses, every cash-event sample is a fresh HTTP call",
        )

    def test_asof_falls_back_to_fetch_historical_when_series_fails(self):
        from datetime import datetime, timezone

        def fake_series(t, s, e):
            raise RuntimeError("transport down")

        def fake_history(ticker, target_date):
            return {"ticker": ticker, "price": Decimal("42.00"),
                    "currency": "USD", "exchange": "NYSE",
                    "valid_at": datetime(2022, 12, 30, 14, 30,
                                         tzinfo=timezone.utc)}

        prov = YahooProvider(fetch=lambda t: {"price": Decimal("0")},
                             fetch_historical=fake_history,
                             fetch_series=fake_series)
        p = prov.get_price("X", asof=datetime(2022, 12, 31, tzinfo=timezone.utc))
        self.assertEqual(p.last_price_local, Decimal("42.00"))

    def test_get_price_without_asof_uses_fetch_quote(self):
        called = []

        def fake_quote(ticker):
            called.append(ticker)
            return {"price": Decimal("123"), "currency": "EUR"}

        def fake_history(ticker, d):
            raise AssertionError("must not be called when asof is None")

        def fake_series(t, s, e):
            raise AssertionError("must not be called when asof is None")

        prov = YahooProvider(fetch=fake_quote, fetch_historical=fake_history,
                             fetch_series=fake_series)
        p = prov.get_price("X")
        self.assertEqual(called, ["X"])
        self.assertEqual(p.last_price_local, Decimal("123"))

    def test_historical_error_returns_none(self):
        def fake_history(t, d):
            raise ValueError("no data")
        def fake_series(t, s, e):
            raise ValueError("no series either")
        from datetime import datetime, timezone
        prov = YahooProvider(fetch=lambda t: {}, fetch_historical=fake_history,
                             fetch_series=fake_series)
        self.assertIsNone(prov.get_price("X", asof=datetime(2022, 1, 1,
                                                            tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()


class TestPenceNormalization(unittest.TestCase):
    """LSE quotes arrive in PENCE with currency 'GBp' — treating pence as
    pounds silently overvalues 100× (turned a £10k position into £1m in a
    year-end MTM). Normalization must run BEFORE any .upper()."""

    def test_gbp_pence_divided(self):
        from sq_yahoo.provider import _normalize_quote
        from decimal import Decimal
        self.assertEqual(_normalize_quote(Decimal("1250"), "GBp"),
                         (Decimal("12.5"), "GBP"))
        self.assertEqual(_normalize_quote(Decimal("1250"), "GBX"),
                         (Decimal("12.5"), "GBP"))
        self.assertEqual(_normalize_quote(Decimal("12.5"), "GBP"),
                         (Decimal("12.5"), "GBP"))      # pounds untouched
        self.assertEqual(_normalize_quote(Decimal("5"), "usd"),
                         (Decimal("5"), "USD"))

    def test_provider_normalizes_live_quote(self):
        from sq_yahoo.provider import YahooProvider
        from decimal import Decimal
        p = YahooProvider(fetch=lambda t: {"price": Decimal("1250"),
                                           "currency": "GBp"})
        q = p.get_price("VOD.L")
        self.assertEqual(q.last_price_local, Decimal("12.5"))
        self.assertEqual(q.currency, "GBP")
