"""sq_skills — install sciqnt's reusable Agent Skills into a coding agent.

The OUTWARD half of the bidirectional LLM-native design (see
research/llm-native-integration.md §3): sciqnt ships capabilities as **Agent
Skills** — a `SKILL.md` whose what+when `description` is the selection
mechanism. Instead of dumping a one-shot prompt + a stale data snapshot into the
agent, we INSTALL the skill into the agent's skills directory so it PERSISTS:
the agent can use it now and in any future session, and it fetches *current*
data itself by running the `sciqnt` CLI. sciqnt computes the numbers
(deterministic); the agent reasons and explains (the probabilistic edge).

Install targets (an agent not listed → `install` returns None and the caller
falls back to a one-shot prompt):
  claude — ~/.claude/skills/<name>/SKILL.md   (folder skill; full frontmatter)
  codex  — ~/.codex/prompts/<name>.md         (slash prompt; body only)

`home=` is injectable so tests never touch the real ~/.
"""
from pathlib import Path
from typing import Optional

# ── the skill catalogue (single source of truth) ───────────────────────────
# Each entry: a third-person `description` (what it does AND when to use it —
# this is what makes the agent auto-select it) + a `body` of procedural
# instructions that drive the `sciqnt` CLI. Keep bodies host-neutral.
_PORTFOLIO_BODY = """\
# sciqnt portfolio

`sciqnt` is a local-first, agent-native cross-asset portfolio tool installed on
this machine. It aggregates the user's holdings across every connected broker /
exchange into one canonical, point-in-time-correct schema. Use it to answer
anything about *their* portfolio.

## How to see what the user sees (discovery, not a frozen map)
**Every view of the sciqnt app is reproducible from the CLI, and the CLI
describes itself** — trust `sciqnt --help` over any list written down here:

    sciqnt --help            # the full, current surface — START HERE
    sciqnt --list            # which connectors exist
    sciqnt <broker>          # one connector's own commands
    sciqnt config show       # user settings (display currency, …)

The shape of the surface (examples, not the contract): `--once` is the
portfolio dump; `--account LABEL` scopes any view to one account in its own
base currency; `--tab NAME` dumps a single tab; `--history RANGE` reproduces
a history sub-tab (ranges like YTD/1Y/All — `--help` lists them); `--asof`
is point-in-time; `--fresh` bypasses the ~60s cache. Add `--json` for
structured data (Decimal-as-string, versioned schema) — prefer it whenever
you compute or compare; the text form is for humans.

Combine views to curate insight no single screen shows — e.g. one account's
1Y history against the whole portfolio's, or positions against news.

## Leave a finding on their home screen (the push channel)
If you discover something worth the user seeing next time they open the app:

    sciqnt insight add "TEXT" --ref "<the command that reproduces it>"

It shows once on the sciqnt home, with your ref command so they can verify.
Use sparingly — a finding, not a feed.

## Explain it
Read the output and explain in plain language: what they hold, P/L, cash,
allocation across asset classes / brokers, and anything notable (concentration,
big movers, drawdown). Figures are already in the user's configured display
currency.

## Analyse / dive deeper
The money math is computed by sciqnt and is authoritative — **cite its figures,
never recompute or invent them.** For deeper work: compare brokers / asset
classes, contrast TWR vs XIRR, inspect a single connector via
`sciqnt <broker> live`.

## Rules
- All money is `Decimal` and carries a currency. Never fabricate numbers.
- Read-only: do not place trades or modify anything.
- If `sciqnt` isn't found, ask the user to ensure it's on PATH.
"""

