"""load_history memoization — pins the cache discipline.

Two properties matter:
  1. Repeated calls on the same data_dir return THE SAME list object
     (not just an equal copy). The TWR build relies on this — 50
     sample-date snapshots shouldn't re-parse the CSV 50 times.
  2. The cache invalidates when the CSV's mtime changes. We can't have
     stale data leak across runs that intentionally swap exports.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

import sq_degiro                                                  # noqa: E402


def _fixture_csv():
    """Path to the synthetic Degiro fixture set. Resolved RELATIVE TO THIS TEST
    so it works both in the monorepo and in the standalone sq-degiro repo."""
    return Path(__file__).resolve().parent / "fixtures"


def _set_up_fixture(tmpdir: Path):
    """Copy the bundled fixture CSVs into `tmpdir` so we can mutate them
    without affecting other tests."""
    src = _fixture_csv()
    shutil.copy(src / "transactions.csv", tmpdir / "transactions.csv")
    # Build a minimal account.csv with just a header
    (tmpdir / "account.csv").write_text(
        "Date,Time,Currency,Description,FX,Change,,Balance,Order ID,"
        "ID isin,Reference\n",
        encoding="utf-8-sig",
    )


class TestLoadHistoryMemoization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        _set_up_fixture(self.dir)
        # Clear any module-level cache from prior tests
        sq_degiro._HISTORY_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()
        sq_degiro._HISTORY_CACHE.clear()

    def test_same_dir_returns_same_object(self):
        a = sq_degiro.load_history(self.dir)
        b = sq_degiro.load_history(self.dir)
        self.assertIs(a, b,
                      "Repeated load_history calls on the same data_dir "
                      "must return the SAME list object — else the TWR "
                      "build re-parses the CSV 50× per run.")

    def test_mtime_change_invalidates(self):
        a = sq_degiro.load_history(self.dir)
        # Touch the file to bump mtime (atomically — write same content)
        time.sleep(0.01)
        tx = self.dir / "transactions.csv"
        content = tx.read_bytes()
        tx.write_bytes(content)
        # Force a different mtime even on filesystems with low resolution
        future = time.time() + 60
        os.utime(tx, (future, future))
        b = sq_degiro.load_history(self.dir)
        self.assertIsNot(a, b,
                         "When the CSV mtime changes, the memoized result "
                         "must be invalidated — else the user can swap "
                         "their export and silently see yesterday's data.")

    def test_missing_dir_returns_none_uncached(self):
        # data_dir without CSVs → None; subsequent call after CSV
        # appears must succeed (no stuck None cached).
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        self.assertIsNone(sq_degiro.load_history(empty))
        # Now add CSVs and try again
        _set_up_fixture(empty)
        self.assertIsNotNone(sq_degiro.load_history(empty))


if __name__ == "__main__":
    unittest.main()
