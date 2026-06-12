# Connect Experience — the broker-connection UX framework

Why this doc: the connect flow grew feature-by-feature (label prompt → field
prompts → verify → refresh-confirm → history essay → robustness essay) and
accumulated design flaws that defy the principles. This is the reset, grounded
in PRINCIPLES.md (P4 convenience-bounded, P15 sovereignty, P17
trust-through-conformance), research/tui-experience.md (progressive disclosure,
errors in the body, plain language) and research/connector-framework.md
(per-user health state).

## The flaws this fixes (observed live, 2026-06)
1. **No typo recovery** — a wrong username at the password prompt meant exit
   and restart. Sequential one-shot prompts have no "back".
2. **Wrong question order** — "refresh credentials?" asked AFTER a verified
   login (fixed earlier: confirm before verify); account label asked FIRST,
   before the user has typed the username it would default to.
3. **Implementation essays at the wrong moment** — after "✓ connected", the
   user got a 4-line history-export lecture and a 5-line auth-robustness
   lecture. The user's job-to-be-done was "connect"; everything else is
   progressive disclosure (one dim line max, detail lives where it's needed).
4. **Failure surfacing is a debug table** — "skipped (live view degraded)"
   with raw exception strings. Plain user language, one line per account,
   with the ACTION ("reconnect"), not the stack.
5. **No re-auth path** — when a session/token dies at refresh time, nothing
   guides the user back to a working state from where they are.

## Principles applied (the short list)
- **P4** the effortless path and the correct path must be the same path —
  setup is a form, not an interrogation; repair is one keystroke from where
  the failure is shown.
- **P15** credentials stay local (keychain / .env); the verify login becomes
  the session — no throwaway logins, no second device identities.
- **P17** "connected" means VERIFIED against the broker, not "stored".
- **tui-experience**: progressive disclosure (headline now, detail one
  keystroke away); errors live in the body and stay actionable; plain
  user terms (never "session", "token", "WAF", "cookie jar" on screen).

## The connect form (sq_secrets.prompt_and_store)
```
Connect Degiro
  username   AliceExample
  password   ********
  2FA key    (blank)

  enter = connect · 1-3 = edit a field · esc = cancel
```
- Collect all fields, then show a **review screen** (secrets masked). Typo?
  Re-enter just that field. Nothing leaves the machine until the user
  confirms the set. This is the back-navigation primitive — one screen,
  numbered edits — chosen over per-field "back" keys because hidden input
  makes in-field navigation invisible and error-prone.
- **Label resolves silently** from the username (the identity field). No
  upfront label prompt in the platform connect flow. A second account for
  the same broker is the rare case: `--account work` stays available, and
  the review screen shows the derived label so the user sees what it'll be
  called.
- Refresh-vs-new confirm happens at the review (we know the label by then),
  BEFORE the verify login — never after a phone tap.
- After "✓ connected as AliceExample": at most ONE dim follow-up line
  (e.g. "history: account view › ? explains how to power P/L & charts").
  No essays. Upgrade hints (e.g. "a 2FA key makes logins fully automatic")
  are one line, shown only when the login actually needed a human.

## Auth-state model (the NeedsAction contract)
Connectors already raise `CredentialsMissing` (not configured). The second
state: configured but **needs the user** (expired token, revoked session,
in-app approval while unattended, SMS challenge…).

```python
class NeedsAction(RuntimeError):
    """The broker needs the user to do something before data can flow.
    `action`  — machine hint: "reconnect" | "approve" | "wait"
    str(self) — ONE plain-language line, user-facing, names what to do."""
    def __init__(self, message, *, action="reconnect"): ...
```
Lives in `sq_secrets` (the auth substrate every bundle already imports).
Bundles translate their broker's failure dialect into it; the platform
translates it into UI. Nothing else flows through (P16: the gate is code).

## Health surfacing (the home + portfolio views)
Per connector-framework §3, health is per-user, dynamic state. The aggregate
already carries it (`BrokerSnapshot.ok/error`); the UI rule:

- **Account rows stay in the list** when they fail — a failing account is a
  fact about the portfolio, not a footnote. Value column shows "—".
- Under the table, one dim line per problem, plain language + action:
  `⚠ degiro:AliceExample needs you — approve the login in the DEGIRO app (^R to retry)`
  `⚠ robinhood:dave isn't connected — Connect to Broker Account › robinhood`
  Raw exception text NEVER reaches the screen; unknown errors render as
  "couldn't fetch (<ExcName>) — ^R to retry" with the detail in ? help.
- **Severity**: missing-creds and needs-action are ⚠ (user-fixable, yellow);
  transient fetch errors are dim (retryable); nothing is red unless the
  money math itself is compromised (that never degrades silently — P17).
- The mapping lives in ONE place (`_account_problem(broker_result)`) so the
  home view, the portfolio view and the CLI dump all say the same words.

## Re-auth at refresh time
When a fetch raises NeedsAction mid-session:
- the TUI shows the ⚠ line as above (the data stays on the last good cache —
  stale-while-revalidate already does this);
- "approve"-type actions self-resolve on retry (^R) once the user has acted —
  the degiro in-app poll already blocks-with-countdown when interactive;
- "reconnect"-type actions point at the Connect screen, which is the SAME
  form as first-time setup (refresh-vs-new guard already distinguishes).
No bespoke re-auth screens: the form IS the repair tool (P4 — one path).

## Device trust (honesty note)
Degiro's "remember this device for 30 days" is cookie-carried; we persist the
jar, but live evidence (2026-06) is that the popup still re-fires on fresh
logins, so the UI must NOT promise 30 days. The popup prompt says only what
to do now. If the trust cookie helps, the user simply sees fewer popups; the
session reuse (one login per sitting) is what does the real work. TOTP setup
key remains the only no-human-ever path — that's the one-line upgrade hint.

## Out of scope (deliberate)
- Capability grants/caps UI (P16) — comes with the first write capability.
- Encrypted-at-rest session store — keychain already covers secrets; session
  files are 0600 short-lived bearer state.
- A full prompt_toolkit form widget — the review-screen pattern gives typo
  recovery without building a TUI forms framework (resist over-engineering).
