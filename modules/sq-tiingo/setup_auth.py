#!/usr/bin/env python3
"""sq-tiingo — one-time API-key setup.

Create a free account at https://www.tiingo.com (Starter tier: 500
symbols/month, 50 req/hr — plenty for a personal portfolio), copy the
API token from your account page, then:

  sciqnt tiingo auth

The token is stored via the shared sq_secrets substrate (keychain-first,
.env fallback) and VERIFIED with a real one-row price fetch before
anything is persisted — a typo'd key fails here, not silently at the
next portfolio render.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-tiingo" / "src"))
from sq_secrets import prompt_and_store


def _verify_tiingo(values):
    """One real (tiny) price fetch — proves the key is live."""
    from datetime import date, timedelta
    from sq_tiingo import fetch_chart
    today = date.today()
    fetch_chart("AAPL", today - timedelta(days=7), today,
                token=values["api_token"].strip())
    return True


SERVICE = "sq-tiingo"
FIELDS = [
    {"key": "api_token", "env": "TIINGO_API_KEY",
     "label": "Tiingo API token (tiingo.com → Account → API)",
     "hidden": True, "required": True,
     "normalize": lambda s: s.strip()},
]

if __name__ == "__main__":
    prompt_and_store(
        SERVICE, FIELDS, review=True, verify=_verify_tiingo,
        title="Connect Tiingo (official EOD prices, free key)",
        note="Free Starter tier · 500 symbols/mo · US-listed symbols only",
    )
