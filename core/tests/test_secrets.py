"""core/sq_secrets conformance test — offline (keychain mocked, temp .env)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/ on path
from sq_secrets import (  # noqa: E402
    get_secret, load_dotenv, prompt, prompt_and_store, select_mode, store_secret,
)
import sq_secrets


class TestDotenv(unittest.TestCase):
    def test_load_dotenv_populates_env(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# comment\nSQ_TEST_KEY="hello"\nSQ_TEST_EMPTY=\n')
            os.environ.pop("SQ_TEST_KEY", None)
            load_dotenv(p)
            self.assertEqual(os.environ.get("SQ_TEST_KEY"), "hello")
        os.environ.pop("SQ_TEST_KEY", None)

    def test_load_dotenv_missing_file_is_noop(self):
        load_dotenv(Path("/no/such/.env"))  # must not raise


class TestGetSecret(unittest.TestCase):
    def test_env_fallback_when_keychain_empty(self):
        os.environ["SQ_TEST_SECRET"] = "from-env"
        try:
            with mock.patch("keyring.get_password", return_value=None):
                self.assertEqual(
                    get_secret("sq-test", "k", "SQ_TEST_SECRET"), "from-env")
        finally:
            os.environ.pop("SQ_TEST_SECRET", None)

    def test_keychain_takes_precedence(self):
        os.environ["SQ_TEST_SECRET"] = "from-env"
        try:
            with mock.patch("keyring.get_password", return_value="from-keychain"):
                self.assertEqual(
                    get_secret("sq-test", "k", "SQ_TEST_SECRET"), "from-keychain")
        finally:
            os.environ.pop("SQ_TEST_SECRET", None)


class TestStoreSecretFallback(unittest.TestCase):
    def test_keychain_success_returns_keychain(self):
        with mock.patch("keyring.set_password") as ks:
            backend = store_secret("sq-test", "k", "v")
        self.assertEqual(backend, "keychain")
        ks.assert_called_once()

    def test_keychain_failure_writes_to_env_file_with_0600(self):
        # Simulates the macOS-over-SSH case (errSecInteractionNotAllowed -25308).
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            with mock.patch("keyring.set_password",
                            side_effect=Exception("simulated -25308")):
                backend = store_secret(
                    "sq-test", "k", "secret-v",
                    env_var="SQ_TEST_X", env_path=env)
            self.assertEqual(backend, "env_file")
            self.assertIn("SQ_TEST_X=secret-v", env.read_text())
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)

    def test_keychain_failure_with_no_fallback_reraises(self):
        with mock.patch("keyring.set_password",
                        side_effect=Exception("nope")):
            with self.assertRaises(Exception):
                store_secret("sq-test", "k", "v")  # no env_var/env_path


class TestPromptAndStoreNormalize(unittest.TestCase):
    def test_normalize_is_applied_before_store(self):
        captured = {}

        def fake_store(service, key, value, env_var=None, env_path=None, **_):
            captured["value"] = value
            return "keychain"

        fields = [{
            "key": "k", "label": "x", "env": "K",
            "normalize": lambda s: s.replace(" ", "").upper(),
            "validate": lambda s: s.isalnum(),
        }]
        with mock.patch("sq_secrets.prompt", return_value="ab cd EF"), \
             mock.patch("sq_secrets.store_secret", side_effect=fake_store):
            prompt_and_store("svc", fields)
        self.assertEqual(captured["value"], "ABCDEF")  # normalized

    def test_validate_failure_reasks_then_blank_cancels(self):
        """A bad format RE-ASKS (a typo must never kill the flow —
        research/connect-experience.md); blank then cancels, storing nothing."""
        fields = [{
            "key": "k", "label": "x", "env": "K",
            "validate": lambda s: False,   # always fails
        }]
        with mock.patch("sq_secrets.prompt",
                        side_effect=["bad", "also bad", ""]), \
             mock.patch("sq_secrets.store_secret") as ks, \
             self.assertRaises(SystemExit):
            prompt_and_store("svc", fields)
        ks.assert_not_called()


class TestPromptModeDispatch(unittest.TestCase):
    def test_terminal_mode_uses_getpass(self):
        with mock.patch("sq_secrets.prompt_terminal", return_value="x") as t, \
             mock.patch("sq_secrets._osascript_prompt") as g:
            self.assertEqual(prompt("p", hidden=True, mode="terminal"), "x")
        t.assert_called_once_with("p", True)
        g.assert_not_called()

    def test_gui_mode_uses_osascript_on_darwin(self):
        with mock.patch("sys.platform", "darwin"), \
             mock.patch("sq_secrets._osascript_prompt", return_value="y") as g, \
             mock.patch("sq_secrets.prompt_terminal") as t:
            self.assertEqual(prompt("p", hidden=True, mode="gui"), "y")
        g.assert_called_once_with("p", True)
        t.assert_not_called()


class TestSelectMode(unittest.TestCase):
    def test_no_tty_returns_terminal(self):
        with mock.patch("sys.stdin") as si:
            si.isatty.return_value = False
            self.assertEqual(select_mode(), "terminal")

    def test_choice_2_returns_gui_fallback_numbered(self):
        # Force the numbered-menu fallback by pretending questionary isn't there.
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.platform", "darwin"), \
             mock.patch("sq_secrets._HAS_Q", False), \
             mock.patch("builtins.input", return_value="2"):
            si.isatty.return_value = True
            self.assertEqual(select_mode(), "gui")

    def test_blank_choice_defaults_to_terminal_fallback_numbered(self):
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.platform", "darwin"), \
             mock.patch("sq_secrets._HAS_Q", False), \
             mock.patch("builtins.input", return_value=""):
            si.isatty.return_value = True
            self.assertEqual(select_mode(), "terminal")

    def test_questionary_path_returns_choice(self):
        # When questionary is available + TTY, select_mode uses sq_tui.themed_select.
        import sq_tui
        fake_q = mock.MagicMock()
        fake_q.ask.return_value = "gui"
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.platform", "darwin"), \
             mock.patch("sq_secrets._HAS_Q", True), \
             mock.patch.object(sq_tui, "themed_select", return_value=fake_q), \
             mock.patch.object(sq_tui, "Choice",
                               side_effect=lambda title=None, value=None, checked=False:
                                   type("C", (), {"title": title, "value": value})()):
            si.isatty.return_value = True
            self.assertEqual(select_mode(), "gui")
        fake_q.ask.assert_called_once()


class TestPromptAndStoreVerifyGate(unittest.TestCase):
    """Stored values must pass verify FIRST; failure stores nothing (P17)."""

    def _fields(self):
        return [
            {"key": "u", "label": "u", "env": "U", "required": True},
            {"key": "p", "label": "p", "env": "P", "required": True, "hidden": True},
        ]

    def test_verify_pass_stores_all(self):
        stored = []
        def fake_store(service, key, value, env_var=None, env_path=None, **_):
            stored.append(key)
            return "keychain"
        verify_called_with = {}
        def verify(vals):
            verify_called_with.update(vals)
            return True
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "secret"]), \
             mock.patch("sq_secrets.store_secret", side_effect=fake_store):
            prompt_and_store("svc", self._fields(), verify=verify)
        self.assertEqual(verify_called_with, {"u": "alice", "p": "secret"})
        self.assertEqual(stored, ["u", "p"])   # both stored, in order, only after verify

    def test_verify_returning_false_stores_nothing(self):
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "secret"]), \
             mock.patch("sq_secrets.store_secret") as ks, \
             self.assertRaises(SystemExit):
            prompt_and_store("svc", self._fields(), verify=lambda v: False)
        ks.assert_not_called()

    def test_verify_raising_stores_nothing(self):
        def bad(_): raise RuntimeError("bad creds")
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "secret"]), \
             mock.patch("sq_secrets.store_secret") as ks, \
             self.assertRaises(SystemExit):
            prompt_and_store("svc", self._fields(), verify=bad)
        ks.assert_not_called()

    def test_no_verify_behaves_as_before(self):
        stored = []
        def fake_store(service, key, value, env_var=None, env_path=None, **_):
            stored.append(key); return "keychain"
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "secret"]), \
             mock.patch("sq_secrets.store_secret", side_effect=fake_store):
            prompt_and_store("svc", self._fields())   # no verify
        self.assertEqual(stored, ["u", "p"])


class TestAccountNamespacing(unittest.TestCase):
    """Account-qualified keys keep multiple accounts on the same service
    disjoint in the keychain. account=None (the default) preserves the
    legacy single-account scheme so existing users' stored creds keep
    working unchanged."""

    def test_account_none_uses_bare_key(self):
        store = {}
        def fake_set(svc, key, value):
            store[(svc, key)] = value
        def fake_get(svc, key):
            return store.get((svc, key))
        with mock.patch.dict(sys.modules, {"keyring": mock.Mock(
                set_password=fake_set, get_password=fake_get)}):
            store_secret("sq-degiro", "username", "alice", env_var="X")
            self.assertEqual(store, {("sq-degiro", "username"): "alice"})
            v = get_secret("sq-degiro", "username", env_var="X")
            self.assertEqual(v, "alice")

    def test_account_qualifier_namespaces_key(self):
        store = {}
        def fake_set(svc, key, value):
            store[(svc, key)] = value
        def fake_get(svc, key):
            return store.get((svc, key))
        with mock.patch.dict(sys.modules, {"keyring": mock.Mock(
                set_password=fake_set, get_password=fake_get)}):
            store_secret("sq-degiro", "username", "alice",
                         env_var="X", account="primary")
            store_secret("sq-degiro", "username", "bob",
                         env_var="X", account="work")
            self.assertEqual(store, {
                ("sq-degiro", "primary:username"): "alice",
                ("sq-degiro", "work:username"):    "bob",
            })
            # Each account's get returns the right secret
            self.assertEqual(
                get_secret("sq-degiro", "username", account="primary"), "alice")
            self.assertEqual(
                get_secret("sq-degiro", "username", account="work"), "bob")
            # Bare key is independent (would be None if never set)
            self.assertIsNone(get_secret("sq-degiro", "username"))

    def test_env_var_qualified_for_account(self):
        # No keychain → env-var fallback. The env var name is suffixed
        # with the upper-cased account name so multi-account .env files
        # can coexist.
        with mock.patch.dict(sys.modules, {"keyring": mock.Mock(
                get_password=mock.Mock(return_value=None))}):
            with mock.patch.dict(os.environ, {
                "DEGIRO_USERNAME":      "legacy-alice",
                "DEGIRO_USERNAME_WORK": "bob",
            }, clear=False):
                self.assertEqual(
                    get_secret("sq-degiro", "username", env_var="DEGIRO_USERNAME"),
                    "legacy-alice")
                self.assertEqual(
                    get_secret("sq-degiro", "username",
                               env_var="DEGIRO_USERNAME", account="work"),
                    "bob")


class TestAccountRegistry(unittest.TestCase):
    """list_accounts / register_account use a per-service JSON config so
    the dispatcher can enumerate without OS-specific keychain-search APIs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name

    def tearDown(self):
        if self._orig_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._orig_xdg
        self.tmp.cleanup()

    def test_empty_when_no_config(self):
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), [])

    def test_register_adds_to_list(self):
        sq_secrets.register_account("sq-degiro", "primary")
        sq_secrets.register_account("sq-degiro", "work")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"),
                         ["primary", "work"])

    def test_register_is_idempotent(self):
        sq_secrets.register_account("sq-degiro", "primary")
        sq_secrets.register_account("sq-degiro", "primary")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), ["primary"])

    def test_unregister_removes(self):
        sq_secrets.register_account("sq-degiro", "primary")
        sq_secrets.register_account("sq-degiro", "work")
        sq_secrets.unregister_account("sq-degiro", "work")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), ["primary"])

    def test_unregister_missing_is_noop(self):
        sq_secrets.unregister_account("sq-degiro", "never-existed")
        # No raise; still empty.
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), [])

    def test_corrupt_config_returns_empty(self):
        # Tolerance: a corrupt config file must NOT explode the dispatcher
        p = sq_secrets._accounts_path("sq-degiro")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("not valid json")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), [])

    def test_clear_accounts_removes_registry(self):
        sq_secrets.register_account("sq-degiro", "work")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), ["work"])
        sq_secrets.clear_accounts("sq-degiro")
        self.assertEqual(sq_secrets.list_accounts("sq-degiro"), [])

    def test_clear_accounts_missing_is_noop(self):
        sq_secrets.clear_accounts("sq-never")        # must not raise


