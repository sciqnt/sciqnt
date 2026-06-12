"""sq-kalshi — Kalshi event-contract source unit (official v2 REST API).

The first AssetClass.EVENT connector — proves the prediction-market schema
extension end-to-end. Read-only.

Public surface:
  * `snapshot(asof=None, *, account=None)` — current portfolio (open event
    contracts + USD cash) via the RSA-PSS-signed v2 API. `asof` unsupported
    (no historical reconstruction wired) — raises.
  * `accounts()` — configured account names (multi-account ready; `[None]`
    legacy single-account).

NOT implemented (honest gaps): load_history()/snapshots_at() — the
/portfolio/settlements endpoint could seed a transaction ledger but isn't
folded yet; execution (read-only, separate trust tier).

Auth: API key id + RSA private key (PEM), stored locally via sq_secrets.
USD-base. Prices are probabilities in [0,1] (Kalshi cents/100).
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import sq_secrets

SERVICE = "sq-kalshi"
SECRET_KEYS = ["key_id", "private_key"]
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def accounts():
    named = sq_secrets.list_accounts(SERVICE)
    sq_secrets.load_dotenv(_ENV_FILE)
    legacy = sq_secrets.get_secret(SERVICE, "key_id", "KALSHI_KEY_ID")
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
            "sq-kalshi has no historical (asof) support yet — settlements-based "
            "history reconstruction isn't wired. Live snapshot only."
        )
    from .canonical import to_canonical
    from .live import fetch_live
    raw = fetch_live(account=account)
    return to_canonical(
        raw["positions_resp"], raw["balance_resp"],
        account_id=("kalshi" if account is None else f"kalshi:{account}"),
        market_prices=raw.get("market_prices"),
    )


__all__ = ["snapshot", "accounts"]
