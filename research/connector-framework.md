# sciqnt — Connector Framework

How a "connector" is designed. Instantiates the principles in `../PRINCIPLES.md`. Shape: **the LSP / Terraform-provider model, made local-first and agent-native.** A thin stable contract in the middle; an unbounded ecosystem of connectors around it; the host grants and enforces capabilities.

### 0. Modular & host-agnostic (the framing)
There is **no in-house runtime** any more than there is an in-house chat. The "product" is a *contract + conformance harness + generator + standalone packages* — not a server or app you run. Two consequences:
- **Granular independence:** every unit works alone (a single connector with no platform; the schema lib with no connectors; the compute with no registry). Composition is opt-in.
- **Host portability:** the same units run inside *any* agent host — Claude Code, Codex, OpenClaw, next year's thing. The core is **host-neutral** (plain scripts + manifest + SKILL.md, text/CLI-first ⇒ runs anywhere); each host gets only a **thin adapter generated from the same manifest** (a `SKILL.md` for Claude, a tool spec for Codex, etc.) — so you keep portability *and* exploit each host's strengths. Even the registry is optional: point a host at a connector in a local folder or git URL and it runs.
- **Coherence anchor:** the only things every module must share are the *thin contract* (canonical schema + verbs) and the *conformance harness*. Modularity is safe *because* the contract is thin — a fat contract would make independence impossible.

## The layers

### 1. Runtime — local-first, on the user's device
Creds stay with the user (they own them). The agent runs locally. This removes platform credential custody (the liability/regulatory nightmare) and makes the hard brokers tractable — for Degiro (no API + 2FA), driving an already-logged-in session works *only because* it's local. Bring-your-own-keys throughout.

### 2. Contract — the thin canonical interface
The stable thing everything hangs off: the verb set (`read_positions`, `read_transactions`, `get_quote`, `place_order`, `cancel_order`, …) typed against the canonical schema (`research/03-canonical-schema.md`). Small and slow-changing. **This is the durable asset.**

### Bundle layout on disk (the canonical structure)
A unit is one folder that is simultaneously a **git-repo-ready package**, an **agent skill**, and a **pip-installable library** — one artifact, three consumers.
```
modules/sq-<name>/
  SKILL.md          # agent-facing: behaviour, when/how to use (skill entry)
  manifest.yaml     # machine-readable: capability tree, flavour, risk tier, schema version
  FINDINGS.md       # LIVING: quirks · caveats · conformance results · open issues (mandatory)
  src/sq_<name>/    # deterministic code (importable; CLI entry); text-first
  bin/sq-<name>     # executable wrapper (the platform↔bundle contract — see below)
  tests/conformance # the unit's conformance cases; fixtures are SYNTHETIC (never real personal data)
  pyproject.toml    # independently installable; (later) pins sq-core contract major version
```

### Canonical-schema substrate (`sq_schema`) — Milestone 0
Every connector translates its dialect INTO the canonical shape defined in **`core/sq_schema/`** — and consumers read the canonical types, never the raw broker JSON. Six entities (v0 post-validation): `Bitemporal` mixin (`valid_at` + `observed_at` on every fact), `Account` (broker + currency base — fiat or crypto), `Instrument` (identifier map + asset_class + listing_currency + optional `terms` slot for derivatives), `Position` (P/L pre-decomposed: `unrealized_product_pl_base` + `unrealized_currency_pl_base` + `realized_product_pl_base` + `realized_currency_pl_base`, derived fields for sums), `CashBalance` (per-currency amount + optional base-currency conversion), `FxRate` (a single bilateral observation, `from_currency` × `rate` = `to_currency`). Money is `Decimal`. Currency codes accept fiat (ISO 4217) AND crypto (BTC/USDT/USDC/...). The whole thing is wrapped in a `PortfolioSnapshot` with FK integrity validation. **Conformance harness** in `sq_schema.conformance.check_snapshot()` catches semantic violations (duplicate positions/cash, negative cost basis, closed-position invariant breaks, Decimal precision pollution) — every connector calls it in tests to self-certify. **FxRateProvider** is a runtime-checkable Protocol; real implementations live in connector bundles (`sq-fx-ecb`, `sq-fx-yfinance`, ...). Design + scope boundaries: `milestone-0-canonical-schema.md`; cross-asset validation: `milestone-0-cross-asset-validation.md`. **Out of scope for v0** (declared, not silent): Transaction / lots / FIFO-LIFO booking, Price time series, CorporateAction, typed `OptionTerms`/`BondTerms` sub-models (use the `terms` dict slot until a real connector forces them), persistence (Postgres/Iceberg). The rule for new bundles: **the file containing dialect knowledge is `canonical.py`; any other consumer must read normalized types only.**

