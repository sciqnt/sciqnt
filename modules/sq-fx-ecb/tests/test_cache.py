"""Cache: TTL check, fetch-and-write, atomic writes."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-fx-ecb" / "src"))

from sq_fx_ecb.cache import (                       # noqa: E402
    cache_path, get_or_fetch, is_fresh,
)


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sq-fx-ecb-cache-"))

    def test_is_fresh_false_when_no_file(self):
        self.assertFalse(is_fresh(self.tmp / "missing.xml", ttl_seconds=3600))

    def test_get_or_fetch_writes_when_no_cache(self):
        calls = []
        def fetch(): calls.append(1); return b"<xml/>"
        data = get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        self.assertEqual(data, b"<xml/>")
        self.assertEqual(len(calls), 1)
        self.assertTrue(cache_path(self.tmp, "daily").is_file())

    def test_get_or_fetch_uses_cache_when_fresh(self):
        calls = []
        def fetch(): calls.append(1); return b"<xml/>"
        get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        # Only the first call fetched
        self.assertEqual(len(calls), 1)

    def test_get_or_fetch_refetches_when_stale(self):
        calls = []
        def fetch(): calls.append(1); return b"<xml/>"
        get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        # Backdate the cache file's mtime
        path = cache_path(self.tmp, "daily")
        old = time.time() - 7200       # 2h ago
        import os
        os.utime(path, (old, old))
        # Fetch again with 1h TTL — should re-fetch
        get_or_fetch(self.tmp, "daily", fetch, ttl_seconds=3600)
        self.assertEqual(len(calls), 2)

    def test_no_tmp_file_left_behind_after_successful_write(self):
        get_or_fetch(self.tmp, "daily", lambda: b"<xml/>", ttl_seconds=3600)
        tmps = list(self.tmp.glob("*.tmp"))
        self.assertEqual(tmps, [],
                         "atomic-write tmp file should be renamed away on success")


if __name__ == "__main__":
    unittest.main()
