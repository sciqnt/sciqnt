#!/usr/bin/env python3
"""sciqnt reset — wipe stored credentials + cached state to return to a clean
first-run install (e.g. to re-test the connect flow, or hand the machine on).

What it removes:
  • keychain credentials for each broker (every key the bundle declares in
    SECRET_KEYS, bare + per registered account)
  • the account registry (~/.config/sciqnt/accounts.<service>.json)
  • the bundle .env credential fallbacks (modules/sq-*/.env)
  • the cache (~/.cache/sciqnt — snapshots, metadata, FX, OpenFIGI)

What it KEEPS (your sovereign data — never auto-deleted):
  • CSV exports under data/ (transaction history). Pass --include-data to
    also wipe those.

Scope: `sciqnt reset` wipes everything; `sciqnt reset <broker>` wipes one
broker. Confirms first unless --yes.
"""
import argparse
import importlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
for _b in (ROOT / "modules").glob("sq-*"):
    if (_b / "src").is_dir():
        sys.path.insert(0, str(_b / "src"))

import sq_secrets                                                    # noqa: E402

CACHE_DIR = Path.home() / ".cache" / "sciqnt"


def _secret_bundles(scope=None):
    """Discover broker bundles declaring SERVICE + SECRET_KEYS (their own
    secret surface — the reset never hard-codes which keys a bundle stores)."""
    out = []
    for bundle in sorted((ROOT / "modules").glob("sq-*")):
        name = bundle.name.replace("sq-", "", 1)
        if scope and name != scope:
            continue
        mod_name = "sq_" + name.replace("-", "_")
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        svc = getattr(mod, "SERVICE", None)
        keys = getattr(mod, "SECRET_KEYS", None)
        if svc and keys:
            out.append((name, svc, list(keys), bundle))
    return out


def _wipe_bundle(name, service, keys, bundle):
    removed = 0
    accts = sq_secrets.list_accounts(service)
    for key in keys:
        if sq_secrets.delete_secret(service, key):              # bare / legacy
            removed += 1
        for acct in accts:
            if sq_secrets.delete_secret(service, key, account=acct):
                removed += 1
    sq_secrets.clear_accounts(service)
    env = bundle / ".env"
    env_removed = False
    if env.exists():
        try:
            env.unlink()
            env_removed = True
        except OSError:
            pass
    print(f"  {name}: removed {removed} keychain item(s)"
          + (", cleared account registry" if accts else "")
          + (", deleted .env" if env_removed else ""))


def main():
    p = argparse.ArgumentParser(prog="sciqnt reset",
                                description="wipe stored credentials + caches")
    p.add_argument("broker", nargs="?", default=None,
                   help="limit the reset to one broker (e.g. degiro). "
                        "Omit to reset everything.")
    p.add_argument("--yes", "-y", action="store_true",
                   help="skip the confirmation prompt")
    p.add_argument("--include-data", action="store_true",
                   help="ALSO delete CSV exports under data/ (your sovereign "
                        "transaction history — kept by default)")
    args = p.parse_args()

    bundles = _secret_bundles(scope=args.broker)
    if args.broker and not bundles:
        print(f"unknown broker '{args.broker}' (or it stores no credentials)")
        return 1

    scope = args.broker or "ALL brokers"
    print(f"sciqnt reset — scope: {scope}\n")
    print("  will remove: keychain credentials, account registry, .env files"
          + (", and the shared cache" if not args.broker else ", and cached snapshots"))
    if args.include_data:
        print("  will ALSO DELETE your CSV transaction history under data/")
    else:
        print("  keeps: CSV exports under data/ (use --include-data to wipe)")

    if not args.yes:
        try:
            ans = input("\n  type 'reset' to confirm: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  aborted.")
            return 1
        if ans != "reset":
            print("  aborted.")
            return 1

    print()
    for name, svc, keys, bundle in bundles:
        _wipe_bundle(name, svc, keys, bundle)

    # Caches: full reset clears the whole dir; scoped clears that broker's files.
    if not args.broker:
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR, ignore_errors=True)
            print("  cache: removed ~/.cache/sciqnt")
    else:
        n = 0
        for pat in (f"snapshot.{args.broker}*.json",
                    f"instrument_metadata.{args.broker}*.json"):
            for f in CACHE_DIR.glob(pat):
                try:
                    f.unlink(); n += 1
                except OSError:
                    pass
        if n:
            print(f"  cache: removed {n} {args.broker} cache file(s)")

    if args.include_data:
        data = ROOT / "data" / (args.broker or "")
        # Scoped → data/<broker>/ ; full → every data/<broker>/ dir.
        targets = [data] if args.broker else [d for d in (ROOT / "data").glob("*") if d.is_dir()]
        for d in targets:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                print(f"  data: removed {d.relative_to(ROOT)}/")

    print("\n  done — run `sciqnt` and Connect an account to set up fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
