"""sq_secrets session store — broker-session persistence (the anti-"new
device email" substrate). Bearer-secret hygiene: dir 0700, file 0600;
SQ_CONFIG_PATH redirects the store (tests never touch ~/.config/sciqnt);
corrupt files read as absent (caller falls through to a fresh login)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_secrets                                         # noqa: E402


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self._tmp.name) / "config.json")

    def tearDown(self):
        if self._old is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._old
        self._tmp.cleanup()

    def test_roundtrip_and_perms(self):
        sq_secrets.save_session("sq-x", {"session_id": "abc"}, account="A")
        self.assertEqual(sq_secrets.load_session("sq-x", account="A"),
                         {"session_id": "abc"})
        p = sq_secrets.session_dir("sq-x", account="A") / "session.json"
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p.parent.stat().st_mode & 0o777, 0o700)
        # store lives under the (overridden) config home, not real $HOME
        self.assertTrue(str(p).startswith(self._tmp.name))

    def test_absent_and_corrupt_read_as_none(self):
        self.assertIsNone(sq_secrets.load_session("sq-x", account="A"))
        p = sq_secrets.session_dir("sq-x", account="A") / "session.json"
        p.write_text("{not json")
        self.assertIsNone(sq_secrets.load_session("sq-x", account="A"))

    def test_clear(self):
        sq_secrets.save_session("sq-x", {"session_id": "abc"})
        sq_secrets.clear_session("sq-x")
        self.assertIsNone(sq_secrets.load_session("sq-x"))
        sq_secrets.clear_session("sq-x")                  # idempotent

    def test_account_name_sanitised_for_filesystem(self):
        sq_secrets.save_session("sq-x", {"sid": 1}, account="user@host:7/x")
        d = sq_secrets.session_dir("sq-x", account="user@host:7/x")
        self.assertNotIn("/", d.name)
        self.assertNotIn(":", d.name)
        self.assertEqual(sq_secrets.load_session("sq-x", account="user@host:7/x"),
                         {"sid": 1})


if __name__ == "__main__":
    unittest.main()
