# 01 — MCP vs Skills vs Libraries vs Code Execution

*Web-grounded research, late-2025/early-2026 state of the ecosystem. Where the ecosystem is genuinely unsettled, this is flagged rather than overstated.*

## 1. MCP (Model Context Protocol): maturity and limitations

MCP launched November 2024 and is now the de facto standard for agent-to-tool connectivity. By late 2025 it had broad cross-vendor native support (Claude, ChatGPT, Google, Microsoft Copilot), and the **official MCP Registry launched in preview on 8 September 2025** (a separate community registry followed in November 2025). Server counts grew from ~1,200 (Q1 2025) to ~6,800+ by year-end, with community indexes citing 18,000+. Governance moved under the **Linux Foundation** (alongside A2A), which matters for durability — it's no longer a single-vendor spec.

**Transports** have consolidated, not proliferated. The 2026 roadmap explicitly states they are **not adding new transports** — only two official ones remain: **stdio** (local) and **Streamable HTTP** (remote, having superseded the older HTTP+SSE transport). The active work is making Streamable HTTP **stateless and horizontally scalable** ("sessions fight with load balancers"). **Auth** is converging on OAuth 2.0 / OIDC, with newer proposals (SEP-1932 DPoP, SEP-1933 Workload Identity Federation) still on the horizon, not finalized.

**Known limitations in practice** (well-documented, take seriously):
- **Context/tool bloat.** Tool definitions are loaded upfront. Multiple analyses report a standard multi-server setup can consume ~70% of the context window before the agent acts; "connect three servers and definitions alone occupy ~143K tokens." Practitioner consensus is agents degrade noticeably past ~2-3 connected servers.
- **Intermediate-result duplication.** Data passed between tool calls flows through the model context repeatedly, inflating tokens.
- **Latency/statefulness.** Each call is a network round-trip; stateful sessions complicate scaling.
- **Security is the sharpest concern.** Prompt injection via tool descriptions and **tool poisoning** (e.g. CVE-2025-54136) are treated as a *supply-chain* class of attack: third-party tool metadata collapses into the same context window as the system prompt, tool definitions can mutate post-install ("rug pull"), and a malicious server can intercept calls to a trusted one. Prompt injection remains broadly unsolved.

## 2. Anthropic Agent Skills

A Skill is a **folder containing a `SKILL.md`** with YAML frontmatter (`name`, `description`) plus optional bundled scripts/resources. The defining mechanism is **progressive disclosure** in three tiers: (1) name+description only at startup (~30-50 tokens each); (2) full `SKILL.md` loaded when the agent judges it relevant; (3) linked files/scripts loaded on demand during execution. Anthropic's framing: bundled context is "effectively unbounded" because only what's needed enters the window.

Skills **teach the agent *how* to do something** (procedural knowledge, runbooks, domain conventions, which tools to call and in what order). They run locally, need no auth or hosted runtime, and are author-friendly (markdown + folders, accessible to non-developers). They are not a replacement for live data access. Anthropic explicitly positions Skills as **complementary to MCP** — Skills teach workflows that *invoke* external tools/software.

## 3. The decision framework (emerging consensus)

The strongest framing across independent sources (Speakeasy, LlamaIndex, Arcade, Milvus) is that **Skills vs MCP is a false dichotomy — they're different layers**:

> "Skills teach agents *how* to do things. MCP servers give agents the *ability* to do things." Tools *do* actions, MCP *provides access*, Skills *encode how to do the job right*.

Practical decision rules:
- **Use MCP** when data changes between invocations (live access), you need auditable/centrally-logged tool calls, server-side credential handling, deterministic schemas, and a single source of truth that updates frequently.
- **Use a Skill** when the knowledge is stable enough to "write down once and be right for weeks," when you want local/zero-latency execution, and when authoring simplicity matters.
- **Use a plain library/CLI** when token efficiency and determinism dominate — CLI-style interfaces reportedly beat MCP by **10-32x in token efficiency** with near-100% success, because there are no upfront tool-definition costs.

There is **no single authoritative Anthropic head-to-head doc** ranking all three; Anthropic's material describes Skills and says they "complement MCP" but stops short of a comparison matrix. The decision framework is industry-emergent, not officially blessed.

## 4. "Code execution as the interface" (tools-as-code)

The most important recent shift for packaging. Anthropic's "code execution with MCP" writing argues agents should **call tools by writing code against an API**, discovering tool definitions on-demand from a filesystem (`./servers/...`) rather than loading all definitions upfront. Reported impact: a worked example dropping **from ~150,000 tokens to ~2,000 (~98.7% saving)**, by (a) loading only the tool definitions a task needs and (b) keeping intermediate data inside the code sandbox instead of round-tripping it through model context. Tools are organized as typed code modules (e.g. TypeScript files) the agent explores and imports.

