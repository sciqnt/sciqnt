"""Daily portfolio history — the pure assembly math + the tab renderer.

_daily_pnl_rows is the determinism-critical piece: day P&L must be
Δ net worth MINUS external flows (a deposit is not a gain), Decimal end-to-end,
first sample consumed as the Δ anchor. The renderer is smoke-tested with a
stubbed series builder (no network, no broker folds).
"""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

from sq_platform import aggregated as ag                # noqa: E402


def _d(day):
    return datetime(2026, 6, day, 23, 59, 59, tzinfo=timezone.utc)


class TestDailyPnlRows(unittest.TestCase):
    def test_pnl_is_delta_minus_flows(self):
        series = [
            (_d(1), Decimal("1000"), Decimal("900"), Decimal("100")),
            (_d(2), Decimal("1010"), Decimal("905"), Decimal("105")),   # +10, no flow
            (_d(3), Decimal("1510"), Decimal("1400"), Decimal("110")),  # +500 incl 480 deposit
            (_d(4), Decimal("1500"), Decimal("1395"), Decimal("105")),  # -10, no flow
        ]
        flows = {_d(3): Decimal("480")}
        rows = ag._daily_pnl_rows(series, flows)
        self.assertEqual(len(rows), 3)                  # first sample = Δ anchor only
        by_date = {r[0]: r for r in rows}
        self.assertEqual(by_date[_d(2)][5], Decimal("10"))    # plain gain
        self.assertEqual(by_date[_d(3)][5], Decimal("20"))    # 500 − 480 deposit
        self.assertEqual(by_date[_d(4)][5], Decimal("-10"))   # loss
        # a withdrawal (negative flow) must ADD back: nw fell 100, of which 80 withdrawn
        rows2 = ag._daily_pnl_rows(
            [(_d(1), Decimal("1000"), Decimal("0"), Decimal("0")),
             (_d(2), Decimal("900"), Decimal("0"), Decimal("0"))],
            {_d(2): Decimal("-80")})
        self.assertEqual(rows2[0][5], Decimal("-20"))

    def test_decimal_end_to_end(self):
        rows = ag._daily_pnl_rows(
            [(_d(1), Decimal("0.01"), Decimal("0"), Decimal("0.01")),
             (_d(2), Decimal("0.03"), Decimal("0"), Decimal("0.03"))], {})
        self.assertIsInstance(rows[0][5], Decimal)
        self.assertEqual(rows[0][5], Decimal("0.02"))


class TestSampleDates(unittest.TestCase):
    def test_daily_shape(self):
        ds = ag._sample_dates_daily(7)
        self.assertEqual(len(ds), 8)                    # +1 Δ anchor
        self.assertEqual(ds, sorted(ds))
        self.assertEqual((ds[-1].date() - ds[0].date()).days, 7)

    def test_monthly_shape(self):
        ds = ag._sample_dates_monthly(12)
        self.assertEqual(len(ds), 13)                   # 12 month-ends + now
        self.assertEqual(ds, sorted(ds))
        # all but the last are genuine month-ends at 23:59:59
        for d in ds[:-1]:
            nxt = d + __import__("datetime").timedelta(days=1)
            self.assertEqual(nxt.day, 1)                # next day = 1st of month

    def test_yearly_shape(self):
        from datetime import timezone as tz
        now = datetime.now(tz.utc)
        ds = ag._sample_dates_yearly(2020)
        self.assertEqual(ds[0].year, 2019)              # zero anchor before year 1
        self.assertEqual(ds[-1].year, now.year)
        self.assertEqual([d.month for d in ds[:-1]], [12] * (len(ds) - 1))


