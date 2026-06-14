"""sq-tui — shared TUI design substrate for sciqnt.

ONE source of design truth: the questionary Style, the ANSI tokens, and the
themed prompt helpers. `sq_platform` (dispatcher) and `sq_secrets` (credential
prompts) both consume this — bundles never carry their own design code.
A visual change (color, qmark, pointer, banner accent) is a one-file edit
that propagates everywhere.

Modules MUST NOT import `questionary` directly for design purposes — go
through `themed_select` / `themed_text` / `themed_password` so the theme
stays uniform across the dispatcher menus and any module's credential or
free-form prompts. The maintenance audit can flag direct imports as drift.
"""
import sys

try:
    import questionary
    HAS_Q = True
except ImportError:
    HAS_Q = False

# Pure formatters / ANSI tokens / charts now live in the zero-dependency
# `sq_fmt` leaf; re-exported here so existing `from sq_tui import fmt_num, BOLD,
# …` keep working and sq_tui's own screens render through the same helpers.
# Importing sq_tui still pulls questionary above (the interactive layer); the
# formatting substrate itself is sq_fmt and stays prompt-toolkit-free.
from sq_fmt import (  # noqa: F401,E402
    NO_COLOR, _c,
    BOLD, DIM, CYAN, GREEN, RED, YELLOW, RST,
    ACCENT_HEX, WARN_HEX, _hex_to_ansi, ACCENT, BRAND, ORANGE, ANSI_RE,
    ok, err, warn_line, heading, pnl,
    fmt_num, fmt_signed, fmt_pct,
    render_chart, render_history, render_pl_bars,
    _vlen, _vpad, format_table, print_table, format_kv, print_kv,
)


# Brand glyphs
QMARK = ""
POINTER = "❯"

# Single style instance everyone uses. Accent + bold on the cursor row.
STYLE = questionary.Style([
    ("qmark",       f"fg:{ACCENT_HEX} bold"),
    ("question",    "bold"),
    ("pointer",     f"fg:{ACCENT_HEX} bold"),
    ("highlighted", f"fg:{ACCENT_HEX} bold"),
    ("selected",    f"fg:{ACCENT_HEX}"),
    ("separator",   "fg:#6c6c6c"),
    ("instruction", "fg:#858585"),
    ("answer",      f"fg:{ACCENT_HEX} bold"),
]) if HAS_Q else None

# Re-export the few questionary primitives bundles need to build menus, so
# they don't have to import `questionary` themselves.
Choice = questionary.Choice if HAS_Q else None
Separator = questionary.Separator if HAS_Q else None


def themed_select(prompt, choices, default=None, instruction=None):
    """Themed wrapper around questionary.select; returns the Question.
    Caller decides between .ask() (lenient: returns None on Ctrl-C) and
    .unsafe_ask() (raises KeyboardInterrupt) — different call sites want
    different cancel semantics."""
    return questionary.select(
        prompt, choices=choices,
        qmark=QMARK, pointer=POINTER, style=STYLE,
        default=default, instruction=instruction,
    )


def themed_text(prompt, default=""):
    """Themed wrapper around questionary.text. Returns the Question."""
    return questionary.text(prompt, qmark=QMARK, style=STYLE, default=default)


def themed_password(prompt):
    """Themed wrapper around questionary.password. Returns the Question."""
    return questionary.password(prompt, qmark=QMARK, style=STYLE)


_QUIET = False
_STATUS_SINK = None        # live-progress capture (see stream_output)


def status(text):
    """Dim informational line for secondary/operational output ('connected …',
    'fetching positions …'). Tertiary to heading() / print_table().
    Routed into the active `stream_output` sink when one is set (live progress
    panels); suppressed inside a `quiet()` block — the home keeps the screen
    clean by silencing this operational chatter during snapshot collection."""
    if _STATUS_SINK is not None:
        _STATUS_SINK(str(text))
        return
    if _QUIET:
        return
    print(f"  {DIM}{text}{RST}")


import contextlib  # noqa: E402
import io          # noqa: E402
import logging     # noqa: E402


@contextlib.contextmanager
def quiet():
    """Silence operational noise for the duration of the block: our own
    `status()` lines AND any stray stdout/stderr/logging from the work inside
    — e.g. a broker library printing an HTTP 401 body when a session has
    expired, which would otherwise pollute the full-screen home. Use ONLY
    around non-interactive work (snapshot collection / aggregation), NEVER
    around a prompt_toolkit `app.run()` (it would swallow the UI)."""
    global _QUIET
    prev = _QUIET
    _QUIET = True
    sink = io.StringIO()
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)                  # mute logging handlers
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            yield
    finally:
        logging.disable(prev_disable)
        _QUIET = prev


@contextlib.contextmanager
def stream_output(sink):
    """Route `status()` lines AND raw stdout/stderr writes into `sink(line)`
    for the duration — the live-progress capture behind async tab computation
    (the panel streams what's being derived instead of freezing). Global like
    `quiet()`; safe to run while a full-screen app renders, because apps write
    to `_REAL_STDOUT`, never `sys.stdout` (see FINDINGS). Lines are ANSI-
    stripped; blanks dropped."""
    global _STATUS_SINK
    prev_sink = _STATUS_SINK
    _STATUS_SINK = sink

    class _LineWriter(io.TextIOBase):
        def __init__(self):
            self._buf = ""

        def write(self, s):
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = ANSI_RE.sub("", line).strip()
                if line:
                    sink(line)
            return len(s)

        def flush(self):
            pass

    w = _LineWriter()
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(w), contextlib.redirect_stderr(w):
            yield
    finally:
        logging.disable(prev_disable)
        _STATUS_SINK = prev_sink


