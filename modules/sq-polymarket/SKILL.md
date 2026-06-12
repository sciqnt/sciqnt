---
name: sq-polymarket
description: Read a Polymarket portfolio — open event-contract positions via the public Data API (wallet address only, no auth) plus on-chain USDC cash from Polygon. Use when someone holds Polymarket prediction-market positions and wants them in the canonical cross-asset portfolio.
---

# sq-polymarket — Polymarket source unit

A **source** unit (data in). Flavour: **api** (public documented Data API — the read path needs NO credentials, only a wallet address, which is public). Read-only. Second `AssetClass.EVENT` connector; first wallet-based (non-broker) source; USDC-base.

## When to use
The user holds Polymarket positions and wants them aggregated with everything else. The read path is **live-proven against the real public API** (a known trader's 100 positions → 100 canonical EVENT positions, conformance clean).

## Setup (once)
```bash
bin/sq-polymarket setup     # stores the wallet ADDRESS (public, not a secret)
```
**Proxy wallets: use the FUNDER address.** For Magic/browser-wallet logins, positions and USDC live at the profile's funder (proxy) address, NOT the signing EOA.

## How to use
```bash
bin/sq-polymarket live      # open event-contract positions
```
Or import: `from sq_polymarket import snapshot; snap = snapshot()` → canonical `PortfolioSnapshot`. Endpoint: `GET https://data-api.polymarket.com/positions?user=<address>` (no auth; `[]` when empty).

## How to read the output
- Prices (`avgPrice`/`curPrice`) are **already probabilities in [0,1]** — no conversion (contrast Kalshi's cents).
- `outcome` ("Yes"/"No") + market title/slug identify the bet; `currentValue − initialValue` is the unrealised P/L.
- **Cash is read on-chain**: ERC-20 `balanceOf(funder)` on Polygon for native USDC AND bridged USDC.e, summed (stdlib JSON-RPC, public RPCs, `POLYMARKET_RPC` override). Best-effort — on total RPC failure cash is omitted, never fabricated.

## What it does NOT do
- No transaction history / no `asof` — no TWR/realised-P&L for Polymarket yet.
- No trading: the CLOB's EIP-712 L1 + HMAC L2 auth is not implemented (read-only by design).

## Caveats & quirks
**Read `FINDINGS.md`** — the living log: verified field list (and the REFUTED fields — `eventId`/`eventSlug`/`oppositeOutcome` do not exist in the payload), funder-vs-EOA trap, on-chain cash mechanics. Update it whenever you learn something new.
