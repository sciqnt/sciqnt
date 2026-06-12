# 05 — Value of Financial Data + Connector Landscape

## PART A — The economics / value of financial data

### A1. Trading styles and what data drives value

| Style | Data that matters | Realistic edge / caveat |
|---|---|---|
| **HFT / microstructure** | L2/L3 order book (MBP-10, MBO), tick data, colocation, microwave links | Edge is almost entirely *speed*, not data ownership. Latency arbitrage ~$5B/yr globally, ~0.42–0.53 bps liquidity cost, ~537 races/day on an avg FTSE 100 name. **A small open project cannot compete here** — data is cheap-ish to buy (Databento L2 from ~$199/mo) but useless without sub-ms infra. |
| **Systematic / quant factor** | Clean PIT fundamentals, returns, factor exposures, some alt-data | Real but decaying. ~50% of published anomaly alpha disappears post-publication; momentum that returned 15–20% now ~3–5%. Edge = *combination + execution discipline*, not any single dataset. |
| **Discretionary / fundamental** | Filings (10-K/Q/8-K), transcripts, normalized financials, news | Data is a research *input*, not an edge; value is the analyst. Aggregation/normalization saves time — where tooling value lives. |
| **Options / vol** | Options chains, IV surfaces, Greeks, realized vol | Data expensive (options often a higher tier); edge in modeling + execution. Retail-accessible. |
| **Long-horizon / passive** | EOD prices, dividends, expense ratios, basic fundamentals | Data needs trivial, essentially *free*. No alpha from data — value is behavioral (staying invested, cost minimization). |
| **Personal portfolio mgmt** | Your *own* positions + transactions, tax lots, fees, allocation | **Highest-ROI quadrant for an open platform.** Value = decision-support (consolidated view, rebalancing, tax-lot/CGT awareness, fee detection, drift). No alpha-decay — it's personal-state data nobody can commoditize. |

### A2. News & sentiment / alt-data — evidence and signal decay
Mixed and decaying. Positive backtests exist but look fragile/overfit (one DJ30 study: 50.6% over 28 months, Sharpe 3.64–5.10 in 2022–23 *only* with a news-impact decay function; many public sentiment kernels show no benefit once realistically traded). **Signal decay is central:** new-trade alpha decays ~12 months on average; crowding accelerated post-2015. When N players act on the same signal, order flow arbitrages it away near-instantly. News is valuable when you have a *latency/coverage* advantage (out of reach for retail) or use it for *context/risk awareness*, not fast directional bets. Sophisticated money already moved to **multimodal** (audio/video/transcripts) because text sentiment decayed.

### A3. The alternative-data market
Size estimates diverge wildly: credible "pure" figure ~**$2.8B in 2025, ~27% YoY**; analyst-firm TAMs balloon to $12–14B (2025) → $135B–$854B by 2030–35 (treat skeptically — they bundle tooling). Buyers: hedge funds dominate (~71% revenue, ~78% penetration); card transactions top type (~17.9%); North America ~69% of spend. Real-time streaming commands a **5–10x premium** vs batch — value is freshness/exclusivity, exactly what a small open project lacks. Published/cheap = crowded = ~50% alpha gone.

### A4. Heuristic for sciqnt: "data X → value type Y → trader-style Z"
Defensible value is **not** market-beating signals. It is:
1. **Normalization/aggregation** — fragmented broker + market + filings → one clean agent-queryable schema. Value = time + correctness, for research.
2. **Personal-finance decision support** — *your own* positions (non-commoditizable) for rebalancing, fee/tax-drag detection, allocation. Accrues to personal/long-horizon investors.
3. **Free/public-data plumbing** — EDGAR parsing, EOD hygiene, PIT correctness — durable infra, not alpha.

Blunt rule: **monetize convenience, correctness, and personal-state insight — never "alpha-in-a-box." If a signal is cheap enough for retail to buy, it's already crowded.**

## PART B — Connector & data-source landscape

### B1. Brokerage account aggregation (read positions/transactions)
| Provider | Coverage | Read/Write | Notes |
|---|---|---|---|
| **SnapTrade** | Retail brokerages, "400M+ accounts," US-centric + some global | **Read AND write (trade)**, near-real-time, full historical txns | Best fit for retail brokerage *and* execution; "Plaid for trading." |
| **Plaid Investments** | 12,000+ institutions | **Read-only**, ~daily refresh, needs normalization | Broad but shallow for investing; no trades/open orders. |
| **Salt Edge** | 5,000+ banks (Europe-first), 60+ countries | Read (AIS/open-banking) | Strong EU/open-banking; bank-account-centric, weaker on brokerage holdings. |
| **Akoya** | US banks/CUs/brokerages, direct FI | Read (token-based) | US open-finance; US-only essentially. |

**EU/Degiro gap (confirmed):** Degiro has **no official API**. Only unofficial reverse-engineered clients (`degiro-connector` PyPI, `degiro-api` GitHub) — fragile, ToS-risky; no aggregator reliably covers it. A real coverage hole for European retail.

