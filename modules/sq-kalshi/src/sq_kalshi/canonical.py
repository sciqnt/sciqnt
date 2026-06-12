"""sq-kalshi — canonical adapter.

ALL Kalshi v2 dialect knowledge lives here. `live.py` does the I/O (RSA-PSS
signed HTTP); `to_canonical()` is pure: raw portfolio responses →
`PortfolioSnapshot` of AssetClass.EVENT positions + USD cash. Fixture-testable,
no network.

Kalshi field conventions (verified — research/connectors-prediction-markets-*.md):
- Money/count fields are fixed-point STRINGS: `_dollars` (up to 6dp),
  `_fp` (counts, 2dp). Parse to Decimal. Older cent-integer fields
  (total_traded, market_exposure, realized_pnl, yes/no_total_cost) are
  DEPRECATED — code against `_fp`/`_dollars`.
- `position_fp` is a SIGNED contract count: positive = YES side, negative = NO.
- Canonical price for an EVENT contract is a PROBABILITY in [0,1]. Kalshi quotes
  in cents (0..100), so price = cents/100. Conformance enforces the [0,1] band.

The live `/portfolio/positions` payload gives cost + realised P&L but NOT a
current market price per position; we leave `last_price_local=None` (a price
overlay from `/markets` would populate it — a separate step). cost_basis comes
from `market_exposure_dollars`; realised P&L from `realized_pnl_dollars`.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                       PortfolioSnapshot, Position)

_ZERO = Decimal("0")
_MONEY_QUANTUM = Decimal("0.00000001")


def _to_decimal(v) -> Decimal:
    """Kalshi fixed-point string (or number) → Decimal. None/''/junk → 0."""
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


def to_canonical(
    positions_resp,
    balance_resp,
    *,
    account_id: str = "kalshi",
    base_currency: str = "USD",
    market_meta: dict | None = None,
    market_prices: dict | None = None,
) -> PortfolioSnapshot:
    """Build a canonical snapshot from Kalshi portfolio responses.

    Args:
      positions_resp : GET /portfolio/positions JSON
                       {market_positions: [...], event_positions: [...], cursor}
      balance_resp   : GET /portfolio/balance JSON {balance, balance_dollars, ...}
      market_meta    : optional {ticker: {title, event_ticker, close_time,
                       result, ...}} from /markets to enrich names / outcome /
                       resolution_date. Sparse-OK (ticker-only labels otherwise).
      market_prices  : optional {ticker: Decimal} — the YES-side probability in
                       [0,1] (live.py converts Kalshi cents → /100). When present
                       for a position's market, mark-to-market is applied:
                       price = yes_prob (YES side) or 1−yes_prob (NO side);
                       value_base = qty × price; unrealized = value − cost_basis.
                       Absent → value_base stays 0 (cost-only view).
    """
    market_prices = market_prices or {}
    now = datetime.now(timezone.utc)
    market_meta = market_meta or {}
    instruments: list[Instrument] = []
    positions: list[Position] = []
    seen: set[str] = set()

    for mp in (positions_resp or {}).get("market_positions", []) or []:
        ticker = mp.get("ticker")
        if not ticker:
            continue
        qty = _to_decimal(mp.get("position_fp"))
        if qty == 0:
            # Kalshi returns settled/zero positions too; skip flat ones for the
            # live "what do I hold" view (realised P&L is read from settlements).
            continue
        outcome = "YES" if qty > 0 else "NO"
        instrument_id = f"kalshi:{ticker}"
        meta = market_meta.get(ticker, {})
        event_ticker = meta.get("event_ticker") or ticker.split("-")[0]

        if instrument_id not in seen:
            seen.add(instrument_id)
            resolution_date = None
            ct = meta.get("close_time") or meta.get("expiration_time")
            if isinstance(ct, str) and len(ct) >= 10:
                resolution_date = ct[:10]
            instruments.append(Instrument(
                valid_at=now, observed_at=now,
                instrument_id=instrument_id,
                identifiers={"broker:kalshi": ticker,
                             "kalshi:event_ticker": event_ticker},
                name=meta.get("title") or ticker,
                asset_class=AssetClass.EVENT,
                listing_currency=base_currency,
                terms={
                    "event_id":         event_ticker,
                    "outcome":          outcome,
                    "resolution_date":  resolution_date,
                    "market_result":    meta.get("result") or None,
                    "settlement_value": None,     # populated post-resolution
                },
            ))

        # cost basis (positive money) + realised P&L (signed) come straight
        # from the position record's _dollars fields.
        cost_basis = _to_decimal(mp.get("market_exposure_dollars")).copy_abs()
        realized   = _to_decimal(mp.get("realized_pnl_dollars"))
        fees       = _to_decimal(mp.get("fees_paid_dollars"))

        # Mark-to-market when a current market price is supplied. Kalshi
        # quotes the YES probability; a NO holder's contract is worth
        # (1 − yes_prob). value = qty × side-price; unrealized = value − cost.
        last_price = None
        value = _ZERO
        unrealized = _ZERO
        yes_prob = market_prices.get(ticker)
        if yes_prob is not None:
            yes_prob = _to_decimal(yes_prob)
            side_price = yes_prob if outcome == "YES" else (Decimal("1") - yes_prob)
            last_price = side_price
            value = qty.copy_abs() * side_price
            unrealized = value - cost_basis

        positions.append(Position(
            valid_at=now, observed_at=now,
            account_id=account_id, instrument_id=instrument_id,
            quantity=qty.copy_abs(),          # magnitude held; outcome carries the side
            last_price_local=last_price,      # YES/NO probability, or None (cost-only)
            value_base=_to_money(value),
            break_even_price_local=None,
            cost_basis_base=_to_money(cost_basis),
            unrealized_product_pl_base=_to_money(unrealized),
            unrealized_currency_pl_base=_ZERO,
            realized_product_pl_base=_to_money(realized),
            realized_currency_pl_base=_ZERO,
            realized_fees_base=_to_money(-fees.copy_abs()) if fees else _ZERO,
        ))

    # Cash — balance_dollars is the spendable USD balance.
    cash_balances = []
    bal = _to_decimal((balance_resp or {}).get("balance_dollars"))
    if bal == 0 and (balance_resp or {}).get("balance") is not None:
        # Fallback: older payloads expose integer cents under `balance`.
        bal = _to_decimal(balance_resp.get("balance")) / Decimal("100")
    if bal != 0:
        cash_balances.append(CashBalance(
            valid_at=now, observed_at=now,
            account_id=account_id, currency=base_currency,
            amount=_to_money(bal),
        ))

    account = Account(
        valid_at=now, observed_at=now,
        account_id=account_id, broker="kalshi", base_currency=base_currency,
    )
    return PortfolioSnapshot(
        valid_at=now, observed_at=now,
        account=account, instruments=instruments,
        positions=positions, cash_balances=cash_balances,
    )
