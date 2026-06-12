"""fold_position — the heart of the event-sourcing model.

This file pins the math via small, hand-checked scenarios. Each test names the
exact arithmetic in the docstring so the rule is verifiable by hand from the
test alone (no need to chase code).
"""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_schema import Transaction, TransactionType                # noqa: E402
from sq_compute import (                                            # noqa: E402
    CostBasisMethod, fold_cash_balances, fold_cash_balances_series,
    fold_position, fold_position_series,
)

ACCT = "acct-1"
INST = "inst-aapl"

D = Decimal


def _t(*, type, executed_at, quantity=None, price_local=None,
       amount=D(0), amount_currency="EUR", fx_rate=None,
       tx_id=None, related=None):
    return Transaction(
        transaction_id=tx_id or f"tx-{int(executed_at.timestamp())}",
        account_id=ACCT,
        instrument_id=INST if quantity is not None else None,
        type=type,
        executed_at=executed_at,
        quantity=quantity,
        price_local=price_local,
        amount=amount,
        amount_currency=amount_currency,
        fx_rate=fx_rate,
        related_transaction_ids=related or [],
    )


def _ts(dd):
    return datetime(2026, 1, dd, tzinfo=timezone.utc)


# ───────────────────────────────────────────────────────────────────────────
# Empty + single-event
# ───────────────────────────────────────────────────────────────────────────
class TestFoldEmptyAndSimple(unittest.TestCase):
    def test_no_transactions_returns_closed_zero_position(self):
        pos = fold_position(ACCT, INST, "EUR", [])
        self.assertEqual(pos.quantity, D(0))
        self.assertEqual(pos.cost_basis_base, D(0))
        self.assertEqual(pos.realized_pl_base, D(0))
        self.assertFalse(pos.is_open)

    def test_single_buy_yields_open_position(self):
        """BUY 100 @ 100 EUR/share, EUR-base account → cost_basis = 10,000 EUR.
        No sells → realized = 0; qty = 100."""
        txns = [_t(type=TransactionType.BUY, executed_at=_ts(1),
                   quantity=D(100), price_local=D(100),
                   amount=D(-10000), amount_currency="EUR",
                   fx_rate=D(1))]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.cost_basis_base, D(10000))
        self.assertEqual(pos.break_even_price_local, D(100))
        self.assertEqual(pos.realized_pl_base, D(0))
        self.assertTrue(pos.is_open)


# ───────────────────────────────────────────────────────────────────────────
# Buy → sell-all (closed position with realized P/L)
# ───────────────────────────────────────────────────────────────────────────
class TestFoldBuySellAll(unittest.TestCase):
    def test_same_ccy_realized_pl_simple(self):
        """BUY 100 @ 100 EUR; SELL 100 @ 120 EUR. EUR-base.
        Realized = (120 - 100) × 100 × 1 = +2000 EUR (product).
        Currency P/L = 0 (same ccy, fx=1)."""
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(10),
               quantity=D(-100), price_local=D(120), amount=D(12000),
               amount_currency="EUR", fx_rate=D(1)),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.quantity, D(0))
        self.assertFalse(pos.is_open)
        self.assertEqual(pos.realized_product_pl_base, D(2000))
        self.assertEqual(pos.realized_currency_pl_base, D(0))
        self.assertEqual(pos.total_pl_base, D(2000))


