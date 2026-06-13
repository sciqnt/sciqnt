"""sq-platform — thin dispatcher & TUI for sciqnt.

Lives in core/ as shared substrate. Discovers bundles by scanning the repo's
`modules/sq-*/bin/sq-*` wrappers — there is NO hard-coded list. Each wrapper
self-describes via two flags (the thin bundle↔platform contract):

  --describe   prints a one-line summary to stdout
  --commands   prints subcommands, one per line, name\\tdescription (tab-sep)

This is the only thing the *bundle-discovery* path requires of a bundle. The
aggregation/home path additionally imports each bundle's package
(`importlib.import_module("sq_"+name)`) to call its `snapshot()` / `accounts()`
— composition in the app layer (P11); modules still never import each other.

The interactive surface is a full-screen app: `sq_tui.select_screen` (one
prompt_toolkit Application on the alternate screen) with a numbered fallback
off-TTY. See `research/tui-experience.md`.
"""
import glob
import os
import shlex
import subprocess
from pathlib import Path

# Design substrate lives in sq_tui — one source of theme/tokens for ALL TUI
# code (the full-screen menus + credential prompts + any future bundle UI).
# Don't duplicate style here.
import sq_tui
from sq_tui import BOLD, BRAND, DIM, RST


def user_modules_dir() -> Path:
    """Where community connectors install — `sciqnt modules add owner/repo`
    drops conformance-passing bundles here. Outside the repo (a pip-installed
    sciqnt has no `modules/`), user-owned, sovereign. `SQ_MODULES_PATH`
    overrides; default follows the same data-dir convention as the price
    archive + insights store."""
    env = os.environ.get("SQ_MODULES_PATH")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "share" / "sciqnt" / "modules"


def bundle_dirs(root) -> list[Path]:
    """Every directory holding a sciqnt bundle, across ALL install sources —
    the single discovery seam (composable doctrine: discovery over
    enumeration; modular + host-agnostic). Sources:
      1. the repo's `modules/sq-*` (dev / git-clone mode)
      2. the user dir `~/.local/share/sciqnt/modules/sq-*` (community
         connectors added via `sciqnt modules add` — no PyPI, no form, no
         central registry; conformance-gated locally)
    A name in BOTH resolves to the repo copy (the maintained bundle beats a
    stale community fetch). Returns deduped bundle dirs, sorted by name."""
    seen: dict[str, Path] = {}
    # User dir first, repo dir second → repo overwrites on name collision.
    for base in (user_modules_dir(), Path(root) / "modules"):
        if not base.is_dir():
            continue
        for d in base.glob("sq-*"):
            if d.is_dir():
                seen[d.name] = d
    return [seen[k] for k in sorted(seen)]


def bundle_src_paths(root) -> list[str]:
    """Each discovered bundle's importable `src/` dir — the launcher adds
    these to sys.path so `import sq_<name>` resolves for community bundles
    too, not only the repo's."""
    return [str(d / "src") for d in bundle_dirs(root) if (d / "src").is_dir()]

# Intro mark — a small braille rendering of the sciqnt tree/sprout (the SVG
# icon). Braille packs 2x4 dots per cell, the highest-resolution monochrome a
# non-image terminal can draw; printed in the brand colour (sq_tui.BRAND).
# Stored as unicode escapes so the source stays pure ASCII. Regenerate via
# the Pillow PNG -> autocrop -> braille pipeline (≤13 cols; rows are ragged).
_TREE = "\u2800\u2800\u2800\u2800\u2802\u2840\u28a0\u2804\u28a0\u2844\n\u2800\u2800\u283a\u2840\u2844\u28a3\u28b0\u2802\u2878\u2840\u2802\u28e4\n\u2800\u2808\u2833\u2804\u2811\u28fc\u28b8\u28b8\u2812\u2863\u2816\n\u2830\u2816\u289a\u28c9\u28c9\u28ea\u28ff\u28f5\u28cb\u28c9\u2809\u2830\u2806\n\u2800\u2830\u2803\u2800\u2800\u2800\u28ff\u2800\u2800\u2800\u2831\u2804\n\u2800\u2800\u2800\u2800\u2800\u2800\u28ff\n\u2800\u2800\u2800\u2800\u2800\u2800\u283b"

VERSION = "0.1-dev"


