"""sq_platform._cache — round-trip + TTL + corruption-tolerance."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_platform import _cache                                            # noqa: E402
from sq_schema import AssetClass, Instrument                              # noqa: E402


def _instrument(iid="degiro:isin:US0378331005"):
    return Instrument(
        instrument_id=iid,
        identifiers={"isin": "US0378331005", "ticker": "AAPL",
                     "broker:degiro": "12345"},
        name="Apple Inc",
        asset_class=AssetClass.STOCK,
        listing_currency="USD",
        listing_venue="NASDAQ",
    )


class TestMetadataCacheRoundtrip(unittest.TestCase):
    def setUp(self):
        # Isolate the cache dir to a tempdir so we never touch the user's
        # real ~/.cache during tests
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_cache_dir = _cache.CACHE_DIR
        _cache.CACHE_DIR = Path(self.tmp.name)

    def tearDown(self):
        _cache.CACHE_DIR = self._orig_cache_dir
        self.tmp.cleanup()

    def test_miss_when_no_cache(self):
        self.assertIsNone(_cache.load_instrument_metadata("nonexistent"))
        self.assertIsNone(_cache.cache_age_seconds("nonexistent"))

    def test_roundtrip(self):
        insts = [_instrument(), _instrument("degiro:isin:DE000A0S9GB0")]
        _cache.save_instrument_metadata("degiro", insts)
        loaded = _cache.load_instrument_metadata("degiro")
        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded), 2)
        # Identity preserved across the JSON round-trip
        self.assertEqual(loaded[0].instrument_id, insts[0].instrument_id)
        self.assertEqual(loaded[0].name,          insts[0].name)
        self.assertEqual(loaded[0].asset_class,   insts[0].asset_class)
        self.assertEqual(loaded[0].listing_currency, insts[0].listing_currency)
        self.assertEqual(loaded[0].identifiers["ticker"], "AAPL")

    def test_stale_cache_returns_none(self):
        insts = [_instrument()]
        _cache.save_instrument_metadata("degiro", insts)
        # Backdate the file beyond TTL
        p = _cache._meta_cache_path("degiro")
        old = time.time() - (_cache.META_CACHE_TTL_SECONDS + 60)
        os.utime(p, (old, old))
        self.assertIsNone(
            _cache.load_instrument_metadata("degiro"),
            "stale-by-TTL cache must read as miss; otherwise "
            "users see frozen metadata long after the source has changed",
        )

    def test_corrupt_cache_returns_none(self):
        p = _cache._meta_cache_path("degiro")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{ not valid json")
        # Corrupt cache is treated as miss — never raises to the caller
        self.assertIsNone(_cache.load_instrument_metadata("degiro"))

    def test_save_failure_is_silent(self):
        # Save under a path we can't create (root-owned). Should NOT raise.
        _cache.CACHE_DIR = Path("/proc/this/cannot/be/written")
        _cache.save_instrument_metadata("degiro", [_instrument()])
        # Just making sure no exception escaped.

    def test_cache_age_seconds_increasing(self):
        _cache.save_instrument_metadata("degiro", [_instrument()])
        age1 = _cache.cache_age_seconds("degiro")
        self.assertIsNotNone(age1)
        self.assertGreaterEqual(age1, 0)
        time.sleep(0.05)
        age2 = _cache.cache_age_seconds("degiro")
        self.assertGreater(age2, age1)


class TestSnapshotCacheRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_cache_dir = _cache.CACHE_DIR
        _cache.CACHE_DIR = Path(self.tmp.name)

    def tearDown(self):
        _cache.CACHE_DIR = self._orig_cache_dir
        self.tmp.cleanup()

    def _snapshot(self):
        from sq_schema import (Account, AssetClass, CashBalance, Instrument,
                               PortfolioSnapshot, Position)
        inst = Instrument(
            instrument_id="degiro:isin:US0378331005",
            identifiers={"isin": "US0378331005", "ticker": "AAPL",
                         "broker:degiro": "12345"},
            name="Apple Inc", asset_class=AssetClass.STOCK,
            listing_currency="USD",
        )
        acct = Account(account_id="10000001", broker="degiro",
                       base_currency="EUR")
        pos = Position(
            account_id="10000001", instrument_id=inst.instrument_id,
            quantity=Decimal("4"), value_base=Decimal("1200"),
            cost_basis_base=Decimal("1000"),
            last_price_local=Decimal("300"),
            realized_product_pl_base=Decimal("0"),
            realized_currency_pl_base=Decimal("0"),
            unrealized_product_pl_base=Decimal("200"),
            unrealized_currency_pl_base=Decimal("0"),
        )
        cash = [CashBalance(account_id="10000001", currency="EUR",
                            amount=Decimal("155.67"))]
        return PortfolioSnapshot(account=acct, instruments=[inst],
                                 positions=[pos], cash_balances=cash)

    def test_roundtrip_strips_computed_fields(self):
        """Position has @computed_field properties that Pydantic includes
        in model_dump_json but rejects on model_validate. The cache must
        strip them on load — otherwise the JSON written by the dispatcher
        can never be read back."""
        snap = self._snapshot()
        _cache.save_snapshot("degiro", snap)
        loaded = _cache.load_snapshot("degiro")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.account.account_id, "10000001")
        self.assertEqual(len(loaded.positions), 1)
        # And derived properties still compute correctly after reload
        self.assertEqual(loaded.positions[0].unrealized_pl_base, Decimal("200"))

    def test_stale_snapshot_returns_none(self):
        _cache.save_snapshot("degiro", self._snapshot())
        p = _cache._snapshot_cache_path("degiro")
        old = time.time() - (_cache.SNAPSHOT_CACHE_TTL_SECONDS + 5)
        os.utime(p, (old, old))
        self.assertIsNone(_cache.load_snapshot("degiro"),
                          "snapshot cache must respect TTL — else the "
                          "user sees yesterday's value as 'live'")

    def test_invalidate_drops_the_cache(self):
        _cache.save_snapshot("degiro", self._snapshot())
        self.assertIsNotNone(_cache.load_snapshot("degiro"))
        _cache.invalidate_snapshot("degiro")
        self.assertIsNone(_cache.load_snapshot("degiro"))

    def test_invalidate_missing_is_noop(self):
        # Must NOT raise when there's nothing to invalidate
        _cache.invalidate_snapshot("nonexistent")

    def test_corrupt_snapshot_returns_none(self):
        p = _cache._snapshot_cache_path("degiro")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json")
        self.assertIsNone(_cache.load_snapshot("degiro"))


if __name__ == "__main__":
    unittest.main()
