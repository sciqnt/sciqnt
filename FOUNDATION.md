# sciqnt — Foundation

*The apex document. The worldview and the one structural idea everything else falls out of. `PRINCIPLES.md` is how these cash out operationally; `research/` is the grounding.*

## Thesis

> Financial intelligence, decomposed into small, deterministic, self-describing units that any AI agent can compose — owned and run by the individual.

The age of AI changes what one person can do. An individual with an agent should be able to do what used to require an institution: connect every account, hold a correct unified picture of their financial reality, reason over it, and act — without surrendering custody of their data, their keys, or their judgment. sciqnt exists to make that the default.

## The one realization

A broker connector, a market-data feed, a P&L calculator, a tax-lot engine, an FX converter, an order executor are **not different kinds of things.** They are **one primitive in three roles.** Every component is a *unit* of the same shape:

- declares its **capabilities** against a thin shared contract,
- has a **deterministic core**,
- is **text/CLI-first**,
- **runs locally**,
- is **capability-gated** and **conformance-tested**,
- works in **any host**.

What differs is only direction:

| Role | Direction | Examples |
|---|---|---|
| **Source** | data **in** | brokers (positions/transactions), market & reference data (quotes, fundamentals, FX, corporate actions), news/filings |
| **Compute** | **transform** (pure function over the ledger) | P&L (realized/unrealized, multi-currency, FIFO/LIFO/average), performance attribution, risk, tax, FX, backtesting |
| **Action** | data/intent **out** | place/cancel orders, rebalancing, transfers — the higher trust tier |

A P&L calculator is just a compute unit; FIFO-vs-LIFO is just a swappable one. Once components share one shape, the AI's job is simply to **compose units it was never individually taught.**

## The ecosystem at altitude

```
            ┌──────────────────────────────────────┐
            │  AGENT HOST  (Claude Code/Codex/…)     │  the conductor — reasons,
            │  composes units · explains · self-heals│  composes, repairs. NOT a unit.
            └───────────────────┬────────────────────┘
                                │  speaks only the contract
   UNITS — one shape, three roles:
        SOURCES  ─►   ┌──────────────┐  ─►  COMPUTES  ─►  ACTIONS
        data in       │  THE LEDGER  │      transform      out to world
        brokers,      │  canonical,  │      P&L · risk ·   orders,
        market data,  │  point-in-   │      tax · FX ·     rebalance,
        news/filings  │  time schema │      attribution    transfers
                      └──────────────┘
   SUBSTRATE — the thin "platform" (all we actually own & ship):
     thin contract · policy/permission gate · conformance harness ·
     generator subagent · registry (optional) · provenance/identity
```

The ledger is the only center. The substrate is small and stable. The value lives in the units — and the units are mostly built by the ecosystem, not by us.

## The Founding Articles

*Thirteen principles that hold across every component, meant to outlast any tool or protocol.*

1. **Sovereignty.** The individual owns their financial reality — their data and keys are theirs, exportable, never held hostage. The test: *you can fire us and keep everything.* Local-first is the default and strongest expression; a cloud option is legitimate only where the user still owns and controls the data. We are custodians of nothing the user can't take back.
2. **One primitive, three roles.** Everything is a unit of the same shape — source, compute, or action. Same model, different direction.
3. **A thin shared language is the only center.** Every unit speaks one canonical, point-in-time schema and a small verb set — and agrees on nothing else. Coherence through minimalism.
4. **Deterministic where it counts; intelligent where it helps.** Code computes truth and acts; the AI composes, reasons, explains, repairs. The boundary is sacred — the model never does the math or holds the truth.
5. **Truth is temporal and append-only.** Never overwrite. Record what was true and when it was known. History is honest or it is worthless.
6. **Capabilities are declared, granted, and enforced in code.** No unit acts beyond what the user explicitly allowed. Consent is granular; enforcement is a deterministic gate — never prose, never the model's discretion.
7. **Trust is earned, never assumed.** Conformance over claims, provenance over reputation, correct-to-the-cent over plausible. Action is a higher tier than knowledge.
8. **Modular and host-agnostic.** Every unit stands alone and runs in any host. No in-house runtime, no central server, no required app. Rent every interface; own only the substrate.
9. **Value before ambition.** Prove value, dogfood it, contribute to what already exists, and build the simplest thing that delivers it — before building anything new. The less ambitious path is often the more valuable one. Usefulness over empire. (This is about restraint of *scope*, not timidity.)
10. **Convenience is a feature, not a luxury.** The sovereign, correct, and safe path must also be the *effortless* one — it should *just work*, with the fewest steps, wherever the user already is. Convenience of use is not simplicity of build; we optimize the user's effort, not our own. Yet convenience is the most dangerous principle — "it's more convenient" is the oldest excuse for taking custody, acting without asking, and locking people in — so it never overrides sovereignty, correctness, or consent: where they tension, we engineer until safe and effortless are the *same* path, and accept friction only when they truly cannot be. (It is also what makes dogfooding real: a tool nobody enjoys using teaches you nothing.)
11. **Trust the model; resist over-engineering.** Capability in the age of AI comes from a capable agent wielding simple, general primitives — not from sophisticated machinery built around it. An agent with `grep` beats a bespoke RAG; a CLI beats a framework. Every abstraction must beat the question *"could the agent just do this with a simple tool?"* — but reach for real engineering wherever determinism and correctness demand it (the money math). The lesson governs the probabilistic edge, never the deterministic core.
12. **The ecosystem grows and heals itself.** We ship the contract, the harness, and the generator — not the long tail. AI lets users build the unsupported and lets units repair themselves. Generative and antifragile by design.
13. **Self-reflection — keep the work honest against these articles.** Nothing is "done" until it has been re-evaluated against this constitution: does the solution actually hold each principle, and where does it fall short? Name the gaps out loud rather than hide them — a solution that quietly violates a top principle is a draft, not a finish. This is the loop (alongside conformance for units) that keeps all the other principles in check.

## What this is, and isn't

It **is** a contract, a conformance harness, a generator, and a worldview — a way to decompose all of finance into units an individual's agent can own and compose.

It **is not** an app, a chatbot, a hosted runtime, a data reseller, or a black box that promises alpha. We don't hold your data, we don't do your math in a language model, and we don't ask you to trust claims we can't prove.

---
Operational detail: `PRINCIPLES.md` (18 operating principles). Connector design: `research/connector-framework.md`. Full reasoning + grounding: `research/synthesis.md` and `research/01..05`.
