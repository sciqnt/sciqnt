"""The deterministic demo portfolio — sciqnt's public face.

Everything here is SYNTHETIC and SEEDED: fictional instruments, a fixed
anchor date, seeded price walks, a scripted contribution/trade/dividend
history. The same dates always produce the same figures, so screenshots,
docs, and the first-run experience are reproducible and contain nobody's
real finances (owner decision 2026-06-12: "those should be the public
figures"). Dates up to *today* extend the walks deterministically — past
values never change as time passes (the seeded sequence only grows).

EUR-only by design: no FX dependency, no network, fully offline — the
demo must render identically on a plane and in CI.
"""
import random
from datetime import date, datetime, time, timezone
from decimal import Decimal

from sq_schema import (
    Account, AssetClass, CashBalance, Instrument, PortfolioSnapshot,
    Transaction, TransactionType,
)
from sq_compute import fold_position

ACCOUNT_ID = "demo:sample"
BASE_CCY = "EUR"
ANCHOR = date(2023, 1, 2)
_Q8 = Decimal("0.00000001")
_2DP = Decimal("0.01")

# (instrument_id, ticker, name, asset_class, start_price, drift, vol)
INSTRUMENTS = [
    ("demo:swrd", "SWRD", "Sample World ETF", AssetClass.ETF,
     Decimal("75"), 0.00045, 0.008),
    ("demo:sqtc", "SQTC", "Sample Tech Co", AssetClass.STOCK,
     Decimal("120"), 0.00065, 0.018),
    ("demo:sbnd", "SBND", "Sample Bond ETF", AssetClass.ETF,
     Decimal("100"), 0.00006, 0.0015),
]

_walks: dict[str, list] = {}          # instrument_id -> [(date, Decimal)]


def _walk(inst_id: str, upto: date) -> list:
    """Seeded daily close walk from ANCHOR to `upto` (inclusive), cached
    and extended on demand. random.Random(inst_id) makes every run — on
    any machine, forever — produce the identical series."""
    spec = next(i for i in INSTRUMENTS if i[0] == inst_id)
    series = _walks.setdefault(inst_id, [])
    if not series:
        series.append((ANCHOR, spec[4]))
    rng = random.Random(inst_id)
    # Re-derive deterministically: consume the rng for the days already
    # generated, then extend. (Cheap: ~1 draw/day.)
    have = len(series)
    d, px = series[-1]
    steps = (upto - ANCHOR).days
    draws = [rng.gauss(spec[5], spec[6]) for _ in range(max(steps, 0))]
    for k in range(have - 1, steps):
        d = date.fromordinal(ANCHOR.toordinal() + k + 1)
        px = (px * (Decimal(1) + Decimal(str(round(draws[k], 6))))
              ).quantize(_Q8)
        series.append((d, px))
    return series


def price(inst_id: str, on: date) -> Decimal:
    """Close at-or-before `on` (weekends/holidays don't exist in demo-land)."""
    on = min(on, date.today())
    series = _walk(inst_id, on)
    idx = min((on - ANCHOR).days, len(series) - 1)
    return series[max(idx, 0)][1]


def _dt(d: date) -> datetime:
    return datetime.combine(d, time(10, 0), tzinfo=timezone.utc)


def _months(start: date, end: date, day: int):
    y, m = start.year, start.month
    while True:
        d = date(y, m, min(day, 28))
        if d > end:
            return
        if d >= start:
            yield d
        m += 1
        if m > 12:
            m, y = 1, y + 1


