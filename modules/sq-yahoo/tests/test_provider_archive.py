"""YahooProvider ↔ sq_price_store integration — all HTTP mocked.

Pins the archive contract:
  - a successful chart fetch writes prices AND div/split events through
  - a failed live fetch falls back to the archived series
    (source "yahoo-archive"), so the portfolio renders offline
  - a spot quote records today's raw observation
  - archive write failures never break pricing (best-effort)
  - no store wired → zero archive behaviour (bare library use)
"""
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-yahoo" / "src"))
sys.path.insert(0, str(ROOT / "core"))

try:                                                               # noqa: E402
    from sq_price_store import PriceStore                           # noqa: E402
    _HAVE_STORE = True
except ImportError:                       # optional archive integration (a leaf lib)
    _HAVE_STORE = False
from sq_yahoo import YahooProvider                                  # noqa: E402

D = Decimal
ASOF = datetime(2024, 1, 4, tzinfo=timezone.utc)

CHART = {
    "series": {date(2024, 1, 2): D("100"), date(2024, 1, 3): D("101")},
    "dividends": {date(2024, 1, 3): D("0.5")},
    "splits": {date(2023, 6, 1): D("3")},
    "currency": "USD",
    "exchange": "NASDAQ",
}


@unittest.skipUnless(_HAVE_STORE, "sq-price-store not installed (optional archive integration)")
class TestArchiveWriteThrough(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PriceStore(root=Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_chart_fetch_records_prices_and_events(self):
        p = YahooProvider(fetch_chart=lambda t, s, e: CHART,
                          store=self.store)
        px = p.get_price("AAPL", asof=ASOF)
        self.assertEqual(px.last_price_local, D("101"))
        self.assertEqual(px.source, "yahoo")
        loaded = self.store.load_series("AAPL")
        self.assertEqual(loaded["series"][date(2024, 1, 2)], D("100"))
        self.assertEqual(self.store.load_events("AAPL", kind="div"),
                         {date(2024, 1, 3): D("0.5")})
        self.assertEqual(self.store.load_events("AAPL", kind="split"),
                         {date(2023, 6, 1): D("3")})

    def test_live_failure_serves_archive(self):
        # Pre-populate the archive, then break the network entirely.
        self.store.record_series("AAPL", CHART["series"],
                                 currency="USD", source="yahoo")

        def boom(*a, **k):
            raise RuntimeError("yahoo is down")
        p = YahooProvider(fetch_chart=boom, fetch_historical=boom,
                          store=self.store)
        px = p.get_price("AAPL", asof=ASOF)
        self.assertEqual(px.last_price_local, D("101"))
        self.assertEqual(px.source, "yahoo-archive")

    def test_stale_archive_not_served_as_current(self):
        # The archive ends LONG ago; asking for today must NOT silently
        # serve a months-old close as current. valid_until = last archived
        # close + 7 days grace — beyond it the provider returns None and
        # the caller degrades visibly.
        self.store.record_series("AAPL", {date(2023, 1, 3): D("90")},
                                 currency="USD", source="yahoo")

        def boom(*a, **k):
            raise RuntimeError("yahoo is down")
        p = YahooProvider(fetch_chart=boom, fetch_historical=boom,
                          store=self.store)
        self.assertIsNone(p.get_price("AAPL",
                                      asof=datetime.now(timezone.utc)))

    def test_stale_archive_gives_per_date_fallback_its_shot(self):
        # When the archive is too stale for the target, the per-date
        # fallback must still get its one attempt (not be pre-empted by
        # a stale archive serve).
        self.store.record_series("AAPL", {date(2023, 1, 3): D("90")},
                                 currency="USD", source="yahoo")

        def boom(*a, **k):
            raise RuntimeError("yahoo is down")

        def fallback(ticker, asof):
            return {"price": D("123"), "currency": "USD"}
        p = YahooProvider(fetch_chart=boom, fetch_historical=fallback,
                          store=self.store)
        px = p.get_price("AAPL", asof=datetime.now(timezone.utc))
        self.assertEqual(px.last_price_local, D("123"))

    def test_archive_preserves_raw_pence_for_normalisation(self):
        # Archived GBp prices must come back normalised by the PROVIDER
        # (pence → pounds), proving raw-at-rest / normalise-at-read.
        self.store.record_series("IB01.L", {date(2024, 1, 3): D("12054")},
                                 currency="GBp", source="yahoo")

        def boom(*a, **k):
            raise RuntimeError("down")
        p = YahooProvider(fetch_chart=boom, fetch_historical=boom,
                          store=self.store)
        px = p.get_price("IB01.L", asof=ASOF)
        self.assertEqual(px.last_price_local, D("120.54"))
        self.assertEqual(px.currency, "GBP")

    def test_spot_quote_recorded_raw(self):
        def fake_quote(ticker):
            return {"price": D("199.5"), "currency": "USD"}
        p = YahooProvider(fetch=fake_quote, store=self.store)
        p.get_price("AAPL")
        loaded = self.store.load_series("AAPL")
        today = datetime.now(timezone.utc).date()
        self.assertEqual(loaded["series"][today], D("199.5"))

    def test_broken_store_never_breaks_pricing(self):
        class _BrokenStore:
            def record_series(self, *a, **k):
                raise OSError("disk full")
            def record_events(self, *a, **k):
                raise OSError("disk full")
            def load_series(self, *a, **k):
                raise OSError("disk full")
        p = YahooProvider(fetch_chart=lambda t, s, e: CHART,
                          store=_BrokenStore())
        px = p.get_price("AAPL", asof=ASOF)
        self.assertEqual(px.last_price_local, D("101"))   # pricing unharmed

    def test_no_store_no_archive(self):
        p = YahooProvider(fetch_chart=lambda t, s, e: CHART)
        px = p.get_price("AAPL", asof=ASOF)
        self.assertEqual(px.last_price_local, D("101"))
        self.assertIsNone(self.store.load_series("AAPL"))   # untouched


if __name__ == "__main__":
    unittest.main()
