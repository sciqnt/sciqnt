"""sq-fmt — pure formatting substrate for sciqnt (ZERO dependencies).

The number/percentage formatters, ANSI colour tokens, key:value + table
renderers, and the braille terminal charts — everything that turns canonical
data into text, with NOTHING heavier than the stdlib (`os`, `re`).

This is the thin leaf that connectors and `sq_secrets` depend on so they render
money the same way EVERYWHERE without dragging in prompt-toolkit. The interactive
layer (`sq_tui`) builds ON this — full-screen apps, questionary prompts, the
tabbed viewer — and re-exports these names for backward compatibility. The
dependency arrow only ever points one way: `sq_tui → sq_fmt`, never back.

Modules MUST NOT import `questionary`/`prompt_toolkit` for formatting — those
belong only to `sq_tui`. A formatting change (colour, number format, table
style) is a one-file edit here that propagates everywhere.
"""
import os
import re

# Honour NO_COLOR (https://no-color.org): any value present → suppress colour.
NO_COLOR = bool(os.environ.get("NO_COLOR"))


def _c(seq: str) -> str:
    """Colour sequence, or '' under NO_COLOR — so every token degrades to plain."""
    return "" if NO_COLOR else seq


# ANSI tokens — for non-questionary `print()` output (banners, headings, hints)
BOLD = _c("\033[1m")
DIM = _c("\033[2m")
CYAN = _c("\033[36m")
GREEN = _c("\033[32m")
RED = _c("\033[31m")
YELLOW = _c("\033[33m")          # warnings: user-fixable, not failures
RST = _c("\033[0m")

# Accent — the ONE highlight colour for the logo, table headers, menu pointer
# and active tab. Fixed project colour #A8DCD1 (pale teal); to rebrand, change
# this one constant. ADAPTIVE: 24-bit truecolor when the terminal advertises it
# (iTerm2/Kitty/modern), else the nearest 256-colour — which Apple Terminal.app
# supports (it silently DROPS truecolor, rendering 24-bit as plain grey).
ACCENT_HEX = "#A8DCD1"                 # '#RRGGBB' form — for prompt_toolkit styles
# Warning orange — the component-level alert colour (sync problems, the
# troubleshoot block). One constant feeds BOTH the ptk style dicts and the
# print-path ORANGE token below.
WARN_HEX = "#ff8700"


def _hex_to_ansi(hexstr: str) -> str:
    """Hex '#RRGGBB' → SGR escape. Truecolor when supported, else nearest
    xterm-256 cube colour."""
    h = hexstr.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return f"\033[38;2;{r};{g};{b}m"
    lvl = (0, 95, 135, 175, 215, 255)
    idx = lambda v: min(range(6), key=lambda i: abs(lvl[i] - v))   # noqa: E731
    return f"\033[38;5;{16 + 36 * idx(r) + 6 * idx(g) + idx(b)}m"


ACCENT = _c(_hex_to_ansi(ACCENT_HEX))  # SGR escape — for print()-based highlights
BRAND = ACCENT                         # the logo uses the same accent
ORANGE = _c(_hex_to_ansi(WARN_HEX))    # warning orange — print-path token

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def ok(text):
    """Green success line with a check — '✓ verified', '✓ connected as …'.
    One source of truth for affirmative status across the TUI."""
    print(f"  {GREEN}✓{RST} {text}")


def err(text):
    """Red failure line with a cross — '✗ verification failed: …'."""
    print(f"  {RED}✗{RST} {text}")


def warn_line(text):
    """A user-fixable warning as a string (no print): yellow ⚠ + plain text.
    The codified severity convention (see `_account_problem` in sq_platform):
    YELLOW ⚠ = the user can fix it (stale export, missing history, missing
    credentials); DIM is reserved for transient/informational lines. Callers
    pass the bare message — no inline '⚠ ' prefix."""
    return f"{YELLOW}⚠{RST} {text}"