def transactions(upto: date | None = None) -> list[Transaction]:
    """The scripted, deterministic history: monthly €500 deposits, periodic
    buys across the three instruments, two partial SQTC sells (realised
    P/L), quarterly/semi-annual dividends, €2 trade fees. Sign conventions
    mirror sq-degiro's canonical adapter (BUY qty+/amount−, SELL qty−/
    amount+, income amount+)."""
    today = upto or date.today()
    out: list[Transaction] = []
    obs = _dt(ANCHOR)                       # fixed observed_at → determinism
    qty_held = {i[0]: Decimal(0) for i in INSTRUMENTS}
    n = 0

    def emit(d, ttype, *, inst=None, qty=None, px=None, amount, fee=None,
             desc=None):
        nonlocal n
        n += 1
        out.append(Transaction(
            valid_at=_dt(d), observed_at=obs,
            transaction_id=f"demo-{n:04d}", account_id=ACCOUNT_ID,
            instrument_id=inst, type=ttype, executed_at=_dt(d),
            quantity=qty, price_local=px, amount=amount,
            amount_currency=BASE_CCY, fee=fee, description=desc))

    def buy(d, inst_id, budget):
        px = price(inst_id, d)
        qty = Decimal(int(budget / px))
        if qty < 1:
            return
        emit(d, TransactionType.BUY, inst=inst_id, qty=qty, px=px,
             amount=-(qty * px).quantize(_2DP), fee=Decimal("2.00"),
             desc="demo buy")
        qty_held[inst_id] += qty

    def sell(d, inst_id, fraction):
        qty = Decimal(int(qty_held[inst_id] * Decimal(str(fraction))))
        if qty < 1:
            return
        px = price(inst_id, d)
        emit(d, TransactionType.SELL, inst=inst_id, qty=-qty, px=px,
             amount=(qty * px).quantize(_2DP), fee=Decimal("2.00"),
             desc="demo sell")
        qty_held[inst_id] -= qty

    events = []
    for d in _months(ANCHOR, today, 1):
        events.append((d, "deposit"))
    for d in _months(ANCHOR, today, 5):
        events.append((d, "buy-swrd"))
    for d in _months(ANCHOR, today, 10):
        if d.month in (2, 5, 8, 11):
            events.append((d, "buy-sqtc"))
        if d.month in (3, 9):
            events.append((d, "buy-sbnd"))
    for d in _months(ANCHOR, today, 20):
        if d.month in (3, 6, 9, 12):
            events.append((d, "div-swrd"))
        if d.month in (6, 12):
            events.append((d, "div-sbnd"))
    for d, kind in [(date(2024, 7, 15), "sell-sqtc-0.3"),
                    (date(2025, 11, 20), "sell-sqtc-0.4")]:
        if d <= today:
            events.append((d, kind))
    events.sort(key=lambda e: (e[0], e[1]))

    for d, kind in events:
        if kind == "deposit":
            emit(d, TransactionType.DEPOSIT, amount=Decimal("500.00"),
                 desc="demo monthly deposit")
        elif kind == "buy-swrd":
            buy(d, "demo:swrd", Decimal("300"))
        elif kind == "buy-sqtc":
            buy(d, "demo:sqtc", Decimal("400"))
        elif kind == "buy-sbnd":
            buy(d, "demo:sbnd", Decimal("600"))
        elif kind == "div-swrd" and qty_held["demo:swrd"] > 0:
            emit(d, TransactionType.DIVIDEND, inst="demo:swrd",
                 amount=(qty_held["demo:swrd"] * Decimal("0.45")
                         ).quantize(_2DP), desc="demo dividend")
        elif kind == "div-sbnd" and qty_held["demo:sbnd"] > 0:
            emit(d, TransactionType.DIVIDEND, inst="demo:sbnd",
                 amount=(qty_held["demo:sbnd"] * Decimal("0.90")
                         ).quantize(_2DP), desc="demo distribution")
        elif kind.startswith("sell-sqtc"):
            sell(d, "demo:sqtc", float(kind.rsplit("-", 1)[1]))
    return out


def build_snapshot(asof: datetime | None = None) -> PortfolioSnapshot:
    """Fold the scripted history into a conformance-clean snapshot, marked
    to the seeded walk's price at `asof` (default today). EUR-only → the
    unrealised P/L is all product-driven (fx component zero)."""
    asof_d = (asof.date() if asof else date.today())
    txns = transactions(upto=asof_d)
    obs = _dt(ANCHOR)

    instruments = [
        Instrument(valid_at=obs, observed_at=obs,
                   instrument_id=iid,
                   identifiers={"ticker": tick, "demo": iid},
                   name=name, asset_class=ac, listing_currency=BASE_CCY,
                   listing_venue="DEMO")
        for iid, tick, name, ac, *_ in INSTRUMENTS
    ]
    positions = []
    for iid, *_ in INSTRUMENTS:
        pos = fold_position(ACCOUNT_ID, iid, BASE_CCY,
                            [t for t in txns if t.instrument_id == iid
                             and t.type in (TransactionType.BUY,
                                            TransactionType.SELL)],
                            asof=asof or _dt(asof_d))
        if pos.is_open:
            px = price(iid, asof_d)
            value = (pos.quantity * px).quantize(_Q8)
            pos = pos.model_copy(update={
                "last_price_local": px.quantize(_Q8),
                "value_base": value,
                "unrealized_product_pl_base":
                    (value - pos.cost_basis_base).quantize(_Q8),
                "unrealized_currency_pl_base": Decimal("0E-8"),
            })
        positions.append(pos)

    cash = Decimal("0")
    for t in txns:
        cash += t.amount
        if t.fee:
            cash -= abs(t.fee)
    account = Account(valid_at=obs, observed_at=obs,
                      account_id=ACCOUNT_ID, broker="demo",
                      base_currency=BASE_CCY,
                      display_name="Sample Portfolio (demo)")
    return PortfolioSnapshot(
        valid_at=asof or _dt(asof_d), observed_at=asof or _dt(asof_d),
        account=account, instruments=instruments, positions=positions,
        cash_balances=[CashBalance(valid_at=obs, observed_at=obs,
                                   account_id=ACCOUNT_ID, currency=BASE_CCY,
                                   amount=cash.quantize(_2DP),
                                   amount_base=cash.quantize(_2DP))],
    )
