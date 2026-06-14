"""sq-secrets — shared credential substrate (NOT a connector).

Generic, cross-cutting: prompt for a secret via a native hidden dialog and store
it in the OS keychain; read it back keychain-first with an env/.env fallback.
Used by any credentialed unit (Degiro live, future brokers/data APIs). The secret
goes dialog -> keychain only; it is never printed, so it can't enter a transcript.

Cross-OS via `keyring` (macOS Keychain / Linux Secret Service / Windows Cred Mgr).
The prompt uses a native macOS dialog (osascript) with a getpass TTY fallback.
"""
import os
import subprocess
import sys
from pathlib import Path

import importlib.util

# Pure formatting tokens come from the zero-dependency sq_fmt leaf, so importing
# sq_secrets stays prompt-toolkit-free (the headless credential path: keychain +
# env, no prompt). The THEMED interactive prompts live in sq_tui and are imported
# lazily, only when we actually prompt at a TTY — keeping the design one-source
# (credential prompts match the dispatcher menus) without the import-time weight.
from sq_fmt import BOLD, DIM, RST, err, ok  # noqa: F401

_HAS_Q = importlib.util.find_spec("questionary") is not None


class NeedsAction(RuntimeError):
    """The broker needs the USER to do something before data can flow —
    expired/revoked session, in-app approval while unattended, SMS challenge.
    Distinct from CredentialsMissing (not configured at all). Bundles
    translate their broker's failure dialect into this; the platform
    translates it into one plain ⚠ line with the action. str(self) must be
    a single plain-language sentence naming what to do (no jargon).

    action: machine hint — "approve" (self-resolves on retry once the user
    acts) | "reconnect" (point at the Connect screen) | "wait" (transient)."""

    def __init__(self, message, *, action="reconnect"):
        super().__init__(message)
        self.action = action


def _osascript_prompt(label, hidden):
    hid = " with hidden answer" if hidden else ""
    script = (f'text returned of (display dialog "{label}" default answer "" '
              f'with title "sciqnt secret setup"{hid})')
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except subprocess.CalledProcessError:
        return None  # user cancelled


def prompt_terminal(label, hidden=False):
    """In-terminal input. Themed via sq_tui when available + TTY (cyan accent,
    bold question, masked password); otherwise stdlib getpass/input fallback.
    Returns None on EOF/Ctrl-C so callers treat it as cancel."""
    if _HAS_Q and sys.stdin.isatty():
        import sq_tui  # lazy: questionary only when actually prompting at a TTY
        try:
            q = sq_tui.themed_password(label) if hidden else sq_tui.themed_text(label)
            v = q.ask()
        except KeyboardInterrupt:
            return None
        return v.strip() if v else None
    import getpass
    try:
        v = getpass.getpass(label + ": ") if hidden else input(label + ": ")
        return v.strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def prompt(label, hidden=False, mode=None):
    """mode: 'terminal' -> getpass/input (TUI, principle 5 default);
            'gui'      -> native macOS dialog (osascript);
            None/'auto' -> 'terminal' if stdin is a TTY else 'gui' on darwin."""
    if mode in (None, "auto"):
        if sys.stdin.isatty():
            mode = "terminal"
        else:
            mode = "gui" if sys.platform == "darwin" else "terminal"
    if mode == "gui" and sys.platform == "darwin":
        return _osascript_prompt(label, hidden)
    return prompt_terminal(label, hidden)


