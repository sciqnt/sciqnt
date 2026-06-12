#!/usr/bin/env python3
"""Investigation: does adding currency-converted dividends + interest close the
gap between our Total P/L and Degiro's displayed Total P/L (EUR 624.08)?"""
import csv
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules" / "sq-yahoo" / "src"))
from sq_yahoo import fetch_quote

DEGIRO_TOTAL_PL = Decimal("624.08")
REALIZED = Decimal("1246.54")
UNREALIZED = Decimal("-810.84")


def num(s):
    s = s.strip().strip('"').replace("\xa0", " ").strip().replace(" ", "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".") if ("," in s and "." in s) else s.replace(",", ".")
    try:
        return Decimal(s)
    except Exception:
        return None


rows = list(csv.reader(open(Path(__file__).parent.parent / "data/degiro/account.csv",
                            encoding="utf-8-sig")))[1:]
gross, tax = {}, {}
interest = Decimal(0)
for r in rows:
    if len(r) < 11:
        continue
    d = r[5].strip().lower()
    ccy = r[7].strip()
    chg = num(r[8])
    if chg is None or not ccy:
        continue
    if "dividendo" in d or "dividend" in d:
        bucket = tax if ("imposto" in d or "tax" in d) else gross
        bucket[ccy] = bucket.get(ccy, Decimal(0)) + chg
    elif ("interest" in d or "juro" in d) and ccy == "EUR":
        interest += chg

eurusd = fetch_quote("EURUSD=X")["price"]   # USD per EUR
gbpeur = fetch_quote("GBPEUR=X")["price"]   # EUR per GBP


def to_eur(amt, ccy):
    if ccy == "EUR":
        return amt
    if ccy == "USD":
        return amt / eurusd
    if ccy == "GBP":
        return amt * gbpeur
    return Decimal(0)


print("gross dividends:", {k: str(v) for k, v in gross.items()})
print("withholding tax:", {k: str(v) for k, v in tax.items()})
net_eur = Decimal(0)
for ccy in sorted(set(list(gross) + list(tax))):
    n = gross.get(ccy, Decimal(0)) + tax.get(ccy, Decimal(0))
    e = to_eur(n, ccy)
    net_eur += e
    print(f"  {ccy}: net {n}  -> EUR {e:.2f}")
total = REALIZED + UNREALIZED + net_eur + interest
diff = DEGIRO_TOTAL_PL - total
print(f"\nnet dividends (EUR, after WHT): {net_eur:.2f}")
print(f"interest (EUR): {interest:.2f}")
print(f"realized {REALIZED} + unrealized {UNREALIZED} + div {net_eur:.2f} "
      f"+ int {interest:.2f} = {total:.2f}")
print(f"Degiro Total P/L = {DEGIRO_TOTAL_PL}  |  diff = {diff:.2f}")
