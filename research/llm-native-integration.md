# LLM-native integration — agents inside every component

**Status:** research synthesis, 2026-06-02. Grounds the "bidirectional LLM-native"
direction (owner-confirmed): every sciqnt component (A) **exposes** itself to agents
(library + SKILL.md + MCP) AND (B) can **launch** the user's *preferred installed
agent* with on-screen context ("use agent to X"). The connector generator is the
flagship case of pattern (B). Produced by the deep-research harness: 5 angles → 24
sources → 25 claims adversarially verified (3-vote), **23 confirmed, 2 refuted**.

> Honesty banner: areas 1–4 (detection, headless launch, Skills/MCP, codegen prior
> art) are backed by **primary vendor docs**. Area 5 (trust/security/governance, the
> CI gate, the UX) is **design synthesis, not independently citation-verified**, and
> two trust-relevant assumptions were **refuted** — see §6. Verify fast-moving CLI
> flags at ship time.

---

## 1. Detect installed agents + a "preferred agent" abstraction  ✓ verified

- **Detection = `shutil.which("claude")`** (stdlib) — the documented way to resolve an
  unqualified binary on PATH; returns the path or `None`. Probe each of `claude`,
  `codex`, `aider`, `gemini`, OpenClaw; an installed set drives the picker.
  [docs.python.org/shutil]
- **Launch = `subprocess.run([...], capture_output=True)`** with a **list of args**
  (`shell=False` default → shell metacharacters are safe, no injection), returns a
  `CompletedProcess` after waiting → clean **return-to-TUI**. For **live token
  streaming** into the TUI, use `Popen` and read incrementally instead. [docs.python.org/subprocess]
- **The pattern is "default browser":** a persisted preferred agent (config key) + a
  per-invocation override, exactly like `$BROWSER` / `xdg-settings` / `update-alternatives`.
  Graceful "no agent installed → install hint" when the detected set is empty.

## 2. Launch an agent headlessly WITH context, then return  ✓ verified (per-CLI)

