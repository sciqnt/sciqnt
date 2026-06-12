"""The agent-summon + data-surface contract.

Three pillars guarded here:
1. DECLARE → DERIVE: a screen's reproduce-command derives from TAB_SURFACES
   (one declaration) — never hand-branched per call site.
2. FACTS, NOT CHOREOGRAPHY: the summon seed carries state (where / screen /
   command / why) and no stage directions; durable knowledge lives in the
   installed skills, and the skills teach DISCOVERY (`sciqnt --help`) rather
   than enumerate a surface that would drift.
3. DATA-FIRST: every reproducible view also has a structured `--json` form
   (versioned schema, Decimal-as-string) — the TUI is one renderer over it.
"""
import json
import subprocess
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_platform.aggregated import (  # noqa: E402
    HISTORY_RANGES, HISTORY_SCHEMA, PORTFOLIO_SCHEMA, TAB_SURFACES,
    _json_scalar, normalize_history_spec, view_command,
)
from sq_platform.home import (  # noqa: E402
    SCREEN_FILE, summon_prompt, summon_seed,
)
import sq_skills  # noqa: E402

ROOT = HERE.parents[1]


class TestViewCommandDerives(unittest.TestCase):
    def test_home_is_once(self):
        self.assertEqual(view_command(), "sciqnt --once")

    def test_undeclared_tab_gets_the_default_surface(self):
        # A NEW tab needs no wiring: absent from TAB_SURFACES → --tab form.
        self.assertEqual(view_command(tab="dividends"),
                         "sciqnt --once --tab dividends")

    def test_declared_tab_uses_its_own_surface(self):
        self.assertIn("history", TAB_SURFACES)
        self.assertEqual(view_command(tab="history", sub="1Y"),
                         "sciqnt --history 1Y")
        self.assertEqual(view_command(tab="history"), "sciqnt --history YTD")

    def test_account_appended_everywhere(self):
        self.assertEqual(
            view_command(account="degiro:Alice", tab="history", sub="All"),
            "sciqnt --history All --account degiro:Alice")
        self.assertEqual(view_command(account="degiro:Alice"),
                         "sciqnt --once --account degiro:Alice")

    def test_account_label_is_shell_safe(self):
        cmd = view_command(account="weird name; rm -rf /")
        self.assertIn("'weird name; rm -rf /'", cmd)


class TestSummonSeed(unittest.TestCase):
    """What the user SEES typed into the agent: one clean pointer line —
    never the lecture (that's the task file's job)."""

    def test_one_short_line_with_location_and_pointer(self):
        seed = summon_seed({"where": "portfolio › exposure"})
        self.assertNotIn("\n", seed)
        self.assertLess(len(seed), 100)
        self.assertIn("portfolio › exposure", seed)
        self.assertIn(".sciqnt-agent-task.md", seed)

    def test_seed_carries_no_capability_lecture(self):
        seed = summon_seed({"where": "home"})
        for lecture in ("authoritative", "--help", "skills", "installed"):
            self.assertNotIn(lecture, seed.lower())


class TestSummonFacts(unittest.TestCase):
    def test_facts_present_no_choreography(self):
        facts = {"where": "portfolio › degiro:Alice › history › YTD",
                 "command": "sciqnt --history YTD --account degiro:Alice",
                 "screen": "  net worth (EUR) │ daily\n  …"}
        p = summon_prompt(facts)
        self.assertIn(facts["where"], p)
        self.assertIn(facts["command"], p)
        self.assertIn(SCREEN_FILE, p)
        # why-summoned fact (no request typed → agent speaks first)
        self.assertIn("without typing a request", p)
        # No stage directions — the agent decides its own behaviour.
        for directive in ("Run it first", "a few sentences", "then ask"):
            self.assertNotIn(directive, p)
        # Capability facts point at skills + the self-describing CLI.
        self.assertIn("sciqnt --help", p)
        self.assertIn("sq-portfolio", p)
        self.assertIn("sq-connectors", p)

    def test_warnings_replace_the_no_request_fact(self):
        p = summon_prompt({"where": "home", "command": "sciqnt --once",
                           "warnings": ["degiro:X needs you to reconnect"]})
        self.assertIn("degiro:X needs you to reconnect", p)
        self.assertNotIn("without typing a request", p)

    def test_bare_summon_still_coherent(self):
        p = summon_prompt(None)
        self.assertIn("sciqnt --help", p)


