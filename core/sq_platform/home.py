"""sciqnt home — the interactive landing.

`sciqnt` (no args, in a TTY) lands HERE: a banner, your aggregated portfolio
summary, and an actions menu — connect an account, view full detail, settings,
browse modules. Not a dump-and-exit; a home you navigate.

Design points:
- Modularity: an unconnected broker is NOT an error. Connectors you haven't
  attached an account to show up in the connect menu — never as a
  CredentialsMissing failure.
- Reuses the aggregate built by `sq_platform.aggregated` (one source of truth
  for the numbers); the home just frames it and adds navigation.
- Gestures: Esc (or the Quit item) exits; ^R refreshes (bypasses the cache).
  Refresh is a keybinding, not a menu row. Non-TTY callers use `run_aggregated`
  (dump) instead — see the launcher.
"""
import random
import subprocess
import sys
import threading
from pathlib import Path

import importlib
import time

import sq_agents
import sq_config
import sq_secrets
import sq_skills
import sq_tui
from sq_tui import GREEN, tabbed_view

from . import (BOLD, BRAND, DIM, RST, banner_text, commands_of, discover_bundles,
               run_interactive)
from . import aggregated as ag
from . import insights


_CCY_SYM = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥",
            "CHF": "CHF", "CAD": "C$", "AUD": "A$"}

# Greyed, rotating examples shown under the agent row — a hint at what the
# SciQnt Agent can do. One is picked at random each redraw; a screen with a
# `_CONTEXT_DEFAULT` shows that fixed example instead (still in the pool so it
# can surface randomly elsewhere).
_AGENT_EXAMPLES = [
    "explain what I'm holding",
    "why did my portfolio move today?",
    "which positions are dragging my P&L?",
    "is my allocation too concentrated?",
    "summarise my performance, TWR vs XIRR",
    "help me connect a broker account",
    "build a connector for an unsupported broker",
    "fix a broker that stopped syncing",
    "compare my accounts by asset class",
    "what changed since I last checked?",
    "explain what these modules do",
]
# Per-screen default hint (a relevant example pinned for that component).
_CONTEXT_DEFAULT = {
    "connect": "help me connect a broker account",
    "accounts": "help me manage or reconnect a broker account",
    "settings": "explain a setting or recommend one",
    "modules": "explain what these modules do",
}
_PF_COLS = ["Net Worth", "Holdings", "Net Cash", "P/L"]
# Cap the failing-account lines under the agent's "⚠ Recommended" header so a
# long outage list never pushes the portfolio table off the fixed-height frame.
_MAX_WARN_LINES = 3

# The home's action menu as a DECLARATION (composable doctrine rule 2) —
# the selection keys route in run_home's dispatch. A future shell (web,
# alternative TUI) renders this same list; code never hard-wires the rows.
HOME_MENU = [
    ("Portfolio Accounts", "accounts"),
    ("Settings", "config"),
    ("Modules", "modules"),
    ("Quit", "quit"),
]


def _money(ccy, v, signed=False):
    """A currency-prefixed cell, e.g. '€ 10,521.42' / '€ +134.88'. '—' if None."""
    if v is None:
        return "—"
    n = float(v)
    s = f"{'+' if signed and n > 0 else ''}{n:,.2f}"
    return f"{_CCY_SYM.get(ccy, ccy)} {s}"


def _cell_style(base, v, signed):
    """prompt_toolkit style for a value cell: a signed P/L value is green/red
    (bold on the PORTFOLIO row); anything else returns '' → inherit the row's
    base style (bold for PORTFOLIO, grey for an account)."""
    if not signed or v is None:
        return ""
    n = float(v)
    bold = " bold" if base == "head" else ""
    if n > 0:
        return f"ansigreen{bold}"
    if n < 0:
        return f"ansired{bold}"
    return ""


def _portfolio_table(agg, ccy):
    """Build the selectable portfolio table: a bold PORTFOLIO total row plus one
    greyed row per connected account, columns Mkt.Value / P/L / Realized /
    UnRealized. P/L cells are coloured green/red by sign. Returns (header_block,
    items, item_styles) where items carry RICH labels (lists of (style, text)
    fragments) so each cell can be styled independently; item_styles is the
    per-row base ('head'/'dim'). Columns align with the rows' 3-char cursor slot.
    PORTFOLIO is display ccy; accounts are in their base ccy."""
    # Columns: Net Worth, Holdings, Net Cash, PnL. (value, signed) per cell —
    # `signed` marks a P/L value to colour green/red.
    # (name, ccy, [(value, signed)], payload, base_style)
    raw = [("Portfolio", ccy,
            [(agg.total_value, False), (agg.positions_value, False),
             (agg.cash_value, False), (agg.total_pl_lifetime, True)],
            "portfolio", "head")]
    for pb in (agg.per_broker or []):
        bc = pb["base_currency"]
        holdings, cash = pb["positions_value_base"], pb["cash_base"]
        raw.append((pb["broker"], bc,
                    [(holdings + cash, False), (holdings, False),
                     (cash, False), (pb["total_pl_lifetime"], True)],
                    ("acct", pb["broker"]), "dim"))

    texts = [[_money(r[1], v, s) for (v, s) in r[2]] for r in raw]
    name_w = max(len(r[0]) for r in raw)
    colw = [max(len(_PF_COLS[j]), *(len(texts[ri][j]) for ri in range(len(raw))))
            for j in range(4)]
    gap = "  "

    items, styles = [], []
    for ri, (name, _c, vals, payload, base) in enumerate(raw):
        frags = [("", name.ljust(name_w))]
        for j in range(4):
            v, signed = vals[j]
            frags.append(("", gap))
            frags.append((_cell_style(base, v, signed), texts[ri][j].rjust(colw[j])))
        items.append((frags, payload))
        styles.append(base)

    pad = "   " + " " * name_w + gap                 # 3-char cursor slot + name col
    # Plain text — the renderer styles this row as a (bold) header; no DIM here.
    header_block = (f"{pad}{gap.join(_PF_COLS[j].rjust(colw[j]) for j in range(4))}\n"
                    f"{pad}{gap.join('─' * colw[j] for j in range(4))}")
    return header_block, items, styles


_HELP = (
    f"  {BOLD}Keys{RST}\n\n"
    "  ↑ ↓  ·  j k     move selection\n"
    "  ←  →            switch agent framework (on the agent row)\n"
    "  enter           open\n"
    "  ^R              refresh (bypass the cache)\n"
    "  ?               toggle this help\n"
    "  esc  ·  q       quit\n"
)

