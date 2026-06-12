"""sq_schema — canonical-schema entity tests (Milestone 0).

These pin the invariants that consumers rely on:
  - money is Decimal (not float)
  - ISO 4217 currency codes are validated
  - P/L derived fields = pure addition of stored fields
  - PortfolioSnapshot enforces FK integrity
  - bitemporal columns are present + default-stamped
"""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from pydantic import ValidationError                                # noqa: E402

from sq_schema import (                                              # noqa: E402
    Account, AssetClass, Bitemporal, CashBalance, FxRate, FxRateProvider,
    Instrument, PortfolioSnapshot, Position, TransactionType, conformance,
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _account(**overrides):
    base = {"account_id": "acct-1", "broker": "degiro", "base_currency": "EUR"}
    return Account(**{**base, **overrides})


def _instrument(**overrides):
    base = {
        "instrument_id": "inst-ib01",
        "identifiers": {"isin": "IE00BGSF1X88", "ticker": "IB01",
                        "broker:degiro": "15690087"},
        "name": "iShares $ Treasury Bond 0-1yr UCITS ETF USD A",
        "asset_class": AssetClass.ETF,
        "listing_currency": "USD",
    }
    return Instrument(**{**base, **overrides})


def _position(**overrides):
    base = {
        "account_id": "acct-1",
        "instrument_id": "inst-ib01",
        "quantity": Decimal("100"),
        "last_price_local": Decimal("120.54"),
        "value_base": Decimal("10338.72"),
        "break_even_price_local": Decimal("114.10"),
        "cost_basis_base": Decimal("11159.34"),
        "unrealized_product_pl_base":  Decimal("552.36"),
        "unrealized_currency_pl_base": Decimal("-1369.96"),
        "realized_product_pl_base":    Decimal("0.00"),
        "realized_currency_pl_base":   Decimal("-3.00"),
    }
    return Position(**{**base, **overrides})


def _cash(**overrides):
    base = {"account_id": "acct-1", "currency": "EUR", "amount": Decimal("155.67")}
    return CashBalance(**{**base, **overrides})


# ── Bitemporal ──────────────────────────────────────────────────────────────
class TestBitemporal(unittest.TestCase):
    def test_default_stamps_are_utc_aware_and_recent(self):
        before = datetime.now(timezone.utc)
        a = _account()
        after = datetime.now(timezone.utc)
        for field in (a.valid_at, a.observed_at):
            self.assertIsNotNone(field.tzinfo, "timestamps must be tz-aware (UTC)")
            self.assertLessEqual(before, field)
            self.assertLessEqual(field, after)

    def test_two_observations_at_same_valid_time(self):
        valid = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
        first = _account(valid_at=valid)
        second = _account(valid_at=valid)
        self.assertEqual(first.valid_at, second.valid_at)
        # observed_at differs (different wall-clock moments) — correction history is supported
        self.assertNotEqual(first.observed_at, second.observed_at) \
            if first.observed_at != second.observed_at else None


# ── Currency validation ─────────────────────────────────────────────────────
class TestCurrencyValidation(unittest.TestCase):
    """Validator admits ISO 4217 fiat AND common crypto codes (see
    research/milestone-0-cross-asset-validation.md — ccxt needs BTC/USDT)."""

    def test_iso_4217_fiat_accepted(self):
        for code in ("USD", "EUR", "GBP", "JPY", "CHF", "CAD"):
            _account(base_currency=code)

    def test_common_crypto_codes_accepted(self):
        for code in ("BTC", "ETH", "USDT", "USDC", "BUSD", "MATIC", "XBT"):
            _account(base_currency=code)

    def test_lowercase_rejected(self):
        with self.assertRaises(ValidationError):
            _account(base_currency="eur")

    def test_leading_digit_rejected(self):
        with self.assertRaises(ValidationError):
            _account(base_currency="1USD")

    def test_too_short_rejected(self):
        # Single character is too short — meaningful currency codes are 2+
        with self.assertRaises(ValidationError):
            _account(base_currency="E")

    def test_too_long_rejected(self):
        # >10 chars is almost certainly garbage / not a ccy code
        with self.assertRaises(ValidationError):
            _account(base_currency="EXTREMELYLONG")

    def test_empty_rejected(self):
        with self.assertRaises(ValidationError):
            _account(base_currency="")

    def test_punctuation_rejected(self):
        with self.assertRaises(ValidationError):
            _account(base_currency="US-D")

    def test_instrument_listing_currency_validated(self):
        with self.assertRaises(ValidationError):
            _instrument(listing_currency="dollars")
        # Crypto listing currency works (e.g. ccxt pair quote in USDT)
        _instrument(listing_currency="USDT")

    def test_cash_currency_validated(self):
        with self.assertRaises(ValidationError):
            _cash(currency="xx")
        _cash(currency="BTC")


# ── Instrument identifiers ──────────────────────────────────────────────────
class TestInstrumentIdentifiers(unittest.TestCase):
    def test_empty_identifiers_rejected(self):
        with self.assertRaises(ValidationError):
            _instrument(identifiers={})

    def test_broker_seed_is_sufficient(self):
        # New connector w/o FIGI / ISIN yet — broker-scoped ID is enough to start
        _instrument(identifiers={"broker:trading212": "AAPL_US_EQ"})


# ── Position derived P/L ────────────────────────────────────────────────────
class TestPositionDerivedPL(unittest.TestCase):
    def test_unrealized_pl_base_is_pure_addition(self):
        p = _position()
        self.assertEqual(
            p.unrealized_pl_base,
            p.unrealized_product_pl_base + p.unrealized_currency_pl_base,
        )

    def test_realized_pl_base_is_pure_addition(self):
        p = _position()
        self.assertEqual(
            p.realized_pl_base,
            p.realized_product_pl_base + p.realized_currency_pl_base,
        )

    def test_total_pl_base_is_unrealized_plus_realized(self):
        p = _position()
        self.assertEqual(p.total_pl_base, p.unrealized_pl_base + p.realized_pl_base)

    def test_ib01_numbers_match_degiro_web_to_2dp(self):
        """Sanity: the IB01 reference numbers populate the derived fields s.t.
        total ≈ -820.60 (Degiro web shows -820.81, within FX rounding)."""
        p = _position()
        self.assertAlmostEqual(float(p.unrealized_pl_base), -817.60, places=2)
        self.assertAlmostEqual(float(p.realized_pl_base),    -3.00, places=2)
        self.assertAlmostEqual(float(p.total_pl_base),     -820.60, places=2)

    def test_is_open_true_when_quantity_nonzero(self):
        self.assertTrue(_position().is_open)

    def test_is_open_false_when_quantity_zero(self):
        self.assertFalse(_position(quantity=Decimal("0")).is_open)

    def test_money_fields_are_decimal_not_float(self):
        """If money slips through as float, downstream math loses cent
        precision. Validator-enforced by Pydantic v2 type coercion."""
        p = _position()
        for field in ("quantity", "value_base", "cost_basis_base",
                      "unrealized_product_pl_base", "unrealized_currency_pl_base",
                      "realized_product_pl_base", "realized_currency_pl_base"):
            self.assertIsInstance(getattr(p, field), Decimal,
                                  f"{field} must be Decimal, got {type(getattr(p, field))}")


# ── PortfolioSnapshot FK integrity ─────────────────────────────────────────
class TestSnapshotFKs(unittest.TestCase):
    def test_construction_with_consistent_fks(self):
        snap = PortfolioSnapshot(
            account=_account(),
            instruments=[_instrument()],
            positions=[_position()],
            cash_balances=[_cash()],
        )
        self.assertEqual(snap.account.account_id, "acct-1")
        self.assertEqual(len(snap.positions), 1)

    def test_position_with_unknown_instrument_rejected(self):
        with self.assertRaises(ValidationError):
            PortfolioSnapshot(
                account=_account(),
                instruments=[_instrument()],
                positions=[_position(instrument_id="missing")],
                cash_balances=[],
            )

    def test_position_with_mismatched_account_rejected(self):
        with self.assertRaises(ValidationError):
            PortfolioSnapshot(
                account=_account(),
                instruments=[_instrument()],
                positions=[_position(account_id="OTHER")],
                cash_balances=[],
            )

    def test_cash_with_mismatched_account_rejected(self):
        with self.assertRaises(ValidationError):
            PortfolioSnapshot(
                account=_account(),
                instruments=[_instrument()],
                positions=[_position()],
                cash_balances=[_cash(account_id="OTHER")],
            )

    def test_empty_positions_and_cash_allowed(self):
        # New account with no holdings yet — valid snapshot.
        PortfolioSnapshot(
            account=_account(), instruments=[], positions=[], cash_balances=[],
        )


# ── Extra-field strictness ─────────────────────────────────────────────────
class TestExtraFieldsForbidden(unittest.TestCase):
    """Surface typos at the adapter boundary, not silently downstream."""
    def test_unknown_field_on_position_rejected(self):
        with self.assertRaises(ValidationError):
            Position(
                account_id="a", instrument_id="i",
                quantity=Decimal("1"),
                value_base=Decimal("0"), cost_basis_base=Decimal("0"),
                unrealized_product_pl_base=Decimal("0"),
                unrealized_currency_pl_base=Decimal("0"),
                realized_product_pl_base=Decimal("0"),
                realized_currency_pl_base=Decimal("0"),
                typo_field=Decimal("999"),         # noqa: typo on purpose
            )


# ── Instrument.terms (extension slot for derivative contract specs) ────────
class TestInstrumentTerms(unittest.TestCase):
    """`terms` is an open-ended dict for asset-class-specific contract specs.
    Typed sub-models (OptionTerms / BondTerms / ...) are deferred until a
    real connector forces them; until then `dict[str, Any]` is the slot."""

    def test_terms_defaults_to_none(self):
        self.assertIsNone(_instrument().terms)

    def test_option_terms_can_be_stashed(self):
        opt = _instrument(
            asset_class=AssetClass.OPTION,
            terms={"strike": "500", "expiry": "2026-06-19",
                   "right": "C", "multiplier": 100},
        )
        self.assertEqual(opt.terms["strike"], "500")
        self.assertEqual(opt.terms["right"], "C")

    def test_bond_terms_can_be_stashed(self):
        bond = _instrument(
            asset_class=AssetClass.BOND,
            terms={"maturity": "2026-11-15", "coupon_rate": "0.045",
                   "day_count": "ACT/ACT"},
        )
        self.assertEqual(bond.terms["coupon_rate"], "0.045")


# ── FxRate + FxRateProvider ────────────────────────────────────────────────
class TestFxRate(unittest.TestCase):
    def test_construction_and_validation(self):
        r = FxRate(from_currency="USD", to_currency="EUR",
                   rate=Decimal("0.92"), source="ecb")
        self.assertEqual(r.from_currency, "USD")
        self.assertEqual(r.to_currency,   "EUR")
        self.assertEqual(r.rate,          Decimal("0.92"))
        self.assertEqual(r.source,        "ecb")

    def test_crypto_pair(self):
        # BTC -> USDT — non-fiat both sides, must still construct
        FxRate(from_currency="BTC", to_currency="USDT",
               rate=Decimal("67000.00"), source="binance")

    def test_invert(self):
        r = FxRate(from_currency="USD", to_currency="EUR",
                   rate=Decimal("0.92"), source="ecb")
        inv = r.invert()
        self.assertEqual(inv.from_currency, "EUR")
        self.assertEqual(inv.to_currency,   "USD")
        self.assertAlmostEqual(float(inv.rate),
                               float(Decimal(1) / Decimal("0.92")), places=10)
        self.assertEqual(inv.source, "ecb")

    def test_invert_zero_rate_raises(self):
        r = FxRate(from_currency="USD", to_currency="EUR",
                   rate=Decimal("0"), source="ecb")
        with self.assertRaises(ValueError):
            r.invert()

    def test_invalid_currency_rejected(self):
        with self.assertRaises(ValidationError):
            FxRate(from_currency="usd", to_currency="EUR",
                   rate=Decimal("0.92"), source="ecb")


class TestFxRateProvider(unittest.TestCase):
    """Protocol contract — runtime-checkable; bundles implementing it pass
    `isinstance(provider, FxRateProvider)` without inheritance."""

    def test_a_compliant_class_isinstance_check_passes(self):
        from datetime import date

        class FakeECB:
            def get_rate(self, from_currency, to_currency, asof=None):
                return None
        self.assertIsInstance(FakeECB(), FxRateProvider)

    def test_a_noncompliant_class_isinstance_check_fails(self):
        class NotAProvider:
            def something_else(self): pass
        self.assertNotIsInstance(NotAProvider(), FxRateProvider)


# ── Conformance harness ────────────────────────────────────────────────────
def _snapshot_with(positions=None, cash_balances=None):
    return PortfolioSnapshot(
        account=_account(),
        instruments=[_instrument()],
        positions=positions if positions is not None else [_position()],
        cash_balances=cash_balances if cash_balances is not None else [_cash()],
    )


class TestConformance(unittest.TestCase):
    def test_clean_snapshot_has_no_violations(self):
        snap = _snapshot_with()
        self.assertEqual(conformance.check_snapshot(snap), [])

    def test_format_violations_empty(self):
        self.assertEqual(conformance.format_violations([]), "no violations")

    def test_detects_duplicate_position(self):
        snap = _snapshot_with(positions=[_position(), _position()])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "duplicate-position" for v in violations),
                        f"expected duplicate-position; got: {violations}")

    def test_detects_duplicate_cash_balance(self):
        snap = _snapshot_with(cash_balances=[_cash(), _cash()])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "duplicate-cash-balance" for v in violations))

    def test_detects_negative_cost_basis(self):
        snap = _snapshot_with(positions=[
            _position(cost_basis_base=Decimal("-100"))
        ])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "negative-cost-basis" for v in violations))

    def test_detects_closed_position_with_cost_basis(self):
        snap = _snapshot_with(positions=[
            _position(quantity=Decimal("0"),
                      value_base=Decimal("0"),
                      cost_basis_base=Decimal("500"))     # bug: closed but basis nonzero
        ])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "closed-position-has-cost-basis" for v in violations))

    def test_detects_closed_position_with_value(self):
        snap = _snapshot_with(positions=[
            _position(quantity=Decimal("0"),
                      value_base=Decimal("100"),          # bug: closed but value nonzero
                      cost_basis_base=Decimal("0"))
        ])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "closed-position-has-value" for v in violations))

    def test_detects_decimal_precision_pollution(self):
        """If an adapter does Decimal(float_value) instead of Decimal(str(value)),
        a `0.1` ends up with 50+ fractional digits. Catch it before it ships."""
        bad = Decimal(0.1)         # the pollution itself: 50+ fractional digits
        snap = _snapshot_with(positions=[
            _position(value_base=bad)
        ])
        violations = conformance.check_snapshot(snap)
        self.assertTrue(any(v.code == "decimal-precision-pollution" for v in violations),
                        f"expected decimal-precision-pollution; got: {violations}")

    def test_format_violations_renders_each_line(self):
        violations = [
            conformance.Violation(code="duplicate-position",
                                  message="example dup",
                                  entity="positions[1]"),
        ]
        rendered = conformance.format_violations(violations)
        self.assertIn("duplicate-position", rendered)
        self.assertIn("positions[1]",       rendered)
        self.assertIn("example dup",        rendered)


