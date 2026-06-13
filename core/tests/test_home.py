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
        self.assertIn("Portfolio Accounts", labels)         # account-management entry
        # No CredentialsMissing / error framing for merely-unconnected brokers
        self.assertNotIn("CredentialsMissing", labels + captured["header"])

    def test_portfolio_row_opens_tabbed_view(self):
        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             self._scripted("portfolio", "quit"), \
             mock.patch.object(home, "tabbed_view") as tv:
            home.run_home(ROOT)
        tv.assert_called_once()

    def test_accounts_then_quit_invokes_accounts_flow(self):
        with mock.patch.object(home.ag, "_collect_snapshots",
                               return_value=[_connected_broker()]), \
             self._scripted("accounts", "quit"), \
             mock.patch.object(home, "_accounts_flow") as af:
            home.run_home(ROOT)
        af.assert_called_once()

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


class TestAccountsFlow(unittest.TestCase):
    """Portfolio Accounts: the connection-management list + per-account
    actions drill-down."""

    def test_lists_connected_accounts_then_connect_new(self):
        """The list shows each connected account (re-derived from
        _discover_brokers) and ends with a 'Connect new Account' row."""
        captured = {}

        def fake_select(root, ctx, crumbs, items, **kw):
            captured["items"] = items
            return home.sq_tui.BACK

        with mock.patch.object(home.ag, "_discover_brokers",
                               return_value=[("degiro", lambda *a: None),
                                             ("degiro:work", lambda *a: None)]), \
             mock.patch.object(home, "_chrome_select", side_effect=fake_select):
            home._accounts_flow(ROOT, [_connected_broker()], ["degiro"])
        labels = " | ".join(l for l, _ in captured["items"])
        self.assertIn("degiro", labels)
        self.assertIn("degiro:work", labels)
        self.assertIn("Connect new Account", labels)

    def test_connect_new_runs_connect_flow(self):
        with mock.patch.object(home.ag, "_discover_brokers", return_value=[]), \
             mock.patch.object(home, "_chrome_select",
                               side_effect=["connect", home.sq_tui.BACK]), \
             mock.patch.object(home, "_connect_flow") as cf:
            home._accounts_flow(ROOT, [], ["degiro"])
        cf.assert_called_once()

    def test_selecting_account_opens_actions(self):
        with mock.patch.object(home.ag, "_discover_brokers",
                               return_value=[("degiro", lambda *a: None)]), \
             mock.patch.object(home, "_chrome_select",
                               side_effect=[("acct", "degiro"), home.sq_tui.BACK]), \
             mock.patch.object(home, "_account_actions") as aa:
            home._accounts_flow(ROOT, [_connected_broker()], ["degiro"])
        aa.assert_called_once()
        self.assertEqual(aa.call_args[0][1], "degiro")

    def test_demo_account_not_listed(self):
        captured = {}

        def fake_select(root, ctx, crumbs, items, **kw):
            captured["items"] = items
            return home.sq_tui.BACK

        with mock.patch.object(home.ag, "_discover_brokers",
                               return_value=[("demo", lambda *a: None)]), \
             mock.patch.object(home, "_chrome_select", side_effect=fake_select):
            home._accounts_flow(ROOT, [], [])
        labels = " | ".join(l for l, _ in captured["items"])
        self.assertNotIn("demo", labels)
        self.assertIn("Connect new Account", labels)


