"""The connector-capability probe (`_accepts_kwarg` / `_call_with_account`
/ `_get_rate_at`) — the replacement for the `except TypeError` retry dance.

THE load-bearing pin: a GENUINE TypeError raised INSIDE a capability that
accepts `account=` must PROPAGATE — the old dance swallowed it and retried
without the kwarg, which could silently fetch the DEFAULT account's money
when the NAMED account's fetch was the one that broke (audit 2026-06-11).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/
ROOT = HERE.parent.parent
for _bundle in (ROOT / "modules").glob("sq-*"):
    _src = _bundle / "src"
    if _src.is_dir():
        sys.path.insert(0, str(_src))

from sq_platform.aggregated import (                     # noqa: E402
    _accepts_kwarg, _call_with_account, _get_rate_at,
)


class TestAcceptsKwarg(unittest.TestCase):
    def test_named_kwarg_detected(self):
        self.assertTrue(_accepts_kwarg(lambda account=None: None, "account"))
        self.assertFalse(_accepts_kwarg(lambda: None, "account"))

    def test_var_keyword_accepts_anything(self):
        self.assertTrue(_accepts_kwarg(lambda **kw: None, "account"))

    def test_uninspectable_returns_none(self):
        # C builtins have no introspectable Python signature on every
        # version — len is reliably uninspectable enough across builds
        # that None OR a real answer is acceptable; what matters is it
        # never raises.
        try:
            result = _accepts_kwarg(len, "account")
        except Exception as e:                           # noqa: BLE001
            self.fail(f"probe raised: {e}")
        self.assertIn(result, (True, False, None))


class TestCallWithAccount(unittest.TestCase):
    def test_account_passed_when_supported(self):
        seen = {}
        def fn(asof, *, account=None):
            seen["account"] = account
            return "ok"
        self.assertEqual(_call_with_account(fn, "work", "ASOF"), "ok")
        self.assertEqual(seen["account"], "work")

    def test_account_omitted_when_unsupported(self):
        def fn(asof):
            return ("no-account", asof)
        self.assertEqual(_call_with_account(fn, "work", 7),
                         ("no-account", 7))

    def test_internal_typeerror_propagates(self):
        # THE pin: the capability ACCEPTS account= but raises a genuine
        # TypeError inside. The old dance retried WITHOUT account= and
        # could return the wrong account's data; now it must propagate.
        calls = []
        def fn(*, account=None):
            calls.append(account)
            raise TypeError("genuine internal bug")
        with self.assertRaises(TypeError):
            _call_with_account(fn, "work")
        self.assertEqual(calls, ["work"])                # never retried bare


class TestGetRateAt(unittest.TestCase):
    def test_asof_passed_when_supported(self):
        class _Fx:
            def get_rate(self, src, dst, *, asof=None):
                return ("rate", src, dst, asof)
        self.assertEqual(_get_rate_at(_Fx(), "USD", "EUR", "D"),
                         ("rate", "USD", "EUR", "D"))

    def test_asof_omitted_for_legacy_provider(self):
        class _Legacy:
            def get_rate(self, src, dst):
                return ("latest", src, dst)
        self.assertEqual(_get_rate_at(_Legacy(), "USD", "EUR", "D"),
                         ("latest", "USD", "EUR"))


if __name__ == "__main__":
    unittest.main()
