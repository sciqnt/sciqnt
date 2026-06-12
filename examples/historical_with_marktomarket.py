#!/usr/bin/env python3
"""Full pipeline: parse CSV history → fold per instrument → overlay
current Yahoo prices → print true mark-to-market positions.

Demonstrates the closure of the "read" + "analyse" build-order steps:
the canonical event-sourcing flow now produces a Position with cost
basis + realised P/L (from history) AND value + unrealised P/L (from
current prices) — the same shape Degiro shows on its web view, derived
entirely from your own data and code.

Run::

    python3 examples/historical_with_marktomarket.py
"""
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))
sys.path.insert(0, str(ROOT / "modules" / "sq-yahoo"  / "src"))

from sq_compute import fold_position
from sq_degiro.canonical import to_canonical_transactions
from sq_market_data import overlay_prices
from sq_schema import AssetClass, Instrument
from sq_yahoo import YahooProvider

FIXTURES = ROOT / "modules" / "sq-degiro" / "tests" / "fixtures"


def main():
    # 1) Parse CSVs (this demo uses the synthetic fixture; replace with
    #    data/degiro/transactions.csv for your real data).
    trades = to_canonical_transactions(
        FIXTURES / "transactions.csv", account_id="degiro",
    )

    # 2) Fold per instrument
    by_inst = defaultdict(list)
    for t in trades:
        by_inst[t.instrument_id].append(t)
    positions = [
        fold_position(account_id="degiro", instrument_id=inst,
                      base_currency="EUR", transactions=txns)
        for inst, txns in by_inst.items()
    ]

    # 3) Build minimal Instrument objects for overlay ticker resolution.
    #    Fixture data uses synthetic ISINs/tickers; real data carries them.
    instruments = [
        Instrument(
            instrument_id="degiro:isin:TEST0000002",
            identifiers={"isin": "TEST0000002", "ticker": "AAPL",
                         "broker:degiro": "TEST0000002"},
            name="OpenCo (mapped to AAPL for demo)",
            asset_class=AssetClass.STOCK, listing_currency="USD",
        ),
    ]

    # 4) Overlay current prices via YahooProvider. Closed positions pass
    #    through unchanged; open ones get value + unrealised P/L populated.
    live = overlay_prices(
        positions, instruments,
        provider=YahooProvider(),
        base_currency="EUR",
    )

    print(f"\n  {'instrument':<32} {'qty':>6} {'price':>10} "
          f"{'value':>10} {'realized':>10} {'unrealized':>10}")
    print("  " + "─" * 80)
    for pos in live:
        inst_id = pos.instrument_id
        price = pos.last_price_local
        price_str = f"{float(price):,.2f}" if price else "—"
        print(f"  {inst_id:<32} {str(pos.quantity):>6} {price_str:>10} "
              f"{float(pos.value_base):>10,.2f} "
              f"{float(pos.realized_pl_base):>10,.2f} "
              f"{float(pos.unrealized_pl_base):>10,.2f}")


if __name__ == "__main__":
    main()
