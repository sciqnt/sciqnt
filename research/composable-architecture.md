# Composable architecture — building blocks for a million agents

The operating doctrine for HOW every sciqnt piece is built, distilled from the
agent-summon redesign (2026-06-12) and the principles (FOUNDATION Articles;
PRINCIPLES: modular & host-agnostic, trust-the-agent, layering). The target
picture: **millions of agents and people contributing, building, and consuming
components independently** — inside sciqnt, inside Claude Code / Codex / any
host, in web frontends we never built. We do not build those consumers up
front; we build every piece so they're possible without rework.

## The four rules

### 1. Data first; presentation is an adapter
Every capability's durable output is **structured data on a versioned schema**
(`sciqnt --json` → `sciqnt.portfolio/v1`, `sciqnt.history/v1`; Decimal-as-
string — precision survives the wire, consumers opt into floats knowingly).
The TUI's tables and braille charts are ONE renderer over that surface; a
React chart, a notebook, another agent are peers, not ports. **Litmus: if a
web frontend would have to parse our rendered text, the build is wrong.**
Rendered text exists for humans; data exists for builders.

### 2. Declare → derive (config-like builds, no hand-wiring)
A component states its identity ONCE — a tab declares its CLI surface
(`TAB_SURFACES`), a bundle declares its capabilities (`manifest.yaml`), a
screen's summon facts are captured by the view layer (`tabbed_view.last_view`)
— and everything downstream (reproduce commands, summon handoffs, validation,
docs) **derives**. Adding a block = adding a declaration; zero parallel
artifacts to keep in sync. Litmus: count what a new tab/connector/screen must
touch — if it's more than its own declaration + body, the framework is
leaking hard-coding.

### 3. Discovery over enumeration (self-describing surfaces)
Consumers learn the surface by ASKING it — `sciqnt --help`, `--list`,
`<bundle> --describe/--commands`, `modules find` — never from a hand-written
map that drifts. Skills teach the worldview and HOW to discover; the contract
lives in the thing itself. (An agent with `--help` beats a bespoke map for
the same reason an agent with grep beats bespoke RAG.) Tests pin the
self-description (`test_summon.TestSelfDescribingCLI`), not prose copies.

### 4. Facts over choreography (AI-native integration)
When an agent enters, hand it **honest state** — where the user is, what's on
their screen (verbatim context file), the command that reproduces it, why the
summon happened — and let it decide behaviour. No stage directions, no prose
classifiers ("if browsing do X, if debugging do Y"). Calibration emerges from
truthful context; scripted turns rot. Same doctrine as the coordinator's
no-rigid-rules rule — it's one principle, applied everywhere.

## What this rules out
- Computing values inside rendering code (data must exist before paint).
- Per-call-site integration wiring (a screen that must remember to assemble
  its own agent context is a bug in the framework, not the screen).
- Hand-maintained surface maps in prompts, skills, or docs.
- "TUI-only" features: anything worth a screen is worth a `--json` form —
  or an explicit, stated reason why not (honest gaps).

## Where we honour it today (anchors)
- `sq_platform.aggregated`: `--json` data surfaces — `sciqnt.portfolio/v1`,
  `sciqnt.history/v1`, `sciqnt.exposure/v1`, `sciqnt.news/v1`,
  `sciqnt.flows/v1` (`TAB_DATA_SURFACES` dispatches `--json --tab X`); every
  tab's compute is split from its render (`_flows_data`, `_portfolio_news`,
  the aggregator exposure calls). `TAB_SURFACES` + `view_command`
  (declare→derive); `register_tab` = the bundle-contribution seam (a
  contributed tab gets surface, summon command, `--tab` validation for free;
  a failing contribution degrades visibly, never poisons the core view).
  `--account` scopes the FETCH (a component query never touches unrelated
  brokers).
- `sq_tui.render_history(payload)`: the TUI chart is a CONSUMER of the
  history/v1 data surface — `history_chart_block` builds the payload first,
  then renders it through this adapter. A web chart consuming the identical
  payload is a peer, not a port. (Proof of rule 1 in running code.)
- `sq_platform.insights`: the agent → app PUSH channel — append-only local
  JSONL (`sciqnt insight add/list/clear`, `SQ_INSIGHTS_PATH` override),
  findings carry their reproduce-command (`--ref`); unseen insights surface
  once on the home (✦ row). Pull + push are now both closed loops.
- `sq_tui.tabbed_view.last_view`: the view layer captures summon facts;
  `sq_platform.home.summon_prompt` ships facts only (screen.txt verbatim);
  `HOME_MENU` declares the home actions.
- `sq_skills`: teaches discovery (`--help`), the data surface (`--json`),
  and the push channel (`sciqnt insight add`).
- Bundles: manifest + SKILL + FINDINGS + bin `--describe/--commands` were
  already declare→derive + self-describing — the connector framework was the
  template; the app layer now matches it.
- **Honest packaging (2026-06-12)**: every core package and bundle is a real
  distribution (`sciqnt-*` dist names, `sq_*` imports unchanged) with
  dependencies that match its actual imports, tied by the root uv workspace
  (single `uv.lock`). PROVEN standalone: a fresh venv +
  `pip install ./modules/sq-degiro <its declared closure>` → `import
  sq_degiro` works outside the repo, 113 bundle tests green (live-flavour
  tests SKIP without the `[live]` extra instead of erroring). "Units stand
  alone" is now literal, not aspirational.

## Known debt (next increments, in value order)
1. **Core tabs through the registry**: contributed tabs register; the
   platform's own tabs are still composed inline in `build_aggregate`.
   Harmless (they're the platform's), but migrating them would make the
   registry the ONLY path and let a config reorder/disable them.
2. **Chrome as declarations**: `HOME_MENU` declares the actions, but screen
   chrome (banner, agent row, layout) is still code. Worth a declarative
   pass only when a second shell (web) exists to consume it.
3. **summary/positions/detailed as standalone surfaces**: today they live
   inside portfolio/v1 (correct — they're projections of it); split only if
   a consumer needs them independently versioned.
4. **Insight lifecycle**: seen/clear is per-machine; if insights ever sync
   across devices, the store needs identity — design then, not now.
5. **Publish (the discoverability half)**: the packages are real but live
   only in this repo — an agent searching the web finds NOTHING until the
   first release (PyPI `sciqnt-*` + public GitHub). OWNER-GATED: blocked on
   the repo scrub (release-framework checklist step 1). Once published,
   `pip install sciqnt-degiro` is the whole story for a user who wants only
   that connector, and a searching agent finds the PyPI page + README +
   SKILL.md.