def _clamp_scroll(offset, body_lines, viewport):
    """Clamp a body scroll offset into [0, body_lines - viewport]. Pure —
    the offset math behind tabbed_view's body scrolling, unit-tested without
    a terminal. A body that fits the viewport always clamps to 0."""
    max_off = max(0, body_lines - max(1, viewport))
    return max(0, min(offset, max_off))


def tabbed_view(tabs, title=None, *, header="", agent=None, menu_label=None,
                interactive=None, sub_defaults=None):
    """Interactive tabbed view (prompt_toolkit). Arrow-key / 1-9 navigation
    across tabs; esc/q/^C exit; ← on the first tab = back; ^R exits with the
    REFRESH sentinel (the CALLER re-fetches and re-opens). `tabs` is an ordered
    dict of {label: str | callable->str | dict} — a DICT value is a set of
    SUB-TABS ({sub_label: str | callable}), rendered as a second tab bar under
    the main one: ↓ focuses it, ←/→ switch the sub-tab (← past the first goes
    back up), ↑ returns to the main tabs. Bodies should be pre-rendered (ANSI
    is parsed by prompt_toolkit); callables are lazy + memoised per (tab, sub).
    Non-interactive callers fall back to printing every tab (and sub-tab) in
    sequence — pipeable / scriptable / CI-safe. `interactive=None` (default)
    auto-detects: BOTH stdin and stdout must be TTYs for the full-screen app;
    pass `interactive=False` to force the line dump (the `--once`/script
    surfaces do), `True` to force the app.

    Optional home-style chrome (so detail views match the landing):
      * `header`  — ANSI block (the banner) rendered above everything.
      * `agent`   — the SciQnt Agent component: {"prefix", "options": [str],
        "selected": int, "hint": str}. Rendered under the header; press ↑ to
        focus it (←/→ choose a framework — ← past the leftmost exits, enter
        returns ("agent", index) to the caller to launch), ↓ back to the tabs.
      * `menu_label` — e.g. "Menu › portfolio": replaces `title` at the start of
        the tab-bar line, home-menu style.

    A body (or lazy body result) may be a TUPLE `(body, note)` — the note is
    reference info (coverage, definitions) shown only in the `?` help overlay,
    keeping the view itself data-only. Non-TTY prints body + note inline so
    dumps stay complete.

    Returns None when closed, or ("agent", index) when the agent row was
    activated (the CALLER launches — sq_tui stays platform-free).

    Defaults to the first tab; current tab gets the brand highlight."""
    labels = list(tabs.keys())
    if not labels:
        return None

    _lazy: dict = {}
    sub_active: dict = {}                  # main label → active sub index
    # `sub_defaults` = {tab_label: sub_label} — which sub-tab a dict tab
    # OPENS on (e.g. history opens on YTD). Unknown labels are ignored.
    for _lab, _sub in (sub_defaults or {}).items():
        _b = tabs.get(_lab)
        if isinstance(_b, dict) and _sub in _b:
            sub_active[_lab] = list(_b.keys()).index(_sub)

    def _subs(label):
        """Sub-tab labels for a dict-valued tab, else None."""
        b = tabs[label]
        return list(b.keys()) if isinstance(b, dict) else None

    def _split(v):
        """A body may be `(body, note)` — note lives in the ? help overlay."""
        if isinstance(v, tuple) and len(v) == 2:
            return v[0], v[1]
        return v, None

    def _resolve(value, key):
        """str | tuple | callable → resolved value, lazily memoised under `key`
        (the renderer calls per frame; an expensive body must not recompute
        per keystroke)."""
        if callable(value):
            if key not in _lazy:
                _lazy[key] = value()
            return _lazy[key]
        return value

    def _body(label):
        b = tabs[label]
        if isinstance(b, dict):
            subs = list(b.keys())
            sl = subs[sub_active.get(label, 0)]
            return _resolve(b[sl], (label, sl))
        return _resolve(b, label)

    # Non-interactive fallback — print all tabs (and sub-tabs) sequentially.
    if interactive is None:
        interactive = _streams_interactive()
    if not interactive or not HAS_Q:
        if title:
            print(f"\n  {BOLD}{title}{RST}")

        def _safe(value, key):
            """One failing tab must not kill the whole dump — mirror the
            interactive `_resolve_live` degradation."""
            try:
                return _split(_resolve(value, key))
            except Exception as e:                              # noqa: BLE001
                return f"  (tab failed: {type(e).__name__}: {e})", None

        for label in labels:
            b = tabs[label]
            if isinstance(b, dict):
                for sl, v in b.items():
                    print(f"\n  {DIM}── {label} › {sl} ──{RST}\n")
                    body, note = _safe(v, (label, sl))
                    print(body + (("\n\n" + note) if note else ""))
            else:
                print(f"\n  {DIM}── {label} ──{RST}\n")
                body, note = _safe(b, label)
                print(body + (("\n\n" + note) if note else ""))
        print()
        return None

    # Interactive path — prompt_toolkit Application with a horizontal tab bar.
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style as PtkStyle

    active = [0]
    focus = ["tabs"]                          # "tabs" | "agent" | "subtabs"
    tabbed_view.last_view = None     # (tab, sub|None, body) on agent summon
    asel = [agent["selected"] if agent else 0]
    scroll = [0]                              # body scroll offset (lines)

    # Interactive lazy bodies compute in a BACKGROUND thread with a live
    # progress panel: the tab paints immediately (spinner + the captured
    # status/stdout lines streaming in) and swaps in the result when done —
    # an expensive tab (summary TWR, history folds) never freezes the UI.
    import threading
    _pending: dict = {}
    _tick = [0]
    _stream_lock = threading.Lock()           # one capture at a time (global sink)

    def _resolve_live(value, key):
        if not callable(value):
            return value
        if key in _lazy:
            return _split(_lazy[key])[0]
        st = _pending.get(key)
        if st is None:
            st = {"lines": []}
            _pending[key] = st

            def _worker():
                def sink(line):
                    st["lines"].append(line)
                    try:
                        app.invalidate()
                    except Exception:                       # noqa: BLE001
                        pass
                try:
                    with _stream_lock, stream_output(sink):
                        res = value()
                except Exception as e:                      # noqa: BLE001
                    res = f"  (tab failed: {type(e).__name__}: {e})"
                _lazy[key] = res
                _pending.pop(key, None)
                try:
                    app.invalidate()
                except Exception:                           # noqa: BLE001
                    pass
            threading.Thread(target=_worker, daemon=True).start()
        _tick[0] += 1
        spin = _SPINNER[_tick[0] % len(_SPINNER)]
        out = f"\n  {BRAND}{spin}{RST} deriving…\n\n"
        for line in st["lines"][-14:]:
            out += f"  {DIM}{line}{RST}\n"
        return out

    def _resolve_live_raw(value, key):
        """Non-callable values pass through _split too."""
        if not callable(value):
            return _split(value)[0]
        return _resolve_live(value, key)

    def _body_live(label):
        b = tabs[label]
        if isinstance(b, dict):
            subs = list(b.keys())
            sl = subs[sub_active.get(label, 0)]
            return _resolve_live_raw(b[sl], (label, sl))
        return _resolve_live_raw(b, label)

    show_help = [False]

    def _active_note():
        """The resolved note of the ACTIVE (sub-)tab, for the ? overlay."""
        lab = labels[active[0]]
        b = tabs[lab]
        if isinstance(b, dict):
            subs = list(b.keys())
            sl = subs[sub_active.get(lab, 0)]
            v = _lazy.get((lab, sl), b[sl] if not callable(b[sl]) else None)
        else:
            v = _lazy.get(lab, b if not callable(b) else None)
        return _split(v)[1] if v is not None else None

    def _help_text():
        lines = [
            f"  {BOLD}Keys{RST}",
            "",
            "  ←/→ · h/l      switch tabs (← on the first = back)",
            "  ↓ / ↑          focus sub-tabs / the agent row",
            "  j/k            scroll the body by line",
            "  PgUp/PgDn      scroll the body by page",
            "  g / G          scroll to top / bottom",
            "  1-9            jump within the focused row",
            "  enter          launch the agent (agent row focused)",
            "  ^R             refresh (re-fetch and re-open)",
            "  ?              toggle this help",
            "  esc · q · ^C   close",
        ]
        note = _active_note()
        if note:
            lines += ["", f"  {BOLD}About this view{RST}", "", note]
        return "\n".join(lines)

    def _agent_fragments():
        """Home-style agent row + greyed hint. Neutral until focused (↑); then
        the ❯ pointer, prefix and the selected framework accent."""
        focused = focus[0] == "agent"
        row = "class:agent-sel" if focused else ""
        out = [(row, f" {'❯' if focused else ' '} "), (row, agent["prefix"])]
        for k, opt in enumerate(agent["options"]):
            if k:
                out.append(("", "  |  "))
            on = focused and k == asel[0]
            out.append(("class:agent-sel" if on else "", opt))
        out.append(("", "\n"))
        # Warning mode: the greyed Ask-hint slot becomes an orange
        # "⚠ Recommended: Troubleshoot with Agent" block listing the issues;
        # same layout (row first), same toggle — only the hint is replaced.
        # Capped so a long outage list can't push the body off the frame.
        warns = agent.get("warn") or []
        if warns:
            out.append(("class:warn", "   ⚠ Recommended: Troubleshoot with Agent\n"))
            for w in warns[:3]:
                out.append(("class:warn", f"      {w}\n"))
            if len(warns) > 3:
                out.append(("class:warn", f"      …and {len(warns) - 3} more\n"))
        else:
            out.append(("class:hint", f"   {agent['hint']}\n"))
        out.append(("", "\n"))
        return FormattedText(out)

    def _tab_bar():
        parts = []
        # The menu/title gets its OWN line; the tab strip sits on the row
        # below — a long breadcrumb (e.g. an account label) must never push
        # the tabs off the right edge.
        if menu_label:
            parts.append(("class:title", f"  {menu_label}\n"))
        elif title:
            parts.append(("class:title", f"  {title}\n"))
        # ❯ marks the FOCUSED row — the same cursor pattern as every list in
        # the TUI (tabs row when tabs are focused, sub-tabs row when those are).
        parts.append(("class:ptr", " ❯ " if focus[0] == "tabs" else "   "))
        for i, lab in enumerate(labels):
            if i == active[0]:
                parts.append(("class:tab-active", f" {lab} "))
            else:
                parts.append(("class:tab-inactive", f" {lab} "))
            if i < len(labels) - 1:
                parts.append(("class:tab-sep", "│"))
        parts.append(("", "\n"))
        # Second-level bar when the active tab has sub-tabs (↓ to focus).
        subs = _subs(labels[active[0]])
        if subs:
            si = sub_active.get(labels[active[0]], 0)
            parts.append(("class:ptr",
                          "   ❯ " if focus[0] == "subtabs" else "     "))
            for j, sl in enumerate(subs):
                if j == si:
                    parts.append(("class:tab-active", f" {sl} "))
                else:
                    parts.append(("class:tab-inactive", f" {sl} "))
                if j < len(subs) - 1:
                    parts.append(("class:tab-sep", "│"))
            parts.append(("", "\n"))
        return FormattedText(parts)

    def _viewport():
        """The body window's rendered height (lines). 24 before first paint."""
        info = getattr(body_window, "render_info", None)
        return info.window_height if info else 24

    def _body_render():
        if show_help[0]:
            return ANSI(_help_text())
        text = _body_live(labels[active[0]])
        if scroll[0]:
            lines = text.split("\n")
            scroll[0] = _clamp_scroll(scroll[0], len(lines), _viewport())
            text = "\n".join(lines[scroll[0]:])
        return ANSI(text)

    def _scroll_by(delta):
        """Scroll the body window by `delta` lines (clamped; no-op when the
        body fits the viewport)."""
        if show_help[0]:
            return
        n = _body_live(labels[active[0]]).count("\n") + 1   # memoised body
        scroll[0] = _clamp_scroll(scroll[0] + delta, n, _viewport())

    def _footer():
        if show_help[0]:
            hint = " ? close help · esc back "
        elif focus[0] == "agent":
            hint = " ←/→ choose framework · enter launch · ↓ back to tabs "
        elif focus[0] == "subtabs":
            hint = (" ←/→ sub-tabs · 1-9 jump · ↑ tabs · ^R refresh · ? help "
                    "· esc/q exit ")
        else:
            hint = " ←/→ tabs · 1-9 jump"
            hint += " · ↓ sub-tabs" if _subs(labels[active[0]]) else ""
            hint += " · ↑ agent" if agent else ""
            hint += " · ^R refresh · ? help · esc/q/^C exit "
        return FormattedText([("class:footer", hint)])

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        if focus[0] == "subtabs":
            focus[0] = "tabs"
        elif agent:
            focus[0] = "agent"

    @kb.add("down")
    def _down(event):
        if focus[0] == "agent":
            focus[0] = "tabs"
        elif focus[0] == "tabs" and _subs(labels[active[0]]):
            focus[0] = "subtabs"

    @kb.add("enter")
    def _enter(event):
        if focus[0] == "agent":
            # Capture the summon FACTS — where the user is (active tab +
            # sub-tab) and the rendered body they're literally looking at —
            # so the caller can hand the agent honest state instead of
            # hand-assembled context. ANSI-stripped: the body travels as a
            # plain-text context file.
            lab = labels[active[0]]
            subs = _subs(lab)
            tabbed_view.last_view = (
                lab, subs[sub_active.get(lab, 0)] if subs else None,
                ANSI_RE.sub("", _body_live(lab)))
            event.app.exit(result=("agent", asel[0]))

    @kb.add("left")
    @kb.add("h")
    def _l(event):
        # ← steps left; at the LEFT EDGE it goes back (up a focus level, or out
        # of the view) — the same no-wrap convention as everywhere else.
        if focus[0] == "agent":
            if asel[0] > 0:
                asel[0] -= 1
            else:
                event.app.exit()
        elif focus[0] == "subtabs":
            lab = labels[active[0]]
            si = sub_active.get(lab, 0)
            if si > 0:
                sub_active[lab] = si - 1
                scroll[0] = 0
            else:
                focus[0] = "tabs"          # past the first sub-tab → back up
        elif active[0] == 0:
            event.app.exit()
        else:
            active[0] -= 1
            scroll[0] = 0

    @kb.add("right")
    @kb.add("l")
    def _r(event):
        if focus[0] == "agent":
            asel[0] = min(asel[0] + 1, len(agent["options"]) - 1)
        elif focus[0] == "subtabs":
            lab = labels[active[0]]
            subs = _subs(lab) or []
            sub_active[lab] = min(sub_active.get(lab, 0) + 1, len(subs) - 1)
            scroll[0] = 0
        else:
            active[0] = min(active[0] + 1, len(labels) - 1)    # stop at the end
            scroll[0] = 0

    for idx in range(min(9, len(labels))):
        @kb.add(str(idx + 1))
        def _j(event, idx=idx):
            if focus[0] == "subtabs":
                lab = labels[active[0]]
                subs = _subs(lab) or []
                if idx < len(subs):
                    sub_active[lab] = idx
            else:
                active[0] = idx
            scroll[0] = 0

    # Body scrolling — j/k by line, PgUp/PgDn by page, g/G to top/bottom
    # (↑/↓ stay focus-navigation: agent row / sub-tabs; offset resets on any
    # tab or sub-tab switch).
    @kb.add("j")
    def _scroll_down(event):
        _scroll_by(1)

    @kb.add("k")
    def _scroll_up(event):
        _scroll_by(-1)

    @kb.add("pagedown")
    def _page_down(event):
        _scroll_by(_viewport())

    @kb.add("pageup")
    def _page_up(event):
        _scroll_by(-_viewport())

    @kb.add("g")
    def _top(event):
        scroll[0] = 0

    @kb.add("G")
    def _bottom(event):
        _scroll_by(10 ** 9)

    @kb.add("c-r")
    def _refresh(event):
        # The view can't re-fetch itself (it holds pre-built bodies) — exit
        # with the REFRESH sentinel; the caller rebuilds and re-opens.
        event.app.exit(result=REFRESH)

    @kb.add("?")
    def _help(event):
        show_help[0] = not show_help[0]

    @kb.add("escape")
    @kb.add("q")
    @kb.add("c-c")
    def _x(event):
        if show_help[0]:
            show_help[0] = False
        else:
            event.app.exit()

    style = PtkStyle.from_dict({
        "title":        "bold",
        "tab-active":   f"fg:#000000 bg:{ACCENT_HEX} bold",
        "tab-inactive": f"fg:{ACCENT_HEX}",
        "tab-sep":      "fg:#6c6c6c",
        "footer":       "fg:#858585",
        "agent-sel":    f"fg:{ACCENT_HEX} bold",
        "ptr":          f"fg:{ACCENT_HEX} bold",
        "hint":         "fg:#6c6c6c",
        "warn":         f"fg:{WARN_HEX}",
    })

    body_window = Window(FormattedTextControl(_body_render), wrap_lines=False)
    panes = []
    if header:
        panes.append(Window(FormattedTextControl(lambda: ANSI(header)),
                            dont_extend_height=True))
    if agent:
        panes.append(Window(FormattedTextControl(_agent_fragments),
                            dont_extend_height=True))
    panes += [
        Window(FormattedTextControl(_tab_bar), dont_extend_height=True),
        body_window,
        Window(FormattedTextControl(_footer), height=1, dont_extend_height=True),
    ]
    layout = Layout(HSplit(panes))

    app = Application(
        layout=layout, key_bindings=kb, style=style,
        full_screen=True, mouse_support=False, color_depth=_app_color_depth(),
        output=_app_output(), refresh_interval=0.15,
    )
    return app.run()


