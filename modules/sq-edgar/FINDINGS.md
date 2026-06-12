# sq-edgar — findings & quirks

Living log. Update the moment anything new is learned.

## Endpoints (all official, free, no key)
- Ticker→CIK map: `https://www.sec.gov/files/company_tickers.json` (7d cache)
- Submissions: `https://data.sec.gov/submissions/CIK{cik:010d}.json` (12h cache)
- Company facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json` (24h cache)

## Quirks (live-verified 2026-06-11)
- **The User-Agent MUST contain an email-shaped token** — `sciqnt/0 (...)`
  prose-only UAs get 403 from www.sec.gov; `sciqnt/0 x@y.z` passes. We
  default to a placeholder (`unconfigured@sciqnt.invalid`) and ask users
  to set `SQ_EDGAR_CONTACT`. Fair-access limit is 10 req/s — far above
  our cached usage.
- **CIK is zero-padded to 10 digits** in data.sec.gov URLs (`CIK0000320193`)
  but plain in the ticker map (`320193`).
- **us-gaap tags vary by filer** — revenue alone has 3 common spellings.
  `_FACT_TAGS` carries fallback chains; first present wins; missing →
  None (never a guess). Annual figures = rows with `form=10-K, fp=FY`,
  newest `end` date wins (handles amended filings).
- **fundamentals_lite picks the latest FY PER TAG, not per filing** — each
  metric independently takes its newest `form=10-K, fp=FY` datapoint. For a
  patchy filer (a tag missing from the latest 10-K but present in an older
  one) the returned figures can span DIFFERENT fiscal years; only
  `fiscal_year_end` (the newest across tags) is reported. Fine for the
  context-only role; do not treat the row as one coherent statement.
- Filing URLs: accession number de-dashed in the Archives path.
- Conformance 2026-06-11: AAPL FY2025 — revenue $416,161M, net income
  $112,010M, EPS 7.46 — eyeball-consistent with Apple's reported FY25. ✓

## Open issues / TODO
- [ ] Form 4 CONTENT parsing (who bought/sold what) — the filings list
      gives the stream; the XML inside each filing has the detail. Add
      when the portfolio holds US single names again (context surface).
- [ ] 13F holdings (institutional positions) — same pattern, add on demand.
