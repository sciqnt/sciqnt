"""sq-performance — return analytics over a canonical Transaction stream.

Five primitives:

  * `xirr(transactions, terminal_value, base_currency, asof=None)` —
    money-weighted annualised return. The IRR of every external cash
    flow (deposit / withdrawal) plus a synthetic terminal inflow equal
    to the current portfolio value. Returns a `Decimal` annualised
    rate or `None` if the solver fails / can't bracket.

  * `total_return(...)` — simple non-annualised summary: net contributed,
    dividends, interest, fees, current value, profit, return%.

  * `twr(value_series, cash_flows)` — time-weighted (geometric) return
    over a sequence of (date, portfolio_value) samples. Independent of
    cash-flow timing — measures the market-driven performance only.
    Pure compute: the caller provides the value series (build it with
    your broker's `snapshot(asof=date)` per cash event).

  * `max_drawdown(value_series)` — largest peak-to-trough decline as
    `{peak_at, peak_value, trough_at, trough_value, drawdown_pct,
    drawdown_abs, recovered_at}`. Recovery is the first sample at-or-
    after trough that meets or exceeds the prior peak (None if never).

  * `twr_index_series(value_series, cash_flows)` — the normalized
    cumulative-return index TWR compounds (cash-flow-stripped). Feed it
    to `max_drawdown` so withdrawals don't read as crashes. Carries flat
    through empty-portfolio performance breaks (see `twr`).

Quick reference
---------------
::

    from datetime import datetime, timezone
    from decimal import Decimal
    from sq_performance import xirr, total_return, twr, max_drawdown

    # Money-weighted (one number per portfolio):
    rate = xirr(txns, terminal_value=Decimal("10000"), base_currency="EUR")

    # Time-weighted (factors out the timing of YOUR deposits):
    value_series = [(d0, Decimal("1000")), (d1, Decimal("1100")), ...]
    cash_flows   = [(d0, Decimal("0")),    (d1, Decimal("0")),    ...]
    tw_rate = twr(value_series, cash_flows)

    # Drawdown (max peak-to-trough loss):
    dd = max_drawdown(value_series)
    print(f"max drawdown: {dd['drawdown_pct']*100:.2f}% "
          f"({dd['peak_at']} -> {dd['trough_at']})")
"""
from .core import max_drawdown, total_return, twr, twr_index_series, xirr

__all__ = ["xirr", "total_return", "twr", "twr_index_series",
           "max_drawdown"]
