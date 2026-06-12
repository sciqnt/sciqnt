---
name: sq-degiro
description: Read a Degiro account — parse its CSV exports into canonical events, compute realized P&L, and reconcile cash to the cent; fetch live positions/cash and refresh the CSVs over the (unofficial) API. Use when someone has a Degiro account and wants correct, consolidated, multi-currency P&L.
---

# sq-degiro — Degiro source unit

A **source** unit (data in). Two flavours behind one interface: **file/CSV** (history — simplest, ToS-clean) and **api** (live positions/cash + history sync — unofficial `degiro-connector`, reverse-engineered, at-your-own-risk; **live-verified**: real-credentials run reconciled to the cent against the Degiro screen, 2026-05-28, see FINDINGS). Read-only — no execution.

## When to use
The user has a Degiro account and wants: realized P&L, current positions, live cash, or a cash-correct reconciliation. Degiro has no official API; the CSV exports are the reliable history path, and `sync` refreshes them programmatically (no manual re-export).

## Inputs
Two CSVs exported from Degiro (full date range), flat `data/degiro/` or per-account `data/degiro/<account>/`:
- `transactions.csv` — trades.
- `account.csv` — cash ledger (dividends, fees, interest, FX, deposits/withdrawals).

## How to use
```bash
bin/sq-degiro setup                  # store credentials (keychain/.env, verified)
bin/sq-degiro live [--account NAME]  # live positions + cash (auto-picks the only
                                     #   account; picker at a TTY when several)
bin/sq-degiro sync [--account NAME]  # refresh history CSVs from Degiro — no args
                                     #   syncs EVERY configured account
bin/sq-degiro doctor                 # read-only health check per account
                                     #   (creds · session · history freshness)
bin/sq-degiro doctor <probe|fix-totp># deeper diagnostics when login is broken
python3 src/sq_degiro/pnl.py [data_dir]   # CSV-only P&L report (default: <repo>/data/degiro)
```
Or import: `from sq_degiro import analyze, snapshot; analyze(Path("…/data/degiro"))`.
Returns/prints: realized P&L per closed position, open positions, cash-ledger categories, and a per-currency cash reconciliation against Degiro's own ending balance.

## Unrealised P&L
Computed — via the platform's mark-to-market overlay (`sq_market_data.overlay_prices` + the sq-yahoo/sq-tiingo price chain), not inside this bundle. `fold_position` keeps the auditable history side; the overlay populates `last_price_local` / `value_base` / `unrealized_*` on top. The aggregated `sciqnt` view does this automatically.

## What it does NOT do
- Execution (orders) — read-only; execution is a separate, higher trust tier.
- The live API path leaves `realized_fees_base = 0` (Degiro's API doesn't expose per-position fees) — only the CSV path is fees-complete.

## Caveats & quirks
**Read `FINDINGS.md`** — it is the living log of broker quirks (cash-sweep, foreign-currency dividends, all-in `Total EUR`, corporate-action-as-transactions, FX legs, Portuguese descriptions, session persistence, in-app approval dance) and conformance results. Update it whenever you learn something new.