# ───────────────────────────────────────────────────────────────────────────
# FIFO vs LIFO vs AVG on a partial sell
# ───────────────────────────────────────────────────────────────────────────
class TestFoldFifoLifoAvg(unittest.TestCase):
    """Setup: BUY 100 @ 100, BUY 100 @ 150, then SELL 100 @ 200. EUR-base.

    FIFO: 100 sold from the 100@100 lot.  Realized = (200-100)*100 = +10,000.
          Remaining: 100 @ 150 lot → cost_basis = 15,000.
    LIFO: 100 sold from the 100@150 lot.  Realized = (200-150)*100 = +5,000.
          Remaining: 100 @ 100 lot → cost_basis = 10,000.
    AVG : avg cost = (100*100 + 100*150) / 200 = 125. Realized = (200-125)*100 = +7,500.
          Remaining: 100 @ 125 → cost_basis = 12,500."""

    def setUp(self):
        self.txns = [
            _t(type=TransactionType.BUY,  executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.BUY,  executed_at=_ts(5),
               quantity=D(100), price_local=D(150), amount=D(-15000),
               amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(10),
               quantity=D(-100), price_local=D(200), amount=D(20000),
               amount_currency="EUR", fx_rate=D(1)),
        ]

    def test_fifo(self):
        pos = fold_position(ACCT, INST, "EUR", self.txns,
                            method=CostBasisMethod.FIFO)
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.cost_basis_base, D(15000))
        self.assertEqual(pos.break_even_price_local, D(150))
        self.assertEqual(pos.realized_pl_base, D(10000))

    def test_lifo(self):
        pos = fold_position(ACCT, INST, "EUR", self.txns,
                            method=CostBasisMethod.LIFO)
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.cost_basis_base, D(10000))
        self.assertEqual(pos.break_even_price_local, D(100))
        self.assertEqual(pos.realized_pl_base, D(5000))

    def test_avg(self):
        pos = fold_position(ACCT, INST, "EUR", self.txns,
                            method=CostBasisMethod.AVG)
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.cost_basis_base, D(12500))
        self.assertEqual(pos.realized_pl_base, D(7500))


# ───────────────────────────────────────────────────────────────────────────
# Cross-currency: product vs currency P/L decomposition on a closed lot
# ───────────────────────────────────────────────────────────────────────────
class TestFoldCrossCurrency(unittest.TestCase):
    """USD-listed stock, EUR-base account.

    BUY 100 @ $100 with EUR/USD = 0.90 → cost basis = 100 × 100 × 0.90 = 9,000 EUR.
    SELL 100 @ $120 with EUR/USD = 0.85 → proceeds in base = 12,000 × 0.85 = 10,200.

    Realized:
      product  = (120 - 100) × 100 × 0.85 = +1,700 EUR  (price moved up; valued at sell FX)
      currency = 100 × 100 × (0.85 - 0.90) = -500 EUR   (USD weakened vs EUR)
      total    = +1,200 EUR  (= 10,200 - 9,000 — round-trip check)"""

    def test_decomposition(self):
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100),
               amount=D(-9000), amount_currency="EUR",
               fx_rate=D("0.90")),
            _t(type=TransactionType.SELL, executed_at=_ts(10),
               quantity=D(-100), price_local=D(120),
               amount=D(10200), amount_currency="EUR",
               fx_rate=D("0.85")),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.quantity, D(0))
        self.assertEqual(pos.realized_product_pl_base,  D(1700))
        self.assertEqual(pos.realized_currency_pl_base, D(-500))
        self.assertEqual(pos.total_pl_base,             D(1200))


# ───────────────────────────────────────────────────────────────────────────
# Non-impacting transaction types
# ───────────────────────────────────────────────────────────────────────────
class TestFoldIgnoresCashOnlyEvents(unittest.TestCase):
    def test_dividend_does_not_change_quantity_or_basis(self):
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.DIVIDEND, executed_at=_ts(5),
               amount=D(50), amount_currency="EUR"),
            _t(type=TransactionType.FEE, executed_at=_ts(6),
               amount=D(-3), amount_currency="EUR"),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        # Dividend + fee don't touch lots
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.cost_basis_base, D(10000))
        self.assertEqual(pos.realized_pl_base, D(0))


