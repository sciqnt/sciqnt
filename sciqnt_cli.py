"""sciqnt — the installed CLI front door.

The pip-installable entry point for the component-world structure: `pip install
sciqnt` brings the app (sq_platform + sq_tui + config-UI) plus its library deps
(pinned to the `sciqnt/sq-*` repos), and `sciqnt` launches it.

Unlike the in-repo `bin/sciqnt` launcher (which assumed the monorepo layout), this
entry is layout-free: the app's library deps are installed packages, and connectors
are discovered from the **user dir** (`~/.local/share/sciqnt/modules/`, populated by
`sciqnt modules add owner/repo`) — sovereign, no repo `modules/` needed.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path


def _root() -> Path:
    """The app's data root. For an installed app there's no repo `modules/`, so the
    root is the user data dir — `bundle_dirs(root)` then resolves to the same user
    modules dir connectors are added into. Overridable via $SQ_ROOT."""
    return Path(os.environ.get("SQ_ROOT", Path.home() / ".local" / "share" / "sciqnt"))


def _setup_bundles(root: Path) -> None:
    """Put every installed connector bundle's src/ on sys.path so `import sq_<broker>`
    resolves inside the aggregation registry (mirrors bin/sciqnt-aggregated.py)."""
    import sq_platform
    for src in sq_platform.bundle_src_paths(root):
        if src not in sys.path:
            sys.path.insert(0, src)


def _parse_asof(s: str) -> datetime:
    try:
        return (datetime.fromisoformat(s).replace(tzinfo=timezone.utc) if "T" in s
                else datetime.combine(datetime.fromisoformat(s).date(),
                                      time(23, 59, 59), tzinfo=timezone.utc))
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"--asof must be YYYY-MM-DD or ISO timestamp; got {s!r}") from e


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = _root()
    root.mkdir(parents=True, exist_ok=True)

    # Sub-commands that route straight into the platform (parsed before the
    # aggregated-view flags, exactly like the original bin/sciqnt dispatcher).
    if argv and argv[0] == "modules":
        import sq_platform  # noqa: F401
        from sq_platform import modules_cmd
        _setup_bundles(root)
        return modules_cmd.cli(root, argv[1:])
    if argv and argv[0] == "--list":
        import sq_platform
        _setup_bundles(root)
        return sq_platform.find_modules(root, " ".join(argv[1:]))

    # Otherwise: the aggregated / interactive portfolio view.
    _setup_bundles(root)
    import sq_config
    sq_config.materialise()
    from sq_platform.aggregated import run_aggregated
    from sq_platform.home import run_home

    p = argparse.ArgumentParser(prog="sciqnt", description="sciqnt — portfolio view")
    p.add_argument("--asof", type=_parse_asof, default=None,
                   help="as-of date (YYYY-MM-DD) for a PIT historical view")
    p.add_argument("--fresh", action="store_true",
                   help="bypass the snapshot cache and force a live fetch")
    p.add_argument("--once", action="store_true",
                   help="print the aggregated view once and exit (non-interactive dump)")
    p.add_argument("--history", nargs="?", const="30", default=None, metavar="RANGE",
                   help="print portfolio state history and exit")
    p.add_argument("--account", default=None, metavar="LABEL",
                   help="one account only, in its own base currency")
    p.add_argument("--tab", default=None, metavar="NAME",
                   help="dump just one tab (summary/positions/exposure/news/flows/detailed)")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="emit structured data instead of the rendered view")
    args = p.parse_args(argv)

    interactive = (sys.stdin.isatty() and sys.stdout.isatty()
                   and args.asof is None and not args.once
                   and args.history is None and args.account is None
                   and args.tab is None and not args.as_json)
    try:
        if interactive:
            return run_home(root, use_snapshot_cache=not args.fresh)
        if args.history is not None:
            from sq_platform.aggregated import run_history
            return run_history(root, args.history, account=args.account,
                               as_json=args.as_json, use_snapshot_cache=not args.fresh)
        return run_aggregated(root, asof=args.asof, account=args.account, tab=args.tab,
                              as_json=args.as_json, use_snapshot_cache=not args.fresh)
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
