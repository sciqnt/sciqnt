"""sq-analytics — pure compute aggregates over canonical entities.

Built on top of `sq_compute` (event-sourcing folds). Same purity contract:
no I/O, same inputs → same outputs, side-effect-free. Each function takes
canonical types (Position / CashBalance / Instrument / Transaction) and
returns a plain dict — composable, JSON-serialisable, agent-friendly.

These are the "analyse" step in the build order (read → reconcile →
**analyse** → suggest → execute). Most are small enough to write inline,
but they live here because:

  1. The compositions are obvious-once-stated and easy to get subtly wrong
     (sign conventions, base vs listing ccy, open vs closed positions).
     One canonical version + tests beats N near-copies.
  2. Agents discover them by importing `sq_analytics` rather than
     re-deriving from primitives every time.
  3. They double as worked examples of how to compose `sq_schema` +
     `sq_compute` correctly.

Quick reference
---------------
::

    from sq_analytics import (
        portfolio_summary, currency_exposure, asset_class_exposure,
        dividend_history, fee_history,
        realized_pl_over_time, cash_flow_over_time,
        tax_lots, all_tax_lots,
    )

    # Snapshot-level (current state)
    portfolio_summary(snapshot.positions, base_currency="EUR")
    currency_exposure(snapshot.positions, snapshot.cash_balances,
                      snapshot.instruments, base_currency="EUR")
    asset_class_exposure(snapshot.positions, snapshot.instruments,
                         base_currency="EUR")

    # Transaction-level (historical)
    dividend_history(transactions, group_by="year")
    fee_history(transactions, group_by="month")
    realized_pl_over_time(transactions, base_currency="EUR", group_by="year")
    cash_flow_over_time(transactions, group_by="year", currency="EUR")

    # Audit-trail (per-closure ClosedLot records — tax filing)
    tax_lots(transactions, account_id="degiro",
             instrument_id="degiro:isin:IE00BGSF1X88",
             base_currency="EUR")
    all_tax_lots(transactions, account_id="degiro", base_currency="EUR")

What NOT to expect here
-----------------------
- **Mark-to-market.** Analytics that need a current market price (TWR/IRR,
  drawdown, time-series portfolio value) require a price overlay from
  `sq-yahoo` or similar; they belong in a separate substrate that depends
  on both this module AND a price source.
- **Risk metrics** (volatility, Sharpe, factor exposures). Same reason —
  they need a returns series, which needs market prices.
"""
from .portfolio import (
    asset_class_exposure, currency_exposure, portfolio_summary,
)
from .income import dividend_history, fee_history, income_summary
from .performance import cash_flow_over_time, realized_pl_over_time
from .tax import all_tax_lots, tax_lots

__all__ = [
    "portfolio_summary",
    "currency_exposure",
    "asset_class_exposure",
    "dividend_history",
    "fee_history",
    "income_summary",
    "realized_pl_over_time",
    "cash_flow_over_time",
    "tax_lots",
    "all_tax_lots",
]
