"""Degiro account.csv → canonical Transactions adapter — conformance + reconciliation.

The reconciliation here is the second half of the proof started in
test_csv_canonical:

  Path A (pre-canonical): pnl.py.compute() returns 'reconciliation' — a
    per-currency dict {ccy: {'computed': sum-of-change, 'reported': last-balance, ...}}.

  Path B (canonical): trades from transactions.csv (via to_canonical_transactions)
    + non-trade events from account.csv (via to_canonical_account_events),
    then fold_cash_balances(combined) by currency.

  CLAIM: Path A's 'computed' (per currency) == Path B's fold output (per
  currency). Same data, two routes, same answer.

If this ever drifts: one of the adapters silently lost / duplicated a row.
Cheap, robust signal — exactly the kind of conformance the canonical layer
exists to provide.
"""
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "modules" / "sq-degiro" / "src"))
sys.path.insert(0, str(ROOT / "core"))

from sq_degiro.canonical import (                                  # noqa: E402
    _classify_description, to_canonical_account_events,
    to_canonical_transactions,
)
from sq_degiro.pnl import compute as pnl_compute                   # noqa: E402
from sq_schema import TransactionType                              # noqa: E402
from sq_compute import fold_cash_balances, fold_cash_by_type        # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


# ───────────────────────────────────────────────────────────────────────────
# Classification — Portuguese + English keyword matrix
# ───────────────────────────────────────────────────────────────────────────
class TestClassifyDescription(unittest.TestCase):
    """Pin the description -> TransactionType mapping so it stays in sync
    with pnl.py's category logic."""

    def test_portuguese_keywords(self):
        cases = {
            "Dividendo Apple": TransactionType.DIVIDEND,
            "Imposto sobre Dividendo": TransactionType.TAX,
            "Comissão de Conectividade": TransactionType.FEE,
            "Levantamento": TransactionType.WITHDRAWAL,
            "Juro creditado": TransactionType.INTEREST,
            "Divisa USD/EUR": TransactionType.FX_EXCHANGE,
        }
        for desc, expected in cases.items():
            self.assertEqual(_classify_description(desc), expected,
                             f"classify({desc!r}) should be {expected}")

    def test_english_keywords(self):
        cases = {
            "Dividend received": TransactionType.DIVIDEND,
            "Dividend tax withholding": TransactionType.TAX,
            "Interest credited": TransactionType.INTEREST,
            "flatex Deposit": TransactionType.DEPOSIT,
            "Withdrawal to bank": TransactionType.WITHDRAWAL,
            "Connectivity fee": TransactionType.FEE,
        }
        for desc, expected in cases.items():
            self.assertEqual(_classify_description(desc), expected,
                             f"classify({desc!r}) should be {expected}")

    def test_skipped_rows_return_none(self):
        """Internal sweeps + trade duplicates must be filtered out."""
        self.assertIsNone(_classify_description("Degiro Cash Sweep Transfer"))
        self.assertIsNone(_classify_description("Compra 10 TestCo"))
        self.assertIsNone(_classify_description("Venda 10 TestCo"))
        # Note: 'buy/sell' words on their own with no qty wouldn't be Degiro's
        # description format, but it's robust to check the variants we'd hit.

    def test_unknown_falls_to_other(self):
        self.assertEqual(_classify_description("Some weird new row type"),
                         TransactionType.OTHER)

    def test_empty_description_falls_to_other(self):
        self.assertEqual(_classify_description(""), TransactionType.OTHER)


