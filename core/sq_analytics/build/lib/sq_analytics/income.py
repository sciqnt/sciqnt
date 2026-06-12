"""Income-event aggregates: dividends, fees, interest, taxes.

Operate on canonical Transactions. Pure functions. Same group_by argument
across the income analytics — 'year' / 'month' / 'instrument'."""
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from sq_schema import Transaction, TransactionType

_ZERO = Decimal("0")


def _bucket_key(t: Transaction, group_by: str):
    if group_by == "year":
        return t.executed_at.year
    if group_by == "month":
        return (t.executed_at.year, t.executed_at.month)
    if group_by == "instrument":
        return t.instrument_id or "(no-instrument)"
    raise ValueError(
        f"unknown group_by={group_by!r}; choose 'year' / 'month' / 'instrument'"
    )


def _aggregate_by_type(
    transactions: Iterable[Transaction],
    types: set,
    *,
    group_by: str,
    currency: str | None,
) -> dict:
    out: dict = defaultdict(lambda: _ZERO)
    for t in transactions:
        if t.type not in types:
            continue
        if currency is not None and t.amount_currency != currency:
            continue
        out[_bucket_key(t, group_by)] += t.amount
    return dict(out)


def dividend_history(
    transactions: Iterable[Transaction],
    *,
    group_by: str = "year",
    currency: str | None = None,
) -> dict:
    """Sum DIVIDEND transactions grouped by `group_by` (year / month / instrument).

    GROSS dividends only: dividend withholding tax is a `TransactionType.TAX`
    event and is NOT included here — TAX is a separate stream. Use
    `fold_cash_by_type` for every type side-by-side (and to derive a
    net-of-tax figure); this function answers 'how much gross dividend
    income did I receive?'.

    `currency` filter (e.g. 'EUR') restricts to one denomination — useful
    when an account holds dividends in multiple currencies and you want to
    aggregate each separately."""
    return _aggregate_by_type(
        transactions,
        types={TransactionType.DIVIDEND},
        group_by=group_by,
        currency=currency,
    )


def fee_history(
    transactions: Iterable[Transaction],
    *,
    group_by: str = "year",
    currency: str | None = None,
) -> dict:
    """Sum FEE transactions PLUS the per-trade `fee` field on BUY/SELL.

    Trade-side fees are stored as a magnitude on each Transaction.fee (the
    Degiro CSV puts `AutoFX Fee` + `Transaction and/or third party fees`
    here, normalised to `|abs|`); we treat them as debits (negative amounts)
    so the sum aligns with cash impact.

    Returns the same shape as `dividend_history`."""
    out: dict = defaultdict(lambda: _ZERO)
    for t in transactions:
        if currency is not None and t.amount_currency != currency:
            continue
        if t.type == TransactionType.FEE:
            out[_bucket_key(t, group_by)] += t.amount
        elif t.fee is not None and t.fee != 0:
            # Trade-side fee; sign-correct (always a debit)
            out[_bucket_key(t, group_by)] += -abs(t.fee)
    return dict(out)


def income_summary(
    transactions: Iterable[Transaction],
    *,
    base_currency: str,
    fx_provider=None,
    asof=None,
    year: int | None = None,
) -> dict:
    """Cross-currency income totals converted to `base_currency`: dividends,
    interest, fees. Each flow converts at its OWN execution date via
    `fx_provider` (the same FX-at-date discipline as `sq_performance.xirr`)
    — never at today's rate, which would smear FX timing into income.

    A flow whose rate is unavailable (no provider, currency outside the
    basket) is NOT silently dropped: it accumulates in `unconverted`,
    keyed by (stream, currency) so opposite-sign streams can never net
    to an invisible zero (a +$100 dividend and a −$100 fee must BOTH
    surface, audit find 2026-06-11).

    `asof` (datetime) — inclusive cutoff; `year` — restrict to one calendar
    year (e.g. the current one for a YTD figure).

    Returns `{"dividends": Decimal, "interest": Decimal, "fees": Decimal,
    "unconverted": {(stream, ccy): Decimal}}` — fees are negative (a
    debit), the income streams positive (barring corrections in the
    source data)."""
    totals = {"dividends": _ZERO, "interest": _ZERO, "fees": _ZERO}
    unconverted: dict[tuple[str, str], Decimal] = defaultdict(lambda: _ZERO)

    def _convert(amount: Decimal, ccy: str, executed_at) -> Decimal | None:
        if ccy == base_currency:
            return amount
        if fx_provider is None:
            return None
        rate = fx_provider.get_rate(ccy, base_currency,
                                    asof=executed_at.date())
        if rate is None:
            return None
        return amount * rate.rate

    for t in transactions:
        if asof is not None and t.executed_at > asof:
            continue
        if year is not None and t.executed_at.year != year:
            continue
        flows: list[tuple[str, Decimal]] = []
        if t.type == TransactionType.DIVIDEND:
            flows.append(("dividends", t.amount))
        elif t.type == TransactionType.INTEREST:
            flows.append(("interest", t.amount))
        elif t.type == TransactionType.FEE:
            # A FEE transaction's amount IS the fee — `t.fee` on the same
            # row would be the same money twice (mirrors `fee_history`'s
            # elif; the two fee surfaces must never disagree).
            flows.append(("fees", t.amount))
        if t.type != TransactionType.FEE and t.fee is not None and t.fee != 0:
            # Trade-side fee on any NON-FEE row (BUY/SELL/DIVIDEND…) —
            # same convention as `fee_history`: a debit.
            flows.append(("fees", -abs(t.fee)))
        for stream, amount in flows:
            converted = _convert(amount, t.amount_currency, t.executed_at)
            if converted is None:
                unconverted[(stream, t.amount_currency)] += amount
            else:
                totals[stream] += converted

    totals["unconverted"] = dict(unconverted)
    return totals
