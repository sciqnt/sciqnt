# sq-config unit — findings, quirks & conformance notes

Living log for the user-config substrate. The engine code lives in
`core/sq_config/__init__.py` (the schema registry + read/write API); this
`modules/sq-config/` bundle is the user surface: `src/sq_config_ui/` (the
interactive full-screen settings screen), `set.py` / `show.py` (CLI entry
points), `bin/sq-config`. **Update this the moment a quirk or conformance
result is discovered.**

## What it is
A small, schema-driven JSON config at `~/.config/sciqnt/config.json` (XDG-style,
overridable via `SQ_CONFIG_PATH` for tests/CI). One `SCHEMA` list is the single
source of truth: every setting declares key, type, allowed values, default, help,
and which engine consumes it. From that the module materialises a documented
file on first run, defaults `get()`, validates `set()`, and renders `config show`.

## Settings status (the `mvp` flag — honest gaps habit)
- **Wired** (an engine reads it and behaviour changes): `display_currency`,
  `cost_basis_method`, `performance_return_method`, `annualize_sub_year_returns`.
- **Declared, not yet honoured** (`mvp=False`, shown as "soon" in `config show`):
  `fees_in_cost_basis` (engine is always fees-inclusive; the expense-fees code
  path doesn't exist), `tax_jurisdiction`, `tax_year_start` (no tax engine
  consumes them). Grounded by `research/config-settings-cross-asset.md`.

## Quirks / conformance
- **Config-free core:** consuming engines NEVER import `sq_config`. Resolution
  happens at each adapter/rendering boundary (`_resolve_cost_basis_method` in
  sq-degiro; `_performance_return_method` / `_annualize_sub_year_returns` in
  `sq_platform.aggregated`), so the deterministic core stays pure. New settings
  must follow this pattern.
- **Atomic writes:** `set()` writes tmp + `os.replace`, so a crash mid-write
  can't corrupt the file. A corrupt/unreadable file degrades to `{}` (callers
  fall back to schema defaults) rather than raising.
- **Forward-compatible:** unknown keys pass through `set()`/`get()` unvalidated
  (hand-added keys aren't rejected); `config show` lists them as "(not in schema)".
- **British spelling intentional:** `materialise` (codebase is British English).
- **Bool coercion:** `set()` accepts true/1/yes/on and false/0/no/off for bool
  settings; anything else raises `ValueError`.
- **ONE settings UI (2026-06):** the interactive surface is
  `sq_config_ui.run_settings` — a full-screen `sq_tui.select_screen` loop
  (rows = key + current value; mvp=False rows dim + "(soon)"; help in the `?`
  overlay; enum → second screen, bool → instant toggle, str → prefilled text
  input). The home's Settings action calls the SAME loop in-process (with its
  own chrome via `make_header`), so home and CLI are identical. The old
  questionary picker is gone — questionary doesn't render ANSI inside choice
  labels (it leaked raw `^[[2m` escapes); `select_screen` strips raw ANSI
  from row labels by design, so styled cells MUST be (style, text) fragments,
  never embedded escape codes.
- **Entry-point interactivity:** bare `sciqnt config` / `config set` check
  `sq_tui._streams_interactive()` and print the `show` dump when piped —
  never a menu loop into a pipe. `config show` is the stable script/agent
  surface; `config set KEY VALUE` the script write path.

## Tests
`core/tests/test_config.py` (schema/defaults/materialise/validation),
`core/tests/test_config_ui.py` (settings-screen rows/help/edit loop + the
CLI entry points, select_screen mocked — no terminal needed), and
`core/tests/test_performance_settings.py` (the rendering-boundary resolvers).
