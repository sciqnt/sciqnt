#!/usr/bin/env python3
"""publish_component — the virtual-monorepo publishing bot.

During the component-world transition the MONOREPO stays the single source of
truth for the code; each graduated component is *published* from it into its own
`sciqnt/<repo>` (the k8s publishing-bot model). This script regenerates one
component's standalone repo tree from its in-mono package and — crucially —
**verifies it installs clean in an isolated venv and passes its tests**, which is
the guarantee the runbook calls out as "not off-the-shelf, build it"
(`sq-constitution/MIGRATION.md`, Phase 2 / honest residuals).

It is deterministic and idempotent: run it, review the git diff in the target
repo, commit, push. The target's own inherited CI re-verifies on push.

    python scripts/publish_component.py sq-schema            # generate + verify
    python scripts/publish_component.py sq-schema --no-verify # skip the venv check

Adding a component = add a SPEC entry. The first (sq-schema) is the contract hub.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import venv
from pathlib import Path

MONO = Path(__file__).resolve().parent.parent
# caller-templates source — overridable via --constitution / $SCIQNT_CONSTITUTION
# (it's a sibling checkout, not a fixed location).
DEFAULT_CONSTITUTION = Path(
    os.environ.get("SCIQNT_CONSTITUTION",
                   Path.home() / "Projects/sciqnt-org/sq-constitution"))
DEFAULT_TARGET_ROOT = Path(
    os.environ.get("SCIQNT_ORG_ROOT", Path.home() / "Projects/sciqnt-org"))


class Spec:
    """One component's publish recipe: where its code/tests live in the mono and
    how the standalone distribution is described. Every per-component shape —
    third-party deps, sibling sciqnt deps, data files — is DATA here, so a new
    component is genuinely one entry (no template edits)."""

    def __init__(self, repo, dist, import_name, pkg_dir, tests, description, role,
                 dependencies=(), sciqnt_deps=(), package_data=(), version="0.1.0"):
        self.repo = repo                  # sciqnt/<repo> short name, e.g. "sq-schema"
        self.dist = dist                  # PyPI distribution, e.g. "sciqnt-schema"
        self.import_name = import_name    # python import, e.g. "sq_schema"
        self.pkg_dir = MONO / pkg_dir     # the package dir in the mono
        self.tests = [MONO / t for t in tests]   # test files to carry over
        self.description = description
        self.role = role                  # topic/manifest role, NOT in the repo name
        self.dependencies = list(dependencies)    # THIRD-PARTY runtime deps only
        self.sciqnt_deps = list(sciqnt_deps)      # sibling component repos (short names)
        self.package_data = list(package_data)    # non-.py files shipped IN the package
        self.version = version            # stamped into the standalone dist (transition)

    @property
    def tag(self) -> str:
        """The git tag this component is shipped at — DERIVED from its version, so
        the tag a dependent pins always matches the code's declared version (one
        source: Spec.version)."""
        return f"v{self.version}"

    def render_deps(self, pin: str) -> list[str]:
        """Full dependency list: third-party verbatim + each sibling sciqnt dep
        pinned per `pin`. During the transition (`git`) siblings resolve from
        their GitHub repo at the sibling's own version tag; flip to `pypi` once
        published. Raises a clear error if a sciqnt_dep names an unknown component
        (reachability — catches a typo'd or unshipped sibling at generate time)."""
        out = list(self.dependencies)
        for short in self.sciqnt_deps:
            if short not in SPECS:
                raise SystemExit(f"{self.repo}: unknown sciqnt_dep '{short}' "
                                 f"(not in SPECS — typo, or not yet specced?)")
            sib = SPECS[short]
            if pin == "pypi":
                out.append(f"{sib.dist}>=0.1,<0.2")
            else:  # git-ref (transitional): point at the sibling's version tag
                out.append(f"{sib.dist} @ git+https://github.com/sciqnt/"
                           f"{sib.repo}@{sib.tag}")
        return out


SPECS = {
    "sq-schema": Spec(
        repo="sq-schema",
        dist="sciqnt-schema",
        import_name="sq_schema",
        pkg_dir="core/sq_schema",
        tests=["core/tests/test_schema.py", "core/tests/test_contract_schema.py"],
        description="sq-schema — the canonical cross-asset contract for sciqnt "
                    "(point-in-time-correct schema + conformance + JSON-Schema artifact).",
        role="contract-hub",
        dependencies=["pydantic>=2.5,<3"],
        package_data=["contract.schema.json"],   # the language-agnostic artifact
    ),

    # ---- Tier 0: pure leaves (no sciqnt deps) -------------------------------
    "sq-fmt": Spec(
        repo="sq-fmt", dist="sciqnt-fmt", import_name="sq_fmt", pkg_dir="core/sq_fmt",
        tests=["core/tests/test_fmt_contract.py"],
        description="sq-fmt — zero-dependency formatters for sciqnt (money/qty/tables), "
                    "the rendering leaf every connector and the TUI share.",
        role="format-leaf",
    ),
    "sq-config": Spec(
        repo="sq-config", dist="sciqnt-config", import_name="sq_config", pkg_dir="core/sq_config",
        tests=["core/tests/test_config.py"],
        description="sq-config — sciqnt's local-first config store (~/.config/sciqnt), "
                    "sovereign and dependency-light.",
        role="config-leaf",
    ),
    "sq-price-store": Spec(
        repo="sq-price-store", dist="sciqnt-price-store", import_name="sq_price_store",
        pkg_dir="core/sq_price_store", tests=["core/tests/test_price_store.py"],
        description="sq-price-store — local-first price/market-data cache for sciqnt.",
        role="storage-leaf",
    ),

    # ---- Tier 1: depend on the contract / tier-0 leaves ---------------------
    "sq-compute": Spec(
        repo="sq-compute", dist="sciqnt-compute", import_name="sq_compute",
        pkg_dir="core/sq_compute", tests=["core/tests/test_fold.py"],
        description="sq-compute — deterministic money math for sciqnt (position fold, "
                    "P/L decomposition). Decimal-exact, the protected core.",
        role="compute-engine", sciqnt_deps=["sq-schema"],
    ),
    "sq-performance": Spec(
        repo="sq-performance", dist="sciqnt-performance", import_name="sq_performance",
        pkg_dir="core/sq_performance", tests=["core/tests/test_performance.py"],
        description="sq-performance — return/performance analytics over the canonical schema.",
        role="analytics-lib", sciqnt_deps=["sq-schema"],
    ),
    "sq-market-data": Spec(
        repo="sq-market-data", dist="sciqnt-market-data", import_name="sq_market_data",
        pkg_dir="core/sq_market_data",
        tests=["core/tests/test_market_data.py", "core/tests/test_chain_provider.py"],
        description="sq-market-data — market-data overlay (prices/chains) on the canonical schema.",
        role="market-data-lib", sciqnt_deps=["sq-schema"],
    ),
    "sq-fx": Spec(
        repo="sq-fx", dist="sciqnt-fx", import_name="sq_fx", pkg_dir="core/sq_fx",
        tests=["core/tests/test_fx_substrate.py"],
        description="sq-fx — FX substrate (rate resolution/conversion) for sciqnt.",
        role="fx-lib", sciqnt_deps=["sq-config", "sq-schema"],
    ),
    "sq-secrets": Spec(
        repo="sq-secrets", dist="sciqnt-secrets", import_name="sq_secrets",
        pkg_dir="core/sq_secrets", tests=["core/tests/test_secrets_sessions.py"],
        description="sq-secrets — sovereign credential storage for sciqnt (OS keyring, "
                    "user owns the keys).",
        role="secrets-lib", dependencies=["keyring"], sciqnt_deps=["sq-config", "sq-fmt"],
    ),

    # ---- Tier 2: depend on tier-1 libs --------------------------------------
    "sq-analytics": Spec(
        repo="sq-analytics", dist="sciqnt-analytics", import_name="sq_analytics",
        pkg_dir="core/sq_analytics", tests=["core/tests/test_analytics.py"],
        description="sq-analytics — portfolio analytics for sciqnt over schema + compute.",
        role="analytics-lib", sciqnt_deps=["sq-compute", "sq-schema"],
    ),
    "sq-aggregator": Spec(
        repo="sq-aggregator", dist="sciqnt-aggregator", import_name="sq_aggregator",
        pkg_dir="core/sq_aggregator", tests=["core/tests/test_aggregator.py"],
        description="sq-aggregator — cross-account aggregation/standardization layer for sciqnt.",
        role="aggregation-layer", sciqnt_deps=["sq-analytics", "sq-fx", "sq-schema"],
    ),
}

# Split order — siblings must exist + be tagged before a dependent's git-ref
# verify can resolve them (topological by sciqnt_deps). NOTE: sq-schema (the hub)
# is deliberately NOT here — it shipped in Phase 2 and is republished on its own
# (`publish_component.py sq-schema`). After a CONTRACT change, re-ship + re-tag the
# hub FIRST, then re-run the tiers (whose leaves pin it by git-ref).
TIERS = [
    ["sq-fmt", "sq-config", "sq-price-store"],
    ["sq-compute", "sq-performance", "sq-market-data", "sq-fx", "sq-secrets"],
    ["sq-analytics", "sq-aggregator"],
]

PYPROJECT = """\
# GENERATED by sciqnt/sciqnt scripts/publish_component.py — do not hand-edit during
# the transition; edit core/{import_name} in the monorepo and re-publish.
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "{dist}"
version = "{version}"                  # stamped by the publishing bot (transition)
description = "{description}"
readme = "README.md"
requires-python = ">=3.10"
license = {{ text = "MIT" }}
authors = [{{ name = "sciqnt" }}]
dependencies = [
{dependencies_block}]

[project.urls]
Homepage = "https://github.com/sciqnt/{repo}"
Source = "https://github.com/sciqnt/{repo}"

[tool.setuptools]
package-dir = {{ "" = "src" }}
packages = ["{import_name}"]
{package_data_block}"""

README = """\
# {repo} · `{dist}`

{description}

> **Published from the monorepo.** During the component-world transition this repo
> is *generated* from [`sciqnt/sciqnt`](https://github.com/sciqnt/sciqnt)
> (`core/{import_name}`) by its publishing bot. The monorepo is the source of truth
> until the component has fully graduated; **edit there**, not here. Role: `{role}`.

## Install

```bash
pip install {dist}
```
{body}
## Governance

Inherits the org's reusable workflows (CI, principle-review, @claude, issue-triage)
from [`sciqnt/sq-constitution`](https://github.com/sciqnt/sq-constitution). Licensed
MIT; contributions are DCO sign-off, never a CLA.
"""

CONTRACT_BODY = """
## The contract artifact

This package is also published as a **language-agnostic JSON-Schema artifact**,
[`contract.schema.json`](src/{import_name}/contract.schema.json), so a connector in
any language — or a reviewing agent — can read and diff it. Regenerate it from the
models with `python -m {import_name}.json_schema --write`; CI fails if it drifts.
"""

MANIFEST = """\
# Component manifest — machine-readable identity (role lives HERE, not in the name).
name: {dist}
import: {import_name}
repo: sciqnt/{repo}
role: {role}
{depends_line}published_from: sciqnt/sciqnt   # virtual-monorepo source of truth (transition)
license: MIT
"""

GITIGNORE = "__pycache__/\n*.pyc\nbuild/\ndist/\n*.egg-info/\n.venv/\n"


def _reset_tree(target: Path):
    """Clear the GENERATED parts of the target, preserving .git and anything
    we don't own (so a human-added file in the repo isn't nuked silently)."""
    for rel in ("src", "tests", ".github/workflows", "pyproject.toml",
                "README.md", "CHANGELOG.md", "FINDINGS.md", "manifest.yaml",
                "LICENSE", ".gitignore"):
        p = target / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()


def _copy_package(spec: Spec, target: Path):
    dst = target / "src" / spec.import_name
    dst.mkdir(parents=True, exist_ok=True)
    data_files = set(spec.package_data)
    for f in sorted(spec.pkg_dir.iterdir()):
        # Ship the package source + the declared data files; skip build cruft and
        # the package's own pyproject/CHANGELOG (regenerated / relocated).
        if f.suffix == ".py" or f.name in data_files:
            shutil.copy2(f, dst / f.name)
    missing = data_files - {f.name for f in spec.pkg_dir.iterdir()}
    if missing:
        raise SystemExit(f"{spec.repo}: declared package_data not found: {sorted(missing)}")
    # If the package declares __version__ (sq_schema does, for its contract-artifact
    # stamp), it MUST match the stamped dist version — else the git-ref a dependent
    # pins points at code whose declared version disagrees with the tag. Guard it.
    init = dst / "__init__.py"
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init.read_text(), re.M)
    if m and m.group(1) != spec.version:
        raise SystemExit(f"{spec.repo}: package __version__ {m.group(1)!r} != "
                         f"Spec.version {spec.version!r} — reconcile before publishing")
    # Living docs (CHANGELOG, FINDINGS) live at the repo root in the standalone
    # layout — carry them over verbatim so the module's findings travel with it.
    for doc in ("CHANGELOG.md", "FINDINGS.md"):
        src = spec.pkg_dir / doc
        if src.exists():
            shutil.copy2(src, target / doc)


