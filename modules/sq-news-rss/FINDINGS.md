# sq-news-rss — findings & quirks

Living log. Update the moment anything new is learned.

## Endpoint
`https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}` — plain RSS 2.0,
needs a User-Agent header (same as the chart endpoint). Live-verified
2026-06-11: `AAPL` returns items; venue-suffixed `IB01.L` returns HTTP 200
(feed may be sparse for low-coverage instruments — sparse ≠ broken).

## Quirks / caveats
- **Unofficial**, no SLA; the chart-endpoint history says Yahoo changes
  surfaces without notice. Provider degrades to `[]` — a news tab with no
  items is the correct failure mode, never a crash.
- `pubDate` is RFC 2822 (`email.utils.parsedate_to_datetime`); occasionally
  absent → `valid_at` falls back to fetch time (declared in the schema doc).
- Items are not de-duplicated across tickers by the feed: two holdings can
  surface the same macro story. The view layer dedups by URL.
- Feed length ~20 items max; this is a "latest headlines" source, not an
  archive. (If news-as-data ever matters, archive observations like prices —
  the PIT pattern applies unchanged.)

## Open issues / TODO
- [ ] Keyed rung in front (sq-finnhub company-news) for reliability + depth.
- [ ] Consider archiving observed headlines (append-only, like prices) once
      there's a consumer for historical news state.