### B2. Broker execution APIs
| Broker | Automatable? | Paper | Notes |
|---|---|---|---|
| **Alpaca** | Yes — developer-first REST | Yes ($100k, resettable) | Commission-free stocks/ETFs; crypto + options; best onboarding. |
| **Interactive Brokers** | Yes — TWS / Client Portal / Flex | Yes (demo) | Broadest asset/global coverage; clunkier API; low fees. |
| **Tradier** | Yes — good REST | Yes (sandbox) | Low equity/option fees; solid options. |
| **Tastytrade** | Yes — official Open API | Yes | Options-focused; rate limit ~60 RPM (low). |
| **Trading212** | Partial/emerging — public API now allows market orders live | Limited | EU-friendly retail; still maturing. |
| **Crypto via ccxt** | Yes — unified API, 100+ exchanges | Per-exchange testnets | De-facto open standard for crypto automation. |

~8/10 API brokers offer demo/paper; rate limits vary widely (~60 RPM tastytrade → ~7,200 Oanda).

### B3. Market & reference data providers
| Provider | Free tier | Coverage / quality |
|---|---|---|
| **Finnhub** | Generous — 60 calls/min, 15-min delayed | Good intl coverage, WebSocket. |
| **Tiingo** | 30+yr history, 5yr fundamentals; 500 sym/mo, 50/hr, 1k/day | Strong EOD + fundamentals value. |
| **Alpha Vantage** | Free tier, 20+yr, stocks/FX/crypto, indicators | Good for learning/small; tight limits. |
| **EODHD** | Paid from ~€19.99/mo | Broad global EOD/fundamentals; good backtesting. |
| **Financial Modeling Prep** | Limited free | Fundamentals-heavy. |
| **Polygon.io** | Limited free; Stocks Advanced **$199/mo**; **Options a separate higher tier** | Strong US real-time. |
| **Databento** | Metered (~$100–500/mo; Standard $199) | Best for tick + L2/L3; cost scales aggressively — model first. |
| **Twelve Data** | Free tier | Multi-asset, global. |
| **yfinance** | "Free" but **unofficial scraping** | **Caveats:** not an API — scrapes Yahoo; undocumented limits, IP blacklisting, breaks on layout change, 15–20min delayed, no streaming. **Unsuitable for automated trading**; prototyping only. |

**PIT/quality:** free tiers rarely give true point-in-time fundamentals. For correctness-as-a-feature: Tiingo/EODHD/Databento credible cheap options; yfinance is not.

### B4. News & filings
- **SEC EDGAR:** **free, public** (REST API, company facts, submissions). Official API lacks full-text search; third parties (sec-api.io, freemium→commercial) add full-text/streaming/XBRL/13F/insider. EDGAR is the highest-value *free* dataset for fundamental/event work.
- **News feeds:** Benzinga/NewsAPI-type are licensed/paid (sales-led, institutional pricing). Free/scrapeable: EDGAR, IR pages, RSS. Real-time licensed newswires are where the latency edge lives — and where sciqnt realistically *cannot* add value vs incumbents.

**Connector takeaway:** the defensible build is an **open normalization layer** over (a) SnapTrade/Plaid/IBKR/Alpaca for real accounts, (b) free EDGAR + cheap EOD (Tiingo/EODHD) for reference data, (c) ccxt for crypto — avoiding the licensed-newswire and HFT-data arms races. The EU/Degiro gap and personal-portfolio decision-support are the genuine open niches.

## Key takeaways (value-first thesis)
1. Alpha-bearing data is a losing game for a small open project — commoditized, crowded (~50% of published anomaly alpha gone), or speed-gated (HFT).
2. Defensible/monetizable value = normalization/aggregation, correctness/PIT plumbing, personal-portfolio decision-support using the user's own non-commoditizable account data.
3. Connectors: open layer over read+execute APIs (SnapTrade/Plaid/IBKR/Alpaca/ccxt) + free EDGAR + cheap EOD; avoid licensed newswires + tick/L2 arms races.
4. Two concrete open niches: **EU/Degiro coverage gap** + personal-finance decision support. Treat giant alt-data TAMs skeptically; credible pure figure ~$2.8B/2025.

## Sources
- https://medium.com/geekculture/is-news-sentiment-still-adding-alpha-54635e45635b · https://permutable.ai/multi-asset-sentiment-avoiding-alpha-decay/ · https://arxiv.org/abs/2507.03350 · https://jhfinance.web.unc.edu/wp-content/uploads/sites/12369/2016/02/Alpha-Decay.pdf
- https://www.imarcgroup.com/alternative-data-market · https://alternativedata.org/stats/ · https://www.kadoa.com/blog/alternative-data-for-hedge-funds · https://www.grandviewresearch.com/industry-analysis/alternative-data-market
- https://corpgov.law.harvard.edu/2021/11/05/quantifying-the-high-frequency-trading-arms-race/ · https://academic.oup.com/qje/article/137/1/493/6368348
- https://snaptrade.com/brokerage-integrations · https://plaid.com/products/investments/ · https://www.saltedge.com/products/account_information · https://akoya.com/blog/the-open-finance-api-stack-securely-access-financial-data-with-akoya
- https://pypi.org/project/degiro-connector/ · https://github.com/icastillejogomez/degiro-api
- https://alpaca.markets/ · https://docs.alpaca.markets/us/docs/paper-trading · https://tastytrade.com/api/ · https://community.trading212.com/t/trading-212-api-update/87988 · https://github.com/ccxt/ccxt
- https://databento.com/pricing · https://polygon.io/pricing · https://aifinhub.io/articles/market-data-apis-compared-2026/ · https://medium.com/@trading.dude/why-yfinance-keeps-getting-blocked-and-what-to-use-instead-92d84bb2cc01
- https://sec-api.io/ · https://github.com/janlukasschroeder/sec-api-python
