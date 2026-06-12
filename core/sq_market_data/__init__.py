"""sq-market-data — mark-to-market overlay over canonical Positions.

The pair to `sq_compute`: where fold_position produces auditable history
(cost basis + realised P/L, fees-inclusive), this substrate overlays a
current market price (via a `PriceProvider`) to populate the LIVE side:
`last_price_local`, `value_base`, `unrealized_*_pl_base`.

Pure compute over canonical entities. The provider does the I/O; the
overlay itself is deterministic given (positions, price quotes, fx rates).

::

    from sq_market_data import overlay_prices
    from sq_yahoo import YahooProvider

    historical = [fold_position(...) for inst in instruments]
    live = overlay_prices(
        positions=historical,
        instruments=instruments,
        provider=YahooProvider(),
        base_currency="EUR",
    )
    # `live` is a NEW list of Positions with mark-to-market fields populated;
    # the input list is unchanged.

Ticker resolution priority (per position):
  1. ``ticker_map[instrument_id]`` if supplied — caller-specified override
     for cases the provider needs a specific symbol form (e.g. ``IB01.L``
     for the LSE-traded ETF when the canonical identifier is just ``IB01``).
  2. ``instrument.identifiers["yahoo_ticker"]`` — the Yahoo-qualified
     symbol (venue suffix included); wins over the bare exchange ticker
     because the suffix is what disambiguates listings.
  3. ``instrument.identifiers["ticker"]`` — the bare broker-given symbol.
  4. None → position passes through unchanged (no mark-to-market).

FX resolution for cross-currency positions:
  - If listing_currency == base_currency: trivially fx = 1.
  - If a ``fx_provider`` is supplied: ``fx_provider.get_rate(listing, base)``.
  - Otherwise: fall back to the historical AVG acquisition rate derived
    from the position itself (``cost_basis_base / (qty × BEP)``).
    This is an honest approximation — the unrealised currency component
    is then 0 by construction (we have no current rate to compare with),
    so the unrealised P/L attributes entirely to the price-driven side.
    Documented; supply a fx_provider for accurate currency-component split.
"""
from decimal import Decimal
from typing import Iterable, Optional

from sq_schema import (
    FxRateProvider, Instrument, Position, Price, PriceProvider,
)

_ZERO = Decimal("0")
_ONE  = Decimal("1")
_MONEY_QUANTUM = Decimal("0.00000001")    # 8dp / satoshi-level


def _to_money(d: Decimal) -> Decimal:
    """Quantize a Decimal to 8 fractional digits before storing on a
    Position. Same discipline as `sq_compute.fold._to_money` — see
    that module for the rationale."""
    return d.quantize(_MONEY_QUANTUM)


class ChainProvider:
    """First-non-None composition of `PriceProvider`s.

    The unit of price reliability is a CHAIN, not a source: Yahoo
    (unofficial, broad) answers first; an official rung (Tiingo) takes
    the ticker when Yahoo can't; each rung's own archive fallback sits
    behind that. A rung that raises is treated as None (degrade, never
    propagate). Order = priority."""

    def __init__(self, *providers):
        self.providers = [p for p in providers if p is not None]

    def get_price(self, ticker: str, *, asof=None):
        for p in self.providers:
            try:
                price = p.get_price(ticker, asof=asof)
            except Exception:                          # noqa: BLE001
                continue
            if price is not None:
                return price
        return None

    def get_intraday(self, ticker: str):
        """First rung that can serve today's intraday bars (optional
        capability — rungs without it are skipped)."""
        for p in self.providers:
            fn = getattr(p, "get_intraday", None)
            if not callable(fn):
                continue
            try:
                bars = fn(ticker)
            except Exception:                          # noqa: BLE001
                continue
            if bars is not None:
                return bars
        return None


def overlay_prices(
    positions: Iterable[Position],
    instruments: Iterable[Instrument],
    *,
    provider: PriceProvider,
    base_currency: str,
    ticker_map: Optional[dict[str, str]] = None,
    fx_provider: Optional[FxRateProvider] = None,
    asof=None,
) -> list[Position]:
    """Return a new list of Positions with mark-to-market fields populated.

    Closed positions (`quantity == 0`) pass through unchanged — there's
    nothing to mark. Open positions whose ticker cannot be resolved by
    the provider also pass through unchanged (silent degradation; check
    each returned position's `last_price_local` to know which were
    overlaid).

    When `asof` is given (a datetime), prices and FX rates are sourced
    at that historical date — the provider must support `get_price(...,
    asof=...)` for this to yield non-None prices, otherwise positions
    pass through. The FX provider's `get_rate(asof=...)` is also passed
    `asof` when supplied.
    """
    inst_by_id  = {i.instrument_id: i for i in instruments}
    ticker_map  = ticker_map or {}
    out: list[Position] = []
    for pos in positions:
        if not pos.is_open:
            out.append(pos)
            continue
        inst = inst_by_id.get(pos.instrument_id)
        if inst is None:
            out.append(pos)
            continue

        # Yahoo-qualified ticker (e.g. "AAPL.L") wins over the bare
        # exchange ticker — the suffix is what disambiguates listings.
        ticker = (ticker_map.get(pos.instrument_id)
                  or inst.identifiers.get("yahoo_ticker")
                  or inst.identifiers.get("ticker"))
        if not ticker:
            out.append(pos)
            continue

        try:
            price = (provider.get_price(ticker, asof=asof)
                     if asof is not None else provider.get_price(ticker))
        except TypeError:
            # Older provider that doesn't accept asof kwarg — degrade.
            price = None if asof is not None else provider.get_price(ticker)
        if price is None:
            out.append(pos)
            continue

        out.append(_apply_overlay(pos, inst, price, base_currency,
                                  fx_provider, asof=asof))
    return out


