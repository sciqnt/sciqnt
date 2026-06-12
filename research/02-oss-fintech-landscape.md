# 02 — Open-Source Financial-Software Landscape

## Project-by-Project Survey

### OpenBB (the "took off" analog) — study closely
**What:** Open-source investment research platform. Began as "Gamestonk Terminal" (a free Bloomberg-Terminal alternative), now repositioned as a "financial data platform for analysts, quants and AI agents." Founded 2021 by Didier Rodrigues Lopes.
**Traction:** ~68k GitHub stars (one of the most-starred fintech repos), ~131k registered users, $9M seed led by OSS Capital; advisors include Travis Oliphant (NumPy) and Naval Ravikant. Launch went viral (~4k stars in 24h).
**Architecture:** Three layers. (1) **Open Data Platform (ODP)** — the open-source core that aggregates 100+ data sources and exposes them to many surfaces at once: Python, REST/FastAPI (`openbb-api` on :6900), Excel, and crucially **MCP servers for AI agents**. (2) **Extensions/Providers model** — each data source is a pluggable *provider*; analytics live in *extensions*; community backends extend the catalog. (3) **OpenBB Workspace** — the paid enterprise UI.
**Business model:** Open-core + hosted/enterprise. Engine free; money from **OpenBB Workspace** ("agentic workspace for finance") sold to asset managers and hedge funds — governance, on-prem deployment, compliance, "bring your own agent," "Workspace MCP."
**Gap it fills:** Aggregation + a single canonical-ish surface over fragmented, expensive data.
**White space:** Research/analytics-first, **not execution/brokerage-first** — no real order-routing/live-trading connector layer. Its "providers" are mostly *read* data sources, not bidirectional broker/exchange connectors. Agent-native support is recent and bolted onto the paid Workspace, not a deeply agent-first open core. No native portfolio/IBOR state or deterministic-compute-plus-LLM-reasoning loop for a personal fund. Canonical schema is data-read-shaped, not trade-lifecycle-shaped.

### ccxt — the open connector-layer model
**What:** Unified API over 100+ crypto exchanges in JS/TS/Python/C#/PHP/Go/Java.
**Traction:** ~43k stars; very active, multi-language community.
**Maintenance model:** The reference design for **community-maintained connectors** — one normalized interface, per-exchange adapter files, contributors own their exchange. MIT licensed.
**Monetization:** Largely non-commercial, but notable: exchange **builder/affiliate programs** — users pay a tiny fee (~1 bps) on top of exchange fees when trading through ccxt, plus tips/sponsorship. A legitimate, non-fraught monetization signal for a connector layer.
**White space:** Crypto-only; no canonical *cross-asset* schema (no equities/options/futures/FX unification), no compute/backtest/reasoning layer, not agent-native.

### Ghostfolio — self-hosted wealth tracker
**What:** Open-source (AGPLv3) wealth/portfolio tracker (Angular + NestJS + Prisma + Postgres).
**Traction:** ~8.5k stars; popular in self-hosting/home-server communities (Umbrel, CasaOS, Unraid).
**Model:** Open-core + **Ghostfolio Premium** hosted SaaS.
**White space (directly relevant):** **No automated broker connectivity** — manual entry + CSV/JSON import, with community scripts bridging brokers. **No AI/agent features.** Tracking-only, no quant/backtest/execution. Exactly the connector + agent gap sciqnt targets.

### Maybe Finance — cautionary tale
**What:** VC-backed personal-finance app; open-sourced (AGPLv3) Jan 2024 on the way down.
**Traction:** ~44k stars, built on Rails + Plaid.
**What happened:** Spent ~$1M, shut B2C in 2023; revived as open source + new $1.5M; pivoted to B2B forecasting July 2025, **shut down its own Synth data API and hosted B2C again (Sept 2025)**. Maintained community self-host fork is **we-promise/sure**.
**Lessons:** Code and account-aggregation patterns reusable; the business is a warning — DIY personal finance is hard to monetize B2C, data-provider/infra costs are brutal, over-building killed velocity. A self-hostable community fork outlived the company — validates open-source-as-survival.

