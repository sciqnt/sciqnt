"""TiingoProvider — PriceProvider conformance, all HTTP mocked.

Pins:
  - the ticker dialect gate (US-style only; venue/index/FX refused locally)
  - symbols pass through VERBATIM (no mapping; BRK-B is already Tiingo's
    dialect, and a dotted ticker is a venue suffix → refused)
  - keyless construction is inert (None, never raises, never fetches)
  - happy path: latest close (asof=None) + PIT close (asof=date)
  - archive write-through and archive fallback
"""
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-tiingo" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_price_store import PriceStore                               # noqa: E402
from sq_schema import Price, PriceProvider                          # noqa: E402
from sq_tiingo import TiingoProvider                                # noqa: E402
from sq_tiingo.provider import _supported                           # noqa: E402

D = Decimal

CHART = {
    "series": {date(2024, 1, 2): D("100"), date(2024, 1, 3): D("101")},
    "dividends": {date(2024, 1, 3): D("0.25")},
    "splits": {},
    "currency": "USD",
    "exchange": None,
}


def _chart_fetch(calls=None):
    def fn(symbol, start, end, *, token):
        if calls is not None:
            calls.append((symbol, token))
        return CHART
    return fn


class TestTickerGate(unittest.TestCase):
    def test_us_symbols_pass(self):
        # class shares are dash-spelled in BOTH our canonical vocabulary
        # (Yahoo-style) and Tiingo's dialect — verbatim pass-through.
        for t in ("AAPL", "SPY", "BRK-B", "MSFT"):
            self.assertTrue(_supported(t), t)

    def test_venue_index_fx_refused(self):
        # a dot is ALWAYS a venue suffix in the canonical vocabulary
        for t in ("IB01.L", "ASML.AS", "4GLD.DE", "BRK.B", "^GSPC",
                  "EURUSD=X"):
            self.assertFalse(_supported(t), t)


class TestProvider(unittest.TestCase):
    def test_satisfies_protocol(self):
        self.assertIsInstance(TiingoProvider(token=""), PriceProvider)

    def test_keyless_is_inert(self):
        calls = []
        p = TiingoProvider(fetch_chart=_chart_fetch(calls), token="")
        self.assertIsNone(p.get_price("AAPL"))
        self.assertEqual(calls, [])                     # never even fetched

    def test_latest_and_pit_close(self):
        p = TiingoProvider(fetch_chart=_chart_fetch(), token="k")
        latest = p.get_price("AAPL")
        self.assertIsInstance(latest, Price)
        self.assertEqual(latest.last_price_local, D("101"))
        self.assertEqual(latest.currency, "USD")
        self.assertEqual(latest.source, "tiingo")
        pit = p.get_price("AAPL",
                          asof=datetime(2024, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(pit.last_price_local, D("100"))

    def test_unsupported_ticker_short_circuits(self):
        calls = []
        p = TiingoProvider(fetch_chart=_chart_fetch(calls), token="k")
        self.assertIsNone(p.get_price("IB01.L"))
        self.assertEqual(calls, [])

    def test_symbol_passed_verbatim(self):
        calls = []
        p = TiingoProvider(fetch_chart=_chart_fetch(calls), token="k")
        p.get_price("BRK-B")
        self.assertEqual(calls[0][0], "BRK-B")

    def test_error_returns_none(self):
        def boom(*a, **k):
            raise RuntimeError("auth")
        p = TiingoProvider(fetch_chart=boom, token="k")
        self.assertIsNone(p.get_price("AAPL"))


class TestAuthVisibility(unittest.TestCase):
    """A rejected key (401/403) prints ONE stderr line per process; plain
    network errors stay silent (the chain degrades quietly, as before)."""

    def setUp(self):
        from sq_tiingo import provider as _prov
        self._prov = _prov
        _prov._auth_warned = False                 # reset the process guard

    def _get(self, exc):
        import contextlib
        import io
        def boom(*a, **k):
            raise exc
        p = TiingoProvider(fetch_chart=boom, token="k")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = p.get_price("AAPL")
        return result, err.getvalue()

    def test_401_warns_once_on_stderr(self):
        import urllib.error
        exc = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        result, err = self._get(exc)
        self.assertIsNone(result)                  # still degrades to None
        self.assertIn("sq-tiingo: API key rejected (HTTP 401)", err)
        self.assertIn("sq-tiingo/api_token", err)
        # Second provider, same process: the guard suppresses a repeat.
        result2, err2 = self._get(exc)
        self.assertIsNone(result2)
        self.assertEqual(err2, "")

    def test_403_also_warns(self):
        import urllib.error
        exc = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        _, err = self._get(exc)
        self.assertIn("HTTP 403", err)

    def test_network_error_stays_silent(self):
        _, err = self._get(OSError("connection refused"))
        self.assertEqual(err, "")

    def test_http_500_stays_silent(self):
        import urllib.error
        exc = urllib.error.HTTPError("u", 500, "Server Error", {}, None)
        _, err = self._get(exc)
        self.assertEqual(err, "")


class TestArchive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PriceStore(root=Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_write_through(self):
        p = TiingoProvider(fetch_chart=_chart_fetch(), token="k",
                           store=self.store)
        p.get_price("AAPL")
        # archived under the CANONICAL ticker, source-attributed
        loaded = self.store.load_series("AAPL")
        self.assertEqual(loaded["series"][date(2024, 1, 3)], D("101"))
        self.assertEqual(self.store.load_events("AAPL", kind="div"),
                         {date(2024, 1, 3): D("0.25")})

    def test_archive_fallback_when_source_fails(self):
        self.store.record_series("AAPL", CHART["series"], currency="USD",
                                 source="tiingo")

        def boom(*a, **k):
            raise RuntimeError("down")
        p = TiingoProvider(fetch_chart=boom, token="k", store=self.store)
        px = p.get_price("AAPL")
        self.assertEqual(px.last_price_local, D("101"))
        self.assertEqual(px.source, "tiingo-archive")


if __name__ == "__main__":
    unittest.main()
