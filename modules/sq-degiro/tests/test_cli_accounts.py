"""CLI account-resolution + multi-account sync-loop contracts.

The CLI boundary itself (argparse, TTY picker, exit codes) is hard to test
end-to-end, so these pin the testable units behind it:

  * `live._resolve_account` — the --account contract: one configured account
    → auto-selected; several + flag → the flag; several + no flag → the
    PICK_ACCOUNT sentinel (main() turns that into a TTY picker, or exit 2
    with the account list for scripts).
  * `history_sync.run_sync` — the per-account loop: CredentialsMissing /
    NeedsAction on ONE account becomes a friendly line and the OTHERS still
    sync; the summary and exit code reflect everything; no traceback ever
    escapes the loop.

Fixtures are synthetic (AccountA/AccountB/AccountC) — never real names.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE.parent / "src"))

import sq_secrets                                                  # noqa: E402
from sq_degiro.history_sync import run_sync                        # noqa: E402
from sq_degiro.live import (CredentialsMissing, PICK_ACCOUNT,      # noqa: E402
                            _resolve_account)


class TestResolveAccount(unittest.TestCase):
    def test_flag_always_wins(self):
        self.assertEqual(
            _resolve_account(["AccountA", "AccountB"], "AccountB"), "AccountB")

    def test_single_named_account_auto_selected(self):
        self.assertEqual(_resolve_account(["AccountA"], None), "AccountA")

    def test_single_legacy_entry_stays_legacy(self):
        # accounts() reports legacy bare-key creds as [None] — live must
        # keep using the unqualified lookup, not demand a name.
        self.assertIsNone(_resolve_account([None], None))

    def test_none_configured_falls_back_to_legacy(self):
        # Nothing configured → legacy path; the CredentialsMissing raised
        # downstream is the friendly "run sciqnt degiro setup" message.
        self.assertIsNone(_resolve_account([], None))

    def test_several_without_flag_needs_a_pick(self):
        self.assertIs(
            _resolve_account(["AccountA", "AccountB"], None), PICK_ACCOUNT)

    def test_legacy_plus_named_also_needs_a_pick(self):
        self.assertIs(_resolve_account([None, "AccountA"], None), PICK_ACCOUNT)


class TestRunSync(unittest.TestCase):
    def test_credentials_missing_does_not_block_other_accounts(self):
        synced = []

        def syncer(account):
            if account == "AccountB":
                raise CredentialsMissing(
                    "No credentials found for account AccountB. "
                    "Set them once with: sciqnt degiro setup --account AccountB.")
            synced.append(account)
            return "3 new rows (total 10, through 2026-06-10)"

        lines = []
        summary, rc = run_sync(["AccountA", "AccountB", "AccountC"], syncer,
                               out=lines.append)
        self.assertEqual(synced, ["AccountA", "AccountC"])   # B skipped, rest ran
        self.assertEqual(rc, 1)                              # one account failed
        self.assertIn("AccountA: 3 new rows", summary)
        self.assertIn("AccountB: No credentials found", summary)
        self.assertIn("AccountC: 3 new rows", summary)
        # progress lines were emitted per account (before + after)
        self.assertIn("  AccountA: syncing…", lines)
        self.assertIn("  AccountC: 3 new rows (total 10, through 2026-06-10)",
                      lines)

    def test_all_green_summary_and_exit_zero(self):
        summary, rc = run_sync(["AccountA", "AccountB"],
                               lambda a: "up to date", out=lambda s: None)
        self.assertEqual(rc, 0)
        self.assertEqual(summary,
                         "AccountA: up to date · AccountB: up to date")

    def test_needs_action_is_friendly_and_continues(self):
        def syncer(account):
            if account == "AccountA":
                raise sq_secrets.NeedsAction(
                    "approve the login in the DEGIRO app, then refresh",
                    action="approve")
            return "up to date"

        summary, rc = run_sync(["AccountA", "AccountB"], syncer,
                               out=lambda s: None)
        self.assertEqual(rc, 1)
        self.assertIn("AccountA: ⚠ approve the login", summary)
        self.assertIn("AccountB: up to date", summary)

    def test_unexpected_error_is_one_line_not_a_traceback(self):
        summary, rc = run_sync(
            ["AccountA"],
            lambda a: (_ for _ in ()).throw(ValueError("boom")),
            out=lambda s: None)
        self.assertEqual(rc, 1)
        self.assertIn("AccountA: sync failed: ValueError: boom", summary)

    def test_legacy_none_account_labelled_default(self):
        summary, rc = run_sync([None], lambda a: "up to date",
                               out=lambda s: None)
        self.assertEqual(summary, "default: up to date")
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
