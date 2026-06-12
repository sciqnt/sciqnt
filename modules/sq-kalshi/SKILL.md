---
name: sq-kalshi
description: Read a Kalshi account — open event-contract positions and USD cash via the official v2 REST API (RSA-PSS signed, read-only), with best-effort mark-to-market from the public markets feed. Use when someone holds Kalshi prediction-market contracts and wants them in the canonical cross-asset portfolio.
---

# sq-kalshi — Kalshi source unit

A **source** unit (data in). Flavour: **api** (official Kalshi v2 REST, not reverse-engineered). Read-only — no execution. First `AssetClass.EVENT` connector; USD-base.

## When to use
The user holds Kalshi event contracts and wants live positions + cash in the same canonical schema as their brokers. Status: fixture-tested adapter against the documented API; **pending a first real-credentials run** (declared in manifest.yaml).

## Setup (once)
```bash
bin/sq-kalshi setup     # stores API key id + RSA private key (keychain/.env, verified)
```
Auth is RSA-PSS request signing (`KALSHI-ACCESS-KEY` / `-SIGNATURE` / `-TIMESTAMP` headers, Unix-ms timestamp, path including the `/trade-api/v2` prefix). Credentials live local-only via `sq_secrets`; a missing credential raises `CredentialsMissing` (the aggregated view degrades just this broker, never crashes).

## How to use
```bash
bin/sq-kalshi live      # open event contracts + cash
```
Or import: `from sq_kalshi import snapshot; snap = snapshot()` → a canonical `PortfolioSnapshot` (EVENT positions + USD cash). `accounts()` lists configured accounts.

## How to read the output
- Each contract is an EVENT position: `terms.outcome` is "YES"/"NO" (mapped from the SIGN of Kalshi's `position_fp`), `quantity` is the contract count.
- Prices are **probabilities in [0,1]** (Kalshi quotes cents → /100; conformance enforces the band).
- Mark-to-market is a **best-effort overlay** from the PUBLIC `/markets` endpoint (no auth): YES values at `yes_prob`, NO at `1 − yes_prob`. Unpriced/unreachable markets stay cost-only (`value_base = 0`) — fixture-proven, not yet observed against a live-priced market.

## What it does NOT do
- No transaction history / no `asof` — `/portfolio/settlements` isn't folded into a canonical Transaction ledger yet, so no TWR/drawdown for Kalshi.
- No execution (read-only; execution is a separate, higher trust tier).

## Caveats & quirks
**Read `FINDINGS.md`** — the living log: fixed-point `_dollars`/`_fp` string fields (the cent-integer fields are deprecated), signed `position_fp`, no spot price in the positions payload, demo vs prod hosts. Update it whenever you learn something new.
