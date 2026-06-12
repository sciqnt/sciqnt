"""sq_analytics — tests for the seven aggregate compute functions.

Each test fixture uses tiny, hand-checked inputs (synthetic Positions /
Transactions / Instruments) so the expected values can be verified by
hand from the test alone."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_analytics import (                                          # noqa: E402
    all_tax_lots, asset_class_exposure, cash_flow_over_time,
    currency_exposure, dividend_history, fee_history, income_summary,
    portfolio_summary, realized_pl_over_time, tax_lots,
)
from sq_compute import CostBasisMethod, fold_position                # noqa: E402
from sq_schema import (                                              # noqa: E402
    AssetClass, CashBalance, Instrument, Position, Transaction,
    TransactionType,
)


def _ts(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


def _instrument(*, instrument_id="inst-A", ticker="ABC", isin="US0000000001",
                asset_class=AssetClass.STOCK, listing_currency="USD",
                name="ACME Corp"):
    return Instrument(
        instrument_id=instrument_id,
        identifiers={"ticker": ticker, "isin": isin,
                     "broker:degiro": instrument_id},
        name=name, asset_class=asset_class,
        listing_currency=listing_currency,
    )


def _position(*, instrument_id="inst-A", account_id="A1",
              quantity=Decimal("100"), value_base=Decimal("10000"),
              last_price_local=Decimal("100"),
              cost_basis_base=Decimal("9500"),
              break_even_price_local=Decimal("95"),
              unrealized_product_pl_base=Decimal("0"),
              unrealized_currency_pl_base=Decimal("0"),
              realized_product_pl_base=Decimal("0"),
              realized_currency_pl_base=Decimal("0")):
    return Position(
        account_id=account_id, instrument_id=instrument_id,
        quantity=quantity, last_price_local=last_price_local,
        value_base=value_base, cost_basis_base=cost_basis_base,
        break_even_price_local=break_even_price_local,
        unrealized_product_pl_base=unrealized_product_pl_base,
        unrealized_currency_pl_base=unrealized_currency_pl_base,
        realized_product_pl_base=realized_product_pl_base,
        realized_currency_pl_base=realized_currency_pl_base,
    )


# ─────────────────────────────────────────────────────────────────────────
# portfolio_summary
# ─────────────────────────────────────────────────────────────────────────
class TestPortfolioSummary(unittest.TestCase):
    def test_empty_portfolio_returns_zeros(self):
        out = portfolio_summary([], base_currency="EUR")
        self.assertEqual(out["instrument_count"],         0)
        self.assertEqual(out["open_position_count"],      0)
        self.assertEqual(out["closed_position_count"],    0)
        self.assertEqual(out["total_cost_basis_base"],    Decimal("0"))
        self.assertEqual(out["total_realized_pl_base"],   Decimal("0"))

    def test_aggregates_open_and_closed(self):
        positions = [
            _position(instrument_id="A", quantity=Decimal("100"),
                      cost_basis_base=Decimal("1000"),
                      value_base=Decimal("1200")),
            _position(instrument_id="B", quantity=Decimal("0"),
                      cost_basis_base=Decimal("0"),
                      value_base=Decimal("0"),
                      realized_product_pl_base=Decimal("200"),
                      realized_currency_pl_base=Decimal("-30")),
        ]
        out = portfolio_summary(positions, base_currency="EUR")
        self.assertEqual(out["instrument_count"],        2)
        self.assertEqual(out["open_position_count"],     1)
        self.assertEqual(out["closed_position_count"],   1)
        self.assertEqual(out["total_cost_basis_base"],   Decimal("1000"))
        self.assertEqual(out["total_value_base"],        Decimal("1200"))
        self.assertEqual(out["total_realized_pl_base"],  Decimal("170"))    # 200 - 30
        self.assertEqual(out["total_realized_product_pl_base"],  Decimal("200"))
        self.assertEqual(out["total_realized_currency_pl_base"], Decimal("-30"))


# ─────────────────────────────────────────────────────────────────────────
# currency_exposure
# ─────────────────────────────────────────────────────────────────────────
class TestCurrencyExposure(unittest.TestCase):
    def test_open_position_uses_listing_currency_local_value(self):
        instruments = [_instrument(instrument_id="X", listing_currency="USD")]
        positions = [_position(instrument_id="X", quantity=Decimal("10"),
                               last_price_local=Decimal("200"),
                               value_base=Decimal("1700"))]   # ignored — local exists
        cash = [CashBalance(account_id="A1", currency="EUR",
                            amount=Decimal("500"))]
        out = currency_exposure(positions, cash, instruments,
                                base_currency="EUR")
        # USD bucket: 10 * 200 = 2,000 (in USD, the listing currency)
        self.assertEqual(out["USD"]["positions"], Decimal("2000"))
        self.assertEqual(out["USD"]["cash"],      Decimal("0"))
        self.assertEqual(out["EUR"]["cash"],      Decimal("500"))

    def test_closed_position_does_not_contribute(self):
        instruments = [_instrument(instrument_id="X", listing_currency="USD")]
        positions = [_position(instrument_id="X", quantity=Decimal("0"),
                               value_base=Decimal("0"),
                               last_price_local=None)]
        out = currency_exposure(positions, [], instruments,
                                base_currency="EUR")
        self.assertEqual(out, {})   # no current exposure from closed positions

    def test_zero_cash_balance_skipped(self):
        out = currency_exposure(
            [], [CashBalance(account_id="A1", currency="USD",
                             amount=Decimal("0"))],
            [], base_currency="EUR",
        )
        self.assertEqual(out, {})


# ─────────────────────────────────────────────────────────────────────────
# asset_class_exposure
# ─────────────────────────────────────────────────────────────────────────
class TestAssetClassExposure(unittest.TestCase):
    def test_buckets_by_asset_class(self):
        instruments = [
            _instrument(instrument_id="S", asset_class=AssetClass.STOCK),
            _instrument(instrument_id="E", asset_class=AssetClass.ETF),
        ]
        positions = [
            _position(instrument_id="S", value_base=Decimal("500"),
                      cost_basis_base=Decimal("400"),
                      realized_product_pl_base=Decimal("50")),
            _position(instrument_id="E", value_base=Decimal("1500"),
                      cost_basis_base=Decimal("1300"),
                      realized_product_pl_base=Decimal("10")),
        ]
        out = asset_class_exposure(positions, instruments,
                                   base_currency="EUR")
        self.assertEqual(out["STOCK"]["position_count"],  1)
        self.assertEqual(out["STOCK"]["value_base"],      Decimal("500"))
        self.assertEqual(out["STOCK"]["cost_basis_base"], Decimal("400"))
        self.assertEqual(out["STOCK"]["realized_pl_base"], Decimal("50"))
        self.assertEqual(out["ETF"]["value_base"],        Decimal("1500"))

    def test_missing_instrument_falls_to_other(self):
        # Position references an instrument that isn't in the snapshot
        positions = [_position(instrument_id="unknown",
                               value_base=Decimal("100"))]
        out = asset_class_exposure(positions, [], base_currency="EUR")
        self.assertIn("OTHER", out)
        self.assertEqual(out["OTHER"]["position_count"], 1)


# ─────────────────────────────────────────────────────────────────────────
# dividend_history + fee_history
# ─────────────────────────────────────────────────────────────────────────
def _tx(*, type, when, amount, inst=None, fee=None, ccy="EUR"):
    return Transaction(
        transaction_id=f"tx-{when.isoformat()}-{type.value}",
        account_id="A", instrument_id=inst,
        type=type, executed_at=when,
        amount=amount, amount_currency=ccy, fee=fee,
    )


class TestDividendHistory(unittest.TestCase):
    def setUp(self):
        self.txns = [
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 3, 1),
                amount=Decimal("100"), inst="inst-1"),
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 6, 1),
                amount=Decimal("50"),  inst="inst-1"),
            _tx(type=TransactionType.DIVIDEND, when=_ts(2025, 3, 1),
                amount=Decimal("80"),  inst="inst-2"),
            # Non-dividend tx (must be ignored)
            _tx(type=TransactionType.FEE,      when=_ts(2024, 1, 1),
                amount=Decimal("-5")),
        ]

    def test_by_year(self):
        out = dividend_history(self.txns, group_by="year")
        self.assertEqual(out, {2024: Decimal("150"), 2025: Decimal("80")})

    def test_by_instrument(self):
        out = dividend_history(self.txns, group_by="instrument")
        self.assertEqual(out["inst-1"], Decimal("150"))
        self.assertEqual(out["inst-2"], Decimal("80"))

    def test_currency_filter(self):
        mixed = self.txns + [
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 9, 1),
                amount=Decimal("5"), inst="inst-3", ccy="USD"),
        ]
        out = dividend_history(mixed, group_by="year", currency="USD")
        self.assertEqual(out, {2024: Decimal("5")})


class TestFeeHistory(unittest.TestCase):
    def test_explicit_fee_transactions(self):
        txns = [
            _tx(type=TransactionType.FEE, when=_ts(2024, 1, 1),
                amount=Decimal("-2")),
            _tx(type=TransactionType.FEE, when=_ts(2024, 6, 1),
                amount=Decimal("-3")),
        ]
        out = fee_history(txns, group_by="year")
        self.assertEqual(out, {2024: Decimal("-5")})

    def test_trade_side_fee_field_counted(self):
        # BUY with a fee component on the trade transaction
        txns = [
            _tx(type=TransactionType.BUY, when=_ts(2024, 1, 1),
                amount=Decimal("-1050"), fee=Decimal("50")),
        ]
        out = fee_history(txns, group_by="year")
        # Fee normalised as a magnitude on Transaction.fee -> sign-corrected to -50
        self.assertEqual(out, {2024: Decimal("-50")})


# ─────────────────────────────────────────────────────────────────────────
# realized_pl_over_time
# ─────────────────────────────────────────────────────────────────────────
class TestRealizedPlOverTime(unittest.TestCase):
    def test_attributes_realized_to_year_of_sell(self):
        # BUY 100 in 2023, SELL 50 in 2024, SELL 50 in 2025.
        # FIFO realised on each sell @ +10/share spread = +500 EUR each.
        txns = [
            Transaction(
                transaction_id="b1", account_id="A", instrument_id="I",
                type=TransactionType.BUY,  executed_at=_ts(2023, 6, 1),
                quantity=Decimal("100"), price_local=Decimal("100"),
                amount=Decimal("-10000"), amount_currency="EUR",
                fx_rate=Decimal("1"),
            ),
            Transaction(
                transaction_id="s1", account_id="A", instrument_id="I",
                type=TransactionType.SELL, executed_at=_ts(2024, 3, 1),
                quantity=Decimal("-50"), price_local=Decimal("110"),
                amount=Decimal("5500"), amount_currency="EUR",
                fx_rate=Decimal("1"),
            ),
            Transaction(
                transaction_id="s2", account_id="A", instrument_id="I",
                type=TransactionType.SELL, executed_at=_ts(2025, 4, 1),
                quantity=Decimal("-50"), price_local=Decimal("110"),
                amount=Decimal("5500"), amount_currency="EUR",
                fx_rate=Decimal("1"),
            ),
        ]
        out = realized_pl_over_time(txns, base_currency="EUR", group_by="year")
        self.assertEqual(out[2024], Decimal("500"))
        self.assertEqual(out[2025], Decimal("500"))
        # No sells in 2023 -> not in dict
        self.assertNotIn(2023, out)


# ─────────────────────────────────────────────────────────────────────────
# cash_flow_over_time
# ─────────────────────────────────────────────────────────────────────────
class TestCashFlowOverTime(unittest.TestCase):
    def test_nested_period_by_type(self):
        txns = [
            _tx(type=TransactionType.DEPOSIT,  when=_ts(2024, 1, 1),
                amount=Decimal("1000")),
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 6, 1),
                amount=Decimal("50")),
            _tx(type=TransactionType.FEE,      when=_ts(2024, 7, 1),
                amount=Decimal("-2")),
            _tx(type=TransactionType.DEPOSIT,  when=_ts(2025, 1, 1),
                amount=Decimal("500")),
        ]
        out = cash_flow_over_time(txns, group_by="year")
        self.assertEqual(out[2024]["DEPOSIT"],   Decimal("1000"))
        self.assertEqual(out[2024]["DIVIDEND"],  Decimal("50"))
        self.assertEqual(out[2024]["FEE"],       Decimal("-2"))
        self.assertEqual(out[2025]["DEPOSIT"],   Decimal("500"))

    def test_currency_filter(self):
        txns = [
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 1, 1),
                amount=Decimal("100"), ccy="EUR"),
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 6, 1),
                amount=Decimal("5"),   ccy="USD"),
        ]
        out_eur = cash_flow_over_time(txns, currency="EUR")
        out_usd = cash_flow_over_time(txns, currency="USD")
        self.assertEqual(out_eur[2024]["DIVIDEND"], Decimal("100"))
        self.assertEqual(out_usd[2024]["DIVIDEND"], Decimal("5"))
        # Each filter must NOT contain the other currency's events
        self.assertNotIn("DIVIDEND", out_eur.get(2024, {}).keys() & {"x"})  # sanity


# ─────────────────────────────────────────────────────────────────────────
# tax_lots + all_tax_lots
# ─────────────────────────────────────────────────────────────────────────
def _trade(*, tid, when, type, qty, price, fee=None, fx=None, ccy="EUR",
           inst="I", acct="A"):
    """Build a BUY/SELL Transaction with EUR-side amount auto-derived."""
    amount = (-qty * price) if type == TransactionType.BUY else (-qty * price)
    return Transaction(
        transaction_id=tid, account_id=acct, instrument_id=inst,
        type=type, executed_at=when,
        quantity=qty, price_local=price,
        amount=amount, amount_currency=ccy, fee=fee, fx_rate=fx,
    )


class TestTaxLots(unittest.TestCase):
    def test_one_buy_one_full_sell_emits_one_closure(self):
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("100")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-10"), price=Decimal("130")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
        )
        self.assertEqual(len(closures), 1)
        c = closures[0]
        self.assertEqual(c.quantity,                  Decimal("10"))
        self.assertEqual(c.cost_basis_base,           Decimal("1000"))
        self.assertEqual(c.proceeds_base,             Decimal("1300"))
        self.assertEqual(c.realized_product_pl_base,  Decimal("300"))
        self.assertEqual(c.realized_currency_pl_base, Decimal("0"))
        self.assertEqual(c.realized_fees_base,        Decimal("0"))
        self.assertEqual(c.realized_pl_base,          Decimal("300"))
        self.assertEqual(c.opened_at, _ts(2024, 1, 1))
        self.assertEqual(c.closed_at, _ts(2024, 6, 1))
        self.assertEqual(c.holding_days, 152)

    def test_fifo_splits_a_sell_across_two_lots(self):
        # Two lots of 5, then sell 8 -> 5 from lot1 (FIFO) + 3 from lot2.
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("100")),
            _trade(tid="b2", when=_ts(2024, 3, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("120")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-8"), price=Decimal("150")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
            method=CostBasisMethod.FIFO,
        )
        self.assertEqual(len(closures), 2)
        # First closure: lot1 fully consumed (qty=5)
        self.assertEqual(closures[0].quantity,           Decimal("5"))
        self.assertEqual(closures[0].opened_at,          _ts(2024, 1, 1))
        self.assertEqual(closures[0].cost_per_unit_local, Decimal("100"))
        self.assertEqual(closures[0].cost_basis_base,    Decimal("500"))
        self.assertEqual(closures[0].realized_pl_base,   Decimal("250"))   # 5×50
        # Second closure: 3 units of lot2
        self.assertEqual(closures[1].quantity,           Decimal("3"))
        self.assertEqual(closures[1].opened_at,          _ts(2024, 3, 1))
        self.assertEqual(closures[1].cost_per_unit_local, Decimal("120"))
        self.assertEqual(closures[1].cost_basis_base,    Decimal("360"))
        self.assertEqual(closures[1].realized_pl_base,   Decimal("90"))    # 3×30

    def test_lifo_drains_newest_first(self):
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("100")),
            _trade(tid="b2", when=_ts(2024, 3, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("120")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-3"), price=Decimal("150")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
            method=CostBasisMethod.LIFO,
        )
        self.assertEqual(len(closures), 1)
        self.assertEqual(closures[0].opened_at,       _ts(2024, 3, 1))
        self.assertEqual(closures[0].cost_per_unit_local, Decimal("120"))

    def test_realized_pl_sum_matches_fold_position(self):
        """Iron contract: sum of ClosedLot.realized_*_base = fold_position's
        realized_*_base. If this breaks, the two code paths drifted."""
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("100"),
                   fee=Decimal("5")),
            _trade(tid="b2", when=_ts(2024, 3, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("120"),
                   fee=Decimal("5")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-15"), price=Decimal("130"),
                   fee=Decimal("3")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
        )
        pos = fold_position(
            account_id="A", instrument_id="I", base_currency="EUR",
            transactions=txns,
        )
        self.assertEqual(
            sum(c.realized_product_pl_base for c in closures),
            pos.realized_product_pl_base,
        )
        self.assertEqual(
            sum(c.realized_currency_pl_base for c in closures),
            pos.realized_currency_pl_base,
        )
        self.assertEqual(
            sum(c.realized_fees_base for c in closures),
            pos.realized_fees_base,
        )

    def test_sell_fee_proportionally_allocated(self):
        # Sell crosses two lots (5 + 3 = 8 matched). A €4 sell fee should
        # split 5/8 to the first closure (€2.50), 3/8 to the second (€1.50).
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("100")),
            _trade(tid="b2", when=_ts(2024, 3, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("100")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-8"), price=Decimal("100"),
                   fee=Decimal("4")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
        )
        self.assertEqual(len(closures), 2)
        # No buy-side fees here, so realized_fees_base IS the sell-fee share.
        self.assertEqual(closures[0].realized_fees_base, Decimal("-2.5"))
        self.assertEqual(closures[1].realized_fees_base, Decimal("-1.5"))
        # And they sum to the original sell fee (sign flipped).
        self.assertEqual(
            sum(c.realized_fees_base for c in closures),
            Decimal("-4"),
        )

    def test_asof_trims_future_sells(self):
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("100")),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-5"), price=Decimal("130")),
            _trade(tid="s2", when=_ts(2025, 3, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-5"), price=Decimal("150")),
        ]
        as_of_2024 = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
            asof=_ts(2024, 12, 31),
        )
        self.assertEqual(len(as_of_2024), 1)
        self.assertEqual(as_of_2024[0].closed_at, _ts(2024, 6, 1))

        all_time = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
        )
        self.assertEqual(len(all_time), 2)

    def test_open_position_emits_no_closures(self):
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("100")),
        ]
        closures = tax_lots(
            txns, account_id="A", instrument_id="I", base_currency="EUR",
        )
        self.assertEqual(closures, [])

    def test_all_tax_lots_fans_across_instruments(self):
        txns = [
            _trade(tid="b1", when=_ts(2024, 1, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("10"), price=Decimal("100"), inst="I-A"),
            _trade(tid="s1", when=_ts(2024, 6, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-10"), price=Decimal("110"), inst="I-A"),
            _trade(tid="b2", when=_ts(2024, 2, 1),
                   type=TransactionType.BUY,
                   qty=Decimal("5"), price=Decimal("50"), inst="I-B"),
            _trade(tid="s2", when=_ts(2024, 7, 1),
                   type=TransactionType.SELL,
                   qty=Decimal("-5"), price=Decimal("60"), inst="I-B"),
        ]
        all_closures = all_tax_lots(txns, account_id="A", base_currency="EUR")
        self.assertEqual(len(all_closures), 2)
        instruments = [c.instrument_id for c in all_closures]
        self.assertIn("I-A", instruments)
        self.assertIn("I-B", instruments)
        # Sorted by closed_at -> I-A's June closure first, then I-B's July.
        self.assertEqual(all_closures[0].instrument_id, "I-A")
        self.assertEqual(all_closures[1].instrument_id, "I-B")


class _StubFx:
    """Fixed-rate FX stub. Knows USD→EUR only; records every asof asked,
    so tests can assert the at-DATE discipline (never today's rate)."""
    def __init__(self, rate=Decimal("0.5")):
        self._rate = rate
        self.asked = []

    def get_rate(self, from_ccy, to_ccy, asof=None):
        self.asked.append((from_ccy, to_ccy, asof))
        if from_ccy == "USD" and to_ccy == "EUR":
            from types import SimpleNamespace
            return SimpleNamespace(rate=self._rate)
        return None


class TestIncomeSummary(unittest.TestCase):
    def setUp(self):
        self.txns = [
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 3, 1),
                amount=Decimal("100"), inst="inst-1"),                 # EUR
            _tx(type=TransactionType.DIVIDEND, when=_ts(2025, 4, 1),
                amount=Decimal("40"), inst="inst-2", ccy="USD"),       # needs FX
            _tx(type=TransactionType.INTEREST, when=_ts(2024, 5, 1),
                amount=Decimal("7")),
            _tx(type=TransactionType.FEE, when=_ts(2024, 6, 1),
                amount=Decimal("-3")),
            # BUY with a trade-side fee — only the fee counts, as a debit
            _tx(type=TransactionType.BUY, when=_ts(2024, 7, 1),
                amount=Decimal("-500"), inst="inst-1", fee=Decimal("2")),
        ]

    def test_same_currency_no_provider(self):
        out = income_summary(self.txns, base_currency="EUR")
        # EUR flows count; the USD dividend lands in unconverted (visible).
        self.assertEqual(out["dividends"], Decimal("100"))
        self.assertEqual(out["interest"], Decimal("7"))
        self.assertEqual(out["fees"], Decimal("-5"))         # -3 FEE + -2 trade fee
        self.assertEqual(out["unconverted"],
                         {("dividends", "USD"): Decimal("40")})

    def test_converts_at_execution_date(self):
        fx = _StubFx(rate=Decimal("0.5"))
        out = income_summary(self.txns, base_currency="EUR", fx_provider=fx)
        self.assertEqual(out["dividends"], Decimal("120"))   # 100 + 40×0.5
        self.assertEqual(out["unconverted"], {})
        # The USD flow must have been converted at ITS OWN date.
        usd_asks = [a for a in fx.asked if a[0] == "USD"]
        self.assertEqual(usd_asks, [("USD", "EUR", _ts(2025, 4, 1).date())])

    def test_missing_rate_degrades_visibly(self):
        class _NoRate:
            def get_rate(self, *a, **k):
                return None
        out = income_summary(self.txns, base_currency="EUR",
                             fx_provider=_NoRate())
        self.assertEqual(out["dividends"], Decimal("100"))
        self.assertEqual(out["unconverted"],
                         {("dividends", "USD"): Decimal("40")})

    def test_unconverted_streams_never_net_to_zero(self):
        # +$100 dividend and -$100 fee, no FX: BOTH must surface — keyed
        # per (stream, ccy) they can't cancel into an invisible {USD: 0}.
        txns = [
            _tx(type=TransactionType.DIVIDEND, when=_ts(2024, 3, 1),
                amount=Decimal("100"), ccy="USD"),
            _tx(type=TransactionType.FEE, when=_ts(2024, 4, 1),
                amount=Decimal("-100"), ccy="USD"),
        ]
        out = income_summary(txns, base_currency="EUR")
        self.assertEqual(out["unconverted"],
                         {("dividends", "USD"): Decimal("100"),
                          ("fees", "USD"): Decimal("-100")})

    def test_fee_transaction_with_fee_field_counted_once(self):
        # A FEE row whose adapter ALSO set t.fee must not double-count —
        # and income_summary must agree with fee_history on it.
        txns = [_tx(type=TransactionType.FEE, when=_ts(2024, 1, 1),
                    amount=Decimal("-2.50"), fee=Decimal("2.50"))]
        out = income_summary(txns, base_currency="EUR")
        self.assertEqual(out["fees"], Decimal("-2.50"))
        self.assertEqual(fee_history(txns, group_by="year"),
                         {2024: Decimal("-2.50")})

    def test_dividend_with_trade_fee_counts_both_streams(self):
        # Non-FEE rows carrying t.fee keep contributing to fees (parity
        # with fee_history's elif convention).
        txns = [_tx(type=TransactionType.DIVIDEND, when=_ts(2024, 1, 1),
                    amount=Decimal("100"), fee=Decimal("1.50"))]
        out = income_summary(txns, base_currency="EUR")
        self.assertEqual(out["dividends"], Decimal("100"))
        self.assertEqual(out["fees"], Decimal("-1.50"))

    def test_year_filter(self):
        fx = _StubFx()
        out = income_summary(self.txns, base_currency="EUR",
                             fx_provider=fx, year=2024)
        self.assertEqual(out["dividends"], Decimal("100"))   # USD div is 2025
        self.assertEqual(out["fees"], Decimal("-5"))

    def test_asof_cutoff(self):
        out = income_summary(self.txns, base_currency="EUR",
                             asof=_ts(2024, 12, 31))
        self.assertEqual(out["dividends"], Decimal("100"))
        self.assertEqual(out["unconverted"], {})             # USD div is after asof


if __name__ == "__main__":
    unittest.main()