class TestDefaultAccountFromUsername(unittest.TestCase):
    """A blank account label names the account after an identity field
    (e.g. username) instead of an anonymous bare-key account."""

    def test_blank_account_defaults_to_username(self):
        stored = []      # (key, account)
        registered = []
        def fake_store(service, key, value, env_var=None, env_path=None, *,
                       account=None):
            stored.append((key, account))
            return "keychain"
        fields = [{"key": "username", "label": "u", "env": "U"},
                  {"key": "password", "label": "p", "env": "P", "hidden": True}]
        answers = iter(["alice", "hunter2"])
        with mock.patch("sq_secrets.prompt", side_effect=lambda *a, **k: next(answers)), \
             mock.patch("sq_secrets.store_secret", side_effect=fake_store), \
             mock.patch("sq_secrets.register_account",
                        side_effect=lambda svc, name: registered.append((svc, name))):
            sq_secrets.prompt_and_store("svc", fields,
                                        default_account_from="username")
        # Both secrets stored under the username-derived account
        self.assertEqual(set(a for _, a in stored), {"alice"})
        self.assertEqual(registered, [("svc", "alice")])

    def test_explicit_account_overrides_default(self):
        stored = []
        with mock.patch("sq_secrets.prompt", side_effect=["bob", "pw"]), \
             mock.patch("sq_secrets.store_secret",
                        side_effect=lambda *a, account=None, **k: stored.append(account) or "keychain"), \
             mock.patch("sq_secrets.register_account"):
            sq_secrets.prompt_and_store(
                "svc",
                [{"key": "username", "label": "u", "env": "U"},
                 {"key": "password", "label": "p", "env": "P", "hidden": True}],
                account="work", default_account_from="username")
        self.assertEqual(set(stored), {"work"})    # explicit wins over username


