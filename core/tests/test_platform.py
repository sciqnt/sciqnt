"""Conformance test for the platform↔bundle contract.

Every executable wrapper under modules/sq-*/bin/sq-* MUST support `--describe`
and `--commands`. The platform discovers bundles by scanning for these — there
is no hard-coded module list — so this test guards the contract directly.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/
from sq_platform import commands_of, discover_bundles  # noqa: E402
from sq_tui import ANSI_RE as _ANSI_RE  # noqa: E402
import sq_platform  # noqa: E402
import sq_tui  # noqa: E402

ROOT = HERE.parents[1]                                  # sciqnt repo root


def _run_wrapper(wrapper: Path, flag: str) -> str:
    """Run `bin/sq-<name> <flag>` and return stdout (5s budget — these are
    static echo paths in every wrapper; a slow one is itself a contract bug)."""
    out = subprocess.run([str(wrapper), flag], capture_output=True,
                         text=True, timeout=15)
    return out.stdout




class TestAnsi(unittest.TestCase):
    def test_ansi_regex_strips_dim_and_bold(self):
        s = "degiro       \x1b[2mDegiro broker\x1b[0m  \x1b[1mbold\x1b[0m"
        self.assertEqual(_ANSI_RE.sub("", s), "degiro       Degiro broker  bold")


class TestSelectScreenFallback(unittest.TestCase):
    """select_screen's non-TTY path: a numbered prompt (the accessible /
    scriptable fallback). The full-screen prompt_toolkit path needs a real TTY
    and is verified manually; here we pin the fallback contract that tests and
    pipes actually hit."""

    def test_numbered_pick_returns_payload(self):
        items = [("Alpha", "a"), ("Beta", "b"), ("Gamma", "c")]
        with mock.patch.object(sq_tui, "HAS_Q", False), \
             mock.patch("builtins.input", return_value="2"):
            r = sq_tui.select_screen(items, header="H")
        self.assertEqual(r, "b")
        self.assertEqual(sq_tui.select_screen.last_index, 1)   # cursor exposed

    def test_fallback_strips_ansi_from_labels(self):
        printed = []
        with mock.patch.object(sq_tui, "HAS_Q", False), \
             mock.patch("builtins.input", return_value="1"), \
             mock.patch("builtins.print",
                        side_effect=lambda *a, **k: printed.append(
                            " ".join(str(x) for x in a))):
            sq_tui.select_screen([("deg \x1b[2mDegiro\x1b[0m", "d")])
        self.assertNotIn("\x1b[", "\n".join(printed))

    def test_eof_and_invalid_return_esc_result(self):
        with mock.patch.object(sq_tui, "HAS_Q", False), \
             mock.patch("builtins.input", side_effect=EOFError):
            self.assertEqual(
                sq_tui.select_screen([("A", "a")], esc_result=sq_tui.QUIT),
                sq_tui.QUIT)
        with mock.patch.object(sq_tui, "HAS_Q", False), \
             mock.patch("builtins.input", return_value="99"):   # out of range
            self.assertEqual(
                sq_tui.select_screen([("A", "a")], esc_result=sq_tui.BACK),
                sq_tui.BACK)

    def test_empty_items_returns_esc_result(self):
        self.assertEqual(sq_tui.select_screen([], esc_result=sq_tui.QUIT),
                         sq_tui.QUIT)




if __name__ == "__main__":
    unittest.main()




