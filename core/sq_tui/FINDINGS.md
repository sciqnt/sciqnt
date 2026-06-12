# sq_tui — findings (living quirks log)

- **All full-screen apps render to `_REAL_STDOUT`** (the terminal captured at import), **never live `sys.stdout`** — every `Application` gets `output=_app_output()`. This is the load-bearing decision that makes `quiet()` (a Python-level `sys.stdout` swap) safe to run *concurrently with a live app from a worker thread*: broker-library chatter is swallowed while the renderer keeps the real fd. If you ever construct an app without `_app_output()`, a concurrent `quiet()` can capture/blank the UI (2026-06-03).
- **Cross-thread app exit** (stale-while-revalidate): a background thread may exit a running `select_screen` via `app.loop.call_soon_threadsafe(app.exit)` using the `app_holder` hook. Always wrap in try/except — the app may already be gone. `loading_screen` avoids the converse race (worker finishing before the loop exists) by starting its worker via `app.run(pre_run=…)`.
- **NO_COLOR is honoured two ways**: `_c()` returns empty SGR tokens, AND `_app_color_depth()` forces 1-bit depth on the prompt_toolkit apps. Both are needed (tokens cover print-path, depth covers ptk styles).
- **Adaptive accent**: Apple Terminal.app drops truecolor, so `_hex_to_ansi` falls back to a 256-colour approximation of `ACCENT_HEX`.
- **`quiet()` must NEVER wrap an `app.run()`** (it would capture the output at app construction). Worker threads wrapping fetches are fine — see the first finding.
- `loading_screen` has a sticky " ^C cancel " footer (gap closed; was flagged in maintenance 2026-06-03).
- ←/→ conventions: ← is back-navigation only (never quits the app; top-level ← is a no-op); toggles and tab bars do NOT wrap — ← at the left edge means back.
- **Interactive vs dump is a TWO-stream decision**: the full-screen apps require BOTH `stdin.isatty()` AND `stdout.isatty()` (stdin alone misroutes `sciqnt --once > file` into the app). `tabbed_view(interactive=…)` lets the caller force it — `run_aggregated` passes `interactive=False` because it IS the non-interactive surface; `None` auto-detects (2026-06-11).
- **Non-interactive dump resilience**: each tab body in the dump path is wrapped in try/except — one failing tab prints `  (tab failed: <Type>: …)` instead of killing the whole dump (mirrors the interactive `_resolve_live`).
- **^R in `tabbed_view`** exits the app with the `REFRESH` sentinel — the view holds pre-built bodies and cannot re-fetch itself; the caller (home's `_portfolio_view`) rebuilds fresh and re-opens.
- **Warning severity**: user-fixable warnings are `warn_line()` (YELLOW ⚠ + plain text); DIM is reserved for transient/informational lines. `WARN_HEX` is the one orange constant (feeds the ptk `warn` style classes AND the print-path `ORANGE`).
- **tabbed_view body scrolling**: j/k scroll by line, PgUp/PgDn by page, g/G to top/bottom; offset resets on any tab/sub-tab switch; the clamp math is the pure `_clamp_scroll` (unit-tested). Deliberate deviation from the §2 keymap: ↑/↓ do NOT scroll there — they own focus navigation (agent row / sub-tabs), so j/k is the only line-scroll. `select_screen` follows the cursor into view via `get_cursor_position` on its body control (long lists scroll with the hover).

## / type-to-filter (2026-06-12 — the deferred item, shipped)
`select_screen` now has skills-find-style filtering: `/` enters filter
mode, typing narrows live (case-insensitive substring over each row's
visible text), SEP headers drop out so results read as a flat list,
↑↓ move within matches, enter selects, esc clears (then esc again
backs out). Letter shortcuts (j/k/q/?/h/l/extra_keys) are gated OFF in
filter mode via prompt_toolkit Conditions so they type into the query.
The footer shows the live query + match count; the menu footer offers
"· / find" once a screen has ≥8 selectable rows. Pure matcher
`_filter_indices` is unit-tested. Non-interactive twin:
`sciqnt modules find <query>` (sq_platform.find_modules).
Inspired by Vercel's `npx skills find` UX — the modules-as-skill-
packages parallel is exact (bundle = folder with SKILL.md).