class TestRefreshGuard(unittest.TestCase):
    """Re-connecting an account that already exists is a credential REFRESH,
    not a second account — the flow says so and confirms before overwriting."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tmp.name
        sq_secrets.register_account("svc", "alice")     # alice already connected

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._orig
        self.tmp.cleanup()

    def _fields(self):
        return [{"key": "username", "label": "u", "env": "U"},
                {"key": "password", "label": "p", "env": "P", "hidden": True}]

    def test_existing_account_declined_stores_nothing(self):
        stored = []
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "pw"]), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch("sq_secrets.store_secret",
                        side_effect=lambda *a, **k: stored.append(a) or "keychain"), \
             self.assertRaises(SystemExit):
            sq_secrets.prompt_and_store("svc", self._fields(),
                                        default_account_from="username")
        self.assertEqual(stored, [])        # declined refresh → nothing written

    def test_existing_account_confirmed_stores(self):
        stored = []
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "pw"]), \
             mock.patch("builtins.input", return_value="y"), \
             mock.patch("sq_secrets.store_secret",
                        side_effect=lambda *a, **k: stored.append(a) or "keychain"):
            sq_secrets.prompt_and_store("svc", self._fields(),
                                        default_account_from="username")
        self.assertTrue(stored)             # confirmed refresh → stored

    def test_new_account_does_not_prompt(self):
        # 'bob' isn't connected → no refresh prompt (input must not be called)
        with mock.patch("sq_secrets.prompt", side_effect=["bob", "pw"]), \
             mock.patch("builtins.input",
                        side_effect=AssertionError("should not prompt for a new account")), \
             mock.patch("sq_secrets.store_secret", return_value="keychain"):
            sq_secrets.prompt_and_store("svc", self._fields(),
                                        default_account_from="username")
        self.assertIn("bob", sq_secrets.list_accounts("svc"))


class TestDeleteSecret(unittest.TestCase):
    def test_delete_calls_keyring_with_qualified_key(self):
        deleted = []
        fake = mock.Mock(delete_password=lambda svc, key: deleted.append((svc, key)))
        with mock.patch.dict(sys.modules, {"keyring": fake}):
            ok = sq_secrets.delete_secret("sq-degiro", "username")
            ok2 = sq_secrets.delete_secret("sq-degiro", "username", account="work")
        self.assertTrue(ok)
        self.assertTrue(ok2)
        self.assertEqual(deleted, [("sq-degiro", "username"),
                                   ("sq-degiro", "work:username")])

    def test_delete_returns_false_when_absent(self):
        def boom(svc, key):
            raise Exception("not found")
        fake = mock.Mock(delete_password=boom)
        with mock.patch.dict(sys.modules, {"keyring": fake}):
            self.assertFalse(sq_secrets.delete_secret("sq-degiro", "username"))


if __name__ == "__main__":
    unittest.main()
