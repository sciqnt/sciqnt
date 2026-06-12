"""Degiro → canonical adapter (Milestone 0 steps 2 + 5).

THIS IS THE ONLY FILE IN sq-degiro THAT KNOWS DEGIRO FIELD NAMES.

Two public adapters, parallel shape:

  to_canonical(raw_update, raw_products, base_ccy, int_account)
                                                     -> PortfolioSnapshot
        Live (API) path. Translates a single get_update() snapshot.

  to_canonical_transactions(transactions_csv_path, *, account_id)
                                                     -> list[Transaction]
        CSV (history) path. Parses transactions.csv into the canonical
        immutable event log. Feed to sq_compute.fold_position() to derive
        historical Positions; the result should reconcile to sq_degiro's
        pre-canonical pnl.py compute() (the test suite pins this).

Pure functions only — no network I/O, no credentials. Takes raw inputs
(dicts / file paths) in, returns `sq_schema` Pydantic types out.
"""
import csv
import pathlib
import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import (  # noqa: E402
    Account, AssetClass, CashBalance, Instrument, PortfolioSnapshot,
    Position, Transaction, TransactionType,
)


# ═══════════════════════════════════════════════════════════════════════════
# Dialect helpers — private. Anything that touches a Degiro field name lives
# here. If you find yourself adding a `_probe(..., "newDegiroField")` call
# anywhere else, it belongs here instead.
# ═══════════════════════════════════════════════════════════════════════════
def _flatten(row: dict) -> dict:
    """Degiro returns each row as {'value': [{'name': k, 'value': v}, ...]}."""
    return {kv.get("name"): kv.get("value") for kv in (row or {}).get("value", [])}


def _probe(d: dict | None, *keys, default=None):
    """Multi-key field-name probe. Degiro's payload shape drifts between
    library versions, so callers list every plausible name; we return the
    first non-empty hit."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return default


def _money_in(v, ccy: str):
    """Degiro stores some money fields as {currency: amount} dicts. Extract
    the amount for `ccy`; fall back to the first available value if the base
    ccy isn't keyed (defensive — shouldn't happen for an account's own data)."""
    if isinstance(v, dict):
        if ccy and ccy in v:
            return v[ccy]
        return next(iter(v.values()), None) if v else None
    return v


def _to_decimal(v) -> Decimal:
    """Float → str → Decimal to avoid binary-precision pollution. Returns
    Decimal('0') for None / empty / unparseable so callers can rely on the
    type without defensive wrappers."""
    if v in (None, ""):
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (TypeError, ValueError, InvalidOperation):
        return Decimal("0")


# 8 decimal places — satoshi-level precision; tight enough for any fiat
# broker (4dp tops in real-world payloads) and enough headroom for crypto.
_MONEY_QUANTUM = Decimal("0.00000001")


def _to_money(v) -> Decimal:
    """Like _to_decimal, but quantized to 8dp. Use for adapter outputs that
    flow into Position money fields — drops the trailing float-precision
    digits that `_compute_pl`'s float math produces (e.g. 552.3590243902448
    → 552.35902439). Conformance harness expects this discipline."""
    return _to_decimal(v).quantize(_MONEY_QUANTUM)


# ── Base-currency discovery (3-layer probe) ────────────────────────────────
_BASE_CCY_PATHS = (
    ("data", "currency"),
    ("data", "baseCurrency"),
    ("data", "intAccountInfo", "currency"),
    ("data", "intAccountInfo", "baseCurrency"),
    ("data", "cashAccount", "currency"),
)


def extract_base_ccy(raw_account_info: dict | None,
                     raw_client_details: dict | None,
                     raw_update: dict | None) -> str | None:
    """Resolve the account's base currency from any of the three Degiro
    response sources. Returns None if none match — caller decides what
    to do (config override, prompt, etc.)."""
    for resp in (raw_account_info, raw_client_details):
        if not isinstance(resp, dict):
            continue
        for chain in _BASE_CCY_PATHS:
            cur = resp
            for k in chain:
                cur = cur.get(k) if isinstance(cur, dict) else None
                if cur is None:
                    break
            if isinstance(cur, str) and len(cur) == 3:
                return cur
    # Cash-list heuristic: if every cash balance is in one ccy, that's the base.
    cash_rows = (raw_update or {}).get("cashFunds", {}).get("value", [])
    ccys = set()
    for row in cash_rows:
        flat = _flatten(row)
        if flat.get("value") in (0, "0", None, ""):
            continue
        ccy = flat.get("currencyCode") or flat.get("id")
        if isinstance(ccy, str) and len(ccy) == 3:
            ccys.add(ccy)
    return next(iter(ccys)) if len(ccys) == 1 else None


