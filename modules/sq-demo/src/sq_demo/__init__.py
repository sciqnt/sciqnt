"""sq-demo — the deterministic demo portfolio (sciqnt's public face).

Activates ONLY while no real account is connected (the platform's
void-fill rule; config `demo_mode`: auto|on|off). Fully synthetic, fully
offline, fully deterministic — fictional instruments, seeded price walks,
a scripted multi-year history. These ARE the public figures: every
screenshot, doc, and first-run screen renders from here, never from
anyone's real finances.

Discovery contract (same as every broker bundle):
  * `accounts()` — always `["sample"]`; the PLATFORM decides whether the
    demo participates (it can't know about other brokers — modularity).
  * `snapshot(asof=None, *, account=None)` — conformance-clean snapshot
    at the seeded walk's prices; `asof` supported (PIT-correct).
  * `load_history(account=None)` — the canonical transaction stream
    (charts / TWR / XIRR / flows all derive from it, same as a broker).
"""
from datetime import datetime
from typing import Optional

from .portfolio import build_snapshot, transactions

DEMO = True                       # the platform's marker for void-fill


def accounts():
    return ["sample"]


def snapshot(asof: Optional[datetime] = None, *, account: Optional[str] = None):
    return build_snapshot(asof=asof)


def load_history(account: Optional[str] = None):
    return transactions()


__all__ = ["snapshot", "accounts", "load_history", "DEMO"]