### Compute substrate (`sq_compute`) — fold Transactions into Positions + cash
**`core/sq_compute/`** is where the deterministic money-math lives. Pure functions: same inputs → same outputs, no I/O. Three flagship functions:
- `fold_position(account_id, instrument_id, base_currency, transactions, *, method, asof) → Position` — CDM event-sourcing: a Position is what you get when you fold the immutable Transaction log. Pluggable `CostBasisMethod` (FIFO / LIFO / AVG); same realised-P/L decomposition (`product` vs `currency`) as the live unrealised path so closed and open lots speak the same language. `asof` trims the stream to a historical instant — PIT correctness for free.
- `fold_cash_balances(transactions, *, asof) → dict[ccy, Decimal]` — per-currency cash ledger; the complement of fold_position. Sum across a complete log = current balance.
- `fold_cash_by_type(transactions, *, currency, asof) → dict[type, Decimal]` — per-`TransactionType` breakdown for structural cash reporting (deposits / dividends / fees / etc.) without keyword string-matching.

**The pnl.py orchestrator (`sq-degiro`).** Since step 8, `sq_degiro.pnl.compute()` is a thin orchestrator over the canonical adapters + these folds. No bundle now carries its own version of the realised-P/L summation or cash reconciliation logic; the deterministic core lives in one place and the bundle code is a wrapper. Pinned by 209 tests including the cross-path agreement tests (steps 6 + 7) which proved equivalence before the refactor landed.

What `fold_position` populates on the returned Position: `quantity`, `break_even_price_local`, `cost_basis_base`, `realized_product_pl_base`, `realized_currency_pl_base`. What it DOES NOT populate: `last_price_local`, `value_base`, `unrealized_*_pl_base` — those require a current market price (a separate concern; live overlay belongs to a price provider). This split is deliberate: the fold is auditable history, the price overlay is a separate substrate, and a divergence between them is a real bug we want to be able to see.

### Market-data substrate (`sq_market_data`) + first provider (`sq-yahoo`)
**`core/sq_market_data/`** sits parallel to `sq_compute` — where fold_position yields auditable historical Positions (cost basis + realised P/L, fees-inclusive), this substrate overlays a current market price to populate the LIVE side: `last_price_local`, `value_base`, `unrealized_*_pl_base`. Pure compute given (positions, price quotes, fx rates); the provider does the I/O. Single function: `overlay_prices(positions, instruments, *, provider, base_currency, ticker_map=None, fx_provider=None) → list[Position]` — non-destructive (returns new Positions; input unchanged). Closed positions pass through unchanged. Unknown tickers also pass through (silent degradation — overlay is best-effort).

**`sq_schema.Price`** is the canonical price observation entity (Decimal + bitemporal + source-attributed); **`sq_schema.PriceProvider`** is the runtime-checkable Protocol every market-data source implements (`get_price(ticker) → Price | None`). First concrete implementation: **`sq_yahoo.YahooProvider`** wraps the existing `fetch_quote` so the rest of the project doesn't need to know about Yahoo's dict shape. Add a second provider (Polygon, Tiingo, etc.) by writing a class implementing the protocol — no other code changes.

### FX rate substrate (`sq_fx`) + first provider (`sq-fx-ecb`)
**`core/sq_fx/`** is the lookup substrate. Consumers call `sq_fx.convert(amount, from_ccy, to_ccy)` and the substrate resolves an installed `FxRateProvider` (explicit arg → `sq_config['fx_provider']` → first-installed default). Returns `None` when no rate is available — callers degrade visibly (e.g. summary shows the amount in source ccy with a `(no rate)` note) rather than fabricating.

**`modules/sq-fx-ecb/`** is the first concrete implementation: ECB EUR-cross daily reference rates (public, no auth, no rate limits worth fearing). Triangulates non-EUR pairs via EUR. Cache TTL 12h for daily / 24h for 90-day history. XDG-located cache (`~/.cache/sciqnt/fx-ecb/`); user-owned, survives `git clean -fdx`. Stdlib only — no `requests` dep.

To add a second provider (e.g. `sq-fx-yfinance` for intraday): drop a bundle that exports a class implementing `FxRateProvider`, register it in `core/sq_fx/__init__.py::_PROVIDERS`, ship. The substrate's lookup chain picks it up automatically.