def banner_text(root):
    """The intro banner as a string, laid out like Claude Code's: the braille
    tree icon on the left, three text lines stacked to its right (name +
    version, tagline, install path), vertically centred. Used both as the
    full-screen home header (drawn once) and by `print_banner` (line path)."""
    tree = _TREE.split("\n")
    width = max(len(ln) for ln in tree)
    # "SciQnt" is the deliberate display LOGOTYPE (the banner only); the command,
    # package prefix, and config dir are all lowercase `sciqnt`.
    text = [
        f"{BOLD}SciQnt{RST} {DIM}v{VERSION}{RST}",
        f"{DIM}Sovereign Cross-Asset Portfolio{RST}",
        f"{DIM}{Path(root).resolve()}{RST}",
    ]
    top = (len(tree) - len(text)) // 2          # vertically centre the text block
    lines = []
    for i, ln in enumerate(tree):
        row = f"  {BRAND}{ln.ljust(width)}{RST}"
        if 0 <= i - top < len(text):
            row += f"   {text[i - top]}"
        lines.append(row)
    return "\n".join(lines)


def print_banner(root):
    """Print the banner — for the line-based surfaces (non-TTY)."""
    print()
    print(banner_text(root))


def discover_bundles(root):
    """Return [(name, wrapper_path, description)] for executable wrappers,
    across every install source (repo + user community dir)."""
    out = []
    for d in bundle_dirs(root):
        for wrapper in sorted(glob.glob(str(d / "bin" / "sq-*"))):
            if not os.access(wrapper, os.X_OK):
                continue
            name = Path(wrapper).name.replace("sq-", "", 1)
            desc = (_run([wrapper, "--describe"]) or "").strip()
            out.append((name, wrapper, desc))
    return out


def commands_of(wrapper):
    """Return [(cmd, description, argspec)] parsed from `<wrapper> --commands`
    (tab-separated). The third field is OPTIONAL and declares the command's
    arguments (e.g. `<from_ccy> <to_ccy> [--asof YYYY-MM-DD]`); when present,
    the module browser prompts for them before running — declared by the unit,
    never hard-wired in the app. Absent → "" → the command runs bare."""
    text = _run([wrapper, "--commands"]) or ""
    out = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = line.split("\t", 2)
        out.append((parts[0],
                    parts[1] if len(parts) > 1 else "",
                    parts[2] if len(parts) > 2 else ""))
    return out


def kinds_of(wrapper):
    """Bundle's self-declared categories, via `<wrapper> --kind` — a
    comma-separated token list (a bundle can live in SEVERAL groups:
    sq-robinhood is broker AND crypto; sq-yahoo is pricing AND fx).
    Capability-declared-by-the-unit, same philosophy as --describe /
    --commands — the dispatcher never hard-codes who is what. Legacy
    single tokens still work; unknown/empty → 'other'."""
    raw = (_run([wrapper, "--kind"]) or "").strip()
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    # Legacy vocabulary from before the data-type split (2026-06-12).
    legacy = {"market-data": "pricing"}
    return [legacy.get(t, t) for t in tokens] or ["other"]


def kind_of(wrapper):
    """First declared category (back-compat shim over `kinds_of`)."""
    return kinds_of(wrapper)[0]


# Display order + label for the category nesting — split by DATA TYPE for
# market data and by MARKET for connectors (owner spec 2026-06-12). A
# bundle appears under EVERY category it declares. Unknown kinds sort
# last under "Other"; nothing breaks when a new token appears.
_KIND_ORDER = [
    ("broker",            "Brokers"),
    ("crypto",            "Crypto"),
    ("prediction-market", "Prediction markets"),
    ("pricing",           "Market data · pricing"),
    ("fx",                "Market data · FX"),
    ("news",              "Market data · news & socials"),
    ("reference",         "Market data · reference"),
    ("filings",           "Market data · filings & fundamentals"),
    ("demo",      "Demo"),
    ("tools",             "Tools & settings"),
    ("other",             "Other"),
]


def discover_grouped(root):
    """Return [(kind, label, [(name, wrapper, desc), …]), …] in display
    order — bundles grouped by their self-declared categories, appearing
    under EVERY category they declare. Empty groups are omitted, so the
    menu only nests categories that actually have modules."""
    bundles = discover_bundles(root)
    by_kind: dict[str, list] = {}
    known = {k for k, _ in _KIND_ORDER}
    for name, wrapper, desc in bundles:
        tokens = kinds_of(wrapper)
        for t in tokens:
            key = t if t in known else "other"
            entry = (name, wrapper, desc)
            if entry not in by_kind.setdefault(key, []):
                by_kind[key].append(entry)
    out = []
    for kind, label in _KIND_ORDER:
        if by_kind.get(kind):
            out.append((kind, label, by_kind[kind]))
    return out


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