_CONNECTORS_BODY = """\
# sciqnt connectors

A sciqnt *connector* is a self-contained bundle under `modules/sq-<name>/` that
maps one broker / exchange / data source into the canonical schema. Use this
skill to do anything connector-related: **see what's set up**, **use** an
existing connector, **build** a new one for an unsupported broker, or
**troubleshoot** one that's failing.

You are running inside the sciqnt repo (read **`AGENT_GUIDE.md`** / `AGENTS.md`
for the codebase map). **Start from the user's goal**, not a checklist: figure
out which broker they mean and whether they want to set up an existing
connector, build a new one, or fix a broken one — ask if it's unclear, don't
dump the whole inventory at them. If their broker isn't in `modules/`, the
natural next step is to **offer to build a connector for it** (see below); a
new/unsupported broker is the common case, not an error.

## See what's set up (when it helps)
- `sciqnt --list` — installed connectors (some, like `fx-ecb`, are data sources,
  not broker accounts; ignore any `status: scaffold` stubs).
- `sq-<name> --describe` / `sq-<name> --commands` — one connector's purpose +
  its commands (the bin wrappers live at `modules/sq-<name>/bin/`).
- Each bundle carries its own docs: `modules/sq-<name>/SKILL.md` (behaviour),
  `manifest.yaml` (capabilities / flavour / risk tier), `FINDINGS.md` (quirks log).
- `sciqnt <name> live` — fetch a live snapshot from a connected one
  (`--fresh` bypasses the cache).

## The contract (for building or fixing)
- `core/sq_schema/` — the canonical Pydantic schema. Money is `Decimal`,
  currency mandatory, bitemporal.
- `core/sq_schema/conformance.py` → `check_snapshot(snap)` returns violations.
  **This is the reward signal — drive it to `[]`.**
- `./run_tests.sh` runs every connector's tests. Iterate generate → test → fix.
- All broker-dialect knowledge belongs in the bundle's `src/sq_<name>/canonical.py`
  (`to_canonical`). Nothing broker-specific leaks elsewhere.

## Build a new connector
**Read `building-a-connector.md` (in this skill folder) for the full framework** —
the bundle anatomy, the discovery contract, the staging→promote workflow, and the
exact commands. In short: scaffold into the `.sq-build/` staging area, fill it to
green conformance, wire the `snapshot()` surface, then promote into `modules/`.
Flavour preference: API → CSV → CLI → browser (last resort). Read-only — `execute`
(placing orders) is a separate, higher trust tier.

## Troubleshoot a failing connector
Reproduce with `sciqnt <name> live` (or `--fresh`). Read the bundle's
`FINDINGS.md` + `canonical.py`. Usual causes: an expired session / credentials,
a changed broker payload shape, or a conformance violation. Fix in
`canonical.py`, re-run `./run_tests.sh` to green, and log the quirk in `FINDINGS.md`.

## Working at scale
You can spawn subagents to work several connectors in parallel (e.g. build one
while diagnosing another) — each connector is independent.

## Rules
- Never put credentials in code, tests, prompts, or commits. Synthetic fixtures only.
- Money is `Decimal`; currency mandatory. Read-only unless explicitly building an
  execute flavour with the trust tier in place.
"""

