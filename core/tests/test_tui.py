"""sq_tui — design substrate tests.

Modules consume sq_tui for theming (style, tokens, table/heading helpers).
These tests pin the contract so bundles inherit a uniform look-and-feel and
the maintenance loop catches drift if anyone reaches around the substrate.
"""
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))     # core/
import sq_tui  # noqa: E402
from sq_tui import (  # noqa: E402
    ACCENT, ANSI_RE, BOLD, CYAN, DIM, HAS_Q, RST, STYLE, YELLOW,
    _clamp_scroll, clear_screen, fmt_num, fmt_pct, fmt_signed,
    format_table, print_table, tabbed_view, warn_line,
)


class TestPzTuiTokens(unittest.TestCase):
    def test_ansi_tokens_present(self):
        for tok in (BOLD, DIM, CYAN, RST):
            self.assertTrue(tok.startswith("\x1b["),
                            "ANSI tokens must be ANSI escape sequences")

    def test_ansi_regex_strips_all(self):
        s = f"{BOLD}hi{RST} {DIM}x{RST} {CYAN}y{RST}"
        self.assertEqual(ANSI_RE.sub("", s), "hi x y")

    def test_style_present_when_questionary_available(self):
        if HAS_Q:
            self.assertIsNotNone(STYLE, "STYLE must be a questionary.Style when HAS_Q")
        else:
            self.assertIsNone(STYLE)


class TestPrintTable(unittest.TestCase):
    """print_table returns the rendered string (in addition to printing) so
    we can inspect it without capturing stdout."""

    def test_widths_and_alignment(self):
        out = print_table(
            ["sym", "qty", "value"],
            [["AAPL", 10, "1,500.00"],
             ["TSLA-LONG-NAME", 5, "1,250.00"]],
        )
        plain = ANSI_RE.sub("", out)
        # Header column 'sym' should be padded to width of 'TSLA-LONG-NAME' (14)
        self.assertIn("sym           ", plain)
        # Numeric column right-aligned: value column ends with '1,500.00'
        for line in plain.splitlines():
            if "AAPL" in line:
                self.assertTrue(line.rstrip().endswith("1,500.00"),
                                f"value column should be right-aligned: {line!r}")

    def test_default_align_is_label_then_right(self):
        out = print_table(["a", "b"], [["xx", "yy"]])
        plain = ANSI_RE.sub("", out)
        rendered_data_line = [l for l in plain.splitlines() if "xx" in l][0]
        # 'xx' left-justified should come BEFORE 'yy' right-justified; 'yy' at end
        self.assertTrue(rendered_data_line.rstrip().endswith("yy"))

    def test_header_carries_bold_accent(self):
        out = print_table(["h1"], [["v1"]])
        # The header line should carry the BOLD + ACCENT (highlight) tokens
        header_line = [l for l in out.splitlines() if "h1" in l][0]
        self.assertIn(BOLD, header_line)
        self.assertIn(ACCENT, header_line)

    def test_title_renders_when_provided(self):
        out = print_table(["a"], [["x"]], title="positions")
        self.assertIn("positions", out)


