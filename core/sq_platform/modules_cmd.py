"""`sciqnt modules add|remove|list` — community connector distribution.

The SCALABLE community path (no PyPI, no form, no central registry, no
maintainer bottleneck): a contributor pushes a connector to their own
GitHub repo; a user runs `sciqnt modules add owner/repo`, which fetches it,
runs its conformance suite LOCALLY, and — only if it passes — installs it
into the user's sovereign modules dir. Trust is earned by the harness, not
claimed by a registry (capability principle). The user owns the result:
plain folders under `~/.local/share/sciqnt/modules/`, removable anytime.

Consent + trust tier (honest): `add` RUNS the connector's own test suite to
verify conformance — that executes third-party code on your machine. You opt
in by typing the command; community connectors are "not endorsed" until they
pass conformance in our CI (the certified tier). Read-only connectors only;
execute flavours are a separate, higher tier.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import BOLD, DIM, RST, user_modules_dir


def _git_fetch(spec: str, dest: Path) -> tuple[bool, str]:
    """Shallow-clone `owner/repo[@ref]` (or a full git URL) into `dest`.
    Returns (ok, detail)."""
    ref = None
    if "@" in spec and not spec.startswith(("http", "git@")):
        spec, ref = spec.rsplit("@", 1)
    local = Path(spec).expanduser()
    if local.exists():
        # A local path (a checkout, or a directory) — copy it directly so it
        # works whether or not it's a git repo.
        shutil.copytree(local, dest, ignore=shutil.ignore_patterns(
            ".git", "__pycache__", "*.pyc"))
        return True, str(local)
    url = spec if spec.startswith(("http", "git@")) \
        else f"https://github.com/{spec}.git"          # owner/repo shorthand
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stderr.strip().splitlines()[-1] if r.stderr else "git clone failed"
    return True, url


def _find_bundles(tree: Path) -> list[Path]:
    """Bundle dirs inside a fetched repo: a dir with `manifest.yaml` and a
    `src/sq_*` package. The repo root itself counts (single-connector repo),
    or any subdir (a monorepo of connectors)."""
    found = []
    candidates = [tree] + [d for d in tree.rglob("*") if d.is_dir()
                           and ".git" not in d.parts]
    for d in candidates:
        has_manifest = (d / "manifest.yaml").is_file()
        has_pkg = (d / "src").is_dir() and bool(list((d / "src").glob("sq_*")))
        if has_manifest and has_pkg:
            found.append(d)
    # de-dup nested matches; keep shallowest
    found.sort(key=lambda p: len(p.parts))
    out: list[Path] = []
    for d in found:
        if not any(str(d).startswith(str(o) + "/") for o in out):
            out.append(d)
    return out


def _conformance(bundle: Path, root: Path) -> tuple[bool, str]:
    """Run the bundle's own test suite as the trust gate. No tests → can't
    verify (allowed, but flagged). Runs with core + the bundle's src on the
    path, in a subprocess so a crash can't take down the host."""
    tests = bundle / "tests"
    if not tests.is_dir() or not any(tests.glob("test_*.py")):
        return True, "no tests shipped — conformance UNVERIFIED"
    env = {"PYTHONPATH": f"{root / 'core'}:{bundle / 'src'}"}
    import os
    full_env = {**os.environ, **env}
    r = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(tests)],
        capture_output=True, text=True, env=full_env, cwd=str(bundle))
    if r.returncode == 0:
        # unittest prints the count on stderr
        tail = (r.stderr or "").strip().splitlines()
        return True, tail[-1] if tail else "tests passed"
    return False, (r.stderr or r.stdout or "tests failed").strip().splitlines()[-1]


def _manifest_facts(bundle: Path) -> dict:
    """The few manifest fields we SURFACE at install/list — risk_tier, endorsed,
    provenance (worst flavour risk), status — read line-by-line so the installer
    stays YAML-dependency-free (full parsing belongs to the conformance harness,
    not here). Provenance is the trust signal: official-api > csv/file >
    reverse-engineered."""
    facts = {"risk_tier": "?", "endorsed": None, "status": "",
             "provenance": "n/a", "has_notice": (bundle / "NOTICE.md").is_file()}
    mf = bundle / "manifest.yaml"
    if not mf.is_file():
        return facts
    risks = set()
    for raw in mf.read_text().splitlines():
        s = raw.split("#", 1)[0].strip()           # drop inline comments
        if ":" not in s:
            continue
        key, _, val = s.partition(":")
        key, val = key.strip(), val.strip()
        if key == "risk_tier" and val:
            facts["risk_tier"] = val
        elif key == "status" and val:
            facts["status"] = val
        elif key == "endorsed" and val:
            facts["endorsed"] = val.lower() == "true"
        elif key == "risk" and val:                # per-flavour provenance
            risks.add(val)
    facts["provenance"] = ("reverse-engineered" if "reverse-engineered" in risks
                           else "official" if "official" in risks else "n/a")
    return facts


def _facts_line(facts: dict) -> str:
    """One dim, honest summary line: provenance · risk_tier · endorsement."""
    endorse = ("" if facts["endorsed"] is None
               else " · endorsed" if facts["endorsed"] else " · not endorsed")
    return f"{facts['provenance']} · risk_tier={facts['risk_tier']}{endorse}"


