"""Pure-compute performance analytics over a canonical Transaction stream.

No I/O. Money is `Decimal`. The XIRR solver uses bracketed bisection (no
scipy dep) — slow per iteration but always converges in <60 steps on
realistic rate ranges (-0.99 .. +10.0)."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Optional

from sq_schema import Transaction, TransactionType

_ZERO = Decimal("0")
_ONE  = Decimal("1")
# Materiality threshold for the "portfolio is economically empty" decision
# in twr(): |value| ≤ 0.5% of the running peak = a performance break (skip,
# factor 1); materially negative = corrupt data (None). See twr's docstring.
_EMPTY_EPSILON = Decimal("0.005")
# Absolute floor for the corruption test (base-ccy units): without it, a
# window STARTING inside a break (running peak still 0) would treat a tiny
# negative reconstruction residue as corrupt. Also the "capital returned"
# threshold that re-anchors the running peak after a break — without the
# re-anchor, re-funding with less than 0.5% of a much larger former era's
# peak left every later segment classified as a break forever (the
# headline then showed a confident-looking 0.00%, audit find 2026-06-11).
_EMPTY_FLOOR = Decimal("10")

# XIRR cash-flow convention (strict — investor↔account boundary only):
#
#   DEPOSIT     →  investor cash OUT (committed capital)         → negative
#   WITHDRAWAL  →  investor cash IN  (capital returned)          → positive
#   terminal    →  investor "would-receive-if-liquidated-today"  → positive
#
# DIVIDEND / INTEREST / FEE / TAX are NOT separate flows here — they
# stayed inside the account (dividend/interest credit the cash balance;
# fees/tax debit it). They're reflected in the terminal value (which
# the caller computes as `positions_value + cash`). Treating them as
# separate XIRR flows would double-count them.
#
# BUY / SELL never appear: they're pure internal rebalances of cash to
# position value within the account.
_EXTERNAL_FLOW_TYPES = {
    TransactionType.DEPOSIT,
    TransactionType.WITHDRAWAL,
}


def _investor_cashflows(
    transactions: Iterable[Transaction],
    *,
    base_currency: str,
    asof: Optional[datetime] = None,
    fx_provider=None,
) -> list[tuple[datetime, Decimal]]:
    """Filter the stream to external flows and flip the sign to the
    investor's perspective. Cross-currency rows are converted to
    `base_currency` at the flow date via `fx_provider.get_rate(asof=
    flow_date)` when provided; without an FX provider, cross-ccy rows
    are silently dropped (XIRR over a mixed-ccy bag is otherwise
    meaningless). FX-at-date is the strict semantic — the value
    crystallised at the time it crossed the investor↔account boundary,
    not at "now"."""
    out: list[tuple[datetime, Decimal]] = []
    for t in transactions:
        if t.type not in _EXTERNAL_FLOW_TYPES:
            continue
        if asof is not None and t.executed_at > asof:
            continue
        amount = t.amount
        if t.amount_currency != base_currency:
            if fx_provider is None:
                continue                                  # silent drop
            try:
                rate = fx_provider.get_rate(
                    t.amount_currency, base_currency,
                    asof=t.executed_at.date(),
                )
            except TypeError:
                rate = fx_provider.get_rate(
                    t.amount_currency, base_currency)
            if rate is None:
                continue                                  # no rate at date
            amount = amount * rate.rate
        # Account-perspective amount: DEPOSIT is +X (cash in); withdrawal -X.
        # Investor-perspective is the opposite: a deposit is YOU putting
        # money IN, hence -X for the IRR solver.
        out.append((t.executed_at, -amount))
    return out


def _xnpv(rate: Decimal, flows: list[tuple[datetime, Decimal]]) -> Decimal:
    """Net Present Value at `rate` (annual, decimal) of `flows`.
    Day-count: 365.25 (matches Excel's XIRR-day-count when years span
    leap years)."""
    if not flows:
        return _ZERO
    t0 = flows[0][0]
    npv = _ZERO
    base = _ONE + rate
    for when, amount in flows:
        days = Decimal((when - t0).days)
        years = days / Decimal("365.25")
        # base ** years for Decimal: convert via float — this is the one
        # place where we accept float precision for the solver's sake.
        # The returned rate is rounded to 6dp at the end so the float
        # path doesn't bleed into the output.
        factor = Decimal(str(float(base) ** float(years)))
        if factor == 0:
            return Decimal("Infinity")
        npv += amount / factor
    return npv


def xirr(
    transactions: Iterable[Transaction],
    *,
    terminal_value: Decimal,
    base_currency: str,
    asof: Optional[datetime] = None,
    fx_provider=None,
    rate_low: Decimal = Decimal("-0.99"),
    rate_high: Decimal = Decimal("10.0"),
    tol: Decimal = Decimal("1e-6"),
    max_iter: int = 100,
) -> Optional[Decimal]:
    """Annualised money-weighted return as a `Decimal` (e.g. `0.0723`
    for +7.23%/yr). Returns `None` when:
      * fewer than two flows (need at least one investment + one return)
      * all flows have the same sign (no IRR exists)
      * solver fails to bracket / converge in `max_iter` steps.

    `terminal_value` is the current portfolio value, in `base_currency`,
    treated as a positive inflow at `asof` (or at the latest flow date
    if `asof` is None). Set it to 0 if you've fully liquidated.

    Cross-currency flows: when `fx_provider` is supplied, every flow is
    converted to `base_currency` at its executed_at date (the strict PIT
    semantic — capture the value at the time it crossed the boundary).
    Without an `fx_provider`, cross-currency flows are silently dropped.
    """
    flows = _investor_cashflows(transactions, base_currency=base_currency,
                                asof=asof, fx_provider=fx_provider)
    if not flows:
        return None

    # Terminal value lands at `asof` if given (PIT correct), otherwise
    # "now". Placing terminal at the latest flow date would be a bug:
    # if your last deposit was years ago and the portfolio has grown
    # since, that compresses years of return into "instant" and inflates
    # the annualised rate.
    flows.sort(key=lambda f: f[0])
    terminal_date = asof or datetime.now(timezone.utc)
    if terminal_value != 0:
        flows.append((terminal_date, terminal_value))

    if len(flows) < 2:
        return None
    signs = {1 if f[1] > 0 else (-1 if f[1] < 0 else 0) for f in flows}
    signs.discard(0)
    if len(signs) < 2:
        # All same sign — no rate makes NPV zero.
        return None

    # XIRR can have multiple sign changes in NPV(rate) when deposits and
    # withdrawals interleave — a single bracket on the full range will
    # often have same-sign endpoints. So: scan in small steps from
    # rate_low to rate_high, find the FIRST sign change, then bisect
    # inside that small bracket. We pick the root nearest to 0% (the
    # standard "economic" answer most spreadsheet XIRRs converge on),
    # by stepping outward from 0% in both directions.
    step = Decimal("0.01")
    pos_scan = [Decimal("0") + step * i for i in range(int(rate_high / step) + 1)]
    neg_scan = [Decimal("0") - step * i for i in range(1, int((rate_low.copy_abs()) / step) + 1)]

    def _bracket_from(scan):
        prev_r = scan[0]
        prev_f = _xnpv(prev_r, flows)
        if not prev_f.is_finite():
            return None
        for r in scan[1:]:
            f = _xnpv(r, flows)
            if not f.is_finite():
                continue
            if prev_f * f < 0:
                return (prev_r, r, prev_f, f)
            prev_r, prev_f = r, f
        return None

    bracket = _bracket_from(pos_scan) or _bracket_from(neg_scan)
    if bracket is None:
        return None

    a, b, fa, _fb = bracket
    for _ in range(max_iter):
        mid = (a + b) / 2
        fm = _xnpv(mid, flows)
        if not fm.is_finite():
            return None
        if abs(fm) < tol or (b - a) < tol:
            return mid.quantize(Decimal("0.000001"))
        if fa * fm < 0:
            b = mid
        else:
            a, fa = mid, fm
    return mid.quantize(Decimal("0.000001"))


def total_return(
    transactions: Iterable[Transaction],
    *,
    terminal_value: Decimal,
    base_currency: str,
    asof: Optional[datetime] = None,
    fx_provider=None,
) -> dict:
    """Simple non-annualised return summary. Pairs nicely with `xirr`:
    XIRR tells you the annualised rate; this tells you the absolute
    profit and over what window.

    Returns a dict with::

        {
          "base_currency":   str,
          "deposits":        Decimal,      # gross +money in
          "withdrawals":     Decimal,      # gross +money out
          "net_contributed": Decimal,      # deposits - withdrawals
          "dividends":       Decimal,      # +money received as dividend
          "interest":        Decimal,
          "fees":            Decimal,      # always ≤ 0
          "tax":             Decimal,      # always ≤ 0
          "current_value":   Decimal,      # = terminal_value
          "profit":          Decimal,      # current_value - net_contributed + side gains
          "return_pct":      Decimal,      # profit / net_contributed (≥ 0 contributed)
          "first_flow_at":   datetime | None,
          "last_flow_at":    datetime | None,
        }
    """
    deposits   = withdrawals = dividends = interest = fees = tax = _ZERO
    first_at   = last_at = None
    for t in transactions:
        if asof is not None and t.executed_at > asof:
            continue
        amount = t.amount
        if t.amount_currency != base_currency:
            if fx_provider is None:
                continue
            try:
                rate = fx_provider.get_rate(
                    t.amount_currency, base_currency,
                    asof=t.executed_at.date(),
                )
            except TypeError:
                rate = fx_provider.get_rate(
                    t.amount_currency, base_currency)
            if rate is None:
                continue
            amount = amount * rate.rate
        if t.type == TransactionType.DEPOSIT:
            deposits   += amount
        elif t.type == TransactionType.WITHDRAWAL:
            withdrawals += -amount         # store as positive magnitude
        elif t.type == TransactionType.DIVIDEND:
            dividends  += amount
        elif t.type == TransactionType.INTEREST:
            interest   += amount
        elif t.type == TransactionType.FEE:
            fees       += amount           # already signed (≤0 typically)
        elif t.type == TransactionType.TAX:
            tax        += amount
        else:
            continue
        if first_at is None or t.executed_at < first_at:
            first_at = t.executed_at
        if last_at is None or t.executed_at > last_at:
            last_at = t.executed_at

    net_contributed = deposits - withdrawals
    # Profit = (what you have) + (what you took out) - (what you put in)
    #        + side gains (dividends + interest) - costs (-fees - tax)
    # Cleaner: profit = current_value - net_contributed
    # (dividends/interest stay inside the account → already in current_value;
    #  fees/tax exit the account → reduce current_value; double-counting only
    #  arises if they were treated as withdrawals. They're separate types,
    #  so the cleaner formula is the right one.)
    profit = terminal_value - net_contributed
    return_pct = (profit / net_contributed * Decimal("100")
                  if net_contributed > 0 else _ZERO)

    return {
        "base_currency":   base_currency,
        "deposits":        deposits,
        "withdrawals":     withdrawals,
        "net_contributed": net_contributed,
        "dividends":       dividends,
        "interest":        interest,
        "fees":            fees,
        "tax":             tax,
        "current_value":   terminal_value,
        "profit":          profit,
        "return_pct":      return_pct.quantize(Decimal("0.01")),
        "first_flow_at":   first_at,
        "last_flow_at":    last_at,
    }


# ── Time-weighted return ──────────────────────────────────────────────────
def twr(
    value_series: list[tuple[datetime, Decimal]],
    cash_flows:   list[tuple[datetime, Decimal]],
    *,
    annualise: bool = True,
) -> Optional[Decimal]:
    """Time-weighted (geometric) return over a sequence of valuations.

    `value_series` is a chronologically-sorted list of (date, value)
    samples — the portfolio value at each point. `cash_flows` is the
    corresponding (date, signed_amount) list (positive = capital
    contributed, negative = capital withdrawn). Both must share the
    same dates and same length so each segment is well-defined.

    Standard TWR: for each segment between consecutive samples we
    compute the segment return AFTER stripping out the contribution
    that happened AT the segment's END (the snapshot at t_i includes
    that cash flow, but we want the growth-only portion):

        R_i  =  (V_end  −  cash_flow_at_end)  /  V_start  −  1

    Compound the (1+R_i)s, subtract 1, optionally annualise to a yearly
    rate using day-weighted compounding over (last_date − first_date).

    A portfolio that EMPTIES mid-series (full withdrawal, later re-funded)
    is a PERFORMANCE BREAK, not corrupt data: segments whose starting
    capital is immaterial (|V_start| ≤ 0.5% of the running peak — covers
    both true zero and tiny reconstruction residues like a -6.98 left by
    fee timing after a near-total withdrawal) compound at factor 1 and the
    chain re-links when capital returns (GIPS-style). A MATERIALLY
    negative V_start is corrupt data.

    Returns None if the series is degenerate (< 2 samples, materially
    negative interim value, or the time span is zero)."""
    if len(value_series) < 2 or len(cash_flows) != len(value_series):
        return None
    growth = _ONE
    running_peak = _ZERO
    measured = False                 # at least one REAL segment compounded
    for i in range(1, len(value_series)):
        _, v_prev   = value_series[i - 1]
        _, v_curr   = value_series[i]
        _, cf_curr  = cash_flows[i]
        running_peak = max(running_peak, v_prev)
        # Strip the boundary cash flow from V_end so the segment return
        # reflects only market growth, not capital contribution. v_prev
        # is the denominator — it already includes any prior cash flows.
        threshold = running_peak * _EMPTY_EPSILON
        if v_prev <= threshold:
            if v_prev < -max(threshold, _EMPTY_FLOOR):
                return None          # materially negative = corrupt data
            # Performance break: factor 1. When capital RETURNED at this
            # boundary, re-anchor the peak so the NEW era's own scale
            # governs materiality from here on (re-link).
            if v_curr > _EMPTY_FLOOR:
                running_peak = _ZERO
            continue
        growth *= (v_curr - cf_curr) / v_prev
        measured = True
    if not measured:
        return None                  # breaks only — nothing was measured
    total_return_dec = growth - _ONE
    if not annualise:
        return total_return_dec.quantize(Decimal("0.000001"))

    days = (value_series[-1][0] - value_series[0][0]).days
    if days <= 0:
        return None
    if growth <= 0:
        # A ≥100% loss can't be annualised (fractional power of a non-
        # positive base is complex). None, not a crash — callers show "—".
        return None
    years = Decimal(days) / Decimal("365.25")
    # Annualise via float (Decimal lacks a fractional-power op).
    annualised = Decimal(str((float(growth)) ** (1 / float(years)))) - _ONE
    return annualised.quantize(Decimal("0.000001"))


# ── TWR index series ──────────────────────────────────────────────────────
def twr_index_series(
    value_series: list[tuple[datetime, Decimal]],
    cash_flows:   list[tuple[datetime, Decimal]],
) -> list[tuple[datetime, Decimal]]:
    """Normalized cumulative-return index over the same inputs as `twr`.

    Starts at 1.0; each sample multiplies by the segment's growth factor
    (V_curr − cf_curr) / V_prev — the same cash-flow-stripped factor TWR
    compounds, so drawdown over this index reflects MARKET moves only
    (a withdrawal doesn't read as a crash).

    Empty-portfolio segments follow `twr`'s performance-break rule:
    |V_start| ≤ 0.5% of the running peak → the index carries FLAT through
    the break and re-links when capital returns (it must NOT truncate —
    truncating hides every later recovery from drawdown). A materially
    negative V_start ends the series there (corrupt data; the truncated
    prefix is still meaningful for drawdown)."""
    if not value_series or len(cash_flows) != len(value_series):
        return []
    out = [(value_series[0][0], _ONE)]
    idx = _ONE
    running_peak = _ZERO
    for i in range(1, len(value_series)):
        _, v_prev  = value_series[i - 1]
        when, v_curr = value_series[i][0], value_series[i][1]
        _, cf_curr = cash_flows[i]
        running_peak = max(running_peak, v_prev)
        threshold = running_peak * _EMPTY_EPSILON
        if v_prev <= threshold:
            if v_prev < -max(threshold, _EMPTY_FLOOR):
                break                # corrupt data — keep the prefix
            if v_curr > _EMPTY_FLOOR:
                running_peak = _ZERO          # re-link (same rule as twr)
            out.append((when, idx))  # performance break: carry flat
            continue
        idx *= (v_curr - cf_curr) / v_prev
        out.append((when, idx))
    return out


# ── Maximum drawdown ──────────────────────────────────────────────────────
def max_drawdown(
    value_series: list[tuple[datetime, Decimal]],
) -> Optional[dict]:
    """Largest peak-to-trough decline in a (date, value) series.

    Walks the series forward, tracking a running maximum (the peak).
    At each sample, computes (peak − value) / peak. Keeps the largest
    such drop. After identifying the (peak, trough), scans forward
    for `recovered_at`: the first sample whose value ≥ peak_value.

    Returns:
        {
          "peak_at":       datetime,
          "peak_value":    Decimal,
          "trough_at":     datetime,
          "trough_value":  Decimal,
          "drawdown_abs":  Decimal,        # peak - trough (>=0)
          "drawdown_pct":  Decimal,        # 0..1, e.g. 0.32 = 32% drop
          "recovered_at":  datetime | None,
        }

    Returns None for a series of < 2 samples or one where the peak
    is non-positive (no meaningful drawdown can be defined)."""
    if len(value_series) < 2:
        return None
    series = sorted(value_series, key=lambda t: t[0])
    peak_date, peak_val = series[0]
    running_peak_date, running_peak_val = series[0]
    worst_dd  = _ZERO
    worst_peak_date, worst_peak_val = series[0]
    worst_trough_date, worst_trough_val = series[0]
    for when, val in series[1:]:
        if val > running_peak_val:
            running_peak_date, running_peak_val = when, val
        if running_peak_val > 0:
            dd_pct = (running_peak_val - val) / running_peak_val
            if dd_pct > worst_dd:
                worst_dd = dd_pct
                worst_peak_date, worst_peak_val = running_peak_date, running_peak_val
                worst_trough_date, worst_trough_val = when, val
    if worst_peak_val <= 0:
        return None
    # Recovery: first sample at/after trough whose value >= peak_value
    recovered_at = None
    for when, val in series:
        if when < worst_trough_date:
            continue
        if val >= worst_peak_val:
            recovered_at = when
            break

    return {
        "peak_at":       worst_peak_date,
        "peak_value":    worst_peak_val,
        "trough_at":     worst_trough_date,
        "trough_value":  worst_trough_val,
        "drawdown_abs":  (worst_peak_val - worst_trough_val),
        "drawdown_pct":  worst_dd.quantize(Decimal("0.000001")),
        "recovered_at":  recovered_at,
    }