| Agent | Non-interactive invocation | Context in / out |
|---|---|---|
| **Claude Code** | `claude -p "<prompt>" --allowedTools "Read,Edit,Bash"` | **reads stdin** (`cat data.txt \| claude -p '…' > out`), `--output-format text\|json\|stream-json` (text=return, stream-json=live tokens w/ `--verbose --include-partial-messages`); `--allowedTools` scopes capability. [code.claude.com/headless] |
| **Claude Agent SDK (Python)** | `query(prompt=…, options=ClaudeAgentOptions(cwd, system_prompt, allowed_tools, permission_mode, mcp_servers))` → `AsyncIterator[Message]` | one-off session; **the on-screen DATA goes in `prompt=`**, the seeding (cwd, tools, a component-specific MCP) goes in options. [code.claude.com/agent-sdk/python] |
| **Codex CLI** | `codex exec "<prompt>"` | progress → **stderr**, final answer → **stdout** (so capture stdout as the result); `--json` turns stdout into JSONL of all events; prompt also pipeable via `-`. [developers.openai.com/codex/noninteractive] |
| **Aider** | `aider -m "<instruction>" --yes-always` | sends one message, applies edits, exits; `--yes-always` for unattended. (open bug #3903: `--yes-always` can skip suggested shell cmds; `--yes` is the older form). [aider.chat/scripting] |
| **OpenClaw / Gemini CLI** | **NOT verified** (see §7 open questions) | probe syntax at implementation time |

**Caveats:** Claude headless has a **~10 MB piped-stdin cap (v2.1.128)** — pass large
portfolio context **by file path**, not piped; user-invoked Skills are interactive-only;
Claude now frames headless as the Agent SDK CLI and recommends a `--bare` mode for scripts.
**Verify flags at ship time — they move fast.**

## 3. Bidirectional skill/MCP substrate  ✓ verified

- **Agent Skill = a filesystem folder** (SKILL.md + scripts + assets) the agent
  discovers and loads dynamically — exactly sciqnt's `modules/sq-*/SKILL.md` model.
  **Progressive disclosure:** only `name` + `description` frontmatter is preloaded;
  SKILL.md is read only when relevant; utility scripts run via bash with only their
  *output* costing tokens → **near-zero idle context cost**. [claude.com/skills-explained, best-practices]
- **The `description` is the selection mechanism** — must say *what it does* AND *when
  to use it*, third person. This is the key insight for (B): **the same description
  that makes an external agent auto-select a Skill is what an in-TUI "use agent to X"
  affordance binds to** — one capability, two front-doors.
- **Skills and MCP are complementary, not alternatives:** "MCP for connectivity,
  Skills for procedural knowledge — use both." So a component packages a capability
  once (Skill + optional MCP tool) and it is both externally consumable and
  in-TUI-launchable. [claude.com/skills-explained] (Soft caveat: the source endorses
  using both, not redundantly double-packaging the *same* capability; a noted
  practitioner prefers Skills-over-MCP for token/stability — a preference, not a refutation.)

## 4. Flagship — agent-generated connector + upstream PR  ✓ prior art verified

- **Test/conformance-driven codegen is proven practice.** Airbyte's **AI Assistant**
  generates a connector from an API-docs link / OpenAPI URL (auth, pagination, headers,
  stream discovery, incremental sync), then the user **runs tests and iterates where it
  misses** — an explicit generate→test→fix loop, exactly sciqnt's
  generate→`check_snapshot()`→fix. (Beta; "chess-centaur" human-in-loop.) [docs.airbyte.com/ai-assist]
- **Dialect-isolation-to-one-file is established.** ccxt: *"we don't send unified
  symbols to exchanges… we don't put exchange-specific market-ids in unified
  structures"* — convert on the boundary (`market()`/`marketId()` out, `safeSymbol()`
  in). OpenBB's TET Fetcher concentrates normalization in `transform_query`/
  `transform_data` into standardized Pydantic models. Both validate sciqnt's
  `canonical.py`-holds-all-dialect → `core/sq_schema` design. [ccxt CONTRIBUTING, docs.openbb.co]
  (Nuance: OpenBB splits dialect across two stages + declarative aliases; sciqnt
  concentrates it in one file — conceptual analogy, not 1:1.)
- **Upstream pipeline:** scaffold bundle → agent fills `canonical.py` against the
  conformance harness → green → `gh` fork/branch/PR with a **self-describing** body
  (manifest + FINDINGS + conformance output) and the conformance suite as the **required
  CI gate**. *(The exact GitHub Actions gate + the self-healing trigger were NOT verified
  — §7.)*

## 5. Trust / security / governance — ⚠ DESIGN SYNTHESIS (not verified here)

These are the right *concerns*, but none of the mechanics below were citation-verified
in this round — treat as a design starting point to harden, not settled fact:
- Launching an agent with **account context is itself a surface** — scope what context
  is exposed; **never put secrets in prompts** (pass by reference/file, redact).
