#!/usr/bin/env python3
"""sq-polymarket — one-time setup.

Polymarket positions are read from a PUBLIC, no-auth endpoint — the only thing
we need is your wallet ADDRESS (public, not secret). For proxy wallets
(Magic / browser-wallet logins) use the FUNDER address shown on your Polymarket
profile — that's where positions + USDC actually live, NOT the signing EOA.

  sciqnt polymarket setup
  sciqnt polymarket setup --account main

We store it via the shared sq_secrets substrate for consistency + multi-wallet
support (it's stored locally but isn't sensitive). Verified by a real positions
fetch before storing.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-polymarket" / "src"))
from sq_secrets import prompt_and_store


def _addr_valid(s):
    return bool(re.fullmatch(r"0x[0-9a-fA-F]{40}", s.strip()))


def _verify_polymarket(values):
    """A real (public) positions fetch — proves the address is reachable."""
    try:
        from sq_polymarket.live import fetch_live
    except ImportError:
        return True
    # Temporarily exercise the endpoint with the entered address.
    import json
    import urllib.parse
    import urllib.request
    from sq_polymarket.live import DATA_API
    qs = urllib.parse.urlencode({"user": values["wallet_address"].strip()})
    req = urllib.request.Request(f"{DATA_API}/positions?{qs}",
                                 headers={"User-Agent": "sciqnt/0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        json.load(r)        # 200 + valid JSON (even []) → reachable
    return True


SERVICE = "sq-polymarket"
ENV_PATH = HERE / ".env"
FIELDS = [
    {"key": "wallet_address", "env": "POLYMARKET_WALLET",
     "label": "Polymarket wallet/funder address (0x… 40 hex)",
     "hidden": False, "required": True,
     "normalize": lambda s: s.strip(), "validate": _addr_valid},
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="sq-polymarket setup")
    parser.add_argument("--account", default=None,
                        help="wallet label for multi-wallet setups")
    args = parser.parse_args()
    prompt_and_store(
        SERVICE, FIELDS, env_path=ENV_PATH, review=True,
        verify=_verify_polymarket, account=args.account,
        default_account_from="wallet_address",
        title="Connect Polymarket",
        note="Wallet/funder address — PUBLIC, not a secret. Use the funder "
             "address from your profile. Verified by a positions fetch.",
    )
