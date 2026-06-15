# sciqnt component-world blueprint

> **Status: proposed (2026-06-15), deep-research-grounded** (pass `wf_e457961a-1b8`,
> 24/25 claims 3-vote-verified, all primary sources). The plan for decomposing the
> `sciqnt/sciqnt` monorepo into a multi-repo **component world** under one org,
> built for the agentic era. **Revises** the connector-distribution call in
> `research/distribution-governance.md` (see §2). No code changes yet — this is the
> decision record + sequence to execute against.

---

## 0. The two decisions that reframe everything

1. **Everything open, under the `sciqnt` org — the liability firewall comes down.**
   The earlier governance doc pushed reverse-engineered connectors *out* of the org
   into community repos. The owner has decided against that: every component,
   connectors included, is **open source under the org** (MIT + DCO). The framing is
   honest and legally favorable — a connector reads the **user's own account with
   their own credentials, locally**, to standardize it into a canonical schema: that
   is **interoperability / data-portability**, not infringement. **ccxt is the direct
   precedent** — 100+ unofficial, reverse-engineered exchange connectors, open, in one
   org, thriving. The repo boundary now sorts almost entirely by **visibility**
   (public-open vs private), not liability.
   - Guardrails that keep "it's just interop" true (codified in §6): **never
     circumvent an access control / DRM** (the one place §1201 weakens the
     fair-use-interop defense); **own-account access only**; **nominative trademark
     use**; **not-affiliated/endorsed `NOTICE`** on every connector. (Get a one-hour
     legal sanity-check before going all-in — diligence, not a blocker. It's a
     personal org.)

2. **Each connector is its own repo.** Not grouped. A connector is *the* unit of
   modularity (everything else is shared infra); it already stands alone (own
   manifest/FINDINGS/tests/conformance); and it is a **leaf consumer of a thin
   contract**, so it federates cheaply. This is the Terraform-provider /
   ccxt / Homebrew-tap model.

---

## 1. The governing lesson: **stabilize the contract, THEN split**

