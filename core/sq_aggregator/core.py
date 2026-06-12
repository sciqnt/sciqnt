"""Cross-broker aggregation primitives.

Each function takes a list of `BrokerSnapshot` and returns a deterministic
dict / list. The FX substrate handles cross-currency totals; legs we can't
convert are surfaced verbatim — we never silently sum across rates we
don't have. Same discipline as `sq-degiro live`'s summary tab, lifted up
to handle N brokers."""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

import sq_analytics
import sq_fx
from sq_fx import FxRateProvider
from sq_schema import CashBalance, Instrument, PortfolioSnapshot, Position

_ZERO = Decimal("0")


@dataclass
class BrokerSnapshot:
    """One broker's current snapshot + a stable label + any fetch error.

    `broker` is the short name (e.g. "degiro"); rendered in the per-broker
    column. `snapshot` is None when the fetch failed — `error` then carries
    a short reason for the status line. Aggregates skip None snapshots so a
    single broker outage never blocks the rest of the view."""
    broker: str
    snapshot: Optional[PortfolioSnapshot] = None
    error:    Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.snapshot is not None


@dataclass
class AggregatedValue:
    """Totals across brokers, denominated in `display_currency` where
    convertible. `unconverted_cash` carries legs whose currency the FX
    provider couldn't price — surface them in their native ccy rather than
    drop them silently."""
    display_currency: str
    total_value:       Optional[Decimal] = None   # positions + cash (converted legs only)
    positions_value:   Optional[Decimal] = None
    cash_value:        Decimal           = _ZERO
    total_realized_pl: Decimal           = _ZERO     # base-currency sums per broker
    total_unrealized_pl: Decimal         = _ZERO
    total_pl_lifetime: Decimal           = _ZERO
    open_position_count:   int           = 0
    closed_position_count: int           = 0
    unconverted_cash: list[tuple[str, str, Decimal]] = field(default_factory=list)
    # (broker, ccy, amount) — surface in native ccy when no rate is available.
    per_broker: list[dict] = field(default_factory=list)
    # One entry per ok broker with their own subtotals in their own base ccy.


# ── helpers ───────────────────────────────────────────────────────────────
def _ok_brokers(brokers: list[BrokerSnapshot]) -> list[BrokerSnapshot]:
    return [b for b in brokers if b.ok]


def _convert_or_none(amount: Decimal, src: str, dst: str,
                     provider: Optional[FxRateProvider]) -> Optional[Decimal]:
    if amount == 0:
        return _ZERO
    if src == dst:
        return amount
    return sq_fx.convert(amount, src, dst, provider=provider)


# ── public API ────────────────────────────────────────────────────────────
def aggregate_positions(
    brokers: list[BrokerSnapshot],
) -> list[tuple[str, Position, Instrument]]:
    """Flatten positions across all ok brokers, tagged with broker name.
    Caller groups / sorts as it likes — we just provide the flat triples
    (broker, Position, Instrument) so display logic can read either side
    without re-resolving the instrument."""
    out: list[tuple[str, Position, Instrument]] = []
    for b in _ok_brokers(brokers):
        inst_by_id = {i.instrument_id: i for i in b.snapshot.instruments}
        for p in b.snapshot.positions:
            inst = inst_by_id.get(p.instrument_id)
            if inst is None:
                continue          # snapshot violates its own FK invariants
            out.append((b.broker, p, inst))
    return out


def aggregate_cash(
    brokers: list[BrokerSnapshot],
) -> list[tuple[str, CashBalance]]:
    """Flatten cash balances across all ok brokers, tagged with broker name."""
    return [(b.broker, c) for b in _ok_brokers(brokers)
            for c in b.snapshot.cash_balances]


def aggregate_value(
    brokers: list[BrokerSnapshot],
    *,
    display_currency: str,
    fx_provider: Optional[FxRateProvider] = None,
) -> AggregatedValue:
    """Sum portfolio value, P/L, and counts across brokers in `display_currency`.

    Math discipline:
      * Position value is `Position.value_base`, which is already in the
        owning account's `base_currency`. We FX-convert that into the
        requested display currency.
      * Cash is FX-converted per (broker, ccy) leg. Any leg with no rate
        is recorded in `unconverted_cash` and NEVER folded into totals.
      * Realized / unrealized P/L sums stay in each broker's base ccy
        in `per_broker[*]` for honest reporting; the headline
        `total_*_pl` figures are FX-converted into the display currency.
        If any leg can't be converted, those headline totals become None.

    Returns an `AggregatedValue` with `total_value=None` whenever any
    contributing leg is unconverted (positions OR cash). That nudges the
    UI into showing partial data with the unconverted legs called out,
    instead of a single number that silently dropped some balance."""
    if fx_provider is None:
        fx_provider = sq_fx.get_provider()

    out = AggregatedValue(display_currency=display_currency)
    positions_total_display = _ZERO
    positions_value_unconverted = False

    for b in _ok_brokers(brokers):
        snap = b.snapshot
        base = snap.account.base_currency
        # Per-broker subtotals — always in that broker's own base ccy.
        positions_value_base = sum((p.value_base for p in snap.positions), _ZERO)
        realized_pl_base     = sum((p.realized_pl_base   for p in snap.positions), _ZERO)
        unrealized_pl_base   = sum((p.unrealized_pl_base for p in snap.positions), _ZERO)
        total_pl_lifetime    = sum((p.total_pl_base       for p in snap.positions), _ZERO)
        open_n   = sum(1 for p in snap.positions if p.is_open)
        closed_n = sum(1 for p in snap.positions if not p.is_open)
        # Net cash for THIS broker, in its own base ccy (foreign legs converted
        # to base; unconvertible legs skipped — best-effort, like the rest).
        cash_base = _ZERO
        for c in snap.cash_balances:
            if c.amount == 0:
                continue
            conv = _convert_or_none(c.amount, c.currency, base, fx_provider)
            if conv is not None:
                cash_base += conv

        out.per_broker.append({
            "broker": b.broker,
            "base_currency": base,
            "positions_value_base": positions_value_base,
            "cash_base":            cash_base,
            "realized_pl_base":     realized_pl_base,
            "unrealized_pl_base":   unrealized_pl_base,
            "total_pl_lifetime":    total_pl_lifetime,
            "open_position_count":   open_n,
            "closed_position_count": closed_n,
        })
        out.open_position_count   += open_n
        out.closed_position_count += closed_n

        # FX-convert positions value into display ccy
        converted = _convert_or_none(positions_value_base, base, display_currency, fx_provider)
        if converted is None:
            positions_value_unconverted = True
        else:
            positions_total_display += converted

        # FX-convert P/L sums into display ccy (broker base → display)
        for field_name, base_value in (
            ("total_realized_pl",   realized_pl_base),
            ("total_unrealized_pl", unrealized_pl_base),
            ("total_pl_lifetime",   total_pl_lifetime),
        ):
            current = getattr(out, field_name)
            if current is None:
                continue   # already poisoned by a prior leg
            converted_pl = _convert_or_none(base_value, base, display_currency, fx_provider)
            if converted_pl is None:
                setattr(out, field_name, None)   # surface partial truthfully
            else:
                setattr(out, field_name, current + converted_pl)

        # Cash: per (broker, ccy)
        for c in snap.cash_balances:
            if c.amount == 0:
                continue
            converted_cash = _convert_or_none(c.amount, c.currency, display_currency, fx_provider)
            if converted_cash is None:
                out.unconverted_cash.append((b.broker, c.currency, c.amount))
            else:
                out.cash_value += converted_cash

    out.positions_value = None if positions_value_unconverted else positions_total_display
    if out.positions_value is not None and not out.unconverted_cash:
        out.total_value = out.positions_value + out.cash_value
    return out


