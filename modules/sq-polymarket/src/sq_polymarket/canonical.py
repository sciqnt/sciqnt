"""sq-polymarket — canonical adapter.

ALL Polymarket Data API dialect knowledge lives here. `live.py` does the I/O
(a public, no-auth GET); `to_canonical()` is pure: the positions list →
`PortfolioSnapshot` of AssetClass.EVENT positions. Fixture-testable.

Verified position fields (research/connectors-prediction-markets-*.md):
  size, avgPrice (0..1), curPrice (0..1), initialValue, currentValue,
  totalBought, cashPnl, realizedPnl, percentPnl, proxyWallet, asset
  (ERC-1155 outcome-token id), conditionId, outcome ("Yes"/"No"), outcomeIndex,
  title, slug, endDate, redeemable, negativeRisk.
REFUTED (do NOT rely on): eventId, eventSlug, oppositeOutcome.

Base currency = USDC. Price is already a probability in [0,1] (no /100 needed,
unlike Kalshi). conditionId is the market id; `asset` (token id) is the unique
per-OUTCOME id → the canonical instrument_id.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                       PortfolioSnapshot, Position)

_ZERO = Decimal("0")
_MONEY_QUANTUM = Decimal("0.00000001")


def _to_decimal(v) -> Decimal:
    if v in (None, ""):
        return _ZERO
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (TypeError, ValueError, InvalidOperation):
        return _ZERO


def _to_money(d: Decimal) -> Decimal:
    return d.quantize(_MONEY_QUANTUM)


def _norm_outcome(v) -> str:
    s = str(v or "").strip().upper()
    return s if s in ("YES", "NO") else (s or "?")


def to_canonical(
    positions,
    *,
    account_id: str = "polymarket",
    base_currency: str = "USDC",
    cash_usdc: Decimal | None = None,
) -> PortfolioSnapshot:
    """Build a canonical snapshot from the Polymarket Data API positions list.

    Args:
      positions : list of position dicts from
                  GET https://data-api.polymarket.com/positions?user=<addr>
      cash_usdc : optional on-chain USDC balance at the funder address (the
                  Data API positions call doesn't return cash; live.py may
                  read it separately). None → no cash balance emitted.
    """
    now = datetime.now(timezone.utc)
    instruments: list[Instrument] = []
    out_positions: list[Position] = []
    seen: set[str] = set()

    for p in positions or []:
        size = _to_decimal(p.get("size"))
        if size == 0:
            continue
        asset = p.get("asset")                       # ERC-1155 token id (per outcome)
        if not asset:
            continue
        instrument_id = f"polymarket:{asset}"
        avg = _to_decimal(p.get("avgPrice"))         # already 0..1
        cur = _to_decimal(p.get("curPrice"))         # already 0..1
        outcome = _norm_outcome(p.get("outcome"))

        if instrument_id not in seen:
            seen.add(instrument_id)
            end = p.get("endDate")
            resolution_date = end[:10] if isinstance(end, str) and len(end) >= 10 else None
            instruments.append(Instrument(
                valid_at=now, observed_at=now,
                instrument_id=instrument_id,
                identifiers={
                    "polymarket:asset":       str(asset),
                    "polymarket:conditionId": str(p.get("conditionId") or ""),
                },
                name=p.get("title") or p.get("slug") or str(asset),
                asset_class=AssetClass.EVENT,
                listing_currency=base_currency,
                terms={
                    "event_id":         p.get("conditionId") or None,
                    "outcome":          outcome,
                    "resolution_date":  resolution_date,
                    "market_result":    None,        # Data API doesn't expose at position-level
                    "settlement_value": None,
                },
            ))

        # Polymarket gives money fields directly. Prefer initialValue /
        # currentValue (authoritative) and fall back to size×price.
        cost_basis = _to_decimal(p.get("initialValue"))
        if cost_basis == 0:
            cost_basis = size * avg
        value = _to_decimal(p.get("currentValue"))
        if value == 0 and cur != 0:
            value = size * cur
        unrealized = value - cost_basis
        realized = _to_decimal(p.get("realizedPnl"))

        out_positions.append(Position(
            valid_at=now, observed_at=now,
            account_id=account_id, instrument_id=instrument_id,
            quantity=size,
            last_price_local=(cur if cur != 0 else None),
            value_base=_to_money(value),
            break_even_price_local=_to_money(avg),
            cost_basis_base=_to_money(cost_basis),
            unrealized_product_pl_base=_to_money(unrealized),
            unrealized_currency_pl_base=_ZERO,
            realized_product_pl_base=_to_money(realized),
            realized_currency_pl_base=_ZERO,
        ))

    cash_balances = []
    if cash_usdc is not None and _to_decimal(cash_usdc) != 0:
        cash_balances.append(CashBalance(
            valid_at=now, observed_at=now,
            account_id=account_id, currency=base_currency,
            amount=_to_money(_to_decimal(cash_usdc)),
        ))

    account = Account(
        valid_at=now, observed_at=now,
        account_id=account_id, broker="polymarket", base_currency=base_currency,
    )
    return PortfolioSnapshot(
        valid_at=now, observed_at=now,
        account=account, instruments=instruments,
        positions=out_positions, cash_balances=cash_balances,
    )
