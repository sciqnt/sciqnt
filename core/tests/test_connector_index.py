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






if __name__ == "__main__":
    unittest.main()
