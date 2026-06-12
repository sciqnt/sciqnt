#!/usr/bin/env python3
"""Run every sq_analytics function against the Degiro CSV fixtures.

Demonstrates the seven aggregates working together on canonical data:
  - portfolio_summary
  - currency_exposure
  - asset_class_exposure
  - dividend_history
  - fee_history
  - realized_pl_over_time
  - cash_flow_over_time

Run::

    python3 examples/analytics_demo.py
"""
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))

from sq_analytics import (
    asset_class_exposure, cash_flow_over_time, currency_exposure,
    dividend_history, fee_history, portfolio_summary,
    realized_pl_over_time,
)
from sq_compute import fold_position
from sq_degiro.canonical import (
    to_canonical_account_events, to_canonical_transactions,
)
from sq_schema import AssetClass, CashBalance, Instrument

FIXTURES = ROOT / "modules" / "sq-degiro" / "tests" / "fixtures"


def _row(label, value):
    print(f"  {label:<28} {value}")


def main():
    # ── Parse canonical Transactions + build synthetic Instruments/Cash ─
    trades = to_canonical_transactions(
        FIXTURES / "transactions.csv", account_id="degiro",
    )
    events = to_canonical_account_events(
        FIXTURES / "account.csv", account_id="degiro",
    )
    all_txns = trades + events

    # Fold a Position per instrument so portfolio-level analytics have inputs
    by_inst = defaultdict(list)
    for t in trades:
        by_inst[t.instrument_id].append(t)
    positions = [
        fold_position(
            account_id="degiro", instrument_id=inst,
            base_currency="EUR", transactions=inst_txns,
        )
        for inst, inst_txns in by_inst.items()
    ]

    # Synthetic Instruments — real CSV pipeline doesn't ship Instruments yet
    instruments = [
        Instrument(
            instrument_id="degiro:isin:TEST0000001",
            identifiers={"isin": "TEST0000001",
                         "ticker": "TESTCO",
                         "broker:degiro": "TEST0000001"},
            name="TestCo",
            asset_class=AssetClass.STOCK, listing_currency="EUR",
        ),
        Instrument(
            instrument_id="degiro:isin:TEST0000002",
            identifiers={"isin": "TEST0000002",
                         "ticker": "OPENCO",
                         "broker:degiro": "TEST0000002"},
            name="OpenCo",
            asset_class=AssetClass.STOCK, listing_currency="EUR",
        ),
    ]
    cash_balances = [
        CashBalance(account_id="degiro", currency="EUR",
                    amount=Decimal("120.00")),
        CashBalance(account_id="degiro", currency="USD",
                    amount=Decimal("5.00")),
    ]

    # ── portfolio_summary ───────────────────────────────────────────────
    print("\n── portfolio_summary ──")
    s = portfolio_summary(positions, base_currency="EUR")
    for k in ("instrument_count", "open_position_count",
              "closed_position_count", "total_cost_basis_base",
              "total_realized_pl_base"):
        _row(k, s[k])

    # ── currency_exposure ───────────────────────────────────────────────
    print("\n── currency_exposure ──")
    ce = currency_exposure(positions, cash_balances, instruments,
                           base_currency="EUR")
    for ccy in sorted(ce):
        parts = ce[ccy]
        _row(ccy, f"positions={parts['positions']}  "
                  f"cash={parts['cash']}  total={parts['total']}")

    # ── asset_class_exposure ────────────────────────────────────────────
    print("\n── asset_class_exposure ──")
    ace = asset_class_exposure(positions, instruments, base_currency="EUR")
    for ac in sorted(ace):
        parts = ace[ac]
        _row(ac, f"{parts['position_count']} positions  "
                 f"value={parts['value_base']}  "
                 f"realized={parts['realized_pl_base']}")

    # ── dividend_history ────────────────────────────────────────────────
    print("\n── dividend_history (by instrument) ──")
    div = dividend_history(all_txns, group_by="instrument")
    if div:
        for k, v in sorted(div.items()):
            _row(k, v)
    else:
        print("  (no dividends in fixture)")

    # ── fee_history ─────────────────────────────────────────────────────
    print("\n── fee_history (by year) ──")
    fees = fee_history(all_txns, group_by="year")
    if fees:
        for k, v in sorted(fees.items()):
            _row(k, v)
    else:
        print("  (no fees in fixture)")

    # ── realized_pl_over_time ───────────────────────────────────────────
    print("\n── realized_pl_over_time (by year) ──")
    rpl = realized_pl_over_time(all_txns, base_currency="EUR",
                                group_by="year")
    if rpl:
        for k, v in sorted(rpl.items()):
            _row(k, v)
    else:
        print("  (no closed lots)")

    # ── cash_flow_over_time ─────────────────────────────────────────────
    print("\n── cash_flow_over_time (EUR, by year) ──")
    cf = cash_flow_over_time(all_txns, group_by="year", currency="EUR")
    for year in sorted(cf):
        print(f"  {year}:")
        for ttype in sorted(cf[year]):
            _row(f"  {ttype}", cf[year][ttype])


if __name__ == "__main__":
    main()
