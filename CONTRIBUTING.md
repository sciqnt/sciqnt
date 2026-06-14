# Contributing to sciqnt

The fastest way to understand this repo: `AGENT_GUIDE.md` (codebase map),
`FOUNDATION.md` (worldview), `PRINCIPLES.md` (the constitution — decisions
go in its direction). Coding agents are first-class contributors here;
point yours at `AGENTS.md`.

## How a PR is reviewed

Two gates, deliberately separate:

1. **CI — the mechanical gate.** `./run_tests.sh` runs in CI on every PR (every
   package's tests, the conformance suite, the personal-data scrub). It answers
   *"is it correct and clean?"* Green is required.
2. **The principle-review agent — the judgment gate.** An agent reads your diff
   against the constitution (`PRINCIPLES.md`) using the rubric in
   `.github/PRINCIPLE_REVIEW.md`, and posts a review. It answers *"does this
   belong in sciqnt?"* — a PR can be green and still bend a top principle (money
   never computed by an LLM, append-only/bitemporal facts, no credential
   custody, the thin contract). It's a maintainer aid, not an auto-merge; a
   human still presses the button.

A maintainer can summon the agent to make changes by commenting **`@claude
<instruction>`** on the PR — e.g. *"@claude bring this in line with
PRINCIPLES.md and push the fix"*. It reads the constitution, edits, keeps the
suite green, and pushes to the branch (forks need *Allow edits from maintainers*).

The fastest way through both gates: run the rubric on yourself first
(`.github/PRINCIPLE_REVIEW.md`) and fill in the PR template's principle
self-check — the "honest gaps" habit (P18).

## Ground rules

- **DCO, not CLA.** Sign your commits off (`git commit -s`,
  `Signed-off-by: Name <email>`). You certify you may contribute the code.
- **The harness is the reviewer.** `./run_tests.sh` must be green — it runs
  every package's tests, the conformance suite, and the personal-data gate.
- **Synthetic fixtures only.** Never real account data, credentials, or
  identifying strings — the gate (`scripts/check_personal_data.sh`) will
  fail your PR, and history rewrites are painful. Approved stand-ins:
  `AccountA/B`, `AliceExample`, account id `10000001`.
- **Money is `Decimal`, currency mandatory, bitemporal** — the
  deterministic core is held to a stricter bar than everything else.

## Dev setup

    git clone … && cd sciqnt
    python3 -m venv .venv && .venv/bin/pip install pydantic prompt-toolkit keyring
    ./run_tests.sh

## Contributing a connector (the most valuable contribution)

Read `research/connector-framework.md`, or just tell your coding agent:
"build a sciqnt connector for <broker>" — the sq-connectors skill knows the
staging→promote workflow (`sq_scaffold` scaffolds a conformance-green
skeleton; you fill in the dialect).

A connector PR needs all five:
1. [ ] `manifest.yaml` accurate (capabilities, flavour, `risk_tier`, status)
2. [ ] conformance green: `check_snapshot()` returns `[]` on your fixtures
3. [ ] synthetic fixtures only (mirroring the REAL payload shape)
4. [ ] `FINDINGS.md` — the living quirks log, honest, including what
       does NOT work
5. [ ] DCO sign-off

Independent connector repos are equally welcome — `sciqnt modules add
owner/repo` installs by git ref and runs conformance locally. Passing
the suite in our scheduled CI earns the **certified** tier.

### Where your connector lives (the zones — read `research/connector-publishing.md`)

Where a connector belongs is decided by **trust/liability**, not convenience:

- **Official-API, sciqnt-owned** → propose it into this monorepo (a PR).
- **Reverse-engineered / unofficial / ToS-bending** (e.g. an unofficial Degiro
  or Robinhood) → it lives in **your own repo, never under the `sciqnt/` org**.
  This is the liability firewall: such connectors are community-maintained,
  hosted-but-not-org-owned, and **must ship an accurate `NOTICE.md`** (no
  affiliation/endorsement, clean-room interop, at-your-own-risk, runs on your own
  account). The scaffold emits one — keep it true. Don't open empty placeholder
  repos under `sciqnt/`; the scaffold + generator is the funnel, and a repo
  graduates only once it passes conformance. sciqnt indexes community connectors;
  it does not host, own, or commercialise connectors it doesn't own.

## Everything else

Bugs and small fixes: just PR with a test. Features: open an issue first —
`PRINCIPLES.md` governs (e.g. presentation never computes; every view
ships a `--json` data form; no credential custody, ever).
