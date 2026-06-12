#!/usr/bin/env python3
"""sq-degiro doctor: reveal the stored Degiro credentials.

⚠️  Prints your username + TOTP SETUP KEY (the long-lived base32 secret) to the
terminal. Use to copy it before a reset/reinstall. Anything printed here may be
captured by your terminal scrollback / session transcript — treat the key as
exposed afterward and regenerate it in Degiro if you're cautious.

Reads the same backends the live path does: OS keychain first, then the
bundle-local .env fallback.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))

from sq_secrets import get_secret, load_dotenv          # noqa: E402

SERVICE = "sq-degiro"
ENV_FILE = HERE / ".env"

if __name__ == "__main__":
    load_dotenv(ENV_FILE)
    print("⚠️  These are SECRETS — they will be in your terminal scrollback.\n")
    user = get_secret(SERVICE, "username",    "DEGIRO_USERNAME")
    pwd  = get_secret(SERVICE, "password",    "DEGIRO_PASSWORD")
    totp = get_secret(SERVICE, "totp_secret", "DEGIRO_TOTP_SECRET")
    print(f"  username:        {user or '(not set)'}")
    print(f"  password:        {'•' * len(pwd) if pwd else '(not set)'}  "
          f"({'set' if pwd else 'missing'})")
    print(f"  totp setup key:  {totp or '(not set — SMS/none, or unset)'}")
    print("\n  Re-enter the setup key at:  sciqnt degiro setup")
