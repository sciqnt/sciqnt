"""FinnhubNewsProvider — NewsProvider conformance, all HTTP mocked.

Pins: keyless inertness, dict→NewsItem conversion (unix ts → valid_at,
fetch-time fallback), per-ticker cache, failure → [] + negative cache.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-finnhub" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import NewsItem, NewsProvider                        # noqa: E402
from sq_finnhub import FinnhubNewsProvider                          # noqa: E402

PUBLISHED = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)


def _fake(items, calls=None):
    def fn(ticker, *, token, days=7):
        if calls is not None:
            calls.append((ticker, token))
        return items
    return fn


class TestFinnhubNewsProvider(unittest.TestCase):
    def test_satisfies_protocol(self):
        self.assertIsInstance(FinnhubNewsProvider(token=""), NewsProvider)

    def test_keyless_is_inert(self):
        calls = []
        p = FinnhubNewsProvider(fetch=_fake([], calls), token="")
        self.assertEqual(p.get_news("AAPL"), [])
        self.assertEqual(calls, [])                  # never fetched

    def test_converts_to_news_items(self):
        items = [{"headline": "H", "url": "u", "summary": "s",
                  "published_at": PUBLISHED}]
        p = FinnhubNewsProvider(fetch=_fake(items), token="k")
        out = p.get_news("AAPL")
        self.assertIsInstance(out[0], NewsItem)
        self.assertEqual(out[0].valid_at, PUBLISHED)
        self.assertEqual(out[0].source, "finnhub")

    def test_missing_published_falls_back(self):
        items = [{"headline": "H", "url": None, "summary": None,
                  "published_at": None}]
        out = FinnhubNewsProvider(fetch=_fake(items), token="k").get_news("X")
        self.assertIsNotNone(out[0].valid_at)

    def test_caches_and_negative_caches(self):
        calls = []
        p = FinnhubNewsProvider(fetch=_fake([], calls), token="k")
        p.get_news("AAPL")
        p.get_news("AAPL")
        self.assertEqual(len(calls), 1)              # cached empty list

        boom_calls = []
        def boom(ticker, *, token, days=7):
            boom_calls.append(ticker)
            raise RuntimeError("down")
        p2 = FinnhubNewsProvider(fetch=boom, token="k")
        self.assertEqual(p2.get_news("NVDA"), [])
        self.assertEqual(p2.get_news("NVDA"), [])
        self.assertEqual(boom_calls, ["NVDA"])       # one attempt only


class TestAuthVisibility(unittest.TestCase):
    """A rejected key (401/403) prints ONE stderr line per process; plain
    network errors stay silent (the chain degrades quietly, as before)."""

    def setUp(self):
        from sq_finnhub import provider as _prov
        self._prov = _prov
        _prov._auth_warned = False                 # reset the process guard

    def _get(self, exc):
        import contextlib
        import io
        def boom(ticker, *, token, days=7):
            raise exc
        p = FinnhubNewsProvider(fetch=boom, token="k")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            result = p.get_news("AAPL")
        return result, err.getvalue()

    def test_401_warns_once_on_stderr(self):
        import urllib.error
        exc = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        result, err = self._get(exc)
        self.assertEqual(result, [])               # still degrades to []
        self.assertIn("sq-finnhub: API key rejected (HTTP 401)", err)
        self.assertIn("sq-finnhub/api_token", err)
        # Second provider, same process: the guard suppresses a repeat.
        result2, err2 = self._get(exc)
        self.assertEqual(result2, [])
        self.assertEqual(err2, "")

    def test_403_also_warns(self):
        import urllib.error
        exc = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        _, err = self._get(exc)
        self.assertIn("HTTP 403", err)

    def test_network_error_stays_silent(self):
        _, err = self._get(OSError("connection refused"))
        self.assertEqual(err, "")


if __name__ == "__main__":
    unittest.main()
