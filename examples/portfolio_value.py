#!/usr/bin/env python3
"""Close the unrealized gap: value the one open Degiro position live, in EUR,
and split capital vs currency effect. Composes the market_price source unit.
Deterministic; prices fetched, never invented.
"""
import sys
import pathlib
from decimal import Decimal, ROUND_HALF_UP

# run-without-install: put each module bundle's src on the path
ROOT = pathlib.Path(__file__).resolve().parents[1]
for _m in ("sq-degiro", "sq-yahoo", "sq-openfigi"):
    sys.path.insert(0, str(ROOT / "modules" / _m / "src"))

from sq_yahoo import fetch_quote          # price source unit
from sq_openfigi import yahoo_candidates  # identifier resolver unit

C = lambda x: Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def price_by_isin(isin, prefer_suffix=None):
    """Composition: resolve ISIN -> candidates, return the first that actually prices.
    The resolve->validate loop lives here, in the app layer, so neither source unit
    depends on the other."""
    for cand in yahoo_candidates(isin, prefer_suffix=prefer_suffix):
        try:
            return cand, fetch_quote(cand)
        except Exception:
            continue
    raise RuntimeError(f"no priceable ticker for {isin}")

# --- the one open position, from the Degiro CSV proof ---
QTY = Decimal("100")
ISIN = "IE00BGSF1X88"                  # auto-resolved to a ticker, no hand lookup
VENUE_SUFFIX = ".L"                    # Degiro venue was LSE (XLON)
BUY_PRICE_USD = Decimal("114.10")
COST_EUR_ALLIN = Decimal("11159.34")   # Total EUR (incl. fees) from transactions.csv
COST_EUR_EXFEE = Decimal("11128.52")   # Value EUR (ex fees)
BUY_FX = Decimal("1.0253")             # USD per EUR at purchase
REALIZED_EUR = Decimal("1246.54")      # from degiro_pnl.py (11 closed positions)

ticker, q = price_by_isin(ISIN, prefer_suffix=VENUE_SUFFIX)       # ISIN -> ticker, validated
px = q["price"]                                                   # quote currency
fx = fetch_quote("EURUSD=X")["price"] if q["currency"] == "USD" else Decimal("1")

mv_usd = QTY * px
mv_eur = mv_usd / fx
unreal = mv_eur - COST_EUR_ALLIN

# indicative split (capital in USD vs FX translation)
usd_capital_gain = mv_usd - QTY * BUY_PRICE_USD
mv_eur_at_buyfx = mv_usd / BUY_FX
fx_effect = mv_eur - mv_eur_at_buyfx
capital_effect_eur = mv_eur_at_buyfx - COST_EUR_EXFEE

print("=" * 64)
print("sciqnt · open position valued live (EUR)")
print("=" * 64)
print(f"  {ISIN} -> {ticker}  qty {QTY}  @ {px} {q['currency']}   EUR/USD {fx}")
print(f"  market value : ${mv_usd:,.2f}  =  EUR {C(mv_eur):,}")
print(f"  cost (all-in): EUR {COST_EUR_ALLIN:,}")
print(f"  UNREALIZED   : EUR {C(unreal):,}")
print(f"     ~ capital (USD price): +${usd_capital_gain:,.2f}  (~EUR {C(capital_effect_eur):,})")
print(f"     ~ currency (USD->EUR): EUR {C(fx_effect):,}   <-- EUR strengthened vs USD")
print("-" * 64)
total = REALIZED_EUR + unreal
print(f"  realized P&L   : EUR {REALIZED_EUR:,}")
print(f"  unrealized P&L : EUR {C(unreal):,}")
print(f"  TOTAL P&L      : EUR {C(total):,}   (excl. dividends/interest)")
print(f"  + cash on hand : EUR 155.67")
print(f"  portfolio value: EUR {C(mv_eur + Decimal('155.67')):,}")
