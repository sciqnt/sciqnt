"""sq-aggregator — merge multiple `PortfolioSnapshot`s into a multi-broker view.

The aggregator is the cross-broker glue. Every broker bundle produces a
`PortfolioSnapshot` (the canonical contract); the aggregator concatenates
them, sums what's summable in a single display currency via the FX
substrate, and surfaces everything else broker-tagged. It is **pure
compute** — no I/O, no rendering. The dispatcher does the fetching;
this module does the math.

Why a separate substrate?
-------------------------
- Pure aggregation logic is easy to test against synthetic snapshots
  without standing up a real broker. The math is one substrate above
  `sq_analytics`, which already handles single-snapshot aggregates.
- The shape is fundamentally different from `sq_analytics`: that module
  answers "what does THIS portfolio look like"; this one answers "what
  do MY portfolios look like, together". Keeping them apart avoids a
  zoo of `*_across_brokers` variants on every analytics function.
- Adding a second broker (IBKR / ccxt / Trading 212) is a no-op here:
  it just appears in `brokers` and falls out of every aggregate.

Quick reference
---------------
::

    from sq_aggregator import (
        BrokerSnapshot, aggregate_value, aggregate_positions, aggregate_cash,
    )

    brokers = [
        BrokerSnapshot(broker="degiro", snapshot=degiro_snap),
        BrokerSnapshot(broker="ibkr",   snapshot=ibkr_snap),
    ]
    totals = aggregate_value(brokers, display_currency="EUR")
    flat_positions = aggregate_positions(brokers)   # [(broker, Position, Instrument), ...]

Math invariant
--------------
For exactly one broker, every aggregate equals what `sq_analytics`
produces over that single snapshot's `positions` / `cash_balances` /
`instruments` directly. Pinned by tests — if it ever breaks, the
single-broker case has silently regressed.
"""
from .core import (
    BrokerSnapshot,
    AggregatedValue,
    aggregate_value,
    aggregate_positions,
    aggregate_cash,
    aggregate_currency_exposure,
    aggregate_asset_class_exposure,
)

__all__ = [
    "BrokerSnapshot",
    "AggregatedValue",
    "aggregate_value",
    "aggregate_positions",
    "aggregate_cash",
    "aggregate_currency_exposure",
    "aggregate_asset_class_exposure",
]
