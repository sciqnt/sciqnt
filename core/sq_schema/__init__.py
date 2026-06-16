"""sq-schema — canonical cross-asset schema for sciqnt.

ONE source of truth for what a Position / Instrument / Account / CashBalance
looks like across every broker / exchange / data source. Every connector
translates its dialect INTO this shape (in its own `canonical.py`); every
consumer (live display, MCP server, analytics) reads FROM this shape and
never touches broker JSON.

Bitemporal from day one — `valid_at` (truth in the world) + `observed_at`
(when we recorded it) on every fact. Money is `Decimal` (deterministic-core
protected). Floats are only for ratios/percents. This module performs NO P/L
math — adapters fill the fields, consumers read them.

Quick reference
---------------
::

    from decimal import Decimal
    from datetime import datetime, timezone
    from sq_schema import (
        Account, Instrument, Position, CashBalance, FxRate,
        Transaction, PortfolioSnapshot, AssetClass, TransactionType,
        conformance,
    )

    # Build an instrument and a position by hand
    acct = Account(account_id="A1", broker="degiro", base_currency="EUR")
    inst = Instrument(
        instrument_id="inst-IB01",
        identifiers={"isin": "IE00BGSF1X88", "ticker": "IB01",
                     "broker:degiro": "15690087"},
        name="iShares $ Treasury Bond 0-1yr UCITS ETF",
        asset_class=AssetClass.ETF, listing_currency="USD",
    )
    pos = Position(
        account_id="A1", instrument_id="inst-IB01",
        quantity=Decimal("100"),
        last_price_local=Decimal("120.54"),
        value_base=Decimal("10338.72"),
        break_even_price_local=Decimal("114.10"),
        cost_basis_base=Decimal("11159.34"),
        unrealized_product_pl_base=Decimal("552.36"),
        unrealized_currency_pl_base=Decimal("-1369.96"),
        realized_product_pl_base=Decimal("0"),
        realized_currency_pl_base=Decimal("-3.00"),
    )
    # Derived fields are computed properties:
    pos.unrealized_pl_base   # -817.60
    pos.realized_pl_base     # -3.00
    pos.total_pl_base        # -820.60
    pos.is_open              # True

    # Wrap into a snapshot (validates FK integrity automatically)
    snap = PortfolioSnapshot(
        account=acct, instruments=[inst], positions=[pos], cash_balances=[],
    )

    # Run semantic conformance checks (returns [] when clean)
    conformance.check_snapshot(snap)

Money invariant
---------------
Every `*_base`, `cost_basis_*`, `value_*`, `amount`, `quantity`, `rate`,
`price_*` field is a Decimal. If your adapter is producing floats, see
`research/connector-framework.md` for the `_to_money` discipline.

Honest gaps (declared, not silent)
----------------------------------
- **No price overlay in fold_position** — see `sq_compute`.
- **No persistence engine** — bitemporal columns present; storage deferred.
- **Typed sub-models for derivatives (OptionTerms / BondTerms)** — use
  `Instrument.terms: dict` until a real connector forces typed schemas.
- **FIGI resolution** — `identifiers["figi"]` populated later by `sq-openfigi`.
"""
__version__ = "0.1.0"   # the contract's semver — SINGLE source (pyproject reads this attr).

from .bitemporal import Bitemporal
from .enums import AssetClass, TransactionType
from .account import Account
from .instrument import Instrument
from .position import Position
from .cash import CashBalance
from .closed_lot import ClosedLot
from .fx import FxRate, FxRateProvider
from .news import NewsItem, NewsProvider
from .price import Price, PriceProvider
from .transaction import Transaction
from .snapshot import PortfolioSnapshot
from . import conformance

__all__ = [
    "Bitemporal",
    "AssetClass",
    "TransactionType",
    "Account",
    "Instrument",
    "Position",
    "CashBalance",
    "ClosedLot",
    "FxRate",
    "FxRateProvider",
    "NewsItem",
    "NewsProvider",
    "Price",
    "PriceProvider",
    "Transaction",
    "PortfolioSnapshot",
    "conformance",
    "contract_json_schema",
]

from .json_schema import contract_json_schema
