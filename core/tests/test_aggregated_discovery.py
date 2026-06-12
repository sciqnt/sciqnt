"""Discovery + conformance gate for the aggregated landing view.

Pins two robustness properties:
  1. The broker registry is capability-based — every bundle whose Python
     package exposes a callable `snapshot` attribute is auto-registered;
     bundles without one (config, fx providers, openfigi, yahoo) are
     not. Adding a new connector must not require core edits.
  2. The conformance gate runs BEFORE aggregation — a snapshot with
     invariant violations is downgraded to a failed broker entry with
     the violations attached, never silently folded into totals.
"""
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))   # core/
for _bundle in (ROOT / "modules").glob("sq-*"):
    _src = _bundle / "src"
    if _src.is_dir():
        sys.path.insert(0, str(_src))

from sq_platform.aggregated import (                                       # noqa: E402
    _broker_label_split, _collect_snapshots, _discover_brokers,
    _enrich_historical_metadata, _make_broker_call,
)
from sq_aggregator import BrokerSnapshot                                    # noqa: E402
from sq_schema import (                                                    # noqa: E402
    Account, AssetClass, CashBalance, Instrument, PortfolioSnapshot, Position,
)


def _ts():
    return datetime(2025, 1, 1, tzinfo=timezone.utc)


def _good_snapshot(broker="degiro"):
    inst = Instrument(
        instrument_id=f"{broker}:isin:GOOD0001",
        identifiers={"ticker": "GOOD", "isin": "GOOD0001",
                     f"broker:{broker}": "GOOD0001"},
        name="Good Corp", asset_class=AssetClass.STOCK,
        listing_currency="EUR",
    )
    acct = Account(account_id=f"{broker}-A1", broker=broker, base_currency="EUR")
    pos = Position(
        account_id=f"{broker}-A1", instrument_id=inst.instrument_id,
        quantity=Decimal("10"), value_base=Decimal("1000"),
        last_price_local=Decimal("100"),
        cost_basis_base=Decimal("900"),
        unrealized_product_pl_base=Decimal("0"),
        unrealized_currency_pl_base=Decimal("0"),
        realized_product_pl_base=Decimal("0"),
        realized_currency_pl_base=Decimal("0"),
    )
    return PortfolioSnapshot(
        account=acct, instruments=[inst], positions=[pos], cash_balances=[],
    )


def _bad_snapshot_duplicate_positions():
    """A snapshot whose conformance check fires: two Positions for the
    same (account_id, instrument_id) — banned by the canonical schema's
    cost-basis-non-negative invariant cousin. The model_validator on
    PortfolioSnapshot doesn't catch this — conformance does."""
    inst = Instrument(
        instrument_id="degiro:isin:DUP",
        identifiers={"ticker": "DUP", "isin": "DUPI0001",
                     "broker:degiro": "DUP"},
        name="Dup Corp", asset_class=AssetClass.STOCK, listing_currency="EUR",
    )
    acct = Account(account_id="degiro-A1", broker="degiro", base_currency="EUR")
    # Two Positions on the same (account, instrument) — conformance only
    p1 = Position(
        account_id="degiro-A1", instrument_id=inst.instrument_id,
        quantity=Decimal("5"), value_base=Decimal("500"),
        cost_basis_base=Decimal("400"),
    )
    p2 = Position(
        account_id="degiro-A1", instrument_id=inst.instrument_id,
        quantity=Decimal("5"), value_base=Decimal("500"),
        cost_basis_base=Decimal("400"),
    )
    return PortfolioSnapshot(
        account=acct, instruments=[inst], positions=[p1, p2], cash_balances=[],
    )


