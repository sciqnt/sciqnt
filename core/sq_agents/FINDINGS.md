# sq_agents — findings (living quirks log)

- **Never script Terminal over AppleEvents.** `osascript -e 'tell app "Terminal" to do script …'` wedges with `AppleEvent timed out (-1712)` on this host. The new-window path instead writes a `.command` launch script and opens it via LaunchServices (`open -a Terminal|iTerm`) — no AppleEvents at all (2026-06-02).
- **The `new_window` path is currently test-only / unreachable from the UI.** The TUI deliberately launches agents INLINE as a sub-session (inherits PATH/env — a GUI-spawned login shell often lacked `claude` on PATH, which is why new-window "didn't work"). Kept as a tested opt-in library option; don't remove without deciding the UX again.
- **Detection is on-demand** — `detect()` runs `shutil.which` per call, so installing/uninstalling an agent after sciqnt is reflected immediately. Never cache it.
- **Resolution order**: explicit arg → config `preferred_agent` (if a real installed name) → first detected. The TUI toggle additionally orders by recency: `recent_installed()` (MRU file `agent_recency.json` next to config.json; `mark_used()` bumps; uninstalled drop out; best-effort writes never break a launch).
- **Launch is shell-free** (`subprocess.run(argv)` list-args) — prompts can't inject. Pass NON-SECRET context only; the full instruction also lands in `.sciqnt-agent-task.md` in the cwd so even un-seedable agents work (gitignored at repo root).
- Config env var is `SQ_CONFIG_PATH` (post-rebrand) — a test isolating via the old `PZ_CONFIG_PATH` silently reads the REAL user config (bit us 2026-06-02).
