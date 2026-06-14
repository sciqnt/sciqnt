"""Connectors must stand alone WITHOUT the interactive TUI (Phase 1 / P11).

Two guarantees, enforced forever so the principle-review agent and CI both
catch regressions:

  1. No connector imports `sq_tui` or `sq_platform` at MODULE LEVEL — the
     interactive layer is a lazy, function-level import (only the interactive
     `live` view pulls prompt-toolkit). Formatting goes through the
     zero-dependency `sq_fmt` leaf.
  2. Every connector (and its `.live` module) imports cleanly with
     prompt-toolkit AND questionary ABSENT — the headless data path
     (snapshot / --json) never requires the TUI.

This is the dependency-direction rule: the arrow points tui → connectors →
core → schema, never back up. A proprietary or headless connector must not
drag in the whole interactive surface.
"""
import ast
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
ROOT = CORE.parent

# (import_name, src_dir) for every first-party connector bundle.
CONNECTORS = [
    ("sq_degiro", ROOT / "modules/sq-degiro/src"),
    ("sq_kalshi", ROOT / "modules/sq-kalshi/src"),
    ("sq_polymarket", ROOT / "modules/sq-polymarket/src"),
    ("sq_robinhood", ROOT / "modules/sq-robinhood/src"),
]

FORBIDDEN = {"sq_tui", "sq_platform"}


def _module_level_imports(py_path):
    """The set of top-level (module-body) imported module roots — nested
    (function/class-body) imports are intentionally excluded."""
    tree = ast.parse(py_path.read_text())
    roots = set()
    for node in tree.body:                       # MODULE BODY ONLY (not walk)
        if isinstance(node, ast.Import):
            for a in node.names:
                roots.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
    return roots


class TestConnectorDecoupling(unittest.TestCase):

    def test_no_module_level_tui_import(self):
        """Every .py in each connector package may use sq_tui/sq_platform only
        via a lazy (function-level) import, never at module level."""
        for name, src in CONNECTORS:
            for py in (src / name).rglob("*.py"):
                roots = _module_level_imports(py)
                bad = roots & FORBIDDEN
                self.assertFalse(
                    bad,
                    f"{py.relative_to(ROOT)} imports {bad} at MODULE level — "
                    f"make it a lazy import inside the interactive function, "
                    f"and take pure formatters from sq_fmt.",
                )

    def test_connectors_import_headless(self):
        """Each connector + its .live module imports with prompt-toolkit AND
        questionary absent, without loading sq_tui — the headless guarantee."""
        paths = [str(CORE)] + [str(src) for _, src in CONNECTORS]
        names = [n for n, _ in CONNECTORS]
        prog = (
            "import sys\n"
            "for m in ('prompt_toolkit', 'questionary'):\n"
            "    sys.modules[m] = None\n"           # simulate ABSENT
            f"for p in {paths!r}:\n"
            "    sys.path.insert(0, p)\n"
            "import importlib\n"
            f"for c in {names!r}:\n"
            "    importlib.import_module(c)\n"
            "    importlib.import_module(c + '.live')\n"
            "assert sys.modules.get('sq_tui') is None, 'sq_tui was loaded headlessly'\n"
            "assert sys.modules.get('prompt_toolkit') is None, 'prompt_toolkit pulled in'\n"
            "print('ok')\n"
        )
        r = subprocess.run([sys.executable, "-c", prog],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         f"headless import failed:\n{r.stdout}\n{r.stderr}")


if __name__ == "__main__":
    unittest.main()
