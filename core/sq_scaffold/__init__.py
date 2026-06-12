"""sq_scaffold — write a new connector bundle skeleton, then hand it to an agent.

Part of the "use agent to connect" flow (research/llm-native-integration.md §9):
when a user's broker isn't supported, the agent (via the sq-connectors skill)
scaffolds a skeleton, fills it against the contract + conformance harness, and
promotes it — on the user's own tokens, against the user's own account.

Two deliberate properties:
  * **Staging-first.** `build()` defaults to the `.sq-build/` staging area, NOT
    `modules/` — a half-built bundle never pollutes the app's connector list
    (which only scans `modules/`). `promote()` moves it in once it's green +
    wired. Keeps the working tree honest.
  * **Discovery contract by construction.** The skeleton already exposes the
    `snapshot()`/`accounts()` public surface in `__init__.py` — the thing that
    makes the app LIST and aggregate a connector. The agent fills the body; it
    can't forget the surface. Broker dialect stays isolated to `canonical.py`.

The skeleton is a WORKING, conformance-green bundle (trivial empty-portfolio
`to_canonical()` + a passing test) so the agent starts from green and extends.

Pure stdlib, string templates — no network, no agent invocation here (that's
`sq_agents.launch`). `build(root, broker)` returns the bundle Path; `promote()`
moves a staged bundle into `modules/`.
"""
import re
import shutil
import stat
from pathlib import Path

GENERATE_FILE = "GENERATE.md"          # the host-neutral generator brief in the bundle
STAGING = ".sq-build"                  # default build area — promoted to modules/ when green


def slugs(broker: str) -> tuple[str, str]:
    """(bundle-slug, package-slug) for a broker name. Bundle uses hyphens
    (`sq-trading212`), package uses underscores (`sq_trading212`). Lowercased,
    non-alphanumerics collapsed to a single separator, edges trimmed."""
    base = re.sub(r"[^a-z0-9]+", "-", broker.strip().lower()).strip("-")
    if not base:
        raise ValueError(f"broker name {broker!r} has no usable characters")
    return f"sq-{base}", f"sq_{base.replace('-', '_')}"


def _manifest(bundle: str, broker: str) -> str:
    return f"""# {bundle} — unit manifest  (SCAFFOLD — fill in as you build)
name: {bundle}
kind: source
risk_tier: read              # read-only until an execute flavour is added + trust-tiered
status: scaffold             # scaffold → proof (fixture-green) → v1 (real-creds run)
schema_version: 0
broker: {broker}
asset_classes: []            # e.g. [EQUITY], [CRYPTO], [EVENT] — set what this broker holds
flavours:                    # prefer: api → file/CSV → cli → browser (last resort)
  # api:
  #   risk: official         # official | reverse-engineered
  #   needs_credentials: true
  #   dependencies: []
  #   code: src/{bundle.replace('-', '_')}/live.py
capabilities:
  read: []                   # e.g. live_positions, live_cash, mark_to_market
  execute: []                # SEPARATE higher trust tier — leave empty for read connectors
honest_gaps:
  - not_implemented          # remove as you implement; keep the ones that stay true
known_quirks: FINDINGS.md
license: MIT
"""


def _skill(bundle: str, broker: str) -> str:
    return f"""# {bundle} — connector skill  (SCAFFOLD)

How an agent uses this connector. Keep behaviour here; keep dialect in
`canonical.py`; keep quirks in `FINDINGS.md`.

## What it connects
{broker}. Replace this with: what the broker is, which asset classes it holds,
and which flavour you chose (API / CSV / CLI / browser) and why.

## Commands
- `{bundle} setup` — store credentials (via `sq_secrets`, never in the repo).
- `{bundle} live`  — fetch a snapshot and print it.

## Mapping
All broker-dialect knowledge lives in `src/{bundle.replace('-', '_')}/canonical.py`
→ `to_canonical(raw)` returns a `sq_schema.PortfolioSnapshot` that passes
`sq_schema.conformance.check_snapshot()`. Money is `Decimal`. Every fact carries
a currency.
"""


def _findings(broker: str) -> str:
    return f"""# {broker} — findings (living quirks log)

Record every broker-dialect surprise here as you discover it: field shapes,
sign conventions, rounding, settlement timing, pagination, auth quirks, rate
limits. This file is the connector's memory — future regenerations read it.

(empty — start logging as you build)
"""