# ───────────────────────────────────────────────────────────────────────────
# Stock split
# ───────────────────────────────────────────────────────────────────────────
class TestFoldSplit(unittest.TestCase):
    def test_two_for_one_split(self):
        """BUY 100 @ 100 EUR; SPLIT 2:1 → 200 shares @ 50 each (cost basis unchanged)."""
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            # SPLIT: quantity carries the ratio (2 for 2:1)
            _t(type=TransactionType.SPLIT, executed_at=_ts(5),
               quantity=D(2), price_local=None, amount=D(0),
               amount_currency="EUR"),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.quantity, D(200))
        self.assertEqual(pos.break_even_price_local, D(50))
        self.assertEqual(pos.cost_basis_base, D(10000))      # unchanged
        self.assertEqual(pos.realized_pl_base, D(0))

    def test_split_does_not_scale_buy_fees(self):
        """BUY 10 @ 100 with a €5 fee; SPLIT 2:1; SELL 20 @ 60.

        The lot's TOTAL fee is €5 regardless of the split — selling the
        whole post-split lot must release exactly −5, not −10. (Audit
        find 2026-06-11: fee_per_unit_local wasn't rescaled with the
        quantity, doubling realised fees across a 2:1 split.)"""
        buy = Transaction(
            transaction_id="b1", account_id=ACCT, instrument_id=INST,
            type=TransactionType.BUY, executed_at=_ts(1),
            quantity=D(10), price_local=D(100), amount=D(-1005),
            amount_currency="EUR", fx_rate=D(1), fee=D(5),
        )
        txns = [
            buy,
            _t(type=TransactionType.SPLIT, executed_at=_ts(5),
               quantity=D(2), amount=D(0), amount_currency="EUR"),
            _t(type=TransactionType.SELL, executed_at=_ts(10),
               quantity=D(-20), price_local=D(60), amount=D(1200),
               amount_currency="EUR", fx_rate=D(1)),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.realized_fees_base, D(-5))
        # product P/L: proceeds 20×60 − cost 10×100 = +200, fee-exclusive
        self.assertEqual(pos.realized_product_pl_base, D(200))


# ───────────────────────────────────────────────────────────────────────────
# Point-in-time (asof)
# ───────────────────────────────────────────────────────────────────────────
class TestFoldAsOf(unittest.TestCase):
    def setUp(self):
        self.txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(20),
               quantity=D(-100), price_local=D(120), amount=D(12000),
               amount_currency="EUR", fx_rate=D(1)),
        ]

    def test_asof_before_sell_shows_open_position(self):
        pos = fold_position(ACCT, INST, "EUR", self.txns, asof=_ts(10))
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.realized_pl_base, D(0))
        self.assertTrue(pos.is_open)

    def test_asof_after_sell_shows_closed_position(self):
        pos = fold_position(ACCT, INST, "EUR", self.txns, asof=_ts(25))
        self.assertEqual(pos.quantity, D(0))
        self.assertEqual(pos.realized_pl_base, D(2000))
        self.assertFalse(pos.is_open)

    def test_asof_sets_valid_at_on_returned_position(self):
        """PIT bitemporal: position's valid_at == asof."""
        asof = _ts(10)
        pos = fold_position(ACCT, INST, "EUR", self.txns, asof=asof)
        self.assertEqual(pos.valid_at, asof)


# ───────────────────────────────────────────────────────────────────────────
# Filter — transactions for OTHER instruments / accounts shouldn't contaminate
# ───────────────────────────────────────────────────────────────────────────
class TestFoldFiltering(unittest.TestCase):
    def test_ignores_transactions_for_other_instruments(self):
        """A SELL for instrument B must not consume lots from instrument A."""
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100), amount=D(-10000),
               amount_currency="EUR", fx_rate=D(1)),
            # A SELL for a different instrument — must not affect our fold
            Transaction(
                transaction_id="other-sell", account_id=ACCT,
                instrument_id="inst-OTHER",
                type=TransactionType.SELL,
                executed_at=_ts(5),
                quantity=D(-50), price_local=D(200),
                amount=D(10000), amount_currency="EUR",
            ),
        ]
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.quantity, D(100))
        self.assertEqual(pos.realized_pl_base, D(0))