### Shared user-config substrate (`sq_config`)
User-level settings live in **one** JSON file (`~/.config/sciqnt/config.json` by default; `SQ_CONFIG_PATH` overrides for tests/CI). Bundles read settings via `sq_config.get(key, default)` or convenience accessors like `sq_config.display_currency()` — they MUST NOT hardcode defaults that should be user-controllable. The user-facing CLI is the **`sq-config`** bundle (`sciqnt config show` / `sciqnt config set`). Adding a new known setting = one entry in `sq-config/set.py::KNOWN_KEYS` and one convenience accessor in `core/sq_config/`. The config file is user-owned (outside the repo, sovereign, survives `git clean -fdx`).

### Shared design substrate (`sq_tui`)
The look-and-feel of every TUI surface — dispatcher menus, credential prompts, every module's output — comes from one place: `core/sq_tui/`. Surface:

| Export | Purpose |
|---|---|
| `STYLE` | the single `questionary.Style` (cyan accent + bold) |
| `BOLD`, `DIM`, `CYAN`, `RST` | ANSI tokens for `print()` output |
| `ANSI_RE` | regex to strip ANSI when passing to questionary |
| `QMARK`, `POINTER` | brand glyphs |
| `Choice`, `Separator` | re-exported questionary primitives |
| `themed_select(prompt, choices, …)` | styled arrow-key menu |
| `themed_text(prompt, …)` | styled freeform text input |
| `themed_password(prompt)` | styled masked input |
| `heading(text)` | bold section title (above a block) |
| `status(text)` | dim informational line ('connected …', 'fetching …') |
| `format_table(headers, rows, …)` | build table string without printing (compose into tabbed views, logs) |
| `print_table(headers, rows, …)` | build + print a table; thin wrapper around format_table |
| `format_kv(items, title=…)` / `print_kv` | label:value block (dim labels, bold values) — ideal for top-metrics summaries |
| `tabbed_view(tabs, title=…)` | interactive arrow-key tabbed view (prompt_toolkit); non-TTY falls back to printing every tab sequentially — pipeable & CI-safe |

**Bundles MUST NOT import `questionary` directly for design**, and MUST NOT hand-roll ANSI tables / colored print(). Go through `sq_secrets` for credentials and `sq_tui` for anything else visual. A theme tweak (cyan → amber, different qmark, etc.) is a one-file edit that propagates across the dispatcher and every module. The maintenance audit can flag direct `questionary` imports / hardcoded color escapes outside `core/sq_tui/` as drift.

### Platform ↔ bundle contract (the wrapper)
Each bundle ships `bin/sq-<name>` (chmod +x). It is the single entry point the platform talks to. The contract is just **two self-describing flags** so the platform can discover and route without a hard-coded module list:
- `sq-<name> --describe` → prints **one line** to stdout: a short human summary.
- `sq-<name> --commands` → prints subcommands, **one per line**, as `name<TAB>description`.

The `sciqnt` dispatcher at the repo root (`bin/sciqnt`) uses these to:
- `sciqnt --list` — enumerate bundles + descriptions.
- `sciqnt <mod>` — show that module's commands.
- `sciqnt <mod> <action> [args]` — forward to `modules/sq-<mod>/bin/sq-<mod> <action> ...`.
- `sciqnt` (no args) — drop into an interactive TUI (numbered menus, stdlib only) that navigates modules → actions → run.

The wrapper itself is also a normal CLI — running `modules/sq-<name>/bin/sq-<name> <action>` directly works the same. Bundles stay independent; the platform is a thin, optional layer over them. Conformance test in `core/tests/test_platform.py` guards the contract — a wrapper that drops `--describe`/`--commands` fails the suite, so the maintenance loop catches drift.
**Staging (monorepo-of-bundles now → per-repo later):** keep all bundles in one repo while the contract is young and you're the only author — the contract can then evolve atomically. Split a bundle into its **own public repo** once the contract is stable (semver) and external contributors arrive. The layout is identical either way, so the split is zero-rework; even in the monorepo each bundle is independently installable (`pip install ./modules/sq-<name>` or from a git URL + subdirectory) and independently publishable. **Units never import each other** — composition lives in the app/agent layer (`examples/`) — which is what makes each independently distributable.

