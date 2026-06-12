"""Cost-basis method config → fold wiring.

`sq_config.cost_basis_method` selects the lot-matching method the Degiro
adapter feeds to `sq_compute.fold_position`. The deterministic core never
reads config — resolution happens at the adapter boundary
(`_resolve_cost_basis_method`). These tests pin that boundary.

SQ_CONFIG_PATH redirects the config file so the user's real settings are
untouched.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

import sq_config                                          # noqa: E402
from sq_compute import CostBasisMethod                    # noqa: E402
from sq_degiro import _resolve_cost_basis_method          # noqa: E402


class TestCostBasisConfigWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-cbm-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def test_defaults_to_fifo_when_unset(self):
        self.assertEqual(_resolve_cost_basis_method(), CostBasisMethod.FIFO)

    def test_reads_configured_method(self):
        for name, enum in (("LIFO", CostBasisMethod.LIFO),
                           ("AVG", CostBasisMethod.AVG),
                           ("FIFO", CostBasisMethod.FIFO)):
            sq_config.set("cost_basis_method", name)
            self.assertEqual(_resolve_cost_basis_method(), enum)

    def test_falls_back_to_fifo_on_garbage(self):
        # bypass validation by writing the file directly (forward-compat path)
        sq_config.path().parent.mkdir(parents=True, exist_ok=True)
        sq_config.path().write_text('{"cost_basis_method": "WACKY"}')
        self.assertEqual(_resolve_cost_basis_method(), CostBasisMethod.FIFO)


if __name__ == "__main__":
    unittest.main()