class TestCapabilityBasedDiscovery(unittest.TestCase):
    def test_available_connectors_are_the_snapshot_bundles(self):
        # _available_connectors is capability-based (exposes snapshot()),
        # INDEPENDENT of whether an account is connected — so it's stable
        # across machines/credential state, unlike _discover_brokers
        # (which now means CONNECTED accounts).
        from sq_platform.aggregated import _available_connectors
        names = _available_connectors(ROOT)
        for broker in ("degiro", "kalshi", "polymarket", "robinhood"):
            self.assertIn(broker, names,
                          f"{broker!r} exposes snapshot() — must be an available connector")
        for not_a_broker in ("config", "fx-ecb", "openfigi", "yahoo"):
            self.assertNotIn(not_a_broker, names,
                             f"{not_a_broker!r} has no snapshot() — not a broker connector")

    def test_discover_brokers_returns_callables(self):
        # Whatever IS connected in this environment must yield a callable.
        for name, snap_fn in _discover_brokers(ROOT):
            self.assertTrue(callable(snap_fn),
                            f"discovered {name} but its snapshot is not callable")

    def test_unconnected_broker_not_discovered(self):
        # A broker whose accounts() is empty must NOT appear in
        # _discover_brokers (so it's never fetched / never errors). Pin it
        # with a fake module so the test is credential-independent.
        from unittest import mock
        import tempfile
        class _Unconnected:
            def accounts(self):
                return []                     # nothing connected
            def snapshot(self, asof=None, *, account=None):
                raise AssertionError("must not be fetched when unconnected")
        tmp = tempfile.TemporaryDirectory()
        try:
            (Path(tmp.name) / "modules" / "sq-degiro").mkdir(parents=True)
            with mock.patch("sq_platform.aggregated.importlib.import_module",
                            return_value=_Unconnected()):
                out = _discover_brokers(Path(tmp.name))
            self.assertEqual(out, [])
        finally:
            tmp.cleanup()


class TestConformanceGate(unittest.TestCase):
    def setUp(self):
        # Isolate _cache.CACHE_DIR to a tempdir so the conformance tests
        # don't leave a write-through snapshot in ~/.cache/sciqnt/ that
        # then poisons a real `sciqnt` run later.
        import tempfile
        from sq_platform import _cache
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_cache_dir = _cache.CACHE_DIR
        _cache.CACHE_DIR = type(_cache.CACHE_DIR)(self._tmp.name)

    def tearDown(self):
        from sq_platform import _cache
        _cache.CACHE_DIR = self._orig_cache_dir
        self._tmp.cleanup()

    def test_clean_snapshot_passes_through(self):
        with mock.patch("sq_platform.aggregated._discover_brokers",
                        return_value=[("degiro", _good_snapshot)]):
            # use_snapshot_cache=False so any leftover cache file from a
            # real `sciqnt` run doesn't short-circuit our mocked broker
            out = _collect_snapshots(ROOT, use_snapshot_cache=False)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].ok)
        self.assertIsNone(out[0].error)

    def test_conformance_violation_is_downgraded_not_folded(self):
        with mock.patch("sq_platform.aggregated._discover_brokers",
                        return_value=[("degiro",
                                       _bad_snapshot_duplicate_positions)]):
            out = _collect_snapshots(ROOT, use_snapshot_cache=False)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].ok,
                         "a snapshot with conformance violations must be "
                         "downgraded to ok=False, never folded into totals")
        self.assertIn("conformance", (out[0].error or "").lower())
        # The specific violation code should appear in the error so the
        # user sees what's actually wrong, not just "conformance failed"
        self.assertIn("duplicate", (out[0].error or "").lower())

    def test_fetch_exception_becomes_failed_entry(self):
        def boom():
            raise RuntimeError("auth failed: invalid TOTP")
        with mock.patch("sq_platform.aggregated._discover_brokers",
                        return_value=[("degiro", boom)]):
            out = _collect_snapshots(ROOT, use_snapshot_cache=False)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0].ok)
        self.assertIn("auth failed", out[0].error or "")

    def test_other_brokers_survive_one_brokers_failure(self):
        """A failing broker must NOT take down the others. Regression for
        the SystemExit bug: _credentials used to sys.exit (a BaseException)
        which slipped past `except Exception` and killed the whole view —
        so a credential-less Robinhood blanked the working Degiro. Brokers
        now raise RuntimeError; one failure downgrades only itself."""
        good_snap = _good_snapshot
        def boom():
            raise RuntimeError("CredentialsMissing: no creds")
        with mock.patch("sq_platform.aggregated._discover_brokers",
                        return_value=[("degiro", good_snap), ("robinhood", boom)]):
            out = _collect_snapshots(ROOT, use_snapshot_cache=False)
        self.assertEqual(len(out), 2)
        by_broker = {b.broker: b for b in out}
        self.assertTrue(by_broker["degiro"].ok)         # survived
        self.assertFalse(by_broker["robinhood"].ok)     # downgraded, not fatal
        self.assertIn("no creds", by_broker["robinhood"].error or "")


