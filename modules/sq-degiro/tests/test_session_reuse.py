"""sq_degiro.connected_api — ONE login per account, persisted across runs.

Why this matters: a fresh `api.connect()` per fetch looks like a new
device/browser to Degiro and fires a login-alert email each time. The
contract under test: (a) a valid persisted session is RESUMED, zero
connect() calls; (b) a rejected/absent session triggers exactly one
connect() and persists the new session id; (c) reset_api drops both the
in-process and on-disk session. No network — TradingAPI is faked.
"""
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE.parent / "src"))

import sq_secrets                                                  # noqa: E402
import sq_degiro                                                   # noqa: E402

# These tests exercise the LIVE flavour (session persistence over the
# degiro_connector SDK) — installed via `pip install sciqnt-degiro[live]`.
# A CSV-only standalone install legitimately lacks it: SKIP, never error.
try:
    import degiro_connector                                        # noqa: F401
except ImportError:
    raise unittest.SkipTest(
        "live flavour not installed (pip install sciqnt-degiro[live])")


class _FakeStorage:
    def __init__(self):
        self.session_id = None


class _FakeAPI:
    """Stands in for degiro_connector TradingAPI. `valid_ids` is the set of
    session ids the fake server accepts; connect() mints 'fresh-<n>'."""
    minted = 0

    def __init__(self, credentials, valid_ids):
        import types
        import requests
        self.credentials = credentials
        self.connection_storage = _FakeStorage()
        self.session_storage = types.SimpleNamespace(session=requests.Session())
        self._valid = valid_ids
        self.connect_calls = 0

    def setup_all_actions(self):
        pass

    def connect(self):
        self.connect_calls += 1
        _FakeAPI.minted += 1
        sid = f"fresh-{_FakeAPI.minted}"
        self.connection_storage.session_id = sid
        self._valid.add(sid)

    def get_client_details(self):
        if self.connection_storage.session_id not in self._valid:
            raise ConnectionError("session rejected")
        return {"data": {"intAccount": 42}}