class TestTabbedViewFallback(unittest.TestCase):
    """The interactive prompt_toolkit path needs a real TTY; the fallback
    must print every tab sequentially so `sciqnt degiro live | tee` and CI
    runs still surface the data. Pin that behavior."""

    def test_non_tty_prints_every_tab(self):
        buf = io.StringIO()
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.stdout", buf):
            si.isatty.return_value = False
            tabbed_view({
                "alpha": "ALPHA-BODY",
                "beta":  "BETA-BODY",
            }, title="test")
        out = buf.getvalue()
        for needle in ("test", "alpha", "ALPHA-BODY", "beta", "BETA-BODY"):
            self.assertIn(needle, out,
                          f"non-TTY fallback should print {needle!r}")

    def test_empty_tabs_is_noop(self):
        with mock.patch("sys.stdin") as si:
            si.isatty.return_value = False
            tabbed_view({})         # must not raise

    def test_interactive_false_forces_dump_even_with_tty_stdin(self):
        """`run_aggregated`/`--once` pass interactive=False — the dump must
        win even when stdin happens to be a TTY (the old single-stream check
        misrouted `sciqnt --once > file` into the full-screen app)."""
        buf = io.StringIO()
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.stdout", buf):
            si.isatty.return_value = True            # TTY stdin, captured stdout
            tabbed_view({"alpha": "ALPHA-BODY"}, title="t", interactive=False)
        self.assertIn("ALPHA-BODY", buf.getvalue())

    def test_auto_detect_requires_both_streams(self):
        """interactive=None: stdout NOT a TTY → dump, even with a TTY stdin."""
        buf = io.StringIO()
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.stdout", buf):
            si.isatty.return_value = True
            tabbed_view({"alpha": "ALPHA-BODY"})     # buf.isatty() is False
        self.assertIn("ALPHA-BODY", buf.getvalue())

    def test_dump_survives_a_failing_tab(self):
        """One lazy tab raising must degrade to '(tab failed: …)' and the
        remaining tabs must still print — mirrors the interactive path."""
        def boom():
            raise TypeError("nope")
        buf = io.StringIO()
        with mock.patch("sys.stdin") as si, \
             mock.patch("sys.stdout", buf):
            si.isatty.return_value = False
            tabbed_view({"bad": boom, "good": "GOOD-BODY"}, title="t")
        out = buf.getvalue()
        self.assertIn("(tab failed: TypeError: nope)", out)
        self.assertIn("GOOD-BODY", out)