# The same keymap for the drill-down (chrome) screens — Esc is BACK there,
# and ^R doesn't apply (the home owns the refresh).
_HELP_SUB = (
    f"  {BOLD}Keys{RST}\n\n"
    "  ↑ ↓  ·  j k     move selection\n"
    "  ←  →            switch agent framework (on the agent row)\n"
    "  enter           select\n"
    "  ?               toggle this help\n"
    "  esc  ·  q       back\n"
)


def _wrappers(root) -> dict:
    """name → bin wrapper path, for the connectors that ship one."""
    return {n: w for n, w, _ in discover_bundles(root)}


def _run_wrapper(wrapper, *args):
    """Run a bundle wrapper command as a subprocess (interactive — e.g. a
    setup prompt). Swallows ^C so it returns to the home rather than exiting."""
    try:
        subprocess.run([wrapper, *args])
    except KeyboardInterrupt:
        pass
    try:
        input(f"\n{DIM}[enter to return home]{RST} ")
    except (EOFError, KeyboardInterrupt):
        pass


def _agent_connect(root):
    """The single agent entry for Connect: hand off with a one-line intent and
    let the (strong, setup-aware) sq-connectors skill drive — it knows to check
    what's already set up and to set up an existing connector OR build a new one
    as the conversation warrants. No step-by-step directions here by design."""
    def task(_how):
        return ("Help me connect a broker or account to sciqnt. (You were "
                "summoned from the app's Connect screen — `sciqnt --list` "
                "shows what's installed.)")
    _agent_connectors(root, "Connect a broker", task)


def _connect_flow(root, available):
    """Pick a connector (full-screen), then run the bundle's `setup` — the
    broker's own interactive credential form (a subprocess — bundles own
    their credential entry), the one step that leaves the full-screen frame.
    No upfront label question: the account name derives from the username
    and is visible in the form's review step (research/connect-experience.md;
    a second same-broker account uses `sciqnt <broker> setup --account work`).

    The SciQnt Agent component sits at the top (context: 'connect'), so the agent
    is one keystroke away to set up OR build any broker — no separate menu item."""
    wrappers = _wrappers(root)
    conn = [(name, name) for name in available if name in wrappers]
    sel = _chrome_select(root, "connect", ("Connect to Broker Account",), conn)
    if sel == sq_tui.BACK:
        return
    # The setup is the bundle's own interactive credential prompt — a subprocess
    # on the NORMAL screen. Clear it and print the static chrome first so the
    # prompt appears inside the standard layout, not over shell scrollback.
    sq_tui.clear_screen()
    print(_static_chrome(root, "connect", "Connect to Broker Account", sel))
    print()
    _run_wrapper(wrappers[sel], "setup")


# ── Portfolio Accounts: manage connected accounts ──────────────────────────
def _broker_module(broker):
    """Import a broker's Python package (`sq_<broker>`) — the same naming
    convention `aggregated._discover_brokers` uses. None if it won't import
    (so callers degrade rather than crash)."""
    try:
        return importlib.import_module("sq_" + broker.replace("-", "_"))
    except Exception:                                       # noqa: BLE001
        return None


def _loading_fetch_one(root, label):
    """Fetch ONE account fresh, with the standard visible progress screen.
    Scopes the fetch to `label` (`_collect_snapshots(only=…)`) so no other
    broker is poked — a per-login-approval account never fires a phone push
    from a refresh of a different one. Returns the snapshots (or [])."""
    return sq_tui.loading_screen(
        [label],
        lambda cb: ag._collect_snapshots(
            root, use_snapshot_cache=False, only=label, on_update=cb),
        header=banner_text(root), title="refreshing…") or []


def _account_detail_view(root, label, brokers):
    """Open ONE account's portfolio/analytics view (its own base currency).
    Reuses the home's `_portfolio_view`; ^R inside re-fetches just this
    account. If the account isn't in `brokers` yet (or is degraded), fetch
    it fresh first; if it still won't load, return quietly (the problem
    surfaces on the home/accounts list)."""
    one = [b for b in brokers if b.ok and b.broker == label]
    if not one:
        fresh = _loading_fetch_one(root, label)
        one = [b for b in fresh if b.ok and b.broker == label]
        if not one:
            return
    base = one[0].snapshot.account.base_currency

    def _rebuild(label=label, base=base):
        fresh = _loading_fetch_one(root, label)
        sub = [b for b in fresh if b.ok and b.broker == label]
        if not sub:
            return None
        with sq_tui.quiet():
            t, _ti, _a = ag.build_aggregate(
                root, sub, display_currency=base, daily=True)
        return t, []

    with sq_tui.quiet():
        tabs, _title, _ = ag.build_aggregate(
            root, one, display_currency=base, daily=True)
    _portfolio_view(root, tabs, label, rebuild=_rebuild)


def _confirm_delete(root, label):
    """Destructive-action confirm: a two-item full-screen pick where Cancel
    is the pre-selected (first) row, so a stray Enter never deletes. Returns
    True only on the explicit 'remove' choice (Esc → BACK → False)."""
    sel = _chrome_select(
        root, "accounts", ("Portfolio Accounts", label, "remove"),
        [("Cancel", "cancel"), (f"Yes, remove {label}", "remove")],
        intro=[f"Remove {label}? This deletes its stored credentials and",
               "login session from this machine. Your downloaded history",
               "(data/ CSVs) is NOT touched.", ""],
        footer_hint="↑↓ move · enter select · esc cancel")
    return sel == "remove"


def _delete_account(root, broker, account, wrapper, cmds):
    """Remove a connected account. Preferred path: the bundle's own `forget`
    command (symmetric with `setup` — it scrubs keychain AND its .env AND the
    session AND the registry). Fallback for a bundle without `forget`: the
    generic `sq_secrets.forget_account` over the bundle's declared
    `SECRET_KEYS` (keychain + session + registry) — honest about the .env
    gap. Returns a one-line outcome string for the caller to show."""
    if wrapper is not None and "forget" in cmds:
        sq_tui.clear_screen()
        label = f"{broker}:{account}" if account else broker
        print(_static_chrome(root, "accounts",
                              "Portfolio Accounts", label, "remove"))
        print()
        args = ["forget"] + (["--account", account] if account else [])
        _run_wrapper(wrapper, *args)
        return None
    # Generic fallback — bundle hasn't added a `forget` command yet.
    mod = _broker_module(broker)
    service = getattr(mod, "SERVICE", f"sq-{broker}")
    keys = list(getattr(mod, "SECRET_KEYS", []))
    sq_secrets.forget_account(service, account, keys)
    label = f"{broker}:{account}" if account else broker
    if not keys:
        note = (f"\n  {DIM}(no credential manifest — you may need to clear "
                f"this broker's stored secrets manually){RST}")
    else:
        note = (f"\n  {DIM}note: an .env fallback (if used) isn't scrubbed by "
                f"the generic path — delete it manually if present{RST}")
    sq_tui.clear_screen()
    print(_static_chrome(root, "accounts", "Portfolio Accounts", label, "remove"))
    print(f"\n  {GREEN}✓{RST} removed {label}{note}")
    try:
        input(f"\n  {DIM}[enter to return]{RST} ")
    except (EOFError, KeyboardInterrupt):
        pass
    return None