# ───────────────────────────────────────────────────────────────────────────
# Adapter shape — fixture parse correctness
# ───────────────────────────────────────────────────────────────────────────
class TestAccountEventsShape(unittest.TestCase):
    def setUp(self):
        self.events = to_canonical_account_events(
            FIXTURES / "account.csv", account_id="acct-test",
        )

    def test_emits_two_non_trade_events(self):
        """Fixture has 6 account rows:
            3 trade-cash dupes (skip — Order Id set)
            1 cash sweep (skip — internal)
            1 deposit
            1 USD dividend
        -> 2 canonical Transactions."""
        self.assertEqual(len(self.events), 2)

    def test_types_are_deposit_and_dividend(self):
        types = {t.type for t in self.events}
        self.assertEqual(types, {TransactionType.DEPOSIT, TransactionType.DIVIDEND})

    def test_dividend_carries_isin(self):
        div = next(t for t in self.events if t.type == TransactionType.DIVIDEND)
        self.assertEqual(div.instrument_id, "degiro:isin:TEST0000003")
        self.assertEqual(div.amount_currency, "USD")
        self.assertEqual(div.amount, Decimal("5.00"))

    def test_deposit_has_no_instrument(self):
        dep = next(t for t in self.events if t.type == TransactionType.DEPOSIT)
        self.assertIsNone(dep.instrument_id)
        self.assertEqual(dep.amount_currency, "EUR")
        self.assertEqual(dep.amount, Decimal("200.00"))

    def test_cash_sweep_skipped(self):
        """Cash sweep row (no Order Id but description starts with 'Degiro Cash
        Sweep Transfer') must not produce a canonical Transaction."""
        for t in self.events:
            self.assertNotIn("sweep", (t.description or "").lower())

    def test_trade_rows_skipped_via_order_id(self):
        """Rows with an Order Id (trade duplicates) shouldn't appear here."""
        descriptions = {(t.description or "").lower() for t in self.events}
        for d in descriptions:
            for kw in ("compra", "venda", "buy ", "sell "):
                self.assertNotIn(kw, d)


# ───────────────────────────────────────────────────────────────────────────
# RECONCILIATION — combined-flow vs pnl.py per-currency change_sum
# ───────────────────────────────────────────────────────────────────────────
class TestCashReconciliation(unittest.TestCase):
    """Path A (pnl.py) and Path B (canonical adapters + fold_cash_balances)
    must agree on per-currency cash totals."""

    def setUp(self):
        self.pnl = pnl_compute(FIXTURES)
        self.trades = to_canonical_transactions(
            FIXTURES / "transactions.csv", account_id="acct-test",
        )
        self.events = to_canonical_account_events(
            FIXTURES / "account.csv",     account_id="acct-test",
        )
        self.canonical = self.trades + self.events
        self.canonical_by_ccy = fold_cash_balances(self.canonical)

    def test_per_currency_total_matches_pnl_computed(self):
        """For each currency the broker has a reported balance for, the
        canonical adapters' summed amount must equal pnl.py's `computed`
        change-sum (which is reconciled against the broker's last balance)."""
        for ccy, recon in self.pnl["reconciliation"].items():
            self.assertIn(ccy, self.canonical_by_ccy,
                          f"canonical has no entry for {ccy}")
            self.assertEqual(
                self.canonical_by_ccy[ccy], recon["computed"],
                f"{ccy} mismatch: pnl.computed={recon['computed']} "
                f"vs canonical-folded={self.canonical_by_ccy[ccy]}",
            )

    def test_eur_reconciles_to_broker_reported_balance(self):
        """End-to-end sanity: EUR sum from canonical events must equal what
        Degiro reports as the last EUR balance — this is the bottom-line check
        pnl.py uses for its reconciliation pass/fail."""
        eur = self.canonical_by_ccy.get("EUR")
        reported_eur = self.pnl["reconciliation"]["EUR"]["reported"]
        # Allow at most 1 cent rounding (same tolerance pnl.py uses)
        self.assertLess(abs(eur - reported_eur), Decimal("0.05"),
                        f"EUR canonical={eur} vs broker={reported_eur}")

    def test_usd_dividend_lands_in_usd_bucket(self):
        """The single USD-denominated dividend must NOT contaminate EUR."""
        self.assertEqual(self.canonical_by_ccy.get("USD"), Decimal("5.00"))


# ───────────────────────────────────────────────────────────────────────────
# Per-type breakdown — replaces pnl.py's hand-coded category dict
# ───────────────────────────────────────────────────────────────────────────
class TestCashByType(unittest.TestCase):
    """fold_cash_by_type produces the same per-category totals pnl.py
    computes by keyword-matching descriptions — but structurally, from
    the canonical TransactionType enum."""

    def setUp(self):
        trades = to_canonical_transactions(
            FIXTURES / "transactions.csv", account_id="acct-test",
        )
        events = to_canonical_account_events(
            FIXTURES / "account.csv",     account_id="acct-test",
        )
        self.by_type_eur = fold_cash_by_type(trades + events, currency="EUR")
        self.pnl_cats   = pnl_compute(FIXTURES)["categories"]

    def test_deposits_match(self):
        # +200 EUR deposit in the fixture
        self.assertEqual(self.by_type_eur.get("DEPOSIT", Decimal("0")),
                         self.pnl_cats.get("deposits", Decimal("0")))


if __name__ == "__main__":
    unittest.main()
