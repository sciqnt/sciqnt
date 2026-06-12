# Config settings for a cross-asset portfolio / tax / performance tool

**Status:** research synthesis, 2026-06-01. Grounds the `sq_config` schema
(`core/sq_config/__init__.py`). Salvaged + synthesised from a 30-agent deep-
research fan-out (primary sources: IRS, HMRC, GOV.UK, CFA Institute GIPS; tool
docs: Sharesight, Portfolio Performance, Ghostfolio, Koinly/CoinTracker, Fidelity).
The automated synthesis step wedged on hung web-fetches; this report is hand-
synthesised from the per-source extractions, which completed and were rated for
provenance.

> Why this doc exists: the user asked "tie up config settings that will be
> useful in the future — fifo vs lifo vs bep, and there's so many others." This
> is the durable design record behind which settings `sq_config` declares, what
> their defaults are, and *why a single global default is often wrong*.

---

## The load-bearing finding

**Cost-basis method and tax behaviour are jurisdiction- and asset-class-specific
— a single global default is wrong.** Every serious tool either (a) bundles
jurisdiction + currency + tax rules into one foundational, often *immutable*
setting (Sharesight fixes tax-residency at portfolio creation), or (b) cascades
the cost-basis default from the country (Koinly: UK→Share Pooling, Canada→ACB,
US→FIFO/HIFO/spec-ID, AU→FIFO/ACB).

Corollary for sciqnt: `tax_jurisdiction` is the anchor; cost-basis method,
tax-year boundaries, CGT allowance and wash-sale handling should *derive* from
it, overridable per asset class. We declare the anchor now; the cascade engine
is a documented future, not built yet (resist over-engineering).

The second load-bearing finding: **Portfolio Performance's design split** —
treat *display/locale/FX-quotation* as global config, but keep *performance
methodology and cost basis* as report-level / transaction-level concerns rather
than a single global default. sciqnt follows the same instinct: the genuinely
global knobs are MVP; methodology knobs are declared but flagged not-yet-wired.

---

## 1. Cost basis / lot accounting

| Jurisdiction | Default method | Notes |
|---|---|---|
| **US (IRS)** | **FIFO** | Only FIFO + **Specific Identification** are IRS-sanctioned. **HIFO/LIFO are *not* standalone IRS methods** — they are lot-selection *strategies inside* Spec-ID. Spec-ID must be elected **at time of sale** (point-in-time constraint). Long-term threshold > 1 year. |
| **UK (HMRC)** | **Section 104 pool** | *Not a simple enum value.* A 3-stage matching algorithm applied in strict order: **same-day rule** (TCGA92/S105(1)) → **30-day "bed-and-breakfast" rule** (TCGA92/S106A) → **Section 104 pooled weighted-average**. Applies to **crypto and equities** alike (CG51560, CRYPTO22256). |
| **Canada (CRA)** | **ACB** (adjusted cost base, averaging) | Mandated. |
| **Australia** | FIFO / ACB | |
| **Ireland / most EU** | FIFO | |

- **Fidelity (US brokerage)**: defaults are **asset-class-specific** — Average
  Cost *mandatory* for mutual funds, FIFO for stocks/bonds. Exposes only
  {Average Cost, FIFO, Specific Shares} — **no LIFO/HIFO**.
- **Crypto-tax tools**: Koinly/CoinTracker expose {FIFO, LIFO, HIFO, ACB, Share
  Pool}; **CoinTracker's default is HIFO** (a *vendor* default ≠ legal default).
- **"BEP" (break-even price)**: Degiro's third method. It belongs to the
  **average-cost / ACB / Section 104-pool family** — a single pooled weighted-
  average cost per instrument. For sciqnt, **`AVG` is the engine equivalent of
  BEP** (both collapse lots to one weighted-average lot before matching).
- **Recent rule change to NOT hardcode**: US crypto historically *property* and
  exempt from the 30-day wash-sale rule; the One Big Beautiful Bill Act extends
  wash-sale to digital assets **from 2026** with dealer/stablecoin carve-outs.
  → wash-sale must be per-jurisdiction, per-asset-class, **date-effective**.
