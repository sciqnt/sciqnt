#!/usr/bin/env python3
"""sq-degiro — remove a connected account's stored credentials.

The symmetric inverse of `setup` (research/connect-experience.md): a bundle
owns its credential ENTRY, so it owns the REMOVAL too. The generic mechanism
(scrub keychain + .env + session + registry) lives in the shared substrate
`core/sq_secrets.forget_account`; this script just supplies WHICH secrets
Degiro uses + WHERE its .env fallback lives.

Single-account (legacy / default):
  sciqnt degiro forget
A named account:
  sciqnt degiro forget --account work

Deletes the account's keychain entries (and matching .env lines), drops the
persisted session, and unregisters the name. Idempotent — running it on an
already-removed account is a quiet no-op.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent           # bundle root
ROOT = HERE.parents[1]                                   # sciqnt repo root
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE / "src"))

import sq_secrets                                          # noqa: E402
from sq_degiro import SERVICE, SECRET_KEYS, SECRET_ENV, _ENV_FILE  # noqa: E402


def forget(account=None) -> dict:
    """Remove `account` (None = legacy single-account). Returns the report
    from sq_secrets.forget_account."""
    keys = [(k, SECRET_ENV.get(k)) for k in SECRET_KEYS]
    return sq_secrets.forget_account(
        SERVICE, account, keys, env_path=_ENV_FILE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="sq-degiro forget",
        description="remove a connected Degiro account's stored credentials")
    parser.add_argument(
        "--account", default=None,
        help="account label to remove (e.g. --account work). Omit for the "
             "legacy single-account scheme (bare keychain keys).")
    args = parser.parse_args()

    import sq_tui                                          # noqa: E402
    label = f"degiro:{args.account}" if args.account else "degiro"
    report = forget(args.account)
    removed = report["keychain"] or report["env"]
    if removed:
        print(f"  {sq_tui.GREEN}✓{sq_tui.RST} removed {label} "
              f"{sq_tui.DIM}(credentials, session){sq_tui.RST}")
    else:
        print(f"  {sq_tui.DIM}nothing stored for {label} — already removed"
              f"{sq_tui.RST}")
