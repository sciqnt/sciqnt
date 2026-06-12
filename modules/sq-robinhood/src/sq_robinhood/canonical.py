"""sq-robinhood — canonical adapter.

ALL Robinhood / robin_stocks dialect knowledge lives here. `live.py` does the
I/O (login + HTTP via robin_stocks) and hands this module raw response dicts;
`to_canonical()` is a pure function: raw shapes → `PortfolioSnapshot`. No I/O,
no network, fully fixture-testable.

Money discipline: robin_stocks returns money as STRINGS (and `build_holdings()`
has a known `equity_change` 6-decimal formatting bug — we don't use it). We pull
the raw `get_open_stock_positions()` / `get_crypto_positions()` shapes, convert
every money field to `Decimal`, and quantize derived values to 8dp at the
Position boundary (the conformance check rejects >12-digit money).

Robinhood is USD-base. Stocks → AssetClass.STOCK, crypto → AssetClass.CRYPTO.
The live path carries NO realized P&L (Robinhood has no settlement events like
Degiro's CSV); realized_*_base = 0 until order-history reconstruction is wired
(see FINDINGS.md "honest gaps").
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                       PortfolioSnapshot, Position)

_ZERO = Decimal("0")
_MONEY_QUANTUM = Decimal("0.00000001")          # 8dp


def _to_decimal(v) -> Decimal:
    """robin_stocks money fields are strings; convert defensively. None /
    empty / unparseable → Decimal('0') so callers never need a guard."""
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


def _symbol_from_instrument(url, instrument_map) -> str | None:
    """Resolve a stock position's `instrument` URL → ticker symbol via the
    map live.py built (get_instrument_by_url). None if unresolved."""
    info = (instrument_map or {}).get(url) or {}
    return info.get("symbol")


def to_canonical(
    stock_positions,
    instrument_map,
    price_map,
    crypto_positions,
    crypto_price_map,
    account_profile,
    *,
    account_id: str = "robinhood",
    base_currency: str = "USD",
) -> PortfolioSnapshot:
    """Build a canonical `PortfolioSnapshot` from raw robin_stocks responses.

    Args (all raw robin_stocks shapes, resolved by live.py):
      stock_positions   : list from get_open_stock_positions()
      instrument_map    : {instrument_url: {symbol, simple_name/name, ...}}
      price_map         : {symbol: latest_price (str|Decimal)}
      crypto_positions  : list from get_crypto_positions()
      crypto_price_map  : {currency_code: latest_price (str|Decimal)}
      account_profile   : load_account_profile() {cash, uncleared_deposits, buying_power}
    """
    now = datetime.now(timezone.utc)
    instruments: list[Instrument] = []
    positions: list[Position] = []
    seen_instruments: set[str] = set()

    # ── Stock positions ────────────────────────────────────────────────
    for raw in stock_positions or []:
        qty = _to_decimal(raw.get("quantity"))
        if qty == 0:
            continue                                    # closed; skip
        url = raw.get("instrument")
        symbol = _symbol_from_instrument(url, instrument_map)
        if not symbol:
            # Can't price or name it without the symbol — skip rather than
            # emit a bogus instrument. (Honest degradation; logged by caller.)
            continue
        info = (instrument_map or {}).get(url) or {}
        instrument_id = f"robinhood:{symbol}"
        avg = _to_decimal(raw.get("average_buy_price"))
        price = _to_decimal((price_map or {}).get(symbol))

        if instrument_id not in seen_instruments:
            seen_instruments.add(instrument_id)
            identifiers = {"ticker": symbol, "broker:robinhood": symbol}
            if url:
                identifiers["robinhood:instrument_url"] = url
            instruments.append(Instrument(
                valid_at=now, observed_at=now,
                instrument_id=instrument_id,
                identifiers=identifiers,
                name=info.get("simple_name") or info.get("name") or symbol,
                asset_class=AssetClass.STOCK,
                listing_currency=base_currency,
            ))

        cost_basis = qty * avg
        value = qty * price
        positions.append(Position(
            valid_at=now, observed_at=now,
            account_id=account_id, instrument_id=instrument_id,
            quantity=qty,
            last_price_local=(price if price != 0 else None),
            value_base=_to_money(value),
            break_even_price_local=_to_money(avg),
            cost_basis_base=_to_money(cost_basis),
            unrealized_product_pl_base=_to_money((price - avg) * qty),
            unrealized_currency_pl_base=_ZERO,     # USD-base, USD-listed
            realized_product_pl_base=_ZERO,        # no settlement events on live path
            realized_currency_pl_base=_ZERO,
        ))

    # ── Crypto positions ───────────────────────────────────────────────
    for raw in crypto_positions or []:
        qty = _to_decimal(raw.get("quantity"))
        if qty == 0:
            continue
        ccy = (raw.get("currency") or {})
        code = ccy.get("code")
        if not code:
            continue
        instrument_id = f"robinhood:crypto:{code}"
        # avg cost from cost_bases[].direct_cost_basis / direct_quantity
        avg = _ZERO
        bases = raw.get("cost_bases") or []
        if bases:
            cb = bases[0]
            direct_cost = _to_decimal(cb.get("direct_cost_basis"))
            direct_qty  = _to_decimal(cb.get("direct_quantity"))
            if direct_qty != 0:
                avg = direct_cost / direct_qty
        price = _to_decimal((crypto_price_map or {}).get(code))

        if instrument_id not in seen_instruments:
            seen_instruments.add(instrument_id)
            instruments.append(Instrument(
                valid_at=now, observed_at=now,
                instrument_id=instrument_id,
                identifiers={"ticker": code, "broker:robinhood": f"crypto:{code}"},
                name=ccy.get("name") or code,
                asset_class=AssetClass.CRYPTO,
                listing_currency=base_currency,
            ))

        cost_basis = qty * avg
        value = qty * price
        positions.append(Position(
            valid_at=now, observed_at=now,
            account_id=account_id, instrument_id=instrument_id,
            quantity=qty,
            last_price_local=(price if price != 0 else None),
            value_base=_to_money(value),
            break_even_price_local=_to_money(avg),
            cost_basis_base=_to_money(cost_basis),
            unrealized_product_pl_base=_to_money((price - avg) * qty),
            unrealized_currency_pl_base=_ZERO,
            realized_product_pl_base=_ZERO,
            realized_currency_pl_base=_ZERO,
        ))

    # ── Cash ───────────────────────────────────────────────────────────
    # Robinhood cash = settled cash + uncleared deposits (mirrors how
    # build_holdings derives buying-power inputs). USD only.
    ap = account_profile or {}
    cash_amount = _to_decimal(ap.get("cash")) + _to_decimal(ap.get("uncleared_deposits"))
    cash_balances = []
    if cash_amount != 0:
        cash_balances.append(CashBalance(
            valid_at=now, observed_at=now,
            account_id=account_id, currency=base_currency,
            amount=_to_money(cash_amount),
        ))

    account = Account(
        valid_at=now, observed_at=now,
        account_id=account_id, broker="robinhood", base_currency=base_currency,
    )
    return PortfolioSnapshot(
        valid_at=now, observed_at=now,
        account=account, instruments=instruments,
        positions=positions, cash_balances=cash_balances,
    )
