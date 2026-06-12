"""Shared enums for the canonical schema.

AssetClass borrows from CFI / Degiro / ccxt vocabulary — extensible. New
asset classes are *added*, not *renamed*: keep stable string values so
serialized snapshots survive refactors.
"""
from enum import Enum


class AssetClass(str, Enum):
    """Cross-asset classification. String-valued so JSON-stable.
    Add new values; never repurpose existing ones."""
    STOCK    = "STOCK"
    ETF      = "ETF"
    BOND     = "BOND"
    FUND     = "FUND"
    OPTION   = "OPTION"
    FUTURE   = "FUTURE"
    FX       = "FX"
    CRYPTO   = "CRYPTO"
    CASH     = "CASH"
    INDEX    = "INDEX"
    WARRANT  = "WARRANT"
    CFD      = "CFD"
    EVENT    = "EVENT"        # prediction-market / event contract (Kalshi, Polymarket).
                             # Binary YES/NO outcome share; price is a probability in
                             # [0,1]; settles to a money value (not a hard $0/$1).
                             # Event-specific spec goes in Instrument.terms — see
                             # instrument.py and research/connectors-prediction-markets-*.md
    OTHER    = "OTHER"        # unknown / not-yet-classified; adapters use as a safe default


class TransactionType(str, Enum):
    """The kind of event a Transaction represents. String-valued so JSON-stable.
    Add new values; never repurpose existing ones."""
    BUY                = "BUY"
    SELL               = "SELL"
    DIVIDEND           = "DIVIDEND"            # cash dividend
    DIVIDEND_REINVEST  = "DIVIDEND_REINVEST"   # share inflow with no separate cash
    FEE                = "FEE"                 # commission, custody, etc.
    TAX                = "TAX"                 # withholding etc.
    INTEREST           = "INTEREST"            # cash interest
    DEPOSIT            = "DEPOSIT"
    WITHDRAWAL         = "WITHDRAWAL"
    FX_EXCHANGE        = "FX_EXCHANGE"         # currency conversion (one or both legs are cash)
    SPLIT              = "SPLIT"               # ratio change, no cash
    SPIN_OFF           = "SPIN_OFF"            # produces a new instrument (multi-leg)
    MERGER             = "MERGER"
    SETTLEMENT         = "SETTLEMENT"          # event contract resolved → cash at $0/$1/scalar
                                              # (the realized event for AssetClass.EVENT)
    OTHER              = "OTHER"               # unknown / future