def _account_actions(root, label, brokers):
    """Manage ONE connected account (full-screen drill-down): view its
    portfolio, refresh it, reconnect (re-enter credentials), or delete it.
    The available actions DERIVE from the bundle's advertised commands
    (`commands_of` — discovery over enumeration), so no per-broker logic is
    hard-wired here. When THIS account failed its last fetch, the agent
    component switches to warning mode: a recommended 'Troubleshoot with
    Agent' line on top, and the agent row launches a troubleshoot session
    scoped to just this account (the deeper `sciqnt <broker> doctor
    probe|fix-totp` diagnostics stay at the CLI, not in this menu). Returns
    'deleted' when the account was removed, else None on back."""
    broker, account = ag._broker_label_split(label)
    wrapper = _wrappers(root).get(broker)
    cmds = {c for c, _d, _a in commands_of(wrapper)} if wrapper else set()
    while True:
        # Re-derive the failure state each loop — a Refresh may have fixed it.
        failed = [b for b in (brokers or [])
                  if b.broker == label and not b.ok]
        recommend = (f"Troubleshoot with Agent ({label} couldn't fetch)"
                     if failed else None)
        items = [("View portfolio", "view"), ("Refresh", "refresh")]
        if "setup" in cmds:
            items.append(("Reconnect / re-enter credentials", "reconnect"))
        items.append(("Delete account", "delete"))
        sel = _chrome_select(
            root, "accounts", ("Portfolio Accounts", label), items,
            recommend=recommend, failed=failed or None,
            footer_hint="↑↓ move · ←→ switch agent · enter select · esc back")
        if sel == sq_tui.BACK:
            return None
        if sel == "view":
            _account_detail_view(root, label, brokers)
        elif sel == "refresh":
            fresh = _loading_fetch_one(root, label)
            if fresh:
                brokers = fresh                      # refresh the status glyphs
        elif sel == "reconnect" and wrapper is not None:
            sq_tui.clear_screen()
            print(_static_chrome(root, "accounts",
                                 "Portfolio Accounts", label, "reconnect"))
            print()
            _run_wrapper(wrapper, "setup",
                         *(["--account", account] if account else []))
        elif sel == "delete":
            if _confirm_delete(root, label):
                _delete_account(root, broker, account, wrapper, cmds)
                return "deleted"


def _accounts_flow(root, brokers, available):
    """Portfolio Accounts — the connection-management surface (distinct from
    the home's portfolio table, which is the analytics drill-in). Lists the
    user's CONNECTED accounts (each → per-account actions) and ends with a
    'Connect new Account' row that runs the existing connect flow.

    The list is RE-DERIVED from `ag._discover_brokers` each loop (discovery
    over enumeration) so a connect/delete reflects immediately. Status glyphs
    (✓ connected / ⚠ needs attention / · not loaded) are best-effort from the
    current snapshots. The demo void-filler isn't a real account, so it's
    never listed here."""
    while True:
        connected = [lbl for lbl, _ in ag._discover_brokers(root)
                     if ag._broker_label_split(lbl)[0] != "demo"]
        status = {b.broker: b.ok for b in (brokers or [])}
        items, styles = [], []
        for lbl in connected:
            ok = status.get(lbl)
            glyph = "✓" if ok else ("⚠" if ok is False else "·")
            items.append((f"{glyph}  {lbl}", ("acct", lbl)))
            styles.append(None)
        if connected:
            items.append(("", sq_tui.SEP))
            styles.append(None)
        items.append(("Connect new Account", "connect"))
        styles.append(None)
        sel = _chrome_select(
            root, "accounts", ("Portfolio Accounts",), items,
            item_styles=styles,
            intro=None if connected else ["No accounts connected yet."],
            footer_hint="↑↓ move · ←→ switch agent · enter open · esc back")
        if sel == sq_tui.BACK:
            return
        if sel == "connect":
            _connect_flow(root, available)
        elif isinstance(sel, tuple) and sel[0] == "acct":
            _account_actions(root, sel[1], brokers or [])