class TestFormattersAndHelpers(unittest.TestCase):
    """The hoisted number formatters (one home in sq_tui; modules alias them)
    + the warning/clear-screen helpers."""

    def test_fmt_num(self):
        self.assertEqual(fmt_num(None), "—")
        self.assertEqual(fmt_num(""), "—")
        self.assertEqual(fmt_num(1234.5), "1,234.50")
        self.assertEqual(fmt_num("abc"), "abc")

    def test_fmt_signed(self):
        self.assertEqual(fmt_signed(None), "—")
        self.assertEqual(fmt_signed(3), "+3.00")
        self.assertEqual(fmt_signed(-1234.5), "-1,234.50")
        self.assertEqual(fmt_signed(0), "0.00")

    def test_fmt_pct(self):
        self.assertEqual(fmt_pct(None), "—")
        self.assertEqual(fmt_pct(0.0734), "+7.34%")     # fraction → ×100
        self.assertEqual(fmt_pct(12.5), "+12.50%")      # already percent
        self.assertEqual(fmt_pct(-0.5), "-50.00%")

    def test_warn_line_is_yellow_warning(self):
        line = warn_line("export is stale")
        self.assertIn("⚠", line)
        self.assertIn("export is stale", line)
        if YELLOW:                                      # plain under NO_COLOR
            self.assertTrue(line.startswith(YELLOW))

    def test_clear_screen_noop_when_not_tty(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            clear_screen()
        self.assertEqual(buf.getvalue(), "")


class TestClampScroll(unittest.TestCase):
    """Pure offset math behind tabbed_view's body scrolling."""

    def test_body_fits_clamps_to_zero(self):
        self.assertEqual(_clamp_scroll(5, 10, 20), 0)

    def test_clamps_to_max_offset(self):
        self.assertEqual(_clamp_scroll(99, 50, 20), 30)

    def test_negative_clamps_to_zero(self):
        self.assertEqual(_clamp_scroll(-3, 50, 20), 0)

    def test_in_range_passes_through(self):
        self.assertEqual(_clamp_scroll(7, 50, 20), 7)

    def test_degenerate_viewport(self):
        self.assertEqual(_clamp_scroll(100, 50, 0), 49)   # viewport floors at 1


if __name__ == "__main__":
    unittest.main()


class TestStreamsInteractive(unittest.TestCase):
    """The interactive-vs-fallback decision MUST test the REAL terminal
    stdout, not sys.stdout — the latter is routinely swapped to a capture
    buffer (quiet(), the home's progress capture). Regression for the
    2026-06-11 hang: at a real TTY with sys.stdout swapped, the home's
    menu took the numbered fallback, its menu text went into the capture,
    and the app blocked on an invisible input("Choice: ")."""

    class _Tty:
        def isatty(self):
            return True

    class _NotTty:
        def isatty(self):
            return False

    def test_swapped_sys_stdout_does_not_demote_a_real_tty(self):
        import io
        from unittest import mock
        with mock.patch.object(sq_tui, "_REAL_STDOUT", self._Tty()), \
             mock.patch.object(sq_tui.sys, "stdin", self._Tty()), \
             mock.patch.object(sq_tui.sys, "stdout", io.StringIO()):
            self.assertTrue(sq_tui._streams_interactive())

    def test_piped_real_stdout_is_non_interactive(self):
        from unittest import mock
        with mock.patch.object(sq_tui, "_REAL_STDOUT", self._NotTty()), \
             mock.patch.object(sq_tui.sys, "stdin", self._Tty()):
            self.assertFalse(sq_tui._streams_interactive())

    def test_non_tty_stdin_is_non_interactive(self):
        from unittest import mock
        with mock.patch.object(sq_tui, "_REAL_STDOUT", self._Tty()), \
             mock.patch.object(sq_tui.sys, "stdin", self._NotTty()):
            self.assertFalse(sq_tui._streams_interactive())


class TestRenderChart(unittest.TestCase):
    """Braille-canvas charts — pure display math (floats fine here;
    money stays Decimal everywhere else)."""

    @staticmethod
    def _braille_chars(text):
        return [ch for ch in text if 0x2800 <= ord(ch) <= 0x28FF]

    def test_too_few_points_returns_empty(self):
        self.assertEqual(sq_tui.render_chart([1]), "")
        self.assertEqual(sq_tui.render_pl_bars([5]), "")

    def test_line_is_braille_with_axis_and_labels(self):
        out = sq_tui.render_chart([0, 50, 100], height=4, width=20)
        plain = ANSI_RE.sub("", out)
        self.assertTrue(self._braille_chars(plain))      # a real stroke
        self.assertIn("┤", plain)                        # y-axis ticks
        self.assertIn("╰", plain)                        # baseline
        self.assertIn("100", plain)                      # max label
        self.assertIn("0", plain)                        # min label

    def test_rising_series_ends_top_right(self):
        out = ANSI_RE.sub("", sq_tui.render_chart([0, 100], height=4,
                                                  width=20))
        rows = [l.split("┤")[-1].split("│")[-1] for l in out.splitlines()]
        # ink in the TOP chart row near the right edge, none at its left
        top = rows[0]
        self.assertTrue(self._braille_chars(top[-3:]))
        self.assertFalse(self._braille_chars(top[:3]))

    def test_x_axis_tick_labels(self):
        out = ANSI_RE.sub("", sq_tui.render_chart(
            [1, 2], height=2, width=24, x_left="01 Jan", x_right="31 Dec"))
        last = out.splitlines()[-1]
        self.assertIn("01 Jan", last)
        self.assertIn("31 Dec", last)

    def test_flat_series_still_draws(self):
        out = ANSI_RE.sub("", sq_tui.render_chart([5, 5, 5], height=3,
                                                  width=12))
        self.assertTrue(self._braille_chars(out))

    def test_pl_bars_diverge_around_zero_axis(self):
        out = sq_tui.render_pl_bars([100, -50], height=4, width=8)
        plain = ANSI_RE.sub("", out)
        lines = plain.splitlines()
        self.assertEqual(len(lines), 4)
        # gains ink above the axis (top half), losses below (bottom half)
        self.assertTrue(self._braille_chars(lines[0] + lines[1]))
        self.assertTrue(self._braille_chars(lines[2] + lines[3]))
        # sign colouring present in the coloured output
        self.assertIn("\033[32m", out)
        self.assertIn("\033[31m", out)
        # zero + peak labels on the gutter
        self.assertIn("0", plain)
        self.assertIn("+100", plain)

    def test_pl_bars_resample_sums_buckets(self):
        # +1 and -1 in the same bucket cancel (sum, not mean of
        # magnitudes) — flows aggregate, levels average.
        out = sq_tui.render_pl_bars([1, -1] * 50, height=4, width=2)
        # every bucket nets to zero → dim axis dots only, no gain/loss ink
        self.assertNotIn("\033[32m", out)
        self.assertNotIn("\033[31m", out)


class TestChartFlatlineAndSigns(unittest.TestCase):
    @staticmethod
    def _braille(text):
        return [ch for ch in text if 0x2800 <= ord(ch) <= 0x28FF]

    def test_flatline_guard_no_noise_amplification(self):
        # A dormant €0.01 account with microscopic FX wobble must render
        # ~flat, not full-height bars (live bug 2026-06-12). The stroke
        # must stay within the middle rows — no ink in the top row.
        vals = [0.0100, 0.0101, 0.0099, 0.0100] * 8
        out = ANSI_RE.sub("", sq_tui.render_chart(vals, height=6, width=30))
        rows = [l.split("┤")[-1].split("│")[-1] for l in out.splitlines()]
        self.assertFalse(self._braille(rows[0]))         # top row clean
        self.assertFalse(self._braille(rows[-2]))        # bottom chart row clean
        # labels are 2dp, not three identical "0"s
        self.assertIn("0.01", out)

    def test_zero_axis_included_and_drawn(self):
        # All-positive series with zero_axis: the domain must reach 0
        # (bottom label) and a dotted zero line must add ink beyond the
        # stroke itself.
        out = ANSI_RE.sub("", sq_tui.render_chart([5, 6, 7], height=4,
                                                  width=20, zero_axis=True))
        self.assertIn("0.00", out)                       # domain reaches 0
        plain = sq_tui.render_chart([5, 6, 7], height=4, width=20)
        self.assertGreater(len(self._braille(ANSI_RE.sub("", out))),
                           len(self._braille(ANSI_RE.sub("", plain))))

    def test_sign_colored_stroke(self):
        out = sq_tui.render_chart([-10, -2, 4, 10], height=4, width=20,
                                  zero_axis=True, sign_colors=True)
        self.assertIn("\033[32m", out)                   # green segment
        self.assertIn("\033[31m", out)                   # red segment


class TestChartDomainTightness(unittest.TestCase):
    @staticmethod
    def _plain(text):
        return ANSI_RE.sub("", text)

    def test_real_shape_not_flattened_by_guard(self):
        # 12k portfolio moving $35 is a REAL shape: the domain must hug
        # the data (calibration bug 2026-06-12 padded ±5%).
        out = self._plain(sq_tui.render_chart([12216, 12251, 12230],
                                              height=4, width=20))
        labels = [l.split("┤")[0].strip() for l in out.splitlines()
                  if "┤" in l]
        # domain hugs the data: every label within [12,216, 12,251] —
        # the old guard padded to ~11,6xx/12,8xx
        for t in labels:
            v = float(t.replace(",", ""))
            self.assertGreaterEqual(v, 12216 - 1)
            self.assertLessEqual(v, 12251 + 1)


class TestFilterIndices(unittest.TestCase):
    """The / type-to-filter's pure matcher (skills-find style)."""

    ITEMS = [
        ("pricing", sq_tui.SEP),
        ("tiingo    Official EOD prices", ("tiingo", "w")),
        ("yahoo     Yahoo Finance quotes", ("yahoo", "w")),
        ("news & socials", sq_tui.SEP),
        ("finnhub   Official company news", ("finnhub", "w")),
    ]

    def test_empty_query_shows_everything(self):
        self.assertEqual(sq_tui._filter_indices(self.ITEMS, ""),
                         [0, 1, 2, 3, 4])

    def test_match_is_case_insensitive_over_visible_text(self):
        self.assertEqual(sq_tui._filter_indices(self.ITEMS, "OFFICIAL"),
                         [1, 4])

    def test_sep_headers_drop_out_of_filtered_results(self):
        out = sq_tui._filter_indices(self.ITEMS, "o")
        self.assertNotIn(0, out)
        self.assertNotIn(3, out)

    def test_no_match_is_empty(self):
        self.assertEqual(sq_tui._filter_indices(self.ITEMS, "zzz"), [])
