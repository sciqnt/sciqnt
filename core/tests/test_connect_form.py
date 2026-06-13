"""The connect form (research/connect-experience.md) — review/edit before
verify, refresh-vs-new folded into the review, and the plain-language account
problem lines.

The review screen is the typo-recovery primitive: a wrong username is fixed
by re-entering ONE field, never exit-and-restart. Nothing reaches verify or
storage until the user confirms the reviewed set."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_secrets                                         # noqa: E402
from sq_secrets import NeedsAction, prompt_and_store      # noqa: E402


FIELDS = [
    {"key": "u", "label": "username", "env": "U", "required": True},
    {"key": "p", "label": "password", "env": "P", "required": True,
     "hidden": True},
]


def _interactive(**also):
    """Patch the seams so the review loop runs deterministically: terminal
    mode, tty stdin, mocked prompt/input/store."""
    patches = {
        "prompt": mock.patch("sq_secrets.prompt", **also.pop("prompt")),
        "input": mock.patch("builtins.input", **also.pop("input")),
        "store": mock.patch("sq_secrets.store_secret",
                            return_value="keychain"),
        "isatty": mock.patch.object(sq_secrets.sys.stdin, "isatty",
                                    return_value=True),
    }
    return patches


class TestReviewEdit(unittest.TestCase):
    def _run(self, prompts, confirms, verify=None, accounts=()):
        stored = []

        def fake_store(service, key, value, env_var=None, env_path=None, **_):
            stored.append((key, value))
            return "keychain"

        out = io.StringIO()
        with mock.patch("sq_secrets.prompt", side_effect=prompts), \
             mock.patch("builtins.input", side_effect=confirms), \
             mock.patch("sq_secrets.store_secret", side_effect=fake_store), \
             mock.patch("sq_secrets.list_accounts",
                        return_value=list(accounts)), \
             mock.patch("sq_secrets.register_account"), \
             mock.patch.object(sq_secrets.sys.stdin, "isatty",
                               return_value=True), \
             redirect_stdout(out):
            prompt_and_store("sq-x", FIELDS, mode="terminal", verify=verify,
                             default_account_from="u", review=True)
        return stored, out.getvalue()

    def test_typo_fixed_via_review_edit(self):
        # types u/p, spots the username typo, edits field 1, connects
        stored, out = self._run(
            prompts=["AlicEexample", "pw", "AliceExample"],     # 3rd = the re-entry
            confirms=["1", ""])                          # edit #1, then enter
        self.assertIn(("u", "AliceExample"), stored)        # fixed value stored
        self.assertIn("password", out)
        self.assertIn("········", out)                   # secret masked
        self.assertNotIn("pw", out.replace("password", ""))  # value never shown

    def test_review_shows_derived_account_name(self):
        _, out = self._run(prompts=["alice", "pw"], confirms=[""])
        self.assertIn("account name", out)
        self.assertIn("alice", out)

    def test_refresh_note_folded_into_review(self):
        # already-connected account: the review NAMES it; no extra y/N step
        _, out = self._run(prompts=["alice", "pw"], confirms=[""],
                           accounts=["alice"])
        self.assertIn("already connected", out)
        self.assertIn("refreshes its credentials", out)

    def test_cancel_at_review_stores_nothing(self):
        stored = []
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "pw"]), \
             mock.patch("builtins.input", side_effect=["q"]), \
             mock.patch("sq_secrets.store_secret",
                        side_effect=lambda *a, **k: stored.append(a)), \
             mock.patch("sq_secrets.list_accounts", return_value=[]), \
             mock.patch.object(sq_secrets.sys.stdin, "isatty",
                               return_value=True), \
             redirect_stdout(io.StringIO()), \
             self.assertRaises(SystemExit):
            prompt_and_store("sq-x", FIELDS, mode="terminal",
                             default_account_from="u", review=True)
        self.assertEqual(stored, [])

    def test_verify_runs_after_review_with_edited_values(self):
        seen = {}

        def verify(vals):
            seen.update(vals)
            return True

        self._run(prompts=["wrng", "pw", "right"], confirms=["1", ""],
                  verify=verify)
        self.assertEqual(seen["u"], "right")             # verify saw the FIX

    def test_review_off_keeps_plain_flow(self):
        # review=False (the default): no input() consumed at all
        stored = []
        with mock.patch("sq_secrets.prompt", side_effect=["alice", "pw"]), \
             mock.patch("builtins.input",
                        side_effect=AssertionError("input must not be read")), \
             mock.patch("sq_secrets.store_secret",
                        side_effect=lambda s, k, v, **kw: stored.append(k)
                        or "keychain"), \
             mock.patch("sq_secrets.list_accounts", return_value=[]), \
             mock.patch("sq_secrets.register_account"), \
             mock.patch.object(sq_secrets.sys.stdin, "isatty",
                               return_value=True), \
             redirect_stdout(io.StringIO()):
            prompt_and_store("sq-x", FIELDS, mode="terminal",
                             default_account_from="u")
        self.assertEqual(stored, ["u", "p"])


class TestNeedsAction(unittest.TestCase):
    def test_contract(self):
        e = NeedsAction("approve the login in the DEGIRO app", action="approve")
        self.assertEqual(str(e), "approve the login in the DEGIRO app")
        self.assertEqual(e.action, "approve")
        self.assertIsInstance(e, RuntimeError)           # dispatcher-catchable

    def test_default_action(self):
        self.assertEqual(NeedsAction("x").action, "reconnect")


class TestAccountProblemLines(unittest.TestCase):
    """One classifier, plain words + the action — raw exception text never
    reaches the screen (it goes to the ? help note instead)."""

    def _line(self, broker, error):
        from sq_platform.aggregated import _account_problem

        class B:
            pass
        b = B()
        b.broker, b.error = broker, error
        return _account_problem(b)

    def test_credentials_missing(self):
        ln = self._line("robinhood:dave", "CredentialsMissing: No Robinhood…")
        self.assertIn("isn't connected", ln)
        self.assertIn("Connect new Account", ln)
        self.assertNotIn("CredentialsMissing", ln)       # no jargon

    def test_needs_action_just_says_couldnt_fetch(self):
        """A 'needs action' failure stops at the honest symptom — no guessed
        reason or remedy (the agent, recommended above, diagnoses), and never
        the raw exception class."""
        ln = self._line("degiro:Alice", "NeedsAction: needs re-authentication")
        self.assertIn("couldn't fetch", ln)
        self.assertNotIn("re-authentication", ln)         # no guessed reason
        self.assertNotIn("NeedsAction", ln)               # no jargon

    def test_conformance_is_integrity_warning(self):
        ln = self._line("degiro:Main", "conformance: bad money decimal")
        self.assertIn("integrity", ln)
        self.assertNotIn("bad money decimal", ln)        # detail → ? help

    def test_unknown_error_just_says_couldnt_fetch(self):
        ln = self._line("kalshi:k1", "ReadTimeout: HTTPSConnectionPool…")
        self.assertIn("couldn't fetch", ln)
        self.assertNotIn("HTTPSConnectionPool", ln)       # no raw detail


if __name__ == "__main__":
    unittest.main()


class TestWarningModeComponent(unittest.TestCase):
    """When accounts fail, the SciQnt Agent component keeps the SAME layout
    as the healthy state (selector row + toggle first) — only the greyed
    Ask-hint slot is replaced by an orange '⚠ Recommended: Troubleshoot with
    Agent' header + the issue lines beneath."""

    def _rows(self, warnings=None):
        from sq_platform import home
        with mock.patch.object(home.sq_agents, "recent_installed",
                               return_value=["claude"]), \
             mock.patch.object(home.sq_agents, "label",
                               side_effect=lambda n: n.title()):
            return home._agent_rows("home", warnings)

    def test_warning_mode_layout(self):
        import sq_tui
        rows, styles, toggle, installed = self._rows(
            ["degiro:Alice needs you — approve the login in the DEGIRO app"])
        self.assertIsNotNone(toggle)                  # toggle KEPT (same style)
        self.assertEqual(rows[0][1], "agent")         # selector row still first
        self.assertIn("SciQnt Agent + Claude", rows[0][0])
        self.assertIn("⚠ Recommended: Troubleshoot with Agent", rows[1][0])  # header
        self.assertEqual(rows[1][1], sq_tui.SEP)
        self.assertIn("needs you", rows[2][0])        # issue lines indented
        self.assertTrue(rows[2][0].startswith("      "))
        self.assertFalse(any('Ask "' in r[0] for r in rows))    # hint replaced

    def test_warning_rows_use_the_warn_style_class(self):
        """Orange comes from the select_screen 'warn' STYLE CLASS, not baked
        ANSI — prompt_toolkit discards raw ESC codes in fragments and a None
        style falls back to class:head (bold white)."""
        rows, styles, *_ = self._rows(["x failed"])
        self.assertEqual(styles[1], "warn")           # header
        self.assertEqual(styles[2], "warn")           # issue line
        self.assertNotIn("\x1b", rows[1][0] + rows[2][0])

    def test_multiple_issues_listed(self):
        rows, *_ = self._rows(["a failed", "b failed"])
        texts = [r[0] for r in rows]
        self.assertEqual(sum("⚠ Recommended: Troubleshoot with Agent" in t
                             for t in texts), 1)      # ONE header
        self.assertTrue(any("a failed" in t for t in texts))
        self.assertTrue(any("b failed" in t for t in texts))

    def test_long_outage_list_is_capped(self):
        """A long failing-account list is truncated so it can't push the
        portfolio table off the fixed-height frame."""
        rows, *_ = self._rows([f"acct{i} failed" for i in range(7)])
        texts = [r[0] for r in rows]
        self.assertTrue(any("…and 4 more" in t for t in texts))   # 7 − 3 shown
        self.assertFalse(any("acct5 failed" in t for t in texts)) # beyond the cap

    def test_healthy_mode_unchanged(self):
        rows, styles, toggle, installed = self._rows(None)
        self.assertIsNotNone(toggle)
        self.assertIn("SciQnt Agent + Claude", rows[0][0])
        self.assertTrue(any('Ask "' in r[0] for r in rows))
        self.assertFalse(any("Troubleshoot" in r[0] for r in rows))


class TestAccountProblemText(unittest.TestCase):
    def test_plain_variant_has_no_ansi(self):
        from sq_platform.aggregated import account_problem_text

        class B:
            broker, error = "degiro:G", "NeedsAction: needs re-authentication"
        text = account_problem_text(B())
        self.assertNotIn("\x1b", text)
        self.assertEqual(text, "degiro:G couldn't fetch")