def _settings_flow(root):
    """Settings — the ONE full-screen settings experience, shared with
    `sciqnt config` / `sciqnt config set`: delegate to the sq-config bundle's
    loop (sq_config_ui.run_settings) IN-PROCESS, wrapped in the home chrome,
    so the screen is identical from home and CLI. The screen itself shows
    every setting with its current value (no separate 'show' submenu); the
    plain dump stays on `sciqnt config show` for scripts."""
    src = str(Path(root) / "modules" / "sq-config" / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from sq_config_ui import run_settings              # the bundle's loop
    run_settings(make_header=lambda *crumbs: _static_chrome(
        root, "settings", "Settings", *crumbs))


def _no_agent_notice():
    """Shown when a 'use agent to …' action is chosen but no coding agent is
    installed — list how to get one + how to pick it."""
    sq_tui.clear_screen()
    print(f"\n  {DIM}No coding agent installed. Install one of:{RST}")
    for lbl, cmd in sq_agents.install_hints():
        print(f"    {BOLD}{lbl}{RST}  {DIM}{cmd}{RST}")
    print(f"  {DIM}then pick it in Settings → preferred_agent (or leave 'auto')."
          f"{RST}")
    try:
        input(f"\n  {DIM}[enter to return home]{RST} ")
    except (EOFError, KeyboardInterrupt):
        pass


def _agent_handoff(label, what, prompt, *, note=None, **launch_kwargs):
    """Hand THIS terminal to the agent as a sub-session: clear the screen, show
    what's happening + how to get back (and an optional `note`, e.g. a skill we
    installed), then run the agent inline (it inherits the TTY, like the
    connector `setup` flow). When the agent exits — Ctrl-C (twice for Claude) /
    Ctrl-D / its own quit — control returns and the home redraws. Inline (not a
    new window) so the agent inherits the PATH/env where
    sciqnt already found it."""
    title = f"❯  SciQnt + {label} — {what}"
    hint = "Quit the agent (Ctrl-C twice · Ctrl-D · its own exit) to return to sciqnt"
    w = max(len(title), len(hint))
    bar = "─" * (w + 2)
    sq_tui.clear_screen()
    print(f"\n  {BRAND}╭{bar}╮{RST}")
    print(f"  {BRAND}│{RST} {BOLD}{BRAND}{title}{RST}{' ' * (w - len(title))} "
          f"{BRAND}│{RST}")
    print(f"  {BRAND}│{RST} {DIM}{hint}{RST}{' ' * (w - len(hint))} {BRAND}│{RST}")
    print(f"  {BRAND}╰{bar}╯{RST}")
    if note:
        print(f"  {DIM}{note}{RST}")
    print(flush=True)
    rc = sq_agents.launch(prompt, **launch_kwargs)
    if rc is None:                                   # agent vanished mid-flight
        _no_agent_notice()
        return
    sq_tui.clear_screen()                            # clean slate before home redraw


def _agent_connectors(root, what, task):
    """Hand the terminal to the agent for any CONNECTORS-group work, installing
    the general `sq-connectors` skill (reusable forever) and launching in the
    repo root for whole-project awareness. `task(how)` builds the prompt given
    the skill's invocation hint (or, for an agent with no skills dir, a phrase
    pointing at the repo). One skill, many entry points — only the prompt varies."""
    agent = sq_agents.resolve()
    if agent is None:
        _no_agent_notice()
        return
    label = sq_agents.label(agent)
    skill = "sq-connectors"
    where = sq_skills.install(agent, skill)
    if where is not None:
        how = sq_skills.invocation_hint(agent, skill)
        note = (f"installed {how} — reusable in any future {label} session ({where})")
    else:
        how = "the sciqnt repo (start with AGENT_GUIDE.md)"
        note = None
    _agent_handoff(label, what, task(how),
                   seed=f"{what} — context in {sq_agents.TASK_FILE}.",
                   note=note, cwd=str(root),
                   task_intro=f"sciqnt — {what.lower()}.")


def _agent_troubleshoot(root, failed):
    """Launch the agent to diagnose + fix the connector(s) that errored on the
    last refresh — the 'use agent to troubleshoot' fallback when something breaks.
    The failing brokers + their errors are injected into the prompt."""
    detail = "\n".join(f"- {b.broker}: {b.error}" for b in failed)

    def task(how):
        return (f"Use {how} to troubleshoot my failing sciqnt connector(s). On "
                f"the last refresh these errored:\n{detail}\n"
                "Reproduce each with `sciqnt <broker> live --fresh`, find the "
                "cause, fix it to green (`./run_tests.sh`), and tell me plainly "
                "what was wrong.")
    _agent_connectors(root, "Troubleshoot connectors", task)


SCREEN_FILE = "screen.txt"            # the summoned-from screen, verbatim


def summon_seed(facts=None) -> str:
    """The ONE visible line typed into the agent — a pointer, not a lecture.
    Everything else (the facts, the screen) travels in the task file; the
    durable knowledge is in the installed skills."""
    where = (facts or {}).get("where")
    loc = f": {where}" if where else ""
    return (f"Summoned from sciqnt{loc} — context in "
            f"{sq_agents.TASK_FILE}.")


def summon_prompt(facts=None) -> str:
    """The TASK-FILE body for a summoned SciQnt Agent: terse fact lines, no
    choreography. The agent gets honest state — where the user is, what's on
    their screen, the command that reproduces it, why the summon happened —
    and decides its own behaviour. Durable knowledge (what sciqnt is, how to
    explore) lives in the installed skills; the CLI self-describes via
    `sciqnt --help`.

    `facts`: {"where": str, "command": str, "screen": str|None,
              "warnings": [str]|None} — all view state is captured by the
    view layer at summon time (tabbed_view.last_view), never hand-assembled
    per call site."""
    facts = facts or {}
    lines = []
    if facts.get("warnings"):
        lines.append("Summoned from the sciqnt app — these problems are on "
                     "the user's screen:")
        lines += [f"- {w}" for w in facts["warnings"]]
    else:
        lines.append("Summoned from the sciqnt app — the user pressed the "
                     "agent key without typing a request; you open.")
    lines.append("")
    if facts.get("where"):
        lines.append(f"view:       {facts['where']}")
    if facts.get("screen"):
        lines.append(f"screen:     {SCREEN_FILE} (verbatim, this directory)")
    if facts.get("command"):
        lines.append(f"reproduce:  {facts['command']}")
    lines.append("")
    lines.append("Every app view has a CLI form — `sciqnt --help` maps it; "
                 "`--json` for data. Figures sciqnt prints are "
                 "authoritative. Skills: sq-portfolio, sq-connectors. "
                 "Leave a home-screen finding: "
                 "sciqnt insight add \"…\" --ref \"<cmd>\".")
    return "\n".join(lines)


def _view_facts(crumbs=()):
    """Compose summon facts from what the VIEW LAYER captured — the single
    universal path for any tabbed screen. A new tab needs no wiring here:
    tabbed_view records (tab, sub, body) at summon and the reproduce command
    derives from ag.TAB_SURFACES."""
    account = crumbs[0] if crumbs else None
    tab, sub, body = sq_tui.tabbed_view.last_view or (None, None, None)
    parts = ["portfolio", *crumbs, *(p for p in (tab, sub) if p)]
    return {"where": " › ".join(parts),
            "command": ag.view_command(account=account, tab=tab, sub=sub),
            "screen": body}


def _launch_sciqnt_agent(root, framework, facts=None):
    """Launch the chosen agent framework as the SciQnt Agent. Installs both
    skills (persistent capability — now and in any future session), runs in
    the repo root, writes the summoned-from screen as a context file, and
    seeds the facts; the agent drives from there."""
    label = sq_agents.label(framework)
    sq_skills.install(framework, "sq-portfolio")
    where = sq_skills.install(framework, "sq-connectors")
    note = (f"sq-portfolio + sq-connectors skills ready — reusable in any future "
            f"{label} session" if where else None)
    screen = (facts or {}).get("screen")
    context = {SCREEN_FILE: screen} if screen else None
    _agent_handoff(label, (facts or {}).get("where") or "Portfolio",
                   summon_prompt(facts), seed=summon_seed(facts),
                   note=note, agent=framework, cwd=str(root),
                   context=context, task_intro="")


def _agent_more_dropdown(root):
    """The 'More' framework picker: every SUPPORTED agentic framework with live
    install state — installed ones (green ✓) selectable to set as default;
    not-installed ones (grey ✗) show an install hint. Detection is on-demand."""
    while True:
        st = sq_agents.status()
        items = []
        for a in st:
            mark = f"{GREEN}✓{RST}" if a["installed"] else f"{DIM}✗{RST}"
            tail = "" if a["installed"] else f"  {DIM}not installed{RST}"
            items.append((f"{mark} {a['label']}{tail}", a["name"]))
        items = [_menu_header("SciQnt Agent", "Frameworks")] + items
        sel = sq_tui.select_screen(
            items, header=banner_text(root) + "\n",
            footer_hint="↑↓ move · enter select · ←/esc back", esc_result=sq_tui.BACK)
        if sel == sq_tui.BACK:
            return
        chosen = next(a for a in st if a["name"] == sel)
        if chosen["installed"]:
            sq_config.set("preferred_agent", sel)        # becomes the default
            sq_agents.mark_used(sel)                     # leads the toggle now
            return
        # not installed → show how to get it, then stay in the picker
        sq_tui.clear_screen()
        print(_static_chrome(root, "home", "SciQnt Agent", "Frameworks"))
        print(f"\n  {BOLD}{chosen['label']}{RST} {DIM}isn't installed.{RST}")
        print(f"  {DIM}install:{RST} {chosen['install']}")
        try:
            input(f"\n  {DIM}[enter to go back]{RST} ")
        except (EOFError, KeyboardInterrupt):
            pass


def _menu_header(*crumbs):
    """A greyed 'Menu[ › crumb › …]' section label (a non-selectable SEP-text
    row) shown directly above a screen's navigable items. Pair with an item
    style of 'dim'."""
    return ("  Menu" + "".join(f" › {c}" for c in crumbs), sq_tui.SEP)


def _agent_hint(context):
    """The greyed `Ask "…"` hint line for `context` — the screen's pinned
    example if it has one, else a random pick from the pool."""
    ex = _CONTEXT_DEFAULT.get(context) or random.choice(_AGENT_EXAMPLES)
    return f'   Ask "{ex}"'


def _agent_rows(context, warnings=None, recommend=None):
    """The reusable SciQnt Agent component for ANY screen: the framework-selector
    row + a context-aware greyed hint. Returns (rows, styles, toggle, installed)
    — prepend `rows`/`styles` to a screen's items and pass `toggle` to
    select_screen (toggle index 0). Detection is on-demand. Handle a sel of
    "agent" with `_agent_activate(root, context, installed)`.

    WARNING MODE (`warnings` = plain-text problem lines): SAME layout and
    toggle as the healthy state — only the greyed Ask-hint slot is replaced
    by an orange "⚠ Recommended: Troubleshoot with Agent" header + the issue
    lines beneath (capped at `_MAX_WARN_LINES`, the rest folded into a
    "…and N more"). Enter on the row launches the troubleshoot session with
    the toggled framework (callers route sel "agent" via `_agent_warn_activate`).

    RECOMMEND MODE (`recommend` = one short string): a single orange
    "⚠ Recommended: <…>" line in place of the hint — for a focused screen
    (e.g. ONE failing account) where a one-liner reads better than the
    multi-line problem block. Same agent-row routing as warning mode."""
    installed = sq_agents.recent_installed()     # MRU order: last-used first
    labels = [sq_agents.label(n) for n in installed]
    options = labels + ["More"]
    if installed:
        agent_label = f"SciQnt Agent + {labels[0]}"   # the most recent leads
    else:
        agent_label = "SciQnt Agent + (no agent installed — More)"
    # A small accent diamond before the agent label, declared as a badge so
    # _toggle_fragments paints it in the highlight colour (class:sel) and drops
    # it under NO_COLOR — see the note below on why baked ANSI is the wrong tool.
    toggle = {"index": 0, "prefix": "SciQnt Agent + ", "options": options,
              "selected": 0, "badge": "◆ "}
    rows = [(agent_label, "agent")]
    styles = [None]
    # Style class, NOT baked ANSI: select_screen renders SEP rows through
    # prompt_toolkit fragments, where the row's class wins (a None style falls
    # back to class:head = bold white) and raw ESC codes are discarded — the
    # "warn" class is what actually paints it orange.
    if recommend:
        rows.append((f"   ⚠ Recommended: {recommend}", sq_tui.SEP))
        styles.append("warn")
    elif warnings:
        # "Recommended" framing (consistent with the single-account screen):
        # a header line + the problem lines indented beneath, capped so a long
        # outage list can't push the portfolio table off the frame.
        rows.append(("   ⚠ Recommended: Troubleshoot with Agent", sq_tui.SEP))
        styles.append("warn")
        shown = warnings[:_MAX_WARN_LINES]
        for w in shown:
            rows.append((f"      {w}", sq_tui.SEP))
            styles.append("warn")
        if len(warnings) > _MAX_WARN_LINES:
            rows.append((f"      …and {len(warnings) - _MAX_WARN_LINES} more",
                         sq_tui.SEP))
            styles.append("warn")
    else:
        rows.append((_agent_hint(context), sq_tui.SEP))
        styles.append("dim")
    return rows, styles, toggle, installed


def _agent_warn_activate(root, installed, failed, idx=None):
    """Act on the agent row while in WARNING mode: the toggled framework is
    honoured (set default + MRU, like _agent_activate) and the session opens
    on the troubleshoot task; the "More" segment still opens the picker."""
    if idx is None:
        idx = sq_tui.select_screen.toggle_selected
    if not installed or idx >= len(installed):     # the "More" segment
        _agent_more_dropdown(root)
        return
    chosen = installed[idx]
    sq_config.set("preferred_agent", chosen)
    sq_agents.mark_used(chosen)
    _agent_troubleshoot(root, failed)


def _agent_activate(root, context, installed, idx=None, facts=None):
    """Act on a selection of the agent row: open the framework picker ("More"),
    or set the chosen framework as default and launch the SciQnt Agent seeded
    with `facts` (the summoned-from state — see summon_prompt).
    `idx` defaults to the select_screen toggle; tab views pass it explicitly."""
    if idx is None:
        idx = sq_tui.select_screen.toggle_selected
    if not installed or idx >= len(installed):     # the "More" segment
        _agent_more_dropdown(root)
        return
    chosen = installed[idx]
    sq_config.set("preferred_agent", chosen)       # remember as the default
    sq_agents.mark_used(chosen)                    # …and bump it to MRU front
    if context == "connect":
        _agent_connect(root)
    else:
        _launch_sciqnt_agent(root, chosen, facts=facts)


def _chrome_select(root, context, crumbs, items, item_styles=None, *,
                   selected=0, footer_hint=None, intro=None,
                   recommend=None, failed=None):
    """`select_screen` wrapped in the standard chrome every level shares:
    banner → SciQnt Agent component (context-aware, fully interactive) →
    'Menu › …' header (+ optional greyed `intro` lines) → `items`. Handles the
    agent row internally (launch, then re-render); returns any other selection
    (BACK included). The cursor starts on the FIRST item (not the agent row);
    the index relative to `items` is exposed as `_chrome_select.last_index`.

    `recommend` (a short string) + `failed` (the degraded BrokerSnapshots)
    put the agent component in warning mode: a "⚠ Recommended: …" line, and
    the agent row launches a troubleshoot session for `failed` instead of the
    plain summon."""
    while True:
        rows, styles, toggle, installed = _agent_rows(context, recommend=recommend)
        head = rows + [("", sq_tui.SEP), _menu_header(*crumbs)]
        head_styles = styles + [None, None]
        for line in (intro or []):
            head.append((f"   {line}", sq_tui.SEP))
            head_styles.append("dim")
        sel = sq_tui.select_screen(
            head + list(items), header=banner_text(root) + "\n",
            item_styles=head_styles + list(item_styles or [None] * len(items)),
            toggle=toggle, selected=len(head) + max(0, selected or 0),
            footer_hint=footer_hint
            or "↑↓ move · ←→ switch agent · enter select · esc back",
            help_lines=_HELP_SUB, esc_result=sq_tui.BACK)
        if sel == "agent":
            if failed:
                _agent_warn_activate(root, installed, failed)
            else:
                _agent_activate(root, context, installed)
            continue
        li = getattr(sq_tui.select_screen, "last_index", 0)
        _chrome_select.last_index = (max(0, li - len(head))
                                     if isinstance(li, int) else 0)
        return sel


_chrome_select.last_index = 0


def _static_chrome(root, context, *crumbs):
    """The same chrome as a plain ANSI header block (banner + a DISPLAY-ONLY
    greyed agent line + hint + bold 'Menu › …'), for screens that aren't select
    lists — text inputs and viewers — so every level looks consistent."""
    installed = sq_agents.recent_installed()
    if installed:
        labels = [sq_agents.label(n) for n in installed] + ["More"]
        agent_line = "   SciQnt Agent + " + "  |  ".join(labels)
    else:
        agent_line = "   SciQnt Agent + (no agent installed — More)"
    menu = "  Menu" + "".join(f" › {c}" for c in crumbs)
    return (banner_text(root) + "\n\n"
            + f"{DIM}{agent_line}{RST}\n"
            + f"{DIM}{_agent_hint(context)}{RST}\n\n"
            + f"{BOLD}{menu}{RST}")


def _portfolio_view(root, tabs, *crumbs, failed=None, rebuild=None):
    """The portfolio / account detail view with the standard home chrome:
    banner + SciQnt Agent component + 'Menu › portfolio …' tab bar. ↑ focuses
    the agent row (←/→ choose, enter launches, then the view re-opens).
    `failed` (degraded BrokerSnapshots) switches the component to warning
    mode — orange problem lines on top, the row as the recommended
    troubleshoot action — matching the home landing.
    `rebuild()` powers ^R: re-fetch fresh and return `(tabs, failed)` (or None
    to keep the current view); the view then re-opens on the fresh data."""
    while True:
        installed = sq_agents.recent_installed()
        labels = [sq_agents.label(n) for n in installed]
        agent = {"prefix": "SciQnt Agent + ",
                 "options": labels + ["More"],
                 "selected": 0,
                 "hint": _agent_hint("portfolio").strip()}
        if failed:                    # warning mode: hint → troubleshoot block
            agent["warn"] = [ag.account_problem_text(b) for b in failed]
        res = tabbed_view(
            tabs, header=banner_text(root) + "\n", agent=agent,
            sub_defaults={"history": "YTD"},
            menu_label="Menu › " + " › ".join(("portfolio",) + crumbs))
        if res == sq_tui.REFRESH:                     # ^R: rebuild fresh + re-open
            if rebuild is not None:
                new = rebuild()
                if new is not None:
                    tabs, failed = new
            continue
        if isinstance(res, tuple) and res[0] == "agent":
            if failed:
                _agent_warn_activate(root, installed, failed, idx=res[1])
            else:
                _agent_activate(root, "portfolio", installed, idx=res[1],
                                facts=_view_facts(crumbs))
            continue                                  # back to the same view
        return


_BG_REFRESH = "__bg_refresh__"          # select_screen result: a bg refresh landed


def _loading_fetch(root, *, fresh):
    """Fetch all brokers with a visible parallel progress screen (cold start /
    ^R). Returns the broker snapshots (or [] if cancelled)."""
    names = [lbl for lbl, _ in ag._discover_brokers(root)]
    title = "refreshing…" if fresh else "loading portfolio…"
    return sq_tui.loading_screen(
        names,
        lambda cb: ag._collect_snapshots(
            root, use_snapshot_cache=not fresh, on_update=cb),
        header=banner_text(root), title=title) or []


def _wake_app(app_holder, result, *, tries=100, interval=0.1):
    """Ask the on-screen select_screen Application to exit with `result` so
    the home loop re-renders. A background worker can finish BEFORE
    `app.run()` has a live event loop (fast fetch beats first paint) — calling
    `app.exit()` then is a silent no-op and the user is stuck until a manual
    keypress. So poll until the app is actually running, then exit it. If it
    never runs (the user already left), give up quietly — the result still
    sits in `pending` and is adopted on the next loop iteration."""
    for _ in range(tries):
        app = app_holder[0]
        if app is not None and getattr(app, "is_running", False):
            try:
                app.loop.call_soon_threadsafe(
                    lambda a=app: a.exit(result=result))
                return
            except Exception:                              # noqa: BLE001
                return
        time.sleep(interval)


def _start_bg_refresh(root, pending, app_holder):
    """Refresh all brokers live in a background thread (stale-while-revalidate).
    Stores the result in `pending['v']` and exits the home's running
    select_screen so the loop re-renders with fresh data — including any
    broker that's currently FAILING (failures aren't cached, so they're
    invisible on the instant warm paint and only surface once this lands)."""
    def _bg():
        try:
            # quiet() suppresses broker chatter; safe concurrently with the home
            # app, which renders to the real terminal, not sys.stdout.
            with sq_tui.quiet():
                pending["v"] = ag._collect_snapshots(root, use_snapshot_cache=False)
        except Exception:                                  # noqa: BLE001
            pass
        finally:
            _wake_app(app_holder, _BG_REFRESH)
    threading.Thread(target=_bg, daemon=True).start()


def _start_chart_compute(brokers, ccy, range_label, chart_cache,
                         computing, app_holder):
    """Build the home chart's series for `range_label` off the paint path
    (YTD ≈ seconds; All ≈ tens). Result lands in `chart_cache`; if the
    home app is on screen, exit it so the loop re-renders with the chart.
    `computing` (a set) prevents duplicate workers per range."""
    if range_label in computing:
        return
    computing.add(range_label)

    def _bg():
        try:
            with sq_tui.quiet():
                block = ag.history_chart_block(brokers, ccy, range_label)
            chart_cache[range_label] = block or ""    # "" = uncomputable
        except Exception:                              # noqa: BLE001
            chart_cache[range_label] = ""
        finally:
            computing.discard(range_label)
            _wake_app(app_holder, _BG_REFRESH)
    threading.Thread(target=_bg, daemon=True).start()


def run_home(root, *, use_snapshot_cache: bool = True) -> int:
    """Interactive landing — a single full-screen app (alternate screen), redrawn
    in place each loop: the logo + portfolio summary are the persistent header,
    the actions are an in-place cursor list, a sticky footer shows the keys. No
    re-printed chrome, no scrollback accumulation. Returns a process exit code.

    ^R refreshes (bypass cache), ? shows help, Esc/q quits. Drilling into a
    detail view (tabs / connect / settings / modules) leaves the frame, runs,
    and returns to a clean home. Non-TTY callers use `run_aggregated` instead."""
    fresh_next = not use_snapshot_cache          # honour --fresh on first pass
    last_tabs = last_title = None
    cursor = 0                                   # sticky menu position
    brokers = None                               # data to render (None → acquire)
    from_cache = stale = False                   # render provenance / freshness
    refreshing = [False]                         # a bg refresh is in flight
    did_initial = [False]                        # the session's first revalidation ran
    pending: dict = {}                           # bg-refresh result holder
    chart_range = ["YTD"]                        # home chart range (toggle)
    chart_cache: dict = {}                       # range → ANSI block ("" = n/a)
    chart_computing: set = set()                 # ranges being built

    while True:
        # Adopt a finished background refresh (set by _start_bg_refresh).
        if "v" in pending:
            brokers, from_cache, stale, refreshing[0] = pending.pop("v"), False, False, False
            chart_cache.clear()                  # fresh data → recompute charts

        # Acquire data when needed.
        #  • FIRST load (and ^R / --fresh) → a visible LIVE fetch (loading
        #    screen): the user opening the app expects current totals, and a
        #    broker that's failing RIGHT NOW must surface its ⚠ immediately —
        #    a stale warm-cache paint would hide both until a later manual
        #    refresh. Live broker sessions are reused (no re-login while the
        #    session is valid), so this isn't a re-auth on every launch.
        #  • LATER re-acquisitions (returning from a submenu) → INSTANT warm
        #    cache, with a background revalidate when it's gone stale.
        if brokers is None:
            if fresh_next or not did_initial[0]:
                brokers, from_cache, stale = _loading_fetch(root, fresh=True), False, False
                fresh_next = False
                did_initial[0] = True
            else:
                cached, is_stale = ag._collect_cached(root)
                if cached:
                    brokers, from_cache, stale = cached, True, is_stale
                else:                            # cold: nothing cached → fetch visibly
                    brokers, from_cache, stale = _loading_fetch(root, fresh=False), False, False
        available = ag._available_connectors(root)
        connected = sorted({ag._broker_label_split(b.broker)[0]
                            for b in brokers if b.ok})
        failed = [b for b in brokers if not b.ok]
        unconnected = [c for c in available if c not in connected]

        pf_items, pf_styles, col_header = [], [], None
        if any(b.ok for b in brokers):
            with sq_tui.quiet():
                last_tabs, last_title, agg = ag.build_aggregate(
                    root, brokers, daily=True)       # daily tab is lazy — free here
            ccy = sq_config.display_currency()
            col_header, pf_items, pf_styles = _portfolio_table(agg, ccy)
            body_intro = ""                                  # table header goes IN items
        else:
            last_tabs = None
            body_intro = (f"\n  {DIM}No accounts connected yet — open Portfolio Accounts "
                          f"› Connect new Account to see your portfolio.{RST}")
        # Trailing blank line → one row of breathing space between the logo and
        # the agent selector row below.
        header = banner_text(root) + body_intro + "\n"

        # The reusable SciQnt Agent component (selector row + greyed "Ask …"
        # hint), right under the banner. Genuine failures (account configured
        # but the fetch errored) switch it to WARNING MODE: orange problem
        # line(s) on top + the row reframed as the recommended troubleshoot
        # action (which replaces the old separate "Troubleshoot with agent"
        # menu item AND the old raw error lines in the header).
        warnings = [ag.account_problem_text(b) for b in failed]
        head, head_styles, toggle, installed = _agent_rows("home", warnings)
        # Demo mode is never mistakable for real money: a warning-coloured
        # recommendation (prominent) + a dim detail line naming the persona.
        _demo = next((b for b in brokers if b.ok
                      and b.broker.split(":")[0] == "demo"), None)
        if _demo is not None:
            who = "the demo"
            try:                                   # name the persona, not a broker
                import sq_demo
                _p = sq_demo.current_persona()
                who = f"{_p['name']} {_p['emoji']}"
            except Exception:                      # noqa: BLE001 — any failure → generic
                pass
            head.append(("   ⚠ Recommended: Connect a broker account to see your "
                         "Portfolio.", sq_tui.SEP))
            head_styles.append("warn")
            head.append((f"     DEMO mode (dummy data) — you're viewing “{who}” "
                         f"Demo Portfolio.", sq_tui.SEP))
            head_styles.append("warn")
        # Agent → app push channel: unseen insights surface ONCE on the
        # home (then marked seen). The ✦ row is plain fact — text + who
        # left it; the ref command lets the user reproduce the finding.
        notes = insights.current(unseen_only=True)
        if notes:
            for n in notes[-3:]:
                ref = f"   ({n['ref']})" if n.get("ref") else ""
                head.append((f"   ✦ {n['source']}: {n['text']}{ref}",
                             sq_tui.SEP))
                head_styles.append("dim")
            insights.mark_seen([n["id"] for n in notes])

        # The PORTFOLIO + account rows ARE the "details" entry (select one to drill
        # in); then a divider, then the action menu. item_styles greys the account
        # rows / bolds PORTFOLIO.
        actions = list(HOME_MENU)
        # Agent component on top, then the portfolio table (its bold column header
        # is a non-selectable SEP-text row so the toggle sits ABOVE the whole
        # table), then a "Menu" section header, then the actions.
        # The embedded history chart (net worth + P/L per period) with a
        # ←/→ range toggle — computed OFF the paint path and session-
        # cached so the home's instant first paint stays instant.
        chart_rows, chart_styles, range_toggle = [], [], None
        if pf_items:
            rng = chart_range[0]
            block = chart_cache.get(rng)
            if block:
                chart_rows = [(block, sq_tui.SEP)]
                chart_styles = [None]
            elif block is None:
                chart_rows = [(ag.chart_skeleton(
                    sq_config.display_currency(), rng), sq_tui.SEP)]
                chart_styles = [None]
            # block == "": range uncomputable → no chart rows at all
            range_toggle = {
                "options": list(ag.HISTORY_RANGES),
                "selected": list(ag.HISTORY_RANGES).index(rng),
                "default": list(ag.HISTORY_RANGES).index("YTD"),
                "separator": " │ ",                # sub-tab-bar look
                "always_accent": True,             # active range stays lit
                "exit_on_change": True,
            }

        menu = [_menu_header()]
        menu_styles = [None]                         # None → bold 'head' (white+bold)
        if pf_items:
            table = [("", sq_tui.SEP), (col_header, sq_tui.SEP)] + pf_items
            table_styles = [None, None] + pf_styles
            # Selector ABOVE the chart (sub-tab-bar idiom).
            items = (head + table + [("", sq_tui.SEP), ("", "range")]
                     + chart_rows + [("", sq_tui.SEP)] + menu + actions)
            item_styles = (head_styles + table_styles + [None, None]
                           + chart_styles + [None] + menu_styles
                           + [None] * len(actions))
            range_toggle["index"] = len(head + table) + 1
        else:
            items = head + [("", sq_tui.SEP)] + menu + actions
            item_styles = head_styles + [None] + menu_styles + [None] * len(actions)

        # A warm (returning-to-home) paint that's gone stale → revalidate live
        # in the background and update in place when it lands (the refresh
        # writes through, so the next acquire is fresh). The session's FIRST
        # paint is already a visible live fetch above, so this only covers
        # later re-acquisitions.
        app_holder = [None]
        if from_cache and stale and not refreshing[0]:
            refreshing[0] = True
            _start_bg_refresh(root, pending, app_holder)

        hint = "↑↓ move · ←→ switch agent · enter open · ^R refresh · esc quit"
        if refreshing[0]:
            hint = f"↻ updating…  ·  {hint}"
        toggles = [toggle] if toggle else []
        if range_toggle is not None:
            toggles.append(range_toggle)
        # Kick the chart worker for the current range (no-op when cached
        # or already in flight) — needs app_holder so it can re-render.
        if (pf_items and chart_range[0] not in chart_cache):
            _start_chart_compute(brokers, sq_config.display_currency(),
                                 chart_range[0], chart_cache,
                                 chart_computing, app_holder)
        sel = sq_tui.select_screen(
            items, header=header, help_lines=_HELP, selected=cursor,
            item_styles=item_styles, toggle=toggles, app_holder=app_holder,
            footer_hint=hint,
            esc_result=sq_tui.QUIT, extra_keys={"c-r": sq_tui.REFRESH},
        )
        if sel == _BG_REFRESH:                    # bg refresh/chart landed → re-render
            continue                              # (cursor preserved; pending adopted up top)
        cursor = sq_tui.select_screen.last_index
        if sel == sq_tui.TOGGLED:                 # range toggle moved → recompute
            if range_toggle is not None:
                picked = sq_tui.select_screen.toggle_selected_by_index.get(
                    range_toggle["index"])
                if picked is not None:
                    chart_range[0] = list(ag.HISTORY_RANGES)[picked]
            continue
        if sel == "range":                        # enter on the toggle row: no-op
            continue
        if sel in ("quit", sq_tui.QUIT):
            return 0
        if sel == sq_tui.REFRESH:
            fresh_next = True
            brokers = None                        # force re-acquire (visible fetch)
        elif sel == "agent":
            if failed:                # warning mode: troubleshoot task
                _agent_warn_activate(root, installed, failed)
            else:
                rng = chart_range[0]
                cmd = "sciqnt --once"
                if rng != "YTD":      # non-default chart range is signal too
                    cmd += f"  (their chart: sciqnt --history {rng})"
                body = sq_tui.ANSI_RE.sub(
                    "", "\n".join(t for t, _ in items if isinstance(t, str)))
                facts = {"where": f"home — portfolio overview + {rng} chart",
                         "command": cmd, "screen": body}
                _agent_activate(root, "home", installed, facts=facts)
        elif sel == "portfolio" and last_tabs is not None:
            def _rebuild_portfolio():
                """^R inside the view: visible fresh fetch, rebuilt tabs."""
                fresh = _loading_fetch(root, fresh=True)
                if not any(b.ok for b in fresh):
                    return None                       # keep the current view
                with sq_tui.quiet():
                    t, _ti, _a = ag.build_aggregate(root, fresh, daily=True)
                return t, [b for b in fresh if not b.ok]
            _portfolio_view(root, last_tabs, failed=failed,
                            rebuild=_rebuild_portfolio)            # whole portfolio
        elif isinstance(sel, tuple) and sel[0] == "acct":          # one account
            one = [b for b in brokers if b.ok and b.broker == sel[1]]
            if one:
                # A single account's view is in its OWN base currency — config
                # display currency governs cross-account aggregation, not this.
                base = one[0].snapshot.account.base_currency

                def _rebuild_account(label=sel[1], base=base):
                    fresh = _loading_fetch(root, fresh=True)
                    sub = [b for b in fresh if b.ok and b.broker == label]
                    if not sub:
                        return None                   # keep the current view
                    with sq_tui.quiet():
                        t, _ti, _a = ag.build_aggregate(
                            root, sub, display_currency=base, daily=True)
                    return t, []
                with sq_tui.quiet():
                    tabs, title, _ = ag.build_aggregate(
                        root, one, display_currency=base, daily=True)
                _portfolio_view(root, tabs, sel[1], rebuild=_rebuild_account)
        elif sel == "accounts":
            _accounts_flow(root, brokers, available)
        elif sel == "config":
            _settings_flow(root)
        elif sel == "modules":
            run_interactive(root)
        # After any action (or a no-op), re-acquire on the next loop — instant
        # from cache, and picks up a bg refresh or a newly-connected account.
        if sel != sq_tui.REFRESH:
            brokers = None
