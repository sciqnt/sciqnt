"""Reusable validators — keep them in one place so the rules are testable
and impossible to drift across entities.

`currency_code` admits ISO 4217 (EUR/USD/GBP/...) AND crypto codes (BTC/ETH/
USDT/USDC/etc.). Rationale documented in
research/milestone-0-cross-asset-validation.md — ccxt-style connectors
need non-ISO codes for both `CashBalance.currency` and
`Instrument.listing_currency` (BTC/USDT pair quoted in USDT).
"""
import re

# 2-10 uppercase alphanumeric, leading letter. Covers ISO 4217 (3-letter
# fiat) and the entire common crypto-code space (BTC, ETH, USDT, USDC,
# BUSD, BNB, SOL, ADA, DOT, XRP, MATIC, AVAX, LINK, XBT, ...).
_CURRENCY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")


def is_currency_code(code: str) -> bool:
    """Accepts ISO 4217 fiat codes AND common crypto codes. Doesn't validate
    against a registry (that's a later, opt-in concern); just the shape."""
    return bool(_CURRENCY_RE.match(code))


def assert_currency_code(code: str, field_name: str) -> str:
    if not is_currency_code(code):
        raise ValueError(
            f"{field_name}={code!r} is not a valid currency code "
            "(must be 2-10 uppercase alphanumerics, leading letter — "
            "covers ISO 4217 fiat + common crypto codes)"
        )
    return code


# Back-compat aliases — older imports keep working. Prefer the new names.
is_iso4217 = is_currency_code
assert_iso4217 = assert_currency_code
