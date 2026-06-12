"""sq_scaffold — scaffolding a new connector bundle.

Scaffolds into a throwaway repo root (not the real modules/), verifies the
layout, name substitution, overwrite guard, and that the generated bundle is
conformance-GREEN out of the box (its own test passes). The generated test
resolves the contract from ITS repo root; since we scaffold into a tempdir with
no core/, we hand it the real core + bundle src via PYTHONPATH.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/
REPO = HERE.parents[1]                                  # the real repo (for the venv)

import sq_scaffold                                        # noqa: E402


class TestSlugs(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(sq_scaffold.slugs("Trading 212"), ("sq-trading-212", "sq_trading_212"))

    def test_punctuation_collapses(self):
        self.assertEqual(sq_scaffold.slugs("  IBKR!! (Pro) "), ("sq-ibkr-pro", "sq_ibkr_pro"))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            sq_scaffold.slugs("!!!")


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="sq-scaffold-test-"))

    def test_builds_into_staging_by_default(self):
        base = sq_scaffold.build(self.root, "Acme Broker")
        self.assertEqual(base, self.root / ".sq-build" / "sq-acme-broker")  # NOT modules/
        self.assertFalse((self.root / "modules").exists())

    def test_writes_expected_layout(self):
        base = sq_scaffold.build(self.root, "Acme Broker")
        rels = {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}
        self.assertEqual(rels, {
            "manifest.yaml", "SKILL.md", "FINDINGS.md", "pyproject.toml",
            "GENERATE.md", "bin/sq-acme-broker",
            "src/sq_acme_broker/__init__.py", "src/sq_acme_broker/canonical.py",
            "src/sq_acme_broker/live.py", "tests/test_canonical.py",
        })

    def test_init_exposes_discovery_contract(self):
        base = sq_scaffold.build(self.root, "Acme")
        init = (base / "src" / "sq_acme" / "__init__.py").read_text()
        self.assertIn("def snapshot(", init)
        self.assertIn("def accounts(", init)

    def test_base_modules_builds_in_place(self):
        base = sq_scaffold.build(self.root, "Acme", base="modules")
        self.assertEqual(base, self.root / "modules" / "sq-acme")

    def test_bin_is_executable(self):
        base = sq_scaffold.build(self.root, "Acme")
        self.assertTrue((base / "bin" / "sq-acme").stat().st_mode & 0o111)

    def test_name_substituted_not_template(self):
        base = sq_scaffold.build(self.root, "Acme")
        man = (base / "manifest.yaml").read_text()
        self.assertIn("name: sq-acme", man)
        self.assertIn("broker: Acme", man)
        self.assertNotIn("<slug>", man)

    def test_overwrite_guarded(self):
        sq_scaffold.build(self.root, "Acme")
        with self.assertRaises(FileExistsError):
            sq_scaffold.build(self.root, "Acme")
        sq_scaffold.build(self.root, "Acme", force=True)             # force overwrites

    def test_promote_moves_staged_into_modules(self):
        sq_scaffold.build(self.root, "Acme")
        dest = sq_scaffold.promote(self.root, "sq-acme")
        self.assertEqual(dest, self.root / "modules" / "sq-acme")
        self.assertTrue(dest.is_dir())
        self.assertFalse((self.root / ".sq-build" / "sq-acme").exists())  # moved, not copied

    def test_promote_accepts_bare_name_and_guards_missing(self):
        sq_scaffold.build(self.root, "Acme")
        sq_scaffold.promote(self.root, "acme")                       # bare name works
        with self.assertRaises(FileNotFoundError):
            sq_scaffold.promote(self.root, "never-built")

    def test_generated_bundle_is_conformance_green_in_staging(self):
        """The scaffold ships a working empty-portfolio mapping — its own test
        (which runs conformance.check_snapshot) must pass immediately, AND from
        the staging area (the generated test resolves paths location-independently)."""
        base = sq_scaffold.build(self.root, "Acme")                  # staged in .sq-build
        d = base / "tests"
        py = REPO / ".venv" / "bin" / "python"
        py = str(py) if py.exists() else sys.executable
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            [str(REPO / "core"), str(base / "src"), env.get("PYTHONPATH", "")])
        r = subprocess.run(
            [py, "-m", "unittest", "discover", "-s", str(d),
             "-p", "test_*.py", "-t", str(d)],
            capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
