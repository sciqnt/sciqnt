# sq-firds — findings & quirks

Living log. Update the moment anything new is learned.

## Why this bundle exists (2026-06-11)
OpenFIGI leaves delisted EU instruments unresolved (4 of the 101 ISINs in
user-zero's Degiro histories were negative-cached → `AssetClass.OTHER`,
"ISIN XX…" names). FIRDS — the EU's MiFID II regulatory instrument
register — resolved **3 of those 4 on first contact** (Premier Oil,
pre-split Harbour Energy, Anywhere Real Estate), with names, CFI codes,
currencies and venues. Official, free, keyless. The 4th (NL0010661914)
predates FIRDS coverage and is unknown everywhere.

## Endpoint
Public Solr core: `https://registers.esma.europa.eu/solr/esma_registers_firds/select`
- `q=isin:"<ISIN>"&sort=valid_from_date desc&rows=50&wt=json`
- Records are per (ISIN, venue MIC) — dozens of rows per ISIN is normal.
- Fields we consume: `gnr_full_name`, `gnr_cfi_code`, `gnr_notional_curr_code`,
  `mic`, `lei`, `status` (`UNCH`/`NEW`/`TERM`/`CANC`), `valid_from_date`.

## Quirks (live-observed 2026-06-11)
- **Tombstone rows:** many rows are attribute-less (status CANC, null
  names). Filter for a non-empty `gnr_full_name`; prefer non-CANC but a
  fully-delisted instrument may legitimately have only TERM/CANC rows —
  its reference data is still good.
- **Server-side range filters are EXPENSIVE:** `gnr_full_name:["" TO *]`
  pushed responses past 20s (timeouts); the plain ISIN query answers in
  ~1s. Filter client-side. Also observed burst sensitivity — back off and
  cache hard (the platform caches metadata for 30 days, negative results
  included).
- **No tickers anywhere** — FIRDS identifies by ISIN+MIC. The enrichment
  chain uses FIRDS for name/class/currency and OpenFIGI for tickers.
- The endpoint is public but undocumented (the registers UI uses it).
  Schema drift is possible; the resolver degrades to None.

## Conformance results
- 2026-06-11: GB00B43G0577 → "PREMIER OIL" STOCK/GBP; GB00BLGYGY88 →
  "HARBOUR ENERGY" STOCK/GBP; US75605Y1064 → "Anywhere Real Estate"
  STOCK/USD; IE00BGSF1X88 → ETF (CFI CEOGBS) USD. CFI→AssetClass mapping
  verified on real codes (ESVUFR→STOCK, CEOGBS→ETF). ✓
- **RESOLVED (2026-06-11) — unverified CFI categories `I`/`J` REMOVED from
  `_CFI_TO_ASSET_CLASS`.** The earlier map guessed `I → INDEX` / `J → CFD`,
  but in the 2015 edition of ISO 10962 category `J` is **Forwards** and `I`
  is not a category at all. Rather than ship a guess, those rows are gone:
  an I/J CFI now maps to None and the instrument honestly stays
  `AssetClass.OTHER`. Re-add a mapping only with the ISO 10962 category
  table in hand. (E / C / CE / D remain conformance-verified above.)

## Open issues / TODO
- [ ] Bulk FULINS files exist (`esma_registers_firds_files` core) if per-ISIN
      lookups ever become too chatty — a local FIRDS extract would be the
      archive-grade approach.