def _index_of(items, payload, default=0):
    """Index of the (label, payload) row whose payload == `payload`, for
    sticky-cursor restore across `select_screen` redraws. `default` (0) when
    not found / payload is None."""
    for i, (_, p) in enumerate(items):
        if p == payload:
            return i
    return default


# Top-level browser groups: connectors split by market; ALL market-data
# kinds fold into ONE "Market data" entry whose module screen shows the
# data types as section headers (no flat "Market data · X" rows at the
# top level — owner UX call, 2026-06-12).
# The browser's FOLDER tree (owner spec 2026-06-12): everything that
# feeds the portfolio nests under "Portfolio connectors"; market data
# nests by data type. Folders are real navigation levels — section
# headers don't scale once the community long tail arrives. A subfolder
# label of None means "leaf-direct": the folder opens straight into its
# module list (Tools).
_FOLDERS = [
    ("portfolio", "Portfolio connectors", [
        ("broker",            "Brokers"),
        ("crypto",            "Crypto"),
        ("prediction-market", "Prediction markets"),
    ]),
    ("market-data", "Market data", [
        ("pricing",   "Pricing"),
        ("fx",        "FX"),
        ("news",      "News & socials"),
        ("reference", "Reference"),
        ("filings",   "Filings & fundamentals"),
    ]),
    ("tools", "Tools & settings", [("tools", None), ("demo", None)]),
    ("other", "Other", [("other", None)]),
]


def discover_tree(root):
    """The browser's folder tree: [(key, label, summary, children)] where
    children = [(kind, sublabel | None, mods)]. sublabel None = the
    folder opens straight into its modules (no subfolder level). A
    module appears under every kind it declares."""
    by_kind = {k: mods for k, _, mods in discover_grouped(root)}
    out = []
    for key, label, subs in _FOLDERS:
        children = [(k, sl, by_kind[k]) for k, sl in subs if by_kind.get(k)]
        if not children:
            continue
        distinct = {n for _, _, mods in children for n, _, _ in mods}
        # Counts only — no enumeration of what's inside (simplicity;
        # the contents reveal themselves one level down).
        n = len(distinct)
        summary = f"{n} module{'s' if n != 1 else ''}"
        out.append((key, label, summary, children))
    return out


def find_modules(root, query: str = "") -> int:
    """`sciqnt modules find <query>` — the non-interactive search surface
    (skills-find style): case-insensitive match over name, description
    and category labels; prints `name  [categories]  description` lines.
    Empty query lists everything. Returns a shell exit code (1 = no
    match)."""
    q = (query or "").strip().lower()
    rows, seen = [], set()
    for key, label, _summary, children in discover_tree(root):
        for _kind, sec_label, mods in children:
            cat = sec_label if sec_label else label
            for name, _w, desc in mods:
                if name in seen:
                    # collect every category for the module
                    for r in rows:
                        if r[0] == name and cat not in r[1]:
                            r[1].append(cat)
                    continue
                seen.add(name)
                rows.append([name, [cat], desc])
    matches = [r for r in rows
               if not q or q in r[0].lower() or q in r[2].lower()
               or any(q in c.lower() for c in r[1])]
    if not matches:
        print(f"no modules match {query!r}")
        return 1
    for name, cats, desc in matches:
        print(f"{name:<12} {DIM}[{', '.join(cats)}]{RST}  {desc}")
    return 0