# ── full-screen single-select (the home / menu primitive) ───────────────────
# Navigation sentinels returned by select_screen.
QUIT = "__quit__"
REFRESH = "__refresh__"
BACK = "__back__"
TOGGLED = "__toggled__"   # a toggle with exit_on_change moved — caller re-renders
SEP = "__sep__"          # a non-selectable blank divider row in select_screen items


def breadcrumb(*parts):
    """Compact accent breadcrumb for full-screen sub-views, e.g.
    'sciqnt › Modules › sq-degiro'. First part bold-accent, rest dim. Used as a
    light header for drill-down screens (the full logo is the home's alone)."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    sep = f" {DIM}›{RST} "
    out = [f"{BOLD}{ACCENT}{parts[0]}{RST}"]
    out += [f"{DIM}{p}{RST}" for p in parts[1:]]
    return "  " + sep.join(out)


def clear_screen():
    """Clear the screen + scrollback and home the cursor (raw ANSI) — the ONE
    home for the escape sequence (callers must not carry their own `_CLR`).
    No-op when stdout isn't a TTY, so piped/captured output stays clean."""
    try:
        is_tty = _REAL_STDOUT.isatty()
    except Exception:                                       # noqa: BLE001
        is_tty = False
    if is_tty:
        # Write to the REAL terminal — a swapped sys.stdout (quiet()/
        # capture) must neither suppress the clear nor swallow the codes.
        print("\033[2J\033[3J\033[H", end="", flush=True,
              file=_REAL_STDOUT)


