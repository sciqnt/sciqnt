"""sq_config_ui — THE interactive settings screen for sciqnt.

One full-screen settings experience (sq_tui.select_screen on the alternate
screen), consistent with the rest of the app — NOT questionary (questionary
choices don't render ANSI, which is how the old picker leaked raw `^[[2m`
escapes into labels). Every entry point shares this loop:

  * `sciqnt config` (bare) and `sciqnt config set`  → set.py → run_settings()
  * the home's Settings action                       → sq_platform.home calls
    run_settings() in-process with the home chrome, so the experience is
    identical from home and CLI.

The screen lists every setting from `sq_config.schema()`: key left, CURRENT
value right (accent bold); not-yet-wired (`mvp=False`) settings render dim
with a "(soon)" suffix. Per-setting help lives in the `?` overlay, not in the
rows. Selecting a row edits it:
  enum → a second select_screen (current preselected, per-option descriptions),
  bool → toggles immediately (no second screen),
  str  → text_input_screen prefilled with the current value (empty → cancel).
All writes go through `sq_config.set()` (schema-validated, atomic) — an
invalid value is never written. After an edit the screen re-renders with the
cursor kept on the same row. Esc/q returns.

Non-interactive callers must NOT enter this loop — `set.py` checks
`sq_tui._streams_interactive()` and prints the plain dump (`show.py`, the
script/agent-facing surface) instead.
"""
import textwrap
from pathlib import Path

import sq_config
import sq_tui
from sq_tui import BOLD, DIM, RST

# repo root: modules/sq-config/src/sq_config_ui/__init__.py → up 4 levels
_ROOT = Path(__file__).resolve().parents[4]

# Style for the value cell on a non-hovered, wired row (accent bold — matches
# the hover/selection accent everywhere else). Dim rows pass "" so the value
# inherits the row's dim base.
_VALUE_STYLE = f"fg:{sq_tui.ACCENT_HEX} bold"

# Per-option descriptions for enum settings whose schema help implies them.
# preferred_agent is handled dynamically (live install detection).
_ENUM_DESC = {
    "cost_basis_method": {
        "FIFO": "first in, first out",
        "LIFO": "last in, first out",
        "AVG":  "average cost · ACB / Section-104 pool / Degiro BEP",
    },
    "performance_return_method": {
        "TWR": "time-weighted — manager skill (GIPS default)",
        "MWR": "money-weighted / XIRR — your personal cash-flow experience",
    },
}


