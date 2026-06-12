# sciqnt — Project Context

**Status:** Milestone 1 in progress. Canonical schema (`core/sq_schema`) + compute (`core/sq_compute`) + analytics (`core/sq_analytics`) + market-data overlay (`core/sq_market_data`) all shipped. Working bundles: `sq-degiro` (CSV history + live TUI, cent-perfect reconciled), `sq-fx-ecb`, `sq-yahoo`, `sq-openfigi`, `sq-config`. Read `STATE.md` for the in-flight state and next deliverable.

## What this is
An open, agent-native, **cross-asset financial-data layer**: one canonical, point-in-time-correct schema (instruments, positions, transactions, cash, corporate actions, prices), fed by an open ecosystem of **community-maintained connectors** (each broker / exchange / data source), exposed to *any* AI agent (Claude, ChatGPT, openclaw) via thin protocol adapters. Deterministic code computes the numbers; LLMs reason and explain.

Owner (DavideGCosta) is **user-zero** — building a personal quant/"fund" on it — but every piece is reusable infrastructure others build on (the OpenBB/Supabase outcome).

**Naming:** this project is branded **sciqnt** and lives on disk at `~/Projects/sq/` (the folder is `sq` to avoid colliding with `~/Projects/sciqnt`, the older Next.js chatbot it reclaims the name from — that chatbot is now legacy). Code prefix is `sq_` (packages) / `sq-` (module bundles); the CLI command is `sciqnt`; config lives at `~/.config/sciqnt/`. Was formerly "p-zero" — fully rebranded 2026-06-01.

## Start here
- **`STATE.md`** — living session handoff: last commit, what's verified, next concrete deliverable. Read FIRST to pick up where the previous session left off. Update at session end from real state, never memory.
- **`AGENT_GUIDE.md`** — durable agent-portable codebase guide (read by any code-execution agent — Claude Code, Codex via the `AGENTS.md` symlink, OpenClaw, etc).
- **`FOUNDATION.md`** — the apex document: thesis, the universal-unit model (one primitive, three roles: source/compute/action), the ecosystem map, and the 13 Founding Articles. Read this first for the worldview.
- **`PRINCIPLES.md`** — the operating constitution (18 principles across value/AI-boundary/contract/data/trust). How the Articles cash out. Decide in their direction.
- **`research/connector-framework.md`** — how a connector is designed (skill bundle + capability tree + flavours + local-first + conformance + generator subagent).
- **`research/synthesis.md`** — THE reasoning document. Vision, where-we-add-value, library/MCP/skills layering, canonical schema, PIT data, business model, build order, risks, future-proofing.
- **`research/release-plan.md`** — distribution (PyPI; uv tool install), ship-on-green-per-bundle cadence, three-audience discoverability (agents: llms.txt/SKILL-in-package/MCP Registry; humans: GitHub-as-SEO + FINDINGS long-tail; community: launch drumbeat), sequenced with owner gates. Engineering mechanics: `research/release-framework.md`.
- **`research/tui-experience.md`** — cutting-edge TUI/CLI-agent UX principles + the sciqnt redesign plan (full-screen app on the alternate screen; keybinding conventions; the migration path off the current line-by-line model). The `/maintenance` audit enforces it.
- **`research/llm-native-integration.md`** — the bidirectional "agents inside every component" design: detect installed agent CLIs + a preferred-agent launcher (default-browser-style), launch an agent headlessly with on-screen context ("use agent to X"), Skills/MCP as the shared substrate, and the connector-generator→conformance→upstream-PR flagship. Honest split: mechanics verified vs trust/CI = design synthesis. Not yet built.
- `research/01..05-*.md` — the full grounding research with sources (MCP/skills; OSS-fintech landscape; canonical schema standards; PIT/bitemporal/Iceberg; data-value + connector landscape).

