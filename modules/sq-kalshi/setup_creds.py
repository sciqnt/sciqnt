#!/usr/bin/env python3
"""sq-kalshi — one-time credential setup.

Kalshi v2 uses RSA-key request signing: you generate an API key in the Kalshi
web UI, which gives you a KEY ID (uuid) + an RSA PRIVATE KEY (PEM). We store
both locally via the shared sq_secrets substrate (keychain-first, .env fallback).

  sciqnt kalshi setup
  sciqnt kalshi setup --account demo

The private key is multi-line PEM — paste it when prompted (terminal mode reads
it hidden; the PEM never touches the transcript). Credentials are verified with
a real signed GET /portfolio/balance before storing — nothing persists if the
signature is rejected.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-kalshi" / "src"))
from sq_secrets import prompt_and_store


def _verify_kalshi(values):
    """Trust-earned-through-conformance: a real signed request before storing."""
    try:
        from sq_kalshi.live import _get
    except ImportError:
        print("  (sq_kalshi/cryptography not importable — skipping verify)")
        return True
    creds = {"key_id": values["key_id"], "private_key": values["private_key"]}
    _get(creds, "/trade-api/v2/portfolio/balance")    # raises on bad signature/auth
    return True


def _pem_valid(s):
    return "BEGIN" in s and "PRIVATE KEY" in s and "END" in s


SERVICE = "sq-kalshi"
ENV_PATH = HERE / ".env"
FIELDS = [
    {"key": "key_id", "env": "KALSHI_KEY_ID",
     "label": "Kalshi API key id (uuid)", "hidden": False, "required": True},
    {"key": "private_key", "env": "KALSHI_PRIVATE_KEY",
     "label": "Kalshi RSA private key (PEM, paste the whole block)",
     "hidden": True, "required": True, "validate": _pem_valid},
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="sq-kalshi setup")
    parser.add_argument("--account", default=None,
                        help="account label for multi-account setups")
    args = parser.parse_args()
    prompt_and_store(
        SERVICE, FIELDS, env_path=ENV_PATH, review=True,
        verify=_verify_kalshi, account=args.account,
        default_account_from="key_id",
        title="Connect Kalshi",
        note="API key id + RSA private key (from the Kalshi web UI). Stored "
             "locally; verified with a signed request before saving.",
    )
