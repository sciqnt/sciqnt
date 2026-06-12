#!/usr/bin/env python3
"""sq_degiro.history_sync — refresh the CSV history straight from Degiro.

Downloads the SAME two CSV reports the web UI exports (transactionReport +
cashAccountReport, `lang=en` so the headers match the parser) over the existing
authenticated session, VALIDATES them with the existing cent-perfect parser,
and only then atomically replaces `history_dir(account)`'s files (previous
files kept as `.bak`). This graduates history from the manual-export flavour to
programmatic (P5 flavour preference): `sciqnt degiro sync` — and ^R/--fresh via
the platform's capability hook — now refresh history too.

Safety contract (trust-earned, P17):
  * the download is parsed by `load_history` BEFORE anything is overwritten;
  * a parse yielding nothing, or FEWER transactions than the current files,
    aborts with the existing files untouched;
  * writes are move-into-place with a `.bak` of what was there.

`fetch` is injectable so tests never touch the network."""
import datetime as _dt
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

# The web app's export endpoints (the library wraps cashAccountReport; the
# transactionReport sibling uses the identical param contract).
REPORTS = {
    "transactions.csv":
        "https://trader.degiro.nl/portfolio-reports/secure/v3/transactionReport/csv",
    "account.csv":
        "https://trader.degiro.nl/portfolio-reports/secure/v3/cashAccountReport/csv",
}
_FROM_DATE = _dt.date(2000, 1, 1)        # "everything" — Degiro clamps internally
_REPORT_LANG = "en"                      # English headers = what the parser expects
_REPORT_COUNTRY = "NL"


def _default_fetch(account: Optional[str]) -> Callable[[str], bytes]:
    """Return GET(url)->bytes bound to the SHARED authenticated session
    (sessionId + intAccount as the web app sends them). Reuses the same
    per-account session as the live fetch — a sync must never be an extra
    login (each fresh login fires a Degiro login-alert email)."""
    from sq_degiro import connected_api

    api, int_account = connected_api(account)
    session_id = api.connection_storage.session_id
    # Reuse the connector's OWN configured session (browser-like headers,
    # cookies) — a bare requests.Session gets 503'd by Degiro's WAF (myracloud).
    http = api.session_storage.session

    def get(url: str) -> bytes:
        params = {
            "intAccount": int_account, "sessionId": session_id,
            "country": _REPORT_COUNTRY, "lang": _REPORT_LANG,
            "fromDate": _FROM_DATE.strftime("%d/%m/%Y"),
            "toDate": _dt.date.today().strftime("%d/%m/%Y"),
        }
        r = http.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.content
    return get


def sync_history(account: Optional[str] = None, *,
                 data_dir: Optional[Path] = None,
                 fetch: Optional[Callable[[str], bytes]] = None,
                 max_age_hours: Optional[float] = None) -> dict:
    """Refresh `history_dir(account)` from Degiro. Returns
    `{dir, transactions, ends}` (or `{skipped: True, age_hours}` when
    `max_age_hours` is set and the current files are fresh enough — the
    platform's auto-sync uses that to avoid re-logging-in on every ^R)."""
    from sq_degiro import history_dir, load_history

    target = Path(data_dir) if data_dir is not None else history_dir(account)

    if max_age_hours is not None:
        cur = target / "transactions.csv"
        if cur.is_file():
            age_h = (_dt.datetime.now().timestamp() - cur.stat().st_mtime) / 3600
            if age_h < max_age_hours:
                return {"skipped": True, "age_hours": round(age_h, 2)}

    get = fetch or _default_fetch(account)
    tmp = Path(tempfile.mkdtemp(prefix="sq-degiro-sync-"))
    for fname, url in REPORTS.items():
        (tmp / fname).write_bytes(get(url))

    # Validate with the REAL parser before touching anything.
    new_txns = load_history(data_dir=tmp)
    if not new_txns:
        raise RuntimeError(
            "downloaded reports parsed to no transactions — existing files "
            "left untouched (lang/format drift? check the raw download)")
    old_txns = (load_history(data_dir=target)
                if (target / "transactions.csv").is_file() else None)
    if old_txns and len(new_txns) < len(old_txns):
        raise RuntimeError(
            f"downloaded history has FEWER transactions ({len(new_txns)}) than "
            f"the current files ({len(old_txns)}) — refusing to overwrite")

    target.mkdir(parents=True, exist_ok=True)
    for fname in REPORTS:
        dst = target / fname
        if dst.exists():
            shutil.move(str(dst), str(dst) + ".bak")
        shutil.move(str(tmp / fname), str(dst))

    ends = max(t.executed_at for t in new_txns).date()
    return {"dir": str(target), "transactions": len(new_txns),
            "ends": ends.isoformat()}


