"""sq_degiro.history_sync — refresh-from-API plumbing, no network.

Injects a fake `fetch` that serves the repo's own synthetic CSV fixtures, and
verifies: validated write + .bak of the previous files, the refusal path
(fewer transactions than current → existing files untouched), and the
max_age_hours skip gate (the platform's bounded auto-sync).
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE.parent / "src"))

from sq_degiro.history_sync import sync_history, REPORTS          # noqa: E402

FIX = HERE / "fixtures"
TX = (FIX / "transactions.csv").read_bytes()
AC = (FIX / "account.csv").read_bytes()


def _fake_fetch(tx=TX, ac=AC):
    def get(url):
        return tx if "transactionReport" in url else ac
    return get


class TestSyncHistory(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sq-degiro-sync-test-"))

    def test_fresh_sync_writes_and_validates(self):
        res = sync_history(data_dir=self.dir, fetch=_fake_fetch())
        self.assertEqual(res["dir"], str(self.dir))
        self.assertGreater(res["transactions"], 0)
        for fname in REPORTS:
            self.assertTrue((self.dir / fname).is_file())

    def test_resync_keeps_bak(self):
        sync_history(data_dir=self.dir, fetch=_fake_fetch())
        time.sleep(0.01)
        sync_history(data_dir=self.dir, fetch=_fake_fetch())
        self.assertTrue((self.dir / "transactions.csv.bak").is_file())
        self.assertTrue((self.dir / "account.csv.bak").is_file())

    def test_refuses_shrunk_history(self):
        sync_history(data_dir=self.dir, fetch=_fake_fetch())
        before = (self.dir / "transactions.csv").read_bytes()
        # a "new" download with only the header row → fewer txns → refuse
        header = TX.split(b"\n", 1)[0] + b"\n"
        with self.assertRaises(RuntimeError):
            sync_history(data_dir=self.dir, fetch=_fake_fetch(tx=header))
        self.assertEqual((self.dir / "transactions.csv").read_bytes(), before)

    def test_empty_download_never_overwrites(self):
        with self.assertRaises(RuntimeError):
            sync_history(data_dir=self.dir, fetch=_fake_fetch(tx=b"", ac=b""))
        self.assertFalse((self.dir / "transactions.csv").exists())

    def test_max_age_gate_skips_fresh_files(self):
        sync_history(data_dir=self.dir, fetch=_fake_fetch())
        res = sync_history(data_dir=self.dir, fetch=_fake_fetch(),
                           max_age_hours=6)
        self.assertTrue(res.get("skipped"))


if __name__ == "__main__":
    unittest.main()
