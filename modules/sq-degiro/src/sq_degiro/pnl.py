#!/usr/bin/env python3
"""sq-degiro CSV flavour: orchestrator over the canonical event-sourcing flow.

`compute(data_dir)` is now a thin layer over:
  - `sq_degiro.canonical.to_canonical_transactions()`  (trades from transactions.csv)
  - `sq_degiro.canonical.to_canonical_account_events()` (cash events from account.csv)
  - `sq_compute.fold_cash_balances()`  (per-currency cash totals)
  - `sq_compute.fold_cash_by_type()`   (per-TransactionType breakdown)

The output dict's shape is preserved exactly (so `report()` and the existing
test_pnl.py keep working). The migration is mechanically safe because steps
6 + 7 of Milestone 0 pinned per-instrument realized P/L AND per-currency
cash reconciliation to agree between the pre-canonical sums in this file
and the canonical adapters + folds. Now this file simply *uses* the canonical
path; pnl.py no longer carries its own version of the money math.

The small CSV-reading helpers that remain (`num`, `pdate`, `load`, and the
private `_csv_*` helpers) are for things the canonical layer doesn't carry:
broker-reported running balances, instrument names, internal-sweep tallies,
and raw row counts/date ranges. These are reconciliation-side metadata, not
ledger data.

Usage: python3 pnl.py [data_dir]   (default: <repo>/data/degiro)
Quirks, caveats & conformance results for this unit: see ../../FINDINGS.md
"""
import csv
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path

# Resolve canonical adapters + compute helpers
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_compute import fold_cash_balances, fold_cash_by_type        # noqa: E402

from .canonical import (                                              # noqa: E402
    to_canonical_account_events, to_canonical_transactions,
)

getcontext().prec = 28
D0 = Decimal("0")
TOL = Decimal("0.05")  # accumulated per-row cent rounding over 100s of rows


# ─────────────────────────────────────────────────────────────────────────
# Small CSV helpers — exported for backward compatibility (test imports
# `num` + `pdate`). Internal-only helpers prefixed with `_`.
# ─────────────────────────────────────────────────────────────────────────
def num(s):
    """Parse Degiro's European decimal format. None if empty/unparseable."""
    if s is None:
        return None
    s = s.strip().strip('"').replace("\xa0", " ").strip().replace(" ", "")
    if s == "":
        return None
    if "," in s and "." in s:           # European: dot=thousands, comma=decimal
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


def pdate(s):
    """Parse Degiro's DD-MM-YYYY date format."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        d, m, y = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def load(path):
    """Read a CSV file as a list of rows (utf-8-sig handles the BOM Degiro ships)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.reader(f))


# ─────────────────────────────────────────────────────────────────────────
# Helpers for reconciliation-side metadata not carried by canonical entities
# ─────────────────────────────────────────────────────────────────────────
def _csv_meta(path):
    """Return (row_count, (min_date, max_date)) for a Degiro CSV file."""
    rows = load(path)
    body = rows[1:] if rows else []
    rows_valid = [r for r in body if r and r[0].strip()]
    dates = [d for d in (pdate(r[0]) for r in rows_valid) if d]
    return len(rows_valid), ((min(dates), max(dates)) if dates else (None, None))


def _read_last_balances(account_csv):
    """Return {ccy: last_reported_balance}.

    The Degiro account.csv is newest-first; we keep the first non-empty balance
    seen per currency = the broker's view of the latest balance. Used for cash
    reconciliation (compare our `computed` against broker's `reported`).
    """
    rows = load(account_csv)
    last = {}
    for r in rows[1:]:
        if len(r) < 11:
            continue
        ccy = r[9].strip()
        bal = num(r[10])
        if ccy and bal is not None and ccy not in last:
            last[ccy] = bal
    return last


