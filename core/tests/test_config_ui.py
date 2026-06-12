"""sq_config_ui — the ONE full-screen settings experience, tested pure.

select_screen / text_input_screen are mocked (scripted picks) — no
prompt_toolkit, no TTY. SQ_CONFIG_PATH points at a tmp dir so the user's real
config is never touched. The CLI entry points (set.py) run as subprocesses to
exercise the real script surface: two-arg writes, invalid-value exit, and the
piped-bare → plain-dump degradation.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))                          # core/
sys.path.insert(0, str(ROOT / "modules" / "sq-config" / "src"))

import sq_config                                  # noqa: E402
import sq_config_ui                               # noqa: E402
import sq_tui                                     # noqa: E402


def _flat(label):
    """Row label → plain text (labels may be rich (style, text) fragments)."""
    return label if isinstance(label, str) else "".join(t for _, t in label)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-config-ui-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev


class TestRows(Base):
    def test_rows_show_current_values(self):
        sq_config.set("display_currency", "EUR")
        items, _ = sq_config_ui.build_settings_items(
            sq_config.schema(), sq_config.all())
        by_key = {p: _flat(l) for l, p in items}
        self.assertIn("EUR", by_key["display_currency"])
        self.assertIn("FIFO", by_key["cost_basis_method"])     # schema default
        self.assertIn("false", by_key["annualize_sub_year_returns"])  # bool cell

    def test_not_yet_wired_rows_marked_soon_and_dim(self):
        items, styles = sq_config_ui.build_settings_items(
            sq_config.schema(), sq_config.materialise())
        keys = [p for _, p in items]
        by_key = {p: _flat(l) for l, p in items}
        for k in ("fees_in_cost_basis", "tax_jurisdiction", "tax_year_start"):
            self.assertIn("(soon)", by_key[k])
            self.assertEqual(styles[keys.index(k)], "dim")
        self.assertNotIn("(soon)", by_key["display_currency"])
        self.assertIsNone(styles[keys.index("display_currency")])

    def test_help_lives_in_overlay_not_rows(self):
        schema = sq_config.schema()
        items, _ = sq_config_ui.build_settings_items(schema, sq_config.all())
        row = _flat(dict((p, l) for l, p in items)["display_currency"])
        self.assertNotIn("Currency for cross-asset", row)     # not in the row
        overlay = sq_config_ui.help_text(schema)
        self.assertIn("Currency for cross-asset", overlay)    # in ? overlay
        self.assertIn("display_currency", overlay)
        self.assertIn("config file:", overlay)

    def test_enum_options_preselect_current_with_descriptions(self):
        s = next(x for x in sq_config.schema()
                 if x.key == "cost_basis_method")
        opts = sq_config_ui.enum_options(s, "LIFO")
        texts = {p: _flat(l) for l, p in opts}
        self.assertIn("(current)", texts["LIFO"])
        self.assertNotIn("(current)", texts["FIFO"])
        self.assertIn("first in, first out", texts["FIFO"])   # implied by help

    def test_parse_bool_tolerant(self):
        for truthy in (True, "true", "TRUE", "yes", "1", "on"):
            self.assertTrue(sq_config_ui.parse_bool(truthy))
        for falsy in (False, "false", "no", "0", "off", "garbage", None):
            self.assertFalse(sq_config_ui.parse_bool(falsy))


class TestLoop(Base):
    """Drive run_settings with scripted select/text stubs — pure logic."""

    def _run(self, picks, texts=()):
        sel, txt = iter(picks), iter(texts)
        with mock.patch.object(sq_config_ui.sq_tui, "select_screen",
                               side_effect=lambda *a, **k: next(sel)), \
             mock.patch.object(sq_config_ui.sq_tui, "text_input_screen",
                               side_effect=lambda *a, **k: next(txt)):
            sq_config_ui.run_settings(make_header=lambda *c: "")

    def test_enum_edit_writes_through_sq_config(self):
        # pick the setting → pick LIFO on the second screen → esc out
        self._run(["cost_basis_method", "LIFO", sq_tui.BACK])
        self.assertEqual(sq_config.get("cost_basis_method"), "LIFO")

    def test_enum_esc_cancels_without_write(self):
        self._run(["cost_basis_method", sq_tui.BACK, sq_tui.BACK])
        self.assertEqual(sq_config.get("cost_basis_method"), "FIFO")

    def test_bool_toggles_immediately_no_second_screen(self):
        # selecting the bool row flips it — NO second select_screen call
        self._run(["annualize_sub_year_returns", sq_tui.BACK])
        self.assertIs(sq_config.get("annualize_sub_year_returns"), True)
        self._run(["annualize_sub_year_returns", sq_tui.BACK])   # …and back
        self.assertIs(sq_config.get("annualize_sub_year_returns"), False)

    def test_str_edit_prefills_and_saves(self):
        self._run(["benchmark", sq_tui.BACK], texts=["CSPX.AS"])
        self.assertEqual(sq_config.get("benchmark"), "CSPX.AS")

    def test_str_empty_cancels(self):
        before = sq_config.get("benchmark")
        self._run(["benchmark", sq_tui.BACK], texts=[""])
        self.assertEqual(sq_config.get("benchmark"), before)


class TestHomeWiring(Base):
    def test_home_settings_action_uses_the_same_loop(self):
        """The home's Settings entry must open the bundle loop in-process,
        wrapped in the home chrome — one experience from home and CLI."""
        from sq_platform import home
        with mock.patch.object(sq_config_ui, "run_settings") as rs:
            home._settings_flow(ROOT)
        rs.assert_called_once()
        hdr = rs.call_args.kwargs["make_header"]()           # home chrome
        self.assertIn("Menu › Settings", sq_tui.ANSI_RE.sub("", hdr))


class TestCliEntry(Base):
    """The real script surface (subprocess) — scripts/agents must keep a
    stable non-interactive path."""
    SET = ROOT / "modules" / "sq-config" / "set.py"

    def _run(self, *args, stdin=subprocess.DEVNULL):
        return subprocess.run([sys.executable, str(self.SET), *args],
                              capture_output=True, text=True,
                              stdin=stdin, env=dict(os.environ))

    def test_two_arg_set_unchanged(self):
        r = self._run("display_currency", "EUR")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("display_currency", r.stdout)
        self.assertEqual(sq_config.get("display_currency"), "EUR")

    def test_two_arg_invalid_value_never_written(self):
        r = self._run("cost_basis_method", "WACKY")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(sq_config.get("cost_basis_method"), "FIFO")

    def test_bare_piped_prints_dump_not_menu(self):
        r = self._run()                       # no args, piped streams
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("display_currency", r.stdout)     # the plain dump
        self.assertNotIn("Choice:", r.stdout)           # no menu loop


if __name__ == "__main__":
    unittest.main()