class TestHistoryStateTab(unittest.TestCase):
    def _rows(self):
        return [
            (_d(2), Decimal("1010"), Decimal("905"), Decimal("105"),
             Decimal("0"), Decimal("10")),
            (_d(3), Decimal("1510"), Decimal("1400"), Decimal("110"),
             Decimal("480"), Decimal("20")),
        ]

    def test_renders_three_sections_and_note(self):
        from datetime import date
        with mock.patch.object(ag, "_build_state_series",
                               return_value=(self._rows(), ["degiro:Main"],
                                             ["robinhood"],
                                             {"degiro:Main": date(2026, 6, 3)})), \
             mock.patch.object(ag, "_earliest_txn_year", return_value=2020), \
             mock.patch.object(ag, "_export_age_days", return_value=0.1):
            out = ag._history_state_tab([], "USD", days=30, months=12)
        self.assertIn("daily — last 30 days", out)
        self.assertIn("monthly — last 12 months", out)
        self.assertIn("yearly — all time", out)
        self.assertIn("1,510.00", out)
        self.assertIn("covers degiro:Main", out)
        self.assertIn("no history (excluded): robinhood", out)
        # fresh files (age 0.1d) → no stale ⚠ despite old last-txn
        self.assertNotIn("export ends", out)
        # most recent first within a section's TABLE. The chart header
        # above each table shows the chronological span ("first → last"),
        # so assert on the LAST occurrences — the table rows.
        self.assertLess(out.rindex("2026-06-03"), out.rindex("2026-06-02"))

    def test_stale_export_is_flagged(self):
        from datetime import date
        rows = [(_d(2), Decimal("10"), Decimal("10"), Decimal("0"),
                 Decimal("0"), Decimal("0"))]
        with mock.patch.object(ag, "_build_state_series",
                               return_value=(rows, ["degiro:Main"], [],
                                             {"degiro:Main": date(2024, 1, 1)})), \
             mock.patch.object(ag, "_earliest_txn_year", return_value=None), \
             mock.patch.object(ag, "_export_age_days", return_value=99.0):
            out = ag._history_state_tab([], "USD")
        self.assertIn("export ends 2024-01-01", out)
        self.assertIn("re-export", out)

    def test_no_history_message(self):
        with mock.patch.object(ag, "_build_state_series",
                               return_value=([], [], ["kalshi"], {})):
            out = ag._history_state_tab([], "USD")
        self.assertIn("no history", out)


class TestHistoryStatus(unittest.TestCase):
    """History coverage must be VISIBLE: missing → expected drop-dir; old
    export → stale; no load_history → unsupported. (The flat→per-account CSV
    migration once degraded all of this silently.)"""

    def _broker(self, label):
        from sq_aggregator import BrokerSnapshot
        from sq_schema import Account, PortfolioSnapshot
        acct = Account(account_id=label, broker=label.split(":")[0],
                       base_currency="EUR")
        return BrokerSnapshot(
            broker=label,
            snapshot=PortfolioSnapshot(account=acct, instruments=[],
                                       positions=[], cash_balances=[]))

    def test_states(self):
        import types
        from sq_schema import Transaction, TransactionType

        old = Transaction(
            transaction_id="t1", account_id="x", type=TransactionType.DEPOSIT,
            amount=Decimal("1"), amount_currency="EUR",
            executed_at=datetime(2024, 1, 2, tzinfo=timezone.utc))
        m_stale = types.ModuleType("sq_fakestale")
        m_stale.load_history = lambda account=None: [old]
        m_stale.history_dir = lambda account=None: Path("/tmp/x")
        m_none = types.ModuleType("sq_fakenone")
        m_none.load_history = lambda account=None: None
        m_none.history_dir = lambda account=None: Path("/data/fakenone/acct")
        m_unsup = types.ModuleType("sq_fakeunsup")
        with mock.patch.dict(sys.modules, {"sq_fakestale": m_stale,
                                           "sq_fakenone": m_none,
                                           "sq_fakeunsup": m_unsup}):
            out = ag._history_status([self._broker("fakestale:a"),
                                      self._broker("fakenone:b"),
                                      self._broker("fakeunsup:c")])
        by = {label: (state, detail) for label, state, detail in out}
        self.assertEqual(by["fakestale:a"][0], "stale")
        self.assertEqual(by["fakestale:a"][1].isoformat(), "2024-01-02")
        self.assertEqual(by["fakenone:b"],
                         ("missing", str(Path("/data/fakenone/acct"))))
        self.assertEqual(by["fakeunsup:c"], ("unsupported", None))


if __name__ == "__main__":
    unittest.main()