def _module_action_loop(root, category, name, wrapper, last_action_per_module):
    """Inner level: pick + run a module's actions (full-screen, standard chrome).
    Returns when the user backs out (Esc). Shared by the grouped browser.
    `category` is the parent group label, so the menu breadcrumb nests fully
    (Menu › Modules › <cat> › sq-x)."""
    from .home import _chrome_select, _static_chrome   # late import
    while True:
        cmds = commands_of(wrapper)
        if not cmds:
            print(f"\n{DIM}no commands advertised by sq-{name}{RST}")
            return
        items = [(f"{c:<10} {DIM}{d}{RST}", c) for c, d, _a in cmds]
        argspec = {c: a for c, _d, a in cmds}
        sub = _chrome_select(
            root, "modules", ("Modules", category, f"sq-{name}"), items,
            selected=_index_of(items, last_action_per_module.get(name)),
            footer_hint="↑↓ move · ←→ switch agent · enter run · esc back")
        if sub == sq_tui.BACK:
            return
        last_action_per_module[name] = sub
        # A command that DECLARES arguments (third --commands field) gets an
        # in-frame prompt for them — so `sq-fx-ecb show <from> <to>` doesn't
        # die on argparse. Blank is allowed (optional-args case); Esc backs out.
        extra = []
        spec = argspec.get(sub, "")
        if spec:
            hdr = (_static_chrome(root, "modules",
                                  "Modules", category, f"sq-{name}", sub)
                   + f"\n\n  {DIM}arguments: {spec}{RST}")
            raw = sq_tui.text_input_screen(
                "arguments:", header=hdr,
                footer_hint="enter run · esc cancel")
            if raw == sq_tui.BACK:
                continue
            extra = shlex.split(raw)
        # Subprocesses run on the NORMAL screen — clear it and print the static
        # chrome first so their output appears inside the standard layout.
        sq_tui.clear_screen()
        print(_static_chrome(root, "modules", "Modules", category, f"sq-{name}"))
        print(f"\n  {DIM}running: sq-{name} {sub}"
              f"{(' ' + ' '.join(extra)) if extra else ''}{RST}\n")
        try:
            subprocess.run([wrapper, sub, *extra])
        except KeyboardInterrupt:
            pass
        try:
            input(f"\n{DIM}[enter to continue]{RST} ")
        except (EOFError, KeyboardInterrupt):
            return


def run_interactive(root):
    """Module browser: folder → (subfolder) → module → actions → run.
    Every level renders the standard chrome (banner + SciQnt Agent
    component + 'Menu › …' header) via home._chrome_select; Esc steps
    back up one level, then leaves the browser; / filters any level.

    Folder tree per `_FOLDERS` (Portfolio connectors / Market data by
    data type / Tools) — real navigation levels so the list stays
    usable as the community connector long tail arrives. Cursor sticks
    across redraws at every level."""
    from .home import _chrome_select               # late import (home imports us)
    HINT = "↑↓ move · ←→ switch agent · enter open · esc back"
    last_folder = None                                   # last folder key
    last_sub_per_folder = {}                             # folder -> sub kind
    last_module_per_sub = {}                             # (folder, kind) -> sel
    last_action_per_module = {}                          # name -> last action

    def _module_rows(mods):
        # Truncate long descriptions — a wrapped row orphans its tail
        # onto the next line inside the fixed-height frame.
        return [(f"{n:<12} "
                 f"{DIM}{(d[:69] + '…') if len(d) > 70 else d}{RST}",
                 (n, w))
                for n, w, d in mods]

    def _modules_level(crumbs, folder_key, kind, mods):
        """Module list → action loop; returns when the user backs out."""
        while True:
            items = _module_rows(mods)
            sel = _chrome_select(
                root, "modules", crumbs, items,
                selected=_index_of(
                    items, last_module_per_sub.get((folder_key, kind))),
                footer_hint=HINT)
            if sel == sq_tui.BACK:
                return
            last_module_per_sub[(folder_key, kind)] = sel
            name, wrapper = sel
            _module_action_loop(root, crumbs[-1], name, wrapper,
                                last_action_per_module)

    while True:                                           # folder level
        groups = discover_tree(root)
        if not groups:
            print(f"\nno modules found under {Path(root)/'modules'}")
            return
        cat_items = [(f"{lbl:<22} {DIM}{summary}{RST}", k)
                     for k, lbl, summary, _ in groups]
        key = _chrome_select(
            root, "modules", ("Modules",), cat_items,
            selected=_index_of(cat_items, last_folder),
            footer_hint=HINT)
        if key == sq_tui.BACK:
            return                                        # leave the browser
        last_folder = key
        label    = next(l for k, l, _, _ in groups if k == key)
        children = next(c for k, _, _, c in groups if k == key)

        # Leaf-direct folder (Tools) → straight to its module list.
        if len(children) == 1 and children[0][1] is None:
            kind, _, mods = children[0]
            _modules_level(("Modules", label), key, kind, mods)
            continue

        while True:                                       # subfolder level
            sub_items = [
                (f"{sl:<22} {DIM}{len(mods)} "
                 f"module{'s' if len(mods) != 1 else ''}{RST}", k)
                for k, sl, mods in children
            ]
            sub = _chrome_select(
                root, "modules", ("Modules", label), sub_items,
                selected=_index_of(sub_items, last_sub_per_folder.get(key)),
                footer_hint=HINT)
            if sub == sq_tui.BACK:
                break                                     # back to folders
            last_sub_per_folder[key] = sub
            sublabel = next(sl for k, sl, _ in children if k == sub)
            mods     = next(m for k, _, m in children if k == sub)
            _modules_level(("Modules", label, sublabel), key, sub, mods)
