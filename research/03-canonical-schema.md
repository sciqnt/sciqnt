# 03 — Canonical Cross-Asset Schema: Industry Standards

## 1. FIBO (Financial Industry Business Ontology)
OWL 2 DL ontology stewarded by EDM Council, standardized via OMG. Defines the *concepts and relationships* of finance (instruments, entities, contracts, dates, agreements) as a formal, machine-reasoned ontology. Strength = *vocabulary and semantic relationships* — a rigorous account of what a "debt instrument" or "equity" *is*.
**Practical reality:** large, abstract, built for enterprise data harmonization and regulatory interoperability, not for powering an app database; native deployment needs OWL tooling + triple stores. **Borrow FIBO's taxonomy and naming, not its machinery** — use it as a dictionary to name/classify entities, ignore the reasoning layer. That a third party (FIB-DM) sells a relational transform of FIBO is itself the signal it's not directly usable as an app schema.

## 2. ISDA CDM (now FINOS CDM)
Machine-readable/executable model of products, trades, and *lifecycle events*, in the Rune DSL (formerly Rosetta), now a FINOS project (v5.x). Standout = the **event model**: trades evolve through discrete, typed lifecycle events (execution, amendment, termination, novation, allocation, exercise) driving state transitions. Covers OTC derivatives, cash securities, SFTs, commodities, ETDs. Adopters (JPMorgan, BNP, DTCC) use it mainly for regulatory reporting.
**For sciqnt:** borrow the *event-sourcing concept* (position = fold of an immutable, append-only event log) — exactly right for corporate actions, splits, lot tracking. But full CDM, Rune DSL, derivatives depth are over-engineered for retail/multi-asset (Broadridge flags adoption complexity). Borrow the pattern, not the artifact.

## 3. FpML, FIX, ISO 20022
Messaging/protocol standards, each strong in one lane:
- **FpML** — XML for OTC derivative *product definitions*; borrow its decomposition of a contract into legs/schedules/payouts for options/swaps.
- **FIX** — de facto *trading/execution* protocol (orders, fills, executions). Borrow enums/field semantics for order side, order type, time-in-force, execution reports; good day-count/coupon fields (`CouponDayCount`).
- **ISO 20022** — universal scheme for *payments and securities settlement* (and corporate actions via `seev.*`). Borrow structured cash/payment modeling + ISO data dictionary (currency, dates, party roles). ISO 15022 (MT564/565/566) remains incumbent for corporate-action notifications but is semi-structured text; ISO 20022 `seev.031` is the structured successor.

Take *concepts and enumerations*, not the wire formats.

## 4. Instrument Identification
No single identifier wins — use a layered strategy:
- **FIGI (OpenFIGI)** as internal join key / spine — free open API, OMG/ANSI standard, covers active+inactive, maps from ISIN/CUSIP/SEDOL/ticker; useful hierarchy (composite vs share-class/exchange-level FIGI).
- **ISIN** as primary external/global ID; **CUSIP** (US/CA), **SEDOL** (UK) as regional aliases.
- **MIC** (ISO 10383) to pin the trading venue.
- **CFI** (ISO 10962) for machine-readable asset classification (don't hand-roll asset taxonomy — CFI's 6-char code encodes category/group/attributes).
- **OSI 21-char symbology** for listed options; synthetic key for OTC/crypto.
**Recommendation:** one `Instrument` entity with stable internal UUID + an `identifiers` map keyed by scheme. Resolve/dedupe via OpenFIGI. **Never make ISIN the primary key** — FX, some crypto, OTC lack one.

## 5. The Hard Cross-Asset Bits
- **Corporate actions:** typed lifecycle events on instrument/position (dividend, split w/ ratio + ex/record/pay dates, merger, spin-off → multi-leg cash+security). Use ISO event-type taxonomy (60+ types, mandatory/voluntary/choice flag). Replay events to derive adjusted positions + cost basis.
- **Bonds:** `coupon_schedule`, `day_count_convention` (Act/Act, 30/360, Act/360); accrued interest = f(last coupon → settlement); keep clean vs dirty price distinct.
- **Options/futures:** contract terms as fields — underlying ref, strike, expiry, call/put, exercise style (American/European), `multiplier` (e.g. 100), settlement (physical/cash).
- **Multi-currency & FX:** every monetary value carries explicit currency; FX trade = two cash legs; store FX rate used per transaction; separate **capital gain from currency gain** (Sharesight does this). Fix a portfolio base currency for reporting.
- **P&L / cost basis:** adopt beancount's model — double-entry postings, positions held *at cost as lots*, pluggable booking (FIFO/LIFO/HIFO/average/specific-lot). Realized P&L on close = proceeds − matched-lot cost (commissions netted); unrealized = mark-to-market of open lots. Cost-basis method = per-account/jurisdiction setting; wash-sale = later overlay.

