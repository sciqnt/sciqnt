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


class TestPlatformContract(unittest.TestCase):
    def test_every_bundle_honours_the_wrapper_contract(self):
        """EVERY modules/sq-* bundle must ship an executable bin/sq-<name>
        that answers --describe (one non-empty line) and --commands (≥1
        tab-separated `name<TAB>description` line). This is the platform↔
        bundle contract — a bundle that drops it silently disappears from
        the dispatcher, so the suite guards it for ALL bundles, not just
        the hand-picked ones below."""
        bundle_dirs = sorted(p for p in (ROOT / "modules").glob("sq-*")
                             if p.is_dir())
        self.assertTrue(bundle_dirs, "no modules/sq-* bundles found")
        for bdir in bundle_dirs:
            name = bdir.name                      # e.g. sq-degiro
            with self.subTest(bundle=name):
                wrapper = bdir / "bin" / name
                self.assertTrue(wrapper.is_file(),
                                f"{name} has no bin/{name} wrapper")
                self.assertTrue(os.access(wrapper, os.X_OK),
                                f"bin/{name} is not executable (chmod +x)")
                describe = _run_wrapper(wrapper, "--describe").strip()
                self.assertTrue(describe,
                                f"{name} --describe printed nothing")
                cmd_lines = [ln for ln in
                             _run_wrapper(wrapper, "--commands").splitlines()
                             if ln.strip()]
                self.assertTrue(cmd_lines,
                                f"{name} --commands printed no commands")
                for ln in cmd_lines:
                    self.assertIn("\t", ln,
                                  f"{name} --commands line not "
                                  f"tab-separated: {ln!r}")

    def test_discover_finds_known_bundles(self):
        bundles = dict((n, (w, d)) for n, w, d in discover_bundles(ROOT))
        for must_have in ("degiro", "config"):
            self.assertIn(must_have, bundles,
                          f"sq-{must_have} wrapper not discovered "
                          f"— does its bin/sq-{must_have} exist + is +x?")
            wrapper, desc = bundles[must_have]
            self.assertTrue(desc, f"sq-{must_have} --describe must print a non-empty summary")

    def test_degiro_wrapper_advertises_commands(self):
        bundles = dict((n, w) for n, w, _ in discover_bundles(ROOT))
        rows = commands_of(bundles["degiro"])
        # 3-tuples: (cmd, description, argspec). argspec "" = runs bare;
        # non-empty = the module browser prompts for arguments first.
        self.assertTrue(all(len(r) == 3 for r in rows))
        cmds = {c: d for c, d, _a in rows}
        specs = {c: a for c, _d, a in rows}
        self.assertEqual(specs["setup"], "")               # argless commands stay bare
        self.assertIn("probe", specs["doctor"])            # doctor declares its args
        # Main-flow commands the dispatcher must surface. `probe` and
        # `fix-totp` are intentionally hidden under `doctor` — see the
        # wrapper script for the rationale (diagnostic, not main-flow).
        for must_have in ("setup", "live", "doctor"):
            self.assertIn(must_have, cmds,
                          f"sq-degiro --commands missing '{must_have}'")
        # Diagnostics should NOT be in the top-level list anymore.
        for must_not in ("probe", "fix-totp"):
            self.assertNotIn(
                must_not, cmds,
                f"sq-degiro --commands should hide '{must_not}' (it lives under `doctor`)",
            )
        # All advertised commands have descriptions
        for cmd, desc in cmds.items():
            self.assertTrue(desc, f"sq-degiro command '{cmd}' has no description")


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