def _bin(bundle: str, broker: str) -> str:
    pkg = bundle.replace("-", "_")
    staging = STAGING
    return f"""#!/usr/bin/env bash
# {bundle} convenience wrapper (SCAFFOLD).
set -e
# Resolve paths relative to THIS script so the wrapper works whether the bundle
# is staged in {staging}/ or promoted to modules/ (both two levels under root).
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="$(cd "$BUNDLE/../.." && pwd)"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || {{ echo "no venv at $PY" >&2; exit 1; }}
case "${{1:-}}" in
  --describe) echo "{broker} — (scaffold) positions + cash"; exit 0 ;;
  --kind) echo "broker"; exit 0 ;;
  --commands)
    printf "setup\\tStore credentials (keychain/.env)\\n"
    printf "live\\tFetch a snapshot\\n"
    exit 0
    ;;
  setup) shift; echo "TODO: implement setup_creds.py" >&2; exit 1 ;;
  live)  shift; exec "$PY" "$BUNDLE/src/{pkg}/live.py" "$@" ;;
  *) echo "usage: $(basename "$0") {{setup|live}} [args]" >&2; exit 1 ;;
esac
"""


def _pyproject(bundle: str, pkg: str) -> str:
    return f"""[project]
name = "{bundle}"
version = "0.0.0"
description = "sciqnt connector (scaffold)"
requires-python = ">=3.11"
dependencies = []

[tool.setuptools]
package-dir = {{"" = "src"}}
packages = ["{pkg}"]
"""


def _canonical(pkg: str, broker: str) -> str:
    return f'''"""{pkg}.canonical — map {broker}'s dialect into the canonical schema.

THIS is the one file that holds all broker-dialect knowledge. Everything else
(bin wrapper, manifest, tests) is plumbing. `to_canonical(raw)` must return a
`PortfolioSnapshot` that passes `sq_schema.conformance.check_snapshot()`.

The scaffold ships a trivial EMPTY-portfolio mapping so the bundle is green from
the first `./run_tests.sh`. Replace `_example_raw()` and the body of
`to_canonical` with the real {broker} payload shape; grow the test fixtures
alongside. Money is always `Decimal`; every balance carries a currency.
"""
from decimal import Decimal

from sq_schema import Account, CashBalance, PortfolioSnapshot

BROKER = "{broker}"


def _example_raw() -> dict:
    """A minimal synthetic payload in THIS broker's shape — replace with the
    real one. Used by the tests so they never touch the network or credentials."""
    return {{"account_id": "demo", "currency": "USD", "cash": "0.00"}}


def to_canonical(raw: dict) -> PortfolioSnapshot:
    """Translate one {broker} payload into a canonical snapshot.

    Scaffold behaviour: an account with a single cash balance, no positions —
    conformance-clean. Build outward from here: parse `raw` into Instruments +
    Positions (with `Decimal` cost basis and `value_base`), more CashBalances,
    corporate actions, etc."""
    account = Account(
        account_id=raw["account_id"],
        broker=BROKER,
        base_currency=raw["currency"],
    )
    cash = [CashBalance(
        account_id=raw["account_id"],
        currency=raw["currency"],
        amount=Decimal(str(raw["cash"])),
    )]
    return PortfolioSnapshot(
        account=account,
        instruments=[],
        positions=[],
        cash_balances=cash,
    )
'''


def _init_py(pkg: str, bundle: str, broker: str) -> str:
    service = bundle
    return f'''"""{bundle} — {broker} source unit.

PUBLIC SURFACE = the discovery contract. The TUI auto-lists this connector under
"Connect an account" and folds it into the aggregate ONLY because this module
exposes top-level `snapshot()` + `accounts()` (see
sq_platform.aggregated._available_connectors). Keep them here — a connector with
the data mapped but no `snapshot()` in __init__ is INVISIBLE to the app.

Thin surface only: broker-dialect parsing lives in `canonical.py`; I/O lives in
`live.py`. Read-only — order placement is a separate, higher trust tier.
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

import sq_secrets

SERVICE = "{service}"
SECRET_KEYS = ["api_key"]                 # the secret names this broker needs
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def accounts():
    """Configured account names. `[None]` = legacy single-account. Empty == no
    account connected yet (a normal state, not an error) — the dispatcher then
    lists this broker as "available to connect"."""
    named = sq_secrets.list_accounts(SERVICE)
    sq_secrets.load_dotenv(_ENV_FILE)
    legacy = sq_secrets.get_secret(SERVICE, SECRET_KEYS[0])
    out = []
    if legacy:
        out.append(None)
    out.extend(named)
    return out


def snapshot(asof: Optional[datetime] = None, *, account: Optional[str] = None):
    """Return a canonical `PortfolioSnapshot` of current {broker} state. Wire
    `live.fetch_live` + `canonical.to_canonical` (the scaffold raises until you
    do). Raise on `asof` unless you build a history-reconstruction path."""
    if asof is not None:
        raise RuntimeError("{bundle} has no historical (asof) support yet — "
                           "live snapshot only.")
    from .canonical import to_canonical
    from .live import fetch_live
    return to_canonical(fetch_live(account=account))


__all__ = ["snapshot", "accounts"]
'''


