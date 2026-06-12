# Release framework — sciqnt MVP and the module family

Synthesis of the release-framework deep research (108-agent workflow, 27 sources,
2026-06-12) plus direct spot-verification of the load-bearing claims. Opinionated:
each section leads with the decision, then the rationale and precedent.

**Provenance note:** the workflow's adversarial-verification stage malfunctioned
(verifier agents returned no votes; every claim was mechanically marked refuted).
The two claims everything else hangs on — PSR monorepo support and uv-workspace
semantics — were re-verified live against primary docs on 2026-06-12. Claims
marked *(training)* match assistant knowledge but weren't re-fetched; treat them
as high-confidence, re-check before acting on the specifics.

---

## 1. Repo shape: monorepo on a uv workspace, built to split later

**Decision: stay one repo. One uv workspace, one lockfile, every core package and
every bundle keeps its own `pyproject.toml`.**

- This is exactly the Airflow model: dozens of `apache-airflow-providers-*`
  distributions released independently from the single `apache/airflow` monorepo,
  batched roughly fortnightly, only changed providers included *(training; their
  PROVIDERS.rst is the canonical reference)*. The monorepo is what lets the
  contract and the bundles be tested together while the contract is young —
  precisely our situation.
- uv workspaces: members share a single lockfile ("a consistent set of
  dependencies") while each member keeps its own `pyproject.toml` and publishes
  independently. **Verified live.**
- **The known escape hatch:** uv's own docs say workspaces are unsuitable when
  members have conflicting requirements — and 13+ connector bundles wrapping
  third-party broker SDKs is exactly where conflicts will appear first. The
  documented fallback is path dependencies via `tool.uv.sources` per package.
  **Verified live.** Rule: the first genuine dependency conflict evicts that
  bundle from the workspace onto a path-dep, not a fork of the whole layout.
- Because every bundle already has its own `pyproject.toml`, SKILL.md, FINDINGS.md
  and conformance tests, splitting a bundle into a standalone repo later is a
  `git filter-repo` + new remote, zero code rework. That was the design goal;
  the release framework just has to not break it (no cross-bundle relative
  imports, no shared mutable state outside the contract packages).

## 2. Versioning: semver per package; bundles pin the contract major

**Decision: independent semver per distribution. `sq-schema` (+ the conformance
harness) IS the contract and carries the meaningful major version. Bundles
declare `sq-schema>=X,<X+1`. The `sciqnt` app stays 0.x semver until the
contract hits 1.0 — no CalVer.**

- Precedent stack: Airflow providers pin a floor on core (`apache-airflow>=2.0`)
  and bumping that floor is explicitly NOT a provider-major *(training)*;
  pytest's plugin API and Terraform's provider protocol both version the
  *contract* separately from the plugins; VS Code extensions declare an
  `engines` range. The common shape: **plugins pin the contract, never the
  reverse**, and the contract's deprecation policy is what makes the ecosystem
  survivable.
- Deprecation policy (write into CONTRIBUTING): a contract-minor may add, never
  remove; removals get a deprecation warning for ≥1 minor before a major; the
  conformance harness tests *both* the current and the deprecated form during
  the window.
- Tags: per-package namespaced — `sq-degiro/v0.2.0`, `sciqnt/v0.1.0`. This is
  the Airflow pattern (`providers-X/1.2.3`) and what python-semantic-release's
  monorepo support expects (`tag_format = "sq-degiro-v{version}"`).

**Tooling: start with a tiny deterministic release script, graduate to
python-semantic-release when cadence justifies it.** PSR v10.4.0 added an
official Conventional-Commits monorepo parser (per-package
`[tool.semantic_release]`, `path_filters`, `scope_prefix`, per-package
`tag_format`; no workspace-level config yet — config is duplicated per package).
**Verified live.** For a solo maintainer shipping a handful of packages, ~23
copies of PSR config plus commit-convention discipline is machinery ahead of
need (*resist over-engineering*). The v0 release script: bump version in the
bundle's `pyproject.toml`, update its CHANGELOG.md, tag `name/vX.Y.Z`, push —
CI does the rest. Revisit PSR when releases become frequent enough that the
script is the bottleneck.

## 3. Publishing: PyPI Trusted Publishing, attestations for free

**Decision: GitHub Actions + PyPI Trusted Publishing (OIDC) from day one. No
long-lived API tokens anywhere.**

- Trusted Publishing is the PyPA-recommended path; "pending publishers" can be
  registered for each distribution name *before* the first release — do this for
  the whole family up front, it also squats the names against typosquatting
  *(training; PyPA guide)*.
- The standard workflow shape: separate build job (uploads artifacts) from
  publish job; `permissions: id-token: write` only on publish; GitHub
  deployment environments `pypi`/`testpypi`; publish gated on tag pattern.
  One reusable workflow, matrix'd over the package path derived from the tag
  prefix *(training)*.
- `pypa/gh-action-pypi-publish` ≥1.11 generates PEP 740 attestations by
  default — supply-chain provenance on every artifact with zero extra signing
  machinery *(training)*. This matters double for us: attestations are the
  cheapest first rung of the execute-tier trust story (§5).
- Name the distributions exactly like the bundles: `sciqnt` (app),
  `sciqnt-schema`/`sq-schema`… — pick ONE prefix convention before first
  publish and never revisit. Recommendation: `sciqnt-` on PyPI (discoverable,
  brand-anchored), `sq_` import names unchanged.

## 4. Install & update story

**Decision: `uv tool install sciqnt` is the documented path (pipx as the
compatibility mention). Connectors install per-user via the app itself.**

- The quickstart must be ONE step to a working TUI: `uv tool install sciqnt`
  → `sciqnt`. Anything more is a launch-killer.
- Self-update: a `sciqnt update` command that shells out to
  `uv tool upgrade sciqnt` (detect pipx and degrade). Never auto-update —
  sovereignty + least surprise; print "update available" at most once per day
  from a local timestamp, from a check the user can turn off (and that is OFF
  in any non-interactive context).
- Module installs are the Vercel-skills move, search-first like the module
  browser already is:
  - **Official tier:** `sciqnt modules add degiro` → `uv pip install
    sciqnt-degiro` into the app's environment.
  - **Community tier:** `sciqnt modules add owner/repo` → install by git ref.
    On install, run the bundle's conformance suite locally and show the result
    BEFORE first use; record `last_successful` per the existing health-state
    design. Conformance-on-install is the trust gate — not a registry, not
    review queues. (HACS precedent: community store deliberately separate from
    core *(training)*.)

## 5. Community contribution & trust tiers

**Decision: DCO not CLA. Three connector tiers. Conformance is the gate at
every tier; execute capability is its own, higher gate.**

- **DCO** (`Signed-off-by`) — zero-friction, no legal entity needed, the 2026
  default for solo-maintainer MIT projects; a CLA buys nothing here and costs
  contributors *(training)*.
- Tiers (markers live in `manifest.yaml`, surfaced in the module browser):
  1. **official** — in this repo, maintainer-owned, released to PyPI.
  2. **certified** — community-owned repo that passes the conformance suite in
     OUR CI (a scheduled job runs certified bundles' suites against the current
     contract; a failure demotes visibly). Precedent: ccxt's certification
     program; Home Assistant's bronze→platinum quality scale with code owners
     *(training)*. Our quality scale already exists implicitly: conformance
     pass + synthetic fixtures + FINDINGS.md freshness + manifest accuracy —
     make those the four named criteria of "certified".
  3. **community** — installable by git ref, conformance runs locally on the
     user's machine, clearly marked "not endorsed" (OpenBB does exactly this
     marking for third-party `openbb-*` providers *(training)*).
