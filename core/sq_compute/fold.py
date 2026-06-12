"""Fold a Transaction stream into a Position.

Pure function. Idempotent. PIT-correct via the `asof` parameter — ask for
the position at any historical instant and get the deterministic answer.

Realized P/L is decomposed into product (price-driven) vs currency (FX-driven)
components, mirroring the canonical Position field set. Same decomposition
formula as live.py's unrealized P/L:

  product  = (sell_price - lot_cost) × matched × sell_fx
  currency = lot_cost × matched × (sell_fx - lot_fx)

(For same-ccy holdings, fx_at_acquisition == sell_fx == 1, currency = 0.)
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Iterator, Optional

from sq_schema import Position, Transaction
from sq_schema.enums import TransactionType
from .booking import CostBasisMethod, Lot

_ZERO = Decimal("0")
_ONE  = Decimal("1")
_MONEY_QUANTUM = Decimal("0.00000001")    # 8dp / satoshi-level


def _to_money(d: Decimal) -> Decimal:
    """Quantize a Decimal to 8 fractional digits.
    Money fields must satisfy `conformance._check_decimal_precision_sane`
    (max 12 fractional digits); fold_position multiplies and divides
    freely during matching so its raw outputs grow to 28+ digits on real
    inputs. We quantize at the Position boundary so every consumer
    receives clean Decimals."""
    return d.quantize(_MONEY_QUANTUM)


def _build_position_snapshot(
    *, account_id, instrument_id, valid_at, observed_at,
    lots, realized_product, realized_currency, realized_fees,
) -> Position:
    """Build a Position from in-progress fold state. Pulled out so both
    `fold_position` and `fold_position_series` can share the exact same
    output shape — drift-by-construction prevention."""
    total_qty = sum((l.quantity for l in lots), _ZERO)
    if total_qty == 0:
        return Position(
            valid_at=valid_at, observed_at=observed_at,
            account_id=account_id, instrument_id=instrument_id,
            quantity=_ZERO,
            value_base=_ZERO,
            cost_basis_base=_ZERO,
            unrealized_product_pl_base=_ZERO,
            unrealized_currency_pl_base=_ZERO,
            realized_product_pl_base=_to_money(realized_product),
            realized_currency_pl_base=_to_money(realized_currency),
            realized_fees_base=_to_money(realized_fees),
        )
    cost_basis_base = sum((l.cost_basis_base for l in lots), _ZERO)
    bep_local = (sum((l.quantity * l.cost_per_unit_local for l in lots), _ZERO)
                 / total_qty)
    return Position(
        valid_at=valid_at, observed_at=observed_at,
        account_id=account_id, instrument_id=instrument_id,
        quantity=total_qty,
        value_base=_ZERO,
        break_even_price_local=_to_money(bep_local),
        cost_basis_base=_to_money(cost_basis_base),
        unrealized_product_pl_base=_ZERO,
        unrealized_currency_pl_base=_ZERO,
        realized_product_pl_base=_to_money(realized_product),
        realized_currency_pl_base=_to_money(realized_currency),
        realized_fees_base=_to_money(realized_fees),
    )


def _clone_lots(lots: list[Lot]) -> list[Lot]:
    """Deep copy of the current lot state. Used by fold_position_series
    to capture an immutable snapshot at each asof checkpoint without
    aliasing the in-progress state for later checkpoints."""
    return [Lot(
        quantity=l.quantity,
        cost_per_unit_local=l.cost_per_unit_local,
        fx_at_acquisition=l.fx_at_acquisition,
        acquired_at=l.acquired_at,
        fee_per_unit_local=l.fee_per_unit_local,
    ) for l in lots]


def fold_position_series(
    account_id: str,
    instrument_id: str,
    base_currency: str,
    transactions: Iterable[Transaction],
    asof_dates: Iterable[datetime],
    *,
    method: CostBasisMethod = CostBasisMethod.FIFO,
) -> dict[datetime, Position]:
    """Single-pass fold yielding a Position at every requested `asof_date`.

    Walks the (account, instrument) transaction slice once in
    chronological order; whenever we cross an asof checkpoint, snapshot
    the current lot state + cumulative realised P/L into a Position.
    Equivalent to calling `fold_position(asof=X)` for each X but
    O(transactions + asof_dates) instead of O(transactions × asof_dates)
    — material when N is large (e.g. TWR/drawdown computation samples
    at every cash-flow date).

    Returns a dict keyed by the asof datetime (one entry per requested
    date — duplicates are deduped). Dates before the first transaction
    return an empty-lot Position (quantity 0)."""
    relevant = sorted(
        (t for t in transactions
         if t.account_id == account_id
         and t.instrument_id == instrument_id),
        key=lambda t: t.executed_at,
    )
    sorted_asofs = sorted(set(asof_dates))
    if not sorted_asofs:
        return {}

    observed_at = datetime.now(timezone.utc)
    out: dict[datetime, Position] = {}

    lots: list[Lot] = []
    realized_product = _ZERO
    realized_currency = _ZERO
    realized_fees = _ZERO

    asof_idx = 0
    for t in relevant:
        # Before applying this tx, capture any checkpoints strictly
        # PRIOR to its time (transactions on the asof boundary itself
        # count as "applied by asof", matching fold_position's `<=`).
        while (asof_idx < len(sorted_asofs)
               and sorted_asofs[asof_idx] < t.executed_at):
            out[sorted_asofs[asof_idx]] = _build_position_snapshot(
                account_id=account_id, instrument_id=instrument_id,
                valid_at=sorted_asofs[asof_idx], observed_at=observed_at,
                lots=_clone_lots(lots),
                realized_product=realized_product,
                realized_currency=realized_currency,
                realized_fees=realized_fees,
            )
            asof_idx += 1

        if t.type == TransactionType.BUY:
            _apply_buy(t, lots, base_currency)
        elif t.type == TransactionType.DIVIDEND_REINVEST:
            _apply_buy(t, lots, base_currency)
        elif t.type == TransactionType.SELL:
            rp, rc, rf = _apply_sell(t, lots, base_currency, method)
            realized_product  += rp
            realized_currency += rc
            realized_fees     += rf
        elif t.type == TransactionType.SPLIT:
            _apply_split(t, lots)
        # Other types are cash-leg-only and don't touch lots.

    # Any asofs remaining are at-or-after all transactions — final state
    while asof_idx < len(sorted_asofs):
        out[sorted_asofs[asof_idx]] = _build_position_snapshot(
            account_id=account_id, instrument_id=instrument_id,
            valid_at=sorted_asofs[asof_idx], observed_at=observed_at,
            lots=_clone_lots(lots),
            realized_product=realized_product,
            realized_currency=realized_currency,
            realized_fees=realized_fees,
        )
        asof_idx += 1

    return out


def fold_position(
    account_id: str,
    instrument_id: str,
    base_currency: str,
    transactions: Iterable[Transaction],
    *,
    method: CostBasisMethod = CostBasisMethod.FIFO,
    asof: Optional[datetime] = None,
) -> Position:
    """Derive a Position from the (account, instrument) slice of a Transaction
    stream. Open positions return populated cost basis + zero realized
    unrealized P/L (caller overlays market price separately). Closed
    positions (quantity 0 after folding) carry lifetime realized P/L.

    The `asof` parameter trims the stream to `executed_at <= asof`, giving
    a PIT-correct historical position.

    `method` chooses lot-matching on sells. AVG collapses lots into a single
    average-cost lot before each sell; FIFO/LIFO traverse the lot list.

    Implementation: thin wrapper over `fold_position_series` with a
    single asof. The series form is the canonical primitive — use it
    directly when you need values at multiple dates (TWR / drawdown)."""
    # Pick an effective asof: either the user-supplied one, or the last
    # transaction's date (or "now" when there are no transactions).
    txn_list = [t for t in transactions
                if t.account_id == account_id
                and t.instrument_id == instrument_id
                and (asof is None or t.executed_at <= asof)]
    if asof is not None:
        eff_asof = asof
    elif txn_list:
        eff_asof = max(t.executed_at for t in txn_list)
    else:
        eff_asof = datetime.now(timezone.utc)
    series = fold_position_series(
        account_id=account_id, instrument_id=instrument_id,
        base_currency=base_currency, transactions=txn_list,
        asof_dates=[eff_asof], method=method,
    )
    return series[eff_asof]


# ── per-transaction handlers ───────────────────────────────────────────────
def _derive_fx(t: Transaction, base_currency: str) -> Decimal:
    """Resolve instrument_currency → base_currency for this transaction.

    Priority:
      1. Explicit `fx_rate` field (broker-reported, normalized by adapter).
      2. None set → fx = 1.0 (same currency).

    NOTE: a previous version of this function derived fx from
    `|amount| / (|qty| × price)` when amount_currency == base_currency and
    fx_rate was None. That logic is WRONG when `amount` is fees-inclusive
    (Degiro's `Total EUR` column includes AutoFX + transaction fees), because
    the derived fx then drifts away from 1 by exactly the fee ratio, which
    DOUBLE-COUNTS fees through both inflated cost basis AND the explicit
    fee allocation. We rely on the adapter contract: if instrument and
    amount currencies differ, set `fx_rate` explicitly; otherwise leave it
    None and we treat fx as 1.
    """
    if t.fx_rate is not None:
        return t.fx_rate
    return _ONE


def _apply_buy(t: Transaction, lots: list[Lot], base_currency: str) -> None:
    qty = t.quantity or _ZERO
    if qty <= 0:
        return
    price = t.price_local or _ZERO
    fx = _derive_fx(t, base_currency)
    # Allocate buy-side fee per unit in INSTRUMENT currency so partial sells
    # release a proportional fee. Transaction.fee is a positive magnitude in
    # amount_currency; we assume amount_currency == base_currency (true for
    # Degiro — fees are always EUR-side) and convert back to local via fx.
    buy_fee_local_per_unit = _ZERO
    if t.fee is not None and t.fee != 0 and fx != 0 and qty != 0:
        buy_fee_total_local = abs(t.fee) / fx        # base → instrument ccy
        buy_fee_local_per_unit = buy_fee_total_local / qty
    lots.append(Lot(
        quantity=qty,
        cost_per_unit_local=price,
        fx_at_acquisition=fx,
        acquired_at=t.executed_at,
        fee_per_unit_local=buy_fee_local_per_unit,
    ))


@dataclass
class Closure:
    """One matched portion during a SELL — emitted by `match_sell_lots`
    and consumed by both `fold_position` (sums the P/L) and
    `sq_analytics.tax_lots` (builds a ClosedLot per record). Sharing the
    iterator means the two code paths can never drift on cost-basis math.

    `lot` is a snapshot of the matched lot AT MATCH TIME — its quantity
    field reflects what remained before the match; subtract `matched` to
    see the post-match remainder. Other lot fields are immutable historical
    record (cost_per_unit_local, fx_at_acquisition, fee_per_unit_local,
    acquired_at) — safe to read after the iterator has moved on."""
    lot_acquired_at:       datetime
    lot_cost_per_unit_local: Decimal
    lot_fx_at_acquisition:   Decimal
    matched:                  Decimal
    sell_transaction:        "Transaction"
    sell_fx:                  Decimal
    realized_product_pl:     Decimal
    realized_currency_pl:    Decimal
    realized_fees_pl:        Decimal     # ≤ 0


def match_sell_lots(
    t: Transaction, lots: list[Lot], base_currency: str,
    method: CostBasisMethod,
):
    """Generator: yield one `Closure` per matched lot, in match order.

    Mutates `lots` in place — lot.quantity decrements as matches happen,
    and exhausted lots (quantity == 0) are dropped from the list at the
    end of the iteration.

    Sell-side fee is allocated **proportionally** across matched lots by
    matched-quantity. fold_position doesn't care which closure carries
    which share (it sums anyway); tax_lots needs the proportional split
    so each ClosedLot has its own correct fee allocation.

    AVG: lots are collapsed to a single weighted-avg lot BEFORE matching,
    matching exactly fold_position's prior behaviour. fee_per_unit is
    weight-averaged too.
    """
    sell_qty = -(t.quantity or _ZERO)
    if sell_qty <= 0:
        return
    sell_price = t.price_local or _ZERO
    sell_fx    = _derive_fx(t, base_currency)
    sell_fee_total = (abs(t.fee)
                      if (t.fee is not None and t.fee != 0) else _ZERO)

    # AVG: collapse lots → single weighted-avg lot (fee-aware)
    if method == CostBasisMethod.AVG and lots:
        total_qty = sum((l.quantity for l in lots), _ZERO)
        if total_qty > 0:
            weighted_cost     = sum((l.quantity * l.cost_per_unit_base    for l in lots), _ZERO)
            weighted_fee_base = sum((l.quantity * l.fee_per_unit_local
                                     * l.fx_at_acquisition                  for l in lots), _ZERO)
            avg_cost_per_unit_base = weighted_cost / total_qty
            avg_fee_per_unit_base  = weighted_fee_base / total_qty
            lots[:] = [Lot(
                quantity=total_qty,
                cost_per_unit_local=avg_cost_per_unit_base,
                fx_at_acquisition=_ONE,
                acquired_at=lots[0].acquired_at,
                fee_per_unit_local=avg_fee_per_unit_base,
            )]

    order = (range(len(lots) - 1, -1, -1) if method == CostBasisMethod.LIFO
             else range(len(lots)))

    # Two-pass so we can proportion the sell fee correctly across matches
    matched_pairs: list[tuple[int, Decimal]] = []
    remaining = sell_qty
    for i in order:
        if remaining <= 0:
            break
        lot = lots[i]
        if lot.quantity <= 0:
            continue
        m = min(remaining, lot.quantity)
        matched_pairs.append((i, m))
        remaining -= m
    actual_matched_total = sum((m for _, m in matched_pairs), _ZERO)

    for i, matched in matched_pairs:
        lot = lots[i]
        product = (sell_price - lot.cost_per_unit_local) * matched * sell_fx
        currency = lot.cost_per_unit_local * matched * (sell_fx - lot.fx_at_acquisition)
        # buy-side fee allocation (proportional within the lot)
        buy_fees = lot.fee_per_unit_local * matched * lot.fx_at_acquisition
        # sell-side fee allocation (proportional across matched lots)
        if actual_matched_total > 0 and sell_fee_total > 0:
            sell_fee_share = sell_fee_total * matched / actual_matched_total
        else:
            sell_fee_share = _ZERO
        fees = -(buy_fees + sell_fee_share)

        yield Closure(
            lot_acquired_at=lot.acquired_at,
            lot_cost_per_unit_local=lot.cost_per_unit_local,
            lot_fx_at_acquisition=lot.fx_at_acquisition,
            matched=matched,
            sell_transaction=t,
            sell_fx=sell_fx,
            realized_product_pl=product,
            realized_currency_pl=currency,
            realized_fees_pl=fees,
        )
        lot.quantity -= matched

    # Drop fully-consumed lots
    lots[:] = [l for l in lots if l.quantity > 0]


def _apply_sell(
    t: Transaction, lots: list[Lot], base_currency: str,
    method: CostBasisMethod,
) -> tuple[Decimal, Decimal, Decimal]:
    """Match the sell against lots per method, summing P/L components.
    Thin wrapper over `match_sell_lots` so fold_position and tax_lots
    share the same matching logic."""
    rp = rc = rf = _ZERO
    for c in match_sell_lots(t, lots, base_currency, method):
        rp += c.realized_product_pl
        rc += c.realized_currency_pl
        rf += c.realized_fees_pl
    return rp, rc, rf


def _apply_split(t: Transaction, lots: list[Lot]) -> None:
    """SPLIT semantics: t.quantity carries the RATIO (e.g. Decimal('2') for 2:1).
    Multiplies each lot's qty by ratio; divides EVERY per-unit amount by
    ratio so lot TOTALS are unchanged — cost basis AND the allocated buy
    fee. (Audit find 2026-06-11: fee_per_unit_local was left unscaled, so
    a post-split sell released buy fees at the pre-split per-unit rate on
    the post-split quantity — realised fees doubled across a 2:1 split.)"""
    ratio = t.quantity
    if ratio is None or ratio <= 0:
        return
    for lot in lots:
        lot.quantity            *= ratio
        lot.cost_per_unit_local /= ratio
        lot.fee_per_unit_local  /= ratio