def _app_color_depth():
    """Force monochrome under NO_COLOR; else let prompt_toolkit auto-detect."""
    if NO_COLOR:
        from prompt_toolkit.output.color_depth import ColorDepth
        return ColorDepth.DEPTH_1_BIT
    return None


# The REAL terminal stdout, captured at import (before any `quiet()` swap). All
# full-screen apps render to THIS, so `quiet()` (which swaps `sys.stdout` to
# suppress broker chatter) can run concurrently — even in a background thread —
# without ever blanking or corrupting the UI. See `quiet()`.
_REAL_STDOUT = sys.stdout


def _streams_interactive() -> bool:
    """True when BOTH stdin and the REAL terminal stdout are TTYs — the
    one home for the interactive-vs-fallback decision.

    Must test `_REAL_STDOUT`, never `sys.stdout`: the latter is routinely
    SWAPPED to a capture buffer (`quiet()`, the home's progress capture),
    and a swapped buffer must not demote a real terminal session to the
    numbered-text fallback. Bug 2026-06-11: `sciqnt` at a real TTY hung
    with a blank screen — the home's main menu took the fallback (its
    menu went into the capture) and blocked on an invisible
    `input("Choice: ")`."""
    try:
        return sys.stdin.isatty() and _REAL_STDOUT.isatty()
    except Exception:                                       # noqa: BLE001
        return False