- **Execute connectors are NOT a tier of the above — they're a different axis.**
  Read connectors at any tier; execute requires: PEP 740/GitHub artifact
  attestations on the artifact, pinned-by-hash install, and the capability
  gate's per-call policy (already designed). No community-tier execute at MVP.
  Full stop. Revisit when there's a signing + review story worth trusting.
- Connector submission flow (CONTRIBUTING.md): manifest accurate → synthetic
  fixtures only (no real personal data — CI greps for it) → conformance suite
  green → FINDINGS.md present and honest → DCO. PR template enumerates exactly
  these five checkboxes.

## 6. Docs, repo hygiene, launch

**Decision: mkdocs-material (+ `mike` for versioned docs when the contract
hits 1.0 — not before). Launch = Show HN + r/algotrading + the OpenBB
community, leading with the agent-native angle.**

- mkdocs-material over Sphinx: markdown-native (SKILL.md/FINDINGS.md reuse
  directly), good enough API docs via mkdocstrings; Sphinx only pays off for
  heavy cross-referenced API surfaces *(training)*. The docs site is largely
  generated FROM the bundles — manifest → capability matrix page, SKILL.md →
  module page. Don't hand-write what the repo already states.
- Telemetry: **none at MVP.** If ever added: opt-in only, anonymous, disclosed
  in README, one env var to verify it's off. (Local-first is the brand; this
  is a one-strike trust issue.)
- First-release checklist, in order:
  1. **Scrub the repo** — STATE.md real account labels, any fixture remnants,
     git history check (`git log -p | grep` for names/emails/account IDs).
     The history was anonymised in-place but the repo has never been pushed:
     verify, or squash-reinit if anything leaks. **Blocking everything.**
  2. LICENSE (MIT), SECURITY.md (private email + 90-day disclosure),
     CODE_OF_CONDUCT, CONTRIBUTING (DCO, submission flow §5), issue/PR
     templates.
  3. README: one-paragraph thesis → `uv tool install sciqnt` → screenshot of
     the TUI → module table generated from manifests.
  4. CI: test matrix (3.11–3.13 × mac/linux), conformance job, personal-data
     grep, lint. All green before the remote exists.
  5. Register PyPI pending publishers for every distribution name.
  6. Tag `sciqnt/v0.1.0` + the bundles; let the release workflow publish.
  7. Docs site live; then announce (Show HN, r/algotrading, OpenBB Discord —
     framed as "agent-native portfolio substrate", the connector-generator
     demo is the hook).

## Honest gaps

- Everything marked *(training)* was claim-matched, not re-fetched — re-verify
  Airflow's current provider cadence and the gh-action attestation default
  before writing the CI workflow.
- The certified-tier scheduled CI against community repos is designed, not
  costed — start with N=0 and build it when the first community bundle shows up.
- No story yet for yanking a malicious community bundle a user already
  installed (PyPI yank only covers the official tier). MVP answer: conformance
  re-runs on contract upgrades + the health-state file; a real revocation feed
  is post-MVP.
- The release script (§2) doesn't exist yet; nor does `sciqnt modules add`'s
  git-ref path — both are MVP-release work items, not research questions.