class TestHistoricalMetadataEnrichment(unittest.TestCase):
    """The --asof path produces sparse Instruments (just ISIN). When a
    matching live snapshot is available, we copy name / asset_class /
    listing_currency / identifiers across. Money is never touched."""

    def _sparse_historical_snapshot(self):
        inst = Instrument(
            instrument_id="degiro:isin:US0378331005",
            identifiers={"isin": "US0378331005",
                         "broker:degiro": "US0378331005"},
            name="ISIN US0378331005",        # sparse: ISIN-name placeholder
            asset_class=AssetClass.OTHER,    # sparse default
            listing_currency="EUR",          # sparse: account base
        )
        acct = Account(account_id="degiro", broker="degiro",
                       base_currency="EUR")
        pos = Position(
            account_id="degiro", instrument_id=inst.instrument_id,
            quantity=Decimal("4"), value_base=Decimal("1000"),
            cost_basis_base=Decimal("1000"),
            realized_product_pl_base=Decimal("0"),
            realized_currency_pl_base=Decimal("0"),
            unrealized_product_pl_base=Decimal("0"),
            unrealized_currency_pl_base=Decimal("0"),
        )
        return PortfolioSnapshot(
            account=acct, instruments=[inst], positions=[pos], cash_balances=[],
        )

    def _rich_live_snapshot(self):
        inst = Instrument(
            instrument_id="degiro:isin:US0378331005",
            identifiers={"isin": "US0378331005", "ticker": "AAPL",
                         "broker:degiro": "12345"},
            name="Apple Inc",
            asset_class=AssetClass.STOCK,
            listing_currency="USD",
            listing_venue="NASDAQ",
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
        return PortfolioSnapshot(
            account=acct, instruments=[inst], positions=[pos], cash_balances=[],
        )

    def test_metadata_copied_money_untouched(self):
        historical = [BrokerSnapshot(broker="degiro",
                                     snapshot=self._sparse_historical_snapshot())]
        live_meta = {"degiro": self._rich_live_snapshot().instruments}
        enriched = _enrich_historical_metadata(historical, live_meta)

        out_inst = enriched[0].snapshot.instruments[0]
        # Display metadata: lifted from live
        self.assertEqual(out_inst.name,             "Apple Inc")
        self.assertEqual(out_inst.asset_class,      AssetClass.STOCK)
        self.assertEqual(out_inst.listing_currency, "USD")
        self.assertEqual(out_inst.identifiers["ticker"], "AAPL")
        # Identifiers preserve historical keys not present in live
        self.assertIn("isin", out_inst.identifiers)

        # Money is untouched on the Position — fold is canonical for history
        out_pos = enriched[0].snapshot.positions[0]
        self.assertEqual(out_pos.value_base,      Decimal("1000"))
        self.assertEqual(out_pos.cost_basis_base, Decimal("1000"))

    def test_no_live_match_passes_through(self):
        historical = [BrokerSnapshot(broker="degiro",
                                     snapshot=self._sparse_historical_snapshot())]
        # Empty meta dict + OpenFIGI fallback off → original sparse
        # metadata preserved (no network calls in tests).
        enriched = _enrich_historical_metadata(
            historical, {}, openfigi_fallback=False)
        out_inst = enriched[0].snapshot.instruments[0]
        self.assertEqual(out_inst.name, "ISIN US0378331005")
        self.assertEqual(out_inst.asset_class, AssetClass.OTHER)

    def test_openfigi_fallback_when_no_live_match(self):
        """Live snapshot doesn't know the ISIN (delisted etc.). OpenFIGI
        fills in name + asset_class + ticker. Cached resolve avoids the
        real network call — we inject one via _cache.save_openfigi_metadata."""
        import tempfile
        from sq_platform import _cache
        tmp = tempfile.TemporaryDirectory()
        try:
            orig = _cache.CACHE_DIR
            _cache.CACHE_DIR = type(orig)(tmp.name)
            # Pre-populate the cache so OpenFIGI is never called over the network
            _cache.save_openfigi_metadata("US0378331005", {
                "isin":         "US0378331005",
                "ticker":       "AAPL",
                "yahoo_ticker": "AAPL",
                "name":         "Apple Inc",
                "asset_class":  "STOCK",
                "exch_code":    "UN",
            })
            historical = [BrokerSnapshot(
                broker="degiro",
                snapshot=self._sparse_historical_snapshot())]
            # No live match in instruments_by_broker → OpenFIGI fallback fires
            enriched = _enrich_historical_metadata(historical, {})
            out_inst = enriched[0].snapshot.instruments[0]
            self.assertEqual(out_inst.name,        "Apple Inc")
            self.assertEqual(out_inst.asset_class, AssetClass.STOCK)
            self.assertEqual(out_inst.identifiers.get("ticker"), "AAPL")
        finally:
            _cache.CACHE_DIR = orig
            tmp.cleanup()

    def test_openfigi_negative_cache_does_not_explode(self):
        """OpenFIGI miss is cached as a negative sentinel so we don't
        hit the network repeatedly. The fallback path must read that
        sentinel and degrade silently — never raise. (FIRDS — the next
        rung — is negative-cached too so no network call happens.)"""
        import tempfile
        from sq_platform import _cache
        tmp = tempfile.TemporaryDirectory()
        try:
            orig = _cache.CACHE_DIR
            _cache.CACHE_DIR = type(orig)(tmp.name)
            _cache.save_openfigi_metadata(
                "US0378331005", {"_negative": True})
            _cache.save_firds_metadata(
                "US0378331005", {"_negative": True})
            historical = [BrokerSnapshot(
                broker="degiro",
                snapshot=self._sparse_historical_snapshot())]
            enriched = _enrich_historical_metadata(historical, {})
            out_inst = enriched[0].snapshot.instruments[0]
            # Stayed sparse — degraded gracefully
            self.assertEqual(out_inst.name, "ISIN US0378331005")
            self.assertEqual(out_inst.asset_class, AssetClass.OTHER)
        finally:
            _cache.CACHE_DIR = orig
            tmp.cleanup()

    def test_firds_rung_fires_after_openfigi_miss(self):
        """The resolver CHAIN: OpenFIGI negative → FIRDS supplies name /
        asset class / listing currency (but no ticker — FIRDS has none).
        Both resolvers injected via their caches; zero network."""
        import tempfile
        from sq_platform import _cache
        tmp = tempfile.TemporaryDirectory()
        try:
            orig = _cache.CACHE_DIR
            _cache.CACHE_DIR = type(orig)(tmp.name)
            _cache.save_openfigi_metadata(
                "US0378331005", {"_negative": True})
            _cache.save_firds_metadata("US0378331005", {
                "isin":         "US0378331005",
                "ticker":       None,
                "yahoo_ticker": None,
                "name":         "PREMIER OIL",
                "asset_class":  "STOCK",
                "exch_code":    "SGMY",
                "currency":     "GBP",
                "cfi":          "ESVUFR",
                "lei":          None,
            })
            historical = [BrokerSnapshot(
                broker="degiro",
                snapshot=self._sparse_historical_snapshot())]
            enriched = _enrich_historical_metadata(historical, {})
            out_inst = enriched[0].snapshot.instruments[0]
            self.assertEqual(out_inst.name, "PREMIER OIL")
            self.assertEqual(out_inst.asset_class, AssetClass.STOCK)
            self.assertEqual(out_inst.listing_currency, "GBP")
            self.assertNotIn("ticker", out_inst.identifiers)
        finally:
            _cache.CACHE_DIR = orig
            tmp.cleanup()

    def test_failed_historical_broker_passes_through(self):
        failed = BrokerSnapshot(broker="degiro", snapshot=None,
                                error="something broke")
        live_meta = {"degiro": self._rich_live_snapshot().instruments}
        out = _enrich_historical_metadata([failed], live_meta)
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], failed)   # untouched


