# sciqnt — maintenance conformance report

**Date:** 2026-06-11 (heavy pass) · **Baseline:** `e60fde9`, 623 tests green ·
**Reviewers:** 4 independent subagents — core-constitution, modules-constitution,
TUI/UX (research/tui-experience.md), adversarial money-path (with live repros).

**Totals across reviewers: CRITICAL 2 · HIGH 7 · MEDIUM ~24 · LOW ~38.**
This was a `--fix` pass: money-core fixes applied by the lead session with
repro tests (the skill's never-auto-edit rule honoured — each was hand-reviewed,
test-pinned, and verified against live data); SAFE fixes applied in batches.

Status legend: ✅ fixed (`44ea283`) · 🔧 fixed in the follow-up batch commits ·
📋 report-only (deliberate, with rationale).

## CRITICAL — wrong money on screen (both REAL in production)

1. ✅ `fold._apply_split` doubled realised fees across a split
   (`fee_per_unit_local` never rescaled with quantity). Repro-pinned.
2. ✅ MTM overlay ignored `Price.currency`: a pence-book LSE holding
   (listing GBX, provider price normalised to GBP) was valued via a
   per-penny FX on a per-pound price — **100× under**. Live impact
   confirmed: the owner's 2021-22 Premier Oil/Harbour samples were
   mis-valued — the "30.2% max drawdown (2021)" headline was an
   artifact; the corrected series shows 9.3%, TWR −2.66% → −0.39%/yr.
   The overlay now works in the price's currency, reconciles
   pence↔pounds explicitly (×100), and REFUSES any other unit mismatch
   (pass-through beats silently wrong money).

## HIGH

3. ✅ TWR performance break never re-linked when re-funded capital was
   below 0.5% of the FORMER era's peak → a confident-looking 0.00%.
   Running peak re-anchors on re-link; absolute floor stops a window
   opening on a tiny negative residue reading as corrupt; annualising
   a ≥100% loss returns None instead of raising.
4. ✅ Exposure tables silently summed mixed currencies (the
   `base_currency` param was dead code). `aggregate_*_exposure` now
   FX-converts every money field to the display currency; unconvertible
   brokers are excluded AND reported; tables label the currency.
5. ✅ Flows tab raw-summed foreign-ccy dividends/fees into a base-ccy
   titled column (deposits on the same rows WERE filtered).
6. 🔧 `--once`/piped routing: tabbed_view keyed the dump off stdin only —
   `sciqnt --once` at a TTY opened the interactive app; `--once | head`
   wrote alt-screen ANSI into the pipe. Explicit `interactive=` param,
   two-stream auto-detect.
7. 🔧 No scrolling in the full-screen views — content below the fold was
   unreachable (positions/flows/history tabs on small terminals).
8. 🔧 The platform-contract test guarded only 2 of 13 bundles; the other
   11 could break `--describe/--commands` invisibly.
9. 🔧 Keyed providers (Tiingo/Finnhub) swallowed 401/403: a REJECTED key
   was indistinguishable from keyless-inert. One stderr line, once per
   process.
10. 🔧 sq-kalshi / sq-polymarket / sq-config had no SKILL.md; sq-yahoo's
    manifest + SKILL described the pre-archive bundle (no fetch_chart,
    no archive write-through/fallback).

## MEDIUM (all ✅/🔧; selected)

- ✅ `income_summary` double-counted a FEE row that also carried
  `t.fee` (now parity-pinned with `fee_history`); unconverted flows
  keyed per (stream, ccy) so a +$100 dividend and a −$100 fee can't
  net to an invisible zero.
- ✅ Incomplete-export detector counted only position P/L as
  "explained" — an income-funded withdrawal warned falsely; dividends +
  interest now count.
- ✅ Degiro 16-column trade rows (no order-id columns) parse instead of
  being silently dropped (money columns end at 15).
- ✅ Drawdown gated on a measured index (all-breaks series printed a
  confident 0.0% next to an honest "—" TWR); benchmark guards p1 > 0.
