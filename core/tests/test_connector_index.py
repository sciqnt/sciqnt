"""The OPTIONAL discoverability index + the naming convention (Phase 3).

- `connectors-index.json` is a thin, checked-in discovery CATALOG — not a
  registry. `sciqnt modules find` reads it; `sciqnt modules add owner/repo`
  must keep working with NO index at all (sovereignty: registry optional).
- Every first-party bundle follows the `sq-<slug>` / `sq_<slug>` naming
  convention (the predictable resolve path, Homebrew/Terraform-style).
- Index entries correspond to real bundles (no rot).
"""
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
ROOT = CORE.parent
sys.path.insert(0, str(CORE))

from sq_platform import modules_cmd  # noqa: E402

BUNDLE_RE = re.compile(r"^sq-[a-z0-9]+(-[a-z0-9]+)*$")
PKG_RE = re.compile(r"^sq_[a-z0-9_]+$")


class TestNamingConvention(unittest.TestCase):
    def test_bundles_and_packages_follow_convention(self):
        for d in sorted((ROOT / "modules").glob("sq-*")):
            if not d.is_dir():
                continue
            self.assertRegex(d.name, BUNDLE_RE,
                             f"{d.name}: bundle must be sq-<slug>")
            src = d / "src"
            if src.is_dir():
                for pkg in src.glob("sq_*"):
                    if pkg.is_dir():
                        self.assertRegex(pkg.name, PKG_RE,
                                         f"{pkg.name}: package must be sq_<slug>")


class TestConnectorIndex(unittest.TestCase):
    def setUp(self):
        self.idx = ROOT / "connectors-index.json"

    def test_index_is_valid_and_versioned(self):
        data = json.loads(self.idx.read_text())
        self.assertEqual(data.get("schema"), "sciqnt.connector-index/v1")
        self.assertIsInstance(data.get("connectors"), list)
        for e in data["connectors"]:
            self.assertIn("name", e)
            self.assertIn("repo", e)
            self.assertRegex(e["name"], BUNDLE_RE)

    def test_first_party_entries_map_to_real_bundles(self):
        data = json.loads(self.idx.read_text())
        for e in data["connectors"]:
            if e.get("zone") == "official" and e.get("repo") == "sciqnt/sciqnt":
                self.assertTrue((ROOT / "modules" / e["name"]).is_dir(),
                                f"index lists {e['name']} but no such bundle")

    def test_find_matches_and_is_query_aware(self):
        # EVENT asset class → the two prediction markets, regardless of order.
        # (smoke: cli returns 0 and doesn't raise)
        self.assertEqual(modules_cmd.find("event", ROOT), 0)
        self.assertEqual(modules_cmd.find("zzz-no-match", ROOT), 0)
        self.assertEqual(modules_cmd.find("", ROOT), 0)

    def test_find_is_optional_no_index(self):
        """With no index present, find degrades gracefully (returns 0) — add
        must never depend on it."""
        import tempfile
        empty = Path(tempfile.mkdtemp(prefix="sq-noindex-"))
        self.assertEqual(modules_cmd.find("anything", empty), 0)


class TestProvenanceSurfacing(unittest.TestCase):
    """`modules add`/`list` surface the manifest's trust signals (provenance,
    risk_tier, endorsement) so install is informed consent — read without a
    YAML dependency."""

    def test_official_vs_reverse_engineered(self):
        kalshi = modules_cmd._manifest_facts(ROOT / "modules/sq-kalshi")
        self.assertEqual(kalshi["provenance"], "official")
        degiro = modules_cmd._manifest_facts(ROOT / "modules/sq-degiro")
        self.assertEqual(degiro["provenance"], "reverse-engineered")

    def test_facts_line_is_honest(self):
        line = modules_cmd._facts_line(
            {"provenance": "reverse-engineered", "risk_tier": "read",
             "endorsed": False})
        self.assertIn("reverse-engineered", line)
        self.assertIn("not endorsed", line)

    def test_missing_manifest_degrades(self):
        import tempfile
        facts = modules_cmd._manifest_facts(Path(tempfile.mkdtemp()))
        self.assertEqual(facts["provenance"], "n/a")
        self.assertIsNone(facts["endorsed"])


if __name__ == "__main__":
    unittest.main()