def _sync_one(account: Optional[str]) -> str:
    """Sync ONE account and return its human outcome line. 'New rows' is the
    parsed-transaction count delta before/after (each download is the FULL
    history, so total_after − total_before == newly appeared rows)."""
    from sq_degiro import history_dir, load_history

    target = history_dir(account)
    old = (load_history(data_dir=target)
           if (target / "transactions.csv").is_file() else None)
    res = sync_history(account)
    total, ends = res["transactions"], res["ends"]
    if old is None:
        return f"{total} rows synced (through {ends}) → {res['dir']}"
    new = total - len(old)
    if new <= 0:
        return f"up to date ({total} rows, through {ends})"
    return f"{new} new rows (total {total}, through {ends})"


def run_sync(accounts, syncer, *, out=print):
    """The per-account sync loop, split from main() so the contract is
    unit-testable with a stubbed syncer.

    `syncer(account) -> str` describes one account's outcome ("12 new rows
    (total 526, through 2026-06-10)" / "up to date"). CredentialsMissing /
    NeedsAction become a friendly per-account line and the loop CONTINUES —
    one unconfigured account must never block the others. Any other failure
    is one line (`sync failed: <type>: <msg>`), never a traceback.

    Returns `(summary, exit_code)`: summary is the one-line roll-up
    ("AccountA: 12 new rows · AccountB: up to date"); exit_code is 0 iff
    every account synced."""
    from sq_secrets import NeedsAction
    from sq_degiro.live import CredentialsMissing

    fragments, failed = [], 0
    for account in accounts:
        label = account or "default"
        out(f"  {label}: syncing…")
        try:
            outcome = syncer(account)
        except CredentialsMissing as e:
            outcome, failed = str(e), failed + 1
        except NeedsAction as e:
            outcome, failed = f"⚠ {e}", failed + 1
        except Exception as e:                               # noqa: BLE001
            outcome, failed = f"sync failed: {type(e).__name__}: {e}", failed + 1
        out(f"  {label}: {outcome}")
        fragments.append(f"{label}: {outcome}")
    return " · ".join(fragments), (1 if failed else 0)


def main(argv):
    import argparse
    p = argparse.ArgumentParser(
        prog="sq-degiro sync",
        description="refresh transactions.csv + account.csv straight from "
                    "Degiro (replaces the manual web export). With no flags "
                    "it syncs EVERY configured account.")
    p.add_argument("--account", default=None, metavar="NAME",
                   help="sync just this account; omit to sync all "
                        "configured accounts")
    args = p.parse_args(argv)

    if args.account is not None:
        targets = [args.account]
    else:
        try:
            from sq_degiro import accounts as _accounts
            targets = _accounts()
        except Exception:                                    # noqa: BLE001
            targets = []
        if not targets:
            # No registry and no legacy keys detected — still try the legacy
            # path so the friendly CredentialsMissing names the fix (setup).
            targets = [None]

    summary, rc = run_sync(targets, _sync_one)
    print(f"  sync summary — {summary}")
    return rc


if __name__ == "__main__":
    HERE = Path(__file__).resolve()
    sys.path.insert(0, str(HERE.parents[4] / "core"))
    sys.path.insert(0, str(HERE.parents[1]))
    sys.exit(main(sys.argv[1:]))
