---
name: sq-firds
description: Resolve an ISIN to official EU reference data (name, CFI code, asset class, currency, venue, LEI) via ESMA FIRDS — free, no key. Use when OpenFIGI doesn't know an ISIN, especially delisted European instruments.
---

# sq-firds — reference-data source unit

A **source** unit (reference data in). Flavour: **api** (official ESMA register). Read-only, keyless.

## When to use
You have an ISIN that OpenFIGI can't resolve — typically a DELISTED European holding from CSV history (Premier Oil, pre-split lines). FIRDS is the EU's regulatory instrument register: everything traded on an EU/EEA venue since 2018 is in it, delisted or not, with the CFI classification the canonical schema standardises on.

## How to use
```bash
python3 src/sq_firds/resolve.py GB00B43G0577
# PREMIER OIL · STOCK (ESVUFR) · GBP · SGMY
```
Or import: `from sq_firds import resolve_metadata` → same dict contract as `sq_openfigi.resolve_metadata` plus `currency`/`cfi`/`lei`. The platform chains it automatically after OpenFIGI in metadata enrichment.

## Caveats
No tickers (FIRDS identifies by ISIN+MIC — pair with sq-openfigi for pricing symbols). Pre-2018 delistings and US-only listings are absent. See FINDINGS.md for endpoint quirks.
