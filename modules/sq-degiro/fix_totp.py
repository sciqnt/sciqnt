#!/usr/bin/env python3
"""Diagnose & auto-normalize the stored Degiro TOTP setup key in .env.

NEVER prints the value. Reports length + base32 validity; if stripping
whitespace/hyphens + uppercasing makes it valid, writes the cleaned value
back to .env (perms preserved at 0600).

The Degiro 2FA "setup key" is base32 (A-Z and 2-7), 32 characters. The
`base64.b32decode` call inside `degiro-connector` raises
`binascii.Error: Incorrect padding` when len(secret) % 8 != 0 — i.e. the
key is the wrong length (not a whitespace/case issue).

Usage:  python3 modules/sq-degiro/fix_totp.py
"""
import pathlib
import re
import sys

ENV_PATH = pathlib.Path(__file__).resolve().parent / ".env"
VAR = "DEGIRO_TOTP_SECRET"


def main():
    if not ENV_PATH.exists():
        sys.exit(f"no .env at {ENV_PATH} — run setup_creds.py first.")

    lines = ENV_PATH.read_text().splitlines()
    idx = None
    secret = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(VAR + "="):
            idx = i
            secret = s[len(VAR) + 1:].strip().strip('"').strip("'")
            break
    if secret is None:
        sys.exit(f"no {VAR} in .env (skipped during setup? re-run setup_creds.py).")

    cleaned = re.sub(r"[\s\-]", "", secret).upper()
    chars_ok = bool(re.fullmatch(r"[A-Z2-7]+", cleaned)) if cleaned else False
    len_ok = chars_ok and len(cleaned) % 8 == 0
    valid = chars_ok and len_ok

    print(f"  raw length            : {len(secret)}")
    if len(cleaned) != len(secret):
        print(f"  after strip/uppercase : {len(cleaned)}")
    print(f"  base32 charset (A-Z2-7): {chars_ok}")
    print(f"  length divisible by 8 : {len_ok}")
    print(f"  valid                 : {valid}")

    if valid and cleaned != secret:
        lines[idx] = f"{VAR}={cleaned}"
        ENV_PATH.write_text("\n".join(lines) + "\n")
        try:
            ENV_PATH.chmod(0o600)
        except Exception:
            pass
        print(f"\n  -> normalized + wrote back to {ENV_PATH}. Try live.py again.")
    elif valid:
        print("\n  -> already valid — the error is somewhere else.")
    else:
        print("\n  -> NOT a valid base32 setup key.")
        if not chars_ok:
            print("     The stored value contains non-base32 characters even after cleanup.")
            print("     Likely cause: you entered the 6-digit OTP code instead of the setup key,")
            print("     or pasted a QR-code URL. Re-run setup_creds.py and enter only the")
            print("     32-char 'setup key' Degiro shows beside the QR code (text — not the QR).")
        else:
            print(f"     Length is {len(cleaned)}; Degiro's setup key is 32. Most likely truncated paste.")
            print("     Re-run setup_creds.py to re-enter the TOTP field (others can stay).")


if __name__ == "__main__":
    main()
