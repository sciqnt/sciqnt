"""RssNewsProvider — NewsProvider conformance, all HTTP mocked.

Pins:
  - raw dicts → canonical NewsItem (publish time as valid_at; fetch-time
    fallback when the feed omits pubDate)
  - per-ticker process cache (one fetch per ticker)
  - failure → [] and negative-cached (never raises, never re-hits)
  - RSS parsing of a real-shaped feed fixture (feed.fetch_headlines)
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-news-rss" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import NewsItem, NewsProvider                        # noqa: E402
from sq_news_rss import RssNewsProvider                             # noqa: E402
from sq_news_rss.feed import fetch_headlines                        # noqa: E402

PUBLISHED = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)

RSS_FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Yahoo! Finance: AAPL News</title>
  <item>
    <title>Apple ships a thing</title>
    <link>https://example.com/a</link>
    <description>A thing was shipped.</description>
    <pubDate>Wed, 10 Jun 2026 09:00:00 +0000</pubDate>
  </item>
  <item>
    <title>Older story</title>
    <link>https://example.com/b</link>
    <pubDate>Tue, 09 Jun 2026 09:00:00 +0000</pubDate>
  </item>
  <item><title></title></item>
</channel></rss>"""


class TestFeedParsing(unittest.TestCase):
    def test_parses_real_shaped_feed(self):
        class _Resp:
            def read(self):
                return RSS_FIXTURE
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            items = fetch_headlines("AAPL", limit=5)
        self.assertEqual(len(items), 2)                  # empty title skipped
        self.assertEqual(items[0]["headline"], "Apple ships a thing")
        self.assertEqual(items[0]["published_at"], PUBLISHED)
        self.assertEqual(items[0]["url"], "https://example.com/a")
        # newest first
        self.assertGreater(items[0]["published_at"], items[1]["published_at"])


class TestRssNewsProvider(unittest.TestCase):
    def test_satisfies_protocol(self):
        self.assertIsInstance(RssNewsProvider(fetch=lambda t, limit: []),
                              NewsProvider)

    def test_converts_to_news_items(self):
        def fake(ticker, *, limit):
            return [{"headline": "H", "url": "u", "summary": "s",
                     "published_at": PUBLISHED}]
        items = RssNewsProvider(fetch=fake).get_news("AAPL")
        self.assertIsInstance(items[0], NewsItem)
        self.assertEqual(items[0].valid_at, PUBLISHED)
        self.assertEqual(items[0].ticker, "AAPL")
        self.assertEqual(items[0].source, "yahoo-rss")

    def test_missing_pubdate_falls_back_to_fetch_time(self):
        def fake(ticker, *, limit):
            return [{"headline": "H", "url": None, "summary": None,
                     "published_at": None}]
        items = RssNewsProvider(fetch=fake).get_news("X")
        self.assertIsNotNone(items[0].valid_at)

    def test_caches_per_ticker(self):
        calls = []
        def fake(ticker, *, limit):
            calls.append(ticker)
            return []
        p = RssNewsProvider(fetch=fake)
        p.get_news("AAPL")
        p.get_news("AAPL")
        self.assertEqual(calls, ["AAPL"])

    def test_failure_returns_empty_and_negative_caches(self):
        calls = []
        def boom(ticker, *, limit):
            calls.append(ticker)
            raise RuntimeError("down")
        p = RssNewsProvider(fetch=boom)
        self.assertEqual(p.get_news("AAPL"), [])
        self.assertEqual(p.get_news("AAPL"), [])
        self.assertEqual(calls, ["AAPL"])                # one attempt only

    def test_limit_respected(self):
        def fake(ticker, *, limit):
            return [{"headline": f"H{i}", "url": f"u{i}", "summary": None,
                     "published_at": PUBLISHED} for i in range(10)]
        items = RssNewsProvider(fetch=fake).get_news("AAPL", limit=3)
        self.assertEqual(len(items), 3)


if __name__ == "__main__":
    unittest.main()
