"""The agent → app PUSH channel: insights.

The pull direction (agents reproduce any view via the CLI / `--json`) has a
mirror here — an agent (summoned, scheduled, or external) can LEAVE a short
finding that the app surfaces on the home screen. Local-first and sovereign:
an append-only JSONL the user owns (`~/.local/share/sciqnt/insights.jsonl`,
`SQ_INSIGHTS_PATH` override), plain text only, no execution surface — the
lowest possible trust tier for a write. Read it, grep it, delete it.

CLI surface (the dispatcher routes `sciqnt insight …` here):
    sciqnt insight add "TEXT" [--ref CMD] [--source NAME]
    sciqnt insight list [-n N] [--json]
    sciqnt insight clear

Append-only with tombstones: `clear` appends a marker rather than rewriting
history (same knowledge-time honesty as the price archive). The home shows
UNSEEN insights once, then marks them seen (a `seen` event row).
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

INSIGHTS_SCHEMA = "sciqnt.insight/v1"


def _path() -> Path:
    env = os.environ.get("SQ_INSIGHTS_PATH")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "sciqnt" / "insights.jsonl"


def _append(row: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _read_rows() -> list[dict]:
    p = _path()
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue                     # a torn write never poisons the rest
    return rows


def add(text: str, *, source: str = "agent", ref: str | None = None) -> dict:
    """Record an insight. `ref` is the reproduce-command behind the finding
    (e.g. 'sciqnt --history YTD') so a reader can verify it themselves —
    findings carry their provenance."""
    row = {"schema": INSIGHTS_SCHEMA, "event": "add",
           "id": uuid.uuid4().hex[:12],
           "ts": datetime.now(timezone.utc).isoformat(),
           "text": text.strip(), "source": source, "ref": ref}
    _append(row)
    return row


def mark_seen(ids: list[str]) -> None:
    if ids:
        _append({"schema": INSIGHTS_SCHEMA, "event": "seen",
                 "ts": datetime.now(timezone.utc).isoformat(), "ids": ids})


def clear() -> None:
    _append({"schema": INSIGHTS_SCHEMA, "event": "clear",
             "ts": datetime.now(timezone.utc).isoformat()})


def current(*, unseen_only: bool = False) -> list[dict]:
    """Insights still standing (after the last clear), oldest first.
    `unseen_only` filters to ones never yet shown by the app."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in _read_rows():
        ev = row.get("event")
        if ev == "clear":
            out, seen = [], set()
        elif ev == "seen":
            seen.update(row.get("ids") or [])
        elif ev == "add":
            out.append(row)
    if unseen_only:
        out = [r for r in out if r["id"] not in seen]
    return out


def cli(argv: list[str]) -> int:
    """`sciqnt insight …` — the agent-facing write/read surface."""
    import argparse
    p = argparse.ArgumentParser(prog="sciqnt insight",
                                description="leave / read agent insights "
                                            "shown on the sciqnt home")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="record an insight (shows on home)")
    a.add_argument("text")
    a.add_argument("--ref", default=None,
                   help="the command that reproduces the finding")
    a.add_argument("--source", default="agent")
    ls = sub.add_parser("list", help="list current insights")
    ls.add_argument("-n", type=int, default=10)
    ls.add_argument("--json", action="store_true", dest="as_json")
    sub.add_parser("clear", help="clear all insights")
    args = p.parse_args(argv)

    if args.cmd == "add":
        row = add(args.text, source=args.source, ref=args.ref)
        print(f"  insight recorded ({row['id']}) — shows on the sciqnt home")
        return 0
    if args.cmd == "clear":
        clear()
        print("  insights cleared")
        return 0
    rows = current()[-args.n:]
    if args.as_json:
        print(json.dumps({"schema": INSIGHTS_SCHEMA, "insights": rows},
                         indent=1))
        return 0
    if not rows:
        print("  (no insights)")
        return 0
    for r in rows:
        ref = f"   [{r['ref']}]" if r.get("ref") else ""
        print(f"  {r['ts'][:16]}  {r['source']}: {r['text']}{ref}")
    return 0