def parse_bool(v) -> bool:
    """Tolerant bool read for the toggle (true/false/yes/no/1/0/on/off…).
    Anything unrecognised reads as False — the toggle then writes True, a
    safe self-heal for a hand-mangled value. Writes still go through
    `sq_config.set`, which is strict."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on")


def display_value(setting, value) -> str:
    """The row's value cell: bools as lowercase true/false (matching the JSON
    on disk), None as an em-dash, everything else str()."""
    if value is None:
        return "—"
    if setting.type == "bool":
        return "true" if parse_bool(value) else "false"
    return str(value)


def build_settings_items(schema, data):
    """The settings rows for select_screen: (items, item_styles).

    Each item is (fragments, key) — rich labels so the value cell can carry
    its own style: key left, current value right in accent bold; mvp=False
    rows get base style 'dim' plus a "(soon)" suffix (their value inherits
    the dim base instead of the accent). Pure — unit-testable without a
    terminal. Help text deliberately NOT in the row (it's in the ? overlay)."""
    keyw = max(len(s.key) for s in schema)
    vals = {s.key: display_value(s, data.get(s.key, s.default)) for s in schema}
    valw = max(len(v) for v in vals.values())
    items, styles = [], []
    for s in schema:
        frags = [("", f"{s.key:<{keyw}}   "),
                 (_VALUE_STYLE if s.mvp else "", f"{vals[s.key]:>{valw}}")]
        if not s.mvp:
            frags.append(("", "  (soon)"))
        items.append((frags, s.key))
        styles.append(None if s.mvp else "dim")
    return items, styles


def help_text(schema) -> str:
    """The `?` overlay: the keymap plus every setting's full help (the rows
    stay data-only; the prose lives one keystroke away)."""
    lines = [
        f"  {BOLD}Keys{RST}",
        "",
        "  ↑ ↓  ·  j k     move",
        "  enter           edit (a true/false setting toggles immediately)",
        "  ?               toggle this help",
        "  esc  ·  q       back",
        "",
        f"  {BOLD}Settings{RST}",
        "",
    ]
    for s in schema:
        soon = "" if s.mvp else f"  {DIM}(soon — declared, not yet wired){RST}"
        lines.append(f"  {BOLD}{s.key}{RST}{soon}")
        for ln in textwrap.wrap(s.help or "—", 72):
            lines.append(f"    {DIM}{ln}{RST}")
    lines += ["", f"  {DIM}config file: {sq_config.path()}{RST}"]
    return "\n".join(lines)


def _default_header(*crumbs) -> str:
    """Standalone-CLI chrome: the banner + a bold 'Menu › Settings[ › …]'
    breadcrumb — the same level layout as the home (which passes its own
    richer chrome via `make_header`)."""
    menu = "  Menu › Settings" + "".join(f" › {c}" for c in crumbs)
    try:                                      # banner needs sq_platform (core)
        from sq_platform import banner_text
        top = banner_text(_ROOT) + "\n\n"
    except Exception:                                       # noqa: BLE001
        top = ""
    return f"{top}{BOLD}{menu}{RST}"


def _intro(s, cur) -> str:
    """Dim context block for an edit screen: the setting's help (wrapped) +
    current/default, appended to the header (header is ANSI-rendered, unlike
    row labels — this is where styled prose belongs)."""
    lines = textwrap.wrap(s.help or "", 72)
    lines.append(f"current: {display_value(s, cur)} · default: {s.default}")
    return "\n\n" + "".join(f"  {DIM}{ln}{RST}\n" for ln in lines)


def _agent_descs(s):
    """Live per-option tags for preferred_agent — like picking a default
    browser: what 'auto' resolves to, and which agents are actually
    installed. Degrades to no descriptions if detection fails."""
    try:
        import sq_agents
        installed = set(sq_agents.detect())
        auto = sq_agents.resolve("auto")
        hint = sq_agents.label(auto) if auto else "none installed"
        return {v: (f"auto → {hint}" if v == "auto"
                    else "installed" if v in installed else "not installed")
                for v in s.allowed}
    except Exception:                                       # noqa: BLE001
        return {}


def enum_options(s, cur):
    """The second-screen rows for an enum setting: value left, dim
    description right (rich fragments — select_screen strips raw ANSI from
    labels, so styling MUST be fragments, never escape codes), '(current)'
    on the active value."""
    descs = _agent_descs(s) if s.key == "preferred_agent" else \
        _ENUM_DESC.get(s.key, {})
    w = max(len(v) for v in s.allowed)
    out = []
    for v in s.allowed:
        frags = [("", f"{v:<{w}}")]
        d = descs.get(v, "")
        if d:
            frags.append(("class:dim", f"  {d}"))
        if v == cur:
            frags.append(("class:dim", "  (current)"))
        out.append((frags, v))
    return out


def _pick_enum(s, cur, header_for):
    """Enum edit: a second select_screen over the allowed values, the current
    one preselected. Returns the picked value, or None on Esc."""
    sel = sq_tui.select_screen(
        enum_options(s, cur),
        header=header_for(s.key) + _intro(s, cur),
        selected=(s.allowed.index(cur) if cur in s.allowed else 0),
        footer_hint="↑↓ move · enter set · esc cancel",
        esc_result=sq_tui.BACK)
    if sel in (sq_tui.BACK, sq_tui.QUIT):
        return None
    return sel


def _enter_text(s, cur, header_for):
    """Free-form edit: full-screen text input prefilled with the current
    value. Empty (or Esc) → None = cancel, nothing written."""
    raw = sq_tui.text_input_screen(
        f"{s.key}:", header=header_for(s.key) + _intro(s, cur),
        default="" if cur is None else str(cur),
        footer_hint="enter save · esc cancel")
    if raw == sq_tui.BACK or not str(raw).strip():
        return None
    return str(raw).strip()


def _edit(s, header_for):
    """Dispatch one edit by setting type. All writes go through
    `sq_config.set` (schema-validated); a ValueError is swallowed — the loop
    re-renders unchanged rather than ever writing an invalid value."""
    cur = sq_config.get(s.key)
    if s.type == "bool":
        new = not parse_bool(cur)          # toggle immediately — no 2nd screen
    elif s.type == "enum":
        new = _pick_enum(s, cur, header_for)
    else:                                  # str / int → free-form text
        new = _enter_text(s, cur, header_for)
    if new is None:
        return
    try:
        sq_config.set(s.key, new)
    except ValueError:
        pass


def run_settings(make_header=None):
    """The settings loop. `make_header(*crumbs)` builds the chrome above the
    list (the home passes its `_static_chrome`; standalone CLI defaults to
    banner + breadcrumb). Re-renders after every edit with the cursor kept on
    the edited row (select_screen.last_index); Esc/q returns.

    Off-TTY, select_screen itself degrades to the numbered fallback — but
    entry points should route pipes to the plain dump instead (see set.py)."""
    header_for = make_header or _default_header
    sq_config.materialise()                # file exists + carries every key
    cursor = 0
    while True:
        schema = sq_config.schema()
        items, styles = build_settings_items(schema, sq_config.all())
        sel = sq_tui.select_screen(
            items, header=header_for() + "\n",
            item_styles=styles, selected=cursor,
            footer_hint="↑↓ move · enter edit · ? help · esc back",
            help_lines=help_text(schema), esc_result=sq_tui.BACK)
        if sel in (sq_tui.BACK, sq_tui.QUIT):
            return
        li = getattr(sq_tui.select_screen, "last_index", 0)
        if isinstance(li, int):            # mocked select stubs may omit it
            cursor = li
        s = next((x for x in schema if x.key == sel), None)
        if s is not None:
            _edit(s, header_for)
