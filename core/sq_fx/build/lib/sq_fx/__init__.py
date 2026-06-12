"""sq-fx — FX rate access substrate.

Provider implementations are CONNECTOR BUNDLES (`sq-fx-ecb`, `sq-fx-yfinance`,
…). This substrate gives consumers a single lookup point + a `convert()`
helper so they don't each repeat the import-or-fallback dance.

Resolution order for ``get_provider(name=None)``:
  1. Explicit ``name`` arg
  2. ``sq_config['fx_provider']``    (user-set via ``sciqnt config set``)
  3. The first installed default     ('ecb' — sq-fx-ecb is the zero-config one)

Returns ``None`` if no provider is installed / configured. Callers should
treat ``None`` as "I don't know this rate" and degrade gracefully (e.g. show
the amount in the source currency with a 'no rate' note). NEVER fabricate.

Quick reference
---------------
::

    from decimal import Decimal
    from datetime import date
    import sq_fx

    # Which providers are installed in this venv?
    sq_fx.available()           # e.g. ["ecb"]

    # Convert money. None if no provider or unknown pair.
    eur = sq_fx.convert(Decimal("100"), "USD", "EUR")
    if eur is None:
        print("no rate; degrading visibly")

    # Same-currency conversion short-circuits to identity (no provider needed)
    sq_fx.convert(Decimal("100"), "EUR", "EUR")   # Decimal('100')

    # Historical
    eur_pre_2023 = sq_fx.convert(
        Decimal("100"), "USD", "EUR", asof=date(2022, 12, 31),
    )

    # Drop down to the provider directly when you need the FxRate object:
    p = sq_fx.get_provider()    # returns an FxRateProvider or None
    if p is not None:
        rate = p.get_rate("USD", "EUR")
        # rate.rate is Decimal; 1 USD = rate.rate EUR; rate.source documents
        # which provider answered. rate.valid_at carries the bitemporal stamp.

The protocol
------------
Any class that implements ``get_rate(from_ccy, to_ccy, asof=None) ->
FxRate | None`` satisfies the ``sq_schema.FxRateProvider`` protocol. Add a
new source by writing such a class, registering it in ``_PROVIDERS``, and
either shipping it as a bundle (``modules/sq-fx-<src>/``) or wiring it into
the project import path.
"""
import importlib
from datetime import date
from decimal import Decimal
from typing import Optional

import sq_config
from sq_schema import FxRateProvider


# USD-pegged stablecoins. Fiat FX providers (ECB) don't quote these, but a
# cross-asset portfolio that holds Polymarket (USDC) / crypto-exchange (USDT)
# balances still needs a single display total. We treat each as USD at 1:1 —
# a DECLARED APPROXIMATION: stablecoins target $1 but can depeg (USDC briefly
# hit ~$0.88 in the Mar-2023 SVB scare). Honest trade-off: a 1:1 peg vs. an
# unconvertible leg dropping out of the total entirely. Documented here and in
# the connector FINDINGS; never silent. Add codes as needed.
_USD_STABLECOINS = frozenset({
    "USDC", "USDT", "DAI", "BUSD", "USDP", "TUSD", "GUSD", "PYUSD", "FDUSD",
})


def _peg_ccy(ccy: str) -> str:
    """Map a known USD stablecoin → 'USD' (1:1 peg); pass other codes through."""
    return "USD" if ccy in _USD_STABLECOINS else ccy


# Known provider names -> (module to import, class to instantiate).
# Keep small and explicit; capability-based discovery replaces this when
# there are 3+ providers (small registries don't earn their keep until then).
_PROVIDERS = {
    "ecb":  ("sq_fx_ecb", "ECBProvider"),
    # "yfinance": ("sq_fx_yfinance", "YFinanceProvider"),   # when built
}


def available() -> list[str]:
    """Return the names of provider bundles that are actually importable
    (installed in this venv). Useful for `sciqnt config set` UIs and for
    debugging 'why didn't FX work'."""
    found = []
    for name, (mod_name, cls_name) in _PROVIDERS.items():
        try:
            mod = importlib.import_module(mod_name)
            getattr(mod, cls_name)                 # attribute existence
            found.append(name)
        except (ImportError, AttributeError):
            continue
    return found


def get_provider(name: Optional[str] = None) -> Optional[FxRateProvider]:
    """Resolve an FxRateProvider. None if not installed/configured."""
    candidate = name or sq_config.get("fx_provider") or "ecb"
    if candidate not in _PROVIDERS:
        return None
    mod_name, cls_name = _PROVIDERS[candidate]
    try:
        mod = importlib.import_module(mod_name)
        provider_cls = getattr(mod, cls_name)
        return provider_cls()
    except (ImportError, AttributeError):
        return None


def convert(
    amount: Decimal,
    from_ccy: str,
    to_ccy: str,
    provider: Optional[FxRateProvider] = None,
    asof: Optional[date] = None,
) -> Optional[Decimal]:
    """Convert `amount` (in `from_ccy`) to `to_ccy`.

    Same-currency conversion is a no-op (returns `amount` unchanged).
    Returns None when no provider is available OR the requested pair can't
    be resolved (unknown currency, no historical rate, etc.). Caller decides
    how to surface — the principled choice is 'show in source ccy + note'.

    USD-stablecoin peg: if a direct rate can't be found and `from_ccy`/`to_ccy`
    is a known USD stablecoin (USDC/USDT/DAI/…), we retry treating it as USD
    at 1:1. A DECLARED APPROXIMATION (see `_USD_STABLECOINS`) — it lets a
    Polymarket-USDC + Degiro-EUR portfolio show one total instead of dropping
    the USDC leg. Pure fiat conversions are unaffected.
    """
    if from_ccy == to_ccy:
        return amount
    if provider is None:
        provider = get_provider()
    if provider is None:
        return None
    rate = provider.get_rate(from_ccy, to_ccy, asof=asof)
    if rate is None:
        # Stablecoin-peg fallback (declared approximation).
        pf, pt = _peg_ccy(from_ccy), _peg_ccy(to_ccy)
        if (pf, pt) != (from_ccy, to_ccy):
            if pf == pt:
                # e.g. USDC↔USDT, or USDC↔USD — both peg to USD → 1:1.
                return Decimal(str(amount)).quantize(Decimal("0.00000001"))
            rate = provider.get_rate(pf, pt, asof=asof)
    if rate is None:
        return None
    return (Decimal(str(amount)) * rate.rate).quantize(Decimal("0.00000001"))
