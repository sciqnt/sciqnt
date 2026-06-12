"""Snapshot-level conformance invariants.

Pydantic validates structure + types + simple field rules. This module checks
**semantic** invariants Pydantic can't express: cross-entity duplicates,
sign sanity on money fields, closed-position cost-basis invariant, etc.

Usage:
    from sq_schema.conformance import check_snapshot, format_violations
    violations = check_snapshot(snapshot)
    if violations:
        raise AssertionError(format_violations(violations))

Connectors call this in their conformance tests right after `to_canonical()`;
runtime callers can use it as a tripwire on suspicious payloads. Both
"violations as data" (the list) and "violations as text" (the formatter)
are useful — keep them separate.

The set of checks is deliberately small. Add new rules as concrete drift
appears; do not pre-specify checks for hypothetical bugs."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Violation:
    """One invariant violation, with enough context to fix at source."""
    code: str           # short kebab-case identifier, e.g. "duplicate-position"
    message: str        # human-readable description with the specific values
    entity: str | None = None   # "position[2]" / "cash_balances[0]" / "account"


def check_snapshot(snapshot) -> list[Violation]:
    """Run every invariant check; return the (possibly empty) violation list.

    NOTE: this doesn't raise. Callers decide what to do with violations —
    some contexts want hard-failure (tests), others want graceful logging
    (a runtime adapter that ingested a slightly-off payload)."""
    v: list[Violation] = []

    _check_no_duplicate_positions(snapshot, v)
    _check_no_duplicate_cash(snapshot, v)
    _check_cost_basis_non_negative(snapshot, v)
    _check_closed_position_cost_basis_is_zero(snapshot, v)
    _check_value_base_consistent_with_quantity(snapshot, v)
    _check_decimal_precision_sane(snapshot, v)
    _check_event_price_is_probability(snapshot, v)
    _check_observed_at_not_before_valid_at_warning(snapshot, v)

    return v


# ── individual checks ─────────────────────────────────────────────────────
def _check_no_duplicate_positions(snapshot, v: list[Violation]) -> None:
    """One Position per (account_id, instrument_id). If a broker reports
    multiple lots for the same instrument, the connector must aggregate
    before producing the canonical snapshot — lots belong in the future
    Transaction model, not in Position."""
    seen = {}
    for i, p in enumerate(snapshot.positions):
        key = (p.account_id, p.instrument_id)
        if key in seen:
            v.append(Violation(
                code="duplicate-position",
                message=f"two Positions for ({p.account_id}, {p.instrument_id}); "
                        f"first at index {seen[key]}, duplicate at index {i}",
                entity=f"positions[{i}]",
            ))
        else:
            seen[key] = i


def _check_no_duplicate_cash(snapshot, v: list[Violation]) -> None:
    """One CashBalance per (account_id, currency). Aggregate before canonicalize."""
    seen = {}
    for i, c in enumerate(snapshot.cash_balances):
        key = (c.account_id, c.currency)
        if key in seen:
            v.append(Violation(
                code="duplicate-cash-balance",
                message=f"two CashBalances for ({c.account_id}, {c.currency}); "
                        f"first at index {seen[key]}, duplicate at index {i}",
                entity=f"cash_balances[{i}]",
            ))
        else:
            seen[key] = i


def _check_cost_basis_non_negative(snapshot, v: list[Violation]) -> None:
    """`cost_basis_base` is a positive money amount (the absolute cost paid)
    or zero (closed). Negative values mean the adapter forgot to flip a sign."""
    for i, p in enumerate(snapshot.positions):
        if p.cost_basis_base < 0:
            v.append(Violation(
                code="negative-cost-basis",
                message=f"cost_basis_base={p.cost_basis_base} should be ≥ 0 "
                        "(cost_basis is the absolute cost paid; 0 for closed positions)",
                entity=f"positions[{i}]",
            ))


def _check_closed_position_cost_basis_is_zero(snapshot, v: list[Violation]) -> None:
    """Closed positions (quantity = 0) have no current cost basis."""
    for i, p in enumerate(snapshot.positions):
        if not p.is_open and p.cost_basis_base != 0:
            v.append(Violation(
                code="closed-position-has-cost-basis",
                message=f"position is closed (quantity=0) but cost_basis_base="
                        f"{p.cost_basis_base} — should be 0",
                entity=f"positions[{i}]",
            ))


def _check_value_base_consistent_with_quantity(snapshot, v: list[Violation]) -> None:
    """value_base must be 0 when quantity is 0 (nothing held -> no value)."""
    for i, p in enumerate(snapshot.positions):
        if not p.is_open and p.value_base != 0:
            v.append(Violation(
                code="closed-position-has-value",
                message=f"position is closed (quantity=0) but value_base="
                        f"{p.value_base} — should be 0",
                entity=f"positions[{i}]",
            ))


def _check_decimal_precision_sane(snapshot, v: list[Violation]) -> None:
    """Catch float→Decimal precision pollution.

    If any money field shows >12 fractional digits, the adapter very
    likely converted via `Decimal(float_value)` instead of
    `Decimal(str(value))` — that route produces 50+ digits (e.g.
    `Decimal(0.1) == Decimal('0.1000000000000000055511151231257827021181583404541015625')`).

    Real-world broker payloads cap out at 4-6 fractional digits (fiat);
    crypto runs to 8 (satoshi). The 12-digit threshold leaves headroom
    for one rounded float-math step while still catching real pollution
    on the order of 50+ digits.

    Adapters that do float math (Degiro-style P/L decomposition) should
    quantize results to 8dp before storage (`_to_money` helper pattern)."""
    SUSPECT_DIGITS = 12
    money_fields = ("value_base", "cost_basis_base",
                    "unrealized_product_pl_base", "unrealized_currency_pl_base",
                    "realized_product_pl_base",   "realized_currency_pl_base")
    for i, p in enumerate(snapshot.positions):
        for field in money_fields:
            d: Decimal = getattr(p, field)
            exp = d.as_tuple().exponent
            # exp is the negative number of fractional digits, e.g. -2 for "1.23"
            if isinstance(exp, int) and exp < -SUSPECT_DIGITS:
                v.append(Violation(
                    code="decimal-precision-pollution",
                    message=f"{field}={d} has >{SUSPECT_DIGITS} fractional digits — "
                            "likely a float→Decimal conversion in the adapter "
                            "(use Decimal(str(v)) instead of Decimal(v))",
                    entity=f"positions[{i}]",
                ))


def _check_event_price_is_probability(snapshot, v: list[Violation]) -> None:
    """Event-contract (prediction-market) prices are probabilities in [0,1].
    A price outside that band almost always means the adapter forgot to
    divide a cents/percent quote by 100 (Kalshi quotes cents; Polymarket
    quotes 0..1). Catch it at the boundary — a $0.62 contract priced as
    62 would inflate value_base 100x.

    Only checked for instruments classified AssetClass.EVENT; everything
    else has unbounded prices."""
    from .enums import AssetClass
    inst_class = {i.instrument_id: i.asset_class for i in snapshot.instruments}
    for i, p in enumerate(snapshot.positions):
        if inst_class.get(p.instrument_id) is not AssetClass.EVENT:
            continue
        price = p.last_price_local
        if price is None:
            continue
        if price < Decimal("0") or price > Decimal("1"):
            v.append(Violation(
                code="event-price-not-probability",
                message=f"last_price_local={price} for an EVENT contract is "
                        "outside [0,1] — prediction-market prices are "
                        "probabilities; the adapter likely needs to divide a "
                        "cents/percent quote by 100",
                entity=f"positions[{i}]",
            ))


def _check_observed_at_not_before_valid_at_warning(snapshot, v: list[Violation]) -> None:
    """Observation should typically be at-or-after the valid time. A snapshot
    observed BEFORE the time it claims to represent is suspicious (clock drift?).
    NOT an error — historical corrections can legitimately have observed_at
    before a future-projected valid_at — so we don't emit anything in that case.
    Reserved here as a future check site; intentionally a no-op for now."""
    return


# ── formatting helper ─────────────────────────────────────────────────────
def format_violations(violations: list[Violation]) -> str:
    """Pretty-print a violation list for inclusion in assertion messages."""
    if not violations:
        return "no violations"
    lines = [f"  {len(violations)} conformance violation(s):"]
    for vio in violations:
        prefix = f"    [{vio.code}]"
        if vio.entity:
            prefix += f" {vio.entity}"
        lines.append(f"{prefix}: {vio.message}")
    return "\n".join(lines)
