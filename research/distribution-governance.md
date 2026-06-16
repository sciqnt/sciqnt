# Distribution & governance framework

> **⚠️ Topology SUPERSEDED (2026-06-16) → the component world.** §1's "monorepo-core +
> federated-community, NEVER org polyrepo" topology was reversed by an owner-green-lit
> decision: everything is org-owned + open (the liability firewall comes down), and
> each component is its own `sciqnt/sq-*` repo. The atomicity property §1 rightly
> defends is preserved via a **virtual-monorepo transition** — the mono stays the
> single source of truth and component repos are *generated* from it by the publishing
> bot until graduation. See `~/Projects/sciqnt-org/sq-constitution/MIGRATION.md` +
> `research/component-world-blueprint.md`. §§2–6 (liability framing, agentic governance,
> license posture, DCO-only) still hold. Below is kept as the rationale that informed
> the transition (the coupling/atomicity analysis is exactly what the publishing bot
> mechanizes).
>
> **Status: decided (2026-06-14).** This is the load-bearing decision for how
> sciqnt's connector ecosystem is hosted, governed, contributed to, monetized,
> and discovered. Grounded in two deep-research passes (topology/liability/
> governance: 23/25 claims 3-vote-verified; the §5 license posture: a second
> focused pass, 22/25 verified). All sections are decided; don't relitigate
> without cause.

## TL;DR — the three-zone model

The ecosystem is **not** one-repo-per-connector under the org. It's three zones,
each chosen by the *trust/liability/ownership* boundary, not by code organization:

| Zone | Home | Holds | License |
|---|---|---|---|
| **1. Core + first-party** | `sciqnt/sciqnt` **monorepo** | contract (schema), compute, analytics, conformance harness, TUI, JSON surfaces, and connectors sciqnt legally owns / can stand behind (sanctioned-API tier) | MIT (open, **never relicensed**) |
| **2. Community / unofficial** | contributors' **own repos** (or a legally-separate community namespace) — federated git-ref, **never under `sciqnt/`** | reverse-engineered / ToS-bending connectors (e.g. unofficial Degiro, Robinhood) | contributor's choice; disclaimed; **never commercialized by sciqnt** |
| **3. Private / proprietary** | sciqnt's **private repos**, same install path | premium / closed connectors; self-originated-data connectors | proprietary |

All three install through the **same** mechanism — `sciqnt modules add owner/repo`
→ fetch → **local conformance gate** → install into the user's sovereign dir. The
mechanism is agnostic to who owns the connector and whether it's open; open-vs-closed
is purely a hosting + licensing decision, made per-connector, with zero re-architecting.

## 1. Repo topology — why monorepo-core + federated-community, not org polyrepo

The owner's lean toward one repo per connector (option B) is **half right**: it does
buy independent release cadence and per-connector usage signal. But hosting those
repos *under the org* is the wrong way to get them, for reasons the evidence makes
concrete:

