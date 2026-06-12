# Trading 212 + IBKR Flex — verified API facts (build-ready, awaiting accounts)

Status: verified 2026-06-11 against official docs (the morning deep-research
pass had these claims die on verifier rate-limits, not refutation — re-checked
directly). **Neither connector is BUILT**: the money-core rule (never implement
a fold against payloads you can't verify) requires a real account for the
conformance run. This note is the build-ready spec so the day an account
exists — owner's or a contributor's — the bundle is a one-session job.

## Trading 212 (the EU-retail complement to Degiro)

Verified from docs.trading212.com:
- **Read path is complete** for our canonical needs:
  - `GET /api/v0/equity/positions` — all open positions (qty, average price,
    P/L) — rate limit **1 req/s**.
  - `GET /api/v0/equity/history/orders` · `/history/dividends` ·
    `/history/transactions` — each **6 req/min**. Dividends as first-class
    events (no inference needed) and cash transactions = the XIRR flows.
  - Async CSV exports: `POST /api/v0/equity/history/exports` (1 req/30s) →
    poll `GET …/exports` (1 req/min) → `downloadLink` when Finished. A
    second, file-flavour path for full-history backfills.
- **Constraints:** enabled for **Invest and Stocks ISA accounts only** (not
  CFD); **multi-currency accounts unsupported** — everything reports in the
  primary account currency; **orders CAN be placed** through the API.
- **Sovereignty note:** because the API supports execution, treat the key as
  a trading credential — store via sq_secrets like broker passwords, and the
  connector must declare `risk_tier: read` while WARNING that the underlying
  key may be execution-capable (check whether T212 offers scoped keys at
  build time — unverified).
- Unverified (page didn't state): API version/beta status, auth header
  format, pagination scheme for history endpoints. Pin at build time.

## IBKR — Flex Web Service (the right path; Client Portal API is not)

Verified 3-0 in the morning pass (campus page now 403s scripted fetches):
- The **Flex Web Service** is a standalone HTTP API that generates and
  retrieves pre-configured Flex Query reports (built once in Client Portal).
  Activity reports include trades, cash transactions, dividends, positions —
  the full canonical read set.
- **Auth = token + query ID only; IB credentials are never in the API call**
  — the cleanest local-first fit of any broker we've assessed.
- The Client Portal API alternative is NOT suitable for unattended local
  refresh (Java gateway + browser login + short sessions — claims died
  unverified on rate limits; the direction was consistent across sources).
  Don't revisit unless Flex proves insufficient.
- Build shape: `sq-ibkr-flex` bundle, file-ish flavour (fetch XML/CSV report
  → canonical adapter), `SendRequest` → `GetStatement` two-step. Needs a
  funded IBKR account for the conformance run.

## Decision

Both stay in the backlog until an account exists to verify against. The
connector-generator model (PRINCIPLES: platform ships contract + harness,
users build the long tail) is the intended path for both — this note is the
input a generator run would start from.