## 6. Lessons From Products
- **beancount** — gold standard for the *accounting core*: immutable plain-text transactions w/ balancing postings, commodities, lots at cost, deterministic FIFO/LIFO/HIFO/average. Steal wholesale.
- **OpenBB** — *pragmatic standardization*: Pydantic v2 standard models, `lower_snake_case`, schema = intersection of fields shared across providers, identical output regardless of source. Right philosophy for an agent-native schema.
- **Ghostfolio** — simple effective app schema: flat `Activity` records (type, symbol, quantity, unitPrice, fee, currency, dataSource, date) folded into derived `PortfolioPosition`. Proof a thin transactional model scales to a real product.
- **Sharesight** — average-cost base, automatic dividends/FX, capital-vs-currency-gain separation, fixed base currency.

## Pragmatic Recommendation for sciqnt
**Borrow, don't invent:**
- Vocabulary/taxonomy → FIBO names + CFI codes.
- Identifier spine → FIGI internal key + multi-scheme alias map (free OpenFIGI).
- Event/lifecycle → CDM's idea (immutable typed events → derived state), implemented simply.
- Accounting core → beancount's double-entry + lots + pluggable booking.
- API/schema discipline → OpenBB's Pydantic, snake_case, provider-intersection.
- Enums/semantics → FIX (orders/executions), ISO 20022 (cash/settlement/corporate actions).

**How thick to start (thin core, typed extensions):** ~6 core entities — `Instrument`, `Position`, `Transaction`/`Activity`, `Cash`, `CorporateAction`, `Price` — where `Transaction` is the immutable event log and `Position` is *derived*. Asset-class specifics (option strike/expiry, bond coupon schedule, FX legs) live in a typed `instrument_terms` sub-object keyed by CFI category. Currency mandatory on every money value from day one.

**Top pitfalls:** (1) over-engineering with full FIBO/CDM (OWL reasoners / Rune DSL would sink a startup — mine for concepts only); (2) ISIN (or any single ID) as primary key; (3) positions as mutable rows (must be derived from immutable event log); (4) hard-coding one cost-basis method or single currency; (5) corporate actions as ad-hoc patches not first-class events; (6) premature derivatives depth before equities/ETFs/cash/bonds.

## Sources
- FIBO: https://edmcouncil.org/financial-industry-business-ontology/ · https://github.com/edmcouncil/fibo/blob/master/ONTOLOGY_GUIDE.md · https://fib-dm.com/finance-ontology-transform-data-model/
- CDM: https://cdm.finos.org/docs/cdm-overview/ · https://cdm.finos.org/docs/product-model/ · https://cdm.finos.org/docs/process-model/ · https://github.com/finos/common-domain-model · https://www.broadridge.com/article/challenges-in-a-common-domain-model-for-securities-finance
- FpML/FIX/ISO20022: https://www.tradeheader.com/consulting-fpml · https://www.iso20022.org/sites/default/files/2022-02/introtoiso20022.pdf
- Identifiers: https://www.openfigi.com/api/documentation · https://www.openfigi.com/api/overview · https://tamer-khraisha.medium.com/financial-data-engineering-series-3-n-financial-identifiers-99a32a6eb321
- Corporate actions: https://www.biqh.com/blog/iso-20022-corporate-actions-in-practice/ · https://isitc.org/wp-content/uploads/Corporate_Actions_Market_Practice_v8.0_Dec2022.pdf
- Day count / coupons: https://en.wikipedia.org/wiki/Day_count_convention · https://www.onixs.biz/fix-dictionary/5.0.sp2.ep264/tagnum_1950.html
- Options symbology: https://en.wikipedia.org/wiki/Option_symbol
- Cost basis/P&L: https://www.ibkrguides.com/reportingreference/reportguide/realized_unrealizedperformancesummary_default.htm · https://help.portfolio-performance.info/en/concepts/cost-methodology/
- beancount: https://beancount.github.io/docs/how_inventories_work.html
- OpenBB: https://openbb.co/blog/the-openbb-platform-data-pipeline
- Ghostfolio: https://deepwiki.com/ghostfolio/ghostfolio/4-portfolio-management
- Sharesight: https://www.sharesight.com/blog/value-your-investments-in-any-currency-with-sharesight/
