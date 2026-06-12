#!/usr/bin/env python3
"""sq-degiro doctor — read-only health check, one block per configured account.

No network, no prompts, nothing stored. For each configured account (plus the
legacy unnamed one when bare keychain keys / .env vars exist) it reports:

  * credentials  — username/password present (and where: keychain or .env)?
                   TOTP setup key stored, or is this an in-app-approval login?
  * session      — persisted Degiro session present + age (Degiro expires
                   them server-side after ~30 min idle; "likely expired" just
                   means the next fetch performs one fresh login)
  * history CSVs — transactions.csv/account.csv present + export age
                   (>7 days stale → `sciqnt degiro sync`)

`sciqnt degiro doctor probe|fix-totp|show-creds` remain the deeper diagnostics
for when login itself is broken.
"""
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE / "src"))

import sq_secrets                                                  # noqa: E402
from sq_degiro import SERVICE, accounts, history_dir               # noqa: E402

ENV_FILE = HERE / ".env"

OK, WARN, BAD = "✓", "⚠", "✗"

_ENV_VARS = {"username": "DEGIRO_USERNAME", "password": "DEGIRO_PASSWORD",
             "totp_secret": "DEGIRO_TOTP_SECRET"}


def _cred_source(key, account):
    """'keychain' / '.env' / None for one credential field — mirrors
    sq_secrets.get_secret's lookup order, but reports WHERE it lives."""
    try:
        import keyring
        if keyring.get_password(SERVICE, sq_secrets._qualified_key(key, account)):
            return "keychain"
    except Exception:                                       # noqa: BLE001
        pass
    var = sq_secrets._qualified_env_var(_ENV_VARS[key], account)
    return ".env" if (var and os.environ.get(var)) else None


def _fmt_age(seconds):
    if seconds < 90 * 60:
        return f"{int(seconds // 60)} min ago"
    if seconds < 48 * 3600:
        return f"{seconds / 3600:.0f} h ago"
    return f"{seconds / 86400:.0f} days ago"


def check_account(account):
    """Health rows for one account: [(mark, topic, detail)]. Pure inspection
    — reads keychain/env/files, never the network."""
    rows = []

    # ── credentials ────────────────────────────────────────────────────
    src = {k: _cred_source(k, account) for k in _ENV_VARS}
    if src["username"] and src["password"]:
        totp = (f"TOTP key ({src['totp_secret']})" if src["totp_secret"]
                else "no TOTP key — logins use the in-app approval popup")
        rows.append((OK, "credentials",
                     f"username + password ({src['username']}); {totp}"))
    else:
        missing = ", ".join(k for k in ("username", "password") if not src[k])
        label = f" --account {account}" if account else ""
        rows.append((BAD, "credentials",
                     f"missing {missing} — run: sciqnt degiro setup{label}"))

    # ── persisted session ──────────────────────────────────────────────
    sess = sq_secrets.session_dir(SERVICE, account=account) / "session.json"
    if sess.is_file():
        age = time.time() - sess.stat().st_mtime
        note = ("" if age < 30 * 60
                else " (likely expired — next fetch logs in once)")
        rows.append((OK, "session", f"persisted {_fmt_age(age)}{note}"))
    else:
        rows.append((WARN, "session",
                     "none persisted — next fetch performs a fresh login"))

    # ── history CSV exports ────────────────────────────────────────────
    d = history_dir(account)
    tx, ac = d / "transactions.csv", d / "account.csv"
    if tx.is_file() and ac.is_file():
        age = time.time() - tx.stat().st_mtime
        if age > 7 * 86400:
            rows.append((WARN, "history CSVs",
                         f"export {_fmt_age(age)} ({d}) — refresh with: "
                         "sciqnt degiro sync"))
        else:
            rows.append((OK, "history CSVs", f"synced {_fmt_age(age)} ({d})"))
    else:
        rows.append((WARN, "history CSVs",
                     f"missing at {d} — fetch with: sciqnt degiro sync"))
    return rows


def main():
    sq_secrets.load_dotenv(ENV_FILE)
    try:
        accts = accounts()
    except Exception as e:                                  # noqa: BLE001
        sys.exit(f"doctor failed: {type(e).__name__}: {e}")

    if not accts:
        print("no Degiro account configured — connect one with: "
              "sciqnt degiro setup")
        print("(login already failing? deeper tools: "
              "sciqnt degiro doctor probe | fix-totp)")
        return 0

    print("degiro doctor — read-only health check (no network, no prompts)\n")
    any_bad = False
    for a in accts:
        print(f"account: {a or 'default (legacy unnamed keys)'}")
        for mark, topic, detail in check_account(a):
            print(f"  {mark} {topic:<13} {detail}")
            any_bad |= (mark == BAD)
        print()
    print("login broken? deeper tools: sciqnt degiro doctor probe | fix-totp")
    return 1 if any_bad else 0


if __name__ == "__main__":
    sys.exit(main())
