# sq-yahoo — findings, quirks & conformance notes

Living log. Update the moment anything new is learned.

## Endpoint
`https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d`
→ `chart.result[0].meta.regularMarketPrice` + `.currency` + exchange. Requires a `User-Agent` header (blocked without one).

## Quirks / caveats
- **Unofficial & delayed** (~15 min). Not for tick/HFT use. ToS-grey for heavy automated use — fine at personal volume.
- **Ticker, not ISIN** — Yahoo has no ISIN lookup; resolve via **sq-openfigi** first.
- **Suffixes matter:** LSE `.L`, Xetra `.DE`, Amsterdam `.AS`, US no suffix; FX as `EURUSD=X`, `GBPEUR=X`.
- **Price is in the listing's currency** — convert with an FX quote; don't assume the position's base currency.
- Endpoint format has changed historically; if it breaks, that's a self-heal trigger (regenerate the parse).

## Conformance results
- 2026-05-28: `IB01.L` and `EURUSD=X`/`GBPEUR=X` fetched cleanly; position value (price × qty ÷ FX) matched Degiro's displayed Portfolio value to within €0.39 (live-price drift). ✓

## Full-range chart + archive write-through (2026-06-11)
- `fetch_chart(ticker, start, end)` = series + dividends + splits + currency meta in ONE
  request (`events=div,splits`). Live-verified depth: AAPL 11,464 closes back to 1980-12-12
  (91 divs, 5 splits); `^GSPC` to 1970; `EURUSD=X` to 2003. The provider now fetches the
  FULL range (epoch→today) per ticker per process — kills the old adaptive window-widening
  AND feeds the archive its maximum depth in the same call.
- **Yahoo's series is split-adjusted**: after a split the whole history shifts. The archive's
  append-only rows keep both observations (knowledge-time honesty); reads are last-wins.
- `YahooProvider(store=sq_price_store.PriceStore())` archives every series/event/spot
  observation and **serves from the archive when Yahoo breaks** (`source="yahoo-archive"`).
  Archive prices are stored RAW (GBp stays GBp) — `_normalize_quote` runs at read time on
  the archive path too, same as live. Wired by `sq_platform._make_market_data_providers`;
  bare library constructions stay archive-free.
- **Archive staleness grace (2026-06-11):** an archived series stands in for the live
  source only up to `max(series) + 7 days` (`_ARCHIVE_GRACE`). A target beyond that
  returns None — the per-date fallback gets its shot and the caller degrades visibly —
  instead of silently serving a months-old close as "current". Pinned in
  `test_provider_archive.py::test_stale_archive_not_served_as_current`.
- Index/FX symbols (`^GSPC`, `EURUSD=X`) work through the same chart endpoint — this is the
  benchmark-series path (no separate index API needed).

## Intraday bars (2026-06-12)
- `fetch_intraday(ticker, interval="5m", lookback="1d")` — the 1D-chart
  feed; `YahooProvider.get_intraday` adds a 120s TTL cache (intraday
  goes stale in minutes — NOT the process-lifetime daily cache), pence
  normalisation, and stale-beats-nothing on refetch failure. NOT
  archived (the price store is daily-keyed; intraday archiving is a
  separate decision). Live-verified: AAPL 29 bars mid-session,
  IB01.L 103 bars across the LSE day.

## Open issues / TODO
- [ ] A licensed price source behind the same `fetch_quote` interface for reliability/accuracy.
- [ ] Spot quotes recorded into the archive use the OBSERVATION date (UTC today) — an
      intraday spot can briefly stand in for the session close until the next series fetch
      supersedes it (last-observation-wins). Harmless for personal MTM; note it.

## Performance traps (2026-06-04)
- **Negative-cache dead tickers** (`_series_failed` / `_fallback_failed`):
  a history full of delisted symbols otherwise re-hits Yahoo on EVERY price
  lookup — one failed series fetch + one failed per-date fallback per ticker
  per PROCESS is the budget. A failed series still gets ONE fallback shot
  (injected fetch_historical-only callers depend on it).
- **Widen the series window to the requested asof** (`valid_from` tracked):
  TWR samples reach back years; a 5y-only window made every older sample fall
  through to a per-date network call (62 calls ≈ 8s per summary build).
- The provider instance must be PROCESS-lifetime (`sq_platform`'s
  `_make_market_data_providers` singleton) — its in-memory series cache is the
  only thing standing between one fetch per ticker per session and one per
  render.
- **GBp/pence (2026-06-04):** LSE instruments quote in PENCE with currency
  `"GBp"`; a naive `.upper()` turns that into `"GBP"` and silently overvalues
  100× (a £10k position read as £1m in year-end MTM). `_normalize_quote` runs
  BEFORE any upper-casing on every quote path (live, series, fallback):
  GBp/GBX → price/100, currency GBP.
