# sciqnt — Principles

The constitution. These hold across the board and are meant to survive tool/protocol churn. When a decision is unclear, decide in the direction of these. Changing one should be deliberate and rare.

## I. Value & process
1. **Value-first, not gap-racing.** Prove value before building. Contributing to / extending existing tools (OpenBB, ccxt, Ghostfolio…) is a first-class outcome, not a fallback. Let the measured *shortfall* of what already exists, against a real need, define the only gap worth building.
2. **Dogfood is the spec.** Build for user-zero's real use. If no one is actually using it, it isn't a feature. Real need over guessed need.
3. **Simplest thing that works, built up incrementally.** Start with the smallest robust unit; add surfaces and complexity only when earned. **Trust a capable agent with simple, general primitives over bespoke machinery — an agent with `grep` beats a bespoke RAG; a CLI beats a framework.** Every abstraction must beat *"could the agent just do this with a simple tool?"* Reach for heavy engineering only where determinism/correctness demand it (the money math — see principle 5); the lesson governs the probabilistic edge, never the deterministic core. No speculative architecture, no building for hypothetical futures.
4. **Convenience is a feature, not a luxury.** The sovereign, correct, safe path must *also* be the effortless one — it should just work, with the fewest manual steps, wherever the user already is. Convenience of *use* is not simplicity of *build*; optimize the user's effort, not the builder's. But convenience is the most dangerous principle — "it's more convenient" is the oldest excuse for taking custody, acting without asking, and locking people in — so it never overrides sovereignty, correctness, or consent: where they tension, engineer until safe and effortless are the *same* path, and accept friction only when they truly can't be. (It's also what makes dogfooding real — a tool nobody enjoys using teaches you nothing.)

## II. The AI / compute boundary
5. **Deterministic core, probabilistic edge.** Code computes the numbers and places the orders; the LLM plans and explains. The model never does the money math — a single wrong figure destroys trust permanently.
6. **Text/CLI-first — TUI is king.** Prefer text, programmatic, scriptable surfaces: token-efficient, deterministic, composable, testable, version-controllable. GUI/browser-driving is a last-resort flavour, never the default.
7. **The LLM orchestrates and self-heals; it is never the runtime.** Its job is deciding *when*, handling messy edges, and regenerating broken connectors — not being the engine that does the work.

## III. Contract & flexibility
8. **Thin stable contract, unbounded ecosystem.** Own a small, slow-changing interface (the verbs + the canonical schema); everything else is a pluggable implementation. (The LSP / Terraform-provider lesson.)
9. **The typed core is the contract; protocols are adapters.** MCP, Skills, A2A, code-execution are swappable wrappers over the same core. Never couple to one agent vendor's surface.
10. **Flexibility over prescription.** Support many connector flavours — programmatic API → file/CSV → CLI → browser (last resort) — behind one interface. Capabilities and flavour are *declared* by the connector, never assumed or hard-wired by the platform.
11. **Modular & host-agnostic.** Every unit stands alone — a single connector, the schema library, the compute — usable without the rest; composition is opt-in. And the whole ecosystem rides *any* agent host (Claude Code, Codex, OpenClaw, …): no in-house runtime, just as there is no in-house chat. The core is host-neutral (plain scripts + manifest + SKILL.md, runnable anywhere); each host gets only a thin adapter generated from the same manifest. Nothing requires a central server — even the registry is optional. (This is only safe *because* the contract is thin — principle 8 is its partner.)

## IV. Data
12. **Own the data layer, rent the interface.** Apps and chatbots churn; a correct, unified, point-in-time financial ledger compounds. As agents proliferate, the scarce thing is correct unified financial state + the connectors to reach it.
13. **Append-only & bitemporal from day one.** Valid-time + knowledge-time on every fact; positions derived from an immutable event log; temporal universe/membership tables. This is the one decision you cannot retrofit. Point-in-time correctness is non-negotiable for anything quant.
14. **Borrow, don't invent (schema).** Mine FIBO/CDM/FIX/ISO-20022/beancount for concepts, enums, and identifiers (FIGI spine, CFI classification). Never adopt their heavyweight machinery (OWL reasoners, Rune DSL).

## V. Trust & security
15. **Sovereignty — the user owns the data; local-first by default.** The data and keys are the user's: exportable, portable, never held hostage — *you can fire us and keep everything.* Local-first (runs on the user's device with their own credentials) is the default and strongest expression and buys privacy + no custody liability + regulatory ease; a cloud option is legitimate only where the user still owns and controls the data (their keys, their export, their right to leave). We hold nothing the user can't take back.
16. **Capability-based security, enforced in code.** A connector declares a capability tree (read/write, nested); the user grants and caps per capability (max notional, allowlist, daily limit, dry-run, confirm-required); a deterministic policy gate enforces every call. Caps are code, never prose, never the model's discretion.
17. **Trust is earned through conformance.** "Success" means *passed the conformance suite*, not "didn't crash." Self-healing and publishing both gate on it. Shared connectors carry provenance/signing + a risk tier (official-api > csv/file > reverse-engineered/browser). Execution is a separate, higher trust tier: read wide, write off-by-default, capped, sandboxed, human-in-loop until trusted.
18. **Self-reflection — re-evaluate every solution against these principles.** Before declaring work done, run it back through the constitution: which principles does it honour, which does it bend, what's still hardcoded / manual / uncovered? State the gaps explicitly (the "honest gaps" habit). A solution that quietly breaks a top principle isn't finished. This is the work-level analogue of conformance (principle 17): conformance verifies units, self-reflection verifies the solution.

---
See `research/connector-framework.md` for how these instantiate into the connector design, `FOUNDATION.md` for the apex worldview (13 Founding Articles), and `research/synthesis.md` for the full grounded reasoning.