def select_mode():
    """Selector — returns 'terminal' or 'gui'. Default 'terminal' (principle 5,
    works everywhere). Skipped when no TTY or non-mac. Uses sq_tui themed
    select when available; numbered-menu fallback otherwise."""
    if not sys.stdin.isatty() or sys.platform != "darwin":
        return "terminal"
    if _HAS_Q:
        import sq_tui  # lazy: questionary only when actually prompting at a TTY
        try:
            r = sq_tui.themed_select(
                "How would you like to enter values?",
                choices=[
                    sq_tui.Choice(
                        "Terminal — hidden input (recommended, works over SSH)",
                        value="terminal", checked=True),
                    sq_tui.Choice(
                        "macOS dialog — GUI popup", value="gui"),
                ],
            ).ask()
            return r or "terminal"
        except KeyboardInterrupt:
            return "terminal"
    # fallback: numbered menu
    print()
    print("How would you like to enter values?")
    print("  1) Terminal — hidden input (recommended, works over SSH)")
    print("  2) macOS dialog — GUI popup")
    try:
        choice = input("Choice [1]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "terminal"
    return "gui" if choice == "2" else "terminal"


def _write_env_var(env_path, var, value):
    """Append/update VAR=value in a local .env file (0600 perms). Preserves
    existing keys; doesn't print the value. Used as a fallback when the OS
    keychain refuses writes (notably SSH sessions on macOS — error -25308)."""
    import pathlib
    p = pathlib.Path(env_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    pairs = []
    seen = False
    if p.exists():
        for line in p.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                pairs.append(line)
                continue
            k, _, _ = s.partition("=")
            if k.strip() == var:
                pairs.append(f"{var}={value}")
                seen = True
            else:
                pairs.append(line)
    if not seen:
        pairs.append(f"{var}={value}")
    p.write_text("\n".join(pairs) + "\n")
    try:
        p.chmod(0o600)
    except Exception:
        pass


def _delete_env_var(env_path, var) -> bool:
    """Remove the `VAR=…` line from a local .env file (preserving the rest).
    Returns True if a line was removed. The symmetric inverse of
    `_write_env_var` — used by a bundle's `forget` flow to scrub the .env
    fallback when an account is deleted. Silent (False) if the file or the
    var is absent."""
    import pathlib
    p = pathlib.Path(env_path)
    if not p.exists():
        return False
    kept, removed = [], False
    for line in p.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, _ = s.partition("=")
            if k.strip() == var:
                removed = True
                continue
        kept.append(line)
    if not removed:
        return False
    p.write_text(("\n".join(kept) + "\n") if kept else "")
    try:
        p.chmod(0o600)
    except Exception:
        pass
    return True


def _qualified_key(key, account):
    """Compose the keychain key for a (key, account) pair.
    `account=None` → bare key (the legacy single-account form; preserved
    so existing users' stored creds keep working unchanged). Otherwise
    `<account>:<key>` so two Degiro accounts (say "primary" and "work")
    can coexist under the same `sq-degiro` service.
    The same qualifier feeds the env-var convention: `KEY` → `KEY_<ACCOUNT>`."""
    if not account:
        return key
    return f"{account}:{key}"


def _qualified_env_var(env_var, account):
    if not env_var or not account:
        return env_var
    safe = "".join(c.upper() if c.isalnum() else "_" for c in account)
    return f"{env_var}_{safe}"


def store_secret(service, key, value, env_var=None, env_path=None, *,
                 account=None):
    """Try the OS keychain; on failure (e.g. macOS SSH -25308), fall back to a
    local .env at env_path using env_var as the variable name. Returns the
    backend tag actually used: 'keychain' or 'env_file'.

    `account` (optional): when set, qualifies the keychain key + env-var
    name with the account label so multiple accounts on the same service
    can coexist. `account=None` keeps the legacy single-account scheme
    (bare key) so existing users' stored creds keep working unchanged."""
    key_q = _qualified_key(key, account)
    env_q = _qualified_env_var(env_var, account)
    try:
        import keyring
        keyring.set_password(service, key_q, value)
        return "keychain"
    except Exception:
        if env_path and env_q:
            _write_env_var(env_path, env_q, value)
            return "env_file"
        raise


def delete_secret(service, key, *, account=None) -> bool:
    """Remove a stored secret from the OS keychain. Returns True if a value
    was deleted, False if absent / no keychain. Symmetric with store_secret;
    used by `sciqnt reset`. The .env fallback isn't touched here — callers
    that reset typically delete the whole .env file."""
    key_q = _qualified_key(key, account)
    try:
        import keyring
        keyring.delete_password(service, key_q)
        return True
    except Exception:
        return False


def get_secret(service, key, env_var=None, *, account=None):
    """Keychain first; then a named env var (populated from .env if loaded).

    `account` (optional): see `store_secret`. With `account=None` reads
    the bare key (legacy / single-account); with `account="<name>"` reads
    the qualified key `<name>:<key>` and the qualified env var
    `<ENV_VAR>_<NAME>`."""
    key_q = _qualified_key(key, account)
    env_q = _qualified_env_var(env_var, account)
    try:
        import keyring
        v = keyring.get_password(service, key_q)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(env_q) if env_q else None


# ── account registry ─────────────────────────────────────────────────────
def account_label_from(identity: str) -> str:
    """Turn an identity value (username / key id / wallet) into a tidy account
    label — used when a setup defaults the account name to e.g. the username.
    Keeps it readable but safe for keychain keys + cache filenames: strip, drop
    a leading 0x, keep alnum / _ / - / . / @, collapse the rest to '-', and
    cap the length (a 0x wallet → its first 10 chars)."""
    import re
    s = (identity or "").strip()
    if s.lower().startswith("0x") and len(s) > 12:
        return s[:10]                       # wallet address → short, recognisable
    s = re.sub(r"[^A-Za-z0-9_.@-]+", "-", s).strip("-")
    return s[:48] or "account"


def _accounts_path(service):
    """Per-service config file listing the user's configured account names.
    Lives under XDG_CONFIG_HOME (or ~/.config) — separate from the
    keychain so we can enumerate without OS-specific search APIs."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sciqnt" / f"accounts.{service}.json"


def list_accounts(service):
    """Return the user's configured account names for `service`. Empty
    list means "no named accounts registered" — most likely a legacy
    single-account user; the dispatcher treats that as account=None
    (bare keys)."""
    p = _accounts_path(service)
    if not p.is_file():
        return []
    try:
        import json
        data = json.loads(p.read_text())
        names = data.get("accounts") if isinstance(data, dict) else data
        if not isinstance(names, list):
            return []
        return [n for n in names if isinstance(n, str) and n]
    except Exception:
        return []


def register_account(service, name):
    """Add `name` to the configured-account list for `service` (idempotent).
    Called by each bundle's `setup --account NAME` path AFTER credentials
    have been verified + stored — never registers a name whose creds
    aren't there to back it up."""
    if not name or not isinstance(name, str):
        raise ValueError("account name must be a non-empty string")
    existing = list_accounts(service)
    if name in existing:
        return existing
    new = existing + [name]
    p = _accounts_path(service)
    p.parent.mkdir(parents=True, exist_ok=True)
    import json
    p.write_text(json.dumps({"accounts": new}, indent=2) + "\n")
    return new


def unregister_account(service, name):
    """Remove `name` from the configured-account list for `service`
    (silent no-op when absent). Does NOT delete the underlying
    keychain entries — that's a separate concern, e.g. for a future
    `setup --remove --account NAME` flow."""
    existing = list_accounts(service)
    if name not in existing:
        return existing
    new = [n for n in existing if n != name]
    p = _accounts_path(service)
    if not new:
        try:
            p.unlink()
        except OSError:
            pass
        return []
    import json
    p.write_text(json.dumps({"accounts": new}, indent=2) + "\n")
    return new


def clear_accounts(service) -> None:
    """Delete the whole account registry file for `service` (used by
    `sciqnt reset`). Silent if absent."""
    try:
        _accounts_path(service).unlink()
    except OSError:
        pass


def forget_account(service, account, keys, *, env_path=None) -> dict:
    """Remove a connected account end-to-end — the symmetric inverse of the
    store side (`store_secret` + `register_account`). The reusable mechanism
    behind every bundle's `forget` command:

      1. delete each account-qualified keychain secret in `keys`
      2. scrub the matching `.env` fallback lines (when `env_path` given)
      3. drop the persisted broker session
      4. unregister the account name from the registry

    `keys` is a list of `(keychain_key, env_var)` pairs — a bundle's
    credential manifest (`CREDENTIAL_KEYS`); `env_var` may be None for a
    keychain-only secret. `account=None` is the legacy single-account form
    (bare keys); a named account uses the `<account>:<key>` /
    `<ENV_VAR>_<ACCOUNT>` qualifiers throughout. Never raises (a partial
    backend — no keyring, no .env — just leaves that step a no-op); returns
    a small report of what was actually removed so the caller can be honest
    about it."""
    removed_keychain, removed_env = [], []
    for entry in keys:
        key, env_var = (entry if isinstance(entry, (tuple, list))
                        else (entry, None))
        if delete_secret(service, key, account=account):
            removed_keychain.append(key)
        if env_path and env_var:
            if _delete_env_var(env_path, _qualified_env_var(env_var, account)):
                removed_env.append(env_var)
    clear_session(service, account)
    if account is not None:
        unregister_account(service, account)
    return {"service": service, "account": account,
            "keychain": removed_keychain, "env": removed_env}


def prompt_and_store(service, fields, env_path=None, mode=None, verify=None,
                     *, account=None, default_account_from=None,
                     title=None, note=None, on_success=None, review=False):
    """The shared connect-an-account flow — ONE consistent UI across every
    broker (degiro, kalshi, polymarket, robinhood, …). Header → prompts →
    green ✓ verified → silent store → green ✓ connected. Implementation
    noise (which backend, per-field confirmations, registry bookkeeping) is
    deliberately kept off-screen; only what the user needs is shown.

    fields: list of {key, label, hidden(bool), required(bool), env(str),
        normalize(callable), validate(callable)}.
    title:  clean header, e.g. "Connect Degiro" (optional).
    note:   one dim context line under the header (optional).
    mode:   'terminal'|'gui'|None — None lets the component pick (select_mode).
    verify(values)->bool: optional 'test login' run BEFORE anything is stored;
        False/raise → nothing persisted (trust-earned-through-conformance, P17).
    account / default_account_from: see store_secret + account_label_from — a
        blank account is named after the identity field (e.g. username).
    on_success(account_label): optional bundle hook called after everything is
        stored, with the RESOLVED account label (post-derivation) — e.g. to
        prepare the account's history dir + print where exports belong.
    review=True: show a review/edit screen after collection (typo recovery —
        research/connect-experience.md). Opt-in by the interactive setup
        entrypoints; programmatic/non-interactive callers keep the plain flow.
    Secrets are never printed. Returns the list of stored (key, backend)."""
    if title:
        print(f"\n  {BOLD}{title}{RST}")
    if note:
        print(f"  {DIM}{note}{RST}")
    if mode is None:
        mode = select_mode()
    print()

    # phase 1 — collect all values into memory; nothing persisted yet.
    values = {}

    def _ask(f, *, editing=False):
        """Prompt one field. Bad format re-asks (a typo must never kill the
        flow). Blank: keeps the current value when editing, skips an optional
        field, cancels a required first entry. Returns False on cancel."""
        while True:
            val = prompt(f["label"], hidden=f.get("hidden", False), mode=mode)
            if not val:
                if editing and f["key"] in values:
                    return True                     # blank = keep as-is
                if not f.get("required", True):
                    values.pop(f["key"], None)
                    return True
                return False                        # blank required = cancel
            norm = f.get("normalize")
            if norm:
                val = norm(val)
            validate = f.get("validate")
            if validate and not validate(val):
                err("that doesn't look right — try again "
                           "(blank to cancel)")
                continue
            values[f["key"]] = val
            return True

    for f in fields:
        if not _ask(f):
            err("cancelled — nothing stored.")
            sys.exit(1)

    def _label():
        if account is not None:
            return account
        ident = (values.get(default_account_from)
                 if default_account_from else None)
        return account_label_from(ident) if ident else None

    # phase 1.5 — review & edit BEFORE anything leaves the machine: secrets
    # masked, the derived account name visible, typos fixable per field —
    # never exit-and-restart. Confirming here also covers refresh-vs-new
    # (the note names it), so no separate y/N question and never AFTER an
    # expensive verify (a real login — maybe a tap on the user's phone).
    interactive = review and mode == "terminal" and sys.stdin.isatty()
    while interactive:
        print()
        for i, f in enumerate(fields, 1):
            v = values.get(f["key"])
            shown = ("········" if f.get("hidden") and v else (v or "—"))
            name = f["label"].split("(")[0].split(",")[0].strip()
            print(f"  {i}) {name:24s} {shown}")
        label = _label()
        if label:
            extra = (" — already connected; this refreshes its credentials"
                     if label in list_accounts(service) else "")
            print(f"  {DIM}   account name{' ' * 13}{label}{extra}"
                  f"{RST}")
        try:
            ans = input(f"\n  enter connect · 1-{len(fields)} edit · "
                        f"q cancel: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "q"
        if ans == "":
            break
        if ans in ("q", "esc"):
            err("cancelled — nothing stored.")
            sys.exit(1)
        if ans.isdigit() and 1 <= int(ans) <= len(fields):
            _ask(fields[int(ans) - 1], editing=True)
        # anything else → just redisplay the review

    account = _label()

    # phase 1.6 — non-interactive fallback for the refresh-vs-new guard
    # (interactive runs covered it in the review note above).
    if not interactive and account and account in list_accounts(service):
        broker = service.replace("sq-", "", 1)
        print(f"\n  {DIM}'{account}' is already connected to {broker}. "
              f"This refreshes its stored credentials — it does NOT create a "
              f"second account.{RST}")
        try:
            ans = input("  refresh its credentials? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            err("cancelled — existing credentials left unchanged.")
            sys.exit(1)

    # phase 2 — verify with the service before persisting (if a verifier exists)
    if verify is not None:
        print(f"  {DIM}verifying…{RST}")
        try:
            verified = verify(values)
        except Exception as e:
            err(f"verification failed: {type(e).__name__}: {e}")
            sys.exit(1)
        if not verified:
            err("verification failed — nothing stored.")
            sys.exit(1)
        ok("verified")

    # phase 3 — store (silently; only after verify passed)
    stored = []
    for f in fields:
        if f["key"] not in values:
            continue
        backend = store_secret(service, f["key"], values[f["key"]],
                               env_var=f.get("env"), env_path=env_path,
                               account=account)
        stored.append((f["key"], backend))

    # phase 4 — register so list_accounts(service) sees the account.
    if account:
        register_account(service, account)

    ok(f"connected as {account}" if account
              else f"connected to {service.replace('sq-', '', 1)}")
    # Optional bundle hook with the RESOLVED account label (it may have been
    # derived from an identity field) — e.g. degiro prepares the per-account
    # history dir + tells the user where CSV exports belong. Best-effort.
    if on_success is not None:
        try:
            on_success(account)
        except Exception:                                   # noqa: BLE001
            pass
    return stored


def load_dotenv(path):
    """Minimal stdlib .env loader (no python-dotenv dep). Populates os.environ."""
    import pathlib
    p = pathlib.Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── Broker session persistence (cross-process) ──────────────────────────
# Why this exists: logging in fresh on every fetch makes each request look
# like a NEW device/browser to the broker — the user gets a login-alert /
# "new device" email on every refresh. Persisting the broker session
# (session id / OAuth token / device token) and reusing it until it actually
# expires makes sciqnt look like ONE long-lived device. Session tokens are
# bearer secrets → directory 0700, files 0600, never printed, gitignored by
# virtue of living under the config home (not the repo).
#
# The store keys off the config home (sq_config.path().parent), so the
# SQ_CONFIG_PATH test override redirects sessions too — tests never touch
# ~/.config/sciqnt.

def session_dir(service, account=None):
    """Per-service session directory: <config-home>/sessions/<service>[/<account>].
    Created on demand with 0700 (tokens inside are bearer credentials)."""
    import re as _re
    import sq_config
    d = sq_config.path().parent / "sessions" / service
    if account:
        d = d / _re.sub(r"[^A-Za-z0-9._-]", "_", str(account))
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def load_session(service, account=None):
    """The persisted session dict for (service, account), or None. Corrupt
    files are treated as absent (caller falls through to a fresh login)."""
    import json
    p = session_dir(service, account) / "session.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def save_session(service, data, account=None):
    """Persist a session dict (0600 — it's a bearer credential)."""
    import json
    p = session_dir(service, account) / "session.json"
    p.write_text(json.dumps(data))
    p.chmod(0o600)


def clear_session(service, account=None):
    """Drop the persisted session (e.g. after the broker rejected it)."""
    p = session_dir(service, account) / "session.json"
    p.unlink(missing_ok=True)
