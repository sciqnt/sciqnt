# sciqnt — Vision & Architecture (research-grounded)

Status: research synthesis, v0.1 · Date: 2026-05-28
Owner: DavideGCosta · Author of this draft: research synthesis from 5 parallel streams (see `research/01..05`)

> **Governing principle (owner steer, 2026-05-28):** This is about **generating and proving value**, NOT racing to claim a market gap. We do not build to "close a gap we don't know exists." If existing tools (especially **OpenBB**) already deliver the value and work well, **contributing to / building on them is a first-class success outcome — not a fallback.** Let the *shortfall* of existing tools, measured against a real need, define any gap worth building. The "market position is open / narrowing" observations below are **context, not a reason to hurry.**

This document answers the three questions that scope the project:
**Where do we add value? What should be what (skills / MCP / library)? What does the future reward?**
Everything below is grounded in the research reports in this folder; key sources are cited inline and listed per-report.

---

## 0. The thesis in one paragraph

sciqnt is **an open, agent-native, cross-asset financial-data layer**: one canonical, point-in-time-correct schema for instruments, positions, transactions, cash, corporate actions and prices — fed by an open ecosystem of community-maintained **connectors** (each broker / exchange / data source), and exposed to *any* AI agent (Claude, ChatGPT, openclaw) through thin protocol adapters. Deterministic code computes the numbers; LLMs reason and explain. The owner is user-zero (a personal quant "fund"), but every piece is reusable infrastructure others build on — the OpenBB/Supabase outcome. **We do not sell alpha and we do not resell licensed data.** We monetise correctness, convenience, personal-state insight, connector reach, and self-originated data.

---

## 1. Where we add value (the value-first answer)

The single most important research finding, consistent across the data-economics and OSS streams: **alpha-bearing data is a losing game for a small open project.** It is either commoditised and crowded (~50% of published anomaly alpha disappears after publication; momentum that paid 15–20% now pays 3–5%), or speed-gated (HFT latency races are a ~$5B/yr winner-take-all tax requiring sub-millisecond infra), or licence-locked (real-time newswires, card-panel alt-data — exclusivity/freshness commands a 5–10x premium we cannot match). The giant alt-data TAM figures ($135B–$854B by 2030) bundle tooling and should be treated skeptically; the credible "pure" alt-data number is ~$2.8B/2025, ~71% bought by hedge funds. (See `05-data-value-and-connectors.md`.)

So value does **not** live where most people assume. It lives in the boring, durable layers underneath — and these compound:

**The sciqnt value ladder (lowest/most-defensible first):**
1. **Canonical normalisation.** Turning fragmented broker + market + filings data into one clean, correct, agent-queryable schema. Value = time saved + correctness, for everyone.
2. **Personal-state decision support.** Reasoning over *your own* positions/transactions/tax-lots/fees — rebalancing, drift, fee/tax-drag detection, consolidated multi-currency P&L. This data is **non-commoditisable** (nobody else has your portfolio) and has **no alpha-decay problem** because it isn't a market signal. This is the highest-ROI quadrant for an open platform.
3. **PIT-correct plumbing.** Point-in-time, survivorship-free reference data and filings parsing (EDGAR is free). Durable because it's infrastructure, not a signal.
4. **Connector reach.** The open, community-maintained connector ecosystem itself — breadth nobody else has bothered to assemble cleanly.
5. **Self-originated data (later, optional).** Data *we* collect/derive (e.g. our own news/sentiment/aggregate signals), where freshness/exclusivity is ours — never repackaged vendor feeds.

**Blunt rule for every dataset/feature:** *monetise convenience, correctness, and personal-state insight — never "alpha-in-a-box." If a signal is cheap enough for retail to buy, it's already crowded.* This is the test the owner asked for: "how much value, for what type of trading?" — answered as a ladder, not a guess.

---

## 2. Market position — what's open, who's close, our wedge