class TestHistoryRanges(unittest.TestCase):
    """Yahoo-style range selectors: daily ≤ 1Y, weekly for 5Y, monthly
    for All (owner spec 2026-06-12). Legacy kinds stay for the CLI."""

    def test_range_labels(self):
        self.assertEqual(
            ag.HISTORY_RANGES,
            ("1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "All"))

    def test_daily_ranges_sample_daily(self):
        for kind, n in (("1D", 1), ("5D", 5), ("1M", 30), ("6M", 182),
                        ("1Y", 365)):
            dates, title, _, _ = ag._range_spec(kind, [])
            self.assertEqual(len(dates), n + 1, kind)      # +1 Δ anchor
            self.assertIn("daily", title)
            self.assertEqual((dates[-1].date() - dates[-2].date()).days,
                             1, kind)

    def test_ytd_is_daily_since_jan_1(self):
        from datetime import date, datetime, timezone
        dates, title, _, _ = ag._range_spec("YTD", [])
        self.assertIn("daily", title)
        today = datetime.now(timezone.utc).date()
        expected = max(1, (today - date(today.year, 1, 1)).days)
        self.assertEqual(len(dates), expected + 1)

    def test_5y_is_weekly(self):
        dates, title, _, _ = ag._range_spec("5Y", [])
        self.assertIn("weekly", title)
        self.assertEqual(len(dates), 5 * 52 + 1)
        self.assertEqual((dates[-2].date() - dates[-3].date()).days, 7)

    def test_all_needs_history(self):
        # no brokers with history → honest None (tab shows the message)
        self.assertIsNone(ag._range_spec("All", []))


class TestIntradayRows(unittest.TestCase):
    """The 1D view's pure series builder: forward-fill per ticker from
    the latest first-bar, constant cash, Δ P/L per bar."""

    def _dt(self, h, m=0):
        return datetime(2026, 6, 12, h, m, tzinfo=timezone.utc)

    def test_forward_fill_and_grid_alignment(self):
        legs = [("AAA", Decimal("10"), Decimal("1")),
                ("BBB", Decimal("2"), Decimal("1"))]
        bars = {
            # AAA bars every 5m from 13:30; BBB starts LATER at 13:40 —
            # the grid must start at 13:40 (both legs priceable).
            "AAA": {self._dt(13, 30): Decimal("100"),
                    self._dt(13, 35): Decimal("101"),
                    self._dt(13, 40): Decimal("102"),
                    self._dt(13, 45): Decimal("103")},
            "BBB": {self._dt(13, 40): Decimal("50"),
                    self._dt(13, 50): Decimal("55")},
        }
        rows = ag._intraday_rows(legs, bars, Decimal("7"))
        self.assertEqual(rows[0][0], self._dt(13, 40))
        # 13:40: 10×102 + 2×50 + 7 = 1127
        self.assertEqual(rows[0][1], Decimal("1127"))
        # 13:45: AAA 103, BBB forward-filled at 50 → 1130 + 7? 10×103+100+7
        self.assertEqual(rows[1][1], Decimal("1137"))
        self.assertEqual(rows[1][5], Decimal("10"))      # Δ P/L
        # 13:50: AAA filled at 103, BBB 55 → 10×103+110+7 = 1147
        self.assertEqual(rows[2][1], Decimal("1147"))

    def test_fx_applied_per_leg(self):
        legs = [("AAA", Decimal("1"), Decimal("0.5"))]
        bars = {"AAA": {self._dt(14): Decimal("100"),
                        self._dt(14, 5): Decimal("110")}}
        rows = ag._intraday_rows(legs, bars, Decimal("0"))
        self.assertEqual(rows[0][1], Decimal("50.0"))
        self.assertEqual(rows[1][1], Decimal("55.0"))

    def test_missing_leg_bars_returns_empty(self):
        legs = [("AAA", Decimal("1"), Decimal("1")),
                ("MISSING", Decimal("1"), Decimal("1"))]
        bars = {"AAA": {self._dt(14): Decimal("1"),
                        self._dt(14, 5): Decimal("2")}}
        self.assertEqual(ag._intraday_rows(legs, bars, Decimal("0")), [])

    def test_single_bar_grid_returns_empty(self):
        legs = [("AAA", Decimal("1"), Decimal("1"))]
        bars = {"AAA": {self._dt(14): Decimal("1")}}
        self.assertEqual(ag._intraday_rows(legs, bars, Decimal("0")), [])