## Load-bearing decisions (don't relitigate without cause)
- **Value-first, not gap-racing (governing principle).** The goal is to *generate and prove value*, not to claim a market position. Do NOT build to close a gap we haven't proven exists. **Contributing to / building on OpenBB (or others) is a first-class success outcome, not a fallback.** Let the measured *shortfall* of existing tools against a real need define any gap worth building. The "position is open/narrowing" is context, not urgency.
- **Build-vs-contribute is decided by Milestone −1** (dogfood OpenBB against a real question first). No platform-building until that value proof exists.
- **Value is NOT alpha-in-a-box.** Monetise correctness, convenience, personal-state insight, connector reach, self-originated data. Never resell licensed feeds (killed Maybe).
- **Layering, not "MCP vs Skills":** deterministic **core library** (the durable contract) → thin **MCP server** (live access, auth, cross-vendor) → **SKILL.md** (how-to). The library is what survives protocol churn.
- **Canonical schema = borrow, don't invent.** FIGI spine + CFI classification; beancount-style lots + pluggable cost-basis; CDM event-sourcing concept (position = fold over immutable transaction log); OpenBB-style Pydantic/snake_case. ~6 entities to start; currency mandatory everywhere.
- **Data: Postgres-now, Iceberg-later — but bitemporal/append-only from day one.** Valid-time + knowledge-time on every fact is the one irreversible decision. PIT correctness is non-negotiable for the quant side.
- **Modular & host-agnostic (moto).** Every unit stands alone (one connector / the schema lib / the compute — usable without the rest); the whole ecosystem runs in ANY agent host (Claude Code, Codex, OpenClaw, …). No in-house runtime, no central server required (registry optional). Core is host-neutral; each host gets a thin adapter. Coherence anchor = the thin contract + conformance harness.
- **Connector = a local-first skill bundle** (manifest w/ declared capability tree + deterministic scripts + SKILL.md + per-user health state). See `research/connector-framework.md`.
- **Text/CLI-first ("TUI is king").** Flavour preference: programmatic API → file/CSV → CLI → **browser only as last resort**. Flexible & declared, never hard-wired. (For Degiro: CSV / `degiro-connector` first, NOT browser.)
- **Sovereignty: the user owns the data/keys** (the test: "fire us and keep everything"). Local-first by default (no platform credential custody); a cloud option is OK *only* if the user still owns/controls the data.
- **Composable building blocks (`research/composable-architecture.md` — the build doctrine).** Four rules on every build: (1) data first — every capability ships versioned structured data (`--json`, Decimal-as-string); renderers (TUI, web, charts) are adapters, never the product; (2) declare → derive — components state their identity once (TAB_SURFACES, manifests), frameworks derive the rest; (3) discovery over enumeration — surfaces self-describe (`--help`, `--describe`), no hand-maintained maps; (4) facts over choreography — agents get honest state, not stage directions. Litmus: a web frontend must never need to parse rendered text; a new block must touch only its own declaration.
- **Trust the agent + simple primitives; resist over-engineering.** An agent with `grep` beats bespoke RAG; a CLI beats a framework. Engineer only where determinism/correctness demand it (the money math) — applies to the probabilistic edge, never the deterministic core.
- **Convenience is a feature, not a luxury — but bounded.** The safe/sovereign/correct path must also be the effortless one; engineer until they're the same path. Convenience NEVER overrides sovereignty, correctness, or consent ("it's more convenient" is the classic excuse for custody/auto-action/lock-in). It's also the precise name for the friction that justifies graduating off a flavour (e.g. manual CSV re-export → programmatic).
- **Capability-based security, enforced in code.** User grants + caps per capability; a deterministic policy gate enforces every call (never prose, never the model). Read wide; execute = separate higher trust tier (signing, sandbox, caps, human-in-loop). Trust earned via the conformance suite; `last_successful` = passed conformance.
- **Growth via generator subagent:** platform ships the contract + harness + generator, not the long tail of connectors; users build unsupported brokers themselves.
- **Self-reflection (do this before claiming done):** re-evaluate every solution against `PRINCIPLES.md` — which it honours, which it bends, what's still hardcoded/manual/uncovered. State gaps explicitly ("honest gaps" habit). Work-level analogue of conformance.
- **Build order:** read → reconcile → analyse → suggest → execute. Owner most wants auto-execution; it's last and most-dependent on the rest.
- **Self-healing connectors via LLMs** (generator + conformance tests) = the novel edge against the connector-maintenance tax.

## Open questions
- Which brokers/exchanges does the owner actually hold? → picks Milestone 1's first connector. (Crypto via ccxt = trivial first full read→execute loop.)

## Conventions
- Code home: this dir (`~/Projects/sq/`). `src/` for code, `research/` for the scoping docs.
- Tech leanings (not yet committed): Postgres serving + (later) Apache Iceberg; Python; Pydantic for the schema.
- See `~/Projects/CLAUDE.md` for the machine-wide registry and ground rules.