# ── productType → AssetClass mapping ──────────────────────────────────────
_ASSET_CLASS_MAP = {
    "STOCK":    AssetClass.STOCK,
    "ETF":      AssetClass.ETF,
    "BOND":     AssetClass.BOND,
    "FUND":     AssetClass.FUND,
    "OPTION":   AssetClass.OPTION,
    "FUTURE":   AssetClass.FUTURE,
    "CURRENCY": AssetClass.FX,
    "CRYPTO":   AssetClass.CRYPTO,
    "INDEX":    AssetClass.INDEX,
    "WARRANT":  AssetClass.WARRANT,
    "CFD":      AssetClass.CFD,
}


def _asset_class(degiro_product_type) -> AssetClass:
    if not degiro_product_type:
        return AssetClass.OTHER
    return _ASSET_CLASS_MAP.get(str(degiro_product_type).upper(), AssetClass.OTHER)


# ── P/L decomposition (the math) ──────────────────────────────────────────
def _compute_pl(h: dict, info: dict | None, base_ccy: str) -> dict:
    """Decompose Degiro's position fields into the canonical 5-field shape.

    Returns a dict with the keys needed to instantiate a `Position`:
      cost_basis                     (positive; 0 for closed)
      unrealized_product_pl_base     (price-driven unrealized; 0 for closed)
      unrealized_currency_pl_base    (FX-driven unrealized; 0 for closed)
      realized_product_pl_base       (lifetime realized — price portion)
      realized_currency_pl_base      (lifetime realized — FX portion)

    Semantics, verified against IB01 to the cent (Degiro web detail view):
      total_pl = value + plBase
      unrealized = total - realized   (for open; 0 for closed by definition)
      For cross-ccy open positions, unrealized further decomposes as:
        product  = (price - BEP) × qty × current_fx - realized_product
        currency = (BEP × qty) × (current_fx - avg_fx) - realized_fx
      For same-ccy: currency = 0, product = unrealized.
      For closed: if Degiro didn't populate the realized split, dump the
      lifetime P/L into realized_product so the derived total_pl_base
      invariant holds (= value + plBase).

    Money math is Decimal end-to-end (H1): every field is parsed via
    `_to_decimal` and all arithmetic — including the FX-rate back-out
    divisions — stays Decimal, so no value ever passes through binary float.
    Division uses the default decimal context (28 significant digits); the
    `_to_money` boundary in `to_canonical` quantizes outputs to 8dp exactly
    as before. Reconciled cent-for-cent against the prior float output on a
    live snapshot (see tests + the H1 commit)."""
    ZERO = Decimal("0")
    value = _to_decimal(h.get("value"))
    plbase = _to_decimal(_money_in(_probe(h, "plBase"), base_ccy))
    realized_product = _to_decimal(_money_in(_probe(h, "realizedProductPl"), base_ccy))
    realized_fx      = _to_decimal(_money_in(_probe(h, "realizedFxPl"),      base_ccy))
    total_pl = value + plbase
    is_open = h.get("size") not in (0, "0", None)

    if not is_open:
        # Closed: unrealized = 0; realized = total. If Degiro didn't ship the
        # split, attribute the whole lifetime P/L to realized_product as a
        # best-effort (consumer can still trust derived total_pl_base).
        if realized_product == 0 and realized_fx == 0 and total_pl != 0:
            realized_product = total_pl
        return {
            "cost_basis":                  ZERO,
            "unrealized_product_pl_base":  ZERO,
            "unrealized_currency_pl_base": ZERO,
            "realized_product_pl_base":    realized_product,
            "realized_currency_pl_base":   realized_fx,
        }

    # Open
    cost_basis = -plbase if plbase < 0 else ZERO
    instrument_ccy = (info or {}).get("currency")
    qty   = _to_decimal(h.get("size"))
    price = _to_decimal(h.get("price"))
    bep   = _to_decimal(_probe(h, "breakEvenPrice", "bep", "averageBuyingPrice"))

    if (instrument_ccy and base_ccy and instrument_ccy != base_ccy
            and qty and price and bep and plbase):
        current_fx = value / (price * qty) if (price * qty) else ZERO
        avg_fx     = -plbase / (bep * qty) if (bep * qty) else ZERO
        unrealized_product_pl  = (price - bep) * qty * current_fx           - realized_product
        unrealized_currency_pl = (bep * qty) * (current_fx - avg_fx)         - realized_fx
    else:
        # Same-ccy or insufficient data: all unrealised is "product"
        unrealized_pl = total_pl - (realized_product + realized_fx)
        unrealized_product_pl  = unrealized_pl
        unrealized_currency_pl = ZERO

    return {
        "cost_basis":                  cost_basis,
        "unrealized_product_pl_base":  unrealized_product_pl,
        "unrealized_currency_pl_base": unrealized_currency_pl,
        "realized_product_pl_base":    realized_product,
        "realized_currency_pl_base":   realized_fx,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Main adapter — the only public function (besides extract_base_ccy)
# ═══════════════════════════════════════════════════════════════════════════
def to_canonical(
    raw_update: dict,
    raw_products: dict,
    base_ccy: str,
    int_account,
    broker: str = "degiro",
    snapshot_time: datetime | None = None,
) -> PortfolioSnapshot:
    """Translate Degiro raw responses into a canonical PortfolioSnapshot.

    Args:
      raw_update     output of api.get_update(request_list=..., raw=True).
      raw_products   the `.data` subdict from api.get_products_info(...).
                     Maps str(productId) → product info dict (symbol/isin/
                     name/currency/productType/exchangeId/...).
      base_ccy       3-letter ISO 4217 base currency (use extract_base_ccy
                     to discover it before calling).
      int_account    broker-assigned account number (any stringifiable type).
      broker         broker tag for ID namespacing — default "degiro".
      snapshot_time  the moment this snapshot represents (valid_at on every
                     entity). Default: now UTC."""
    when = snapshot_time or datetime.now(timezone.utc)
    account_id = str(int_account)

    account = Account(
        valid_at=when, observed_at=when,
        account_id=account_id,
        broker=broker,
        base_currency=base_ccy,
    )

    # ── Positions + Instruments ─────────────────────────────────────────
    portfolio_rows = (raw_update or {}).get("portfolio", {}).get("value", [])
    instruments: list[Instrument] = []
    seen_instruments: set[str] = set()

    # Two-pass: first build a per-instrument-id accumulator so multiple
    # broker rows on the same ISIN (Degiro can split one ISIN across
    # multiple productIds — corporate actions, listing-venue splits)
    # collapse to ONE canonical Position. The conformance contract is
    # one Position per (account, instrument); lots belong in the
    # Transaction model, not Position.
    by_iid: dict[str, dict] = {}
    for raw_row in portfolio_rows:
        h = _flatten(raw_row)
        if str(h.get("positionType")) != "PRODUCT":
            continue
        pid = str(h.get("id", ""))
        if not pid:
            continue

        info = raw_products.get(pid, {}) or {}
        # Prefer ISIN-form instrument_id when the broker shipped one — it's
        # the cross-source stable key (CSV adapters also use it). Fall back
        # to the broker-internal productId when no ISIN is available, so
        # broker-only products (cash funds, indices) still get IDs.
        isin = info.get("isin")
        instrument_id = f"{broker}:isin:{isin}" if isin else f"{broker}:{pid}"

        if instrument_id not in seen_instruments:
            seen_instruments.add(instrument_id)
            identifiers = {f"broker:{broker}": pid}
            if isin:
                identifiers["isin"]   = isin
            if info.get("symbol"):
                identifiers["ticker"] = info["symbol"]
            instruments.append(Instrument(
                valid_at=when, observed_at=when,
                instrument_id=instrument_id,
                identifiers=identifiers,
                name=info.get("name") or pid,
                asset_class=_asset_class(info.get("productType")),
                listing_currency=(info.get("currency") or base_ccy),
                listing_venue=(info.get("exchangeId") or info.get("vwdExchangeId")),
            ))

        pl = _compute_pl(h, info, base_ccy)
        bep_raw = _probe(h, "breakEvenPrice", "bep", "averageBuyingPrice")
        qty = _to_decimal(h.get("size"))
        bep_local = (_to_decimal(bep_raw)
                     if bep_raw not in (None, "") else None)
        row = {
            "quantity":         qty,
            "value_base":       _to_decimal(h.get("value")),
            "last_price_local": (_to_decimal(h.get("price"))
                                 if h.get("price") not in (None, "") else None),
            "bep_local":        bep_local,
            "cost_basis":       _to_money(pl["cost_basis"]),
            "u_prod":           _to_money(pl["unrealized_product_pl_base"]),
            "u_curr":           _to_money(pl["unrealized_currency_pl_base"]),
            "r_prod":           _to_money(pl["realized_product_pl_base"]),
            "r_curr":           _to_money(pl["realized_currency_pl_base"]),
        }
        acc = by_iid.get(instrument_id)
        if acc is None:
            by_iid[instrument_id] = row
        else:
            # Merge: sum money + qty; weighted-average BEP by quantity; keep
            # the first non-None last_price (same-ISIN rows trade in lockstep
            # most of the time — when they don't, broker-native dialect is
            # leaking and the user should see one number, deterministically
            # chosen).
            prev_qty = acc["quantity"]
            new_qty  = prev_qty + qty
            if (acc["bep_local"] is not None and bep_local is not None
                    and new_qty > 0):
                acc["bep_local"] = ((acc["bep_local"] * prev_qty
                                     + bep_local * qty) / new_qty)
            elif acc["bep_local"] is None:
                acc["bep_local"] = bep_local
            acc["quantity"]   = new_qty
            acc["value_base"]   += row["value_base"]
            acc["cost_basis"]   = _to_money(acc["cost_basis"]   + row["cost_basis"])
            acc["u_prod"]       = _to_money(acc["u_prod"]       + row["u_prod"])
            acc["u_curr"]       = _to_money(acc["u_curr"]       + row["u_curr"])
            acc["r_prod"]       = _to_money(acc["r_prod"]       + row["r_prod"])
            acc["r_curr"]       = _to_money(acc["r_curr"]       + row["r_curr"])
            if acc["last_price_local"] is None:
                acc["last_price_local"] = row["last_price_local"]

    positions: list[Position] = [
        Position(
            valid_at=when, observed_at=when,
            account_id=account_id,
            instrument_id=iid,
            quantity=v["quantity"],
            last_price_local=v["last_price_local"],
            value_base=v["value_base"],
            break_even_price_local=v["bep_local"],
            cost_basis_base=v["cost_basis"],
            unrealized_product_pl_base=v["u_prod"],
            unrealized_currency_pl_base=v["u_curr"],
            realized_product_pl_base=v["r_prod"],
            realized_currency_pl_base=v["r_curr"],
        )
        for iid, v in by_iid.items()
    ]

    # ── Cash balances ───────────────────────────────────────────────────
    cash_balances: list[CashBalance] = []
    for raw_row in (raw_update or {}).get("cashFunds", {}).get("value", []):
        flat = _flatten(raw_row)
        ccy = flat.get("currencyCode") or flat.get("id")
        if not (isinstance(ccy, str) and len(ccy) == 3):
            continue                                # skip malformed rows
        cash_balances.append(CashBalance(
            valid_at=when, observed_at=when,
            account_id=account_id,
            currency=ccy,
            amount=_to_decimal(flat.get("value")),
            amount_base=None,                       # populated when sq-fx arrives
        ))

    return PortfolioSnapshot(
        valid_at=when, observed_at=when,
        account=account,
        instruments=instruments,
        positions=positions,
        cash_balances=cash_balances,
    )


# ═══════════════════════════════════════════════════════════════════════════
# CSV adapter — Degiro's transactions.csv → canonical Transactions
# ═══════════════════════════════════════════════════════════════════════════
def _parse_degiro_decimal(s: Optional[str]) -> Optional[Decimal]:
    """Degiro CSVs use European number format: `.` thousands sep, `,` decimal sep.
    Mirrors pnl.py's `num()` logic so they parse identically."""
    if s is None:
        return None
    s = s.strip().strip('"').replace("\xa0", " ").strip().replace(" ", "")
    if s == "":
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _parse_degiro_date(s: str) -> Optional[date]:
    """Degiro CSV dates are `DD-MM-YYYY`."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        d, m, y = s.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _parse_degiro_time(s: str) -> time:
    """Degiro CSV times are `HH:MM` (sometimes empty)."""
    s = (s or "").strip()
    if not s:
        return time(0, 0)
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return time(0, 0)


# transactions.csv column indices (verified against fixture + pnl.py):
#   0  Date            (DD-MM-YYYY)
#   1  Time            (HH:MM)
#   2  Product         (name)
#   3  ISIN
#   4  Reference exchange
#   5  Venue
#   6  Quantity        (signed: + = buy / - = sell)
#   7  Price           (per-unit, in `Local value`'s currency)
#   8  (currency code for Price/Local value — header is empty)
#   9  Local value     (signed)
#   10 (currency code for Local value AGAIN — header is empty. NOT the
#       cash-leg currency: real exports show GBX/USD here for foreign
#       listings while Value EUR / Total EUR stay EUR. Verified against
#       live exports 2026-06-11 — see FINDINGS "transactions.csv column
#       semantics".)
#   11 Value EUR       (signed; FX-converted from Local value, before fees)
#   12 Exchange rate   (instrument-ccy → EUR; empty when local==EUR)
#   13 AutoFX Fee EUR
#   14 Transaction and/or third party fees EUR
#   15 Total EUR       (Value EUR + fees, signed; the net cash hit)
#   16 Order ID        (header position — but real exports carry an EMPTY
#       field here and put the uuid at 17; both shapes are read)
_TX_COL_DATE          = 0
_TX_COL_TIME          = 1
_TX_COL_ISIN          = 3
_TX_COL_QTY           = 6
_TX_COL_PRICE         = 7
_TX_COL_LOCAL_CCY     = 8
_TX_COL_LOCAL_VALUE   = 9
_TX_COL_LOCAL_CCY_2   = 10
_TX_COL_VALUE_EUR     = 11
_TX_COL_EXCHANGE_RATE = 12
_TX_COL_AUTOFX_FEE    = 13
_TX_COL_OTHER_FEE     = 14
_TX_COL_TOTAL_EUR     = 15
_TX_COL_ORDER_ID      = 16
_TX_COL_ORDER_ID_ALT  = 17


def to_canonical_transactions(
    transactions_csv: Path,
    *,
    account_id: str,
    broker: str = "degiro",
) -> list[Transaction]:
    """Parse Degiro's `transactions.csv` into canonical Transactions.

    One Transaction per row:
      type            BUY  if Quantity > 0; SELL if Quantity < 0
      instrument_id   f"{broker}:isin:{ISIN}"
      executed_at     Date + Time, naive UTC (Degiro CSV is local Amsterdam
                      time — we don't have the tz from the CSV; treat as
                      UTC for now; documented as a known approximation)
      quantity        signed (matches our convention)
      price_local     CSV Price (listed; NOT fee-adjusted)
      amount          CSV Total EUR (signed, INCLUDES fees)
      amount_currency "EUR" — the cash leg ("Total EUR" by header) is
                      always the account base. Column 10 is NOT the cash
                      ccy: it repeats the LOCAL currency (GBX/USD for
                      foreign listings) and labelling the EUR amount with
                      it broke every FX join downstream (found via the
                      income summary, 2026-06-11).
      fee             AutoFX Fee + Other fees (column 13 + 14)
                      Always non-negative; the absolute value of the
                      Degiro-reported fee (CSV sign convention varies; we
                      normalise to magnitude for cleanliness).
      fx_rate         CSV Exchange rate (None when same-ccy as account base)
      description     "Order order_id" if present, else None
      transaction_id  the order_id if present, else f"row-{i}-{date}"

    Note on fee semantics: Degiro's `Total EUR` already includes fees in the
    cash leg, so `amount` is fees-inclusive. The separate `fee` field is for
    audit / reporting. When reconciling fold_position output against the
    pre-canonical pnl.py, fees do NOT appear in fold's realised P/L (which is
    price-driven); they DO appear in pnl.py's realised total (which sums
    Total EUR for closed positions). The test suite asserts that fold's
    realised + sum(fees for the closed instrument) == pnl.py's realised."""
    transactions_csv = Path(transactions_csv)
    out: list[Transaction] = []

    with open(transactions_csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    if not rows:
        return []

    for i, r in enumerate(rows[1:], start=2):                   # 1-based, skip header
        # Minimum = every MONEY column present (through Total EUR, col 15).
        # Order ID is optional/trailing — requiring 17 columns silently
        # dropped otherwise-valid 16-column trade rows (audit 2026-06-11).
        if len(r) <= _TX_COL_TOTAL_EUR or not r[_TX_COL_DATE].strip():
            continue
        d = _parse_degiro_date(r[_TX_COL_DATE])
        if d is None:
            continue
        executed_at = datetime.combine(d, _parse_degiro_time(r[_TX_COL_TIME]),
                                       tzinfo=timezone.utc)
        isin = r[_TX_COL_ISIN].strip()
        if not isin:
            continue
        qty = _parse_degiro_decimal(r[_TX_COL_QTY])
        if qty is None or qty == 0:
            continue                                            # malformed / zero-qty row

        price_local = _parse_degiro_decimal(r[_TX_COL_PRICE])
        total_eur   = _parse_degiro_decimal(r[_TX_COL_TOTAL_EUR]) or Decimal("0")
        autofx_fee  = _parse_degiro_decimal(r[_TX_COL_AUTOFX_FEE])  or Decimal("0")
        other_fee   = _parse_degiro_decimal(r[_TX_COL_OTHER_FEE])   or Decimal("0")
        fee_total   = abs(autofx_fee) + abs(other_fee)
        # The cash leg is the "Total EUR" column — account-base EUR by
        # definition. (Column 10 looks like a currency code but repeats
        # the LOCAL listing currency; see the column map above.)
        amount_ccy  = "EUR"

        # Degiro CSV's `Exchange rate` is in their convention:
        #   amount_local_ccy = amount_base_ccy × exchange_rate
        # i.e. for a GBX-priced row settled in EUR with rate=86.24, ONE
        # EUR equals 86.24 GBX. Our canonical convention is the inverse:
        # `fx_rate` = how many amount-currency units per ONE instrument-
        # currency unit (so 0.01159 EUR per GBX). Invert at the adapter
        # boundary so consumers (fold_position, etc.) get a number that
        # multiplies cleanly with price_local to give base-ccy amounts.
        csv_fx = _parse_degiro_decimal(r[_TX_COL_EXCHANGE_RATE])
        if csv_fx is not None and csv_fx != 0:
            fx_rate = Decimal(1) / csv_fx
        else:
            fx_rate = None        # same-ccy row; let _derive_fx fall through
        # Real exports leave 16 empty and put the uuid at 17; synthetic /
        # older shapes may use 16 directly. Take whichever is non-empty.
        order_id = ""
        for col in (_TX_COL_ORDER_ID, _TX_COL_ORDER_ID_ALT):
            if len(r) > col and r[col].strip():
                order_id = r[col].strip()
                break

        tx_type = TransactionType.BUY if qty > 0 else TransactionType.SELL
        tx_id   = order_id or f"row-{i}-{isin}-{d.isoformat()}"

        out.append(Transaction(
            valid_at=executed_at, observed_at=datetime.now(timezone.utc),
            transaction_id=tx_id,
            account_id=account_id,
            instrument_id=f"{broker}:isin:{isin}",
            type=tx_type,
            executed_at=executed_at,
            quantity=qty,
            price_local=price_local,
            amount=total_eur,
            amount_currency=amount_ccy,
            fee=fee_total if fee_total != 0 else None,
            fx_rate=fx_rate,
            description=(f"Order {order_id}" if order_id else None),
        ))

    return out


# ═══════════════════════════════════════════════════════════════════════════
# account.csv adapter — non-trade cash events (DIVIDEND / FEE / INTEREST / etc.)
# ═══════════════════════════════════════════════════════════════════════════
#
# account.csv columns (verified against fixture + pnl.py):
#   0  Date                (DD-MM-YYYY)
#   1  Time                (HH:MM)
#   2  Value date
#   3  Product             (name; empty for deposit/withdrawal)
#   4  ISIN                (empty for cash-only rows)
#   5  Description         (Portuguese OR English — keyword-categorised)
#   6  FX rate             (empty unless cross-ccy)
#   7  Change currency
#   8  Change              (signed)
#   9  Balance currency
#   10 Balance             (running, broker-reported)
#   11 Order Id            (when set, this row mirrors a transactions.csv
#                           cash leg — skip to avoid double-counting)
_AC_COL_DATE         = 0
_AC_COL_TIME         = 1
_AC_COL_PRODUCT      = 3
_AC_COL_ISIN         = 4
_AC_COL_DESCRIPTION  = 5
_AC_COL_FX_RATE      = 6
_AC_COL_CHG_CCY      = 7
_AC_COL_CHANGE       = 8
_AC_COL_BAL_CCY      = 9
_AC_COL_BALANCE      = 10
_AC_COL_ORDER_ID     = 11


def _classify_description(desc: str) -> Optional[TransactionType]:
    """Return the canonical TransactionType for a Degiro account.csv row,
    or None if the row should be SKIPPED (internal transfers, trade
    duplicates — those belong to transactions.csv).

    Description matching is keyword-based and handles both Portuguese
    (Degiro's NL/EU exports often default to PT for international users)
    and English. Mirrors pnl.py's category logic so the two paths agree.
    """
    d = (desc or "").strip().lower()
    if not d:
        return TransactionType.OTHER

    # Internal cash sweeps — skip (already excluded in pnl.py's reconciliation).
    if "cash sweep" in d:
        return None
    # Trade-row duplicates of transactions.csv (Compra/Venda/Buy/Sell).
    # Caller can also filter on Order Id presence; we keep both belt + braces.
    if any(k in d for k in ("compra", "venda", "buy ", "sell ")):
        return None

    # Dividend variants — tax-on-dividend takes precedence over plain dividend
    has_div = "dividendo" in d or "dividend" in d
    has_tax = "imposto" in d or "tax" in d
    if has_div and has_tax:
        return TransactionType.TAX
    if has_div:
        return TransactionType.DIVIDEND

    if "interest" in d or "juro" in d:
        return TransactionType.INTEREST
    if "deposit" in d:
        return TransactionType.DEPOSIT
    if "withdrawal" in d or "levantamento" in d:
        return TransactionType.WITHDRAWAL
    if any(k in d for k in ("comiss", "fee", "custo", "conectividade")):
        return TransactionType.FEE
    if "divisa" in d or " fx " in f" {d} " or d.startswith("fx"):
        return TransactionType.FX_EXCHANGE
    return TransactionType.OTHER


def to_canonical_account_events(
    account_csv: Path,
    *,
    account_id: str,
    broker: str = "degiro",
) -> list[Transaction]:
    """Parse Degiro's `account.csv` into canonical non-trade Transactions.

    SKIPS:
      - rows with an Order Id (these are trade-cash duplicates of
        transactions.csv — covered by to_canonical_transactions)
      - cash sweep / internal transfers (`Degiro Cash Sweep Transfer`,
        `flatex euro bankaccount` rows) — not real external cash flows

    EMITS Transactions with:
      type            classified from description (DIVIDEND / TAX /
                      INTEREST / DEPOSIT / WITHDRAWAL / FEE / FX_EXCHANGE
                      / OTHER)
      instrument_id   "degiro:isin:{ISIN}" when ISIN present, else None
      amount          CSV Change column (signed)
      amount_currency CSV Change-currency column
      fx_rate         CSV FX column (None when empty)
      transaction_id  f"account-{row#}-{date}"  (no broker-stable ID
                      available for non-trade rows)"""
    account_csv = Path(account_csv)
    out: list[Transaction] = []

    with open(account_csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []

    for i, r in enumerate(rows[1:], start=2):
        if len(r) < 11 or not r[_AC_COL_DATE].strip():
            continue

        # Skip trade-row duplicates by Order Id presence
        order_id = (r[_AC_COL_ORDER_ID].strip()
                    if len(r) > _AC_COL_ORDER_ID else "")
        if order_id:
            continue

        d = _parse_degiro_date(r[_AC_COL_DATE])
        if d is None:
            continue
        executed_at = datetime.combine(d, _parse_degiro_time(r[_AC_COL_TIME]),
                                       tzinfo=timezone.utc)
        change_ccy = r[_AC_COL_CHG_CCY].strip()
        change_amt = _parse_degiro_decimal(r[_AC_COL_CHANGE])
        if change_amt is None or not change_ccy:
            continue

        desc = r[_AC_COL_DESCRIPTION].strip()
        product = r[_AC_COL_PRODUCT].strip()

        # Belt+braces: also catch internal transfers via the product field
        if product.lower() == "flatex euro bankaccount":
            continue

        tx_type = _classify_description(desc)
        if tx_type is None:                          # skip (sweep / trade dupe)
            continue

        isin = r[_AC_COL_ISIN].strip()
        instrument_id = f"{broker}:isin:{isin}" if isin else None
        fx_rate = _parse_degiro_decimal(r[_AC_COL_FX_RATE])

        out.append(Transaction(
            valid_at=executed_at, observed_at=datetime.now(timezone.utc),
            transaction_id=f"account-{i}-{d.isoformat()}",
            account_id=account_id,
            instrument_id=instrument_id,
            type=tx_type,
            executed_at=executed_at,
            amount=change_amt,
            amount_currency=change_ccy,
            fx_rate=fx_rate,
            description=desc or None,
        ))

    return out


def account_csv_cash_ledger(account_csv: Path) -> list[tuple[datetime, str, Decimal]]:
    """The broker CASH LEDGER from account.csv — the authoritative source for
    cash LEVELS. Returns `[(executed_at, currency, change)]` for EVERY row with
    a Change, excluding ONLY internal mirrors:
      - `Degiro Cash Sweep Transfer` descriptions (flatex bank ↔ Degiro cash
        double-entries — counting them double-books every deposit), and
      - `flatex euro bankaccount` product rows (older-era same mirror).

    Unlike `to_canonical_account_events`, this INCLUDES Order-Id rows (the
    trades' real EUR cash legs) and AutoFX legs — because for cash, the ledger
    itself is the truth: its cumulative per-currency sum reproduces the CSV's
    own stated running Balance to the cent (validated against a real export:
    final EUR 155.67 exact, USD/GBP net 0.00 ±0.01 rounding).

    WHY a separate path: the canonical Transaction stream deliberately carries
    trade consideration in LOCAL currency (transactions.csv — what positions /
    realised P&L need) and drops Order-Id account rows to avoid double-counting
    P&L — a topology that cannot also reconcile multi-currency cash (local-ccy
    trade legs with no counterleg). Positions fold over transactions; CASH sums
    the ledger. Both are pure, both reconcile, each against its own truth."""
    account_csv = Path(account_csv)
    out: list[tuple[datetime, str, Decimal]] = []
    with open(account_csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    for r in rows[1:]:
        if len(r) < 11 or not r[_AC_COL_DATE].strip():
            continue
        d = _parse_degiro_date(r[_AC_COL_DATE])
        if d is None:
            continue
        change_ccy = r[_AC_COL_CHG_CCY].strip()
        change_amt = _parse_degiro_decimal(r[_AC_COL_CHANGE])
        if change_amt is None or not change_ccy:
            continue
        desc = r[_AC_COL_DESCRIPTION].strip().lower()
        if "cash sweep" in desc:
            continue
        if r[_AC_COL_PRODUCT].strip().lower() == "flatex euro bankaccount":
            continue
        executed_at = datetime.combine(
            d, _parse_degiro_time(r[_AC_COL_TIME]), tzinfo=timezone.utc)
        out.append((executed_at, change_ccy, change_amt))
    return out