def _read_instrument_names(transactions_csv):
    """Return {isin: product_name} — names are display data, not money math,
    so they live outside the canonical Transaction (which carries no name)."""
    rows = load(transactions_csv)
    names = {}
    for r in rows[1:]:
        if len(r) < 4:
            continue
        isin = r[3].strip()
        name = r[2].strip()
        if isin:
            names[isin] = name
    return names


def _read_internal_sweep_total(account_csv):
    """Sum of EUR changes flagged as internal transfers — preserved for
    reporting (categories['internal_sweep']) since the canonical adapter
    correctly SKIPS these rows."""
    rows = load(account_csv)
    total = D0
    for r in rows[1:]:
        if len(r) < 11:
            continue
        desc = r[5].strip().lower()
        product = r[3].strip().lower()
        ccy = r[7].strip()
        chg = num(r[8])
        internal = ("cash sweep" in desc) or (product == "flatex euro bankaccount")
        if internal and ccy == "EUR" and chg is not None:
            total += chg
    return total


# ─────────────────────────────────────────────────────────────────────────
# The orchestrator — same dict shape as before; logic now lives elsewhere
# ─────────────────────────────────────────────────────────────────────────
def compute(data_dir):
    """Parse the two CSVs and return structured results. Pure of I/O side
    effects beyond reading the files; no printing."""
    data_dir = Path(data_dir)
    tx_csv = data_dir / "transactions.csv"
    ac_csv = data_dir / "account.csv"

    # ── canonical entities (the money math) ─────────────────────────────
    trades = to_canonical_transactions(tx_csv, account_id="degiro")
    events = to_canonical_account_events(ac_csv, account_id="degiro")
    all_txns = trades + events

    # ── per-instrument net qty + net cash ───────────────────────────────
    names = _read_instrument_names(tx_csv)
    by_isin = defaultdict(list)
    for t in trades:
        if t.instrument_id and t.instrument_id.startswith("degiro:isin:"):
            isin = t.instrument_id[len("degiro:isin:"):]
            by_isin[isin].append(t)

    realized = D0
    closed, open_pos, neg = [], [], []
    for isin in sorted(by_isin, key=lambda i: names.get(i, "")):
        txns_for = by_isin[isin]
        nm = names.get(isin, isin)
        net_qty  = sum((t.quantity or D0 for t in txns_for), D0)
        net_cash = sum((t.amount       for t in txns_for), D0)
        if abs(net_qty) < Decimal("0.0001"):
            realized += net_cash
            closed.append((nm, isin, net_cash))
        elif net_qty < 0:
            neg.append((nm, isin, net_qty, net_cash))
        else:
            open_pos.append((nm, isin, net_qty, net_cash))

    # Total trade-leg fees (from transactions.csv; canonical stores |fee|, so
    # we surface as negative — matches pnl.py's "debit" sign convention).
    fees_tx = -sum((t.fee or D0 for t in trades), D0)

    # ── cash categories (TransactionType-driven, + sweep tally on the side) ─
    by_type_eur = fold_cash_by_type(all_txns, currency="EUR")
    categories = {
        "deposits":       by_type_eur.get("DEPOSIT",     D0),
        "withdrawals":    by_type_eur.get("WITHDRAWAL",  D0),
        "trade_cash":     by_type_eur.get("BUY", D0) + by_type_eur.get("SELL", D0),
        "fx_conversions": by_type_eur.get("FX_EXCHANGE", D0),
        "dividends":      by_type_eur.get("DIVIDEND",    D0),
        "dividend_tax":   by_type_eur.get("TAX",         D0),
        "interest":       by_type_eur.get("INTEREST",    D0),
        "fees":           by_type_eur.get("FEE",         D0),
        "other":          by_type_eur.get("OTHER",       D0),
        "internal_sweep": _read_internal_sweep_total(ac_csv),
    }

    # ── per-currency reconciliation against broker-reported last balance ──
    canonical_by_ccy = fold_cash_balances(all_txns)
    last_balances    = _read_last_balances(ac_csv)
    reconciliation = {}
    ok = True
    for ccy in sorted(set(canonical_by_ccy) | set(last_balances)):
        reported = last_balances.get(ccy)
        if reported is None:
            continue
        computed = canonical_by_ccy.get(ccy, D0)
        diff = computed - reported
        passed = abs(diff) <= TOL
        ok = ok and passed
        reconciliation[ccy] = {
            "computed": computed, "reported": reported,
            "diff": diff, "ok": passed,
        }

    # ── meta: row counts + date ranges (raw CSV rows, not canonical events) ─
    tx_count, tx_dates = _csv_meta(tx_csv)
    ac_count, ac_dates = _csv_meta(ac_csv)

    return {
        "tx_count": tx_count, "ac_count": ac_count,
        "tx_dates": tx_dates, "ac_dates": ac_dates,
        "realized": realized, "closed": closed, "open": open_pos, "neg": neg,
        "categories": categories, "fees_tx": fees_tx,
        "reconciliation": reconciliation, "reconciliation_ok": ok,
    }