- 🔧 Live broker TUIs colour P/L via `pnl()` (were plain); fmt helpers
  hoisted to sq_tui (5 hand-copies); yellow-⚠ severity applied to the
  user-fixable history/export warnings (were dim, inverting the
  convention); FIRDS names whitespace-stripped before entering the
  canonical layer; drawdown date-lines demoted to the `?` overlay
  (reference, not action); `clear_screen()` replaces the raw escape in
  home; `display_currency` default unified to the schema (call-site
  fallbacks removed); Yahoo archive fallback no longer claims coverage
  through today (staleness budget; a months-old close can't silently
  mark today's portfolio); Tiingo token moved to the Authorization
  header; manifests/dependency claims corrected (BRK-B, degiro sync,
  stdlib-only honesty); **personal data anonymised** (owner's account
  names in test fixtures/comments, real ledger figures in FINDINGS) —
  required before this repo ever gets a remote.

## Formerly report-only — closed in the final pass (`/goal fix everything`)

- ✅ **`except TypeError` kwarg-fallback dance — REFACTORED.**
  `_accepts_kwarg` (signature probe) + `_call_with_account` /
  `_get_rate_at` replace every call-and-retry site in the platform
  (snapshot, load_history, snapshots_at, get_rate). A genuine internal
  TypeError now PROPAGATES instead of misrouting to the no-account call
  path — pinned by `test_capability_probe.py` (the wrong-account
  scenario asserts no bare retry). The guarded retry survives only for
  uninspectable callables, inside the probe itself.
- ✅ **Blanket `except Exception` around the TWR/benchmark build —
  SURFACED.** The failure class is captured per broker
  (`series_error`, also fed by a raising `load_history`) and rendered
  as a yellow ⚠ warning ("performance series failed (…) — ^R to
  retry") instead of an unexplained dash.
- ✅ **FIRDS CFI rows I/J — REMOVED, not guessed.** ISO 10962 (2015)
  has J = Forwards and no I category; the unverified mappings are gone
  and such instruments honestly stay `AssetClass.OTHER`. FINDINGS
  updated to the removal decision.
- ✅ **`sq_secrets` `sys.exit` — VERIFIED + DECIDED.** All five sites
  live in `prompt_and_store`, which is only ever invoked from
  `setup_creds.py` SUBPROCESS entry points — CLI-boundary exits that
  can never kill the dispatcher. Decision + the in-process escape
  hatch (`SetupCancelled`) recorded in sq_secrets FINDINGS. The
  broader package-breadth observation stands as accepted architecture.

## 📋 Standing decisions (not defects; revisit with cause)

- **Provider chains hard-coded in the app layer** (price, news,
  metadata-resolver rungs): documented P11 composition; a declarative
  rung registry becomes worth it when third-party rungs exist.
- **`_ChainNews` vs `ChainProvider`:** different semantics
  (first-non-empty vs first-non-None) in justified homes; unifying now
  is machinery for its own sake — revisit when a third chain appears.
- **`sq_secrets` breadth / sq-config architectural deviations** —
  declared in their FINDINGS.

## What checked out clean (worth knowing)

- Decimal discipline: no unsanctioned floats in any money path (the two
  sanctioned float sites are the XIRR solver power + TWR annualisation,
  both boundary-quantised). `_to_money` 8dp quantisation consistent.
- No bundle-to-bundle imports anywhere; dialect containment clean; all
  13 bin wrappers answer the contract; conformance gate wired in front
  of aggregation; `.gitignore` covers data/secrets/artifacts.
- NO_COLOR honoured everywhere incl. all of today's new surfaces;
  zero questionary imports outside sq_tui; one raw escape (fixed).

## Verification

- Pre-fix: 623 green at `e60fde9`. Money batch: green at `44ea283`
  (+13 regression tests, live re-render verified the corrected
  headline). SAFE batches: green at `b4bca76` — **660 tests** total
  (+37 over the audit), live smoke render verified (corrected
  drawdown/TWR, currency-labelled exposure, new warning severities,
  dump routing).
- Remaining personal-data note: `STATE.md` (the machine-local handoff)
  deliberately keeps real account labels and live P/L figures — that
  is its job. It must be rewritten/excluded if the repo ever gets a
  public remote; everything else is anonymised.