_BUILDING_DOC = """\
# Building a sciqnt connector — the framework

A connector is a self-contained bundle that maps one broker / exchange / data
source into sciqnt's canonical schema. Follow this exactly — it's how a connector
becomes visible to the app and trusted by the harness.

## Golden rule: build in staging, promote when done
**Never build directly in `modules/`** — the app discovers connectors by scanning
`modules/`, so a half-built bundle there shows up broken. Build in the gitignored
`.sq-build/` staging area and `promote()` it only once it's green + wired:

    # scaffold a conformance-green skeleton into .sq-build/sq-<slug>/
    python -c "import sys; sys.path.insert(0,'core'); import sq_scaffold; print(sq_scaffold.build('.', 'Broker Name'))"

The skeleton already passes `./run_tests.sh` and already exposes the discovery
contract — you fill in the bodies, then:

    # once green + wired, move it into modules/ where the app finds it
    python -c "import sys; sys.path.insert(0,'core'); import sq_scaffold; print(sq_scaffold.promote('.', 'sq-<slug>'))"

## Bundle anatomy (`<bundle>/`)
- `manifest.yaml` — name, kind, `risk_tier`, `status` (scaffold → proof → v1),
  flavour, declared capabilities, honest gaps.
- `SKILL.md` — agent-facing behaviour for this connector.
- `FINDINGS.md` — living quirks log (field shapes, sign conventions, rounding…).
- `bin/<bundle>` — wrapper exposing `--describe` / `--kind` / `--commands`,
  `setup`, `live`.
- `pyproject.toml`, `tests/test_canonical.py` (SYNTHETIC fixtures only).
- `src/<pkg>/__init__.py`, `canonical.py`, `live.py` — see below.

## THE DISCOVERY CONTRACT (the part connectors most often miss)
`src/<pkg>/__init__.py` MUST expose two top-level callables:

    def accounts(): ...                                  # configured account names; [None] = single
    def snapshot(asof=None, *, account=None): ...        # -> canonical PortfolioSnapshot

The app lists a connector under "Connect an account" and folds it into the
portfolio aggregate **only because these exist** (see
`sq_platform.aggregated._available_connectors`, which imports `sq_<name>` and
checks for a callable `snapshot`). A connector with the data mapped but no
`snapshot()` in `__init__.py` is INVISIBLE to the app — this is the #1 build
mistake. The scaffold wires this for you; keep it wired. Mirror a finished one:
`modules/sq-kalshi/src/sq_kalshi/__init__.py`.

## Where each kind of knowledge lives
- `canonical.py` → `to_canonical(raw)` holds ALL broker-dialect knowledge and
  returns a `PortfolioSnapshot` that passes
  `sq_schema.conformance.check_snapshot()` (drive violations to `[]`). Money is
  `Decimal`; every balance carries a currency.
- `live.py` → `fetch_live(account=None)` is thin I/O only: read creds via
  `sq_secrets`, hit the API / read the file / run the CLI, return raw dicts for
  `to_canonical`. No dialect logic here. Raise `CredentialsMissing` (never
  `sys.exit`) so one broker's outage doesn't poison the aggregate. When the
  broker needs the USER (expired session, device challenge, in-app approval
  while unattended) raise `sq_secrets.NeedsAction("plain one-line action",
  action="approve"|"reconnect")` — the platform renders it as one ⚠ line
  with the action; raw errors never reach the screen.
- `__init__.py` ties them: `snapshot()` = `to_canonical(fetch_live(...))`.

## Loop
Pick the safest flavour (API > CSV > CLI > browser). Implement → `./run_tests.sh`
→ fix, until green with conformance clean. Grow fixtures from the REAL payload
shape (never live data / credentials in the repo). Log quirks in `FINDINGS.md`.
Flip `manifest.yaml: status` off `scaffold` (→ `proof` when fixture-green; `v1`
after a real-credentials run). Keep it read-only.

## Auth robustness ladder (tell the user where they stand)
Auth methods differ in how unattended they are: API key / TOTP setup key
(no human in the loop, ever) > device-trust cookie ("remember for 30 days" —
expires, then needs a human) > per-login approval (phone popup / SMS — blocks
every unattended refresh). Two conventions, both modelled by sq-degiro /
sq-robinhood `setup_creds.py`:
- **Persist the session** (`sq_secrets.save_session` / `session_dir`) so every
  fetch doesn't look like a new device — otherwise the broker emails a
  new-device alert per refresh and re-challenges constantly.
- **When setup lands on a less-robust rung, SAY SO**: after a successful
  verify, print a short note naming the most robust method this broker offers
  and how to upgrade (e.g. "enable 2FA, copy the setup key, re-run setup").
  Detect the rung from the flow that actually happened (e.g. the login needed
  an in-app tap), never nag users already on the top rung.
"""