# ─────────────────────────────────────────────────────────────────────────
# Display layer — unchanged from the original; consumes the same dict shape
# ─────────────────────────────────────────────────────────────────────────
def report(res):
    print("=" * 70)
    print("sciqnt · Degiro proof — realized P&L + cash reconciliation")
    print("=" * 70)
    print(f"transactions: {res['tx_count']} rows | {res['tx_dates'][0]} -> {res['tx_dates'][1]}")
    print(f"account     : {res['ac_count']} rows | {res['ac_dates'][0]} -> {res['ac_dates'][1]}")

    print("\n--- REALIZED P&L (fully-closed positions, EUR, fees incl.) ---")
    for nm, isin, pnl in sorted(res["closed"], key=lambda x: x[2]):
        print(f"  {pnl:>12,.2f}  {nm[:46]:46} {isin}")
    print(f"  {'-'*12}")
    print(f"  {res['realized']:>12,.2f}  TOTAL realized trading P&L ({len(res['closed'])} closed)")

    if res["open"]:
        print("\n--- OPEN positions (still held — need price for unrealized) ---")
        for nm, isin, q, c in res["open"]:
            print(f"  qty {q:>10,.4f}  net EUR {c:>12,.2f}  {nm[:40]:40} {isin}")
    if res["neg"]:
        print("\n--- NEGATIVE net qty (sells exceed buys -> history incomplete) ---")
        for nm, isin, q, c in res["neg"]:
            print(f"  qty {q:>10,.4f}  net EUR {c:>12,.2f}  {nm[:40]:40} {isin}")

    print("\n--- CASH LEDGER categories (EUR rows) ---")
    cat = res["categories"]
    for k in ["deposits", "withdrawals", "trade_cash", "fx_conversions",
              "dividends", "dividend_tax", "interest", "fees", "internal_sweep", "other"]:
        if cat.get(k, D0) != 0:
            print(f"  {cat[k]:>12,.2f}  {k}")
    print(f"  fees embedded in trades (AutoFX + txn): {res['fees_tx']:,.2f} EUR")

    print("\n--- CASH RECONCILIATION (sum of changes vs Degiro's last balance) ---")
    for ccy, r in res["reconciliation"].items():
        flag = "OK (<=cent rounding)" if r["ok"] else "*** MISMATCH"
        print(f"  {ccy}: computed {r['computed']:>14,.2f} | degiro {r['reported']:>14,.2f} "
              f"| diff {r['diff']:>10,.2f}  {flag}")
    print("\n  => reconciliation", "PASSES — parser reads every row correctly, "
          "internal transfers netted, balances match to the cent"
          if res["reconciliation_ok"] else "FAILS (parsing/category gap to investigate)")


def analyze(data_dir):
    res = compute(data_dir)
    report(res)
    return res


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[4] / "data" / "degiro"
    analyze(d)
