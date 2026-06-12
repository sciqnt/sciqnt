# sq_secrets — findings, quirks & conformance notes

Living log for the shared credential substrate. Update the moment anything new is learned.

## Backends
- **macOS Keychain** via `keyring` (`keyring.backends.macOS`). Preferred — encrypted at rest, OS-managed.
- **`.env` file fallback** (0600) — written by `_write_env_var`; used when the keychain refuses writes. Plaintext-on-disk; relies on filesystem perms + FileVault for at-rest security. `live.py` (and any reader) loads it via `load_dotenv` and resolves via `get_secret`'s env-var fallback.

`store_secret` tries keychain first; on any exception, falls back to `.env` if the caller supplied `env_var` + `env_path` — else it re-raises. Backend used is returned (`'keychain'` | `'env_file'`) and printed by `prompt_and_store` so the user knows where their secret landed.

## Quirks
1. **macOS over SSH cannot write to the user's login keychain** (`errSecInteractionNotAllowed`, OSStatus **`-25308`**). `keyring.set_password` raises `PasswordSetError`. This is a real Security-framework restriction: SSH sessions don't have the ACL/UI context needed to surface the keychain-unlock UI, even if the user is logged in on the host console. Discovered 2026-05-29 on the home-server-over-SSH setup. Fix: `.env` fallback (above). **Console sessions are unaffected.**
2. **`osascript` dialogs DO display over SSH** when a user is logged in on the host console — the dialog renders to the console user's WindowServer. So the hidden-prompt UX still works; only the keychain *write* is blocked. (This asymmetry is what surfaced the quirk: dialog → value back → keychain write fails.)
3. **`get_password` over SSH** likely fails for the same reason; `get_secret` swallows the error and falls through to `os.environ`, so a `.env` set by the fallback writer is read transparently. No extra wiring needed.

## Conformance results
- 4 tests on `load_dotenv` + `get_secret` precedence (keychain over env, env fallback).
- 3 tests on `store_secret` backend selection (keychain success; mocked keychain failure → `.env` write at 0600; failure with no fallback re-raises).
- Verified manually 2026-05-29: SSH session on macOS hits `-25308` on real keychain write → the `.env` fallback writes the value, file perms 0600, `live.py` reads it via env fallback.

## Input modes (terminal vs GUI dialog)
`prompt()` accepts `mode='terminal' | 'gui' | None`; `select_mode()` exposes a tiny TUI selector. **Default = terminal when stdin is a TTY** (principle 5: TUI is king + works over SSH). GUI dialog is opt-in on macOS for console sessions. Terminal mode uses `getpass.getpass` (hidden) / `input()` (visible). Cancel/EOF returns `None`. Tested in `core/tests/test_secrets.py`.

## Verify-before-store (trust earned through conformance — P17)
`prompt_and_store(..., verify=callable)` collects every field into memory, calls the verifier (typically a live connect with the entered values), and **stores nothing if verify fails or raises**. So a typo / wrong TOTP key fails at setup time with the real error, instead of being stored silently and exploding next session. Each credentialed connector supplies its own verifier (the platform doesn't know how to "test login" with anyone). For sq-degiro that's `_verify_degiro` (calls `TradingAPI.connect()`). Tested in `core/tests/test_secrets.py` (verify pass → all stored; False → nothing; raise → nothing; no verify → unchanged behaviour).

## `sys.exit` in `prompt_and_store` — DECIDED, not a defect (audit 2026-06-11)
The maintenance audit flagged five `sys.exit(1)` sites in library-looking
code. Verified: `prompt_and_store` is called ONLY from the bundles'
`setup_creds.py` scripts, which run as SUBPROCESSES (the home's connect
flow shells out to `sciqnt <broker> setup`). The exits terminate the
setup subprocess, never the dispatcher — that's CLI-boundary behaviour,
deliberate. The "raise, never sys.exit" rule remains in force for FETCH
paths (`CredentialsMissing` etc.), which is where a SystemExit once
killed the whole aggregated view. If `prompt_and_store` is ever called
in-process, convert the exits to a `SetupCancelled` exception first.

## Open issues / TODO
- [ ] Per-field backend choice (currently per-call; if keychain works for one field, all use it; mixed-mode isn't supported by design).
- [ ] Optional explicit "force backend" flag (`SQ_SECRETS_BACKEND=env_file`) for users who'd rather skip the keychain probe.
- [ ] When keychain backend genuinely works (console session), the first probe still attempts it — that's fine but worth a one-line log.