- **Contract-change coordination is the killer.** While the contract still moves
  (Milestone 1), a monorepo makes a schema change + all first-party connector updates
  **one atomic, tested commit**. N org repos turn it into an **N-repo version matrix**.
  This is the exact pain **Airbyte's own engineers** flagged: the connector-in-monorepo
  *"becomes a bottleneck"* and the hardest part to fix was **decoupling CI/CD**
  ([airbyte#11058](https://github.com/airbytehq/airbyte/issues/11058)). The lesson cuts
  *for* a monorepo here: the coupling Airbyte disliked is the same atomicity sciqnt
  *wants* while its contract is young.
- **ccxt is the decisive counter-proof.** It governs **100+ unofficial exchange
  connectors in ONE monorepo**, deliberately — *"one pull request per one exchange…
  commit just one single source file"* ([ccxt](https://github.com/ccxt/ccxt)). A large
  unofficial-connector ecosystem thrives centrally; per-connector repos are not required
  for scale. (Caveat: ccxt's shared base is *fat* ~15k lines — it validates "central
  atomic connector edits," not literally a thin contract. sciqnt's thin contract is a
  deliberate improvement ccxt doesn't itself prove.)
- **Other shortfalls of org polyrepo:** CI/secrets duplication across N repos,
  discoverability fragmentation, search/SEO dilution, governance overhead, and the
  "hundreds of near-empty proposed repos" sprawl.

**Where per-connector separation IS right:** for *community/unofficial* connectors —
which must be federated out of the org anyway for liability (§2). There, contributors'
own repos give exactly the independent cadence + per-repo signal the owner wants, with
**no contract-coordination cost to sciqnt** (they pin a contract version; they migrate
on their own schedule). So the owner's instinct lands — just in Zone 2, not Zone 1.

**Federation is registry-optional and proven.** Homebrew lets *any* Git repo be a
package source, namespaced `owner/repo`, over *"any protocol that Git can handle"*, with
a naming-prefix convention and **no central server** ([brew taps](https://docs.brew.sh/Taps.html)).
sciqnt's `modules add owner/repo` is already this model. Federated sources legitimately
carry a **distinct install/trust path** (a refuted over-claim confirmed taps are *not*
treated identically to core) — which is exactly what the conformance-gate-on-install
provides.

**Trigger to split a first-party connector out of the monorepo** (so the rule isn't
vague): when it needs (a) an independent release cadence, (b) external co-maintainers,
or (c) to be private. Until one is true → it stays in the monorepo.

## 2. Liability split — the firewall

Reverse-engineered / unofficial connectors are the value multiplier (they make the
unified view possible) **and** the legal risk. The research grounds a defensible posture
(US-scoped; **get counsel before finalizing**):

- Reverse-engineering for interoperability can be **lawful fair use** (*Sega v. Accolade*,
  *Sony v. Connectix*) when it's intermediate copying to discover interface specs, then
  clean re-implementation — how a clean-room broker connector is built.
- **Van Buren v. United States** (2021) *"appears to foreclose imposing CFAA liability for
  mere… ToS violations"* of purpose ([CRS LSB10616](https://www.congress.gov/crs-product/LSB10616),
  [EFF](https://www.eff.org/issues/coders/reverse-engineering-faq)).
- **Residual risk:** click-through *"no reverse engineering"* EULAs **can** bind
  (*Blizzard v. BnetD*). And DMCA §1201 if any access-control is circumvented.
- **Operative survival precedent:** youtube-dl/yt-dlp — GitHub reinstated it and set a
  **higher procedural bar** for §1201 claims, erring *"on the side of the developer"*
  ([GitHub policy](https://github.blog/news-insights/policy-news-and-insights/standing-up-for-developers-youtube-dl-is-back/)).

**Decision:** unofficial/reverse-engineered connectors are **community-maintained,
hosted-but-NOT-org-owned, explicitly disclaimed (no-endorsement), trademark-separated,
and never commercialized by sciqnt.** sciqnt ships the *contract + harness + generator*
and *indexes* community connectors; it does not host or sell connectors it doesn't own.
The official org carries only sanctioned-API and sciqnt-owned connectors.

## 3. Agentic contribution governance — scaffold → fork/PR → gate

The pipeline the owner wants, made safe:

1. **Scaffold-first.** A connector starts from a template/generator (`sq_scaffold`) that
   emits a conformance-green skeleton + manifest + FINDINGS stub. (Avoid the "empty
   proposed repo" literal form — it produces abandoned-repo sprawl; prefer a template
   repo / generator the agent runs locally, and only graduate to a real repo when the
   connector passes conformance.)
2. **Fork/branch → PR.** No direct creation; every change is a PR.
3. **Two gates, ordered — the deterministic one is the real one:**
   - **CI conformance (hard gate).** The same acceptance-test suite on every PR — the
     mechanism that *cannot be talked out of failing*. This is the proven model:
     Airbyte *"runs all connectors against the same set of integration tests… run
     automatically in CI when you open a pull request"* with stricter tests required for
     higher tiers ([Airbyte CAT](https://docs.airbyte.com/platform/connector-development/testing-connectors/connector-acceptance-tests-reference)).
   - **Principle-review agent (advisory).** Reads the diff vs the constitution and posts
     a review. **It is advisory only — never a required merge check** — because it is
     attackable (next point).
4. **Human merge** for anything money-core-adjacent or contract-touching.

**Prompt injection is a demonstrated, critical, architecturally-unsolved risk** — a CSA
note showed a **PR title** made Claude exfiltrate live API keys, no write access needed;
hidden HTML comments steer the agent while staying invisible to human review
([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-claude-code-github-action-prompt-injection/)).
sciqnt's review workflow already mitigates (base-only checkout, read-only tools, "treat
PR text as untrusted data"); **keep it that way and keep the deterministic conformance
gate as the thing that actually blocks merge.**

**Evolution path (not v1):** production AI review uses a **coordinator + specialists**,
not one monolith — Cloudflare runs up to 7 specialised reviewers consolidated by a
coordinator, ~$1.19/review at 131k runs/30d ([Cloudflare](https://blog.cloudflare.com/ai-code-review/)).
sciqnt's single principle-review agent is a fine v1; v2 splits into principle-alignment /
conformance-readiness / money-core-touch / secret-hygiene + a coordinator.

## 4. Provenance & tiers

Mirror Terraform's supply-chain posture **without** its mandatory registry: a
**naming convention** (`sq-`/`sq_`, like Homebrew's `homebrew-` and Terraform's
`terraform-provider-`) for a predictable resolve path, and **signed releases** for
provenance ([Terraform publishing](https://developer.hashicorp.com/terraform/registry/providers/publishing)).
Trust tiers map to the existing risk tiers: **official-api > csv/file >
reverse-engineered/browser**, earned through conformance, not through a human bottleneck.

## 5. Open / proprietary boundary + license posture — **DECIDED**

> Deep-research-grounded (pass `wf_4c6cb922-4eb`, 22/25 claims 3-vote-verified).
> The repo already implements this posture (MIT across the root LICENSE + all 31
> packages; DCO, not CLA) — this section records *why* it is the right call and
> makes "never relicense" + "DCO-only" load-bearing commitments, not defaults.

### The recommendation (one posture, not a menu)

| Layer | License | Why |
|---|---|---|
| **Contract / schema / SDK** (`sq_schema`, `sq_fmt`, the conformance harness, the connector contract) | **MIT — permanently** | Must stay permissive so *every* connector — community, **and proprietary/private** — can build on it without copyleft infection. This is the Grafana lesson: it relicensed its *core* but **kept plugins/agents/SDK Apache** so the ecosystem stays buildable. |
| **Engine / core** (compute, analytics, platform, TUI) | **MIT — permanently** | sciqnt is **local-first** with a **data + ops moat**, not a hosted service a hyperscaler can strip-mine — so AGPL's network-copyleft protection is *low-value here* (its trigger barely fires for a local CLI/library) and *high-friction* (enterprise legal teams ban AGPL; it deters embedding in agent hosts). When the moat is self-originated data + connector reach + brand — not the code — permissive maximizes adoption with no moat cost (the PostHog/Supabase "open code, monetize the data/hosted layer" model). |
| **First-party connectors** | **MIT** | Consistent with the repo; reference implementations. |
| **Community connectors** | **author's choice** | They own their repos (Zone 2). Because the contract is MIT, they *may* be proprietary, MIT, or anything. |
| **Proprietary layer** (self-originated data + its backend; specific private connectors; a hosted convenience/sync layer) | **closed, ADDITIVE on top** | Monetize via value-added products on a permanently-open core (dbt Cloud / dbt's Fusion binary; Grafana Cloud + Enterprise) — **never** by relicensing the core. Moat = self-originated data + unified correctness + connector reach + brand, **never reselling licensed feeds**. |
| **Third-party broker connectors sciqnt doesn't own** | **never commercialized** | (The liability firewall, §2.) |

### Governance: **DCO-only, never a CLA** — the load-bearing rug-pull-proofing

Every relicensing rug-pull was **structurally enabled by a CLA with copyright
assignment + single-vendor governance** ([arXiv 2411.04739](https://arxiv.org/pdf/2411.04739)).
A **DCO** lacks that power imbalance, so a DCO-only project is *"less likely to be
rug-pulled"* ([LWN](https://lwn.net/SubscriberLink/1036465/e80ebbc4cee39bfb/)) —
and the commitment is itself the strongest **trust signal**, because it makes the
rug-pull *structurally impossible* (you cannot relicense contributors' code without
their permission). sciqnt already uses DCO; this makes it a deliberate, permanent
anti-rug-pull guarantee, not an incidental choice. **Adopting a CLA later would
itself be the betrayal** — don't.

### Why permissive-and-permanent beats relicensing (the evidence)

- **The fork trigger is *relicensing previously-open code*** from permissive/weak-copyleft
  (Apache/MPL/BSD) to restrictive source-available (SSPL/BSL/RSALv2) — OpenTofu←Terraform-BSL,
  Valkey←Redis-SSPL, OpenSearch←Elasticsearch-SSPL ([opentofu.org](https://opentofu.org/blog/opentofu-announces-fork-of-terraform/),
  [chaoss](https://chaoss.community/what-happens-to-relicensed-open-source-projects-and-their-forks/)).
  After Redis relicensed, **essentially all external company contributors stopped** and moved to the fork.
- **Relicensing didn't even pay off:** RedMonk found *no evidence* it improved vendors' financials,
  and **Elastic backtracked**, re-adding AGPL in Aug 2024 *"to call Elasticsearch open source again"*
  ([elastic.co](https://www.elastic.co/blog/elasticsearch-is-open-source-again)).
- **The survivors monetize additively on a permanently-open core:** dbt Core stays Apache-2.0 while
  dbt Labs sells a proprietary binary + premium features on top ([getdbt](https://www.getdbt.com/blog/licensing-dbt));
  Grafana keeps AGPL core + Apache SDK and monetizes Cloud/Enterprise, *"not on restrictive licensing of the core"*
  ([grafana](https://grafana.com/blog/2021/04/20/qa-with-our-ceo-on-relicensing/)).

### The load-bearing rules

1. **Never relicense what was once open.** Build proprietary as *separate additive products*.
2. **DCO-only, forever.** No CLA, no copyright assignment.
3. **Contract/SDK stays MIT** so all connectors (incl. proprietary) build on it.
4. **Don't cripple the open core to sell the proprietary layer** — the line is *data + ops + hosted*, never removing local capability (avoids "open-core resentment").

### Top failure modes + mitigations

- **A hyperscaler offers "sciqnt cloud" (strip-mining).** Low risk for a local-first, data-moat tool. Mitigation: the moat is self-originated data + ops + the connector network + **trademark** (protect the *sciqnt* name — code is free, the name is not; the Grafana approach), not the code. AGPL-the-engine is a last-resort lever *only if* strip-mining becomes a *measured* threat — but it doesn't fit local-first, so don't pre-optimize.
- **Open-core resentment** (premium features seen as cannibalizing the open core). Mitigation: the open core must stay genuinely complete standalone (it is — full local portfolio analytics); proprietary is strictly *additive* (hosted convenience, self-originated data), never subtractive.
- **Investor pressure to relicense** (what hit Redis/HashiCorp). Mitigation: DCO-only makes it structurally hard; the evidence shows relicensing doesn't even help financials; optionally a public no-relicense pledge / eventual neutral-foundation path.

## 6. Telemetry & discoverability — registry-optional, sovereign

Reconciling "we want per-connector usage + discoverability" with "registry optional +
local-first + sovereign":

- **Telemetry:** layer cheap signals first — PyPI download stats + per-repo GitHub
  insights (traffic/clones/dependents) for federated connectors. Any first-party
  telemetry ping is **opt-in, privacy-preserving** (Homebrew's analytics model:
  documented, opt-out-able, aggregate). Never a precondition to use. *(Exact mix is an
  open question — see below.)*
- **Discoverability:** an **optional thin index** — a connector index repo / `awesome-sciqnt`
  list + **`llms.txt`** for agents + (later) an **MCP registry** entry — not a mandatory
  central server. Humans and agents both resolve through the same naming convention +
  index.

## Open questions (carried)

- Exact telemetry mix that yields per-connector signal without violating sovereignty.
- Human-in-the-loop ratio for money-adjacent merges (full-auto vs maintainer-required).
- Preventing conformance-gaming (connectors that pass the suite while subtly wrong) and
  scaffold-funnel sprawl.

## Evidence base

Deep-research pass `wf_77da24a5-7b1` (2026-06-14): 5 angles, 25 sources fetched, 120
claims, 25 verified (23 confirmed 3-0/2-1, 2 killed). Primary sources cited inline above.