Implication: **the durable primitive is a well-typed code API/library**, not a hand-curated list of tool definitions. MCP and Skills become *delivery wrappers* over that library. (Caveat: code execution introduces sandboxing and credential-exposure risk — raw API keys in sandboxes are an org-scale risk vs MCP's server-side credential custody.)

## 5. Forward-looking (1-3 years)

- **Layered protocol stack solidifying:** MCP = agent-to-tool; **A2A (Google) = agent-to-agent**, with **A2A "Agent Cards"** for capability discovery; IBM/AGNTCY **ACP merged into A2A (Sept 2025)** to reduce fragmentation. Both MCP and A2A under Linux Foundation; joint spec work expected through 2026.
- **Discovery without live connections:** the 2026 MCP roadmap adds a **`.well-known` metadata format** so registries/crawlers learn capabilities without connecting — durable signal that *static, declarative capability description* is the future.
- **Stateless, horizontally-scalable HTTP** is the committed direction; auth converging on OAuth/OIDC.
- **Agents authoring their own tools / tools-as-code** is gaining momentum and pairs naturally with progressive disclosure.

**Durable design choices today:** a clean typed core API; declarative, static capability/metadata description; OAuth/OIDC-based auth; statelessness; avoiding deep coupling to any one agent vendor's surface.

## 6. Recommendation for sciqnt

**Layer it. Do not pick one.** A connector should be packaged as three stacked artifacts over one core:

1. **Core: a deterministic, well-typed library** (canonical cross-asset schema + each connector as an independent, importable, versioned module). The durable asset — survives every protocol shift, is the "code" in code-execution, directly usable without any agent.
2. **Thin MCP server wrapping the library** — for live data, server-side auth/credential custody, auditability, cross-vendor reach (Claude, ChatGPT, openclaw). Keep the tool surface **small and code-execution-friendly** (a few code-API-style entry points, not dozens of granular tools) to dodge the context-bloat ceiling.
3. **A Skill (SKILL.md) per connector/workflow** documenting *how* to use the library/MCP server — financial conventions, which calls to compose, how to interpret outputs. Cheap via progressive disclosure.

**Mapping to sciqnt goals:** "deterministic code computes, LLMs reason" → library (compute) + Skill (reason/explain). "Plug independently into many agents" → library (universal) + MCP (open cross-vendor protocol). The OpenBB/Supabase "others build on top" outcome needs a real library foundation — MCP/Skills alone are agent adapters, not composable software. Keep the **library as the contract**; treat MCP/Skill/A2A as swappable adapters.

**Uncertainty flags:** MCP security model (tool poisoning, injection) is unsolved — the MCP layer must pin/verify connector provenance and not auto-merge untrusted third-party metadata. The Skills-vs-MCP decision framework is community consensus, not official Anthropic doctrine. Code-execution-as-interface is compelling but early — design the core library so it works whether agents call it via MCP tools *or* generated code.

## Sources
- https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- https://www.anthropic.com/engineering/code-execution-with-mcp
- https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/
- https://blog.modelcontextprotocol.io/posts/2025-12-19-mcp-transport-future/
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
- https://www.speakeasy.com/blog/skills-vs-mcp
- https://www.llamaindex.ai/blog/skills-vs-mcp-tools-for-agents-when-to-use-what
- https://www.mcpjam.com/blog/claude-agent-skills
- https://milvus.io/blog/is-mcp-dead-cli-and-skills-for-ai-agents.md
- https://www.arcade.dev/blog/what-are-agent-skills-and-tools/
- https://simonwillison.net/2025/Apr/9/mcp-prompt-injection/
- https://www.truefoundry.com/blog/blog-mcp-tool-poisoning-gateway-defense
- https://www.practical-devsecops.com/mcp-security-vulnerabilities/
- https://optinampout.com/blogs/mcp-vs-a2a-vs-acp-agent-protocols-2026
- https://arxiv.org/pdf/2505.02279
- https://en.wikipedia.org/wiki/Model_Context_Protocol

*Source-quality note: the Anthropic engineering posts and modelcontextprotocol.io roadmap/transport blogs are authoritative; decision-framework and adoption-statistics pieces are credible secondary/vendor analysis — adoption numbers (e.g. "78% of enterprise teams," "18,000 servers") are indicative, not verified.*
