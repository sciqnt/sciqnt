"""sq_market_data — overlay tests + Price/PriceProvider schema tests.

The overlay is pure compute given (positions, instruments, provider).
Tests use a fake PriceProvider so they don't touch the network."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from pydantic import ValidationError                              # noqa: E402

from sq_market_data import overlay_prices                          # noqa: E402
from sq_schema import (                                            # noqa: E402
    AssetClass, FxRate, FxRateProvider, Instrument, Position,
    Price, PriceProvider,
)


def _now():
    return datetime.now(timezone.utc)


class _FakePriceProvider:
    """Deterministic; returns the configured price per ticker. None for unknown."""
    def __init__(self, prices: dict):
        self.prices = prices         # {ticker: (price, currency)}
        self.calls = []

    def get_price(self, ticker: str):
        self.calls.append(ticker)
        entry = self.prices.get(ticker)
        if entry is None:
            return None
        price, ccy = entry
        return Price(
            valid_at=_now(), observed_at=_now(),
            last_price_local=price, currency=ccy, source="fake",
        )


class _FakeFxProvider:
    def __init__(self, rates: dict):
        self.rates = rates           # {(from, to): rate}

    def get_rate(self, from_currency, to_currency, asof=None):
        r = self.rates.get((from_currency, to_currency))
        if r is None:
            return None
        return FxRate(
            valid_at=_now(), observed_at=_now(),
            from_currency=from_currency, to_currency=to_currency,
            rate=r, source="fake",
        )


# ─────────────────────────────────────────────────────────────────────────
# Schema tests for Price + PriceProvider
# ─────────────────────────────────────────────────────────────────────────
class TestPriceSchema(unittest.TestCase):
    def test_basic_construction(self):
        p = Price(last_price_local=Decimal("100.50"),
                  currency="EUR", source="yahoo")
        self.assertEqual(p.last_price_local, Decimal("100.50"))
        self.assertEqual(p.currency, "EUR")
        self.assertIsNone(p.instrument_id)

    def test_invalid_currency_rejected(self):
        with self.assertRaises(ValidationError):
            Price(last_price_local=Decimal("1"), currency="eur", source="x")

    def test_protocol_isinstance(self):
        self.assertIsInstance(_FakePriceProvider({}), PriceProvider)


# ─────────────────────────────────────────────────────────────────────────
# Overlay — same-currency case
# ─────────────────────────────────────────────────────────────────────────
class TestOverlaySameCurrency(unittest.TestCase):
    def setUp(self):
        # Open EUR-listed position bought at 100, current price 120.
        self.inst = Instrument(
            instrument_id="i", identifiers={"ticker": "X"},
            name="X Corp", asset_class=AssetClass.STOCK,
            listing_currency="EUR",
        )
        self.pos = Position(
            account_id="A", instrument_id="i",
            quantity=Decimal("10"), break_even_price_local=Decimal("100"),
            cost_basis_base=Decimal("1000"),
        )
        self.provider = _FakePriceProvider({"X": (Decimal("120"), "EUR")})

    def test_overlay_populates_value_and_unrealized(self):
        out = overlay_prices(
            [self.pos], [self.inst],
            provider=self.provider, base_currency="EUR",
        )
        self.assertEqual(len(out), 1)
        p = out[0]
        self.assertEqual(p.last_price_local, Decimal("120"))
        self.assertEqual(p.value_base,        Decimal("1200"))
        # Same currency → no currency component
        self.assertEqual(p.unrealized_currency_pl_base, Decimal("0"))
        # Product = (120-100)*10*1 = 200
        self.assertEqual(p.unrealized_product_pl_base,  Decimal("200"))
        self.assertEqual(p.unrealized_pl_base,          Decimal("200"))

    def test_overlay_is_non_destructive(self):
        out = overlay_prices(
            [self.pos], [self.inst],
            provider=self.provider, base_currency="EUR",
        )
        self.assertEqual(self.pos.last_price_local,  None)
        self.assertEqual(self.pos.value_base,        Decimal("0"))
        self.assertNotEqual(out[0], self.pos)


# ─────────────────────────────────────────────────────────────────────────
# Overlay — cross-currency case with explicit fx_provider
# ─────────────────────────────────────────────────────────────────────────
class TestOverlayCrossCurrency(unittest.TestCase):
    def test_uses_fx_provider_when_supplied(self):
        # USD-listed bought when EUR/USD was 0.90 → cost_basis 9,000 EUR.
        # Current price 120 USD, current EUR/USD 0.85.
        # Expected:
        #   value_base   = 100 × 120 × 0.85 = 10,200 EUR
        #   product_pl   = (120-100) × 100 × 0.85 = +1,700 EUR
        #   currency_pl  = value - cost - product = 10,200 - 9,000 - 1,700 = -500 EUR
        inst = Instrument(
            instrument_id="i", identifiers={"ticker": "X"},
            name="X", asset_class=AssetClass.STOCK,
            listing_currency="USD",
        )
        pos = Position(
            account_id="A", instrument_id="i",
            quantity=Decimal("100"),
            break_even_price_local=Decimal("100"),
            cost_basis_base=Decimal("9000"),
        )
        prices = _FakePriceProvider({"X": (Decimal("120"), "USD")})
        fxp    = _FakeFxProvider({("USD", "EUR"): Decimal("0.85")})
        out = overlay_prices(
            [pos], [inst],
            provider=prices, fx_provider=fxp, base_currency="EUR",
        )
        p = out[0]
        self.assertEqual(p.value_base,                  Decimal("10200.00"))
        self.assertEqual(p.unrealized_product_pl_base,  Decimal("1700.00"))
        self.assertEqual(p.unrealized_currency_pl_base, Decimal("-500.00"))
        self.assertEqual(p.unrealized_pl_base,          Decimal("1200.00"))

    def test_falls_back_to_avg_fx_when_no_provider(self):
        """No fx_provider → derive avg FX from existing cost basis. The
        unrealised currency component is zero (we don't know current FX),
        but the product component is honest."""
        inst = Instrument(
            instrument_id="i", identifiers={"ticker": "X"},
            name="X", asset_class=AssetClass.STOCK,
            listing_currency="USD",
        )
        pos = Position(
            account_id="A", instrument_id="i",
            quantity=Decimal("100"),
            break_even_price_local=Decimal("100"),
            cost_basis_base=Decimal("9000"),     # avg fx at acquisition = 0.90
        )
        prices = _FakePriceProvider({"X": (Decimal("120"), "USD")})
        out = overlay_prices(
            [pos], [inst],
            provider=prices, base_currency="EUR",   # no fx_provider
        )
        p = out[0]
        # current_fx falls back to avg = 0.90
        self.assertEqual(p.value_base,                  Decimal("10800.00"))
        self.assertEqual(p.unrealized_product_pl_base,  Decimal("1800.00"))
        # value - cost - product = 10800 - 9000 - 1800 = 0
        self.assertEqual(p.unrealized_currency_pl_base, Decimal("0.00"))


# ─────────────────────────────────────────────────────────────────────────
# Overlay — pass-through cases
# ─────────────────────────────────────────────────────────────────────────
class TestOverlayPassThrough(unittest.TestCase):
    def test_closed_position_passes_through_unchanged(self):
        inst = Instrument(instrument_id="i", identifiers={"ticker": "X"},
                          name="X", asset_class=AssetClass.STOCK,
                          listing_currency="EUR")
        closed = Position(
            account_id="A", instrument_id="i",
            quantity=Decimal("0"),
            realized_product_pl_base=Decimal("50"),
        )
        prov = _FakePriceProvider({"X": (Decimal("999"), "EUR")})
        out = overlay_prices([closed], [inst],
                             provider=prov, base_currency="EUR")
        # Provider never called; closed position unchanged
        self.assertEqual(prov.calls, [])
        self.assertEqual(out[0], closed)

    def test_unknown_ticker_passes_through_unchanged(self):
        inst = Instrument(instrument_id="i",
                          identifiers={"ticker": "UNKNOWN"},
                          name="X", asset_class=AssetClass.STOCK,
                          listing_currency="EUR")
        pos = Position(account_id="A", instrument_id="i",
                       quantity=Decimal("10"),
                       break_even_price_local=Decimal("100"),
                       cost_basis_base=Decimal("1000"))
        prov = _FakePriceProvider({})    # empty — provider knows nothing
        out = overlay_prices([pos], [inst],
                             provider=prov, base_currency="EUR")
        self.assertEqual(out[0], pos)    # unchanged

    def test_ticker_map_overrides_instrument_identifiers(self):
        inst = Instrument(instrument_id="i", identifiers={"ticker": "RAW"},
                          name="X", asset_class=AssetClass.STOCK,
                          listing_currency="EUR")
        pos = Position(account_id="A", instrument_id="i",
                       quantity=Decimal("10"),
                       break_even_price_local=Decimal("100"),
                       cost_basis_base=Decimal("1000"))
        prov = _FakePriceProvider({"OVERRIDE.L": (Decimal("105"), "EUR")})
        out = overlay_prices(
            [pos], [inst],
            provider=prov, base_currency="EUR",
            ticker_map={"i": "OVERRIDE.L"},
        )
        self.assertEqual(out[0].last_price_local, Decimal("105"))


# ─────────────────────────────────────────────────────────────────────────
# Overlay — price/listing UNIT mismatches (audit 2026-06-11)
# ─────────────────────────────────────────────────────────────────────────
class TestOverlayUnitMismatch(unittest.TestCase):
    """The price is denominated in Price.currency, not necessarily the
    listing currency. The pence↔pound case is reconciled (×100); any
    other mismatch refuses the overlay (pass-through beats silently
    wrong money — the old code valued a pence book 100× under)."""

    def _pence_book(self):
        # Degiro-style LSE holding: listing + BEP in PENCE. 1000 sh
        # @ 400p ≈ £4,000; cost basis in GBP base = 1000×400×0.01.
        inst = Instrument(
            instrument_id="i", identifiers={"ticker": "HBR.L"},
            name="Pence Corp", asset_class=AssetClass.STOCK,
            listing_currency="GBX",
        )
        pos = Position(
            account_id="A", instrument_id="i",
            quantity=Decimal("1000"),
            break_even_price_local=Decimal("400"),       # pence
            cost_basis_base=Decimal("4000"),             # GBP
        )
        return inst, pos

    def test_pence_book_pound_price_values_correctly(self):
        # Provider normalised the quote to POUNDS (Yahoo GBp→GBP): £4.50.
        inst, pos = self._pence_book()
        prov = _FakePriceProvider({"HBR.L": (Decimal("4.50"), "GBP")})
        out = overlay_prices([pos], [inst], provider=prov,
                             base_currency="GBP")
        p = out[0]
        self.assertEqual(p.value_base, Decimal("4500"))   # NOT 45 (100× under)
        # product = (4.50 − 4.00) × 1000 × 1 = 500; no currency component
        self.assertEqual(p.unrealized_product_pl_base, Decimal("500"))
        self.assertEqual(p.unrealized_currency_pl_base, Decimal("0"))

    def test_pence_book_pound_price_avg_fx_fallback(self):
        # EUR base, NO fx provider: the avg-fx fallback derives EUR-per-
        # PENNY from the position; the overlay must rescale it to
        # EUR-per-POUND for the pound-denominated price.
        inst, pos = self._pence_book()
        pos = pos.model_copy(update={
            "cost_basis_base": Decimal("4680"),          # EUR @ 1.17 €/£
        })
        prov = _FakePriceProvider({"HBR.L": (Decimal("4.00"), "GBP")})
        out = overlay_prices([pos], [inst], provider=prov,
                             base_currency="EUR")
        # avg fx per penny = 4680/(1000×400) = 0.0117 → per pound 1.17
        self.assertEqual(out[0].value_base, Decimal("4680"))
        self.assertEqual(out[0].unrealized_pl_base, Decimal("0"))

    def test_pence_price_pound_book_normalised(self):
        # Defensive inverse: book in GBP, provider returned raw pence.
        inst = Instrument(
            instrument_id="i", identifiers={"ticker": "X.L"},
            name="X", asset_class=AssetClass.STOCK,
            listing_currency="GBP",
        )
        pos = Position(account_id="A", instrument_id="i",
                       quantity=Decimal("100"),
                       break_even_price_local=Decimal("4"),
                       cost_basis_base=Decimal("400"))
        prov = _FakePriceProvider({"X.L": (Decimal("450"), "GBX")})
        out = overlay_prices([pos], [inst], provider=prov,
                             base_currency="GBP")
        self.assertEqual(out[0].value_base, Decimal("450"))

    def test_unreconcilable_units_refuse_overlay(self):
        # Sparse EUR-labelled instrument priced in USD: silently treating
        # the USD price as EUR was an 8-15% error — must pass through.
        inst = Instrument(
            instrument_id="i", identifiers={"ticker": "DLST"},
            name="Delisted", asset_class=AssetClass.STOCK,
            listing_currency="EUR",                      # sparse fallback
        )
        pos = Position(account_id="A", instrument_id="i",
                       quantity=Decimal("10"),
                       break_even_price_local=Decimal("100"),
                       cost_basis_base=Decimal("1000"))
        prov = _FakePriceProvider({"DLST": (Decimal("105"), "USD")})
        out = overlay_prices([pos], [inst], provider=prov,
                             base_currency="EUR")
        self.assertIsNone(out[0].last_price_local)       # untouched
        self.assertEqual(out[0].value_base, Decimal("0"))


if __name__ == "__main__":
    unittest.main()
