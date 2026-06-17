# sciqnt

**A local-first, agent-native portfolio tracker & cross-asset financial data
layer.** One canonical, point-in-time-correct schema for your positions,
transactions, cash and prices — fed by community connectors for each broker
/ exchange / data source, rendered in a fast TUI, and consumable by any AI
agent (Claude Code, Codex, …) through plain CLI + versioned JSON surfaces.

Deterministic code computes the numbers. Agents reason and explain. You own
every byte: your credentials live in your OS keyring, your data on your
disk — there is no server.

```
  net worth (EUR) │ daily

  24,570 ┤                                                       ⢀⡤⠖⠋⠹
         │                                 ⣀⡤⣄⣤⣀⣀⣀⣀⣀  ⡤⠤⠤⠤⣄ ⣀⣀⣀⣀⡤⠞
  22,019 ┤                            ⢀⣠⢤⣰⠒⠃     ⠉ ⠈⠉⠛⠁   ⠈⠉⠁⠉⠈⠁
         │                    ⢀⣰⠒⠚⠉⠉⠓⠒⠋
         │⣀          ⣀⢀⣀⣠⠤⠖⠋⠛⠉⠉
  19,468 ┤⠈⠙⠒⢦⣀⡤⠤⣤⣄⣠⠴⠋⠉
         ╰────────────────────────────────────────────────────────────
          2026-01-02                                        2026-06-12

  total value             24,121.05 EUR      TWR        13.70 %/yr
  total P/L (lifetime)    +3,340.95 EUR      XIRR        9.79 %/yr
  dividends (lifetime)      +395.10 EUR      max DD     −14.5 %
```

*That's the built-in demo portfolio — synthetic and deterministic. sciqnt
runs in demo mode until you connect an account; no real finances appear in
any screenshot or doc, ever.*

## Install

Requires **Python ≥ 3.10**. The app pulls its component libraries (the
`sciqnt/sq-*` repos) automatically.

```sh
pip install "git+https://github.com/sciqnt/sciqnt"   # the whole stack, one command
sciqnt                                                # interactive home (demo portfolio until you connect)
```

…or isolated as a tool:

```sh
uv tool install "git+https://github.com/sciqnt/sciqnt"   # or: pipx install "git+https://github.com/sciqnt/sciqnt"
```

> **PyPI** (`pip install sciqnt`) is being published — until every component
> dist is up, prefer the `git+https://…` form above. Connectors are added at
> runtime, not installed here: `sciqnt modules add owner/repo`.

**Develop on the app itself:**

```sh
git clone https://github.com/sciqnt/sciqnt && cd sciqnt
python3 -m venv .venv && .venv/bin/pip install -e .   # pulls the component libs by git-ref
.venv/bin/sciqnt
```

macOS note: use a Python built against modern OpenSSL (e.g. Homebrew
`python@3.13`) — the system Python's LibreSSL is fragile against financial-API TLS.

## What you get

- **The TUI**: portfolio home with net-worth chart (1D…All ranges,
  5-minute intraday), positions / exposure / income / news / flows /
  history tabs, account drill-downs — everything keyboard-driven.
- **Honest money math**: `Decimal` end-to-end, FIFO/LIFO/AVG lots,
  fees-inclusive cost basis, TWR (GIPS-style breaks), XIRR, max drawdown,
  benchmark comparison — computed from your raw transaction history,
  point-in-time-correct (`sciqnt --asof 2024-12-31`).
- **Connectors as self-contained bundles** (`modules/sq-*`): manifest +
  agent-facing SKILL + a living quirks log (FINDINGS) + conformance tests.
  Degiro (CSV + live), Robinhood, Kalshi, Polymarket, Yahoo, Tiingo, ECB
  FX, SEC EDGAR, FIRDS, OpenFIGI, RSS news — and a scaffold + harness for
  building your own.
- **Agent-native, both directions**: every view is reproducible from the
  CLI (`sciqnt --help` maps it; `--json` gives versioned, Decimal-as-string
  data — `sciqnt.portfolio/v1`, `sciqnt.history/v1`, …). Summon your coding
  agent from any screen and it receives where you are, what's on your
  screen, and the command that reproduces it; agents can leave findings on
  your home screen (`sciqnt insight add`).
- **A point-in-time price archive**: append-only, bitemporal, yours.

## For agents

Run `sciqnt --help`. Every screen of the app has a CLI form; add `--json`
for structured data. Skills ship in-repo (`sq-portfolio`, `sq-connectors`)
and install into Claude Code / Codex automatically when summoned from the
app. **[`AGENTS.md`](AGENT_GUIDE.md) is the codebase map — start there if
you're an agent.**

## Build a connector for your broker

The platform ships the contract + conformance harness + a scaffold — the
long tail of connectors belongs to the community (and to your coding
agent). See [CONTRIBUTING.md](CONTRIBUTING.md); the short version:

```
"build a sciqnt connector for <my broker>"   # tell your coding agent
```

Independent connector repos install with `sciqnt modules add owner/repo`
(conformance runs locally before first use — trust is earned by the
harness, not claimed).

## Going deeper

- [`FOUNDATION.md`](FOUNDATION.md) — the worldview + the 13 Founding Articles.
- [`PRINCIPLES.md`](PRINCIPLES.md) — the 18 operating principles.
- [`research/`](research/) — the grounded reasoning behind every decision.

Principles, the short list: local-first and sovereign — fire us and keep
everything. Deterministic core, probabilistic edge — LLMs never touch the
money math. Data first — rendered text is for humans, versioned JSON is the
contract. Read wide, execute gated. Synthetic fixtures only.

## License

MIT — see [LICENSE](LICENSE).