No single project today owns *open + agent-native + cross-asset + canonical + community-connector + deterministic-compute + LLM-reasoning*. The position is **genuinely open** (and narrowing over time — but per the governing principle above, that's *context, not a reason to race*) (`02-oss-fintech-landscape.md`):

- **OpenBB** (~68k stars, $9M seed, ~131k users) is closest on canonical data + multi-surface (Python/REST/Excel/**MCP**). But it is **research/read-first, execution-light**, its connectors are read-data *providers* not bidirectional broker connectors, and **agents live in the paid Workspace**, not an agent-first open core.
- **ccxt** (~43k stars) is the reference design for **community-maintained connectors** and shows a clean monetisation (exchange affiliate/builder rev-share, ~1 bps) — but it's **crypto-only, no cross-asset canonical schema, no compute/agent layer**.
- **OpenAlgo** nails broker-connector aggregation + idea→live but is **India-only, not agent-native**.
- **Ghostfolio** (~8.5k stars) proves the self-hosted tracker demand but has **no automated broker connectivity and no AI**.
- **Maybe Finance** (~44k stars) is the cautionary tale: ~$1M spent, B2C personal-finance is hard to monetise, **reselling licensed data (their Synth API) bled them**; the community fork outlived the company — open-source as survival.
- Emerging land-grab: single-source **MCP data wrappers** (Alpha Vantage MCP, FMP MCP, "Era" personal-finance connector in Anthropic's directory). They're claiming "agent-native" but are **vendor-specific and closed** — none is the open, modular *platform*.

A *possible* wedge — *if* the value is proven and existing tools fall short — would be the intersection nobody holds: ccxt-style **community connectors** + OpenBB-style **canonical multi-surface core**, made **execution-capable and agent-first (open, not a paid afterthought)**, spanning **all asset classes**, with two concrete underserved niches: the **EU/Degiro coverage gap** (no official API; only fragile reverse-engineered clients) and **personal-portfolio decision support**.

**But the wedge is a hypothesis, not a plan.** OpenBB is closest and does the undifferentiated heavy lifting (100+ providers, multi-surface, MCP). The value-first stance means: **build *with* OpenBB, contribute *to* it, or extend it — before building *against* it.** Only a measured shortfall against a real need justifies a parallel platform. See Milestone −1 in §8.

---

## 3. What should be what — the layering (the core architecture answer)

The research is decisive and counter to the "MCP vs Skills" framing: **it's not a choice, it's a stack** (`01-mcp-skills-libraries.md`). Three artifacts over one core, per connector/capability:

```
┌─────────────────────────────────────────────────────────────┐
│  SKILL (SKILL.md)  — teaches the agent HOW: financial         │  ← portable know-how,
│  conventions, which calls to compose, how to read outputs     │     ~free via progressive disclosure
├─────────────────────────────────────────────────────────────┤
│  MCP server (thin)  — live data access, server-side auth/     │  ← the open, cross-vendor
│  credential custody, auditability, cross-agent reach          │     WIRE protocol (Claude/GPT/openclaw)
│  + A2A adapter later for agent-to-agent                       │
├─────────────────────────────────────────────────────────────┤
│  CORE LIBRARY (deterministic, well-typed)                     │  ← THE DURABLE ASSET.
│  canonical schema + each connector as an importable,          │     survives every protocol shift;
│  versioned module; the compute (P&L, lots, FX, PIT)           │     is the "code" in code-execution;
│                                                                │     usable with no agent at all
└─────────────────────────────────────────────────────────────┘
```

**Why this layering, mapped to our own principles:**
- *"Deterministic code computes, LLMs reason"* maps exactly onto **library (compute)** + **Skill (reason/explain)**.
- *"Plug independently into many agents"* is served by the **library (universal)** + **MCP (the one open cross-vendor protocol)**.
- *"Others build on top" (OpenBB/Supabase outcome)* requires a **real library as the foundation** — MCP/Skills alone are agent adapters, not composable software.

**The durable-primitive argument (this is the future-proofing).** Anthropic's "code execution with MCP" work shows agents increasingly call tools by *writing code against a typed API* and discovering definitions on demand — one worked example dropped from ~150k tokens to ~2k (~98.7%) by not front-loading tool definitions and keeping intermediate data in the sandbox. MCP's biggest practical limit is exactly this **context/tool bloat** (3 servers' definitions can eat ~143k tokens; agents degrade past ~2–3 servers). The lesson: **the durable thing is a clean, typed core library/API; MCP, Skills and A2A are swappable delivery wrappers over it.** Keep the library as the contract and you survive whatever wins.

**Decision rules (when to reach for which):**
- **Library / CLI** when determinism and token-efficiency dominate (CLI-style interfaces reportedly beat MCP 10–32x on tokens). This is the default and the foundation.
- **MCP server** when data changes between calls (live access), you need server-side credentials, auditability, and cross-vendor reach. Keep the tool surface *small and code-execution-friendly* (a few code-API entry points, not dozens of granular tools).
- **Skill** when the knowledge is stable enough to "write once, be right for weeks," wants local/zero-latency, and benefits from author-friendly markdown.

**Concrete packaging for a sciqnt connector** (e.g. `sq-connector-alpaca`): a typed library module implementing the canonical interface → a thin MCP server exposing a handful of code-style entry points → a `SKILL.md` documenting the financial conventions and safe usage. Same pattern for every broker/data source.

**Forward-looking (1–3 yr), durable bets to make now:** clean typed core API; **declarative/static capability metadata** (MCP's coming `.well-known` discovery signals this); OAuth/OIDC auth; statelessness (MCP is committing to stateless horizontally-scalable HTTP); avoid deep coupling to any one vendor's agent surface. MCP and A2A are both under the Linux Foundation now — interop is consolidating, not fragmenting.

---

## 4. The canonical schema — the hard core (borrow, don't invent)

The owner is right that this is the hard core, and the research says **almost everything is borrowable** (`03-canonical-schema.md`). Mine the standards for *concepts and enumerations*; do **not** adopt their machinery (no OWL reasoners, no Rune DSL — those sink startups).

**What to borrow from where:**
- **Vocabulary/taxonomy** → FIBO names; **CFI codes (ISO 10962)** for machine-readable asset classification (don't hand-roll an asset taxonomy).
- **Identifier spine** → **FIGI (OpenFIGI, free API)** as the internal join key, with a multi-scheme alias map (ISIN/CUSIP/SEDOL/MIC/ticker). **Never make ISIN the primary key** — FX, crypto and OTC lack one.
- **Event/lifecycle pattern** → ISDA/FINOS **CDM's idea** (immutable typed lifecycle events → derived state), implemented simply.
- **Accounting core** → **beancount's** model wholesale: double-entry postings, positions held as **lots at cost**, pluggable booking (FIFO/LIFO/HIFO/average/specific-lot).
- **API discipline** → **OpenBB's** approach: Pydantic, `snake_case`, schema = intersection of fields shared across providers, identical output regardless of source.
- **Enums/semantics** → **FIX** (order side/type/TIF, execution reports), **ISO 20022** (cash/settlement; `seev.*` corporate actions).

**Thin core to start (~6 entities), specialisation additive:**
`Instrument`, `Position`, `Transaction`/`Activity`, `Cash`, `CorporateAction`, `Price` — where **`Transaction` is the immutable event log and `Position` is *derived* (a fold over events)**, and asset-class specifics (option strike/expiry/multiplier, bond coupon schedule + day-count, FX legs) live in a typed `instrument_terms` sub-object keyed by CFI category. **Currency is mandatory on every monetary value from day one** (retrofitting it is brutal). Separate **capital gain from currency gain** (Sharesight pattern). Cost-basis method is a per-account/jurisdiction setting.

**Top pitfalls to avoid:** over-engineering with full FIBO/CDM; ISIN-as-PK; storing positions as *mutable rows* (splits/dividends/cost-basis become un-auditable — positions must be derived from the event log); hard-coding one currency or one cost-basis method; modelling corporate actions as ad-hoc patches instead of first-class events; premature derivatives depth before equities/ETFs/cash/bonds are solid.

---

## 5. Data architecture — point-in-time, Postgres now, Iceberg later

The owner's instinct ("Postgres frontend + Iceberg PIT backend") is directionally right but the **sequencing** matters, and one decision is irreversible (`04-pit-bitemporal-iceberg.md`).

**Why PIT is non-negotiable for the quant side:** without it, look-ahead bias (e.g. trading on fundamentals before their ~6-week reporting lag), survivorship bias (today's universe omits delisted names), and restatement/adjustment all silently corrupt backtests — look-ahead alone can inflate returns 100–500 bps. The fix is **bitemporality**: store both **valid-time** (when a fact was true) and **knowledge/system-time** (when we learned it); an "as-of" query sets knowledge-time = decision-time and makes look-ahead *structurally impossible*.

**The staging recommendation:** **start Postgres-only with strict bitemporal, append-only modelling. Defer Iceberg until you actually feel OLTP/cost/replay pain.** Iceberg-first is premature; but the *modelling* cannot be deferred. Get these right on day one to keep the Iceberg door open without a painful migration:
1. **Append-only fact tables with valid-time + knowledge-time** columns — no destructive updates. *This is the one irreversible-if-skipped decision; retrofitting knowledge-time onto a mutable snapshot DB is effectively impossible.*
2. Stable surrogate IDs + a monotonic version/ordering token per fact (for later CDC into Iceberg).
3. Columnar-friendly, additive-evolution schema (maps cleanly to Parquet/Iceberg).
4. **Temporal universe/membership tables** (so survivorship is solved in the model, not at query time).
5. Decide nothing catalog-specific yet — catalogs (REST/Glue/Nessie/Polaris) are swappable.

**When Iceberg does arrive:** it adds immutable snapshots, time-travel, branching/tagging (tag a "research dataset v2026-05-01" for perfectly reproducible backtests) and schema evolution. The most production-credible Postgres↔Iceberg bridge as of now is **pg_lake** (Snowflake-Labs, Apache-2.0, Nov 2025) with DuckDB execution; `pg_duckdb` and Trino/Spark are mature; `pg_analytics`/`pg_lakehouse` (ParadeDB) is **discontinued — do not build on it**; Iceberg v3 features (row lineage) are real but early. North stars for PIT done right: **Databento** (immutable, point-in-time instrument definitions) and academic **CRSP PIT** datasets.

---

## 6. The connector model — flavours, capability-gating, self-healing

This is where the owner's "modular, community, at-the-user's-risk" vision becomes concrete and safe.

- **Two connector flavours, one interface:** an **official-API** wrapper, *or* — for brokers with no API (e.g. Degiro) — a **browser/UI-automation** module (community, explicitly "at your own risk"). Same canonical interface, different backend.
- **Capability-gated verbs (the key safety design):** a connector *declares which verbs it implements* — **read** verbs (`read_positions`, `read_transactions`, `get_quote` — the safe, common 90%) vs **execute** verbs (`place_order`, `cancel_order` — dangerous, opt-in, separate trust tier). This formalises "just the API or community-at-risk depending on the broker," and cleanly separates the safe community surface from the dangerous one.
- **Execution is a different trust tier, not just another verb.** A bad *read* connector shows a wrong number; a bad/malicious *execute* connector drains an account — and an open registry of order-placing modules is a wallet-drainer's dream. Execution connectors need: signing/provenance verification, sandboxing, hard deterministic guardrails (size caps, allow-lists, dry-run, mandatory confirmation, kill-switch), and human-in-loop until trust is earned.
- **Self-healing connectors via LLMs — our novel edge.** The tax that kills connector projects is maintenance (brokers change formats; adapters rot). Ship a **connector generator** (point an agent at API docs → scaffold against a **conformance test suite**) and **self-healing** (broker changes → agent regenerates the adapter, conformance tests gate the merge). This dissolves the exact tax that constrained ccxt-style projects and is far easier now with agents.
- **Community owns the long tail** (ccxt/OpenBB pattern): maintainers scale linearly with sources; the connector layer must be open or the ecosystem won't compound.

---

## 7. Business model — what works, what's fraught

From the OSS-fintech stream:
**Works:** open-core + **hosted/governed compute** SaaS (Ghostfolio Premium, OpenBB Workspace — funds pay for governance/compliance/on-prem, not features); **affiliate/builder rev-share on order flow** (ccxt ~1 bps — low-friction, aligned, legally clean for a connector platform); **self-originated curated data** as a service.
**Fraught — avoid:** **reselling licensed third-party data** (bled Maybe's Synth; forces per-file licensing; margin-poor and legally constrained — monetise data we *originate*, not vendor feeds); **pure B2C DIY personal finance** (hard to monetise, infra-heavy — lead with B2B/pro or self-host); **holding back the connector layer** (must be open/community or it won't take off — monetise the curated data + governed compute on top).

---

## 8. Build order & first milestone (dogfood-first)

The architecture itself forces the order: **read → reconcile → analyse → suggest → execute.** You cannot safely auto-execute a portfolio you can't yet measure correctly, and the read/ledger layer is the prerequisite for trustworthy execution. The owner most wants auto-execution; it is therefore *last in the build order and first to get hurt by skipping the rest*.

**Milestone −1 (value proof with existing tools — do this FIRST):** before designing or building anything, dogfood **OpenBB** (and ccxt for crypto) end-to-end against *one real question the owner can't easily answer today* — e.g. correct consolidated multi-currency P&L under his own cost-basis method, ideally via OpenBB's agent/MCP path. Three outcomes, all valuable: (1) it works → value gained with zero build, maybe a contribution upstream; (2) it half-works → the precise friction is the validated, narrow gap → build *only that*, as an extension on top; (3) it can't → now there's *evidence* (not a guess) that the foundation is missing and the schema/connector work below is justified. **No platform-building until this proof exists.**

**Milestone 0 (the keystone, on paper — only if Milestone −1 justifies building):** the **canonical schema** for the read verbs across the 2–3 asset classes the owner actually holds + the bitemporal/append-only Postgres modelling. No code until this is right.

**Milestone 1 (first working dogfood):** one connector (start with whatever the owner holds that has a real API; **crypto via ccxt is the trivial first full read→execute loop** with testnets, so it can even prove the execute path safely) → ingest to the canonical ledger → expose ~3–4 read tools over a thin MCP server → ask any agent "what's my real P&L / exposure now," computed deterministically, explained by the LLM. Packaged as library + MCP + SKILL.md to validate the layering.

**Milestone 2+:** add connectors (incl. the Degiro browser-automation, at-risk flavour), reconciliation correctness, then decision-support, then — behind the execution trust tier and guardrails — auto-execution on paper/tiny size first.

---

## 9. Risks & open questions

- **MCP security is unsolved** (tool poisoning, prompt injection via tool metadata — CVE-2025-54136 class). Our MCP layer must pin/verify connector provenance and never auto-merge untrusted third-party metadata. (`01`)
- **Execution safety/regulatory:** auto-execution and offering execution tooling to others raises real money risk and regulatory exposure (MiFID/SEC). Start read-only, self-only; earn execution.
- **The Degiro beachhead is fragile by nature** (reverse-engineered/browser-automation, ToS-risky). Good wedge for demand, bad to depend on for reliability — frame it as community/at-risk.
- **Adoption ≠ a repo.** Open-source is distribution only if DX is excellent and the free core installs in one step (OpenBB's 4k-stars-in-24h, Ghostfolio's one-Docker-Compose).
- **Open question — which brokers does the owner actually hold?** This picks Milestone 1's first connector. (Still open as of this date.)
- Treat secondary adoption stats and giant TAM figures as indicative, not verified (flagged throughout `01` and `05`).

---

## 10. Future-proofing — the durable bets

1. **Own the data layer, rent the interface.** Apps and chatbots churn; a correct, unified, PIT financial ledger compounds. As agents proliferate, the scarce thing is *correct unified financial state + the connectors to reach it* — own that.
2. **The typed core library is the contract.** MCP, Skills, A2A, code-execution are swappable adapters. Build so the core works whether agents call it via MCP tools *or* generated code.
3. **Deterministic core, probabilistic edge.** Numbers and orders are code (auditable, correct-to-the-cent); the LLM only explains and explores. A single wrong P&L destroys trust permanently.
4. **Append-only / bitemporal from day one.** The one schema decision you can't retrofit.
5. **Protocol-over-product, capability-declared.** Expose declarative capabilities; ride whichever agent/protocol wins.
6. **Self-healing, community-owned connectors.** Turn the maintenance tax into an agent-automated, community-scaled strength.
7. **Dogfood relentlessly.** Build only what user-zero actually uses; that's how the real need is discovered instead of guessed.

---

### Raw research (full reports + sources)
- `research/01-mcp-skills-libraries.md` — MCP vs Skills vs library vs code-execution; the layering recommendation.
- `research/02-oss-fintech-landscape.md` — OpenBB/ccxt/Ghostfolio/Maybe/quant frameworks; traction, business models, white space.
- `research/03-canonical-schema.md` — FIBO/CDM/FIX/ISO20022/FIGI/beancount; borrow-don't-invent schema recommendation.
- `research/04-pit-bitemporal-iceberg.md` — point-in-time, bitemporal modelling, Postgres→Iceberg staging.
- `research/05-data-value-and-connectors.md` — value of data by trading style; broker/market-data/news connector landscape.
