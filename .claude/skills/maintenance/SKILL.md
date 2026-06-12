---
name: maintenance
description: Audit the sciqnt codebase against its own constitution (FOUNDATION.md + PRINCIPLES.md) and emit a ranked conformance report. Propose-only by default; opt-in --fix applies SAFE findings only and NEVER auto-edits the deterministic money-core. Use to catch principle drift — mislocated/cross-cutting code, hardcoded or stale values, missing/outdated FINDINGS or manifests, secret/data hygiene, docs-vs-code drift.
---

# maintenance — principle-conformance audit & cleanup

Operationalizes **self-reflection (principle 18)** and **conformance (principle 17)** as a repeatable pass, so drift is caught systematically rather than ad-hoc. The constitution IS the spec — this reads `FOUNDATION.md` + `PRINCIPLES.md` and the repo; nothing separate to maintain.

## When to run
Before a milestone/commit/publish, or whenever the codebase has grown and you want a deep clean. Complements (does not replace) in-the-moment self-reflection.

## How it runs
Spawn a **fresh subagent** (independent reviewer, not the building session) — `general-purpose`. For a large repo, fan out one reviewer per module via a workflow; for the current size, a single pass is enough. The subagent reads the principles + the repo, audits, and writes a ranked report. It does **not** modify code unless `--fix` is passed.

## The checklist (the teeth) — for each unit in `modules/*`, `core/`, `examples/`
Check against the constitution, flag violations with `file:line`, the **principle # violated**, severity, and a concrete proposed fix:

1. **Modularity / placement (P8, P11):** generic/cross-cutting code living inside one specific unit (e.g. the credential-handling that was wrongly in sq-degiro); units importing each other (composition belongs in the app layer); a unit doing more than its one job.
2. **Determinism boundary (P4):** money/quantity math that isn't deterministic code; `float` used for money instead of `Decimal`; any path where the LLM would compute or hold a number.
3. **Stale / hardcoded values (P3, P4):** hardcoded constants that should be live or derived (e.g. a stale unrealized figure; a hardcoded ticker/venue/position). Flag anything that can silently go wrong.
4. **Text/CLI-first & flavour (P5, P9):** browser/GUI used where text/API/CSV exists; flavour not declared in the manifest.
5. **Living FINDINGS (mandatory):** every unit has a current `FINDINGS.md`; discovered quirks/conformance results are recorded there, not lost.
6. **Manifest accuracy (P9):** `manifest.yaml` present and its declared capabilities/flavours/risk match the actual code.
7. **Sovereignty / secret & data hygiene (P13, P15):** no real personal data or secrets tracked in git; `.gitignore` covers `data/`, `.env`, `.venv/`; creds only via the shared `core/sq_secrets` substrate.
8. **Honest gaps & status (P18):** each unit's declared `status` matches reality; open FINDINGS TODOs surfaced; no overclaiming "done".
9. **Drift & cruft:** docs-vs-code mismatch; dead code; unused imports; conformance results that no longer hold (re-run the documented checks where cheap).
10. **TUI experience (P5 "TUI is king"):** the interactive surface must follow `research/tui-experience.md`. Flag: chrome (logo/header/banner) **re-printed per navigation** instead of drawn once in a persistent frame; **manual blank-line spacing** (`print()` / `"\n"` used to position things); **dump-and-scroll menus** that append into scrollback instead of an in-place full-screen layout; **inconsistent keybindings** or a missing footer hint / `?` help (the keymap is `Esc` back/quit, `?` help, `/` filter, `^R` refresh, arrows+`j/k` move); `NO_COLOR` not honoured; or no line-based fallback kept for non-TTY / piped / accessibility. The deterministic line-dump path (`run_aggregated`, `--once`) is the accessible surface and must stay.

## Policy — propose vs fix
- **Default = propose only.** Produce the report; change nothing.
- **`--fix` (opt-in) applies SAFE findings only:** docs/FINDINGS/manifest updates, moving mislocated generic code, removing dead code/unused imports, wiring an obviously-stale constant to its live source *when the wiring is mechanical and the result is verified*. Always show diffs.
- **NEVER auto-edit the deterministic money-core** (P&L math, cost-basis, reconciliation logic). Those are reported for human review only — a wrong "fix" there silently corrupts a number.

## Tests gate — fixes MUST keep tests green (principle 17)
- **Before `--fix`:** run `./run_tests.sh` from the repo root and record the pre-fix result (all units' conformance suites). If anything is red *before*, fix that first or stop — never paper over a pre-existing failure.
- **After every `--fix` batch:** re-run `./run_tests.sh`. If it goes red, **revert the batch** and report which fix broke which test (don't try to patch on top — investigate the failure).
- A fix is only considered *applied* if (a) pre-tests were green, (b) post-tests are green, and (c) the diff was shown. Otherwise it stays as a *proposal* in the report.
- For findings the suite doesn't yet cover (e.g. live broker connection), the report flags "no test backing — manual verification required" and never auto-fixes.

## Output
- Write a ranked report to `maintenance/reports/REPORT.md` (overwrite) — grouped by severity, each item: principle #, `file:line`, what & why, proposed fix, and whether `--fix` is allowed to touch it.
- Record durable findings into the relevant unit's `FINDINGS.md` (per the document-findings principle) so knowledge accretes in the repo, not the chat.
- Return a concise summary (counts by severity + the top items).
