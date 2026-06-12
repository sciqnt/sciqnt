#!/usr/bin/env python3
"""sq-robinhood — one-time credential setup.

Robinhood-specific part only: WHICH secrets Robinhood needs (username, password,
optional MFA/TOTP setup key). The generic mechanism (native hidden dialog → OS
keychain, never touching the transcript) lives in the shared substrate
`core/sq_secrets`.

Single-account (default):
  sciqnt robinhood setup

Named account alongside (multi-account):
  sciqnt robinhood setup --account taxable

robin_stocks is UNOFFICIAL / reverse-engineered. Credentials are verified
against Robinhood (a real login) before storing — nothing is persisted if the
login fails.
"""
import argparse
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
from sq_secrets import prompt_and_store


def _b32_normalize(s):
    """MFA setup keys are base32 — strip whitespace/hyphens + uppercase."""
    return re.sub(r"[\s\-]", "", s).upper()


def _b32_valid(s):
    return bool(re.fullmatch(r"[A-Z2-7]+", s)) and len(s) % 8 == 0


def _verify_robinhood(values):
    """Trust-earned-through-conformance: attempt a real login before storing.
    Returns True if Robinhood accepts the credentials. Raising == False to
    prompt_and_store (nothing persisted)."""
    try:
        import robin_stocks.robinhood as rh
        import pyotp
    except ImportError:
        print("  (robin_stocks/pyotp not installed in this env — skipping verify)")
        return True
    mfa_code = None
    if values.get("mfa_secret"):
        mfa_code = pyotp.TOTP(values["mfa_secret"]).now()
    # Login into a stash dir (the resolved account label isn't known yet);
    # on_success moves the pickle into the account's session dir, so the
    # verify login BECOMES the persistent session/device — a throwaway
    # store_session=False login minted a new device_token and earned a
    # "new device" email, then the first real fetch earned another.
    import tempfile
    stash = tempfile.mkdtemp(prefix="sq-robinhood-setup-")
    rh.login(values["username"], values["password"], mfa_code=mfa_code,
             store_session=True, pickle_path=stash)
    _verify_robinhood.stash = stash      # raises above on any auth/MFA failure
    _verify_robinhood.no_mfa = not values.get("mfa_secret")
    return True


SERVICE = "sq-robinhood"
ENV_PATH = HERE / ".env"
FIELDS = [
    {"key": "username", "env": "ROBINHOOD_USERNAME",
     "label": "Robinhood username (email)", "hidden": False, "required": True},
    {"key": "password", "env": "ROBINHOOD_PASSWORD",
     "label": "Robinhood password", "hidden": True, "required": True},
    {"key": "mfa_secret", "env": "ROBINHOOD_MFA_SECRET",
     "label": "Robinhood MFA/2FA setup key (base32), blank if SMS/none",
     "hidden": True, "required": False,
     "normalize": _b32_normalize, "validate": _b32_valid},
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="sq-robinhood setup",
                                     description="store Robinhood credentials")
    parser.add_argument("--account", default=None,
                        help="account label for multi-account setups "
                             "(e.g. --account taxable). Omit for single-account.")
    args = parser.parse_args()

    def _adopt_session(account):
        """Move the verify login's pickle into the account's session dir —
        that login becomes the persistent session/device (no further
        new-device emails; see FINDINGS.md)."""
        stash = getattr(_verify_robinhood, "stash", None)
        if not stash:
            return
        import shutil
        from pathlib import Path
        from sq_secrets import session_dir
        dest = session_dir(SERVICE, account=account)
        for f in Path(stash).glob("*.pickle"):
            shutil.move(str(f), str(dest / f.name))
        shutil.rmtree(stash, ignore_errors=True)
        # One-line upgrade hint, only when the user is NOT on the top rung
        # (an authenticator-app key = no SMS/device challenges, ever).
        if getattr(_verify_robinhood, "no_mfa", False):
            import sq_tui
            print(f"  {sq_tui.DIM}tip: an authenticator-app MFA key makes "
                  f"logins fully automatic — re-run setup to add it"
                  f"{sq_tui.RST}")

    prompt_and_store(
        SERVICE, FIELDS, env_path=ENV_PATH, review=True,
        verify=_verify_robinhood, account=args.account,
        default_account_from="username", on_success=_adopt_session,
        title="Connect Robinhood",
        note="⚠ unofficial (robin_stocks) — against Robinhood ToS, at your own "
             "risk. Stored locally; verified by a real login before saving.",
    )
