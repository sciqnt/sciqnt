"""Instrument — what we own / what we'd trade.

Identifier strategy (per the research): the eventual spine is FIGI (OpenFIGI,
free + open) — multi-scheme `identifiers` map carries every known scheme
side-by-side so the connector can seed with broker-internal IDs today and
sq-openfigi can enrich tomorrow. NEVER make any single identifier the primary
key — FX / crypto / OTC don't all have one.

`terms` is an open-ended extension slot for asset-class-specific contract
specs. Conventional keys (when populated):
    OPTION:  {strike: Decimal, expiry: "YYYY-MM-DD", right: "C"|"P", multiplier: int}
    FUTURE:  {contract_month: "YYYY-MM", multiplier: int, point_value: Decimal}
    BOND:    {maturity: "YYYY-MM-DD", coupon_rate: Decimal, day_count: str,
              accrued_interest: Decimal}
    EVENT:   {event_id: str,            # the event a market belongs to (Kalshi event_ticker,
                                        #   Polymarket conditionId)
              outcome: "YES"|"NO",      # which side this instrument represents
              resolution_date: "YYYY-MM-DD" | None,
              market_result: "yes"|"no"|"scalar"|"void" | None,  # None until resolved
              settlement_value: Decimal | None}  # payout per contract once resolved
                                        # (a MONEY value — NOT a hard $0/$1; scalar/void exist)
              # Event-contract price is a probability in [0,1]; quantity is a
              # share/contract count; value = quantity × price. Conformance
              # checks the [0,1] price band. See sq-kalshi / sq-polymarket.
Adding typed sub-models (OptionTerms, BondTerms, EventTerms, ...) is deliberately
deferred until the dict convention proves insufficient. See
research/milestone-0-cross-asset-validation.md and
research/connectors-prediction-markets-and-robinhood.md."""
from pydantic import field_validator
from typing import Any

from .bitemporal import Bitemporal
from .enums import AssetClass
from ._validators import assert_currency_code


class Instrument(Bitemporal):
    instrument_id: str                          # our stable internal UUID
    identifiers: dict[str, str]                 # multi-scheme: {"figi":..,"isin":..,"ticker":..,
                                                # "broker:degiro":"15690087", ...}
    name: str
    asset_class: AssetClass
    listing_currency: str                       # currency code — unit `last_price_local` is in.
                                                # Fiat OR crypto code (BTC/USDT for ccxt pairs).
    listing_venue: str | None = None            # MIC ("XLON") or descriptive ("LSE")
    terms: dict[str, Any] | None = None         # asset-class-specific contract spec (see module docstring)

    @field_validator("listing_currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        return assert_currency_code(v, "listing_currency")

    @field_validator("identifiers")
    @classmethod
    def _at_least_one_id(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError(
                "identifiers must contain at least one scheme "
                "(e.g. {'broker:<name>': '<id>'} as a seed)"
            )
        return v
