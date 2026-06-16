"""sq-demo contract: deterministic, conformance-clean, offline.

The demo portfolio is sciqnt's PUBLIC FACE (first-run experience, docs,
screenshots) — these tests pin the properties that make that safe:
same figures forever (seeded), schema-clean, no network, and the
platform's void-fill rule (demo only while nothing real is connected).
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "core"))
sys.path.insert(0, str(HERE.parents[0] / "src"))

import sq_demo                                                  # noqa: E402
from sq_demo import portfolio                                   # noqa: E402
from sq_schema import TransactionType, conformance              # noqa: E402

# sq_platform is the interactive APP layer — present in the mono workspace, absent
# from a standalone connector install (a connector must NOT depend on the app).
# App-level aggregation tests skip when it isn't importable.
try:
    import sq_platform  # noqa: F401
    _HAVE_PLATFORM = True
except ImportError:
    _HAVE_PLATFORM = False

ASOF = datetime(2026, 6, 1, tzinfo=timezone.utc)


class TestDemoSnapshot(unittest.TestCase):
    def test_conformance_clean(self):
        self.assertEqual(conformance.check_snapshot(sq_demo.snapshot()), [])

    def test_pit_asof_supported_and_clean(self):
        s = sq_demo.snapshot(asof=ASOF)
        self.assertEqual(conformance.check_snapshot(s), [])

    def test_deterministic_forever(self):
        """Two builds at the same asof agree to the cent — the property
        that makes demo figures publishable in docs."""
        a = sq_demo.snapshot(asof=ASOF)
        b = sq_demo.snapshot(asof=ASOF)
        for pa, pb in zip(a.positions, b.positions):
            self.assertEqual(pa.value_base, pb.value_base)
            self.assertEqual(pa.quantity, pb.quantity)
        self.assertEqual(a.cash_balances[0].amount,
                         b.cash_balances[0].amount)

    def test_past_never_changes_as_walk_extends(self):
        """Extending the walk to a later date must not move earlier
        prices (screenshots taken months apart agree on history)."""
        portfolio._walks.clear()
        early = portfolio.price("demo:swrd", ASOF.date())
        portfolio.price("demo:swrd", datetime.now(timezone.utc).date())
        self.assertEqual(portfolio.price("demo:swrd", ASOF.date()), early)

    def test_history_is_rich(self):
        txns = sq_demo.load_history()
        types = {t.type for t in txns}
        for needed in (TransactionType.DEPOSIT, TransactionType.BUY,
                       TransactionType.SELL, TransactionType.DIVIDEND):
            self.assertIn(needed, types)
        # fees ride on the trades
        self.assertTrue(any(t.fee for t in txns))

    def test_realized_pl_exists(self):
        s = sq_demo.snapshot(asof=ASOF)
        sqtc = next(p for p in s.positions if p.instrument_id == "demo:sqtc")
        self.assertNotEqual(sqtc.realized_pl_base, 0)

    def test_discovery_contract(self):
        self.assertEqual(sq_demo.accounts(), ["sample"])
        self.assertTrue(callable(sq_demo.snapshot))
        self.assertTrue(callable(sq_demo.load_history))
        self.assertTrue(sq_demo.DEMO)


@unittest.skipUnless(_HAVE_PLATFORM, "sq-platform (app layer) not installed standalone")
class TestVoidFill(unittest.TestCase):
    """The PLATFORM owns when demo participates (the bundle can't know
    about other brokers). Environment-independent: assert the invariant,
    not a fixed outcome."""

    def test_auto_means_demo_only_when_alone(self):
        from sq_platform import aggregated as ag
        found = ag._discover_brokers(HERE.parents[2])
        demo = [lb for lb, _ in found if lb.split(":")[0] == "demo"]
        real = [lb for lb, _ in found if lb.split(":")[0] != "demo"]
        if real:
            self.assertEqual(demo, [], "demo must vanish once real "
                                       "accounts are connected (auto)")
        else:
            self.assertEqual(demo, ["demo:sample"],
                             "demo must fill the void when nothing is "
                             "connected")

    def test_demo_never_in_connect_menu(self):
        from sq_platform import aggregated as ag
        self.assertNotIn("demo", ag._available_connectors(HERE.parents[2]))


if __name__ == "__main__":
    unittest.main()