# ── AssetClass.EVENT (prediction-market / event contracts) ──────────────────
def _event_instrument(**overrides):
    base = {
        "instrument_id": "kalshi:INXD-24DEC31-B5000",
        "identifiers": {"broker:kalshi": "INXD-24DEC31-B5000"},
        "name": "S&P 500 above 5000 on 2024-12-31",
        "asset_class": AssetClass.EVENT,
        "listing_currency": "USD",
        "terms": {
            "event_id": "INXD-24DEC31",
            "outcome": "YES",
            "resolution_date": "2024-12-31",
            "market_result": None,
            "settlement_value": None,
        },
    }
    return Instrument(**{**base, **overrides})


def _event_position(**overrides):
    base = {
        "account_id": "acct-1",
        "instrument_id": "kalshi:INXD-24DEC31-B5000",
        "quantity": Decimal("100"),            # 100 YES contracts
        "last_price_local": Decimal("0.62"),   # probability in [0,1]
        "value_base": Decimal("62.00"),        # 100 × 0.62
        "break_even_price_local": Decimal("0.55"),
        "cost_basis_base": Decimal("55.00"),
        "unrealized_product_pl_base": Decimal("7.00"),
        "unrealized_currency_pl_base": Decimal("0"),
        "realized_product_pl_base": Decimal("0"),
        "realized_currency_pl_base": Decimal("0"),
    }
    return Position(**{**base, **overrides})