class TestFoldFeesInclusive(unittest.TestCase):
    """fold_position is fees-inclusive: realized_pl_base = product + currency + fees.
    Fees are allocated proportionally per lot at buy time so partial sells get
    a proportional buy-side fee; sell-side fees apply entirely to that sell."""

    def test_buy_sell_with_fees_matches_net_cash(self):
        """BUY 100 @ €100 with €5 fee (-10,005 cash). SELL 100 @ €120 with €3
        fee (+11,997 cash). Net cash: +1,992. fold_position.realized_pl_base
        must equal +1,992 (the actual cash gain). Decomposition:
          product = (120-100)×100 = +2,000
          currency = 0 (same ccy)
          fees    = -(5 + 3) = -8
          realized = 2,000 - 8 = +1,992 ✓"""
        txns = [
            _t(type=TransactionType.BUY,  executed_at=_ts(1),
               quantity=D(100), price_local=D(100),
               amount=D(-10005), amount_currency="EUR",
               fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(10),
               quantity=D(-100), price_local=D(120),
               amount=D(11997), amount_currency="EUR",
               fx_rate=D(1)),
        ]
        # Manually set the fee field on the synthetic transactions
        txns[0] = txns[0].model_copy(update={"fee": D("5")})
        txns[1] = txns[1].model_copy(update={"fee": D("3")})
        pos = fold_position(ACCT, INST, "EUR", txns)
        self.assertEqual(pos.realized_product_pl_base,  D(2000))
        self.assertEqual(pos.realized_currency_pl_base, D(0))
        self.assertEqual(pos.realized_fees_base,        D(-8))
        self.assertEqual(pos.realized_pl_base,          D(1992))

    def test_partial_sell_gets_proportional_buy_fee(self):
        """BUY 100 with €10 fee allocates €0.10 fee per share. SELL 30
        triggers €0.10 × 30 = €3 buy-side fee + the sell's own fee."""
        txns = [
            _t(type=TransactionType.BUY, executed_at=_ts(1),
               quantity=D(100), price_local=D(100),
               amount=D(-10010), amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(5),
               quantity=D(-30), price_local=D(110),
               amount=D(3299), amount_currency="EUR", fx_rate=D(1)),
        ]
        txns[0] = txns[0].model_copy(update={"fee": D("10")})
        txns[1] = txns[1].model_copy(update={"fee": D("1")})
        pos = fold_position(ACCT, INST, "EUR", txns)
        # Only 30/100 of the buy fee released; sell fee entirely:
        self.assertEqual(pos.realized_fees_base, D("-4"))    # -(0.10×30 + 1) = -4
        # Product: (110-100)×30 = +300 ; realized = 300 + 0 + (-4) = +296
        self.assertEqual(pos.realized_product_pl_base, D(300))
        self.assertEqual(pos.realized_pl_base,         D(296))
        # Open position has the other 70/100 of fees still attached to lot
        self.assertEqual(pos.quantity, D(70))