- Community/agent-written connectors that touch creds (and, execute-tier, move money)
  need: **capability/permission manifests enforced in code** (not prose), **sandboxing**,
  **read-vs-execute tiering**, code-signing/provenance (sigstore/SLSA), and human-review
  gates. **"Conformance-passed ≠ trustworthy."** (OWASP MCP Top-10 + MCP-security writeups
  were fetched but their specific controls weren't verified into claims.)

## 6. Refuted — do NOT build on these  ✗

1. **Permission modes (`acceptEdits`/`plan`/`bypassPermissions`) do NOT cleanly map to
   sciqnt's read-vs-execute trust tiers** (voted 1-2 refuted). Don't assume the agent's
   permission mode gives you the trust boundary — sciqnt must enforce read-vs-execute in
   its OWN code / capability manifest, not lean on the agent host's permission flags.
2. **ccxt does NOT mandate offline static request/response conformance tests as a
   contribution precondition** (1-2 refuted). ccxt is weaker prior art for a "required
   conformance CI gate" than assumed — **lean on Airbyte's run-tests loop** as the
   precedent instead.

## 7. Open questions (resolve at implementation)
- Exact headless syntax for **OpenClaw and Gemini CLI** (prompt arg, stdin, cwd flag,
  output format) — neither survived verification.
- The **actual enforced** read-vs-execute mechanism (since permission-mode mapping was
  refuted): agent `allowed_tools`, an MCP server-side capability manifest, or sciqnt's
  own sandbox? What does `manifest.yaml` risk/flavour bind to at runtime?
- What makes a community connector **"trusted"** beyond conformance — signing/provenance
  + human-review gates; the local→trusted graduation flow.
- The precise **GitHub Actions** workflow running the conformance suite as a required
  gate on agent-opened PRs, and how the **self-healing** loop (broker change →
  regression → regenerate → re-gate) is triggered and bounded.

---

## 8. Ranked recommendations (transferable)
1. **One launcher abstraction over heterogeneous agent CLIs**, `shutil.which`-detected,
   `subprocess`-launched, default-browser-style preferred-agent config + per-call override.
2. **Package each component capability ONCE as a Skill** (SKILL.md + description that
   states what+when) — it's both the external-agent entry and the in-TUI "use agent to X"
   binding. Add an MCP tool only where live connectivity is needed.
3. **Pass on-screen data via the prompt/stdin (by file for big context), seed cwd + scoped
   tools** — return-to-TUI with `run()`, stream with `Popen`.
4. **Enforce read-vs-execute in sciqnt's own code**, not the agent's permission flags (refuted).
5. **Model the connector generator on Airbyte's generate→test→fix loop**, with the
   conformance harness as the reward signal and dialect isolated to `canonical.py`.
6. **Treat trust as unsolved** — design the signing/sandbox/human-gate model deliberately
   before accepting community execute-tier connectors.

## 9. sciqnt-specific design + smallest first step
- **Config:** `preferred_agent` (enum of detected agents) in `sq_config`; a launcher
  module in core (e.g. `sq_agents`) that detects (`shutil.which`) + launches
  (`subprocess`) with a per-agent adapter (claude/codex/aider verified; openclaw/gemini
  to probe).
- **Per-component action:** a generic `use agent to <X>` affordance in `select_screen`
  that hands the preferred agent a prompt + context (the on-screen data by file) + the
  component's SKILL.
- **Flagship:** "Connect an account → use agent to connect" = scaffold bundle → agent
  fills `canonical.py` to green conformance → `gh` PR (conformance CI gate).
- **SMALLEST FIRST STEP (proposed):** detect installed agents + a Settings
  `preferred_agent` picker + ONE action — **"use agent to explain my portfolio"** (dump
  the current aggregate to a temp file, launch the preferred agent with a one-line
  prompt + that file, return to the TUI). Proves the launcher + context-handoff end to
  end with zero trust surface (read-only, no creds in the prompt).

## Sources (primary unless noted)
- Python stdlib: shutil.which / subprocess — https://docs.python.org/3/library/shutil.html , /subprocess.html
- Claude Code headless — https://code.claude.com/docs/en/headless ; Agent SDK (Python) — https://code.claude.com/docs/en/agent-sdk/python
- Codex non-interactive — https://developers.openai.com/codex/noninteractive
- Aider scripting — https://aider.chat/docs/scripting.html
- Anthropic Skills — https://claude.com/blog/skills-explained ; best-practices — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Airbyte AI Assist — https://docs.airbyte.com/platform/connector-development/connector-builder-ui/ai-assist
- ccxt CONTRIBUTING — https://github.com/ccxt/ccxt/blob/master/CONTRIBUTING.md ; OpenBB data pipeline — https://docs.openbb.co/platform/user_guides/add_data_provider_extension
- Trust (fetched, not verified into claims): OWASP MCP Top-10 — https://owasp.org/www-project-mcp-top-10/ ; sigstore agent provenance — https://www.alwaysfurther.ai/blog/sigstore-ai-agent-provenance