def _live_py(pkg: str, broker: str) -> str:
    return f'''"""{pkg}.live — thin I/O for {broker}. Sign the request, fetch, and hand
RAW dicts to `canonical.to_canonical`. No dialect knowledge here (that's
canonical.py). Credentials come from `sq_secrets` — NEVER hard-code them.

The scaffold leaves `fetch_live` unimplemented so the bundle stays honest: until
you implement it (and flip the manifest off `status: scaffold`), the connector
isn't live. The fixture-based tests exercise `to_canonical` directly and don't
need this.
"""


class CredentialsMissing(RuntimeError):
    """Raise (never sys.exit) so an aggregated view downgrades just this broker."""


def fetch_live(account=None) -> dict:
    """Fetch the current {broker} payload (raw dicts) for `to_canonical`.
    TODO: implement — read creds via sq_secrets, call the API / read the file /
    run the CLI (prefer API > CSV > CLI > browser), return the raw shape that
    `canonical.to_canonical` expects."""
    raise NotImplementedError(
        "{pkg}.live.fetch_live is not implemented yet — wire the {broker} fetch.")
'''


def _test(pkg: str, bundle: str, broker: str) -> str:
    return f'''"""{bundle} canonical adapter — fixture-based (no network, no creds).

Starts GREEN against the scaffold's empty-portfolio mapping. As you implement
`to_canonical` for real {broker} payloads, grow these fixtures and assertions —
the conformance check is the reward signal: keep it clean.

Paths are resolved relative to this file (walk up to the repo root that has
`core/sq_schema`) so the bundle's tests pass whether it's staged in {STAGING}/
or promoted to modules/.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
SRC = HERE.parents[1] / "src"                                         # <bundle>/src
ROOT = next((p for p in HERE.parents
             if (p / "core" / "sq_schema").is_dir()), HERE.parents[3])
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(SRC))

from {pkg}.canonical import to_canonical, _example_raw                # noqa: E402
from sq_schema import conformance                                     # noqa: E402


class Test{pkg.title().replace('_', '')}Mapping(unittest.TestCase):
    def setUp(self):
        self.snap = to_canonical(_example_raw())

    def test_conformance_clean(self):
        violations = conformance.check_snapshot(self.snap)
        self.assertEqual(violations, [], conformance.format_violations(violations))

    def test_account_present(self):
        self.assertTrue(self.snap.account.account_id)
        self.assertTrue(self.snap.account.base_currency)


if __name__ == "__main__":
    unittest.main()
'''


