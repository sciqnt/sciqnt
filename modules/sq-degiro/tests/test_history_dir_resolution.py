"""Per-account CSV directory resolution (`_resolve_history_dir`).

Canonical layout is per-account (`data/degiro/<account>/`). A named account
whose subdir has no CSVs falls back to the flat `data/degiro/` ONLY when it is
the sole connected account — so one account can never inherit another's
history. These tests pin every branch with a tmp data root + a mocked
`accounts()` roster (no keychain / real data dir touched).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

import sq_degiro                                              # noqa: E402
from sq_degiro import _resolve_history_dir                    # noqa: E402


def _touch_csvs(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    (d / "transactions.csv").write_text("hdr\n")
    (d / "account.csv").write_text("hdr\n")


class TestResolveHistoryDir(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="sq-degiro-hist-")) / "degiro"
        self.base.mkdir(parents=True)

    def test_legacy_none_account_uses_flat(self):
        self.assertEqual(_resolve_history_dir(None, base=self.base), self.base)

    def test_named_account_with_own_subdir_uses_subdir(self):
        _touch_csvs(self.base / "AccountA")
        # Even if flat CSVs also exist, the account's own subdir wins.
        _touch_csvs(self.base)
        self.assertEqual(
            _resolve_history_dir("AccountA", base=self.base),
            self.base / "AccountA",
        )

    def test_sole_named_account_falls_back_to_flat(self):
        _touch_csvs(self.base)                       # only flat CSVs exist
        with mock.patch.object(sq_degiro, "accounts", return_value=["AccountA"]):
            self.assertEqual(
                _resolve_history_dir("AccountA", base=self.base),
                self.base,
            )

    def test_multi_account_does_not_fall_back(self):
        _touch_csvs(self.base)                       # only flat CSVs exist
        with mock.patch.object(
            sq_degiro, "accounts",
            return_value=["AccountA", "AccountB"],
        ):
            # No fallback: returns the (empty) per-account subdir, so the
            # caller sees "no history" rather than double-counting flat CSVs.
            self.assertEqual(
                _resolve_history_dir("AccountA", base=self.base),
                self.base / "AccountA",
            )

    def test_legacy_plus_named_account_no_fallback(self):
        # A legacy bare-creds account (None) co-existing with a named one
        # means the flat dir is already the legacy account's — don't let the
        # named account claim it too.
        _touch_csvs(self.base)
        with mock.patch.object(
            sq_degiro, "accounts", return_value=[None, "AccountA"]):
            self.assertEqual(
                _resolve_history_dir("AccountA", base=self.base),
                self.base / "AccountA",
            )

    def test_no_csvs_anywhere_returns_subdir(self):
        with mock.patch.object(sq_degiro, "accounts", return_value=["X"]):
            self.assertEqual(
                _resolve_history_dir("X", base=self.base), self.base / "X")


if __name__ == "__main__":
    unittest.main()
