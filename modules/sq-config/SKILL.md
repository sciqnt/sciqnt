---
name: sq-config
description: Show or change sciqnt's user-level settings (display currency, cost-basis method, performance-return method, …) stored in one local JSON file. Use when the user wants to see or change how sciqnt displays or computes things.
---

# sq-config — user-config unit

An **infra** unit (outside the source/compute/action triad — see manifest.yaml). The engine lives in `core/sq_config/` (schema registry + read/write API); this bundle is the CLI surface. Local file only — no network, no credentials.

## When to use
The user asks to see or change a sciqnt setting: display currency, cost-basis method (FIFO/LIFO/AVG), performance-return method, sub-year annualisation, benchmark, preferred agent. All settings live in **one** user-owned JSON file: `~/.config/sciqnt/config.json` (`SQ_CONFIG_PATH` overrides for tests/CI).

## How to use
```bash
bin/sq-config                  # interactive full-screen settings screen (bare == set)
bin/sq-config set              # the same screen
bin/sq-config set KEY VALUE    # non-interactive validated write (scripts/agents)
bin/sq-config show             # plain dump — the script/agent-facing surface
```
Or via the dispatcher: `sciqnt config` / `sciqnt config set [KEY VALUE]` / `sciqnt config show`.
Agents and pipes should use `show` + `set KEY VALUE`; bare/`set` auto-degrade to the dump when the streams aren't a TTY.
Programmatic reads go through `sq_config.get(key, default)` or convenience accessors (`sq_config.display_currency()`); bundles MUST NOT hardcode defaults that should be user-controllable.

## How it behaves
- One `SCHEMA` list is the single source of truth (key, type, allowed values, default, help, consuming engine); the file is auto-materialised documented on first run.
- **Wired settings** (an engine honours them): `display_currency`, `cost_basis_method`, `performance_return_method`, `annualize_sub_year_returns`, `preferred_agent`.
- **Declared but NOT yet honoured** (`mvp=False`, shown as "soon"): `fees_in_cost_basis`, `tax_jurisdiction`, `tax_year_start` — no engine consumes them yet (honest gap, declared in FINDINGS).
- Writes are atomic (tmp + `os.replace`); a corrupt file degrades to schema defaults rather than raising; unknown keys pass through unvalidated; bools accept true/1/yes/on etc.

## Adding a setting
One entry in the core `SCHEMA` (`core/sq_config/__init__.py`), plus a convenience accessor in `core/sq_config/`. The settings screen, the dump, and validation all derive from the schema — nothing else to update. Consuming engines never import `sq_config` directly — resolution happens at the adapter/rendering boundary (config-free core).

## Caveats & quirks
**Read `FINDINGS.md`** — the living log (settings status, atomic-write behaviour, forward-compat rules). Update it whenever you learn something new.
