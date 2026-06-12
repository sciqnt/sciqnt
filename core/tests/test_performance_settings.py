"""Performance-methodology config → rendering wiring.

Two `sq_config` settings are resolved at the rendering boundary in
`sq_platform.aggregated` (the pure core never reads config):

  * `performance_return_method` ('TWR'|'MWR') — flags which return the
    summary marks as the headline. Both are always computed.
  * `annualize_sub_year_returns` (bool) — gates annualising the TWR for
    holding periods under one year (GIPS I.5.A.4 prohibits it by default).

These tests pin the resolvers + the annualise decision. SQ_CONFIG_PATH
redirects the config file so the user's real settings are untouched.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))           # core/
for _bundle in (ROOT / "modules").glob("sq-*"):
    _src = _bundle / "src"
    if _src.is_dir():
        sys.path.insert(0, str(_src))

import sq_config                                                   # noqa: E402
from sq_platform.aggregated import (                               # noqa: E402
    _annualize_sub_year_returns, _performance_return_method,
    _should_annualise,
)


class TestPerformanceReturnMethod(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-perf-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def test_defaults_to_twr_when_unset(self):
        self.assertEqual(_performance_return_method(), "TWR")

    def test_reads_configured_method(self):
        for value in ("MWR", "TWR"):
            sq_config.set("performance_return_method", value)
            self.assertEqual(_performance_return_method(), value)

    def test_falls_back_to_twr_on_garbage(self):
        # bypass set() validation by writing the file directly (forward-compat)
        sq_config.path().parent.mkdir(parents=True, exist_ok=True)
        sq_config.path().write_text('{"performance_return_method": "WACKY"}')
        self.assertEqual(_performance_return_method(), "TWR")


class TestAnnualizeSubYearReturns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-perf-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def test_defaults_to_false(self):
        # GIPS default — do NOT annualise sub-year returns.
        self.assertIs(_annualize_sub_year_returns(), False)

    def test_reads_configured_true(self):
        sq_config.set("annualize_sub_year_returns", True)
        self.assertIs(_annualize_sub_year_returns(), True)
        sq_config.set("annualize_sub_year_returns", "false")
        self.assertIs(_annualize_sub_year_returns(), False)


class TestShouldAnnualise(unittest.TestCase):
    def test_over_a_year_always_annualises(self):
        self.assertTrue(_should_annualise(400, False))
        self.assertTrue(_should_annualise(365, False))

    def test_sub_year_defaults_to_not_annualising(self):
        self.assertFalse(_should_annualise(200, False))
        self.assertFalse(_should_annualise(0, False))

    def test_opt_in_annualises_even_sub_year(self):
        self.assertTrue(_should_annualise(30, True))
        self.assertTrue(_should_annualise(400, True))


class _StubPriceProvider:
    """get_price returns a canned Price per asof date."""
    def __init__(self, prices):                      # {date: Decimal}
        self._prices = prices

    def get_price(self, ticker, *, asof=None):
        from sq_schema import Price
        target = asof.date() if hasattr(asof, "date") else asof
        px = self._prices.get(target)
        if px is None:
            return None
        return Price(valid_at=asof, observed_at=asof, instrument_id=None,
                     last_price_local=px, currency="EUR", source="stub")


class TestBenchmarkPerformance(unittest.TestCase):
    """_benchmark_performance — the zero-flow TWR comparison leg."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq-bench-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")
        from datetime import datetime, timezone
        self.t0 = datetime(2023, 1, 2, tzinfo=timezone.utc)
        self.t1 = datetime(2024, 1, 2, tzinfo=timezone.utc)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def test_default_benchmark_is_msci_world_etf(self):
        self.assertEqual(sq_config.benchmark(), "IWDA.AS")

    def test_computes_price_return_over_window(self):
        from decimal import Decimal
        from sq_platform.aggregated import _benchmark_performance
        stub = _StubPriceProvider({self.t0.date(): Decimal("100"),
                                   self.t1.date(): Decimal("110")})
        out = _benchmark_performance(self.t0, self.t1, annualise=True,
                                     price_provider=stub)
        self.assertEqual(out["ticker"], "IWDA.AS")
        self.assertEqual(out["return_pct"], Decimal("10"))
        # ~1y window → annualised ≈ the period return
        self.assertAlmostEqual(float(out["twr"]), 0.10, places=2)

    def test_none_disables(self):
        from sq_platform.aggregated import _benchmark_performance
        sq_config.set("benchmark", "none")
        out = _benchmark_performance(self.t0, self.t1, annualise=True,
                                     price_provider=_StubPriceProvider({}))
        self.assertIsNone(out)

    def test_unpriceable_window_returns_none(self):
        from sq_platform.aggregated import _benchmark_performance
        out = _benchmark_performance(self.t0, self.t1, annualise=True,
                                     price_provider=_StubPriceProvider({}))
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
