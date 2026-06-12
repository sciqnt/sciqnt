"""sq_platform.home — interactive landing loop, driven via mocked menu input.

No TTY needed: we patch the menu to return a scripted sequence of choices and
assert the loop dispatches + exits correctly, and that an unconnected broker is
framed as "available to connect" rather than an error.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
for _b in (ROOT / "modules").glob("sq-*"):
    if (_b / "src").is_dir():
        sys.path.insert(0, str(_b / "src"))

from sq_platform import home                                          # noqa: E402
from sq_aggregator import BrokerSnapshot                             # noqa: E402
from sq_schema import (Account, AssetClass, CashBalance, Instrument,  # noqa: E402
                       PortfolioSnapshot, Position)


def _connected_broker():
    inst = Instrument(instrument_id="degiro:isin:X",
                      identifiers={"ticker": "X", "isin": "X"},
                      name="X", asset_class=AssetClass.STOCK, listing_currency="EUR")
    acct = Account(account_id="degiro", broker="degiro", base_currency="EUR")
    pos = Position(account_id="degiro", instrument_id="degiro:isin:X",
                   quantity=Decimal("10"), value_base=Decimal("100"),
                   cost_basis_base=Decimal("90"))
    snap = PortfolioSnapshot(account=acct, instruments=[inst], positions=[pos],
                             cash_balances=[CashBalance(account_id="degiro",
                                            currency="EUR", amount=Decimal("5"))])
    return BrokerSnapshot(broker="degiro", snapshot=snap)


class TestHomeLoop(unittest.TestCase):
    def setUp(self):
        # Silence banner; stub the aggregate so we don't hit network/keychain.
        from sq_aggregator import AggregatedValue
        agg = AggregatedValue(display_currency="EUR",
                              total_value=Decimal("100"),
                              total_pl_lifetime=Decimal("10"))
        self._patches = [
            mock.patch.object(home.ag, "_available_connectors",
                              return_value=["degiro", "kalshi", "polymarket",
                                            "robinhood"]),
            mock.patch.object(home.ag, "build_aggregate",
                              return_value=({"summary": "x"},
                                            "sciqnt · portfolio", agg)),
            # Force the cold path (no on-disk cache) so the per-test
            # `_collect_snapshots` mock is authoritative + deterministic.
            mock.patch.object(home.ag, "_collect_cached", return_value=([], False)),
        ]
        for p in self._patches:
            p.start()

    @staticmethod
    def _scripted(*choices):
        """A select_screen stand-in that returns a scripted sequence of picks
        (the home loop calls it once per iteration)."""
        it = iter(choices)
        return mock.patch.object(home.sq_tui, "select_screen",
                                 side_effect=lambda *a, **k: next(it))

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_quit_exits_zero(self):
        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             self._scripted("quit"):
            rc = home.run_home(ROOT)
        self.assertEqual(rc, 0)

    def test_unconnected_brokers_are_offered_not_errored(self):
        # Only degiro connected; 3 others available. The home shows the
        # PORTFOLIO table + a Connect action (unconnected brokers are reachable
        # there), NOT an error block.
        captured = {}

        def fake_select(items, **kw):
            captured["items"] = items
            captured["header"] = kw.get("header", "")
            return "quit"

        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             mock.patch.object(home.sq_tui, "select_screen",
                               side_effect=fake_select):
            home.run_home(ROOT)
        def _text(lbl):                                     # labels may be rich
            return lbl if isinstance(lbl, str) else "".join(t for _, t in lbl)
        labels = " | ".join(_text(l) for l, _ in captured["items"])
        self.assertIn("Portfolio", labels)                  # portfolio total row
        self.assertIn("Net Worth", labels)                  # table column header (now a row)
        self.assertIn("SciQnt Agent", labels)               # agent selector row
        self.assertIn("Connect to Broker Account", labels)         # unconnected reachable
        # No CredentialsMissing / error framing for merely-unconnected brokers
        self.assertNotIn("CredentialsMissing", labels + captured["header"])

    def test_portfolio_row_opens_tabbed_view(self):
        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             self._scripted("portfolio", "quit"), \
             mock.patch.object(home, "tabbed_view") as tv:
            home.run_home(ROOT)
        tv.assert_called_once()

    def test_connect_then_quit_invokes_connect_flow(self):
        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             self._scripted("connect", "quit"), \
             mock.patch.object(home, "_connect_flow") as cf:
            home.run_home(ROOT)
        cf.assert_called_once()

    def test_no_connected_brokers_shows_intro_not_crash(self):
        with mock.patch.object(home.ag, "_collect_snapshots", return_value=[]), \
             self._scripted("quit"):
            rc = home.run_home(ROOT)        # must not crash with empty brokers
        self.assertEqual(rc, 0)


class TestConnectFlow(unittest.TestCase):
    def test_runs_setup_without_label_question(self):
        """No upfront account-label prompt (research/connect-experience.md):
        the name derives from the username inside the setup form's review.
        text_input_screen must NOT be invoked at all."""
        ran = {}
        def fake_run(wrapper, *args):
            ran["wrapper"] = wrapper
            ran["args"] = args
        with mock.patch.object(home, "_wrappers",
                               return_value={"kalshi": "/bin/sq-kalshi"}), \
             mock.patch.object(home.sq_tui, "select_screen", return_value="kalshi"), \
             mock.patch.object(home.sq_tui, "text_input_screen",
                               side_effect=AssertionError("no label prompt")), \
             mock.patch.object(home, "_run_wrapper", side_effect=fake_run):
            home._connect_flow(ROOT, ["kalshi"])
        self.assertEqual(ran["wrapper"], "/bin/sq-kalshi")
        self.assertEqual(ran["args"], ("setup",))

    def test_back_aborts(self):
        with mock.patch.object(home, "_wrappers",
                               return_value={"degiro": "/bin/sq-degiro"}), \
             mock.patch.object(home.sq_tui, "select_screen",
                               return_value=home.sq_tui.BACK), \
             mock.patch.object(home, "_run_wrapper") as rw:
            home._connect_flow(ROOT, ["degiro"])
        rw.assert_not_called()


if __name__ == "__main__":
    unittest.main()
