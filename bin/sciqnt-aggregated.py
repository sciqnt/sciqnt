#!/usr/bin/env python3
"""Launcher for the aggregated landing view — math + rendering live in
`sq_platform.aggregated`. This file just adjusts sys.path so each
configured broker bundle is importable, parses optional flags, then
dispatches."""
import argparse
import sys
from datetime import datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
# Each bundle's src/ on the path so `import sq_<broker>` resolves for the
# registry inside sq_platform.aggregated — across ALL install sources (the
# repo's modules/ AND the user's community dir, via bundle_src_paths).
import sq_platform                                          # noqa: E402
for src in sq_platform.bundle_src_paths(ROOT):
    sys.path.insert(0, src)

from sq_platform.aggregated import run_aggregated   # noqa: E402
from sq_platform.home import run_home                # noqa: E402


def _parse_asof(s: str) -> datetime:
    """Parse `YYYY-MM-DD` (or full ISO timestamp) → UTC datetime. We
    interpret a bare date as 23:59:59 UTC on that day so positions reflect
    everything that happened ON that date."""
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc) \
            if "T" in s else \
            datetime.combine(datetime.fromisoformat(s).date(),
                             time(23, 59, 59), tzinfo=timezone.utc)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"--asof must be YYYY-MM-DD or ISO timestamp; got {s!r}"
        ) from e


def main():
    p = argparse.ArgumentParser(prog="sciqnt",
                                description="aggregated portfolio view")
    p.add_argument("--asof", type=_parse_asof, default=None,
                   help="as-of date (YYYY-MM-DD) for a PIT historical view")
    p.add_argument("--fresh", action="store_true",
                   help="bypass the 60s snapshot cache and force a live "
                        "fetch (also invalidates the cache so subsequent "
                        "runs see the fresh data)")
    p.add_argument("--once", action="store_true",
                   help="print the aggregated view once and exit (the "
                        "non-interactive dump; default when stdout is piped)")
    p.add_argument("--history", nargs="?", const="30", default=None,
                   metavar="RANGE",
                   help="print portfolio state history and exit. RANGE is a "
                        "TUI range label (1D/5D/1M/6M/YTD/1Y/5Y/All) for "
                        "exactly that history sub-tab, or a number of days "
                        "(default 30) for the legacy daily/monthly/yearly "
                        "stack")
    p.add_argument("--account", default=None, metavar="LABEL",
                   help="one account only (e.g. degiro:MyName — a unique "
                        "prefix works), in its own base currency; the CLI "
                        "mirror of the app's account drill-down")
    p.add_argument("--tab", default=None, metavar="NAME",
                   help="dump just one tab of the portfolio view (summary/"
                        "positions/exposure/news/flows/detailed)")
    p.add_argument("--json", action="store_true", dest="as_json",
                   help="emit structured data instead of the rendered view "
                        "(versioned schema; Decimals as strings). The "
                        "agent/integration surface — works with --once, "
                        "--history, --account, --asof")
    args = p.parse_args()
    # Materialise the user config on first run so ~/.config/sciqnt/config.json
    # exists, carries documented defaults, and is discoverable + hand-editable
    # (rather than invisible until the first `config set`).
    import sq_config                                          # noqa: E402
    sq_config.materialise()
    # Interactive home when at a terminal and not a one-shot / historical dump;
    # the plain dump otherwise (piping, `--asof`, `--once`, `--history`,
    # `--account`, `--tab`) so scripts + agents keep a stable output.
    interactive = (sys.stdin.isatty() and sys.stdout.isatty()
                   and args.asof is None and not args.once
                   and args.history is None and args.account is None
                   and args.tab is None and not args.as_json)
    try:
        if interactive:
            return run_home(ROOT, use_snapshot_cache=not args.fresh)
        if args.history is not None:
            from sq_platform.aggregated import run_history   # noqa: E402
            return run_history(ROOT, args.history, account=args.account,
                               as_json=args.as_json,
                               use_snapshot_cache=not args.fresh)
        return run_aggregated(
            ROOT, asof=args.asof, account=args.account, tab=args.tab,
            as_json=args.as_json,
            use_snapshot_cache=not args.fresh,
        )
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
