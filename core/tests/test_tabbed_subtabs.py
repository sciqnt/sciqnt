"""tabbed_view sub-tabs — a dict-valued tab renders as a second-level tab set.

Interactive behaviour needs a TTY; what IS testable headlessly: the non-TTY
fallback prints every (tab › sub-tab) sequentially, and callable sub-bodies are
lazy (evaluated exactly once via the shared memo)."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_tui                                             # noqa: E402


class TestSubTabsNonTTY(unittest.TestCase):
    def test_dict_tab_prints_each_subtab(self):
        calls = []

        def monthly():
            calls.append(1)
            return "MONTHLY-BODY"

        tabs = {
            "summary": "SUMMARY-BODY",
            "history": {"daily": "DAILY-BODY", "monthly": monthly},
        }
        out = io.StringIO()
        with redirect_stdout(out):
            sq_tui.tabbed_view(tabs, title="t")           # non-TTY in tests
        text = out.getvalue()
        self.assertIn("history › daily", text)
        self.assertIn("history › monthly", text)
        self.assertIn("DAILY-BODY", text)
        self.assertIn("MONTHLY-BODY", text)
        self.assertEqual(calls, [1])                      # lazy body ran once

    def test_body_note_tuple_prints_note_inline(self):
        """A (body, note) tab value: the TUI shows the note only behind ?,
        but the non-TTY dump prints it inline so scripts/agents keep it."""
        tabs = {
            "summary": ("BODY-TEXT", "NOTE-TEXT"),
            "history": {"daily": lambda: ("D-BODY", "D-NOTE")},
        }
        out = io.StringIO()
        with redirect_stdout(out):
            sq_tui.tabbed_view(tabs, title="t")
        text = out.getvalue()
        self.assertIn("BODY-TEXT", text)
        self.assertIn("NOTE-TEXT", text)
        self.assertLess(text.index("BODY-TEXT"), text.index("NOTE-TEXT"))
        self.assertIn("D-BODY", text)
        self.assertIn("D-NOTE", text)


class TestStreamOutput(unittest.TestCase):
    """stream_output routes status() AND raw prints into the sink (ANSI
    stripped, blanks dropped) — the live-progress feed for async tabs."""

    def test_captures_status_and_stdout(self):
        got = []
        with sq_tui.stream_output(got.append):
            sq_tui.status("fetching degiro…")
            print(f"{sq_tui.DIM}connected · int_account=1{sq_tui.RST}")
            print("")                                     # blank → dropped
        self.assertEqual(got, ["fetching degiro…", "connected · int_account=1"])
        # restored afterwards: status prints again (no sink)
        out = io.StringIO()
        with redirect_stdout(out):
            sq_tui.status("after")
        self.assertIn("after", out.getvalue())


if __name__ == "__main__":
    unittest.main()