class TestConnectedApi(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_env = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self._tmp.name) / "config.json")
        sq_degiro._APIS.clear()
        _FakeAPI.minted = 0
        self._valid = set()

        class _Creds:
            int_account = None
        patches = [
            mock.patch("degiro_connector.trading.api.API",
                       lambda credentials: _FakeAPI(credentials, self._valid)),
            mock.patch("sq_degiro.live._credentials", lambda account: _Creds()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        sq_degiro._APIS.clear()
        if self._old_env is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._old_env
        self._tmp.cleanup()

    def test_cold_start_logs_in_once_and_persists(self):
        api, int_account = sq_degiro.connected_api("Main")
        self.assertEqual(int_account, 42)
        self.assertEqual(api.connect_calls, 1)
        saved = sq_secrets.load_session("sq-degiro", account="Main")
        self.assertEqual(saved["session_id"], "fresh-1")

    def test_in_process_reuse_no_second_login(self):
        api1, _ = sq_degiro.connected_api("Main")
        api2, _ = sq_degiro.connected_api("Main")
        self.assertIs(api1, api2)
        self.assertEqual(api1.connect_calls, 1)              # still ONE login

    def test_resume_from_disk_zero_logins(self):
        # a previous process left a session the server still accepts
        sq_secrets.save_session("sq-degiro", {"session_id": "from-disk"},
                                account="Main")
        self._valid.add("from-disk")
        api, int_account = sq_degiro.connected_api("Main")
        self.assertEqual(int_account, 42)
        self.assertEqual(api.connect_calls, 0)               # resumed, no login
        self.assertEqual(api.connection_storage.session_id, "from-disk")

    def test_rejected_session_self_heals_with_one_login(self):
        sq_secrets.save_session("sq-degiro", {"session_id": "expired"},
                                account="Main")              # server rejects it
        api, int_account = sq_degiro.connected_api("Main")
        self.assertEqual(int_account, 42)
        self.assertEqual(api.connect_calls, 1)
        saved = sq_secrets.load_session("sq-degiro", account="Main")
        self.assertEqual(saved["session_id"], "fresh-1")     # re-persisted

    def test_accounts_are_isolated(self):
        api_a, _ = sq_degiro.connected_api("A")
        api_b, _ = sq_degiro.connected_api("B")
        self.assertIsNot(api_a, api_b)
        self.assertIsNotNone(sq_secrets.load_session("sq-degiro", account="A"))
        self.assertIsNotNone(sq_secrets.load_session("sq-degiro", account="B"))

    def test_reset_api_clears_memory_and_disk(self):
        sq_degiro.connected_api("Main")
        sq_degiro.reset_api("Main")
        self.assertNotIn("Main", sq_degiro._APIS)
        self.assertIsNone(sq_secrets.load_session("sq-degiro", account="Main"))

    def test_cookies_survive_across_processes(self):
        """The 'remember this device for 30 days' grant is a cookie — it must
        ride along with the session id, or every fresh process re-triggers
        the in-app popup regardless of what the user ticked."""
        import time
        api1, _ = sq_degiro.connected_api("Main")
        api1.session_storage.session.cookies.set(
            "deviceTrust", "tok", domain="trader.degiro.nl", path="/",
            expires=int(time.time()) + 30 * 86400, secure=True)
        sq_degiro.persist_session_state(api1, account="Main")
        sq_degiro._APIS.clear()                       # simulate a new process
        api2, _ = sq_degiro.connected_api("Main")
        jar = {c.name: c.value for c in api2.session_storage.session.cookies}
        self.assertEqual(jar.get("deviceTrust"), "tok")

    def test_cookie_only_restore_for_setup_verify(self):
        """restore_device_cookies loads the 30-day deviceToken but NOT the
        session id — setup's verify must run a REAL login (to validate the
        newly-typed credentials) while riding the device trust."""
        import time
        api1, _ = sq_degiro.connected_api("Main")
        api1.session_storage.session.cookies.set(
            "deviceToken", "tok", domain="trader.degiro.nl", path="/",
            expires=int(time.time()) + 30 * 86400)
        sq_degiro.persist_session_state(api1, account="Main")
        fresh = _FakeAPI(object(), self._valid)
        sq_degiro.restore_device_cookies(fresh, "Main")
        jar = {c.name: c.value for c in fresh.session_storage.session.cookies}
        self.assertEqual(jar.get("deviceToken"), "tok")
        self.assertIsNone(fresh.connection_storage.session_id)  # no resume

    def test_expired_cookies_not_persisted(self):
        import time
        api, _ = sq_degiro.connected_api("Main")
        api.session_storage.session.cookies.set(
            "dead", "x", domain="trader.degiro.nl",
            expires=int(time.time()) - 60)
        sq_degiro.persist_session_state(api, account="Main")
        saved = sq_secrets.load_session("sq-degiro", account="Main")
        self.assertNotIn("dead", [c["name"] for c in saved["cookies"]])


def _login_err(status, status_text, token=None):
    from degiro_connector.core.exceptions import DeGiroConnectionError
    from degiro_connector.trading.models.login import LoginError
    return DeGiroConnectionError(
        "…", LoginError(status=status, statusText=status_text,
                        inAppToken=token))


class _InAppAPI:
    """Mirrors the REAL protocol (observed live): the initial /login answers
    status 12 + inAppToken; polling /in-app while the popup is unanswered
    answers status 3 'badCredentials' (yes, really); after the user taps
    Yes (`approve_after` attempts) it returns the session id."""

    def __init__(self, approve_after):
        import types
        self.credentials = types.SimpleNamespace(in_app_token=None,
                                                 int_account=None)
        self.connection_storage = _FakeStorage()
        self.attempts = 0
        self._approve_after = approve_after

    def connect(self):
        self.attempts += 1
        if self.credentials.in_app_token is None:
            raise _login_err(12, "inAppTOTPNeeded", "tok-1")   # popup pushed
        if self.credentials.in_app_token == "tok-1" \
                and self.attempts > self._approve_after:
            self.connection_storage.session_id = "approved-sid"
            return
        raise _login_err(3, "badCredentials")        # pending, NOT bad creds


class TestInAppApproval(unittest.TestCase):
    """Degiro accounts WITHOUT a TOTP key use in-app login confirmation:
    status 12 + an inAppToken, then the client polls /in-app until the user
    taps Yes. degiro-connector just raises — sq_degiro.login completes it."""

    def test_polls_until_approved(self):
        api = _InAppAPI(approve_after=3)
        msgs = []
        flow = sq_degiro.login(api, notify=msgs.append, poll=0.001)
        self.assertEqual(flow, "in-app")          # caller can suggest TOTP
        self.assertEqual(api.connection_storage.session_id, "approved-sid")
        self.assertTrue(any("DEGIRO app" in m for m in msgs))
        self.assertIsNone(api.credentials.in_app_token)   # never leaks onward

    def test_timeout_raises_needs_action(self):
        """An unanswered popup surfaces as NeedsAction — the platform's
        plain-language contract (one ⚠ line: what to do), not a raw timeout."""
        api = _InAppAPI(approve_after=10**9)              # user never taps
        with self.assertRaises(sq_secrets.NeedsAction) as ctx:
            sq_degiro.login(api, notify=None, timeout=0.01, poll=0.001)
        self.assertEqual(ctx.exception.action, "approve")
        self.assertIn("DEGIRO app", str(ctx.exception))
        self.assertIsNone(api.credentials.in_app_token)

    def test_no_wait_fails_fast_without_polling(self):
        """The AUTOMATIC path (wait_for_approval=False) must NOT sit on the
        in-app poll — one stuck account would hang every refresh. It raises
        NeedsAction immediately after the first /login (status 12), with no
        further /in-app polls."""
        api = _InAppAPI(approve_after=10**9)
        with self.assertRaises(sq_secrets.NeedsAction) as ctx:
            sq_degiro.login(api, notify=None, wait_for_approval=False)
        self.assertEqual(ctx.exception.action, "approve")
        self.assertEqual(api.attempts, 1)                 # ONE attempt, no poll
        self.assertIsNone(api.credentials.in_app_token)   # never leaks onward

    def test_genuinely_bad_credentials_raise_immediately(self):
        """status 3 on the INITIAL /login (before any status 12) really is
        bad credentials — no in-app phase, no polling, immediate raise."""
        from degiro_connector.core.exceptions import DeGiroConnectionError

        class _BadCreds:
            def __init__(self):
                import types
                self.credentials = types.SimpleNamespace(in_app_token=None)
                self.connection_storage = _FakeStorage()
                self.attempts = 0

            def connect(self):
                self.attempts += 1
                raise _login_err(3, "badCredentials")

        api = _BadCreds()
        with self.assertRaises(DeGiroConnectionError):
            sq_degiro.login(api, poll=0.001)
        self.assertEqual(api.attempts, 1)                 # no retry storm

    def test_unrelated_error_during_poll_raises(self):
        """During the in-app phase only 3/12 mean 'pending' — anything else
        (e.g. 405 maintenance) must surface, not be polled forever."""
        from degiro_connector.core.exceptions import DeGiroConnectionError

        class _Breaks:
            def __init__(self):
                import types
                self.credentials = types.SimpleNamespace(in_app_token=None)
                self.connection_storage = _FakeStorage()
                self.attempts = 0

            def connect(self):
                self.attempts += 1
                if self.credentials.in_app_token is None:
                    raise _login_err(12, "inAppTOTPNeeded", "tok-1")
                raise _login_err(405, "maintenance")

        api = _Breaks()
        with self.assertRaises(DeGiroConnectionError):
            sq_degiro.login(api, poll=0.001)
        self.assertEqual(api.attempts, 2)


if __name__ == "__main__":
    unittest.main()
