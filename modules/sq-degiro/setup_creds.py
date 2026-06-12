#!/usr/bin/env python3
"""sq-degiro — one-time credential setup.

Degiro-specific part only: WHICH secrets Degiro needs. The generic mechanism
(native hidden dialog -> OS keychain, never touching the transcript) lives in the
shared substrate `core/sq_secrets`.

Single-account (legacy / default):
  sciqnt degiro setup

Add a named account alongside (or instead of) the legacy single-account creds:
  sciqnt degiro setup --account work
The named account gets its own qualified keychain entries
(`sq-degiro:work:username` etc) and shows up as "degiro:work" in the
aggregated landing view. Multiple `--account` runs add more accounts.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent           # bundle root
ROOT = HERE.parents[1]                                   # sciqnt repo root
sys.path.insert(0, str(ROOT / "core"))
from sq_secrets import prompt_and_store


def _b32_normalize(s):
    """TOTP setup keys are base32. Strip whitespace/hyphens + uppercase so a
    pasted 'ABCD EFGH …' or 'abcd-efgh-…' becomes a clean key. Caught here
    rather than later in `base64.b32decode` (which throws 'Incorrect padding')."""
    return re.sub(r"[\s\-]", "", s).upper()


def _b32_valid(s):
    return bool(re.fullmatch(r"[A-Z2-7]+", s)) and len(s) % 8 == 0


def _verify_degiro(values):
    """Trust-earned-through-conformance: attempt a real connect with the entered
    credentials BEFORE storing. Returns True if Degiro accepts them; False
    otherwise. Raising is treated the same as False by prompt_and_store.
    Uses degiro-connector 3.x action-based API (setup_all_actions → connect)."""
    try:
        from degiro_connector.trading.api import API as TradingAPI
        from degiro_connector.trading.models.credentials import Credentials
    except ImportError:
        print("  (degiro-connector not installed in this env — skipping verify)")
        return True
    kw = {"username": values["username"], "password": values["password"]}
    if values.get("totp_secret"):
        kw["totp_secret_key"] = values["totp_secret"]
    creds = Credentials(**kw)
    api = TradingAPI(credentials=creds)
    api.setup_all_actions()                          # binds dynamic methods
    # sq_degiro.login (not bare api.connect()): completes the in-app
    # approval flow for accounts without a TOTP key — Degiro pushes a
    # popup to the DEGIRO app and we poll until the user taps Yes.
    sys.path.insert(0, str(HERE / "src"))
    from sq_degiro import login as degiro_login, restore_device_cookies
    # Ride the persisted 30-day device-trust cookie (if this account was
    # connected before) so re-running setup doesn't re-fire the in-app
    # popup. Cookies ONLY — a real login must still happen, because the
    # whole point of verify is to test the newly-typed credentials.
    restore_device_cookies(
        api, getattr(_verify_degiro, "cli_account", None)
        or values.get("username"))
    _verify_degiro.flow = degiro_login(api, notify=lambda m: print(f"  {m}"))
    # Stash the API so on_success can persist its session + cookies for the
    # RESOLVED account — the verify login then BECOMES the reusable session
    # (and the 'remember this device for 30 days' cookie survives) instead
    # of a throwaway (every throwaway login = a Degiro alert/popup).
    _verify_degiro.api = api
    return True


SERVICE = "sq-degiro"
ENV_PATH = HERE / ".env"                                 # gitignored, 0600
# Each field declares its keychain key AND its env-var name (used by the .env
# fallback when keychain is unavailable, e.g. macOS over SSH).
FIELDS = [
    {"key": "username", "env": "DEGIRO_USERNAME",
     "label": "Degiro username", "hidden": False, "required": True},
    {"key": "password", "env": "DEGIRO_PASSWORD",
     "label": "Degiro password", "hidden": True, "required": True},
    {"key": "totp_secret", "env": "DEGIRO_TOTP_SECRET",
     "label": "Degiro 2FA setup key (32 chars), blank if no 2FA",
     "hidden": True, "required": False,
     "normalize": _b32_normalize, "validate": _b32_valid},
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="sq-degiro setup",
                                     description="store Degiro credentials")
    parser.add_argument(
        "--account", default=None,
        help="account label for multi-account setups (e.g. --account work). "
             "Omit for the legacy single-account scheme (bare keychain keys).",
    )
    args = parser.parse_args()
    _verify_degiro.cli_account = args.account    # for the cookie restore

    def _history_hint(account):
        """Post-connect housekeeping, quietly: prepare the account's CSV-
        history dir, persist the verify login's session, and say at most ONE
        dim line — the user's job here was 'connect', everything else is
        progressive disclosure (the portfolio view's ⚠/help explains history
        when it matters; research/connect-experience.md)."""
        sys.path.insert(0, str(HERE / "src"))
        from sq_degiro import history_dir
        hd = history_dir(account)
        try:
            hd.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        api = getattr(_verify_degiro, "api", None)
        if api is not None:           # verify's login becomes THE session
            from sq_degiro import persist_session_state
            persist_session_state(api, account=account)
        import sq_tui
        if getattr(_verify_degiro, "flow", None) == "in-app":
            print(f"  {sq_tui.DIM}tip: a 2FA setup key (DEGIRO app › "
                  f"Settings › Security) makes logins fully automatic — "
                  f"re-run setup to add it{sq_tui.RST}")

    prompt_and_store(
        SERVICE, FIELDS, env_path=ENV_PATH, review=True,
        verify=_verify_degiro, account=args.account,
        default_account_from="username",
        title="Connect Degiro",
        note="Stored locally (keychain, or .env fallback). "
             "Verified against Degiro before saving.",
        on_success=_history_hint,
    )