class TestHistorySpec(unittest.TestCase):
    def test_int_and_int_string_are_days(self):
        self.assertEqual(normalize_history_spec(30), 30)
        self.assertEqual(normalize_history_spec("90"), 90)

    def test_every_tui_range_is_reachable_any_case(self):
        for r in HISTORY_RANGES:
            self.assertEqual(normalize_history_spec(r.lower()), r)
            self.assertEqual(normalize_history_spec(r.upper()), r)

    def test_garbage_is_none(self):
        self.assertIsNone(normalize_history_spec("fortnight"))


class TestDataSurface(unittest.TestCase):
    def test_json_scalar_money_is_string_never_float(self):
        s = json.dumps({"v": Decimal("10.50"), "d": date(2026, 6, 12)},
                       default=_json_scalar)
        self.assertIn('"10.50"', s)
        self.assertIn('"2026-06-12"', s)

    def test_schemas_are_versioned(self):
        self.assertRegex(PORTFOLIO_SCHEMA, r"^sciqnt\..+/v\d+$")
        self.assertRegex(HISTORY_SCHEMA, r"^sciqnt\..+/v\d+$")


class TestSelfDescribingCLI(unittest.TestCase):
    def test_help_documents_every_surface(self):
        """`sciqnt --help` is the discovery contract the skill points at —
        a surface missing from it is invisible to every agent."""
        out = subprocess.run(
            [str(ROOT / ".venv/bin/python"),
             str(ROOT / "bin/sciqnt-aggregated.py"), "--help"],
            capture_output=True, text=True, timeout=30).stdout
        for flag in ("--once", "--account", "--tab", "--history",
                     "--asof", "--fresh", "--json"):
            self.assertIn(flag, out, f"--help misses {flag}")
        for r in HISTORY_RANGES:
            self.assertIn(r, out, f"--help misses history range {r}")


class TestRenderHistoryAdapter(unittest.TestCase):
    """sq_tui.render_history consumes the sciqnt.history/v1 DATA surface —
    the TUI chart is one renderer over the same payload a web chart gets."""

    def _payload(self, n=5):
        return {"schema": "sciqnt.history/v1", "range": "YTD",
                "display_currency": "EUR",
                "rows": [{"date": f"2026-01-0{i+1}",
                          "net_worth": str(10000 + i * 50),
                          "holdings": str(9000 + i * 50),
                          "net_cash": "1000", "flows": "0",
                          "pl_period": str(50 if i % 2 else -25)}
                         for i in range(n)],
                "covers": ["x"], "skipped": []}

    def test_renders_from_wire_form(self):
        import sq_tui
        out = sq_tui.render_history(self._payload())
        self.assertIn("net worth (EUR) │ daily", sq_tui.ANSI_RE.sub("", out))
        self.assertIn("P/L per period", sq_tui.ANSI_RE.sub("", out))
        self.assertIn("2026-01-01", out)        # x-axis labels from the data

    def test_intraday_range_uses_time_labels(self):
        import sq_tui
        pl = self._payload()
        pl["range"] = "1D"
        pl["rows"] = [{**r, "date": f"2026-06-12T1{i}:30:00+00:00"}
                      for i, r in enumerate(pl["rows"])]
        out = sq_tui.ANSI_RE.sub("", sq_tui.render_history(pl))
        self.assertIn("5-minute bars", out)
        self.assertIn("10:30", out)

    def test_too_short_is_empty(self):
        import sq_tui
        pl = self._payload(1)
        self.assertEqual(sq_tui.render_history(pl), "")


