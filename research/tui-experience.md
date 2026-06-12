# Cutting-edge TUI experience — principles + sciqnt action plan

**Status: IMPLEMENTED (2026-06).** The migration this document planned has
shipped: full-screen alternate-screen apps everywhere (`select_screen`,
`tabbed_view`, `loading_screen`, `text_input_screen`), persistent chrome
(banner + SciQnt Agent component + `Menu › …` header on every level),
keybinding conventions (← back / no wrap, Esc-q-^C quit, ^R refresh, `?` help),
NO_COLOR honoured (SGR tokens + 1-bit ptk depth), and the non-TTY line-dump
fallbacks kept. The `/maintenance` audit (checklist #10) enforces it. The text
below is the original research synthesis — its "current gaps" describe the
PRE-migration state and are retained for rationale, not as open work.

*Research synthesis, 2026-06-01.* Grounds the redesign of sciqnt's
interactive TUI (`core/sq_platform` + `core/sq_tui`). Produced by the
deep-research harness: 5 angles → 24 sources → 109 claims → 25 adversarially
verified (3-vote), **0 refuted**. Cites primary docs (Claude Code, prompt_toolkit,
Textual, lazygit, k9s, clig.dev, no-color.org) over blogs where they conflict.

> Why this exists: the owner flagged the home flow as clunky — it **re-prints the
> banner/logo on every screen, accumulates blank-line whitespace, and dumps menus
> into scrollback**. This is the durable record of what "good" looks like and how
> sciqnt should get there. Honours the **"TUI is king"** principle (CLAUDE.md).

---

## The load-bearing finding

**sciqnt's clunkiness is the architecture, not the styling.** It uses an
*append-only, line-by-line print* model: every navigation `print()`s fresh chrome
+ content below the last, so the screen grows, scrolls, and repeats the logo. The
cure every serious TUI uses is the opposite model:

**A full-screen application on the alternate screen buffer** (DEC private mode
`?1049`) that **draws the chrome once and redraws only the regions that change.**
Claude Code "draws like vim or htop" — full-screen, in place. [code.claude.com/fullscreen]
[ratatui.rs/alternate-screen]

Mechanics (all verified):
- **Alternate screen buffer** is a separate terminal screen; entering it (`?1049h`)
  preserves the user's scrollback, and on exit (`?1049l`) the original screen +
  scrollback are **restored** — the TUI leaves no scroll spam behind. [ratatui.rs]
- **Flicker-free rendering** = overwrite in place + **synchronized output**
  (DEC mode `?2026`), which batches a frame so the terminal paints it atomically
  (double-buffer / atomic-frame). Claude Code's renderer relies on this.
  [christianparpart gist][slyapustin blog]
- You compute the new screen and **diff** it against the last, emitting only
  changed cells. That's what makes vim/htop/lazygit feel instant and stutter-free.

**Honest tradeoff (verified caveat):** full-screen/alternate-screen apps *disable
native terminal scrollback* while active (Claude Code's opt-in fullscreen, v2.1.89+,
hit exactly this — issue #42670), and full-screen programs are **hostile to screen
readers**. → keep a **non-fullscreen / line-based fallback** for non-TTY, piped,
`NO_COLOR`, and accessibility use (see §4). Full-screen is for the *interactive TTY*
path only.

### When full-screen vs a clean line-based REPL
- **Full-screen app** (alternate screen, persistent layout): stateful navigation,
  dashboards, lists you move a cursor through, live-updating data. ← sciqnt's home,
  module browser, and portfolio tabs all fit this.
- **Line-based REPL / one-shot dump**: scriptable output, pipes, logs, `--once`
  dumps, CI. Keep this for `sciqnt --once`, `--asof`, and any non-TTY caller.

---

## 1. How the leading AI-agent CLIs are built

| Tool | Stack | Notes |
|---|---|---|
| **Claude Code** | **Ink** (React for terminals, Node) | full-screen, flicker-free, fixed bottom input box [verified] |
| **Gemini CLI** | **Ink** | same family [verified] |
| **OpenCode** | **OpenTUI** | the "Ink killer" cohort [stork.ai blog] |
| Codex CLI | Rust/Ratatui (immediate-mode) | per the melker tui-comparison |
| Charm tools (glow, gum) | **Bubble Tea** (Go, Elm-arch) | |

**Shared UX conventions** (the patterns to copy):
- A **persistent input/command box fixed at the bottom**, content scrolls above it.
- **Minimal chrome**: the brand/header appears **once**, not per turn.
- **Streaming / instant feedback**, a **status line**, a **sticky footer** of hints.
- **Truecolor theming** with graceful degradation (sciqnt already does this via the
  adaptive accent — keep it).

Rendering-model split (verified): **immediate-mode** (Ratatui — redraw everything
each frame) vs **retained/reactive** (Textual — a widget tree, re-render only
changed parts). For Python with modern async needs, the reactive model (Textual)
is the recommended modern choice; prompt_toolkit's full-screen `Application` is the
lower-level, lower-risk option.

---

## 2. Keyboard & interaction conventions (the near-universal set)

Verified against lazygit, k9s, Textual, clig.dev. Adopt these so muscle memory
transfers:

| Key | Action | Source |
|---|---|---|
| `↑/↓` + `j/k` | move selection | lazygit, k9s (vim + arrows both) |
| `Enter` | select / drill in | universal |
| `Esc` / `q` | back, then quit at top | lazygit, k9s |
| `?` | **context-sensitive help** overlay | lazygit (pressing `?` lists keys for the focused panel) |
| `/` | **filter the current list** | lazygit, k9s fuzzy filter |
| `Ctrl-P` / `Ctrl-K` | **command palette** (fuzzy) | Textual built-in; k9s aliases |
| `g` / `G` | jump to top / bottom | vim-class |
| `Ctrl-R` | refresh / reload | conventional |
| `Tab` / `←/→` | move between panels / tabs | lazygit, sciqnt's tabbed view |

Principles:
- **Single-key, non-modal where possible; avoid chords** for primary actions
  (chords are fine for rare ones). [clig.dev]
- **Discoverability is mandatory:** a **sticky footer hint bar** of the current
  keys, plus a `?` help overlay. Don't make users guess. lazygit's
  context-sensitive `?` is the gold standard.
- **Consistency:** the same key does the same thing everywhere; `Esc` always means
  "up/out".
- **Breadcrumb / context** so the user always knows where they are.
- **Progressive disclosure:** show the headline; details live one keystroke away
  (sciqnt's "Portfolio details" tab is already this instinct).

---

## 3. Reference TUIs — why they feel good (transferable patterns)

- **lazygit** — panels with context-sensitive `?` help; `/` filter; single-key
  actions per panel; everything reachable without leaving the keyboard. [lazygit.dev]
- **k9s** — command **aliases** + a fuzzy **filter mode** to drive to any resource
  fast; live-updating views. [k9scli.io]
- **fzf** — fuzzy-find as a universal navigation primitive (type-to-narrow).
- **btop / htop** — dense, live, in-place dashboards; no scroll, all redraw.
- **Harlequin / Posting** — full **Textual** apps (Harlequin on textual 6.4.0):
  persistent layout, command palette, panels, mouse + keyboard. [harlequin.sh]
- **Textual command palette** — fuzzy-searchable action list, `Ctrl-P`; the modern
  "do anything" affordance. [textual command_palette]

Common thread: **a stable frame you navigate**, instant feedback, type-to-filter,
and a discoverable command surface — never a growing scroll of reprinted screens.

---

## 4. Accessibility & fallbacks (non-negotiable)

- **`NO_COLOR`**: if the env var is present (any value), **suppress all color**.
  [no-color.org] (sciqnt currently always emits ANSI — a gap; see action plan.)
- **Don't colorize when not a TTY / when piped**; detect `stdout.isatty()`.
  [clig.dev, seirdy]
- **Full-screen TUIs are hostile to screen readers** → always keep the line-based
  path (`--once`, non-TTY) as the accessible/scriptable surface. [afixt, verified]
- Respect `TERM=dumb` and missing-truecolor (sciqnt's adaptive accent already
  handles the truecolor→256 case).

---

## 5. Ranked design principles for sciqnt

1. **One full-screen app, drawn once.** Persistent layout (header / body / footer);
   navigation swaps the *body*, never re-prints the header. Alternate screen buffer;
   restore scrollback on exit. *(Kills the re-printed-logo + whitespace problems at
   the root.)*
2. **Sticky footer hint bar + `?` help overlay.** Always show the active keys.
3. **Consistent keybindings** (the table in §2). `Esc`=back/quit, `?`=help,
   `/`=filter, `Ctrl-R`=refresh, arrows+`j/k`=move, `Ctrl-P`=palette (later).
4. **No manual spacing / no dump-and-scroll.** Layout owns spacing; never hand-
   `print("\n")` to position things; never append menus into scrollback.
5. **Progressive disclosure + breadcrumb.** Headline first, details a keystroke away,
   always show where you are.
6. **Type-to-filter** any list once there are enough connectors/positions to warrant it.
7. **Keep the line-based dump** for non-TTY / `--once` / `NO_COLOR` / a11y. Two
   surfaces, one set of numbers.
8. **Theme through the single accent token** (already done) + honour `NO_COLOR`.

---

## 6. Recommendation & migration path

**Recommendation: migrate the interactive TTY surface to a single prompt_toolkit
full-screen `Application`** — *not* a Textual rewrite, *not* status-quo line-based.

Rationale:
- sciqnt **already depends on prompt_toolkit** (questionary is built on it) and
  **already runs one full-screen prompt_toolkit `Application`** — the tabbed
  portfolio view (`sq_tui.tabbed_view`). A full-screen home is the *same stack*,
  **no new dependency**, lowest risk. prompt_toolkit's `Application(full_screen=True)`
  is the documented path. [prompt_toolkit full_screen docs]
- **Textual is the richer option** (reactive widgets, CSS, built-in command palette,
  mouse) and the modern recommendation in general — but it's a **new heavy dependency
  + a real rewrite**. Defer it; revisit if/when the UI wants web-style layout, panels,
  and a palette out of the box. Note it as the "if we outgrow prompt_toolkit" path.

**Migration path (incremental — each step independently shippable):**
1. **Stop the bleeding (cheap, now):** in the current line-based home, clear+redraw
   per loop instead of appending, and print the banner **once**. Buys most of the
   "less clunky" feel before the rewrite. *(Lowest-effort fix for the stated pain.)*
2. **Unify the frame:** build one `sq_tui` full-screen `Application` shell —
   persistent **header** (logo once + breadcrumb), swappable **body**, sticky
   **footer** hint bar. Fold the existing `tabbed_view` into it as one body view.
3. **Port the home + module browser** into body views of that shell; replace the
   reprint-and-scroll menus with an in-place cursor list.
4. **Wire the standard keymap** (§2) centrally: `Esc`/`q`, `?` help overlay, `/`
   filter, `Ctrl-R` refresh, arrows+`j/k`, later `Ctrl-P` palette.
5. **Keep `run_aggregated` (line dump)** untouched as the non-TTY / `NO_COLOR` /
   accessible surface; add `NO_COLOR` honouring to `sq_tui`.

### Highest-leverage fixes for the stated pain points
| Pain | Fix |
|---|---|
| Logo re-printed every screen | Header drawn once in the persistent frame (step 2); interim: print banner once + clear-per-loop (step 1) |
| Accumulating blank-line whitespace | Layout owns spacing; delete manual `print()` spacers (principle 4) |
| Dump-and-scroll menus | In-place cursor list in the body, alternate screen (step 3) |
| Clunky quit/refresh | Already moved to Esc-quit / `^R`-refresh; formalise in the central keymap (step 4) |

## Honest gaps / caveats
- Full-screen disables native scrollback while active (Claude Code #42670) and
  hurts screen readers — hence the mandatory line-based fallback (§4, principle 7).
- Several stack claims (Codex=Ratatui, OpenCode=OpenTUI) come from blogs/community
  comparisons, not vendor docs — directionally reliable, not gospel. Claude/Gemini =
  Ink and prompt_toolkit/Textual specifics are from primary sources.
- This doc is *design guidance*, not a committed plan — the architecture step is the
  owner's call; step 1 is safe to do immediately.

## Sources (selected; full set in the research run)
- Claude Code fullscreen — https://code.claude.com/docs/en/fullscreen
- Ratatui alternate screen — https://ratatui.rs/concepts/backends/alternate-screen/
- Synchronized output (DEC 2026) — https://gist.github.com/christianparpart/d8a62cc1ab659194337d73e399004036
- prompt_toolkit full-screen apps — https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html
- Textual app guide / command palette — https://textual.textualize.io/guide/app/ , /guide/command_palette/
- Harlequin (Textual case study) — https://harlequin.sh/
- lazygit keybindings — https://lazygit.dev/keybindings/
- k9s — https://k9scli.io/
- CLI guidelines — https://clig.dev/
- NO_COLOR — https://no-color.org/
