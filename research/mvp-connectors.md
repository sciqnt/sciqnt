# MVP connector & data-source plan (free-first)

Status: decided 2026-06-11 (owner steer: completely-free sources first, scraping acceptable
when declared; news as a first-class data type; position for alpha via substrate, not signals).
Grounded in: `05-data-value-and-connectors.md`, the 2026-06-11 deep-research pass
(verified-claim list below), and a codebase gap audit (same date).

## Owner steer (verbatim intent)

1. **Completely free first** — even where that means unofficial/scraped sources. Paid rungs
   (EODHD, Tiingo paid) stay available as opt-in flavours but are never required for the MVP.
2. **News articles are in scope** as portfolio context ("what happened to MY portfolio today").
3. **"Set to generate alpha"** — honest framing per our own research: no free feed is an edge
   alone (crowded by definition). The edge-shaped things are (a) the **bitemporal archive** we
   originate by persisting free feeds from today (PIT honesty is what vendors actually charge
   for), (b) **joins across the canonical schema** (insider + short interest + news timing +
   prediction-market odds + the user's own exposure), (c) **personal-state insight** nobody can
   commoditise. Build the substrate that lets an agent hunt; do NOT ship "signals".

## The portfolio-view gaps this plan closes (from the 2026-06-11 audit)

| # | Gap (what the user sees) | Closed by |
|---|---|---|
| 1 | XIRR/TWR/drawdown "—" for Robinhood/Kalshi/Polymarket (no txn history) | Wave C: fold RH orders + Kalshi settlements into canonical Transactions |
| 2 | No benchmark comparison anywhere | Wave A4: benchmark series via ETF proxies through the price chain |
| 3 | `--asof` valuations fall back to cost basis (no durable price history) | Wave A3: Yahoo full-range history + persistent PIT price archive; Wave B: Stooq second source |
| 4 | Dividends computed but invisible in summary | Wave A2: income lines in summary tab |
| 5 | Historical FX stops at ECB's 90-day file (old flows silently dropped from XIRR) | Wave A1: eurofxref-hist.xml (1999→) |
| 6 | EU ISINs stay AssetClass.OTHER / "ISIN XX…" when OpenFIGI misses | Wave B: ESMA FIRDS bulk reference data |
| 7 | No fundamentals / filings / events context | Wave B: SEC EDGAR (companyfacts, 8-K, Form 4, 13F) |
| 8 | No news context | Wave B: Finnhub free tier + per-ticker RSS + EDGAR events, joined to holdings |

## Market data — the free stack

**Design rule:** every source is a provider behind the existing protocols (`PriceProvider`,
`FxRateProvider`, new `NewsProvider`/metadata enrichers), flavour declared in the manifest
(official-api / unofficial-api / file-download), failures degrade visibly. A provider CHAIN
(not a single source) is the unit of reliability: two independent free sources per data type
where possible.

| Data type | Primary (free) | Second rung (free) | Paid opt-in flavour |
|---|---|---|---|
| Daily price history + splits/divs | **sq-yahoo** chart API `range=max&events=div,splits` (unofficial, declared) | **sq-stooq** CSV EOD (no key; US+EU) | sq-eodhd ($19.99/mo All-World, verified 3-0) |
| Benchmarks | same chain — `^GSPC`, `IWDA.AS`, ETF proxies | same | same |
| FX | **sq-fx-ecb** full history 1999→ (official) | Frankfurter API (same ECB data, hosted) | — |
| Instrument metadata (EU ISINs) | **sq-openfigi** (have) + **ESMA FIRDS** bulk files (official, free) + GLEIF LEI | — | — |
| Fundamentals + filings (US) | **SEC EDGAR** companyfacts XBRL / submissions / 8-K / Form 4 / 13F (official, free) | — | — |
| News | **Finnhub** free tier company news (official) | per-ticker **RSS** (Yahoo Finance, Google News) | — |
| Macro | **FRED** (free key) + ECB Data Portal | — | — |
| Short interest | FINRA published files (free) | — | — |
| Event probabilities | already have: sq-kalshi + sq-polymarket public odds | — | — |

Verified 2026-06-11 (adversarial 3-0 unless noted):
- Tiingo free: 500 sym/mo, 50/hr, 1k/day, 30y EOD history incl. free; license "internal use
  only" (BYO-key OK); **EU listings not an advertised category** → why it's not our EU answer.
- EODHD free = 20 calls/day (useless); paid All-World $19.99/mo, 100k/day, 30y, splits+divs.
- Twelve Data free = US-only; EU needs $66–79/mo → eliminated.
- IBKR **Flex Web Service**: standalone HTTP, pre-configured reports, token+queryId auth —
  IB credentials never in the API call; no TWS needed. Ideal local-first read-only path.
- UNVERIFIED (rate-limit abstains, all from official docs, re-verify before building):
  Trading 212 public API v0 endpoint set (positions / account cash / historical orders /
  dividends / transactions; key+secret auth; beta; Invest+ISA only), IBKR Client Portal API
  constraints (Java gateway, manual browser login, 24h sessions).

## The PIT price archive (the compounding asset)

Every price/FX/odds observation any provider fetches is written through to a local
**append-only, bitemporal store** (valid_at = trading date, observed_at = fetch time,
source-attributed). Rationale:
- Yahoo can break or rewrite history; the archive makes us progressively independent.
- Survivorship-free, as-known-then history is exactly what vendors charge for; ours accrues
  from $0 starting today. Self-originated data = value ladder rung 5.
- It is the substrate for honest backtests later (knowledge-time queries).
Implementation: start as the same pattern as the existing on-disk caches (user-owned dir),
schema-compatible with the future Postgres/Iceberg move (additive, columnar-friendly).

## Brokers

| Priority | Connector | Why / path |
|---|---|---|
| C1 | **sq-robinhood history** | robin_stocks order history → canonical Transactions; kills "—" row for an already-connected broker. Needs a real-creds field-shape pass. |
| C2 | **sq-kalshi settlements** | `/portfolio/settlements` → SETTLEMENT transactions; realised P/L for events. |
| C3 | **sq-trading212** | Official public API (beta v0), user-generated key, full read path incl. dividends + transactions endpoints. Highest-value EU retail complement to Degiro. Re-verify docs first. |
| C4 | **sq-ibkr-flex** | Verified fit: token-auth reports incl. transactions; big reach, cross-asset. |
| C5 | **CSV-import generalisation** | The universal fallback; we already have cent-perfect Degiro CSV machinery; Ghostfolio/PP ecosystems prove the demand. |

Aggregators (SnapTrade/Plaid): out for the MVP — central credential custody contradicts
local-first sovereignty, and per-connection pricing doesn't fit BYO-keys.

## Build order

- **Wave A (view gaps, mostly-wired data):** A1 ECB full FX history · A2 dividends/income in
  summary · A3 Yahoo full history + div/splits + PIT archive · A4 benchmark comparison.
- **Wave B (new free sources):** B1 sq-stooq · B2 sq-edgar · B3 FIRDS metadata enrichment ·
  B4 portfolio-news surface (Finnhub + RSS) · B5 FRED macro (stretch).
- **Wave C (broker completeness):** C1 RH history · C2 Kalshi settlements · C3 Trading 212 ·
  C4 IBKR Flex · C5 CSV-import generalisation.

Per-item definition of done: conformance/fixture tests green, FINDINGS.md updated, flavour +
quirks declared, view renders the new data, honest gaps stated.
