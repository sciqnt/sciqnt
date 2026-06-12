#!/usr/bin/env python3
"""sq-finnhub — one-time API-key setup.

Create a free account at https://finnhub.io (60 calls/min), copy the
API key from the dashboard, then:

  sciqnt finnhub auth

Stored via the shared sq_secrets substrate (keychain-first, .env
fallback) and VERIFIED with a real company-news fetch before anything
is persisted.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-finnhub" / "src"))
from sq_secrets import prompt_and_store


def _verify_finnhub(values):
    """One real news fetch — proves the key is live (401/403 raise)."""
    from sq_finnhub import fetch_company_news
    fetch_company_news("AAPL", token=values["api_token"].strip(), days=2)
    return True


SERVICE = "sq-finnhub"
FIELDS = [
    {"key": "api_token", "env": "FINNHUB_API_KEY",
     "label": "Finnhub API key (finnhub.io → Dashboard)",
     "hidden": True, "required": True,
     "normalize": lambda s: s.strip()},
]

if __name__ == "__main__":
    prompt_and_store(
        SERVICE, FIELDS, review=True, verify=_verify_finnhub,
        title="Connect Finnhub (official company news, free key)",
        note="Free tier · 60 calls/min · powers the news tab's keyed rung",
    )