def _apply_overlay(
    pos: Position,
    inst: Instrument,
    price: Price,
    base_currency: str,
    fx_provider: Optional[FxRateProvider],
    *,
    asof=None,
) -> Position:
    """Pure: produce a new Position with mark-to-market fields filled.

    When `asof` is given, the FX rate is also requested at that date
    (FxRateProvider's `get_rate(asof=...)`). Providers that don't accept
    asof fall back to the latest rate; providers that don't know the
    pair at all fall back to the avg acquisition fx (honest approximation
    — the currency-P/L component then collapses to zero).

    UNIT DISCIPLINE (audit find 2026-06-11): the price is denominated in
    `price.currency`, NOT necessarily `inst.listing_currency` — providers
    normalise LSE pence quotes to pounds while Degiro books the listing
    (and the BEP) in GBX. Ignoring that valued a pence-book position 100×
    under (the avg-fx fallback applied a per-penny rate to a per-pound
    price). The overlay now works in the PRICE's currency: the pence↔pound
    relation is reconciled explicitly (×100), and any OTHER unit mismatch
    refuses the overlay (position passes through with its cost surrogate
    — visible degradation beats a silently wrong number)."""
    listing_ccy = inst.listing_currency
    price_ccy = price.currency or listing_ccy
    current_price = price.last_price_local
    bep = pos.break_even_price_local or _ZERO

    # Reconcile the BEP/history unit (listing) with the price unit.
    # `scale` converts listing-unit amounts into price-unit amounts.
    scale = _ONE
    work_ccy = price_ccy
    if price_ccy != listing_ccy:
        if _is_pence(listing_ccy) and price_ccy == "GBP":
            scale = Decimal("0.01")          # pence book, pound price
        elif listing_ccy == "GBP" and _is_pence(price_ccy):
            current_price = current_price / Decimal("100")
            work_ccy = "GBP"                 # pence price, pound book
        else:
            return pos                       # unreconcilable — refuse
    bep_w = bep * scale

    # Current fx (price/work currency → base)
    if work_ccy == base_currency:
        current_fx = _ONE
    elif fx_provider is not None:
        try:
            rate = (fx_provider.get_rate(work_ccy, base_currency, asof=asof.date())
                    if asof is not None else
                    fx_provider.get_rate(work_ccy, base_currency))
        except TypeError:
            rate = fx_provider.get_rate(work_ccy, base_currency)
        # Fall back to acquisition fx if provider doesn't know the pair.
        # _derive_avg_fx yields base-per-LISTING-unit; ÷scale re-expresses
        # it as base-per-work-unit (pence→pound = ×100).
        current_fx = (rate.rate if rate is not None
                      else _derive_avg_fx(pos) / scale)
    else:
        current_fx = _derive_avg_fx(pos) / scale

    qty = pos.quantity
    new_value_base = qty * current_price * current_fx
    # Decomposition mirrors fold_position + live.canonical conventions:
    #   product P/L  = price-driven, valued at the current FX
    #   currency P/L = "what changed in FX" × the cost basis
    #                = current_value - cost_basis - product_pl
    # That last form avoids needing the per-lot acquisition FX (we only
    # carry the AVG via cost_basis_base / (qty × BEP)).
    unreal_product_pl  = (current_price - bep_w) * qty * current_fx
    unreal_total       = new_value_base - pos.cost_basis_base
    unreal_currency_pl = unreal_total - unreal_product_pl

    # Quantize at the boundary — Decimal multiplications grow precision
    # unboundedly (qty × price × fx easily yields 25+ fractional digits).
    # Position has conformance checks that reject >12-digit money, AND
    # unquantized Decimals slow down every downstream sum / comparison.
    return pos.model_copy(update={
        "last_price_local":           _to_money(current_price),
        "value_base":                 _to_money(new_value_base),
        "unrealized_product_pl_base": _to_money(unreal_product_pl),
        "unrealized_currency_pl_base":_to_money(unreal_currency_pl),
    })


def _is_pence(ccy: Optional[str]) -> bool:
    """LSE pence codes — Degiro books listings as 'GBX', Yahoo's raw
    feed says 'GBp'. Either way: hundredths of GBP."""
    return ccy is not None and (ccy == "GBp" or ccy.upper() == "GBX")


def _derive_avg_fx(pos: Position) -> Decimal:
    """Fall-back: derive the AVG acquisition fx from existing position fields.
    cost_basis_base = qty × BEP × avg_fx  →  avg_fx = cost_basis_base / (qty × BEP)
    Returns 1.0 when the relationship is undefined (zero qty, missing BEP)."""
    bep = pos.break_even_price_local
    if pos.quantity == 0 or bep in (None, _ZERO):
        return _ONE
    return pos.cost_basis_base / (pos.quantity * bep)