class TestEventPositionsRender(unittest.TestCase):
    """Regression: an EVENT (prediction-market) position must render in the
    aggregated positions tab, not KeyError. The label lookup is defensive —
    even a brand-new asset class falls back to its name rather than crashing
    the whole view."""

    def _event_broker(self, broker, ccy):
        inst = Instrument(
            instrument_id=f"{broker}:M1",
            identifiers={f"broker:{broker}": "M1"},
            name="Will X happen?", asset_class=AssetClass.EVENT,
            listing_currency=ccy,
            terms={"event_id": "EVT", "outcome": "YES",
                   "resolution_date": "2025-12-31",
                   "market_result": None, "settlement_value": None},
        )
        acct = Account(account_id=broker, broker=broker, base_currency=ccy)
        pos = Position(
            account_id=broker, instrument_id=inst.instrument_id,
            quantity=Decimal("100"), last_price_local=Decimal("0.62"),
            value_base=Decimal("62"), cost_basis_base=Decimal("55"),
            unrealized_product_pl_base=Decimal("7"),
            unrealized_currency_pl_base=Decimal("0"),
            realized_product_pl_base=Decimal("0"),
            realized_currency_pl_base=Decimal("0"),
        )
        snap = PortfolioSnapshot(account=acct, instruments=[inst],
                                 positions=[pos], cash_balances=[])
        return BrokerSnapshot(broker=broker, snapshot=snap)

    def test_event_positions_render_without_keyerror(self):
        from sq_platform.aggregated import _positions_tab
        from sq_aggregator import aggregate_positions
        brokers = [self._event_broker("kalshi", "USD"),
                   self._event_broker("polymarket", "USDC")]
        flat = aggregate_positions(brokers)
        body = _positions_tab(flat)            # must NOT raise
        self.assertIn("Event contracts", body)

    def test_unmapped_asset_class_falls_back_to_name(self):
        from sq_platform.aggregated import _asset_label
        self.assertEqual(_asset_label(AssetClass.EVENT), "Event contracts")
        # A hypothetical unmapped class → its .value, never a KeyError
        class _Fake:
            value = "WIDGET"
        self.assertEqual(_asset_label(_Fake()), "WIDGET")