class TestTabRegistry(unittest.TestCase):
    """register_tab is the bundle-contribution seam: one declaration,
    surface + summon command derive."""

    def tearDown(self):
        from sq_platform import aggregated as ag
        ag.TAB_REGISTRY[:] = [(k, b) for k, b in ag.TAB_REGISTRY
                              if k != "divs"]
        ag.TAB_SURFACES.pop("divs", None)

    def test_register_declares_surface_and_derives_command(self):
        from sq_platform import aggregated as ag
        ag.register_tab("divs", lambda ctx: "  body",
                        surface=lambda sub: "--divs")
        self.assertEqual(ag.view_command(tab="divs"), "sciqnt --divs")

    def test_reregister_replaces_not_duplicates(self):
        from sq_platform import aggregated as ag
        ag.register_tab("divs", lambda ctx: "a")
        ag.register_tab("divs", lambda ctx: "b")
        self.assertEqual([k for k, _ in ag.TAB_REGISTRY].count("divs"), 1)


class TestInsightsPushChannel(unittest.TestCase):
    """The agent → app channel: append-only, local, text-only."""

    def setUp(self):
        import os, tempfile
        self.tmp = tempfile.mktemp(suffix=".jsonl")
        os.environ["SQ_INSIGHTS_PATH"] = self.tmp

    def tearDown(self):
        import os
        os.environ.pop("SQ_INSIGHTS_PATH", None)
        Path(self.tmp).unlink(missing_ok=True)

    def test_add_surface_seen_clear_lifecycle(self):
        from sq_platform import insights
        r = insights.add("IB01 drove the whole YTD move",
                         ref="sciqnt --history YTD")
        self.assertEqual([i["id"] for i in insights.current(unseen_only=True)],
                         [r["id"]])
        insights.mark_seen([r["id"]])
        self.assertEqual(insights.current(unseen_only=True), [])
        self.assertEqual(len(insights.current()), 1)   # seen ≠ gone
        insights.clear()
        self.assertEqual(insights.current(), [])

    def test_torn_line_never_poisons_the_rest(self):
        from sq_platform import insights
        insights.add("good one")
        with open(self.tmp, "a") as f:
            f.write("{torn json\n")
        insights.add("after the tear")
        self.assertEqual(len(insights.current()), 2)


class TestPerTabDataSurfaces(unittest.TestCase):
    def test_every_data_tab_is_versioned(self):
        from sq_platform import aggregated as ag
        for schema in (ag.EXPOSURE_SCHEMA, ag.NEWS_SCHEMA, ag.FLOWS_SCHEMA):
            self.assertRegex(schema, r"^sciqnt\..+/v\d+$")

    def test_empty_portfolio_payloads_are_well_formed(self):
        from sq_platform import aggregated as ag
        self.assertEqual(ag.flows_json([])["accounts"], [])
        self.assertEqual(ag.news_json([])["by_ticker"], [])
        ej = ag.exposure_json([], "EUR")
        self.assertEqual(ej["by_currency"], [])
        self.assertEqual(ej["display_currency"], "EUR")


class TestSummonMentionsPushChannel(unittest.TestCase):
    def test_prompt_carries_the_insight_capability(self):
        p = summon_prompt({"where": "home", "command": "sciqnt --once"})
        self.assertIn("sciqnt insight add", p)


class TestSkillTeachesDiscovery(unittest.TestCase):
    def test_portfolio_skill_points_at_help_not_a_frozen_map(self):
        body = sq_skills.CATALOG["sq-portfolio"]["body"]
        self.assertIn("sciqnt --help", body)
        self.assertIn("--json", body)
        self.assertIn("sciqnt insight add", body)   # the push channel
        # The skill trusts the CLI's self-description over its own examples.
        self.assertIn("trust", body.lower())


if __name__ == "__main__":
    unittest.main()
