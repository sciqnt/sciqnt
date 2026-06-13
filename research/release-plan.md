# Release plan — distribution, cadence, discoverability

The EXECUTION plan for shipping sciqnt as a fast-paced, community-driven
product. Engineering mechanics live in `research/release-framework.md`
(versioning, trust tiers, CI); build doctrine in
`research/composable-architecture.md`. This doc decides distribution,
cadence, and how humans AND agents find us — sequenced, with owner gates
marked. Grounded 2026-06-12 (MCP Registry ~2k servers and growing; llms.txt
at ~10% adoption skewing developer tools — Anthropic, Stripe, Vercel,
Supabase ship one; IDE agents fetch it even though big LLM crawlers mostly
don't; MCP + AGENTS.md donated to the Agentic AI Foundation 2026-02).

## 1. Distribution: PyPI is home; everything else is an adapter

- **PyPI, period.** The product is Python; every unit is already a real
  `sciqnt-*` distribution (uv workspace, honest deps — landed 2026-06-12).
  npm has no role until a JS SDK exists (don't build one speculatively —
  value-first). Homebrew tap = later, when install friction is a measured
  complaint (it's a maintenance tax).
- **The quickstart is ONE line:** `uv tool install sciqnt` (pipx noted as
  fallback). Anything longer kills the launch.
- **App vs library vs connector — three install stories, one registry:**
  - app: `uv tool install sciqnt`
  - library user: `pip install sciqnt-schema sciqnt-compute` (the contract
    stands alone — the OpenBB-outcome path)
  - connector-only: `pip install sciqnt-degiro` (proven standalone)
- **Community tier distributes via git, not PyPI — BUILT 2026-06-12:**
  `sciqnt modules add owner/repo` fetches a connector, runs its conformance
  suite locally, and installs it (only if green) into the user's sovereign
  dir `~/.local/share/sciqnt/modules/`; `remove`/`list` to manage. NO PyPI,
  NO per-module form, NO central registry — this is the SCALABILITY answer
  for thousands of community connectors (the per-package PyPI form is a
  one-time setup for OUR ~29 official packages only, never a contributor
  cost). Discovery is source-agnostic (`bundle_dirs`: repo + user dir;
  installed-entry-points next for the `uv tool install` path). The long
  tail never waits on us, and we never custody it.
- **MCP server** (when built): published to the **MCP Registry** — ~2k
  entries, early listing = real visibility; add the `.well-known` server
  card when the spec lands.

## 2. Cadence: ship-on-green per bundle, deliberate on the contract

- **Bundles release independently and often** (the Airflow providers model;
  per-package tags `sciqnt-degiro/v0.2.0` → CI publishes via Trusted
  Publishing). A connector fix ships the day it's green — fast pace lives
  HERE, where blast radius is one broker.
- **The contract (`sciqnt-schema` + conformance) moves slowly and
  deliberately** — additive minors, deprecation windows, bundles pin the
  major. Community speed is only safe because the thing they build against
  is boring.
- **Merge bar = the conformance suite + synthetic-fixtures check + DCO.**
  No review queue theater; the harness is the reviewer (capability-based
  trust, principle 5). Certified-tier community repos get scheduled CI
  re-runs against the current contract; failures demote visibly.
- **Release notes are generated** from per-package CHANGELOGs; a `v0`
  release script first, python-semantic-release's monorepo parser when
  cadence makes the script the bottleneck (framework §2).

## 3. Discoverability — three audiences, one content source

**The composable doctrine applies to marketing too: write content ONCE in
the repo (FINDINGS, SKILL, manifests), derive every surface from it.**

### 3a. Agents searching (the native audience)
- **llms.txt + llms-full.txt** at the docs root, generated from the docs
  build. Low cost, exactly our demographic (IDE agents fetch it; we ARE an
  agent-native tool — not shipping one would be absurd).
- **AGENTS.md** already in-repo (Codex symlink) — keep it the canonical
  agent map; GitHub renders it, agents fetch raw.
- **SKILL.md ships inside every package** — an agent that pip-installs a
  connector gets its how-to in site-packages, offline.
- **PyPI metadata as agent-SEO**: long_description = README per package,
  keywords (`portfolio`, `degiro`, `point-in-time`, `agent-native`,
  `local-first`, broker names), classifiers, project URLs (docs, repo,
  changelog). Agents read PyPI JSON; make it dense.
- **MCP Registry + awesome-mcp lists** when the MCP server ships.

### 3b. Humans searching (SEO)
- **GitHub repo = the #1 ranking asset.** Org/repo `sciqnt/sciqnt`;
  description with the searchable phrase ("local-first, agent-native
  portfolio tracker & financial data layer"); topics (`portfolio-tracker`,
  `degiro`, `quant`, `llm-agents`, `local-first`); social preview image;
  README leading with the one-line install + a TUI screenshot + the
  60-second connector-generator GIF.
- **"sciqnt" is unique** — zero collision, instant #1 for the brand, but
  nobody searches it. Discovery rides the LONG TAIL: every connector's
  FINDINGS.md is genuinely rare content people DO search
  ("degiro transactions.csv column format", "robinhood export history
  python", "GBp pence yahoo finance 100x"). Docs site publishes each
  bundle's FINDINGS + SKILL as pages — the quirks log doubles as the SEO
  moat, and it's already written.
- **Docs site**: mkdocs-material on GitHub Pages (framework §6), pages
  generated from manifests/SKILLs/FINDINGS. Custom domain when owned.
- **Honest comparison pages** (high-intent searches): vs Ghostfolio, vs
  OpenBB, vs beancount/plaintext-accounting — each states what THEY do
  better (value-first honesty is also the credible-content strategy).

### 3c. Community channels (launch moments, not one launch)
- **Soft launch**: repo public + PyPI live + docs up + awesome-list PRs
  (awesome-quant, awesome-python-finance; awesome-mcp later) + GitHub
  topics. Let it index for a week or two.
- **Show HN**: the hook is NOT "another portfolio tracker" — it's "I built
  an agent-native finance layer; watch Claude build a working broker
  connector in 20 minutes" (the generator demo GIF). HN loves local-first +
  sovereignty + show-the-internals.
- **Targeted communities**: r/algotrading, r/eupersonalfinance +
  r/DEGIRO (the Degiro connector is the wedge — that audience has NO good
  tooling), r/Python, r/selfhosted (local-first resonates), OpenBB Discord
  (collaborative framing — contributing upstream is a first-class outcome,
  never adversarial).
- **A launch moment per milestone** thereafter: MCP server → MCP/agents
  communities; T212/IBKR connectors → their subreddits; the
  connector-generator tutorial → AI-coding communities. Fast-paced product
  = a drumbeat, not a bang.
- **The flagship content asset**: "Build a connector for YOUR broker with
  your coding agent" tutorial — it's simultaneously the community-growth
  flywheel (Article: generator + harness, not the long tail), the best
  demo, and the highest-intent SEO page.

## 4. Sequence (owner gates marked ⛔)

1. **✅ Scrub — DONE 2026-06-12** (tree). Working tree is clean: STATE.md
   labels → AccountA/B; the family-member name → AliceExample (docs + tests); real
   Degiro int_account ids → 10000001; machine paths genericised; the
   stray committed `screen.txt` (real portfolio capture) removed +
   gitignored along with all summon artifacts; 72 tracked `build/` +
   `egg-info` artifacts purged + gitignored. The gate is automated —
   `scripts/check_personal_data.sh` scans TRACKED files (the publish
   boundary), asserts no tracked `.env`, and runs inside
   `./run_tests.sh`; it becomes the CI job verbatim.
   **History decision: publish with FRESH history.** The local history
   carries ~300 occurrences of identity strings (labels, family name,
   machine paths) plus the machine author email on every commit —
   rewriting is error-prone; the public repo starts from a clean initial
   commit at push time (step 4), the local repo keeps its full history
   private. (.env credentials were NEVER tracked; the real password in
   `modules/sq-degiro/.env` never entered history — local-hygiene note
   for the owner: migrate to sq_secrets/keyring and delete the .env.)
2. **Repo hygiene** (1 session): LICENSE, SECURITY.md, CODE_OF_CONDUCT,
   CONTRIBUTING (DCO + the 5-checkbox connector submission flow), issue
   templates (incl. "connector request" — the demand signal for the
   generator), PR template.
3. **CI** (1 session): test matrix (3.11–3.13 × mac/linux), conformance
   job, personal-data grep, lint. Green BEFORE the remote exists.
4. **✅ GitHub org + push — DONE 2026-06-12**: `sciqnt` org created by
   owner; `sciqnt/sciqnt` public at https://github.com/sciqnt/sciqnt with
   FRESH history (single root commit, `DavideGCosta@users.noreply` author;
   local pre-publish history stays on the never-pushed `private-history`
   branch). Topics set (portfolio-tracker, degiro, quant, local-first,
   llm-agents, agent-native, tui, python, point-in-time, finance);
   issues + discussions enabled; launch README with demo-mode figures.
   Still to do here: social preview image (needs the GitHub UI).
5. **PyPI**: reserve ALL `sciqnt-*` names as pending publishers (also
   anti-typosquatting), Trusted Publishing workflow, tag → publish. First
   tags: `sciqnt/v0.1.0` + the contract + the proven bundles.
6. **Docs + llms.txt**: mkdocs-material, pages generated from bundles,
   llms.txt/llms-full.txt, GitHub Pages.
7. **Soft launch** (§3c) → wait, index, fix the first-user papercuts.
8. **⛔ Show HN** with the generator demo. Then the drumbeat.

## 4b. The public figures: demo mode (owner decision 2026-06-12)

**No screenshot, doc, README capture, or first-run screen ever shows real
finances — sciqnt deploys in DEMO MODE until a user connects an account.**
The `sq-demo` bundle is a deterministic synthetic portfolio (seeded price
walks, scripted multi-year history, EUR-only, offline) that flows through
the SAME pipeline as any broker — fold, MTM, charts, history, `--json` —
so the first-run experience is the full product, not an empty state. The
platform's void-fill rule (config `demo_mode`: auto|on|off) retires it the
moment a real account connects. All launch assets (README screenshot, the
generator GIF's "before" state, docs examples) render from
`demo_mode: on`.

## 5. What we deliberately do NOT do

- No npm/Homebrew/conda at launch (adapters when demanded, not before).
- No telemetry, ever at MVP; opt-in-only if ever (sovereignty is the brand).
- No paid launch/ads; no growth hacks that outrun the conformance story.
- No registry/marketplace custody of community connectors — git refs +
  local conformance keep the user in control (fire-us test).

## Honest gaps

- The generator demo (the Show HN hook) needs a clean recorded run —
  build/verify before step 8, it's the launch's load-bearing asset.
- Comparison pages require genuinely trying Ghostfolio/OpenBB current
  versions (value-first: measure the shortfall, don't assert it).
- MCP server doesn't exist yet — Registry listing waits on it.
- Domain ownership (sciqnt.com/.dev) unverified — owner to check/buy.
