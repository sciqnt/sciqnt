# sq-finnhub — findings & quirks

Living log. Update the moment anything new is learned.

## API
`GET /api/v1/company-news?symbol=…&from=YYYY-MM-DD&to=YYYY-MM-DD&token=…`
→ list of `{headline, url, summary, datetime (unix), source, …}`.
Free tier: 60 calls/min (verified in the 2026-06-11 research pass —
"generous" by the deep-research source; re-confirm on first live run).

## Key
`sq_secrets.get_secret("sq-finnhub", "api_token", env_var="FINNHUB_API_KEY")`.
Keyless = inert provider ([]), the platform news chain falls through to
sq-news-rss. The key never leaves the machine.

## Quirks
- `datetime` is a unix timestamp (seconds); occasionally 0/garbage —
  fall back to fetch time for `valid_at` (declared in the schema doc).
- Coverage is US-centric; venue-suffixed EU tickers often return [] —
  that's the chain's job, not an error.
- Items can repeat across adjacent days (the API window overlaps) — the
  view layer dedups by URL anyway.

## Open issues / TODO
- [ ] **Live conformance pending a real key** — implemented from the
      documented API; first keyed run should compare one ticker's items
      against the RSS rung and record the result here.