class TestAccountActions(unittest.TestCase):
    _CMDS = [("setup", "", ""), ("doctor", "", ""), ("forget", "", "")]

    def test_actions_derive_from_advertised_commands(self):
        """The action list is DERIVED from advertised commands: `setup` →
        Reconnect; a bundle without it doesn't get the row. No standing
        'Health check' action (the doctor diagnostics live at the CLI)."""
        def labels_for(cmds):
            captured = {}

            def fake_select(root, ctx, crumbs, items, **kw):
                captured["items"] = items
                return home.sq_tui.BACK

            with mock.patch.object(home, "_wrappers",
                                   return_value={"degiro": "/bin/sq-degiro"}), \
                 mock.patch.object(home, "commands_of", return_value=cmds), \
                 mock.patch.object(home, "_chrome_select",
                                   side_effect=fake_select):
                home._account_actions(ROOT, "degiro", [])
            return [l for l, _ in captured["items"]]

        with_setup = labels_for([("setup", "", ""), ("doctor", "", "")])
        self.assertIn("Reconnect / re-enter credentials", with_setup)  # setup → row
        self.assertNotIn("Health check", with_setup)                   # doctor ≠ menu row
        self.assertIn("Delete account", with_setup)

        without_setup = labels_for([("live", "", "")])
        self.assertNotIn("Reconnect / re-enter credentials", without_setup)

    def test_failed_account_recommends_troubleshoot(self):
        """When THIS account failed its last fetch, the agent component goes
        into warning mode: a recommend line + the failed snapshot are passed
        through to _chrome_select (so the agent row launches troubleshoot)."""
        failed = BrokerSnapshot(broker="degiro:AccountA", snapshot=None,
                                error="DeGiroConnectionError: No session id")
        captured = {}

        def fake_select(root, ctx, crumbs, items, **kw):
            captured.update(kw)
            return home.sq_tui.BACK

        with mock.patch.object(home, "_wrappers",
                               return_value={"degiro": "/bin/sq-degiro"}), \
             mock.patch.object(home, "commands_of", return_value=self._CMDS), \
             mock.patch.object(home, "_chrome_select", side_effect=fake_select):
            home._account_actions(ROOT, "degiro:AccountA", [failed])
        self.assertIn("couldn't fetch", captured.get("recommend", ""))
        self.assertEqual(captured.get("failed"), [failed])

    def test_delete_confirmed_calls_delete_account(self):
        with mock.patch.object(home, "_wrappers",
                               return_value={"degiro": "/bin/sq-degiro"}), \
             mock.patch.object(home, "commands_of", return_value=self._CMDS), \
             mock.patch.object(home, "_chrome_select", return_value="delete"), \
             mock.patch.object(home, "_confirm_delete", return_value=True), \
             mock.patch.object(home, "_delete_account") as da:
            res = home._account_actions(ROOT, "degiro:work", [])
        self.assertEqual(res, "deleted")
        da.assert_called_once()
        # broker/account split passed through correctly
        self.assertEqual(da.call_args[0][1], "degiro")
        self.assertEqual(da.call_args[0][2], "work")

    def test_delete_cancelled_stays(self):
        """Declining the confirm does NOT delete and keeps the menu open."""
        with mock.patch.object(home, "_wrappers",
                               return_value={"degiro": "/bin/sq-degiro"}), \
             mock.patch.object(home, "commands_of", return_value=self._CMDS), \
             mock.patch.object(home, "_chrome_select",
                               side_effect=["delete", home.sq_tui.BACK]), \
             mock.patch.object(home, "_confirm_delete", return_value=False), \
             mock.patch.object(home, "_delete_account") as da:
            res = home._account_actions(ROOT, "degiro", [])
        da.assert_not_called()
        self.assertIsNone(res)

    def test_delete_prefers_bundle_forget_command(self):
        """When the bundle advertises `forget`, delete runs it (not the
        generic substrate)."""
        ran = {}
        with mock.patch.object(home, "_run_wrapper",
                               side_effect=lambda w, *a: ran.update(w=w, a=a)), \
             mock.patch.object(home.sq_tui, "clear_screen"), \
             mock.patch.object(home, "_static_chrome", return_value=""):
            home._delete_account(ROOT, "degiro", "work",
                                 "/bin/sq-degiro", {"setup", "forget"})
        self.assertEqual(ran["w"], "/bin/sq-degiro")
        self.assertEqual(ran["a"], ("forget", "--account", "work"))

    def test_delete_fallback_uses_forget_account_substrate(self):
        """A bundle WITHOUT a forget command falls back to the generic
        sq_secrets.forget_account over its declared SECRET_KEYS."""
        with mock.patch.object(home.sq_tui, "clear_screen"), \
             mock.patch.object(home, "_static_chrome", return_value=""), \
             mock.patch("builtins.input", return_value=""), \
             mock.patch.object(home.sq_secrets, "forget_account") as fa:
            home._delete_account(ROOT, "degiro", "work", "/bin/sq-degiro",
                                 {"setup", "doctor"})   # no 'forget'
        fa.assert_called_once()
        self.assertEqual(fa.call_args[0][0], "sq-degiro")   # SERVICE
        self.assertEqual(fa.call_args[0][1], "work")        # account


