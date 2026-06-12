"""sq-robinhood — Robinhood source unit (unofficial, via robin_stocks).

Public surface (the cross-broker contract — implements the subset Robinhood
supports today):

  * `snapshot(asof=None, *, account=None)` — current live state via the
    robin_stocks API. `asof` is NOT supported (Robinhood has no CSV/history
    reconstruction path yet) — raises if given, so the aggregated `--asof`
    view downgrades this broker with a clear reason rather than fabricating.
  * `accounts()` — configured account names (multi-account ready via
    sq_secrets; `[None]` for the legacy single-account scheme).

NOT implemented (honest gaps, see FINDINGS.md):
  * `load_history()` / `snapshots_at()` — Robinhood has no CSV export and the
    order-history reconstruction (get_all_stock_orders/get_all_crypto_orders →
    canonical Transactions) isn't wired yet. So TWR / drawdown / realised-P&L
    don't compute for Robinhood until that lands. The LIVE snapshot (positions,
    cash, unrealised P&L) works.
  * Execution — read-only; execution is a separate higher trust tier.

Robinhood is USD-base; stocks → STOCK, crypto → CRYPTO. No schema change vs the
equities path — this bundle is the second connector that proves the canonical
schema is broker-agnostic in practice.
"""
from datetime import datetime
from typing import Optional

import sq_secrets
from pathlib import Path

SERVICE = "sq-robinhood"
SECRET_KEYS = ["username", "password", "mfa_secret"]
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def accounts():
    """Configured Robinhood account names. `[None]` = legacy single-account.
    Checks BOTH keychain and the .env fallback (see sq_degiro.accounts)."""
    named = sq_secrets.list_accounts(SERVICE)
    sq_secrets.load_dotenv(_ENV_FILE)
    legacy_user = sq_secrets.get_secret(SERVICE, "username", "ROBINHOOD_USERNAME")
    out = []
    if legacy_user:
        out.append(None)
    out.extend(named)
    # Empty == this broker has NO account connected yet (a normal state, not
    # an error). The dispatcher then lists it as "available to connect"
    # rather than fetching it and surfacing a CredentialsMissing error.
    return out


def snapshot(asof: Optional[datetime] = None, *, account: Optional[str] = None):
    """Return a canonical `PortfolioSnapshot` of current Robinhood state.

    `asof` is unsupported — Robinhood has no historical reconstruction path
    (no CSV, order-history folding not yet wired). Raises so the dispatcher
    downgrades this broker in `--asof` mode rather than showing stale/wrong data.
    """
    if asof is not None:
        raise RuntimeError(
            "sq-robinhood has no historical (asof) support yet — Robinhood "
            "exposes no CSV/history reconstruction path. Live snapshot only."
        )
    from .canonical import to_canonical
    from .live import fetch_live
    raw = fetch_live(account=account)
    return to_canonical(
        raw["stock_positions"], raw["instrument_map"], raw["price_map"],
        raw["crypto_positions"], raw["crypto_price_map"], raw["account_profile"],
        account_id=("robinhood" if account is None else f"robinhood:{account}"),
    )


__all__ = ["snapshot", "accounts"]
