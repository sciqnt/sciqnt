"""_collect_snapshots — concurrent broker fetching.

Proves brokers are fetched in parallel (wall-clock ≈ slowest, not the sum),
results stay in discovery order, one broker's failure degrades only itself, and
progress is reported per broker. Fakes the broker fns (no network).
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

from sq_platform import aggregated as ag                # noqa: E402


def _slow_ok(delay, snap="SNAP"):
    def _fn(*a, **k):
        time.sleep(delay)
        return snap
    return _fn


class TestCollectParallel(unittest.TestCase):
    def setUp(self):
        # No cache, no real conformance / disk — isolate the concurrency logic.
        self._p = [
            mock.patch.object(ag.conformance, "check_snapshot", return_value=[]),
            mock.patch.object(ag._cache, "save_snapshot", lambda *a, **k: None),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _run(self, brokers):
        with mock.patch.object(ag, "_discover_brokers", return_value=brokers):
            return ag._collect_snapshots(Path("."), use_snapshot_cache=False)

    def test_runs_concurrently(self):
        brokers = [(f"b{i}", _slow_ok(0.15)) for i in range(4)]
        t0 = time.monotonic()
        out = self._run(brokers)
        elapsed = time.monotonic() - t0
        self.assertEqual(len(out), 4)
        self.assertTrue(all(b.ok for b in out))
        self.assertLess(elapsed, 0.45, f"serial would be ~0.6s; got {elapsed:.2f}s")

    def test_preserves_discovery_order(self):
        brokers = [("zebra", _slow_ok(0.10)), ("alpha", _slow_ok(0.01)),
                   ("mid", _slow_ok(0.05))]
        out = self._run(brokers)
        self.assertEqual([b.broker for b in out], ["zebra", "alpha", "mid"])

    def test_one_failure_degrades_only_itself(self):
        def boom(*a, **k):
            raise RuntimeError("kaboom")
        brokers = [("good", _slow_ok(0.01)), ("bad", boom)]
        out = {b.broker: b for b in self._run(brokers)}
        self.assertTrue(out["good"].ok)
        self.assertFalse(out["bad"].ok)
        self.assertIn("kaboom", out["bad"].error)

    def test_progress_callback_fires_per_broker(self):
        seen = []
        lock = __import__("threading").Lock()

        def on_update(name, state):
            with lock:
                seen.append((name, state))
        brokers = [("a", _slow_ok(0.01)), ("b", _slow_ok(0.01))]
        with mock.patch.object(ag, "_discover_brokers", return_value=brokers):
            ag._collect_snapshots(Path("."), use_snapshot_cache=False,
                                  on_update=on_update)
        names = {n for n, _ in seen}
        self.assertEqual(names, {"a", "b"})
        self.assertTrue(any(s == "ok" for _, s in seen))

    def test_needs_action_fails_fast_without_retry(self):
        """NeedsAction (e.g. 'approve the login in the app') is NOT retried —
        a retry can't fix a user-action requirement and re-attempting a login
        would re-fire the in-app push. A transient error still retries."""
        import sq_secrets
        calls = {"need": 0, "flaky": 0}

        def needs(*a, **k):
            calls["need"] += 1
            raise sq_secrets.NeedsAction("approve in the app", action="approve")

        def flaky(*a, **k):
            calls["flaky"] += 1
            raise RuntimeError("transient")

        brokers = [("need", needs), ("flaky", flaky)]
        with mock.patch.object(ag, "_FETCH_RETRY_DELAY_S", 0):
            out = {b.broker: b for b in self._run(brokers)}
        self.assertFalse(out["need"].ok)
        self.assertEqual(calls["need"], 1)                          # no retry
        self.assertIn("NeedsAction", out["need"].error)
        self.assertEqual(calls["flaky"], ag._LIVE_FETCH_ATTEMPTS)   # retried


if __name__ == "__main__":
    unittest.main()