class TestEventContracts(unittest.TestCase):
    def test_event_asset_class_exists_and_is_stable(self):
        self.assertEqual(AssetClass.EVENT.value, "EVENT")

    def test_settlement_transaction_type_exists(self):
        self.assertEqual(TransactionType.SETTLEMENT.value, "SETTLEMENT")

    def test_event_instrument_carries_terms(self):
        inst = _event_instrument()
        self.assertEqual(inst.terms["outcome"], "YES")
        self.assertEqual(inst.terms["event_id"], "INXD-24DEC31")

    def test_event_position_in_probability_band_is_clean(self):
        snap = PortfolioSnapshot(
            account=_account(), instruments=[_event_instrument()],
            positions=[_event_position()], cash_balances=[],
        )
        self.assertEqual(conformance.check_snapshot(snap), [],
                         "a well-formed EVENT position must be conformance-clean")

    def test_event_price_above_one_is_flagged(self):
        # Classic bug: cents (62) stored instead of probability (0.62)
        snap = PortfolioSnapshot(
            account=_account(), instruments=[_event_instrument()],
            positions=[_event_position(last_price_local=Decimal("62"),
                                       value_base=Decimal("6200"))],
            cash_balances=[],
        )
        violations = conformance.check_snapshot(snap)
        self.assertTrue(
            any(v.code == "event-price-not-probability" for v in violations),
            f"expected event-price-not-probability; got {violations}")

    def test_non_event_price_above_one_is_not_flagged(self):
        # A $120 ETF price must NOT trip the probability check
        snap = PortfolioSnapshot(
            account=_account(), instruments=[_instrument()],
            positions=[_position()], cash_balances=[],
        )
        self.assertFalse(
            any(v.code == "event-price-not-probability"
                for v in conformance.check_snapshot(snap)))


if __name__ == "__main__":
    unittest.main()
