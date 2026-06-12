"""sq_performance — XIRR + total_return correctness."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_performance import (max_drawdown, total_return, twr,        # noqa: E402
                            twr_index_series, xirr)
from sq_schema import Transaction, TransactionType                  # noqa: E402


def _ts(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _tx(*, type, when, amount, ccy="EUR", inst=None):
    return Transaction(
        transaction_id=f"tx-{when.isoformat()}-{type.value}",
        account_id="A", instrument_id=inst,
        type=type, executed_at=when,
        amount=amount, amount_currency=ccy,
    )


class TestXIRR(unittest.TestCase):
    def test_simple_two_flow_known_rate(self):
        """100 deposited today, 110 retrievable in a year = 10%/yr exactly."""
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
        ]
        rate = xirr(txns, terminal_value=Decimal("110"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        # 110 / 100 = 1.10 over 1.0027 years → ~10%/yr
        self.assertAlmostEqual(float(rate), 0.10, places=2)

    def test_loss_returns_negative_rate(self):
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
        ]
        rate = xirr(txns, terminal_value=Decimal("90"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        self.assertLess(float(rate), 0)
        self.assertGreater(float(rate), -0.20)         # roughly -10%

    def test_multiple_deposits_blended_rate(self):
        # Two equal deposits 6 months apart, terminal value gives
        # ~10%/yr blended.
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 7, 1), amount=Decimal("100")),
        ]
        rate = xirr(txns, terminal_value=Decimal("215"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        self.assertGreater(float(rate), 0)             # positive return
        self.assertLess(float(rate), 0.30)

    def test_dividend_is_in_terminal_value_not_a_separate_flow(self):
        """Under the strict XIRR convention, dividends/interest/fees do
        NOT appear as separate flows — they stay inside the account and
        show up in the terminal value (the account's current cash +
        position value). Treating them as separate flows double-counts.

        Setup: deposit 100, receive 5 dividend (stays as cash in the
        account), position now worth 100 + 5 cash = 105 terminal.
        XIRR over a year → ~5%/yr."""
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
            _tx(type=TransactionType.DIVIDEND,
                when=_ts(2024, 6, 1), amount=Decimal("5")),
        ]
        # terminal_value=105 = position 100 + cash 5
        rate = xirr(txns, terminal_value=Decimal("105"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        # Single flow pair: -100 → +105 over 1 year → +5%
        self.assertAlmostEqual(float(rate), 0.05, places=2)

    def test_returns_none_when_all_same_sign(self):
        # Only deposits, never any return: no IRR exists
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
        ]
        rate = xirr(txns, terminal_value=Decimal("0"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNone(rate)

    def test_excludes_buy_sell_internal_trades(self):
        """BUY/SELL are internal to the account — they must NOT show up
        in the XIRR cash-flow stream (else we'd double-count the cost
        basis as a "deposit")."""
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100")),
            # Internal trade — money stays in the account
            _tx(type=TransactionType.BUY,
                when=_ts(2024, 2, 1), amount=Decimal("-50"), inst="I"),
        ]
        # With ONLY the deposit counted, terminal 110 → ~10%/yr
        rate = xirr(txns, terminal_value=Decimal("110"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(float(rate), 0.10, places=2)

    def test_ignores_cross_currency_flows(self):
        # Mixed-ccy bag: USD flows ignored when computing in EUR
        # WITHOUT an fx_provider injected (silent drop)
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100"), ccy="EUR"),
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("1000"), ccy="USD"),
        ]
        rate = xirr(txns, terminal_value=Decimal("110"),
                    base_currency="EUR", asof=_ts(2025, 1, 1))
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(float(rate), 0.10, places=2)

    def test_mixed_ccy_flows_converted_when_fx_provided(self):
        """When an fx_provider is injected, cross-currency flows convert
        at flow date — so a USD deposit at USD/EUR = 0.90 contributes
        $1000 × 0.90 = €900 to the IRR. Without conversion the rate
        would compute on EUR-only flows; with conversion it reflects
        the true capital committed."""
        from sq_schema import FxRate
        class _FxFake:
            def get_rate(self, src, dst, *, asof=None):
                if src == dst:
                    return FxRate(valid_at=_ts(2024,1,1),
                                  observed_at=_ts(2024,1,1),
                                  from_currency=src, to_currency=dst,
                                  rate=Decimal("1"), source="test")
                if src == "USD" and dst == "EUR":
                    return FxRate(valid_at=_ts(2024,1,1),
                                  observed_at=_ts(2024,1,1),
                                  from_currency=src, to_currency=dst,
                                  rate=Decimal("0.90"), source="test")
                return None

        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("100"), ccy="EUR"),
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("1000"), ccy="USD"),
        ]
        # Net invested: 100 + 1000×0.9 = 1000 EUR. Terminal 1100 → +10%.
        rate = xirr(txns, terminal_value=Decimal("1100"),
                    base_currency="EUR", asof=_ts(2025, 1, 1),
                    fx_provider=_FxFake())
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(float(rate), 0.10, places=2,
                               msg="mixed-ccy XIRR with fx_provider must "
                                   "convert each flow at its own date")


class TestTotalReturn(unittest.TestCase):
    def test_basic_summary(self):
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1),  amount=Decimal("1000")),
            _tx(type=TransactionType.DIVIDEND,
                when=_ts(2024, 6, 1),  amount=Decimal("50")),
            _tx(type=TransactionType.FEE,
                when=_ts(2024, 6, 1),  amount=Decimal("-3")),
            _tx(type=TransactionType.WITHDRAWAL,
                when=_ts(2024, 12, 1), amount=Decimal("-100")),
        ]
        out = total_return(txns, terminal_value=Decimal("1080"),
                           base_currency="EUR")
        self.assertEqual(out["deposits"],        Decimal("1000"))
        self.assertEqual(out["withdrawals"],     Decimal("100"))
        self.assertEqual(out["net_contributed"], Decimal("900"))
        self.assertEqual(out["dividends"],       Decimal("50"))
        self.assertEqual(out["fees"],            Decimal("-3"))
        self.assertEqual(out["current_value"],   Decimal("1080"))
        # Profit = 1080 - 900 = 180
        self.assertEqual(out["profit"],          Decimal("180"))
        # return_pct = 180 / 900 * 100 = 20%
        self.assertEqual(out["return_pct"],      Decimal("20.00"))

    def test_zero_contributed_yields_zero_pct(self):
        out = total_return([], terminal_value=Decimal("1000"),
                           base_currency="EUR")
        self.assertEqual(out["net_contributed"], Decimal("0"))
        self.assertEqual(out["return_pct"],      Decimal("0"))

    def test_asof_trims_future_flows(self):
        txns = [
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2024, 1, 1), amount=Decimal("1000")),
            _tx(type=TransactionType.DEPOSIT,
                when=_ts(2026, 1, 1), amount=Decimal("500")),
        ]
        out = total_return(txns, terminal_value=Decimal("1100"),
                           base_currency="EUR",
                           asof=_ts(2025, 12, 31))
        self.assertEqual(out["deposits"], Decimal("1000"),
                         "asof must exclude future deposits")


class TestTWR(unittest.TestCase):
    def test_simple_two_period_no_flows(self):
        # 1000 → 1100 → 1210 with no cash flows between samples = 10% then 10%
        # geometric = 1.1 × 1.1 = 1.21 → 21% total
        # Annualised over ~2 years (731 days) → ~10%/yr
        vs = [
            (_ts(2024, 1, 1), Decimal("1000")),
            (_ts(2025, 1, 1), Decimal("1100")),
            (_ts(2026, 1, 1), Decimal("1210")),
        ]
        cfs = [(d, Decimal("0")) for d, _ in vs]
        rate = twr(vs, cfs)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(float(rate), 0.10, places=3)
        # Total (non-annualised) should be ~21%
        total = twr(vs, cfs, annualise=False)
        self.assertAlmostEqual(float(total), 0.21, places=3)

    def test_factors_out_a_deposit(self):
        """TWR's whole point: a fresh deposit must NOT pump the return.
        Setup: V=1000 grew to 1100 in year 1 (10%). Year 2 you deposit
        500 — V went 1100 → 1600 right at the boundary, then grew 10%
        to 1760. TWR should report ~10%/yr (the underlying market
        return), not (1760-1000-500)/1500 = ~17.3% which a naive
        return-on-net-flow would yield."""
        vs = [
            (_ts(2024, 1, 1), Decimal("1000")),
            (_ts(2025, 1, 1), Decimal("1600")),    # 1100 after growth + 500 deposit
            (_ts(2026, 1, 1), Decimal("1760")),    # 1600 × 1.10
        ]
        cfs = [
            (_ts(2024, 1, 1), Decimal("0")),
            (_ts(2025, 1, 1), Decimal("500")),     # deposit at the boundary
            (_ts(2026, 1, 1), Decimal("0")),
        ]
        rate = twr(vs, cfs)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(float(rate), 0.10, places=3,
                               msg="TWR must strip out the boundary deposit")

    def test_full_withdrawal_is_flat_zero_return(self):
        # 1000 → 0 with a -1000 withdrawal at the boundary: that's a
        # 0% segment (no market growth, just cash out). NOT undefined —
        # strip the flow: (0 - (-1000)) / 1000 = 1.0 → 0%.
        vs = [
            (_ts(2024, 1, 1), Decimal("1000")),
            (_ts(2025, 1, 1), Decimal("0")),
        ]
        cfs = [
            (_ts(2024, 1, 1), Decimal("0")),
            (_ts(2025, 1, 1), Decimal("-1000")),
        ]
        total = twr(vs, cfs, annualise=False)
        self.assertIsNotNone(total)
        self.assertAlmostEqual(float(total), 0.0, places=4)

    def test_returns_none_on_zero_starting_value(self):
        # Genuine undefined: V_start = 0 (can't divide).
        vs = [
            (_ts(2024, 1, 1), Decimal("0")),
            (_ts(2025, 1, 1), Decimal("100")),
        ]
        cfs = [
            (_ts(2024, 1, 1), Decimal("0")),
            (_ts(2025, 1, 1), Decimal("100")),
        ]
        self.assertIsNone(twr(vs, cfs))

    def test_too_few_samples_returns_none(self):
        self.assertIsNone(twr([(_ts(2024, 1, 1), Decimal("1000"))], [(_ts(2024, 1, 1), Decimal("0"))]))

    def test_emptied_then_refunded_portfolio_breaks_and_relinks(self):
        # A real account shape (found 2026-06-11): account emptied
        # with a tiny NEGATIVE reconstruction residue (-6.98 vs a ~26k
        # peak), re-funded later. Old behaviour: None (the headline TWR
        # showed "—" for the LARGEST account). Correct behaviour: the
        # empty stretch is a GIPS-style performance break — factor 1 —
        # and the real segments still compound: +10% then +20% → 32%.
        vs = [
            (_ts(2021, 1, 1), Decimal("10000")),
            (_ts(2021, 6, 1), Decimal("11000")),   # +10% market
            (_ts(2022, 1, 1), Decimal("-6.98")),   # emptied (residue)
            (_ts(2023, 1, 1), Decimal("5000")),    # re-funded
            (_ts(2024, 1, 1), Decimal("6000")),    # +20% market
        ]
        cfs = [
            (_ts(2021, 1, 1), Decimal("0")),
            (_ts(2021, 6, 1), Decimal("0")),
            (_ts(2022, 1, 1), Decimal("-11006.98")),
            (_ts(2023, 1, 1), Decimal("5006.98")),
            (_ts(2024, 1, 1), Decimal("0")),
        ]
        total = twr(vs, cfs, annualise=False)
        self.assertIsNotNone(total)
        self.assertAlmostEqual(float(total), 0.32, places=4)

    def test_materially_negative_value_is_still_corrupt(self):
        vs = [
            (_ts(2021, 1, 1), Decimal("10000")),
            (_ts(2022, 1, 1), Decimal("-5000")),    # 50% of peak: not a residue
            (_ts(2023, 1, 1), Decimal("5000")),
        ]
        cfs = [(d, Decimal("0")) for d, _ in vs]
        self.assertIsNone(twr(vs, cfs))

    def test_relink_after_much_smaller_refund(self):
        # €1M era → emptied → re-funded with €4k (far below 0.5% of the
        # old peak) → doubled. Without re-anchoring the running peak,
        # every post-refund segment stayed "a break" and the headline
        # printed a confident 0.00% (audit find 2026-06-11).
        vs = [
            (_ts(2020, 1, 1), Decimal("1000000")),
            (_ts(2021, 1, 1), Decimal("0")),          # emptied
            (_ts(2022, 1, 1), Decimal("4000")),       # tiny re-fund
            (_ts(2023, 1, 1), Decimal("8000")),       # +100% market
        ]
        cfs = [
            (_ts(2020, 1, 1), Decimal("0")),
            (_ts(2021, 1, 1), Decimal("-1000000")),
            (_ts(2022, 1, 1), Decimal("4000")),
            (_ts(2023, 1, 1), Decimal("0")),
        ]
        total = twr(vs, cfs, annualise=False)
        self.assertIsNotNone(total)
        self.assertAlmostEqual(float(total), 1.0, places=4)   # +100%

    def test_window_starting_on_negative_residue_relinks(self):
        # A window that OPENS inside a break (tiny negative residue,
        # running peak still unknown) must break-and-relink, not declare
        # the series corrupt.
        vs = [
            (_ts(2022, 1, 1), Decimal("-6.98")),
            (_ts(2023, 1, 1), Decimal("10000")),
            (_ts(2024, 1, 1), Decimal("11000")),
        ]
        cfs = [
            (_ts(2022, 1, 1), Decimal("0")),
            (_ts(2023, 1, 1), Decimal("10006.98")),
            (_ts(2024, 1, 1), Decimal("0")),
        ]
        total = twr(vs, cfs, annualise=False)
        self.assertIsNotNone(total)
        self.assertAlmostEqual(float(total), 0.10, places=4)

    def test_total_loss_annualised_returns_none_not_crash(self):
        # growth ≤ 0 can't be annualised (fractional power of a negative
        # base) — must be None, never InvalidOperation.
        vs = [
            (_ts(2023, 1, 1), Decimal("1000")),
            (_ts(2024, 1, 1), Decimal("-100")),    # >100% loss w/ leverage
        ]
        cfs = [(d, Decimal("0")) for d, _ in vs]
        self.assertIsNone(twr(vs, cfs, annualise=True))

    def test_dust_balance_does_not_explode(self):
        # A €0.03 leftover between funding eras must not turn a 1-cent
        # wobble into a ±33% "return" — it's below materiality: break.
        vs = [
            (_ts(2021, 1, 1), Decimal("10000")),
            (_ts(2022, 1, 1), Decimal("0.03")),     # drained to dust
            (_ts(2023, 1, 1), Decimal("5000.03")),  # re-funded
            (_ts(2024, 1, 1), Decimal("5500.03")),  # +10% market
        ]
        cfs = [
            (_ts(2021, 1, 1), Decimal("0")),
            (_ts(2022, 1, 1), Decimal("-9999.97")),
            (_ts(2023, 1, 1), Decimal("5000")),
            (_ts(2024, 1, 1), Decimal("0")),
        ]
        total = twr(vs, cfs, annualise=False)
        self.assertIsNotNone(total)
        self.assertAlmostEqual(float(total), 0.10, places=3)


class TestTwrIndexSeries(unittest.TestCase):
    def test_carries_flat_through_break_and_sees_recovery(self):
        # Index must NOT truncate at the empty stretch — drawdown needs
        # the later samples to find the recovery.
        vs = [
            (_ts(2021, 1, 1), Decimal("10000")),
            (_ts(2021, 6, 1), Decimal("7000")),     # -30% market
            (_ts(2022, 1, 1), Decimal("0")),        # emptied
            (_ts(2023, 1, 1), Decimal("5000")),     # re-funded
            (_ts(2024, 1, 1), Decimal("8000")),     # +60% market
        ]
        cfs = [
            (_ts(2021, 1, 1), Decimal("0")),
            (_ts(2021, 6, 1), Decimal("0")),
            (_ts(2022, 1, 1), Decimal("-7000")),
            (_ts(2023, 1, 1), Decimal("5000")),
            (_ts(2024, 1, 1), Decimal("0")),
        ]
        idx = twr_index_series(vs, cfs)
        self.assertEqual(len(idx), 5)                # nothing truncated
        self.assertEqual(idx[1][1], Decimal("0.7"))  # the -30%
        self.assertEqual(idx[3][1], idx[2][1])       # flat through break
        dd = max_drawdown(idx)
        self.assertAlmostEqual(float(dd["drawdown_pct"]), 0.30, places=4)
        self.assertIsNotNone(dd["recovered_at"])     # 0.7×1.6=1.12 ≥ 1.0

    def test_materially_negative_truncates_prefix(self):
        vs = [
            (_ts(2021, 1, 1), Decimal("10000")),
            (_ts(2022, 1, 1), Decimal("-5000")),
            (_ts(2023, 1, 1), Decimal("5000")),
        ]
        cfs = [(d, Decimal("0")) for d, _ in vs]
        idx = twr_index_series(vs, cfs)
        self.assertEqual(len(idx), 2)                # prefix kept, rest cut


class TestMaxDrawdown(unittest.TestCase):
    def test_simple_drawdown(self):
        # 100 → 120 (new peak) → 80 (trough) → 110 (no recovery)
        vs = [
            (_ts(2024, 1, 1), Decimal("100")),
            (_ts(2024, 6, 1), Decimal("120")),
            (_ts(2024, 9, 1), Decimal("80")),
            (_ts(2024, 12, 1), Decimal("110")),
        ]
        dd = max_drawdown(vs)
        self.assertIsNotNone(dd)
        self.assertEqual(dd["peak_value"],    Decimal("120"))
        self.assertEqual(dd["trough_value"],  Decimal("80"))
        self.assertEqual(dd["drawdown_abs"],  Decimal("40"))
        # (120-80)/120 = 1/3
        self.assertAlmostEqual(float(dd["drawdown_pct"]), 1/3, places=4)
        # Never recovered to 120 within the series
        self.assertIsNone(dd["recovered_at"])

    def test_recovers_to_new_peak(self):
        # 100 → 120 (peak A) → 80 (trough) → 130 (recovery surpasses peak A)
        vs = [
            (_ts(2024, 1, 1), Decimal("100")),
            (_ts(2024, 6, 1), Decimal("120")),
            (_ts(2024, 9, 1), Decimal("80")),
            (_ts(2024, 12, 1), Decimal("130")),
        ]
        dd = max_drawdown(vs)
        self.assertIsNotNone(dd)
        self.assertEqual(dd["recovered_at"], _ts(2024, 12, 1))

    def test_picks_deepest_drawdown_not_first(self):
        # 100 → 90 (-10%) → 95 → 130 (new peak) → 70 (-46%) → 80
        # Deepest is 130→70, not 100→90, even though 100→90 was first.
        vs = [
            (_ts(2024, 1, 1),  Decimal("100")),
            (_ts(2024, 2, 1),  Decimal("90")),
            (_ts(2024, 3, 1),  Decimal("95")),
            (_ts(2024, 6, 1),  Decimal("130")),
            (_ts(2024, 9, 1),  Decimal("70")),
            (_ts(2024, 12, 1), Decimal("80")),
        ]
        dd = max_drawdown(vs)
        self.assertIsNotNone(dd)
        self.assertEqual(dd["peak_at"],    _ts(2024, 6, 1))
        self.assertEqual(dd["trough_at"],  _ts(2024, 9, 1))
        self.assertEqual(dd["peak_value"], Decimal("130"))

    def test_monotone_increase_yields_zero_dd(self):
        vs = [
            (_ts(2024, 1, 1), Decimal("100")),
            (_ts(2024, 6, 1), Decimal("120")),
            (_ts(2024, 12, 1), Decimal("150")),
        ]
        dd = max_drawdown(vs)
        self.assertIsNotNone(dd)
        self.assertEqual(dd["drawdown_pct"], Decimal("0").quantize(Decimal("0.000001")))

    def test_too_few_samples_returns_none(self):
        self.assertIsNone(max_drawdown([(_ts(2024, 1, 1), Decimal("100"))]))


if __name__ == "__main__":
    unittest.main()
