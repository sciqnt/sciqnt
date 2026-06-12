# Contributing to sciqnt

The fastest way to understand this repo: `AGENT_GUIDE.md` (codebase map),
`FOUNDATION.md` (worldview), `PRINCIPLES.md` (the constitution — decisions
go in its direction). Coding agents are first-class contributors here;
point yours at `AGENTS.md`.

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

## Everything else

Bugs and small fixes: just PR with a test. Features: open an issue first —
`PRINCIPLES.md` governs (e.g. presentation never computes; every view
ships a `--json` data form; no credential custody, ever).
