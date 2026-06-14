"""sq_fmt declares its public formatting contract via __all__ — guard against
drift (a name listed but missing, or a public name silently dropped)."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_fmt  # noqa: E402


class TestFmtContract(unittest.TestCase):
    def test_all_names_exist(self):
        """Every name in __all__ resolves to a real attribute."""
        for name in sq_fmt.__all__:
            self.assertTrue(hasattr(sq_fmt, name),
                            f"sq_fmt.__all__ lists {name!r} but it is not defined")

    def test_no_duplicate_or_private_names(self):
        self.assertEqual(len(sq_fmt.__all__), len(set(sq_fmt.__all__)),
                         "duplicate names in sq_fmt.__all__")
        for name in sq_fmt.__all__:
            self.assertFalse(name.startswith("_"),
                             f"{name!r} is private — keep it out of the public API")


if __name__ == "__main__":
    unittest.main()