The single most-confirmed finding (3-0, primary): **HashiCorp split providers out of
Terraform Core only AFTER extracting `terraform-plugin-sdk` to its own repo and
stabilizing its API**, so providers no longer import Core — they import a
deliberately delimited SDK whose interface is *one versioned protobuf file*
(`tfplugin5.x.proto`) ([terraform#23200](https://github.com/hashicorp/terraform/issues/23200),
[HashiCorp blog](https://www.hashicorp.com/en/blog/announcing-the-terraform-plugin-sdk)).
That thin, stable, versioned boundary is what "unlocked the potential for a thriving
ecosystem … core providers maintained by HashiCorp, and a large number of high-quality
third-party providers." Each provider then got "its own release cadence, versioning,
and documentation."

**Direct translation for sciqnt:** the canonical schema + conformance harness is our
`tfplugin5.proto`. **Extract and stabilize the CONTRACT package first**; only then
detonate components and connectors into their own repos. Splitting tightly-coupled
pieces *before* the contract settles means paying an N-repo migration tax on every
experimental schema tweak. This is the lowest-regret decision and it drives the whole
sequence (§8).

**The middle ground while you transition (the "virtual monorepo"):** Kubernetes keeps
one git tree as source of truth (`staging/`) and a **publishing-bot** `git filter-branch`-es
each staging dir into its own standalone repo, *guaranteeing* the published repos are
self-consistent and `go get`-installable; contributions go to the mono, published repos
are read-only mirrors ([k8s staging](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/staging.md),
[publishing-bot](https://github.com/kubernetes/publishing-bot)). sciqnt can do the same
during the cutover: keep the uv-workspace mono authoritative, publish guaranteed-installable
standalone repos, and flip individual components to "real" independent repos as they
stabilize. **Honest caveat:** that bot is Go/GOPATH-specific and itself untested — a
Python/uv equivalent must be *built*, it's not off-the-shelf.

---

## 2. The org topology (sorted by visibility, per decision 1)

Org = **`sciqnt`**. Every public repo is **MIT + DCO**.

### Governance & contract (the spine)
| Repo | What | Notes |
|---|---|---|
| **`constitution`** | `PRINCIPLES.md` + `FOUNDATION.md` + the principle-review rubric + **reusable workflows** (ci / conformance / principle-review / auto-merge) + peribolos-style org config | The injected source of truth (§3). Public. |
| **`.github`** | org **default community-health files** (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue/PR templates) + org default workflows | Native org-wide fallback. Must be **public**. |
| **`contract`** | the canonical schema (`sq_schema`) + the **conformance harness** + JSON-schema export | The semver'd **hub** (§4). This is our `tfplugin5.proto`. |

### Shared libraries (deterministic, standalone)
| Repo | What |
|---|---|
| **`math-x`** | general math/formulas (possibly not even sciqnt-specific) — the strongest "stands alone" case |
| **`compute`** | money math: `sq_compute` / `sq_performance` / `sq_analytics` / `sq_aggregator` (deterministic core, P5) |
| **`fmt`** | the zero-dep formatting leaf (`sq_fmt`) |
| **`config`** | settings / `sq_config` |

### The standardization layer
| Repo | What |
|---|---|
| **`portfolio`** | the **anti-corruption / aggregation layer** (§5) — consumes conformant connector outputs, emits unified canonical portfolio state. The money-core lives here/below; connectors carry no money logic. |

### Apps (consumers / adapters of the data surface)
| Repo | What | Visibility |
|---|---|---|
| **`app-tui`** | `sq_tui` + `sq_platform` + home | public MIT |
| **`app-web`** (future) | web UI | **private if it holds client accounts/data** |

### Connectors — **one repo each** (`sciqnt/sq-<broker>`)
`sq-degiro`, `sq-robinhood`, `sq-kalshi`, `sq-polymarket`, `sq-yahoo`, `sq-fx-ecb`,
`sq-openfigi`, `sq-edgar`, `sq-firds`, `sq-finnhub`, `sq-tiingo`, `sq-news-rss`, … —
**all open, MIT, org-owned, each with a `NOTICE`** (own-account / no-circumvention /
nominative-use / not-affiliated). Reverse-engineered (`sq-degiro`, `sq-robinhood`)
and official-API (`sq-kalshi`, …) live side by side; the manifest `risk_tier` /
`provenance` is the difference, not the repo location.

### The private perimeter (the only non-open zone)
Separate **private** repos for anything that **must** be private by *visibility*, not
liability: components that **hold client accounts/data**, and proprietary
**self-originated data** + its backend. This is the commercial edge.

### Dependency graph (acyclic; the contract is the hub)
```
constitution ──(governance, no code dep)──> everything
contract ──> compute, portfolio, app-tui, every sq-<broker> connector
math-x ──> compute, portfolio
fmt ──> app-tui, connectors
compute ──> portfolio
portfolio ──> app-tui
sq-<broker> connectors ──(conform to)──> contract ──(consumed by)──> portfolio
```

---

## 3. The constitution, injected org-wide

Two complementary mechanisms (both proven):

1. **Human-facing governance → the org `.github` repo's default community-health files**
   (GOVERNANCE/CONTRIBUTING/CODE_OF_CONDUCT/SECURITY + templates). GitHub displays them
   for every repo without its own copy; a repo's own file overrides per-file
   ([GitHub docs](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)).
   - **Critical caveat (verified):** these defaults are **NOT placed in each repo's
     clone / git history**. So a CI agent that must *read* `PRINCIPLES.md` from the
     working tree **cannot** rely on the `.github` default.

2. **Machine-enforced governance → the `constitution` repo + reusable workflows.**
   - Each repo's CI is a one-line call to a **reusable workflow** in `constitution@vX`
     (`ci.yml`, `conformance.yml`, `principle-review.yml`, `auto-merge`). One source,
     pinned by version, updated by bumping the ref.
   - The **principle-review agent fetches `PRINCIPLES.md` + the rubric from
     `constitution@pinned`** at run time (not the invisible `.github` default) — the
     "principle-review reads the org constitution" pattern, done correctly.
   - **Org rulesets + required workflows** make the conformance + principle-review
     workflow a *required* gate on every repo, with **tiered enforcement** and
     **dynamic targeting by custom property** (e.g. `risk_tier=official|reverse-engineered`)
     so stricter rules attach to riskier connectors automatically
     ([rulesets best-practices](https://wellarchitected.github.com/library/governance/recommendations/managing-repositories-at-scale/rulesets-best-practices/),
     [required workflows](https://github.blog/enterprise-software/ci-cd/enforcing-code-reliability-by-requiring-workflows-with-github-repository-rules/)).
     **⚠ Plan dependency:** org rulesets / required workflows / custom-property tiering
     need **GitHub Enterprise Cloud**. Confirm sciqnt's plan before committing this
     layer (open question §9). Also note: "required workflows scale uniformly to all
     repos" was the one **refuted** claim (1-2) — verify at scale, don't assume.
   - **Allstar** (a GitHub App driven from a central `.allstar` repo) for *continuous*
     drift detection on security baselines, complementing the merge-time gate
     ([Allstar](https://github.com/ossf/allstar)).
   - **Org-as-code (peribolos):** membership, teams, repo creation declared as YAML in
     `constitution`, reconciled to GitHub and review-gated — the Kubernetes `kubernetes/org`
     model ([k8s org](https://github.com/kubernetes/org)). Principle 7 made literal:
     ownership is config, reviewed like code.

---

## 4. The contract as the semver'd hub (our `tfplugin5.proto`)

- **`contract` repo ships one thing:** the canonical schema (pydantic) + a stable
  **JSON-schema export** + the **conformance suite** (`check_snapshot`). Published as
  `sciqnt-contract`, **strict semver**: a breaking schema change = **major** bump.
- **Every connector/component depends on `sciqnt-contract >= X, < X+1`.** The version
  pin is the coordination-bounding mechanism (the thin-stable-contract principle made
  enforceable). A connector "passes" iff it passes conformance **against the contract
  version it targets** — that's the cross-repo invariant (Principle 4).
- **Per-component installability guarantee:** during transition, the uv-workspace mono
  stays authoritative and a publishing step guarantees each component installs
  standalone against its pinned contract (the k8s publishing-bot guarantee, Python/uv
  flavor — to be built).

---

## 5. The standardization layer (`portfolio`) — keep connectors dumb, contract thin

The validated shape (DDD **anti-corruption layer** / **canonical data model** /
ports-and-adapters; cf. OpenBB providers→standardized models, Singer/Meltano
taps→target, Airbyte source→destination):

- **Connectors are dumb adapters.** Each maps `broker → canonical schema` and nothing
  more. No money logic, no cross-broker knowledge, no aggregation.
- **`portfolio` is the one standardization/aggregation layer.** It consumes *conformant*
  canonical outputs from N independent connectors and composes them into unified
  portfolio state. It **never reaches into a connector's internals** (anti-corruption)
  — it only sees canonical data. The **deterministic money-core (P5) lives here/below**,
  isolated from connectors.
- This keeps the contract **thin** (connectors only need the schema, not the aggregation
  logic) and the ecosystem **unbounded** (any conformant connector composes for free).

So: `N dumb connectors → conform to thin contract → portfolio standardizes → apps render`.

---

## 6. Interop / disclaimer policy (because everything's org-owned now)

Codify org-wide (in `constitution`, applied to every connector's `NOTICE`):
- **Own-account only** — connectors access the *user's* account with the *user's*
  credentials, locally. No custody (P3).
- **No circumvention** — never defeat an access control / DRM / anti-bot wall (the
  §1201 line; keep on the fair-use-interop side).
- **Nominative trademark use** — broker names identify the integration target only;
  no implied affiliation/endorsement.
- **`NOTICE` on every connector** — not affiliated/endorsed; interoperability tool;
  at-your-own-risk; respects the broker's ToS is the user's responsibility.
- **The narrative, stated plainly:** *standardizing brokers into a canonical schema for
  the age of AI* — pro-user, pro-portability. It's both honest and the strongest posture.

---

## 7. The agentic cross-repo sync system (the keystone)

This is what makes a polyrepo of N connectors *cheaper* to keep in sync than the human
era — the monorepo's "atomic cross-cutting change" superpower, reconstructed by agents.

**Propagation (contract bump → dependents migrated):**
- **Pull model for the federated/sovereign edge** (and the default): each repo runs
  **Renovate** to detect a new `sciqnt-contract` version; the bump PR fails CI on
  breakage; a **migration agent** (our `@claude`/triage shape) reads the changelog +
  failure, **migrates** the code (not just bumps the version), re-runs conformance to
  green, opens a PR — gated by CI + principle-review + **human merge**. The bot author
  means it never auto-merges (the gate we built).
- **Push model for tightly-coordinated first-party** release trains: on `contract`
  release, `sciqnt-bot` dispatches the migration agent into the known first-party
  dependents. (Never push into repos you don't own.)
- **Semver intent** is declared explicitly per change (the **Changesets** pattern —
  author-declared major/minor/patch, not inferred) so propagation knows the blast class
  ([Changesets](https://changesets-docs.vercel.app/)).
- **Escalation:** the agent **auto-migrates mechanical changes** (a field rename) but
  **flags semantic/behavioral changes for a human** (a money-math meaning shift) — never
  silently "fixes" the money-core (P5).
- **Topological ordering** for the diamond graph: `contract → compute → portfolio → app`
  propagate in dependency order (compute goes green before portfolio migrates against it).

**Blast-radius protection (don't let a contract change silently break connectors):**
- A `contract` change PR triggers a **crater-style conformance run** — the conformance
  suite is run for **every first-party connector repo** (a `craterbot`-style registry
  set) against the **candidate** contract, surfacing "this PR breaks N connectors"
  *before* merge ([crater](https://github.com/rust-lang/crater/blob/master/docs/bot-usage.md)).
  Block merge if it breaks a first-party connector without an accompanying migration.
- **The conformance suite IS the cross-repo contract test** (consumer-driven contract
  testing, Pact-style "can-i-deploy" semantics): a unit is deployable against `contract
  vX` iff its conformance passes against `vX`.
- **Honest residual the agentic era does NOT erase:** you **cannot run repos you don't
  control**. Community connectors self-test via conformance **with lag** — the federated
  edge is *eventually consistent*, not pre-merge-verified. The conformance gate is their
  safety net; a status surface (each connector's "conformant against contract vX?")
  communicates it without a central server (registry OPTIONAL, P2).

---

## 8. The split SEQUENCE (decisive order)

Driven by the verified criteria: **coupling to the moving contract**, license/visibility
divergence, independent cadence, ownership.

| Phase | Move | Why this order |
|---|---|---|
| **0. now** | In the mono: **extract + harden the `contract` package** (schema + conformance) as a clean semver'd boundary; bring the liability firewall *down* in the docs (decision 1). | The Terraform lesson — stabilize the contract *before* splitting. Zero-risk prep. |
| **1.** | Split **`constitution`** + **`.github`** (governance injection). | No code coupling; pure upside; everything downstream inherits it. |
| **2.** | Split **`contract`** as the published hub once its API is stable-ish. | The hub everything pins. |
| **3.** | Split the **loose leaves**: `math-x`, `fmt`, `app-tui`. | Consumers/adapters; don't drive contract change; low migration cost. |
| **4.** | **Build the agentic sync** (migration agent + crater-style conformance + Renovate) — *before* the connector explosion. | The thing that makes phase 5 cheap. |
| **5.** | **Detonate connectors → one repo each.** Reverse-engineered ones (`sq-degiro`, `sq-robinhood`) can go early (leaf + firewall down); the rest as the contract approaches ~1.0. | "Stabilize-then-detonate" — avoids N migrations per experimental tweak. |
| **6.** | Split **`portfolio`** + **`compute`** (the tightly-coupled core) last. | Highest coupling to the (now-stable) contract. |
| **(ongoing)** | Stand up the **private perimeter** repos (web/client-data, self-originated data) when those products exist. | By visibility necessity. |

---

## 9. Honest residuals & open questions

- **Plan tier:** org rulesets / required workflows / custom-property tiering / org-wide
  `.github` defaults-from-public-repo need **GitHub Enterprise Cloud**. **Confirm
  sciqnt's plan** — the §3 enforcement design depends on it. (Fallback on a free org:
  the `constitution` reusable-workflows + each repo opting-in via its own CI call, minus
  the *required* org-ruleset gate — weaker, but workable.)
- **The publishing-bot guarantee is not off-the-shelf for Python/uv** — it must be
  built (the k8s one is Go-specific and untested).
- **Conformance lag** on the federated edge is irreducible — community connectors aren't
  pre-merge testable. Accept eventual consistency; the conformance gate bounds it.
- **Agent-migration non-determinism** — contained by conformance + human merge, never
  trusted on the money-core.
- **Required-workflow uniformity at scale** was the one refuted claim — verify behavior
  for the actual repo count rather than assuming.
- **The contract-first sequencing is the lowest-regret move** regardless of the softer
  points — do phase 0 first.

## Evidence base
Deep-research pass `wf_e457961a-1b8` (2026-06-15): 5 angles, 24 sources, 113 claims,
25 verified (24 confirmed 3-0, 1 refuted). Primary sources cited inline.
