"""sq_config — user-level config substrate tests.

SQ_CONFIG_PATH overrides the on-disk location so tests never touch the
user's real ~/.config/sciqnt/config.json.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # core/

import sq_config  # noqa: E402


class TestPzConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-config-test-")
        self._prev_env = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev_env is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev_env

    def test_get_returns_default_when_unset(self):
        self.assertIsNone(sq_config.get("nope"))
        self.assertEqual(sq_config.get("nope", "fallback"), "fallback")

    def test_all_returns_empty_when_no_file(self):
        self.assertEqual(sq_config.all(), {})

    def test_set_then_get_roundtrip(self):
        sq_config.set("display_currency", "EUR")
        self.assertEqual(sq_config.get("display_currency"), "EUR")
        # file actually persisted
        self.assertTrue(sq_config.path().is_file())

    def test_set_creates_parent_directory(self):
        # config.json sits inside a freshly-allocated tmp dir; the parent
        # may exist but the immediate parent of CONFIG_PATH must be created
        # if it doesn't (e.g. ~/.config/sciqnt/ on first run).
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "nested" / "x.json")
        sq_config.set("k", "v")
        self.assertTrue(sq_config.path().is_file())

    def test_display_currency_default_fallback(self):
        self.assertEqual(sq_config.display_currency("EUR"), "EUR")
        self.assertEqual(sq_config.display_currency(), "USD")  # documented default

    def test_display_currency_reads_set_value(self):
        sq_config.set(sq_config.DISPLAY_CURRENCY, "GBP")
        self.assertEqual(sq_config.display_currency(), "GBP")
        # explicit fallback ignored once a value is set
        self.assertEqual(sq_config.display_currency("EUR"), "GBP")

    def test_corrupt_file_returns_empty_then_overwrites(self):
        sq_config.path().parent.mkdir(parents=True, exist_ok=True)
        sq_config.path().write_text("not-json{")
        self.assertEqual(sq_config.all(), {})       # graceful: no crash
        sq_config.set("k", "v")
        self.assertEqual(sq_config.get("k"), "v")   # overwrites clean

    # ── schema / defaults registry ─────────────────────────────────────────
    def test_get_falls_back_to_schema_default(self):
        # No file, no explicit default → the schema default for a known key.
        self.assertEqual(sq_config.get("cost_basis_method"), "FIFO")
        self.assertEqual(sq_config.get("display_currency"), "USD")

    def test_schema_keys_unique_and_have_defaults(self):
        keys = [s.key for s in sq_config.schema()]
        self.assertEqual(len(keys), len(set(keys)))     # no dupes
        for s in sq_config.schema():
            self.assertIsNotNone(s.default)
            if s.type == "enum":
                self.assertIn(s.default, s.allowed)     # default is valid

    def test_materialise_creates_file_with_all_defaults(self):
        self.assertFalse(sq_config.path().is_file())
        data = sq_config.materialise()
        self.assertTrue(sq_config.path().is_file())
        for s in sq_config.schema():
            self.assertEqual(data[s.key], s.default)

    def test_materialise_is_non_destructive(self):
        sq_config.set("display_currency", "GBP")        # user value
        sq_config.materialise()
        # user value preserved; missing keys filled with defaults
        self.assertEqual(sq_config.get("display_currency"), "GBP")
        self.assertEqual(sq_config.get("cost_basis_method"), "FIFO")

    def test_materialise_idempotent(self):
        first = sq_config.materialise()
        second = sq_config.materialise()
        self.assertEqual(first, second)

    def test_set_validates_enum(self):
        with self.assertRaises(ValueError):
            sq_config.set("cost_basis_method", "WACKY")
        sq_config.set("cost_basis_method", "LIFO")      # valid: no raise
        self.assertEqual(sq_config.cost_basis_method(), "LIFO")

    def test_unknown_key_passes_through(self):
        # forward-compatible: ad-hoc keys aren't rejected
        sq_config.set("some_future_key", 42)
        self.assertEqual(sq_config.get("some_future_key"), 42)

    def test_bool_setting_coerces_string_forms(self):
        sq_config.set("annualize_sub_year_returns", "false")
        self.assertIs(sq_config.get("annualize_sub_year_returns"), False)
        sq_config.set("annualize_sub_year_returns", "yes")
        self.assertIs(sq_config.get("annualize_sub_year_returns"), True)
        with self.assertRaises(ValueError):
            sq_config.set("annualize_sub_year_returns", "maybe")

    def test_research_settings_declared(self):
        keys = {s.key for s in sq_config.schema()}
        # the grounded forward-looking settings from the research synthesis
        for k in ("tax_jurisdiction", "tax_year_start",
                  "performance_return_method", "annualize_sub_year_returns",
                  "fees_in_cost_basis"):
            self.assertIn(k, keys)
        # mvp flag honestly separates wired from declared-but-not-yet-honoured
        by_key = {s.key: s for s in sq_config.schema()}
        self.assertTrue(by_key["cost_basis_method"].mvp)            # wired
        self.assertTrue(by_key["performance_return_method"].mvp)    # wired
        self.assertTrue(by_key["annualize_sub_year_returns"].mvp)   # wired
        self.assertFalse(by_key["tax_jurisdiction"].mvp)            # declared only
        self.assertFalse(by_key["fees_in_cost_basis"].mvp)          # declared only


if __name__ == "__main__":
    unittest.main()