def _copy_tests(spec: Spec, target: Path):
    dst = target / "tests"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "__init__.py").write_text("")
    for t in spec.tests:
        shutil.copy2(t, dst / t.name)


def _copy_workflows(target: Path, constitution: Path):
    dst = target / ".github" / "workflows"
    dst.mkdir(parents=True, exist_ok=True)
    src = constitution / "caller-templates"
    if not src.exists():
        raise SystemExit(
            f"caller-templates not found at {src} — clone sq-constitution there, "
            f"or pass --constitution / set $SCIQNT_CONSTITUTION")
    for wf in sorted(src.glob("*.yml")):
        shutil.copy2(wf, dst / wf.name)


def _render_fields(spec: Spec, pin: str) -> dict:
    deps = spec.render_deps(pin)
    deps_block = "".join(f'    "{d}",\n' for d in deps)
    if spec.package_data:
        items = ", ".join(f'"{p}"' for p in spec.package_data)
        pkg_data_block = (f"\n[tool.setuptools.package-data]\n"
                          f"{spec.import_name} = [{items}]\n")
    else:
        pkg_data_block = ""
    # The contract-artifact README section + manifest line apply only to the hub
    # (the package that ships contract.schema.json).
    is_hub = "contract.schema.json" in spec.package_data
    body = CONTRACT_BODY.format(import_name=spec.import_name) if is_hub else "\n"
    if is_hub:
        depends_line = "contract: self        # this IS the contract\n"
    elif spec.sciqnt_deps:
        sibs = ", ".join(SPECS[s].dist for s in spec.sciqnt_deps)
        depends_line = f"depends_on: [{sibs}]\n"
    else:
        depends_line = ""
    return dict(repo=spec.repo, dist=spec.dist, import_name=spec.import_name,
                description=spec.description, role=spec.role, version=spec.version,
                dependencies_block=deps_block, package_data_block=pkg_data_block,
                body=body, depends_line=depends_line)