class TestAgentWarningComponent(unittest.TestCase):
    """The agent component's recommend/warning modes + routing."""

    def test_agent_rows_recommend_renders_single_orange_line(self):
        rows, styles, _toggle, _inst = home._agent_rows(
            "accounts", recommend="Troubleshoot with Agent (degiro:X couldn't fetch)")
        # row 0 is the selector; row 1 is the recommend line, styled 'warn'.
        self.assertIn("⚠ Recommended:", rows[1][0])
        self.assertIn("couldn't fetch", rows[1][0])
        self.assertEqual(styles[1], "warn")
        self.assertEqual(len(rows), 2)                  # one line, not a block

    def test_chrome_select_routes_agent_to_troubleshoot_when_failed(self):
        """Selecting the agent row in warning mode launches the troubleshoot
        session (not the plain summon)."""
        failed = [BrokerSnapshot(broker="degiro:X", snapshot=None, error="boom")]
        with mock.patch.object(home.sq_tui, "select_screen",
                               side_effect=["agent", home.sq_tui.BACK]), \
             mock.patch.object(home, "_agent_warn_activate") as warn, \
             mock.patch.object(home, "_agent_activate") as plain:
            home._chrome_select(ROOT, "accounts", ("Portfolio Accounts", "degiro:X"),
                                [("View portfolio", "view")],
                                recommend="x", failed=failed)
        warn.assert_called_once()
        plain.assert_not_called()


class _FakeApp:
    """Minimal stand-in for a running prompt_toolkit Application."""
    def __init__(self, running=True):
        self.is_running = running
        self.exited = "__never__"
        loop = self
        self.loop = loop

    def call_soon_threadsafe(self, fn):
        fn()

    def exit(self, result=None):
        self.exited = result


class TestBgRefreshRace(unittest.TestCase):
    """The stale-while-revalidate re-render must survive a fetch that finishes
    before the app's event loop is live (the 'only shows on manual refresh'
    bug)."""

    def test_wake_app_exits_running_app(self):
        app = _FakeApp(running=True)
        home._wake_app([app], home._BG_REFRESH, tries=1, interval=0)
        self.assertEqual(app.exited, home._BG_REFRESH)

    def test_wake_app_waits_then_exits_once_running(self):
        """App not running yet on the first poll → wake waits, then exits it
        when it comes up (no lost re-render)."""
        app = _FakeApp(running=False)
        holder = [app]

        calls = {"n": 0}
        real_sleep = home.time.sleep

        def flip(_):
            calls["n"] += 1
            app.is_running = True            # becomes live after the first poll
        with mock.patch.object(home.time, "sleep", side_effect=flip):
            home._wake_app(holder, home._BG_REFRESH, tries=5, interval=0)
        self.assertEqual(app.exited, home._BG_REFRESH)
        self.assertGreaterEqual(calls["n"], 1)

    def test_wake_app_gives_up_quietly_if_never_running(self):
        with mock.patch.object(home.time, "sleep", return_value=None):
            home._wake_app([None], home._BG_REFRESH, tries=3, interval=0)  # no raise

    def test_first_load_does_a_visible_live_fetch(self):
        """Opening the app does a visible LIVE fetch (loading screen) — so
        totals are current and a currently-failing broker's ⚠ surfaces on
        load — instead of painting stale cache. The warm-cache path is for
        LATER re-acquisitions, not the first paint."""
        ok = _connected_broker()
        failed = BrokerSnapshot(broker="degiro:AccountB", snapshot=None,
                                error="boom")
        with mock.patch.object(home, "_loading_fetch",
                               return_value=[ok, failed]) as lf, \
             mock.patch.object(home.ag, "_collect_cached") as cc, \
             mock.patch.object(home.sq_tui, "select_screen", return_value="quit"):
            home.run_home(ROOT)
        lf.assert_called()                                  # visible fetch on load
        self.assertTrue(lf.call_args.kwargs.get("fresh"))   # …and it's a LIVE one
        cc.assert_not_called()                              # not the warm path first


if __name__ == "__main__":
    unittest.main()
