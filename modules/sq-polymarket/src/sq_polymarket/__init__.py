"""sq-polymarket — Polymarket event-contract source unit (public Data API).

Second AssetClass.EVENT connector + the first WALLET-based (non-broker) source.
Read-only, USDC-base. Positions come from a PUBLIC no-auth endpoint — the only
"credential" is a wallet address (public, not secret).

Public surface:
  * `snapshot(asof=None, *, account=None)` — current positions for the
    configured wallet. `asof` unsupported (no historical reconstruction) — raises.
  * `accounts()` — configured wallet labels (multi-wallet ready; `[None]` legacy).

Cash: the positions API returns none, so we read the funder address's on-chain
USDC balance (native + bridged USDC.e, summed) via a public Polygon JSON-RPC
eth_call — see onchain.py. Best-effort (None on RPC failure → cash omitted).

Honest gaps: no history/asof; trading (CLOB) auth not implemented (read-only).
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import sq_secrets

SERVICE = "sq-polymarket"
SECRET_KEYS = ["wallet_address"]
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def accounts():
    named = sq_secrets.list_accounts(SERVICE)
    sq_secrets.load_dotenv(_ENV_FILE)
    legacy = sq_secrets.get_secret(SERVICE, "wallet_address", "POLYMARKET_WALLET")
    out = []
    if legacy:
        out.append(None)
    out.extend(named)
    # Empty == this broker has NO account connected yet (a normal state, not
    # an error). The dispatcher then lists it as "available to connect"
    # rather than fetching it and surfacing a CredentialsMissing error.
    return out


def snapshot(asof: Optional[datetime] = None, *, account: Optional[str] = None):
    if asof is not None:
        raise RuntimeError(
            "sq-polymarket has no historical (asof) support — the Data API "
            "returns current positions only. Live snapshot only."
        )
    from .canonical import to_canonical
    from .live import fetch_live
    raw = fetch_live(account=account)
    return to_canonical(
        raw["positions"],
        account_id=("polymarket" if account is None else f"polymarket:{account}"),
        cash_usdc=raw.get("cash_usdc"),
    )


__all__ = ["snapshot", "accounts"]