def generator_brief(bundle: str, pkg: str, broker: str) -> str:
    """The host-neutral instruction handed to whichever agent the user prefers.
    Written into the bundle as GENERATE.md AND passed as the launch prompt, so
    an agent we can't seed on the CLI just reads one file. References the
    contract + harness by path — the agent works from the repo, not this text."""
    return f"""# Build the {bundle} connector for sciqnt

You're extending **sciqnt** (a local-first, agent-native cross-asset portfolio
tool) with a connector for **{broker}**. A working, conformance-GREEN skeleton
has been scaffolded at `{STAGING}/{bundle}/` (the staging area — NOT yet in
`modules/`, so the app can't see it until you promote it). Your job: make it
fetch and correctly map {broker}'s real data, then promote it.

Read **`AGENT_GUIDE.md`** for the codebase map, and the **building-a-connector**
section of the sq-connectors skill for the full framework. Quick contract:
- `core/sq_schema/` — canonical schema; money is `Decimal`, currency mandatory.
- `core/sq_schema/conformance.py` → `check_snapshot(snap)` returns violations —
  **your reward signal: drive it to `[]`.**
- Look at a finished connector for the pattern: `modules/sq-kalshi/` (API).

## Steps (all inside `{STAGING}/{bundle}/`)
1. Pick the safest flavour {broker} supports (API > CSV > CLI > browser). Record
   it in `manifest.yaml` + `SKILL.md`.
2. Map all {broker}-dialect knowledge in `src/{pkg}/canonical.py` →
   `to_canonical(raw)`. Implement `src/{pkg}/live.py` → `fetch_live()` (creds via
   `sq_secrets`, never hard-coded). Nothing broker-specific leaks elsewhere.
3. **Wire the discovery contract** — `src/{pkg}/__init__.py` already exposes
   `snapshot()` + `accounts()`; make sure `snapshot()` returns a real
   `PortfolioSnapshot` (this is what makes the app LIST and aggregate the
   connector — a connector without it is invisible). Implement `setup_creds.py`
   and wire `setup` in `bin/{bundle}`.
4. Grow `tests/test_canonical.py` with SYNTHETIC fixtures in {broker}'s real
   shape. Run `./run_tests.sh` and iterate generate → test → fix until green.
   Log dialect quirks in `FINDINGS.md`; flip `manifest.yaml: status` off
   `scaffold` (→ `proof` when fixture-green).
5. **Promote** when green + wired:
   `python -c "import sys; sys.path.insert(0,'core'); import sq_scaffold; print(sq_scaffold.promote('.', '{bundle}'))"`
   — moves it into `modules/`, where the app discovers it.

## Guardrails
- Work only inside `{STAGING}/{bundle}/` (then promote). Don't touch `core/` or
  other connectors.
- No secrets in code, tests, or commits. Synthetic fixtures only.
- Money is `Decimal`, never `float`. Read-only — `execute` (orders) is a
  separate, higher trust tier; don't add it here.
"""


def _write(path: Path, text: str, *, executable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build(root, broker: str, *, base: str = STAGING, force: bool = False) -> Path:
    """Scaffold a connector bundle for `broker` under `<root>/<base>/sq-<slug>/`.
    Returns the bundle Path. Raises FileExistsError if it exists (unless `force`).

    `base` defaults to the **staging** area `.sq-build/` (gitignored): build and
    iterate to green THERE so a half-built bundle never pollutes `modules/` — the
    app only discovers connectors under `modules/`. Call `promote()` to move it
    in once it's wired + green. Pass `base="modules"` to build in place.

    The bundle is conformance-green out of the box AND already exposes the
    `snapshot()`/`accounts()` discovery contract (in __init__.py); GENERATE.md
    carries the brief."""
    bundle, pkg = slugs(broker)
    dest = Path(root) / base / bundle
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} already exists")

    _write(dest / "manifest.yaml", _manifest(bundle, broker))
    _write(dest / "SKILL.md", _skill(bundle, broker))
    _write(dest / "FINDINGS.md", _findings(broker))
    _write(dest / "pyproject.toml", _pyproject(bundle, pkg))
    _write(dest / "bin" / bundle, _bin(bundle, broker), executable=True)
    _write(dest / "src" / pkg / "__init__.py", _init_py(pkg, bundle, broker))
    _write(dest / "src" / pkg / "canonical.py", _canonical(pkg, broker))
    _write(dest / "src" / pkg / "live.py", _live_py(pkg, broker))
    _write(dest / "tests" / "test_canonical.py", _test(pkg, bundle, broker))
    _write(dest / GENERATE_FILE, generator_brief(bundle, pkg, broker))
    return dest


def promote(root, name: str, *, force: bool = False) -> Path:
    """Move a staged bundle (`<root>/.sq-build/sq-<name>`) into `modules/` so the
    app discovers it. `name` may be the slug ('sq-foo') or bare ('foo'). Returns
    the new path. Raises if the staged bundle is missing, or the target exists
    (unless `force`). Do this only once the bundle is wired + conformance-green."""
    slug = name if name.startswith("sq-") else f"sq-{name}"
    src = Path(root) / STAGING / slug
    if not src.is_dir():
        raise FileNotFoundError(f"no staged bundle at {src}")
    dest = Path(root) / "modules" / slug
    if dest.exists():
        if not force:
            raise FileExistsError(f"{dest} already exists")
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    return dest
