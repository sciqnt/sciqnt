"""Degiro cash-ledger reconciliation — cash LEVELS come from account.csv itself.

The canonical Transaction stream carries trade consideration in LOCAL currency
(what positions/realised-P&L need) and skips Order-Id account rows — a topology
that cannot also reconcile multi-currency cash. account_csv_cash_ledger sums the
broker's OWN ledger (every Change row except internal sweep mirrors) and must
reproduce the stated running Balance: that is the conformance check this file
encodes, on a synthetic export with all the trap row types (flatex sweeps,
Order-Id trade legs, AutoFX leg pairs, fees, Portuguese descriptions).
"""
import sys
import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE.parent / "src"))

from sq_degiro.canonical import account_csv_cash_ledger          # noqa: E402
import sq_degiro                                                  # noqa: E402

# Chronology (oldest last, like a real export):
#  1. deposit €2000 (flatex Deposit mirror + sweep mirror INTO Degiro cash)
#  2. buy 10 X @ $100 → AutoFX: EUR −90 out, USD +1000 in; trade leg USD −1000
#     (Order-Id row — REAL cash leg, must count); fee €2 (Comissões)
#  3. dividend $5 in, AutoFX back: USD −5 / EUR +4.50
# Final stated: EUR 2000 − 90 − 2 + 4.50 = 1912.50; USD 0.00
_CSV = """Date,Time,Value date,Product,ISIN,Description,FX,Change,,Balance,,Order Id
03-01-2024,10:00,03-01-2024,,,Crédito de divisa,1.1111,EUR,"4,50",EUR,"1912,50",
03-01-2024,10:00,03-01-2024,,,Levantamento de divisa,,USD,"-5,00",USD,"0,00",
03-01-2024,09:00,03-01-2024,ACME,US000000000X,Dividendo,,USD,"5,00",USD,"5,00",
02-01-2024,15:00,02-01-2024,ACME,US000000000X,"Comissões de transação DEGIRO e/ou taxas de terceiros",,EUR,"-2,00",EUR,"1908,00",
02-01-2024,15:00,02-01-2024,ACME,US000000000X,"Compra 10 ACME@100,00 USD",,USD,"-1000,00",USD,"0,00",ord-1
02-01-2024,15:00,02-01-2024,,,Crédito de divisa,,USD,"1000,00",USD,"1000,00",
02-01-2024,15:00,02-01-2024,,,Levantamento de divisa,1.1111,EUR,"-90,00",EUR,"1910,00",
01-01-2024,12:01,01-01-2024,,,Degiro Cash Sweep Transfer,,EUR,"2000,00",EUR,"2000,00",
01-01-2024,12:00,01-01-2024,,,flatex Deposit,,EUR,"2000,00",EUR,"0,00",
"""


class TestCashLedger(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="sq-degiro-ledger-"))
        (self.dir / "account.csv").write_text(_CSV)
        # minimal transactions.csv so load_history works (one matching trade)
        (self.dir / "transactions.csv").write_text(
            "Date,Time,Product,ISIN,Reference exchange,Venue,Quantity,Price,,"
            "Local value,,Value EUR,Exchange rate,AutoFX Fee,"
            "Transaction and/or third party fees EUR,Total EUR,Order ID,\n"
            '02-01-2024,15:00,ACME,US000000000X,NSY,XNAS,10,"100,00",USD,'
            '"-1000,00",USD,"-900,00","1,1111",,"-2,00","-902,00",ord-1,\n')

    def test_ledger_matches_stated_final_balances(self):
        """Sum of included Change rows == the broker's stated running Balance:
        sweeps and flatex mirrors excluded; Order-Id trade legs and AutoFX leg
        pairs INCLUDED. Cent-exact."""
        entries = account_csv_cash_ledger(self.dir / "account.csv")
        tot: dict = {}
        for _ts, ccy, amt in entries:
            tot[ccy] = tot.get(ccy, Decimal("0")) + amt
        self.assertEqual(tot["EUR"], Decimal("1912.50"))
        self.assertEqual(tot["USD"], Decimal("0.00"))

    def test_sweep_and_mirror_rows_excluded(self):
        entries = account_csv_cash_ledger(self.dir / "account.csv")
        # 9 data rows − 1 sweep = 8 ledger entries (flatex Deposit row stays:
        # its own Balance shows 0 — it's the OTHER ledger — but Degiro nets it
        # against the sweep; we exclude the SWEEP, keeping deposits visible)
        self.assertEqual(len(entries), 8)

    def test_snapshot_cash_uses_ledger(self):
        """The historical snapshot's cash_balances must be the ledger numbers,
        not the canonical-txn fold (which would carry local-ccy trade legs)."""
        asof = datetime(2024, 1, 5, tzinfo=timezone.utc)
        snap_fn = sq_degiro.snapshot
        with mock.patch.object(sq_degiro, "_resolve_history_dir",
                                        return_value=self.dir):
            snap = snap_fn(asof)
        cash = {c.currency: c.amount for c in snap.cash_balances}
        self.assertEqual(cash.get("EUR"), Decimal("1912.50"))
        self.assertNotIn("USD", cash)                  # nets to 0 → omitted

    def test_pit_mid_history(self):
        """PIT correctness: cash at a date between events reflects only rows ≤
        that date (after the buy, before the dividend)."""
        asof = datetime(2024, 1, 2, 23, 59, tzinfo=timezone.utc)
        with mock.patch.object(sq_degiro, "_resolve_history_dir",
                                        return_value=self.dir):
            snap = sq_degiro.snapshot(asof)
        cash = {c.currency: c.amount for c in snap.cash_balances}
        self.assertEqual(cash.get("EUR"), Decimal("1908.00"))


if __name__ == "__main__":
    unittest.main()