_MONEY_QUANTUM = Decimal("0.00000001")     # 8dp boundary, same as sq_market_data

# The stored money components on a Position (the derived properties —
# realized_pl_base / unrealized_pl_base / total_pl_base — sum these, so
# converting the components converts everything).
_POSITION_MONEY_FIELDS = (
    "value_base", "cost_basis_base",
    "realized_product_pl_base", "realized_currency_pl_base",
    "unrealized_product_pl_base", "unrealized_currency_pl_base",
    "realized_fees_base",
)


def _positions_in_display_ccy(
    brokers: list[BrokerSnapshot],
    display_currency: str,
    fx_provider,
) -> tuple[list, list]:
    """Each broker's positions with EVERY money field FX-converted from
    that broker's base currency into `display_currency`. Positions whose
    base can't convert are EXCLUDED and reported, never silently summed
    (audit find 2026-06-11: the exposure tables previously concatenated
    EUR and USD `value_base`s into one number).

    Returns `(converted, skipped)` where converted is
    `[(Position, Instrument)]` and skipped is `[(broker, base_ccy,
    n_positions)]`."""
    converted, skipped = [], []
    for b in brokers:
        if not b.ok:
            continue
        base = b.snapshot.account.base_currency
        inst_by_id = {i.instrument_id: i for i in b.snapshot.instruments}
        if base == display_currency:
            converted.extend((p, inst_by_id.get(p.instrument_id))
                             for p in b.snapshot.positions)
            continue
        rate = _convert_or_none(Decimal("1"), base, display_currency,
                                fx_provider)
        if rate is None:
            if b.snapshot.positions:
                skipped.append((b.broker, base, len(b.snapshot.positions)))
            continue
        for p in b.snapshot.positions:
            updates = {
                f: (getattr(p, f) * rate).quantize(_MONEY_QUANTUM)
                for f in _POSITION_MONEY_FIELDS
            }
            converted.append((p.model_copy(update=updates),
                              inst_by_id.get(p.instrument_id)))
    return converted, skipped


def aggregate_currency_exposure(
    brokers: list[BrokerSnapshot],
    *,
    display_currency: str,
    fx_provider=None,
) -> dict:
    """Run `sq_analytics.currency_exposure` over all brokers' positions
    with money fields FX-converted to `display_currency` first (the
    listing-currency BUCKETING still reflects each instrument's own
    currency — only the VALUES are display-ccy). Unconvertible brokers'
    positions are excluded; call `_positions_in_display_ccy` directly
    if you need the skip list."""
    pairs, _ = _positions_in_display_ccy(brokers, display_currency,
                                         fx_provider)
    positions   = [p for p, _ in pairs]
    instruments = list({i.instrument_id: i for _, i in pairs
                        if i is not None}.values())
    cash        = [c for _, c in aggregate_cash(brokers)]
    return sq_analytics.currency_exposure(
        positions, cash, instruments, base_currency=display_currency,
    )


def aggregate_asset_class_exposure(
    brokers: list[BrokerSnapshot],
    *,
    display_currency: str,
    fx_provider=None,
) -> tuple[dict, list]:
    """Run `sq_analytics.asset_class_exposure` over all brokers' positions
    FX-converted to `display_currency`. Returns `(exposure, skipped)` —
    skipped is `[(broker, base_ccy, n_positions)]` for brokers whose base
    couldn't convert (surface it; never silently sum mixed currencies)."""
    pairs, skipped = _positions_in_display_ccy(brokers, display_currency,
                                               fx_provider)
    positions   = [p for p, _ in pairs]
    instruments = list({i.instrument_id: i for _, i in pairs
                        if i is not None}.values())
    return sq_analytics.asset_class_exposure(
        positions, instruments, base_currency=display_currency,
    ), skipped
