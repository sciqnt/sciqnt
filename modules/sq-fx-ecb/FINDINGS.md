# sq-fx-ecb — findings & quirks

Living log. Update when you learn something new about ECB's feed or our handling.

## ECB data model
- Daily reference rates published weekdays around **16:00 CET** ("close of trading day in the Eurosystem").
- Format: `1 EUR = rate units of CCY`. Every rate is EUR-cross.
- Daily file: `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`
- 90-day rolling: `…/eurofxref-hist-90d.xml`
- Full history (since 1999): `…/eurofxref-hist.xml` (~1 MB) — wired: `asof` older than
  ~80 days transparently loads this file instead of the 90-day one. Live-verified
  2026-06-11: USD→EUR at 2021-03-15, 2005-07-01 and 1999-01-08 all return that day's fixing.

## Cache policy
- **Daily file**: 12h TTL. Survives a re-run within the trading day; refreshes once the next publishing window passes.
- **90-day file**: 24h TTL. Rolls daily anyway.
- Cache dir: `~/.cache/sciqnt/fx-ecb/` (XDG-style; user-owned, outside the repo, survives `git clean -fdx`).
- Writes are atomic (`.tmp` + `replace`) so an interrupted refresh leaves no corrupt XML.

## Triangulation
Non-EUR pairs (e.g. `USD → GBP`) computed via EUR:

```
rate(USD, GBP) = rate(EUR, GBP) / rate(EUR, USD)
```

Introduces ~1e-10 rounding (well below money-display granularity). Round-trip (e.g. `convert(amount, USD, EUR)` then back) does not always equal `amount` exactly — quantize at display.

## Currencies excluded from ECB basket
- **RUB** — excluded since the 2022 sanctions. Any query for RUB returns `None`.
- Historically other currencies have entered/left the basket; check the ECB site if a query unexpectedly returns `None`.

## Open issues / TODO
- Consider intraday — ECB ships a daily fixing only. For live FX-sensitive use, `sq-fx-yfinance` (when built) is the better source.
- Conformance suite uses fixture XML (no network); add an opt-in integration test (`SQ_FX_ECB_LIVE=1`) that hits the real ECB endpoint to detect schema drift early.