def _app_output():
    """A prompt_toolkit Output bound to the real terminal, independent of any
    `sys.stdout` redirection. None if we can't build one (caller lets ptk
    default)."""
    try:
        from prompt_toolkit.output.defaults import create_output
        return create_output(stdout=_REAL_STDOUT)
    except Exception:                                       # noqa: BLE001
        return None


def _filter_indices(items, query: str) -> list:
    """Indices of rows visible under a type-to-filter query: empty query →
    everything; otherwise case-insensitive substring match over each row's
    visible text, with SEP rows DROPPED (filtered results read as a flat
    ranked list, `npx skills find`-style)."""
    if not query:
        return list(range(len(items)))
    q = query.lower()
    out = []
    for i, (label, payload) in enumerate(items):
        if payload == SEP:
            continue
        txt = label if isinstance(label, str) else "".join(t for _, t in label)
        if q in ANSI_RE.sub("", txt).lower():
            out.append(i)
    return out


def select_screen(items, *, header="", footer_hint=None, help_lines=None,
                  selected=0, esc_result=QUIT, extra_keys=None, item_styles=None,
                  toggle=None, app_holder=None):
    """Full-screen single-select list on the alternate screen buffer — the
    persistent-layout replacement for re-printed line menus.

    Layout: a `header` (pre-rendered ANSI string, drawn ONCE at top — logo,
    portfolio summary…), a selectable body of `items` (list[(label, payload)];
    `label` is a str, OR a list of (style, text) fragments for per-cell colour —
    e.g. green/red P/L — where an empty fragment style inherits the row base),
    and a sticky `footer_hint`. A SEP payload renders a non-selectable row: blank if
its label is empty, else a header-styled (bold) static-text block (e.g. a
table's column header). Returns the chosen payload, or a sentinel:
    REFRESH (^R), `esc_result` (Esc/q — defaults to QUIT at the top level), or
    any value mapped in `extra_keys` {prompt_toolkit-key: payload}. `?` toggles
    a help overlay (`help_lines`, ANSI). `item_styles` (parallel to `items`)
    sets a per-row style class used when that row is NOT hovered — `'head'`
    (bold, e.g. a PORTFOLIO total) or `'dim'` (greyed, e.g. an account); the
    hovered row is always accent. The final cursor index is exposed as
    `select_screen.last_index` so a caller loop can keep the cursor in place.

    `app_holder` (optional 1-element list): receives the prompt_toolkit
    Application before it runs, so a background thread can exit it
    thread-safely (`app.loop.call_soon_threadsafe(app.exit)`) — used for
    stale-while-revalidate (refresh in the background, re-render when ready).

    `toggle` makes ONE row a horizontal selector (e.g. an agent-framework
    picker): `{"index": int, "prefix": ANSI str, "options": [str,...],
    "selected": int, "default": int|None}`. When the cursor is on that row, ←/→
    cycle the segments live (in-place, no exit); the selected segment is accent,
    the `default` segment is tagged. The chosen segment index is exposed as
    `select_screen.toggle_selected`. On rows other than the toggle, ← is back.

    Non-TTY / no questionary → prints the header + a numbered menu (the
    accessible, scriptable fallback) and reads a line. The interactive frame is
    TTY-only; this keeps pipes / NO_COLOR / screen-reader use working."""
    select_screen.last_index = selected
    if not items:
        return esc_result

    if not (HAS_Q and _streams_interactive()):
        vis = [(label, p) for label, p in items if p != SEP]   # drop dividers
        if header:
            print(header)
        print()
        for i, (label, _) in enumerate(vis, 1):
            txt = label if isinstance(label, str) else "".join(t for _, t in label)
            print(f"  {i}) {ANSI_RE.sub('', txt)}")
        try:
            raw = input("Choice: ").strip()
            i = int(raw) - 1
            if 0 <= i < len(vis):
                select_screen.last_index = i
                return vis[i][1]
        except (EOFError, KeyboardInterrupt, ValueError):
            pass
        return esc_result

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style as PtkStyle

    def _publish_toggles():
        select_screen.toggle_selected = tsel[0] if tsel else 0
        select_screen.toggle_selected_by_index = {
            t["index"]: tsel[slot] for slot, t in enumerate(toggles)}

    query = [""]                                      # the / type-to-filter
    visible = [list(range(len(items)))]               # row indices on screen

    def _selectable():
        return [i for i in visible[0] if items[i][1] != SEP]

    def _recompute_filter():
        visible[0] = _filter_indices(items, query[0])
        vis = _selectable()
        if vis and sel[0] not in vis:
            sel[0] = vis[0]

    def _step(cur, d):
        """Move the cursor by `d` within the VISIBLE selectable rows
        (skips SEP dividers; respects an active filter)."""
        vis = _selectable()
        if not vis:
            return cur
        if cur in vis:
            return vis[(vis.index(cur) + d) % len(vis)]
        return vis[0]

    start = max(0, min(selected, len(items) - 1))
    if items[start][1] == SEP:                        # never start on a divider
        start = _step(start, 1)
    sel = [start]
    mode = ["menu"]                                   # "menu" | "help" | "filter"
    # `toggle` accepts one dict (legacy) or a LIST of dicts — several
    # horizontal selectors can coexist (agent row + range row). Each may
    # set "exit_on_change": True to exit the app with TOGGLED whenever
    # ←/→ moves it (callers that must recompute content react and
    # re-render; the cursor sticks via last_index).
    toggles = ([toggle] if isinstance(toggle, dict) else list(toggle or []))
    t_by_index = {t["index"]: (slot, t) for slot, t in enumerate(toggles)}
    tsel = [t["selected"] for t in toggles] or [0]

    def _toggle_fragments(slot, t, hovered):
        """Render a horizontal-toggle row: prefix + ' | '-joined options. The
        row reads as a plain (neutral) row UNTIL it's hovered; only then does the
        ❯ pointer and the SELECTED option show in accent — so it doesn't look
        'on' while the cursor is elsewhere."""
        ptr = "❯" if hovered else " "
        row = "class:sel" if hovered else "class:item"
        sep = t.get("separator", "  |  ")
        out = [(row, f" {ptr} ")]
        if t.get("prefix"):
            out.append((row, t["prefix"]))          # prefix accents on hover
        for k, opt in enumerate(t["options"]):
            if k:
                out.append(("class:item", sep))
            # "always_accent" toggles (the range bar) show the active pick
            # like a tab bar — highlighted whether or not the row is
            # hovered; legacy toggles (agent row) highlight on hover only.
            accent = (hovered or t.get("always_accent")) and k == tsel[slot]
            out.append(("class:sel" if accent else "class:item", opt))
        out.append(("class:item", "\n"))
        return out

    def _header():
        return ANSI(header) if header else FormattedText([])

    def _body():
        if mode[0] == "help" and help_lines:
            return ANSI(help_lines)
        out = []
        for i in visible[0]:
            label, payload = items[i]
            if payload == SEP:                         # non-selectable divider…
                if label and "\x1b" in label:          # ANSI block (e.g. a chart)
                    from prompt_toolkit.formatted_text import to_formatted_text
                    out.extend(to_formatted_text(ANSI(label)))
                    out.append(("", "\n"))
                elif label:                            # …or a static text block
                    # default header style (bold); item_styles[i] overrides
                    # (e.g. 'dim' for a greyed hint line)
                    st = (f"class:{item_styles[i]}"
                          if (item_styles and i < len(item_styles) and item_styles[i])
                          else "class:head")
                    out.append((st, label + "\n"))
                else:
                    out.append(("class:item", "\n"))
                continue
            if i in t_by_index:                        # horizontal-toggle row
                slot, t = t_by_index[i]
                out += _toggle_fragments(slot, t, i == sel[0])
                continue
            ptr = "❯" if i == sel[0] else " "
            if i == sel[0]:                            # hovered → whole row accent
                txt = label if isinstance(label, str) else "".join(t for _, t in label)
                out.append(("class:sel", f" {ptr} {ANSI_RE.sub('', txt)}\n"))
                continue
            base = (f"class:{item_styles[i]}"
                    if (item_styles and i < len(item_styles) and item_styles[i])
                    else "class:item")
            if isinstance(label, str):                 # plain row
                out.append((base, f" {ptr} {ANSI_RE.sub('', label)}\n"))
            else:                                      # rich row: per-cell styles
                out.append((base, f" {ptr} "))         # ('' fragment style → row base)
                out += [(st or base, txt) for st, txt in label]
                out.append((base, "\n"))
        return FormattedText(out)

    def _footer():
        if mode[0] == "help":
            return FormattedText([("class:footer", " esc back ")])
        if mode[0] == "filter":
            n = len(_selectable())
            return FormattedText([
                ("class:sel", f" / {query[0]}▌"),
                ("class:footer",
                 f"  {n} match{'es' if n != 1 else ''} · ↑↓ move · "
                 f"enter select · esc clear "),
            ])
        hint = footer_hint or "↑↓ move · enter select · esc quit"
        if len(_selectable()) >= 8:
            hint += " · / find"
        if help_lines:
            hint += " · ? help"
        return FormattedText([("class:footer", f" {hint} ")])

    kb = KeyBindings()
    from prompt_toolkit.filters import Condition
    in_filter = Condition(lambda: mode[0] == "filter")
    not_filter = ~in_filter

    @kb.add("up")
    @kb.add("k", filter=not_filter)
    def _up(event):
        if mode[0] in ("menu", "filter"):
            sel[0] = _step(sel[0], -1)

    @kb.add("down")
    @kb.add("j", filter=not_filter)
    def _down(event):
        if mode[0] in ("menu", "filter"):
            sel[0] = _step(sel[0], 1)

    @kb.add("enter")
    def _enter(event):
        if mode[0] == "help":
            mode[0] = "menu"
            return
        if not _selectable():
            return                          # filter matched nothing
        select_screen.last_index = sel[0]
        _publish_toggles()
        event.app.exit(result=items[sel[0]][1])

    @kb.add("?", filter=not_filter)
    def _help(event):
        if help_lines:
            mode[0] = "menu" if mode[0] == "help" else "help"

    # ── / type-to-filter (skills-find style: type to narrow, enter to
    # select, esc to clear; SEP headers drop out of filtered results) ──
    @kb.add("/", filter=not_filter)
    def _filter_on(event):
        if mode[0] == "menu":
            mode[0] = "filter"
            query[0] = ""
            _recompute_filter()

    @kb.add("<any>", filter=in_filter)
    def _filter_type(event):
        ch = event.data
        if ch and ch.isprintable():
            query[0] += ch
            _recompute_filter()

    @kb.add("backspace", filter=in_filter)
    def _filter_back(event):
        if query[0]:
            query[0] = query[0][:-1]
            _recompute_filter()
        else:
            mode[0] = "menu"
            _recompute_filter()

    def _toggle_moved(event, slot, t):
        if t.get("exit_on_change"):
            select_screen.last_index = sel[0]
            _publish_toggles()
            event.app.exit(result=TOGGLED)

    @kb.add("left", filter=not_filter)   # ← steps the toggle left; at the
    def _left(event):        #   leftmost (or off the toggle row) it goes
        if mode[0] != "menu":            #   BACK — no wrap-around.
            mode[0] = "menu"
            return
        if sel[0] in t_by_index and tsel[t_by_index[sel[0]][0]] > 0:
            slot, t = t_by_index[sel[0]]
            tsel[slot] -= 1
            _toggle_moved(event, slot, t)
        elif esc_result is not QUIT:
            # ← is BACK-navigation only. At the top level (esc_result QUIT)
            # there is nowhere to go back to — ← never exits the app; that's
            # esc / q / ^C.
            select_screen.last_index = sel[0]
            _publish_toggles()
            event.app.exit(result=esc_result)

    @kb.add("right", filter=not_filter)  # → steps the toggle right (no wrap)
    def _right(event):
        if mode[0] == "menu" and sel[0] in t_by_index:
            slot, t = t_by_index[sel[0]]
            before = tsel[slot]
            tsel[slot] = min(tsel[slot] + 1, len(t["options"]) - 1)
            if tsel[slot] != before:
                _toggle_moved(event, slot, t)

    @kb.add("escape")
    @kb.add("q", filter=not_filter)
    @kb.add("c-c")
    def _esc(event):
        if mode[0] == "filter":
            query[0] = ""                  # esc CLEARS the filter first
            mode[0] = "menu"
            _recompute_filter()
        elif mode[0] == "help":
            mode[0] = "menu"
        else:
            select_screen.last_index = sel[0]
            _publish_toggles()
            event.app.exit(result=esc_result)

    for key, payload in (extra_keys or {}).items():
        def _bind(p):
            @kb.add(key, filter=not_filter)
            def _k(event):
                if mode[0] == "menu":
                    select_screen.last_index = sel[0]
                    _publish_toggles()
                    event.app.exit(result=p)
        _bind(payload)

    style = PtkStyle.from_dict({
        "sel":    f"fg:{ACCENT_HEX} bold",     # hovered row
        "item":   "",                          # default
        "head":   "bold",                      # emphasised row (e.g. PORTFOLIO)
        "dim":    "fg:#6c6c6c",                # greyed row (e.g. an un-hovered account)
        "warn":   f"fg:{WARN_HEX}",            # warning orange (sync problems)
        "footer": "fg:#858585",
    })

    def _cursor_pos():
        """Cursor row for the body control — each item renders exactly one
        line, so the Window scrolls the hovered row into view when the list
        is taller than the screen (cursor-follow)."""
        from prompt_toolkit.data_structures import Point
        if mode[0] == "help":
            return Point(x=0, y=0)
        y = visible[0].index(sel[0]) if sel[0] in visible[0] else 0
        return Point(x=0, y=y)

    layout = Layout(HSplit([
        Window(FormattedTextControl(_header), dont_extend_height=True),
        Window(FormattedTextControl(_body, get_cursor_position=_cursor_pos,
                                    show_cursor=False), wrap_lines=False),
        Window(FormattedTextControl(_footer), height=1, dont_extend_height=True),
    ]))
    app = Application(layout=layout, key_bindings=kb, style=style,
                      full_screen=True, mouse_support=False,
                      color_depth=_app_color_depth(), output=_app_output())
    if app_holder is not None:                     # let a bg thread exit this app
        app_holder[0] = app                        # (stale-while-revalidate refresh)
    return app.run()


