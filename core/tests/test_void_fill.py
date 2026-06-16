"""Demo void-fill is the PLATFORM's rule (not the connector's) — tested HERE.

Moved from the sq-demo connector (where it couldn't live: it reaches into app
internals and needs the demo to be a discoverable bundle, only true after the
connector's own conformance passes — a chicken-and-egg). The rule: the sq-demo
bundle participates only while no REAL account is connected, keyed on the
`demo_mode` config (auto|on|off). The platform owns it because a bundle can't
know about other brokers (P11 modularity).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # core/

from sq_platform.aggregated import _apply_demo_void_fill   # noqa: E402


def _brokers(*labels):
    """A synthetic (label, fn) broker list — the void-fill rule is pure on it."""
    return [(lb, lambda: None) for lb in labels]


def _labels(out):
    return [lb for lb, _ in out]


class TestDemoVoidFill(unittest.TestCase):
    def test_auto_demo_fills_the_void_when_alone(self):
        out = _apply_demo_void_fill(_brokers("demo:sample"), "auto")
        self.assertEqual(_labels(out), ["demo:sample"],
                         "demo must fill the void when nothing real is connected")

    def test_auto_demo_vanishes_once_a_real_account_is_connected(self):
        out = _apply_demo_void_fill(_brokers("demo:sample", "degiro:me"), "auto")
        self.assertEqual(_labels(out), ["degiro:me"],
                         "demo must vanish once a real account is connected (auto)")

    def test_off_never_shows_demo(self):
        self.assertEqual(_labels(_apply_demo_void_fill(_brokers("demo:sample"), "off")), [])
        self.assertEqual(
            _labels(_apply_demo_void_fill(_brokers("demo:sample", "degiro:me"), "off")),
            ["degiro:me"])

    def test_on_always_keeps_demo(self):
        # 'on' keeps demo even alongside real accounts (an explicit user choice).
        self.assertEqual(_labels(_apply_demo_void_fill(_brokers("demo:sample"), "on")),
                         ["demo:sample"])
        self.assertEqual(
            _labels(_apply_demo_void_fill(_brokers("demo:sample", "degiro:me"), "on")),
            ["demo:sample", "degiro:me"])

    def test_real_only_is_untouched(self):
        out = _apply_demo_void_fill(_brokers("degiro:me", "kalshi:x"), "auto")
        self.assertEqual(_labels(out), ["degiro:me", "kalshi:x"])


if __name__ == "__main__":
    unittest.main()