class _FakeModule:
    """Stand-in for a broker bundle module. Records the account each
    snapshot()/snapshots_at() call was made with."""
    def __init__(self, account_list):
        self._account_list = account_list
        self.calls = []

    def accounts(self):
        return self._account_list

    def snapshot(self, asof=None, *, account=None):
        self.calls.append(("snapshot", asof, account))
        return f"snap[{account}]"


class TestBrokerLabelSplit(unittest.TestCase):
    def test_qualified(self):
        self.assertEqual(_broker_label_split("degiro:work"), ("degiro", "work"))

    def test_bare(self):
        self.assertEqual(_broker_label_split("degiro"), ("degiro", None))


class TestMakeBrokerCall(unittest.TestCase):
    def test_closes_over_account(self):
        mod = _FakeModule([None])
        call = _make_broker_call(mod, "work")
        call()
        self.assertEqual(mod.calls[-1], ("snapshot", None, "work"))

    def test_falls_back_when_snapshot_rejects_account(self):
        # Legacy broker whose snapshot() doesn't accept account=…
        class _Legacy:
            def __init__(self):
                self.calls = []
            def snapshot(self, asof=None):
                self.calls.append(asof)
                return "legacy"
        leg = _Legacy()
        call = _make_broker_call(leg, "work")
        out = call()
        self.assertEqual(out, "legacy")
        self.assertEqual(leg.calls, [None])   # called without account kwarg


class TestMultiAccountDiscovery(unittest.TestCase):
    """Discovery iterates (broker, account) pairs from accounts(). The
    label is bare for legacy (None) accounts and `broker:account` for
    named ones."""

    def _fake_root(self):
        """A real tempdir with one `modules/sq-degiro/` so _discover_brokers's
        glob + is_dir succeed without mocking pathlib internals."""
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        (Path(tmp.name) / "modules" / "sq-degiro").mkdir(parents=True)
        return tmp

    def test_iterates_accounts_into_labels(self):
        mod = _FakeModule(["primary", "work"])
        tmp = self._fake_root()
        try:
            with mock.patch("sq_platform.aggregated.importlib.import_module",
                            return_value=mod):
                out = _discover_brokers(Path(tmp.name))
        finally:
            tmp.cleanup()
        labels = [label for label, _ in out]
        self.assertEqual(labels, ["degiro:primary", "degiro:work"])
        # Each call closes over the right account
        for label, fn in out:
            fn()
        self.assertEqual(
            [c[2] for c in mod.calls], ["primary", "work"])

    def test_legacy_none_account_is_bare_label(self):
        mod = _FakeModule([None])
        tmp = self._fake_root()
        try:
            with mock.patch("sq_platform.aggregated.importlib.import_module",
                            return_value=mod):
                out = _discover_brokers(Path(tmp.name))
        finally:
            tmp.cleanup()
        self.assertEqual([label for label, _ in out], ["degiro"])


if __name__ == "__main__":
    unittest.main()