### Quant/algo frameworks (each a narrow niche)
- **QuantConnect / LEAN:** LEAN ~16k stars, open source (C#, Python). Money via **cloud SaaS + per-dataset data licensing + institutional seats**. Niche: cloud-scale, data-rich, backtest→live. Walled-garden data.
- **NautilusTrader:** Rust-native, event-driven, HFT/microstructure grade; **self-funded, no investors, LGPL, open indefinitely**. Niche: low-latency execution correctness.
- **Backtrader:** Pythonic, local, beginner-friendly backtesting; ubiquitous but feels unmaintained.
- **vn.py:** Asian/Chinese-market live + backtest. **Hikyuu:** C++/Python ultra-fast China A-share research. **OpenAlgo:** self-hosted, 30+ Indian brokers behind one unified API (idea→backtest→live) — closest "broker connector aggregator," but India-only.
**Collective white space:** All are *compute engines*, not *canonical-data + connector platforms*. None is agent-native, none owns a community connector ecosystem across asset classes globally, data is BYO or vendor-locked.

### Plain-text accounting (beancount / hledger)
**Model:** Local-first, own-your-data plain-text ledgers; double-entry; CSV import via rule files; Fava UI.
**Limits:** Manual/CSV import only (no live broker sync), incompatible journal syntaxes, steep learning curve, accounting-shaped not market/trade-shaped (no quotes, no backtest, no positions-as-of marking). Validates the "own your data / local-first" ethos — but shows it doesn't scale to live cross-asset quant alone.

## Synthesis

### A. Is the "Supabase/OpenBB for personal quant infra" position taken? — Genuinely OPEN, but closing fast.
No single project owns *open + agent-native + cross-asset + canonical-data + community-connector + deterministic-compute-plus-LLM*. Closest + what they miss:
- **OpenBB** — closest on canonical data + multi-surface + MCP, but **research-read-only, execution-light, agents in paid Workspace**.
- **ccxt** — nails community-connector + affiliate monetization but **crypto-only, no canonical cross-asset schema, no compute/agent layer**.
- **OpenAlgo** — broker-connector aggregation + idea→live but **single-region (India), not agent-native**.
- Emerging threat: **MCP-server data wrappers** (Alpha Vantage MCP, FMP MCP, QuantJourney's QJ-API/QJ-DATA with IBOR/PMS/Instrument-Master; **Era** — first personal-finance connector in Anthropic's Claude directory, read-*write* with transfers). Landing the agent-native land-grab now, but mostly **vendor-specific, closed, single-source**. **The integration/canonical-schema + open-connector-ecosystem layer is the open white space.**

### B. Patterns that made winners take off
1. **Community owns the connector long tail** (ccxt per-exchange adapters; OpenBB providers).
2. **One canonical schema, many surfaces** (OpenBB: Python/REST/Excel/MCP from one core).
3. **Viral free core + zero-friction install** (OpenBB 4k-stars-in-24h; Ghostfolio one-Docker-Compose + home-server app-store presence).
4. **Open-source as distribution and survival insurance** (Maybe's fork outlived the company).
5. **Credible advisors/sponsors + a clear "Bloomberg is expensive" wedge.**

### C. Business models — work vs fraught
**Work:** open-core + hosted SaaS (Ghostfolio Premium, QuantConnect cloud); open engine + enterprise governance/compliance/on-prem (OpenBB Workspace — the highest-revenue path; funds pay for governance); affiliate/builder rev-share on order flow (ccxt ~1 bps — low-friction, aligned, legally clean); value-add **self-originated** curated data.
**Fraught/avoid:** reselling licensed third-party market data (bled Maybe's Synth; forces per-file licensing; legally constrained, margin-poor); pure B2C DIY personal finance (hard to monetize, infra-heavy); holding back the connector layer (must be open/community or the ecosystem won't compound).

**Implication for sciqnt:** the defensible open position = ccxt-style community connector ecosystem + OpenBB-style canonical multi-surface core, made **execution-capable and agent-first from day one** (MCP-native open core, not a paid afterthought), monetized via hosted/governed compute + **self-originated** curated data — explicitly not by reselling licensed feeds.

## Sources
- https://github.com/OpenBB-finance/OpenBB · https://openbb.co/ · https://openbb.co/blog/openbb-releases-open-data-platform/ · https://startupintros.com/orgs/openbb
- https://github.com/ccxt/ccxt
- https://github.com/ghostfolio/ghostfolio
- https://github.com/maybe-finance/maybe · https://github.com/we-promise/sure · https://newsletter.failory.com/p/3-reasons-maybe-failed
- https://nautilustrader.io/ · https://github.com/nautechsystems/nautilus_trader
- https://www.quantconnect.com/ · https://www.quantconnect.com/docs/v2/cloud-platform/datasets/licensing
- https://github.com/fasiondog/hikyuu · https://github.com/marketcalls/openalgo
- https://plaintextaccounting.org/ · https://hledger.org/beancount.html
- https://quantjourney.substack.com/p/ai-agent-native-investment-infrastructure
- https://www.financialcontent.com/article/bizwire-2026-5-6-era-becomes-the-first-personal-finance-connector-in-anthropics-claude-directory-and-every-other-mcp-compatible-agent
- https://api.market/blog/magicapi/stock-market-api/best-mcp-servers-stock-market-data

*Star counts are live GitHub figures at time of research (OpenBB ~68k, Maybe ~44k, ccxt ~43k, LEAN ~16k, Ghostfolio ~8.5k).*
