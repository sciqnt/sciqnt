"""The community connector distribution path: `sciqnt modules add/remove`.

The SCALABLE answer to "how do thousands of connectors ship without a
per-module PyPI form": git-ref install into a user-owned dir, gated by the
connector's own conformance suite run locally. No PyPI, no central registry,
no maintainer bottleneck. These tests pin that the gate actually gates and
that installed connectors are discovered by the real app.
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

import sq_platform as sp                                       # noqa: E402
from sq_platform import modules_cmd                            # noqa: E402

ROOT = HERE.parents[1]


def _make_bundle(repo: Path, name: str, *, passing: bool):
    """A minimal but real bundle: manifest + a snapshot()-exposing package +
    a conformance test that passes or fails on demand."""
    pkg = f"sq_{name}"
    (repo / "src" / pkg).mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "manifest.yaml").write_text(f"name: sq-{name}\nkind: source\n")
    (repo / "src" / pkg / "__init__.py").write_text(textwrap.dedent(f"""
        def accounts(): return []
        def snapshot(asof=None, *, account=None): return None
        __all__ = ["snapshot", "accounts"]
    """))
    verdict = "self.assertTrue(True)" if passing else "self.assertTrue(False)"
    (repo / "tests" / "test_conf.py").write_text(textwrap.dedent(f"""
        import unittest
        class T(unittest.TestCase):
            def test_it(self): {verdict}
    """))


class TestCommunityInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.user = self.tmp / "user-modules"
        os.environ["SQ_MODULES_PATH"] = str(self.user)

    def tearDown(self):
        os.environ.pop("SQ_MODULES_PATH", None)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _repo(self, name, *, passing):
        repo = self.tmp / f"repo-{name}"
        repo.mkdir()
        _make_bundle(repo, name, passing=passing)
        return repo

    def test_passing_connector_installs_and_is_discovered(self):
        repo = self._repo("acmebroker", passing=True)
        rc = modules_cmd.add(str(repo), ROOT)
        self.assertEqual(rc, 0)
        self.assertTrue((self.user / "sq-acmebroker").is_dir())
        # bundle_dirs (the single discovery seam) now includes it
        self.assertIn("sq-acmebroker",
                      [d.name for d in sp.bundle_dirs(ROOT)])

    def test_failing_conformance_is_rejected(self):
        repo = self._repo("sketchy", passing=False)
        rc = modules_cmd.add(str(repo), ROOT)
        self.assertEqual(rc, 1)
        self.assertFalse((self.user / "sq-sketchy").exists(),
                         "a connector that fails conformance must NOT install")

    def test_remove(self):
        modules_cmd.add(str(self._repo("acmebroker", passing=True)), ROOT)
        self.assertEqual(modules_cmd.remove("acmebroker", ROOT), 0)
        self.assertFalse((self.user / "sq-acmebroker").exists())

    def test_remove_refuses_builtin(self):
        # built-in (repo) bundles are not under the user dir → not removable
        self.assertEqual(modules_cmd.remove("degiro", ROOT), 1)

    def test_repo_wins_on_name_collision(self):
        # a community copy of an existing repo bundle resolves to the repo one
        modules_cmd.add(str(self._repo("degiro", passing=True)), ROOT)
        degiro = next(d for d in sp.bundle_dirs(ROOT) if d.name == "sq-degiro")
        self.assertTrue(str(degiro).startswith(str(ROOT / "modules")))


if __name__ == "__main__":
    unittest.main()
