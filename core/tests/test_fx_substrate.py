"""sq_fx substrate — lookup + convert helpers.

The actual `FxRateProvider` implementation lives in `modules/sq-fx-ecb/`;
this layer just resolves a provider by name (with fallbacks) and offers a
short-form `convert()`. Tests use a fake provider so they don't depend on
network or a particular bundle being installed.
"""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))                                       # core/
sys.path.insert(0, str(PROJECT_ROOT / "modules" / "sq-fx-ecb" / "src"))    # sq_fx_ecb bundle

import sq_config                                                  # noqa: E402
import sq_fx                                                      # noqa: E402
from sq_schema import FxRate, FxRateProvider                      # noqa: E402


class _FakeProvider:
    """Deterministic FxRateProvider for substrate tests."""
    def __init__(self, rates=None):
        # `rates or {default}` would fall through on rates={}; use is-None
        self.rates = ({("USD", "EUR"): Decimal("0.86")}
                      if rates is None else rates)
        self.calls = []

    def get_rate(self, from_currency, to_currency, asof=None):
        self.calls.append((from_currency, to_currency, asof))
        rate = self.rates.get((from_currency, to_currency))
        if rate is None:
            return None
        now = datetime.now(timezone.utc)
        return FxRate(valid_at=now, observed_at=now,
                      from_currency=from_currency, to_currency=to_currency,
                      rate=rate, source="fake")


class TestProtocolConformance(unittest.TestCase):
    def test_fake_provider_satisfies_protocol(self):
        self.assertIsInstance(_FakeProvider(), FxRateProvider)


class TestConvert(unittest.TestCase):
    def test_same_currency_is_no_op(self):
        # No provider needed — short-circuit returns the amount as-is.
        self.assertEqual(
            sq_fx.convert(Decimal("100"), "EUR", "EUR", provider=_FakeProvider()),
            Decimal("100"),
        )

    def test_convert_uses_supplied_provider(self):
        p = _FakeProvider({("USD", "EUR"): Decimal("0.86")})
        result = sq_fx.convert(Decimal("100"), "USD", "EUR", provider=p)
        self.assertEqual(result, Decimal("86.00000000"))   # quantized to 8dp
        self.assertEqual(p.calls, [("USD", "EUR", None)])

    def test_convert_no_rate_returns_none(self):
        p = _FakeProvider({})
        self.assertIsNone(
            sq_fx.convert(Decimal("100"), "USD", "EUR", provider=p),
        )

    def test_convert_asof_passed_through(self):
        p = _FakeProvider({("USD", "EUR"): Decimal("0.86")})
        asof = date(2026, 3, 15)
        sq_fx.convert(Decimal("100"), "USD", "EUR", provider=p, asof=asof)
        self.assertEqual(p.calls[0][2], asof)

    def test_convert_with_no_provider_and_none_available_returns_none(self):
        # Force the resolution chain to come up empty
        with mock.patch.object(sq_fx, "get_provider", return_value=None):
            self.assertIsNone(
                sq_fx.convert(Decimal("100"), "USD", "EUR"),
            )


class TestGetProviderResolution(unittest.TestCase):
    """Resolution order: explicit arg -> sq_config -> default 'ecb'."""

    def setUp(self):
        # Per-test config dir so we don't touch real user config
        self.tmp = tempfile.mkdtemp(prefix="sq-fx-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def test_unknown_provider_name_returns_none(self):
        self.assertIsNone(sq_fx.get_provider(name="nonexistent-provider"))

    def test_default_resolves_to_ecb_when_sq_fx_ecb_installed(self):
        # sq_fx_ecb IS installed in this venv, so default resolution should work
        provider = sq_fx.get_provider()
        self.assertIsNotNone(provider)
        self.assertEqual(provider.__class__.__name__, "ECBProvider")

    def test_config_override_used_when_set(self):
        sq_config.set("fx_provider", "ecb")
        provider = sq_fx.get_provider()
        self.assertIsNotNone(provider)

    def test_available_lists_installed_providers(self):
        # sq-fx-ecb is in the venv; should appear in available()
        self.assertIn("ecb", sq_fx.available())


class TestStablecoinPeg(unittest.TestCase):
    """USD-stablecoin → USD 1:1 peg fallback (declared approximation).
    Lets a USDC/USDT leg convert into a fiat display total instead of
    dropping out. Pure fiat conversions are unaffected."""

    def _fake_provider(self):
        from sq_schema import FxRate
        class _P:
            def get_rate(self, src, dst, asof=None):
                # Knows only USD↔EUR (like ECB) — NOT stablecoins.
                if src == "USD" and dst == "EUR":
                    return FxRate(valid_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                  observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                  from_currency="USD", to_currency="EUR",
                                  rate=Decimal("0.90"), source="test")
                return None
        return _P()

    def test_usdc_converts_via_usd_peg(self):
        # USDC→EUR: no direct rate → peg USDC=USD → USD→EUR @ 0.90
        out = sq_fx.convert(Decimal("100"), "USDC", "EUR", provider=self._fake_provider())
        self.assertEqual(out, Decimal("90.00000000"))

    def test_usdc_to_usd_is_one_to_one(self):
        out = sq_fx.convert(Decimal("100"), "USDC", "USD", provider=self._fake_provider())
        self.assertEqual(out, Decimal("100.00000000"))

    def test_usdc_to_usdt_is_one_to_one(self):
        out = sq_fx.convert(Decimal("100"), "USDC", "USDT", provider=self._fake_provider())
        self.assertEqual(out, Decimal("100.00000000"))

    def test_unknown_nonstable_still_none(self):
        # A non-stablecoin unknown code must still degrade to None (no fake peg)
        self.assertIsNone(
            sq_fx.convert(Decimal("100"), "XYZ", "EUR", provider=self._fake_provider()))

    def test_fiat_conversion_unaffected(self):
        out = sq_fx.convert(Decimal("100"), "USD", "EUR", provider=self._fake_provider())
        self.assertEqual(out, Decimal("90.00000000"))


if __name__ == "__main__":
    unittest.main()