def _write_meta(spec: Spec, target: Path, pin: str):
    fields = _render_fields(spec, pin)
    (target / "pyproject.toml").write_text(PYPROJECT.format(**fields))
    (target / "README.md").write_text(README.format(**fields))
    (target / "manifest.yaml").write_text(MANIFEST.format(**fields))
    (target / ".gitignore").write_text(GITIGNORE)
    license_src = MONO / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, target / "LICENSE")


def _verify_clean_install(spec: Spec, target: Path):
    """The publishing guarantee: a fresh venv, `pip install .`, tests pass against
    the INSTALLED package (not the mono's source tree)."""
    vdir = target / ".verify-venv"
    if vdir.exists():
        shutil.rmtree(vdir)
    venv.create(vdir, with_pip=True)
    py = vdir / ("Scripts" if os.name == "nt" else "bin") / "python"
    def run(args, **kw):
        return subprocess.run([str(py), *args], cwd=target, **kw)
    print("  · pip install . (isolated)")
    r = run(["-m", "pip", "install", "-q", "."], capture_output=True, text=True)
    if r.returncode:
        shutil.rmtree(vdir)
        raise SystemExit(f"clean-install FAILED:\n{r.stdout}\n{r.stderr}")
    print("  · unittest discover -s tests (against the installed package)")
    r = run(["-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            capture_output=True, text=True)
    shutil.rmtree(vdir)
    # The build leaves transient artifacts in-tree (gitignored); clean them so a
    # rerun and the pushed tree stay pristine.
    for cruft in list(target.glob("build")) + list(target.rglob("*.egg-info")):
        if cruft.is_dir():
            shutil.rmtree(cruft)
    if r.returncode:
        raise SystemExit(f"standalone tests FAILED:\n{r.stdout}\n{r.stderr}")
    # unittest reports to stderr
    print("  ·", (r.stderr.strip().splitlines() or ["ok"])[-1])


def publish(name: str, target_root: Path, constitution: Path,
            pin: str = "git", verify: bool = True) -> Path:
    spec = SPECS[name]
    target = target_root / spec.repo
    target.mkdir(parents=True, exist_ok=True)
    print(f"publishing {spec.repo} ({spec.dist}) → {target}  [pin={pin}]")
    _reset_tree(target)
    _copy_package(spec, target)
    _copy_tests(spec, target)
    _copy_workflows(target, constitution)
    _write_meta(spec, target, pin)
    print("  · tree generated")
    if verify:
        _verify_clean_install(spec, target)
        print("  · VERIFIED: installs clean + tests green in isolation")
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("component", choices=sorted(SPECS), nargs="?",
                    help="component to publish (or pass --all to do every tier in order)")
    ap.add_argument("--all", action="store_true",
                    help="generate every component in dependency-tier order. NOTE: with "
                         "the default --pin git + verify, this assumes each sibling's "
                         "version tag ALREADY exists on GitHub — true for steady-state "
                         "re-generation, NOT a cold first publish (a tier-N verify fetches "
                         "tier-(N-1) by git-ref). Cold bootstrap: ship tier-by-tier "
                         "(push+tag between tiers), or use --no-verify.")
    ap.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT,
                    help="dir that holds the per-component repo checkouts "
                         "($SCIQNT_ORG_ROOT)")
    ap.add_argument("--constitution", type=Path, default=DEFAULT_CONSTITUTION,
                    help="sq-constitution checkout (caller-templates source) "
                         "($SCIQNT_CONSTITUTION)")
    ap.add_argument("--pin", choices=["git", "pypi"], default="git",
                    help="how to pin sibling sciqnt deps: git-ref (transition) or pypi")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the isolated clean-install + test verification")
    a = ap.parse_args()
    names = [n for tier in TIERS for n in tier] if a.all else [a.component]
    if not a.all and not a.component:
        ap.error("name a component or pass --all")
    for n in names:
        target = publish(n, a.target_root, a.constitution, pin=a.pin, verify=not a.no_verify)
        print(f"done → {target}")


if __name__ == "__main__":
    main()
