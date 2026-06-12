"""sq_aggregator — single-broker iron contract + two-broker concat math.

The single-broker invariant is the load-bearing test: if it ever breaks,
`sciqnt` (no args, aggregated) silently diverges from `sq-degiro live`
(per-broker) and we've lost cent-perfect reconciliation."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_aggregator import (                                           # noqa: E402
    BrokerSnapshot,
    aggregate_asset_class_exposure,
    aggregate_cash,
    aggregate_currency_exposure,
    aggregate_positions,
    aggregate_value,
)
import sq_analytics                                                   # noqa: E402
from sq_schema import (                                               # noqa: E402
    Account, AssetClass, CashBalance, FxRate, FxRateProvider,
    Instrument, PortfolioSnapshot, Position,
)


def _ts(year=2025, month=1, day=1):
    return datetime(year, month, day, tzinfo=timezone.utc)


class _FakeFx:
    """Tiny in-memory FX provider — rates are (src,dst) -> Decimal multiplier.
    Returns an `FxRate` (the protocol contract) or None when no rate exists."""
    def __init__(self, rates: dict[tuple[str, str], Decimal]):
        self.rates = rates

    def get_rate(self, from_currency: str, to_currency: str, *, asof=None):
        if from_currency == to_currency:
            return FxRate(
                valid_at=_ts(), observed_at=_ts(),
                from_currency=from_currency, to_currency=to_currency,
                rate=Decimal("1"), source="test",
            )
        rate = self.rates.get((from_currency, to_currency))
        if rate is None:
            return None
        return FxRate(
            valid_at=_ts(), observed_at=_ts(),
            from_currency=from_currency, to_currency=to_currency,
            rate=rate, source="test",
        )


def _instrument(instrument_id, *, ticker="ABC", isin="US0000000001",
                asset_class=AssetClass.STOCK, ccy="EUR", broker="degiro"):
    return Instrument(
        instrument_id=instrument_id,
        identifiers={"ticker": ticker, "isin": isin,
                     f"broker:{broker}": instrument_id},
        name=f"{ticker} Inc", asset_class=asset_class,
        listing_currency=ccy,
    )


def _position(account_id, instrument_id, *, qty=Decimal("100"),
              value=Decimal("10000"), cost=Decimal("9500"),
              realized_product=Decimal("0"), realized_currency=Decimal("0"),
              realized_fees=Decimal("0"),
              unrealized_product=Decimal("0"), unrealized_currency=Decimal("0")):
    return Position(
        account_id=account_id, instrument_id=instrument_id,
        quantity=qty, value_base=value, cost_basis_base=cost,
        last_price_local=Decimal("100"),
        unrealized_product_pl_base=unrealized_product,
        unrealized_currency_pl_base=unrealized_currency,
        realized_product_pl_base=realized_product,
        realized_currency_pl_base=realized_currency,
        realized_fees_base=realized_fees,
    )


def _snapshot(*, broker, base_ccy, positions, instruments, cash):
    account = Account(account_id=f"{broker}-A1", broker=broker, base_currency=base_ccy)
    return PortfolioSnapshot(
        account=account, instruments=instruments,
        positions=positions, cash_balances=cash,
    )


# ─────────────────────────────────────────────────────────────────────────
# Single-broker iron contract
# ─────────────────────────────────────────────────────────────────────────
class TestSingleBrokerContract(unittest.TestCase):
    """When there's exactly one broker, every aggregator output equals
    what `sq_analytics` produces over that snapshot directly. This is
    the load-bearing reconciliation pin."""

    def _build(self):
        instruments = [
            _instrument("degiro:isin:A", ticker="AAA"),
            _instrument("degiro:isin:B", ticker="BBB"),
        ]
        positions = [
            _position("degiro-A1", "degiro:isin:A",
                      value=Decimal("1200"), cost=Decimal("1000"),
                      unrealized_product=Decimal("200")),
            _position("degiro-A1", "degiro:isin:B",
                      qty=Decimal("0"), value=Decimal("0"), cost=Decimal("0"),
                      realized_product=Decimal("150"),
                      realized_fees=Decimal("-5")),
        ]
        cash = [
            CashBalance(account_id="degiro-A1", currency="EUR",
                        amount=Decimal("500")),
        ]
        snap = _snapshot(broker="degiro", base_ccy="EUR",
                         positions=positions, instruments=instruments,
                         cash=cash)
        return snap, instruments, positions, cash

    def test_value_totals_match_naive_sums(self):
        snap, _, positions, _ = self._build()
        brokers = [BrokerSnapshot(broker="degiro", snapshot=snap)]
        out = aggregate_value(brokers, display_currency="EUR")
        # Display ccy == base ccy, no FX involved — totals must equal naive sums.
        self.assertEqual(out.positions_value,     Decimal("1200"))
        self.assertEqual(out.cash_value,          Decimal("500"))
        self.assertEqual(out.total_value,         Decimal("1700"))
        self.assertEqual(out.total_realized_pl,   sum((p.realized_pl_base for p in positions), Decimal("0")))
        self.assertEqual(out.total_unrealized_pl, sum((p.unrealized_pl_base for p in positions), Decimal("0")))
        self.assertEqual(out.total_pl_lifetime,   sum((p.total_pl_base for p in positions), Decimal("0")))
        self.assertEqual(out.open_position_count,   1)
        self.assertEqual(out.closed_position_count, 1)
        self.assertEqual(out.unconverted_cash,    [])

    def test_currency_exposure_equals_sq_analytics_single(self):
        snap, instruments, positions, cash = self._build()
        brokers = [BrokerSnapshot(broker="degiro", snapshot=snap)]
        agg = aggregate_currency_exposure(brokers, display_currency="EUR")
        ref = sq_analytics.currency_exposure(
            positions, cash, instruments, base_currency="EUR",
        )
        self.assertEqual(agg, ref)

    def test_asset_class_exposure_equals_sq_analytics_single(self):
        snap, instruments, positions, _ = self._build()
        brokers = [BrokerSnapshot(broker="degiro", snapshot=snap)]
        agg, skipped = aggregate_asset_class_exposure(
            brokers, display_currency="EUR")
        ref = sq_analytics.asset_class_exposure(
            positions, instruments, base_currency="EUR",
        )
        self.assertEqual(agg, ref)
        self.assertEqual(skipped, [])      # same-ccy: nothing excluded

    def test_flat_positions_preserves_order_and_tags_broker(self):
        snap, _, _, _ = self._build()
        brokers = [BrokerSnapshot(broker="degiro", snapshot=snap)]
        flat = aggregate_positions(brokers)
        self.assertEqual(len(flat), 2)
        for broker_name, _pos, _inst in flat:
            self.assertEqual(broker_name, "degiro")

    def test_failed_broker_skipped_not_raised(self):
        brokers = [BrokerSnapshot(broker="degiro", snapshot=None,
                                  error="ConnectionRefused")]
        out = aggregate_value(brokers, display_currency="EUR")
        # No ok brokers -> totals are the zero baseline; never raises.
        self.assertEqual(out.positions_value, Decimal("0"))
        self.assertEqual(out.cash_value,      Decimal("0"))
        self.assertEqual(out.total_value,     Decimal("0"))


# ─────────────────────────────────────────────────────────────────────────
# Two-broker concat / aggregation math
# ─────────────────────────────────────────────────────────────────────────
class TestTwoBrokerAggregation(unittest.TestCase):
    def _two_brokers(self):
        # Degiro: EUR base. 1 open position worth 1200 EUR, 100 EUR cash.
        # IBKR:   USD base. 1 open position worth 2000 USD,   0 cash.
        deg = _snapshot(
            broker="degiro", base_ccy="EUR",
            instruments=[_instrument("degiro:isin:A", broker="degiro")],
            positions=[_position("degiro-A1", "degiro:isin:A",
                                 value=Decimal("1200"), cost=Decimal("1000"),
                                 realized_product=Decimal("50"))],
            cash=[CashBalance(account_id="degiro-A1", currency="EUR",
                              amount=Decimal("100"))],
        )
        ibkr = _snapshot(
            broker="ibkr", base_ccy="USD",
            instruments=[_instrument("ibkr:isin:B", ticker="BBB",
                                     ccy="USD", broker="ibkr")],
            positions=[_position("ibkr-A1", "ibkr:isin:B",
                                 value=Decimal("2000"), cost=Decimal("1800"),
                                 realized_product=Decimal("100"))],
            cash=[],
        )
        fx = _FakeFx({("USD", "EUR"): Decimal("0.9")})
        return [
            BrokerSnapshot(broker="degiro", snapshot=deg),
            BrokerSnapshot(broker="ibkr",   snapshot=ibkr),
        ], fx

    def test_totals_fx_converted_to_display(self):
        brokers, fx = self._two_brokers()
        out = aggregate_value(brokers, display_currency="EUR", fx_provider=fx)
        # positions: 1200 EUR + 2000 USD × 0.9 = 1200 + 1800 = 3000
        self.assertEqual(out.positions_value, Decimal("3000.0"))
        # cash: 100 EUR + nothing else = 100
        self.assertEqual(out.cash_value, Decimal("100"))
        self.assertEqual(out.total_value, Decimal("3100.0"))
        # realized: 50 EUR + 100 USD × 0.9 = 50 + 90 = 140
        self.assertEqual(out.total_realized_pl, Decimal("140.0"))

    def test_partial_when_no_rate_available(self):
        brokers, _ = self._two_brokers()
        # No FX provider at all — USD legs cannot be priced into EUR.
        # The mathematical contract: USD positions DON'T fold into
        # positions_value (poisons to None), and USD cash legs are NOT
        # added either. Single ok broker matters: degiro's EUR legs convert
        # trivially; IBKR's USD legs surface as unconverted.
        # We also tighten the fake-fx provider to return None to be safe.
        fx = _FakeFx({})  # empty -> no rate for USD->EUR
        out = aggregate_value(brokers, display_currency="EUR", fx_provider=fx)
        self.assertIsNone(out.positions_value)
        self.assertIsNone(out.total_value)
        # cash: only EUR was convertible
        self.assertEqual(out.cash_value, Decimal("100"))
        # P/L sums for IBKR (USD) didn't convert, so they're None too
        self.assertIsNone(out.total_realized_pl)

    def test_flat_positions_concatenated_with_broker_tags(self):
        brokers, _ = self._two_brokers()
        flat = aggregate_positions(brokers)
        names = sorted({b for b, _, _ in flat})
        self.assertEqual(names, ["degiro", "ibkr"])
        # Every position is paired with its own Instrument
        for _, pos, inst in flat:
            self.assertEqual(pos.instrument_id, inst.instrument_id)

    def test_per_broker_breakdown_is_in_native_base_ccy(self):
        brokers, fx = self._two_brokers()
        out = aggregate_value(brokers, display_currency="EUR", fx_provider=fx)
        by_broker = {pb["broker"]: pb for pb in out.per_broker}
        self.assertEqual(by_broker["degiro"]["base_currency"], "EUR")
        self.assertEqual(by_broker["degiro"]["positions_value_base"], Decimal("1200"))
        self.assertEqual(by_broker["ibkr"]["base_currency"], "USD")
        self.assertEqual(by_broker["ibkr"]["positions_value_base"], Decimal("2000"))


# ─────────────────────────────────────────────────────────────────────────
# Multi-currency cash with one unconverted leg
# ─────────────────────────────────────────────────────────────────────────
class TestUnconvertedLeg(unittest.TestCase):
    def test_unconverted_cash_surfaces_in_native_ccy(self):
        snap = _snapshot(
            broker="degiro", base_ccy="EUR",
            instruments=[],
            positions=[],
            cash=[
                CashBalance(account_id="degiro-A1", currency="EUR",
                            amount=Decimal("50")),
                CashBalance(account_id="degiro-A1", currency="XAU",   # gold; no rate
                            amount=Decimal("3")),
            ],
        )
        brokers = [BrokerSnapshot(broker="degiro", snapshot=snap)]
        fx = _FakeFx({})  # no rates configured for XAU
        out = aggregate_value(brokers, display_currency="EUR", fx_provider=fx)
        self.assertEqual(out.cash_value, Decimal("50"))           # converted leg
        self.assertEqual(out.unconverted_cash,
                         [("degiro", "XAU", Decimal("3"))])
        # total_value MUST go None whenever any leg is unconverted
        self.assertIsNone(out.total_value)


class TestExposureMixedCurrencies(unittest.TestCase):
    """Audit find 2026-06-11: the exposure tables used to concatenate
    EUR and USD value_base sums into one number. Money fields must be
    FX-converted to the display currency; unconvertible brokers are
    excluded AND reported, never silently summed."""

    def _two_brokers(self):
        eur = _snapshot(
            broker="degiro", base_ccy="EUR",
            instruments=[_instrument("degiro:isin:A", ticker="AAA")],
            positions=[_position("degiro-A1", "degiro:isin:A",
                                 value=Decimal("1000"),
                                 cost=Decimal("800"))],
            cash=[],
        )
        usd = _snapshot(
            broker="robinhood", base_ccy="USD",
            instruments=[_instrument("rh:X", ticker="XXX", ccy="USD",
                                     broker="robinhood")],
            positions=[_position("robinhood-A1", "rh:X",
                                 value=Decimal("1000"),
                                 cost=Decimal("900"))],
            cash=[],
        )
        return [BrokerSnapshot(broker="degiro", snapshot=eur),
                BrokerSnapshot(broker="robinhood", snapshot=usd)]

    def test_values_converted_not_concatenated(self):
        fx = _FakeFx({("USD", "EUR"): Decimal("0.5")})
        agg, skipped = aggregate_asset_class_exposure(
            self._two_brokers(), display_currency="EUR", fx_provider=fx)
        self.assertEqual(skipped, [])
        # 1000 EUR + 1000 USD × 0.5 = 1500 EUR — NOT a raw 2000
        self.assertEqual(agg["STOCK"]["value_base"], Decimal("1500"))
        self.assertEqual(agg["STOCK"]["cost_basis_base"],
                         Decimal("800") + Decimal("450"))

    def test_unconvertible_broker_excluded_and_reported(self):
        fx = _FakeFx({})                       # no USD rate
        agg, skipped = aggregate_asset_class_exposure(
            self._two_brokers(), display_currency="EUR", fx_provider=fx)
        self.assertEqual(agg["STOCK"]["value_base"], Decimal("1000"))
        self.assertEqual(skipped, [("robinhood", "USD", 1)])


if __name__ == "__main__":
    unittest.main()