CATALOG: dict[str, dict] = {
    "sq-portfolio": {
        "group": "portfolio",
        "description": (
            "Explain and analyse the user's cross-asset investment portfolio "
            "from sciqnt (a local-first portfolio tool). Use whenever the user "
            "asks about their holdings, P/L, cash, allocation, performance, or "
            "wants portfolio analysis. Runs the local `sciqnt` CLI to read "
            "current canonical positions and cash across all connected brokers."
        ),
        "body": _PORTFOLIO_BODY,
    },
    "sq-connectors": {
        "group": "connectors",
        "description": (
            "Work with sciqnt connectors — the bundles that map a broker / "
            "exchange / data source into the canonical schema. Use when the user "
            "wants to connect a new or unsupported broker, set up or inspect an "
            "existing connector, or troubleshoot one that's failing to fetch. "
            "Operates inside the sciqnt repo against the contract + conformance "
            "harness; builds and fixes connectors and runs the test suite."
        ),
        "body": _CONNECTORS_BODY,
        "files": {"building-a-connector.md": _BUILDING_DOC},
    },
}

# Agents whose skill dir we know how to write. "kind" selects the on-disk shape.
_TARGETS = {
    "claude": {"kind": "folder", "rel": (".claude", "skills")},     # <dir>/<name>/SKILL.md
    "codex":  {"kind": "prompt", "rel": (".codex", "prompts")},     # <dir>/<name>.md
}


def names() -> list[str]:
    """The skills sciqnt ships."""
    return list(CATALOG)


def for_group(group: str) -> Optional[str]:
    """The (general) skill that serves a capability group, e.g. 'portfolio' →
    'sq-portfolio', 'connectors' → 'sq-connectors'. None if no such group. One
    skill per group: entry points differ only in the injected prompt."""
    for name, s in CATALOG.items():
        if s.get("group") == group:
            return name
    return None


def supported(agent: str) -> bool:
    """True if we know where to install skills for `agent`."""
    return agent in _TARGETS


def skill_md(name: str) -> str:
    """The full SKILL.md text (YAML frontmatter + body) for a catalogue skill."""
    s = CATALOG[name]
    return (f"---\nname: {name}\ndescription: {s['description']}\n---\n\n"
            f"{s['body']}")


def installed_path(agent: str, name: str, *, home: Optional[Path] = None) -> Optional[Path]:
    """Where `name` installs for `agent` (no I/O). None if unsupported/unknown."""
    if name not in CATALOG or agent not in _TARGETS:
        return None
    t = _TARGETS[agent]
    base = (home or Path.home()).joinpath(*t["rel"])
    if t["kind"] == "folder":
        return base / name / "SKILL.md"
    return base / f"{name}.md"                       # prompt


def install(agent: str, name: str, *, home: Optional[Path] = None) -> Optional[Path]:
    """Install (idempotently overwrite) skill `name` for `agent`. Returns the
    written path, or None if the agent/skill is unsupported.

    Folder agents get the full SKILL.md (frontmatter drives discovery) plus any
    supporting `files` (e.g. a deep-dive subskill) as siblings — progressive
    disclosure: SKILL.md references them, they load only when relevant. Prompt
    agents (no folder) get the body with supporting files appended, so the
    framework still travels with the single slash-prompt."""
    path = installed_path(agent, name, home=home)
    if path is None:
        return None
    files = CATALOG[name].get("files", {})
    path.parent.mkdir(parents=True, exist_ok=True)
    if _TARGETS[agent]["kind"] == "folder":
        path.write_text(skill_md(name))
        for fname, text in files.items():
            (path.parent / fname).write_text(text)
    else:                                                  # prompt: single file
        extra = "".join(f"\n\n---\n\n# {fname}\n\n{text}"
                        for fname, text in files.items())
        path.write_text(CATALOG[name]["body"] + extra)
    return path


def invocation_hint(agent: str, name: str) -> str:
    """How to refer to the skill when seeding the agent / telling the user.
    Folder skills are referenced by name (the agent auto-selects on description);
    prompt agents use a literal slash command."""
    if _TARGETS.get(agent, {}).get("kind") == "prompt":
        return f"/{name}"
    return f"the {name} skill"