class TestFoldPositionSeries(unittest.TestCase):
    """Pin the equivalence: fold_position_series([X, Y, Z]) returns the
    same Positions (cent-for-cent) as calling fold_position(asof=X),
    fold_position(asof=Y), fold_position(asof=Z) one by one. The series
    primitive replaces N fold-loops with one chronological pass; that's
    the only legitimate optimisation — any divergence means math drift."""

    def _txns(self):
        return [
            _t(type=TransactionType.BUY,  executed_at=_ts(1),
               quantity=D(10), price_local=D(100),
               amount=D(-1000), amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.BUY,  executed_at=_ts(5),
               quantity=D(5), price_local=D(120),
               amount=D(-600), amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(8),
               quantity=D(-7), price_local=D(150),
               amount=D(1050), amount_currency="EUR", fx_rate=D(1)),
            _t(type=TransactionType.SELL, executed_at=_ts(12),
               quantity=D(-8), price_local=D(160),
               amount=D(1280), amount_currency="EUR", fx_rate=D(1)),
        ]

    def test_series_equals_per_asof_loop(self):
        txns = self._txns()
        asofs = [_ts(1), _ts(2), _ts(6), _ts(9), _ts(13), _ts(20)]
        series = fold_position_series(
            ACCT, INST, "EUR", txns, asofs,
        )
        for a in asofs:
            ref = fold_position(ACCT, INST, "EUR", txns, asof=a)
            actual = series[a]
            self.assertEqual(actual.quantity,                ref.quantity,        a)
            self.assertEqual(actual.cost_basis_base,         ref.cost_basis_base, a)
            self.assertEqual(actual.realized_product_pl_base, ref.realized_product_pl_base, a)
            self.assertEqual(actual.realized_currency_pl_base, ref.realized_currency_pl_base, a)
            self.assertEqual(actual.realized_fees_base,      ref.realized_fees_base, a)
            self.assertEqual(actual.realized_pl_base,        ref.realized_pl_base, a)
            self.assertEqual(actual.break_even_price_local,  ref.break_even_price_local, a)

    def test_empty_asof_dates_returns_empty_dict(self):
        self.assertEqual(
            fold_position_series(ACCT, INST, "EUR", self._txns(), []),
            {},
        )

    def test_duplicate_asofs_dedup(self):
        txns = self._txns()
        out = fold_position_series(ACCT, INST, "EUR", txns,
                                    [_ts(5), _ts(5), _ts(5)])
        self.assertEqual(len(out), 1)

    def test_asof_before_first_transaction_yields_zero_qty(self):
        # First txn is at _ts(1) (Jan 1, 2026); asof at "yesterday" (Dec 31, 2025)
        before = datetime(2025, 12, 31, tzinfo=timezone.utc)
        txns = self._txns()
        out = fold_position_series(ACCT, INST, "EUR", txns, [before])
        pos = out[before]
        self.assertEqual(pos.quantity,        D(0))
        self.assertEqual(pos.realized_pl_base, D(0))

    def test_series_lots_dont_alias_across_asofs(self):
        """Each checkpoint clones lots — mutating lots later must NOT
        retroactively change earlier snapshots (caught by Pydantic's
        immutable derived fields)."""
        txns = self._txns()
        out = fold_position_series(ACCT, INST, "EUR", txns,
                                    [_ts(6), _ts(20)])
        early = out[_ts(6)]
        late  = out[_ts(20)]
        self.assertEqual(early.quantity, D(15))     # 10 + 5 buys
        self.assertEqual(late.quantity,  D(0))      # all sold by ts=20
        # Earlier snapshot must NOT have been mutated by the later sells
        self.assertEqual(early.realized_pl_base, D(0))


class TestFoldCashBalancesSeries(unittest.TestCase):
    """Same equivalence pinning for the cash-ledger series primitive."""

    def _txns(self):
        return [
            _t(type=TransactionType.DEPOSIT,    executed_at=_ts(1),
               amount=D(1000), amount_currency="EUR"),
            _t(type=TransactionType.DIVIDEND,   executed_at=_ts(3),
               amount=D(50),   amount_currency="EUR"),
            _t(type=TransactionType.WITHDRAWAL, executed_at=_ts(5),
               amount=D(-300), amount_currency="EUR"),
            _t(type=TransactionType.DIVIDEND,   executed_at=_ts(7),
               amount=D(20),   amount_currency="USD"),
        ]

    def test_series_equals_per_asof_loop(self):
        txns = self._txns()
        asofs = [_ts(1), _ts(2), _ts(4), _ts(6), _ts(10)]
        out = fold_cash_balances_series(txns, asofs)
        for a in asofs:
            ref = fold_cash_balances(txns, asof=a)
            self.assertEqual(out[a], ref, a)

    def test_empty_asofs(self):
        self.assertEqual(fold_cash_balances_series(self._txns(), []), {})


if __name__ == "__main__":
    unittest.main()