- **2025+ crypto**: pre-trade lot identification required (no retroactive
  selection); methods apply **per-wallet/account**, not per-asset.

**sciqnt today:** the engine (`sq_compute`) implements **FIFO / LIFO / AVG**.
AVG covers the average-cost / ACB / Section 104-pool / Degiro-BEP family.
**Honest gaps (not implemented):** HIFO & true Specific-ID; the UK same-day +
30-day matching algorithm (we approximate UK with `AVG` = the pool only, *without*
the same-day/B&B pre-steps). Documented; not silently wrong.

→ Schema: `cost_basis_method` ∈ {FIFO, LIFO, AVG}, default **FIFO**. **WIRED.**

## 2. Tax / jurisdiction

- **Tax year (personal ≠ government/corporate):** US calendar, **UK 6 Apr–5 Apr**,
  **AU 1 Jul–30 Jun**, Canada/Ireland/most EU calendar. Sharesight models this
  as an end-of-year *month* dropdown. → `tax_year_start` (MM-DD), jurisdiction-
  specific.
- **US holding period:** > 1 year = long-term; LTCG 0/15/20% vs ordinary;
  $3,000/$1,500 annual net-capital-loss deduction + carryforward (IRS Topic 409).
- **UK CGT annual exemption:** **£3,000** (2024/25 onward — down sharply from
  £12,300 in 2021/22); rates 18%/24%, which *changed mid-tax-year* in 2024/25.
  → must be **per-jurisdiction, per-tax-year** and point-in-time-correct.
- **Wash sale:** US ±30 days (61-day window), IRC §1091, basis-adjustment
  deferral. UK analog = the 30-day bed-and-breakfast rule, but it **adjusts cost
  basis** rather than disallowing the loss.

→ Schema: `tax_jurisdiction` ∈ {US, UK, CA, AU, IE, EU, OTHER}, default OTHER;
`tax_year_start` default "01-01". **Declared, not yet wired** (no tax engine).

## 3. Performance methodology

- **GIPS (CFA Institute, 2020):** **TWR is the primary/default** headline return
  (strips client-driven cash flows → manager-skill comparison); **MWR/IRR only
  under specified conditions** (closed-end/illiquid, or control of cash flows),
  and when used must be annualised since-inception through the most recent
  year-end.
- **But a personal tool can defensibly default to money-weighted:** Sharesight's
  headline is **money-weighted (Modified Dietz variation)** with *no* user
  choice. Kitces: "no right choice" — serious tools expose **both**.
- **Annualisation:** **never annualise sub-1-year returns** (GIPS I.5.A.4 —
  geometric/compound, not arithmetic); annualise only ≥ 1 year. Day-count
  ACT/365 in `R_ann = (1+R)^(365/d) − 1` (The Spaulding Group).
- **Benchmarks** must be total-return (price-only prohibited). **Risk-free rate**
  feeds Sharpe/Sortino (Ghostfolio/PP expose it).

**sciqnt today:** computes **both TWR and money-weighted XIRR** (+ drawdown). No
Sharpe/Sortino yet (so no `risk_free_rate` consumer → not added — would be a slot
no module reads).

→ Schema: `performance_return_method` ∈ {TWR, MWR}, default **TWR**;
`annualize_sub_year_returns` bool default **false** (GIPS). **Both WIRED** (since
2026-06) at the rendering boundary in `sq_platform.aggregated` — the pure
performance core stays config-free:

- `performance_return_method` **flags the headline** in the per-broker summary:
  the chosen return's column header carries a `▸` marker and a footnote names it
  + how to switch. Both figures stay visible — selecting a headline never hides
  the other (show-the-work ethos). There is no *single* portfolio-level return
  yet (XIRR/TWR over mixed brokers + currencies isn't well-defined), so the flag
  lands per-broker — that's the honest unit it can apply to today.
- `annualize_sub_year_returns` **gates TWR annualisation**: a broker whose
  sampled span is < 365 days shows its *cumulative period* TWR (not annualised),
  marked `†` with a footnote, unless the user opts in. This **fixes a real
  GIPS-default violation** — the engine previously always annualised, inflating
  short-period returns. **Honest gap:** XIRR is annualised *by construction* (the
  solver finds an annual rate); we don't de-annualise it for sub-year spans, so
  the guard applies to TWR only.

## 4. Dividends / income

- **Gross vs net of withholding** — jurisdiction-specific; Sharesight decomposes
  return into capital / dividend / currency components.
- **DRIP:** mature open tools (**Ghostfolio**) have **no first-class DRIP toggle**
  — reinvestment is modeled by *activity composition* (a DIVIDEND + a BUY priced
  at the per-share value received). Useful signal: DRIP may be data, not a knob.
- Accrual vs cash basis.

→ Not added to the schema yet (no dividend-tax engine; DRIP is activity-level).
Documented as a future area. Avoids declaring knobs nothing reads.

## 5. FX

- **Source/provider** (sciqnt: ECB + stablecoin peg). Sharesight uses an intraday
  rate (5-min refresh).
- **Conversion timing:** transaction-date vs settlement-date vs daily-close.
- **Quotation:** PP exposes a direct/indirect FX-quotation toggle as a global pref.
- Triangulation base currency.

→ Future. sciqnt's FX is currently transaction-date via the canonical txn fx.
A `fx_rate_source` / `fx_conversion_timing` pair is the natural next addition.

## 6. Display / locale

- base/display currency, locale, number/date format, timezone, decimal precision.
- PP concretely exposes: `share_count_precision` (default 1), `quote_precision`
  (default 2), `always_show_currency_code`, `locale`/`country`,
  `fx_quotation_direct_indirect`, `trading_calendar`.

→ Schema: `display_currency` is **WIRED** (MVP). Precision/locale/timezone are
natural near-term additions (the TUI currently hardcodes 2dp); declared as future.

## 7. Fees

- **Sharesight default: brokerage is capitalised into the cost base** (fees-in-
  basis = yes). sciqnt's `fold_position` is **already fees-complete** (realised
  P&L = product + currency + fees), matching this default.

→ Schema: `fees_in_cost_basis` bool default **true** (reflects current engine
behaviour; a toggle to *expense* fees instead is declared, not yet wired).

---

## What we changed in code (this round)

`sq_config` now has a **schema registry** + **auto-materialise** (config.json is
written with documented defaults on first run). Seeded with `display_currency`
and `cost_basis_method`; this round adds the grounded forward-looking settings
above with an `mvp` flag distinguishing **wired** from **declared-but-not-yet-
honoured**. `cost_basis_method` is **wired** through to `sq_compute.fold_position`
at the adapter boundary (pure core stays config-free).

## Honest gaps / disagreements flagged

- **HIFO / Specific-ID / UK same-day+30-day matching** not implemented; `AVG`
  approximates the pooled-average families (ACB / S.104 pool / Degiro BEP).
- **TWR vs MWR default**: GIPS says TWR (institutional); Sharesight ships MWR
  (retail). We default **TWR**; the selector now flags the headline per-broker
  (no single portfolio-level return exists yet — see §3).
- **Sub-year annualisation guard is TWR-only**: XIRR is annualised by
  construction; we don't de-annualise it for sub-year spans (§3).
- **Wash-sale for US crypto** changed effective 2026 — any future wash-sale
  setting must be date-effective, not a static boolean.
- **CGT allowances/rates** change between (and within) tax years — must be
  point-in-time data, never hardcoded constants.
- Several crypto-tool URLs 403'd and the browser fallback occasionally resolved
  to a competitor's page; vendor-default claims (e.g. CoinTracker HIFO default)
  are corroborated across ≥2 extractions but are vendor blogs, not primary law.