### 3. Connector = a skill bundle (capability tree + code + how-to + health)
A folder, the simplest robust unit. Contains:
- **Manifest** — declared capability tree, flavour + risk tier, schema version it maps to, known quirks. *Static, shared.*
- **Deterministic scripts** — the code that does auth/fetch/parse/normalise/compute. **Text/CLI-first**: the connector exposes a programmatic/CLI surface the agent calls; it does not rely on the model to parse or calculate.
- **SKILL.md** — how-to (financial conventions, how to read outputs, how to run the scripts).
- **Findings log (living, MANDATORY)** — quirks, caveats, and conformance results captured *the moment they're discovered* — the `known_quirks` made real, plus reconciliation outcomes and open issues. Default behaviour, not optional: a unit without an up-to-date findings log is incomplete, because the hard-won broker knowledge (cash-sweep, foreign-currency dividends, FX timing…) is the connector's real value and must live *with the code*, never only in a chat transcript. Reference: `src/degiro_findings.md`.
- **Health state** — `last_successful_run`, `last_error`, `last_conformance_pass`. *Dynamic, per-user, NOT in the shared repo.*

Capabilities nest (a skill can have multiple levels):
```
degiro/
  read/    positions, transactions, quotes        ← low risk, default-allow
  write/   place_order, cancel_order               ← high risk, default-deny, caps required
```

### 4. Connector flavours — flexible, declared, text-first
One interface, many mechanisms. Preference order (per Principle 5 — TUI is king):
1. **Programmatic API** (official or unofficial client, e.g. `degiro-connector`) — text, deterministic, best.
2. **File / CSV import** (broker statement/export) — text, reliable, ToS-clean; great for a first dogfood.
3. **CLI / scriptable tool** wrapping the above.
4. **Browser automation** — **last resort only**, for brokers with no text/API/file path. Fragile; local-first makes it viable (drive the user's logged-in session) but never the default.

The connector *declares* its flavour in the manifest; the platform never hard-wires one.

### 5. Permissions — capability-based, user-granted, code-enforced
The manifest *declares*; the user *grants* per capability and sets caps (max notional, instrument allowlist, daily limit, dry-run default, confirm-required) — same ergonomics as configuring Claude Code/Chrome access yourself. Defaults: read wide, write off. **Enforcement is a deterministic policy gate** every call passes through (LLM-independent). Local-first makes caps convenient to configure; the gate makes them *enforced*. "Feels safe" vs "is safe."

### 6. Conformance harness — the trust gate
A standard test suite every connector runs against. `last_successful` = "passed conformance," not "didn't crash." It gates: self-healing (a regenerated connector must pass before it's trusted — otherwise it could silently return wrong numbers), and publishing to the registry.

### 7. Generator subagent — the growth engine
Broker not supported? The user invokes a `scaffold-connector` subagent that reads the broker's docs / inspects its surface, generates the skill bundle (text-first flavour preferred), runs it against the conformance harness with the user's account, and iterates until green — on the user's tokens. **The platform ships the contract + harness + generator, not the long tail of connectors.** That's how every broker gets covered without a maintenance army, and how users build even when something isn't supported yet.

### 8. Registry — distribution with provenance
Separates "my local connector" (I accept my own risk) from "community-published" (signed, provenance-tagged, trust-tiered, capability + flavour declared). A `.well-known`-style declarative manifest means a connector's capabilities are discoverable without running it.

## Trust tiers (summary)
- **Read** connectors: low risk, can be wide open.
- **Write/execute** connectors: separate, higher tier — signing/provenance + sandbox + caps (code-enforced) + human-in-loop until trusted.
- **Flavour risk:** official-api > csv/file > reverse-engineered/browser.

## Why this stays flexible and grows
- The platform stays tiny and stable (contract + harness + generator + policy gate); the ecosystem (connectors) is unbounded and self-built.
- Deterministic core, LLM as orchestrator/healer — trust intact.
- Local-first = privacy + no custody liability + regulatory ease + portability — the direction Claude Code / Cursor / Cline are all proving out.
- Capability-based security + conformance gate are the patterns that let VS Code / browser / Terraform plugin ecosystems grow without collapsing.

## First instantiation (Milestone −1 / 1)
A `degiro` connector, **read-only, text-first**: start with the CSV-export flavour (a parse script + SKILL.md + manifest) or the programmatic `degiro-connector` flavour — *not* browser. Goal: produce the owner's correct consolidated multi-currency P&L from his real Degiro data. Proves the contract, the skill-bundle shape, the conformance harness, and the value — at the smallest scale.
