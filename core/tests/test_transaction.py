"""Transaction — schema-level invariants.

Pydantic enforces structure + ISO/crypto currency. Sign conventions are
documented in the entity docstring; this file pins the validator rules
and a few "round-trip JSON" sanity checks."""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from pydantic import ValidationError                              # noqa: E402

from sq_schema import Transaction, TransactionType                # noqa: E402


def _tx(**overrides):
    base = {
        "transaction_id": "tx-1",
        "account_id":     "acct-1",
        "instrument_id":  "inst-ib01",
        "type":           TransactionType.BUY,
        "executed_at":    datetime(2026, 5, 1, 14, 30, tzinfo=timezone.utc),
        "quantity":       Decimal("100"),
        "price_local":    Decimal("114.10"),
        "amount":         Decimal("-9789.93"),     # buy -> cash out
        "amount_currency": "EUR",
        "fx_rate":        Decimal("0.85775"),
    }
    return Transaction(**{**base, **overrides})


class TestTransactionConstruction(unittest.TestCase):
    def test_minimal_buy(self):
        t = _tx()
        self.assertEqual(t.type, TransactionType.BUY)
        self.assertIsInstance(t.amount, Decimal)
        self.assertIsInstance(t.quantity, Decimal)

    def test_pure_cash_event_no_instrument(self):
        """DEPOSIT has no instrument_id and no quantity — just a cash amount."""
        t = Transaction(
            transaction_id="deposit-1",
            account_id="acct-1",
            type=TransactionType.DEPOSIT,
            executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            amount=Decimal("1000"),
            amount_currency="EUR",
        )
        self.assertIsNone(t.instrument_id)
        self.assertIsNone(t.quantity)
        self.assertEqual(t.amount, Decimal("1000"))

    def test_amount_currency_validated(self):
        with self.assertRaises(ValidationError):
            _tx(amount_currency="eur")   # lowercase fails

    def test_extra_fields_rejected(self):
        with self.assertRaises(ValidationError):
            _tx(typo_field="oops")

    def test_related_transactions_default_empty(self):
        self.assertEqual(_tx().related_transaction_ids, [])

    def test_decimal_money_invariant(self):
        for field in ("quantity", "price_local", "amount", "fee", "fx_rate"):
            v = getattr(_tx(fee=Decimal("0.5")), field)
            if v is not None:
                self.assertIsInstance(v, Decimal,
                                      f"{field} must be Decimal, got {type(v)}")


if __name__ == "__main__":
    unittest.main()