select_screen.last_index = 0
select_screen.toggle_selected = 0


def text_input_screen(prompt, *, header="", footer_hint=None, default=""):
    """Full-screen single-line text entry on the alternate screen — the
    consistent in-frame replacement for a bare `input()`. `header` is a
    pre-rendered ANSI string (banner + breadcrumb + any instructions). Returns
    the entered text on Enter (may be ""), or BACK on Esc. Left/Right move the
    cursor here (so Esc — not ←  — cancels). Non-TTY → plain input()."""
    if not (HAS_Q and _streams_interactive()):
        if header:
            print(header)
        try:
            return input(f"  {prompt} ")
        except (EOFError, KeyboardInterrupt):
            return BACK

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI, FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style as PtkStyle
    from prompt_toolkit.widgets import TextArea

    field = TextArea(text=default, multiline=False, prompt=f"  {prompt} ",
                     style="class:input")
    result = [BACK]
    kb = KeyBindings()

    @kb.add("enter", eager=True)
    def _ok(event):
        result[0] = field.text
        event.app.exit()

    @kb.add("escape")
    @kb.add("c-c")
    def _esc(event):
        result[0] = BACK
        event.app.exit()

    def _footer():
        return FormattedText([("class:footer",
                               f" {footer_hint or 'enter confirm · esc cancel'} ")])

    layout = Layout(HSplit([
        Window(FormattedTextControl(lambda: ANSI(header)), dont_extend_height=True),
        Window(height=1),                                  # spacer
        field,
        Window(FormattedTextControl(_footer), height=1, dont_extend_height=True),
    ]), focused_element=field)
    style = PtkStyle.from_dict({"input": f"fg:{ACCENT_HEX} bold",
                                "footer": "fg:#858585"})
    app = Application(layout=layout, key_bindings=kb, style=style,
                      full_screen=True, mouse_support=False,
                      color_depth=_app_color_depth(), output=_app_output())
    app.run()
    return result[0]


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def loading_screen(names, work, *, header="", title="loading…"):
    """Run `work(on_update)` in a background thread while showing live per-item
    progress (spinner + state) on the alternate screen, then return work's
    result. `names` seeds the rows in order; `work` calls `on_update(name, state)`
    as items progress and returns a value. States containing 'ok'/'cached' show a
    green ✓, 'skip'/'fail' a red ✗, anything else an animated spinner.

    Non-TTY → just runs `work` with a `status()` callback (no frame). The worker
    is started via `pre_run` so the app's event loop exists before it can finish
    (so the cross-thread exit can't race)."""
    if not (HAS_Q and _streams_interactive()):
        return work(lambda n, s: status(f"{n}: {s}"))

    import threading
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import HSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    order = list(names)
    states = {n: "queued" for n in order}
    lock = threading.Lock()
    result, err, tick = {}, {}, [0]

    def on_update(name, state):
        with lock:
            if name not in states:
                order.append(name)
            states[name] = state
        try:
            app.invalidate()
        except Exception:                                   # noqa: BLE001
            pass

    def _glyph(state):
        s = state.lower()
        if s.startswith("ok") or "cached" in s:
            return f"{GREEN}✓{RST}"
        if "skip" in s or "fail" in s:
            return f"{RED}✗{RST}"
        return f"{BRAND}{_SPINNER[tick[0] % len(_SPINNER)]}{RST}"

    def _body():
        tick[0] += 1
        rows = [f"  {DIM}↻ {title}{RST}", ""]
        with lock:
            for n in order:
                st = states[n]
                pretty = "ready" if st == "ok" else st
                rows.append(f"   {_glyph(st)}  {n:<22} {DIM}{pretty}{RST}")
        return ANSI("\n".join(rows))

    def _runner():
        try:
            # Suppress broker chatter (connector libs printing login/HTTP noise)
            # so it can't corrupt the full-screen render. Safe to swap sys.stdout
            # here: the app renders to _REAL_STDOUT, not sys.stdout.
            with quiet():
                result["v"] = work(on_update)
        except Exception as e:                              # noqa: BLE001
            err["e"] = e
        finally:
            try:
                app.loop.call_soon_threadsafe(app.exit)
            except Exception:                               # noqa: BLE001
                pass

    kb = KeyBindings()

    @kb.add("c-c")                                          # abandon the wait (rare)
    def _cancel(event):
        event.app.exit()

    def _footer():
        from prompt_toolkit.formatted_text import FormattedText
        return FormattedText([("class:footer", " ^C cancel ")])

    from prompt_toolkit.styles import Style as PtkStyle
    layout = Layout(HSplit([
        Window(FormattedTextControl(lambda: ANSI(header)), dont_extend_height=True),
        Window(height=1, dont_extend_height=True),
        Window(FormattedTextControl(_body)),
        Window(FormattedTextControl(_footer), height=1, dont_extend_height=True),
    ]))
    app = Application(layout=layout, key_bindings=kb, full_screen=True,
                      mouse_support=False, refresh_interval=0.12,
                      style=PtkStyle.from_dict({"footer": "fg:#858585"}),
                      color_depth=_app_color_depth(), output=_app_output())
    app.run(pre_run=lambda: threading.Thread(target=_runner, daemon=True).start())
    if "e" in err:
        raise err["e"]
    return result.get("v")
