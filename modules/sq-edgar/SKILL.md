---
name: sq-edgar
description: SEC EDGAR filings and fundamentals for US-listed companies (official, free, no key) — latest fiscal-year revenue/income/EPS, recent 8-K material events and Form 4 insider trades. Use for fundamentals or filings context on a US holding.
---

# sq-edgar — filings & fundamentals source unit

A **source** unit (context in). Flavour: **api** (official SEC JSON). Read-only, keyless.

## When to use
You want fundamentals ("what did this company earn last year?") or the primary-source event stream (8-K material events, Form 4 insider trades, 10-K/Q) for a **US-listed** holding. EU-only listings aren't SEC registrants — this returns nothing for them, by design.

## Setup (be a good citizen)
`export SQ_EDGAR_CONTACT=you@example.com` — the SEC's fair-access policy wants a contact in the User-Agent. Works without it (placeholder), but set it.

## How to use
```bash
python3 src/sq_edgar/edgar.py AAPL
```
Or import: `from sq_edgar import fundamentals_lite, recent_filings` — `fundamentals_lite("AAPL")` → latest-FY revenue/net income/EPS/assets/equity (Decimal, source-dated); `recent_filings("AAPL", forms={"8-K","4"})` → newest filings with URLs.

## Caveats
Context only — never feeds the money math. Tag fallback chains cover common us-gaap variants but exotic filers may report under tags we don't read (value comes back None, never wrong). See FINDINGS.md.
