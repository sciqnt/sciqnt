#!/usr/bin/env python3
"""sq-degiro probe — diagnose Degiro login WITHOUT storing anything.

Useful when `setup_creds.py`'s verify keeps failing and you want to isolate
which value is wrong:
  - 6-digit code (live, from your authenticator app) succeeds → your username
    and password are fine; the STORED TOTP setup key is wrong (regenerate it).
  - 6-digit code also fails → username or password is wrong (or clock skew).
Nothing is persisted. Read-only diagnostic.
"""
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
from sq_secrets import prompt, select_mode  # noqa: E402


def main():
    print("sq-degiro probe — diagnose Degiro login (no storage, no .env writes)")
    print("Bypasses the stored TOTP secret by using a fresh 6-digit code from")
    print("your authenticator app.\n")

    try:
        from degiro_connector.trading.api import API as TradingAPI
        from degiro_connector.trading.models.credentials import Credentials
    except ImportError:
        sys.exit("degiro-connector not installed in this env.")

    mode = select_mode()
    user = prompt("Degiro username", hidden=False, mode=mode)
    pwd = prompt("Degiro password", hidden=True, mode=mode)
    otp = prompt("Current 6-digit 2FA code (blank if no 2FA on the account)",
                 hidden=True, mode=mode)
    if not user or not pwd:
        sys.exit("cancelled.")

    kw = {"username": user, "password": pwd}
    if otp:
        otp = otp.strip().replace(" ", "")
        if not otp.isdigit() or len(otp) not in (6, 8):
            sys.exit(f"6-digit code looks malformed (got {len(otp)} chars).")
        kw["one_time_password"] = int(otp)

    creds = Credentials(**kw)
    api = TradingAPI(credentials=creds)
    api.setup_all_actions()                          # degiro-connector 3.x action loader
    print(f"\nattempting connect (server time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}) ...")
    try:
        api.connect()
    except Exception as e:
        print(f"\n  FAILED: {type(e).__name__}: {e}")
        print("\n  Most likely:")
        print("    * username or password is wrong (try logging in to Degiro web)")
        print("    * 2FA isn't actually enabled on Degiro (re-do the enable flow")
        print("      and CONFIRM with a code so it's active)")
        print("    * server clock is off — check `date`; TOTP needs <30s skew")
        return

    print("\n  SUCCESS — Degiro accepted your credentials.")
    print("\n  Diagnosis: your username + password are fine.")
    print("  If setup_creds.py keeps failing with the stored setup key, the key")
    print("  itself is wrong (different/stale value, or 2FA setup wasn't")
    print("  fully completed). Disable + re-enable 2FA on Degiro to get a fresh")
    print("  32-character setup key, then re-run: sciqnt degiro setup")


if __name__ == "__main__":
    main()