class TestGroupedDiscovery(unittest.TestCase):
    """The module browser nests by each bundle's self-declared --kind, so the
    list scales (brokers / market data / tools) instead of one flat dump."""

    def test_kinds_of_reads_wrapper(self):
        bundles = dict((n, w) for n, w, _ in discover_bundles(ROOT))
        self.assertEqual(sq_platform.kinds_of(bundles["degiro"]), ["broker"])
        self.assertEqual(sq_platform.kinds_of(bundles["fx-ecb"]), ["fx"])
        self.assertEqual(sq_platform.kinds_of(bundles["config"]), ["tools"])
        # multi-category bundles declare comma-separated tokens
        self.assertEqual(sq_platform.kinds_of(bundles["robinhood"]),
                         ["broker", "crypto"])
        self.assertEqual(sq_platform.kinds_of(bundles["yahoo"]),
                         ["pricing", "fx"])

    def test_legacy_market_data_token_maps_to_pricing(self):
        with mock.patch.object(sq_platform, "_run",
                               return_value="market-data\n"):
            self.assertEqual(sq_platform.kinds_of("/w"), ["pricing"])

    def test_grouped_buckets_and_order(self):
        groups = sq_platform.discover_grouped(ROOT)
        labels = [lbl for _, lbl, _ in groups]
        self.assertEqual(labels[0], "Brokers")
        self.assertIn("Crypto", labels)
        self.assertIn("Prediction markets", labels)
        self.assertIn("Market data · pricing", labels)
        self.assertIn("Market data · news & socials", labels)
        self.assertIn("Tools & settings", labels)
        by_kind = {k: {n for n, _, _ in mods} for k, _, mods in groups}
        # connectors split by market; multi-membership works
        self.assertEqual(by_kind["broker"], {"degiro", "robinhood"})
        self.assertEqual(by_kind["prediction-market"],
                         {"kalshi", "polymarket"})
        self.assertIn("robinhood", by_kind["crypto"])     # broker AND crypto
        self.assertIn("yahoo", by_kind["pricing"])
        self.assertIn("yahoo", by_kind["fx"])             # pricing AND fx

    def test_unknown_kind_falls_into_other(self):
        # A wrapper that declares an unmapped kind lands in a trailing Other.
        with mock.patch.object(sq_platform, "discover_bundles",
                               return_value=[("widget", "/w", "d")]), \
             mock.patch.object(sq_platform, "kinds_of",
                               return_value=["gizmo"]):
            groups = sq_platform.discover_grouped(ROOT)
        self.assertEqual(groups[-1][1], "Other")
        self.assertEqual(groups[-1][2], [("widget", "/w", "d")])


if __name__ == "__main__":
    unittest.main()


class TestDiscoverTree(unittest.TestCase):
    """The browser's FOLDER tree: Portfolio connectors (brokers/crypto/
    prediction markets) and Market data (by data type) as real
    navigation levels; Tools is leaf-direct (owner spec 2026-06-12)."""

    def test_top_level_folders(self):
        tree = sq_platform.discover_tree(ROOT)
        labels = [l for _, l, _, _ in tree]
        self.assertEqual(labels, ["Portfolio connectors", "Market data",
                                  "Tools & settings"])

    def test_portfolio_subfolders(self):
        tree = sq_platform.discover_tree(ROOT)
        pf = next(c for k, _, _, c in tree if k == "portfolio")
        self.assertEqual([sl for _, sl, _ in pf],
                         ["Brokers", "Crypto", "Prediction markets"])
        brokers = next(m for _, sl, m in pf if sl == "Brokers")
        self.assertEqual({n for n, _, _ in brokers},
                         {"degiro", "robinhood"})
        crypto = {n for _, sl, m in pf if sl == "Crypto" for n, _, _ in m}
        self.assertIn("robinhood", crypto)       # multi-membership intact

    def test_market_data_subfolders(self):
        tree = sq_platform.discover_tree(ROOT)
        md = next(c for k, _, _, c in tree if k == "market-data")
        self.assertEqual([sl for _, sl, _ in md],
                         ["Pricing", "FX", "News & socials", "Reference",
                          "Filings & fundamentals"])
        fx = {n for _, sl, m in md if sl == "FX" for n, _, _ in m}
        self.assertEqual(fx, {"fx-ecb", "yahoo"})

    def test_tools_is_leaf_direct(self):
        tree = sq_platform.discover_tree(ROOT)
        tools = next(c for k, _, _, c in tree if k == "tools")
        self.assertEqual(len(tools), 2)          # tools + demo kinds
        self.assertTrue(all(sub is None for _, sub, _ in tools))

    def test_summaries_are_counts_only(self):
        tree = sq_platform.discover_tree(ROOT)
        summaries = {k: smry for k, _, smry, _ in tree}
        # counts only, distinct modules (double-listings counted once),
        # NO enumeration of contents (simplicity — owner call 2026-06-12)
        self.assertEqual(summaries["portfolio"], "4 modules")
        self.assertEqual(summaries["market-data"], "8 modules")
        self.assertEqual(summaries["tools"], "2 modules")  # config + demo


class TestFindModules(unittest.TestCase):
    """`sciqnt modules find` — the non-interactive search surface."""

    def test_matches_name_description_and_category(self):
        import contextlib, io
        for q, expect in (("news", "finnhub"), ("yahoo", "news-rss"),
                          ("reference", "firds")):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = sq_platform.find_modules(ROOT, q)
            self.assertEqual(rc, 0, q)
            self.assertIn(expect, buf.getvalue())

    def test_no_match_exit_code(self):
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sq_platform.find_modules(ROOT, "zzzz"), 1)

    def test_multi_category_badges(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            sq_platform.find_modules(ROOT, "yahoo")
        line = next(l for l in buf.getvalue().splitlines()
                    if l.startswith("yahoo"))
        self.assertIn("Pricing", line)
        self.assertIn("FX", line)
