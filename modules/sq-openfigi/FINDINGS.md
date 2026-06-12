# sq-openfigi — findings, quirks & conformance notes

Living log. Update the moment anything new is learned.

## Endpoint
`POST https://api.openfigi.com/v3/mapping` body `[{"idType":"ID_ISIN","idValue":"<isin>"}]`.
No API key needed at low volume (rate-limited: more headroom with a free key).

## Quirks / caveats
- **Many listings per ISIN** (one per exchange + currency variants), e.g. `IE00BGSF1X88` → IB01.L, IB01.SW, IB01.AS, IBC1.DE, ISHUF (US OTC), plus dozens of MIC-specific rows. Filter to the venue you want.
- **OpenFIGI ticker ≠ Yahoo symbol** always — hence the **resolve→validate** pattern (try to price each candidate; keep the first that works). Validation lives in the composition layer, not here, so this unit stays independent of any price source.
- Exchange-code → Yahoo-suffix map (`EXCH_YF` in resolve.py) is partial; extend as new venues appear. Unmapped exchanges yield `yahoo: None`.

## Conformance results
- 2026-05-28: `IE00BGSF1X88` resolved to `IB01.L` (preferred `.L`/LSE), which priced successfully via sq-yahoo and matched the hand-found ticker. ✓

## Open issues / TODO
- [ ] Extend `EXCH_YF` venue map as needed.
- [ ] Optional free OpenFIGI key for higher rate limits.
- [ ] Use the Degiro venue/exchange column to choose `prefer_suffix` automatically.