def add(spec: str, root: Path) -> int:
    print(f"  fetching {BOLD}{spec}{RST}…")
    tmp = Path(tempfile.mkdtemp(prefix="sciqnt-add-"))
    try:
        ok, detail = _git_fetch(spec, tmp / "repo")
        if not ok:
            print(f"  could not fetch: {detail}")
            return 1
        bundles = _find_bundles(tmp / "repo")
        if not bundles:
            print("  no sciqnt connector found in that repo "
                  "(needs manifest.yaml + src/sq_<name>/)")
            return 1
        dest_root = user_modules_dir()
        dest_root.mkdir(parents=True, exist_ok=True)
        installed = []
        for b in bundles:
            name = b.name if b.name.startswith("sq-") else \
                "sq-" + next(iter((b / "src").glob("sq_*"))).name[3:].replace("_", "-")
            facts = _manifest_facts(b)
            print(f"  found {BOLD}{name}{RST}  {DIM}{_facts_line(facts)}{RST}")
            if facts["provenance"] == "reverse-engineered" and not facts["has_notice"]:
                print(f"    {DIM}⚠ reverse-engineered, no NOTICE.md disclaimer — "
                      f"community connectors should ship one "
                      f"(research/connector-publishing.md){RST}")
            print("  running conformance…")
            passed, msg = _conformance(b, root)
            mark = "✓" if passed else "✗"
            print(f"    {mark} {msg}")
            if not passed:
                print(f"  {name}: conformance FAILED — not installed "
                      "(fix it, or open an issue on the connector's repo)")
                continue
            target = dest_root / name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(b, target, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "*.pyc"))
            installed.append(name)
        if not installed:
            return 1
        print(f"\n  installed: {', '.join(installed)}")
        print(f"  {DIM}→ {dest_root}{RST}")
        print("  run `sciqnt` — it's discovered automatically; "
              "`sciqnt modules remove <name>` to uninstall.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove(name: str, root: Path) -> int:
    name = name if name.startswith("sq-") else f"sq-{name}"
    target = user_modules_dir() / name
    if not target.is_dir():
        print(f"  {name} is not a community-installed connector "
              f"(only those under {user_modules_dir()} can be removed; "
              "built-in bundles ship with the app)")
        return 1
    shutil.rmtree(target)
    print(f"  removed {name}")
    return 0


def list_installed(root: Path) -> int:
    base = user_modules_dir()
    bundles = sorted(base.glob("sq-*")) if base.is_dir() else []
    if not bundles:
        print("  no community connectors installed "
              "(add one with: sciqnt modules add owner/repo)")
        return 0
    print(f"  community connectors ({base}):")
    for b in bundles:
        facts = _manifest_facts(b)
        print(f"    {b.name.replace('sq-', '', 1)}  {DIM}{_facts_line(facts)}{RST}")
    return 0


def find(query: str, root: Path) -> int:
    """Search the OPTIONAL connector index (`connectors-index.json`) — a thin,
    checked-in discovery catalog, NOT a registry. Discovery is optional and
    sovereign: `modules add owner/repo` works with no index at all, and the
    catalog is non-exhaustive (community connectors may exist that aren't
    listed). Matches `query` against name/broker/provenance/asset-class/cap."""
    idx = Path(root) / "connectors-index.json"
    if not idx.is_file():
        print("  no connector index shipped — discovery is optional; you can "
              "still `sciqnt modules add owner/repo` directly")
        return 0
    try:
        conns = json.loads(idx.read_text()).get("connectors", [])
    except (ValueError, OSError):
        print("  connector index is unreadable")
        return 1
    q = (query or "").lower().strip()

    def _match(e):
        hay = " ".join([
            e.get("name", ""), e.get("broker", ""), e.get("provenance", ""),
            e.get("zone", ""), " ".join(e.get("asset_classes") or []),
            " ".join(e.get("capabilities") or []),
        ]).lower()
        return q in hay

    hits = [e for e in conns if _match(e)] if q else conns
    if not hits:
        print(f"  no indexed connectors match {query!r} ({len(conns)} indexed; "
              "the catalog is non-exhaustive — others may exist unindexed)")
        return 0
    label = f" for {query!r}" if q else ""
    print(f"  {len(hits)} connector(s){label}:")
    for e in hits:
        ac = ",".join(e.get("asset_classes") or []) or "-"
        tier = f"{e.get('zone', '')}/{e.get('provenance', 'n/a')}"
        print(f"    {BOLD}{e['name']}{RST}  "
              f"{DIM}{tier} · {ac} · {e.get('repo', '')}{RST}")
    print(f"  {DIM}install: sciqnt modules add <owner/repo>{RST}")
    return 0


def cli(root, argv: list[str]) -> int:
    if not argv:
        print("usage: sciqnt modules add owner/repo | remove <name> | "
              "list | find <query>")
        return 2
    sub, rest = argv[0], argv[1:]
    root = Path(root)
    if sub == "find":
        return find(rest[0] if rest else "", root)
    if sub == "add":
        if not rest:
            print("usage: sciqnt modules add owner/repo[@ref]")
            return 2
        return add(rest[0], root)
    if sub == "remove":
        if not rest:
            print("usage: sciqnt modules remove <name>")
            return 2
        return remove(rest[0], root)
    if sub == "list":
        return list_installed(root)
    print(f"unknown: modules {sub} (add | remove | list | find)")
    return 2