def status(text):
    """Dim informational progress line ('connecting…', 'fetching positions…') —
    secondary operational output during a fetch. This pure version just prints;
    the interactive layer (`sq_tui`) defines its own SINK-AWARE `status` for
    live-progress panels. Both behave the same to the user: sq_tui's
    `stream_output`/`quiet` redirect stdout, so a plain print here is still
    captured into the live panel (or silenced) — which is exactly why a
    connector can call `status` without dragging in prompt-toolkit."""
    print(f"  {DIM}{text}{RST}")


def heading(text):
    """Section heading — bold, with leading blank line for breathing room.
    Use for the title above a table or a logical block of output."""
    print(f"\n  {BOLD}{text}{RST}")


# ── terminal charts (braille canvas — btop-style) ────────────────────────
# Chart math is display-only float; money stays Decimal everywhere else.
# A braille cell packs 2×4 dots, so a width×height CELL grid gives a
# (width·2)×(height·4) DOT grid — thin smooth lines instead of block fills.

_BRAILLE_BITS = {(0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
                 (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80}


class _BrailleCanvas:
    """Minimal dot canvas. (0,0) is the TOP-LEFT dot; x grows right,
    y grows down. One foreground colour per CELL (last writer wins —
    callers keep same-coloured dots cell-aligned)."""

    def __init__(self, cells_w: int, cells_h: int):
        self.w, self.h = cells_w, cells_h
        self.dots = [[0] * cells_w for _ in range(cells_h)]
        self.color = [[""] * cells_w for _ in range(cells_h)]

    @property
    def dots_w(self):
        return self.w * 2

    @property
    def dots_h(self):
        return self.h * 4

    def set(self, x: int, y: int, color: str = ""):
        if not (0 <= x < self.dots_w and 0 <= y < self.dots_h):
            return
        cy, cx = y // 4, x // 2
        self.dots[cy][cx] |= _BRAILLE_BITS[(x % 2, y % 4)]
        if color:
            self.color[cy][cx] = color

    def vline(self, x: int, y0: int, y1: int, color: str = ""):
        for y in range(min(y0, y1), max(y0, y1) + 1):
            self.set(x, y, color)

    def rows(self) -> list:
        out = []
        for cy in range(self.h):
            cells = []
            for cx in range(self.w):
                mask = self.dots[cy][cx]
                ch = chr(0x2800 + mask) if mask else " "
                col = self.color[cy][cx]
                cells.append(f"{col}{ch}{RST}" if (col and mask) else ch)
            out.append("".join(cells))
        return out


def _resample_line(vals: list, n: int) -> list:
    """Linear-interpolated resample of a LEVEL series to exactly n points."""
    out = []
    for i in range(n):
        pos = i * (len(vals) - 1) / (n - 1)
        lo = int(pos)
        frac = pos - lo
        v = vals[lo] if frac == 0 or lo + 1 >= len(vals) \
            else vals[lo] * (1 - frac) + vals[lo + 1] * frac
        out.append(v)
    return out


def _chart_domain(vals: list, *, zero_axis: bool = False) -> tuple:
    """(vmin, vmax) for a chart y-domain, with the FLATLINE GUARD: a
    sub-cent span pads around the level instead of normalising to noise
    (a dormant €0.01 account must draw flat, not amplify FX wobble to
    full height). The guard is ABSOLUTE (1 cent), deliberately not
    relative — a 12k portfolio moving $35 in a month is a real shape
    the user wants to see, not noise (calibration bug, 2026-06-12)."""
    vmin, vmax = min(vals), max(vals)
    if (vmax - vmin) <= 0.01:
        mid = (vmax + vmin) / 2
        pad = max(0.01, abs(mid) * 0.05)
        vmin, vmax = mid - pad, mid + pad
    if zero_axis:
        vmin, vmax = min(vmin, 0.0), max(vmax, 0.0)
    return vmin, vmax


def _fmt_chart_value(v: float) -> str:
    """Adaptive y-label: 2dp for small magnitudes (a flat €0.01 account
    must not label every gridline '0'), thousands-grouped integers
    otherwise."""
    return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"


def render_chart(values, *, height: int = 6, width: int = 60,
                 fmt=_fmt_chart_value, x_left: str = "",
                 x_right: str = "", zero_axis: bool = False,
                 sign_colors: bool = False) -> str:
    """Braille line chart of a LEVEL series (e.g. net worth) — a thin
    stroke on a (width·2)×(height·4) dot grid, with a y-axis
    (max / mid / min labels), a baseline, and optional x-axis tick
    labels (`x_left` / `x_right`, typically the date span).

    `zero_axis=True` forces 0 into the y-domain and draws a dim dotted
    line at zero (for P/L-like series). `sign_colors=True` colours the
    stroke green where the value is ≥ 0 and red below (cumulative P/L);
    default stroke is the accent.

    FLATLINE GUARD: when the series' span is negligible (≤ 0.5% of its
    magnitude, or sub-cent), the y-domain is padded around the level
    instead of normalised to it — otherwise microscopic FX noise on a
    dormant €0.01 account amplifies into full-height swings (live bug,
    2026-06-12).

    Pure text → dumps/pipes fine; NO_COLOR-safe (tokens go empty).
    Returns "" for fewer than 2 points — callers skip the chart."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return ""
    canvas = _BrailleCanvas(width, height)
    n = canvas.dots_w
    pts = _resample_line(vals, n)
    vmin, vmax = _chart_domain(pts, zero_axis=zero_axis)
    span = (vmax - vmin) or 1.0
    y_of = lambda v: round((vmax - v) / span * (canvas.dots_h - 1))  # noqa: E731
    if zero_axis:
        y0 = y_of(0.0)
        for x in range(0, canvas.dots_w, 3):        # dim dotted zero line
            canvas.set(x, y0, DIM)
    ys = [y_of(v) for v in pts]

    def _stroke(idx):
        if not sign_colors:
            return ACCENT
        return GREEN if pts[idx] >= 0 else RED
    canvas.set(0, ys[0], _stroke(0))
    for x in range(1, n):
        canvas.vline(x, ys[x - 1], ys[x], _stroke(x))  # connect the stroke

    labels = {0: fmt(vmax), height - 1: fmt(vmin)}
    if height >= 3:
        labels[(height - 1) // 2] = fmt((vmax + vmin) / 2)
    lw = max(len(t) for t in labels.values())
    lines = []
    for cy, row in enumerate(canvas.rows()):
        tick = labels.get(cy)
        gutter = (f"{DIM}{tick.rjust(lw)} ┤{RST}" if tick is not None
                  else f"{DIM}{' ' * lw} │{RST}")
        lines.append(f"  {gutter}{row}")
    lines.append(f"  {DIM}{' ' * lw} ╰{'─' * width}{RST}")
    if x_left or x_right:
        pad = width - len(x_left) - len(x_right)
        lines.append(f"  {' ' * (lw + 2)}{DIM}{x_left}"
                     f"{' ' * max(pad, 1)}{x_right}{RST}")
    return "\n".join(lines)


def render_history(payload, *, height: int = 6, width: int = 60) -> str:
    """Render a `sciqnt.history/v1` payload (the `--json` data surface) as
    the TUI's chart block — net-worth braille line + per-period P/L bars,
    minimal dim header. THE adapter proving rule 1 of the composable
    doctrine: this renderer is ONE consumer of the data surface; a web
    chart consuming the identical payload is a peer, not a port.

    Accepts rich values (Decimal/datetime, fresh from history_json) or
    wire form (strings, round-tripped through JSON). "" when the series
    is too short to chart."""
    from datetime import datetime as _dt
    from decimal import Decimal as _D

    def _money(v):
        return v if isinstance(v, _D) else _D(str(v))

    def _when(v):
        if isinstance(v, str):
            return _dt.fromisoformat(v)
        return v

    rows = payload.get("rows") or []
    if len(rows) < 2:
        return ""
    rng = payload.get("range")
    ccy = payload.get("display_currency", "")
    nw = [_money(r["net_worth"]) for r in rows]
    pl = [_money(r["pl_period"]) for r in rows]
    first, last = _when(rows[0]["date"]), _when(rows[-1]["date"])
    intraday = rng == "1D"
    x_fmt = "%H:%M" if intraday else "%Y-%m-%d"
    freq = {"1D": "5-minute bars", "5Y": "weekly",
            "All": "monthly"}.get(rng, "daily")
    chart = render_chart(nw, height=height, width=width,
                         x_left=first.strftime(x_fmt),
                         x_right=last.strftime(x_fmt))
    if not chart:
        return ""
    parts = [f"  {DIM}net worth ({ccy}) │ {freq}{RST}", "", chart]
    bars = render_pl_bars(pl, width=width)
    if bars:
        parts += ["", f"  {DIM}P/L per period{RST}", bars]
    return "\n".join(parts)


def render_pl_bars(values, *, height: int = 4, width: int = 60,
                   fmt=_fmt_chart_value) -> str:
    """Braille diverging column chart for a FLOW series (per-period P/L):
    thin green columns rise from a zero axis, red ones hang below it —
    magnitude scaled to the biggest |value|. Resamples by bucket SUM
    (flows aggregate across merged periods; +1/−1 in one bucket nets to
    nothing). Labels: +peak / 0 / −trough. "" for < 2 points."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return ""
    if len(vals) > width:                       # one CELL column per period
        step = len(vals) / width
        vals = [sum(vals[int(i * step):max(int((i + 1) * step),
                                           int(i * step) + 1)])
                for i in range(width)]
    peak = max(abs(v) for v in vals) or 1.0
    canvas = _BrailleCanvas(width, height)
    axis = canvas.dots_h // 2                   # zero line (dot row)
    half = axis - 1                             # dots available each side
    cell_w = max(1, canvas.dots_w // max(len(vals), 1))
    for i, v in enumerate(vals):
        x0 = i * cell_w
        mag = 0 if v == 0 else max(1, round(abs(v) / peak * half))
        color = GREEN if v > 0 else RED if v < 0 else DIM
        for dx in range(min(cell_w, 2)):        # ≤1 cell wide → one colour
            x = x0 + dx
            if v > 0:
                canvas.vline(x, axis - mag, axis - 1, color)
            elif v < 0:
                canvas.vline(x, axis + 1, axis + mag, color)
            else:
                canvas.set(x, axis, DIM)
    pos_peak = max((v for v in vals if v > 0), default=0)
    neg_peak = min((v for v in vals if v < 0), default=0)
    labels = {0: f"+{fmt(pos_peak)}" if pos_peak else "",
              axis // 4: "0",                  # the cell row holding the axis
              height - 1: f"−{fmt(abs(neg_peak))}" if neg_peak else ""}
    lw = max(len(t) for t in labels.values())
    lines = []
    for cy, row in enumerate(canvas.rows()):
        tick = labels.get(cy, "")
        gutter = (f"{DIM}{tick.rjust(lw)} ┤{RST}" if tick
                  else f"{DIM}{' ' * lw} │{RST}")
        lines.append(f"  {gutter}{row}")
    return "\n".join(lines)


def pnl(value, text=None):
    """Colour a P&L / return figure: green if positive, red if negative,
    plain at zero. `value` decides the sign; `text` is the display string
    (defaults to a signed 2dp format). ONE source of truth for P&L colour
    across the TUI — every money/return figure routes through here."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return text if text is not None else str(value)
    s = text if text is not None else f"{'+' if n > 0 else ''}{n:,.2f}"
    if n > 0:
        return f"{GREEN}{s}{RST}"
    if n < 0:
        return f"{RED}{s}{RST}"
    return s


# ── number formatting (ONE home — every module renders money the same way) ──
def fmt_num(v):
    """'—' for None/'', else thousands-separated 2dp ('1,234.50');
    non-numeric values fall back to str()."""
    if v in (None, ""):
        return "—"
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def fmt_signed(v):
    """Like fmt_num but with a leading '+' for positive values."""
    if v in (None, ""):
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    sign = "+" if n > 0 else ""
    return f"{sign}{n:,.2f}"


def fmt_pct(v):
    """Signed percentage, 2dp. A magnitude ≤ 1 is treated as a fraction and
    scaled ×100 (0.0734 → '+7.34%'); larger values are taken as percent."""
    if v in (None, ""):
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(n) <= 1:
        n *= 100
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.2f}%"


def _vlen(s):
    """Visible length — string length ignoring ANSI colour codes, so a
    coloured/dimmed cell still aligns to its column."""
    return len(ANSI_RE.sub("", s))


def _vpad(s, w, right):
    """Pad `s` to visible width `w` (ANSI-aware). Right- or left-justify."""
    gap = w - _vlen(s)
    if gap <= 0:
        return s
    return (" " * gap + s) if right else (s + " " * gap)


def format_table(headers, rows, align=None, title=None, row_styles=None):
    """Build the table string (no print). Brand styling: cyan-bold header, dim
    rule under it, default-text body. Column widths auto-fit (ANSI-aware, so
    coloured cells stay aligned). Numeric columns default to right-aligned.

    headers    : list[str]            column titles
    rows       : list[list[Any]]      cell values (str() applied); cells may
                                      carry ANSI colour (e.g. via pnl()).
    align      : list[str] | None     'l' or 'r' per column.
    title      : str | None           optional heading above the table
    row_styles : list[str|None]|None  per-row ANSI style (e.g. DIM to grey out
                                      a closed position). Parallel to rows."""
    n = len(headers)
    cells = [[str(c) if c is not None else "" for c in row] for row in rows]
    if align is None:
        align = ["l"] + ["r"] * (n - 1)
    widths = []
    for i in range(n):
        col = [headers[i]] + [r[i] if i < len(r) else "" for r in cells]
        widths.append(max(_vlen(c) for c in col))

    def _fmt_row(values, *, style=None):
        parts = []
        for i, v in enumerate(values):
            s = _vpad(v, widths[i], align[i] == "r")
            if style:
                s = f"{style}{s}{RST}"
            parts.append(s)
        return "  " + "  ".join(parts)

    lines = []
    if title:
        lines.append(f"  {BOLD}{title}{RST}")
        lines.append("")
    lines.append(_fmt_row(headers, style=f"{BOLD}{ACCENT}"))
    lines.append(_fmt_row(["─" * w for w in widths], style=DIM))
    for idx, r in enumerate(cells):
        style = row_styles[idx] if (row_styles and idx < len(row_styles)) else None
        lines.append(_fmt_row(r, style=style))
    return "\n".join(lines)


def print_table(headers, rows, align=None, title=None):
    """Build + print a table. Thin wrapper around format_table for callers
    that just want output. Returns the string too, so it's still composable."""
    out = format_table(headers, rows, align=align, title=title)
    if title:
        print()      # breathing room (the no-print path lets the caller decide)
    print(out)
    return out


def format_kv(items, title=None):
    """Build a key:value block string (no print). Labels left, values
    right-aligned to a common column, both columns visually distinct
    (labels dim, values bold). Ideal for "top metrics" / summaries.
    items: dict or list[(label, value)]."""
    if isinstance(items, dict):
        items = list(items.items())
    if not items:
        return ""
    label_w = max(_vlen(str(k)) for k, _ in items)
    value_w = max(_vlen(str(v)) for _, v in items)
    lines = []
    if title:
        lines.append(f"  {BOLD}{title}{RST}")
        lines.append("")
    for k, v in items:
        lines.append(f"  {DIM}{_vpad(str(k), label_w, False)}{RST}   "
                     f"{BOLD}{_vpad(str(v), value_w, True)}{RST}")
    return "\n".join(lines)


def print_kv(items, title=None):
    """Build + print a kv block. Returns the rendered string."""
    out = format_kv(items, title=title)
    if title:
        print()
    print(out)
    return out
