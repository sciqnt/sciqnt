# Connector publishing — the three zones & the liability firewall

> **Decided (see `research/distribution-governance.md`).** Where a connector
> lives is determined by **trust / liability / ownership**, never by code
> organization. This is the operational rule for contributors and maintainers.

## The decision tree

```
Is the connector built ONLY on an official, sanctioned API (documented, ToS-permitted),
and is sciqnt willing to own + maintain it?
│
├── YES → ZONE 1: propose it into the sciqnt/sciqnt MONOREPO (a PR).
│          The contract still moves; the monorepo keeps cross-connector
│          migrations atomic. Carries the official-api risk tier.
│
└── NO (reverse-engineered, unofficial, ToS-bending, or you want to own it) →
           ZONE 2: it lives in YOUR OWN repo. Never under the sciqnt/ org.
           Users install it with `sciqnt modules add owner/repo` (git-ref →
           local conformance gate → installs into their sovereign dir).

Is it a closed/commercial connector sciqnt itself builds? → ZONE 3: a private repo,
same install path. (Not a contributor concern.)
```

| Zone | Home | Examples | Risk tier |
|---|---|---|---|
| **1. Core / first-party** | `sciqnt/sciqnt` monorepo (PR) | sanctioned-API brokers sciqnt owns | official-api |
| **2. Community / unofficial** | **contributor's own repo** (federated git-ref) | reverse-engineered Degiro, Robinhood, scraped/CSV sources | reverse-engineered / csv-file |
| **3. Private / proprietary** | sciqnt's private repo | premium / self-originated-data connectors | (sciqnt-internal) |

## Why reverse-engineered connectors must NOT live under `sciqnt/`

This is the **liability firewall**. Reverse-engineered interoperability clients
are, in the US, largely lawful (fair-use interop — *Sega v. Accolade*, *Sony v.
Connectix*; *Van Buren* forecloses most CFAA-via-ToS exposure). **But** a
click-through "no reverse engineering" EULA can still bind (*Blizzard v. BnetD*),
and DMCA §1201 bites if any access-control is circumvented. The defensible
posture — the one yt-dlp and ccxt survive on — is:

- **community-maintained, hosted but NOT org-owned.** The project ships the
  *contract + conformance harness + generator* and *indexes* community
  connectors. It does **not** host, own, or commercialise a connector it
  doesn't own.
- **explicitly disclaimed** (every scaffold ships `NOTICE.md`: no affiliation,
  no endorsement, clean-room interop, at-your-own-risk, run-on-your-own-account).
- **trademark-separated** — broker names used only nominatively (to identify the
  integration target), never to imply association.

This is governance guidance, not legal advice — get jurisdiction-specific
counsel before relying on it.

## How to publish a Zone 2 connector

1. **Scaffold** it: `sq_scaffold.build(...)` (or tell your coding agent "build a
   sciqnt connector for <broker>" — the sq-connectors skill drives it). You get a
   conformance-green skeleton with `manifest.yaml`, `NOTICE.md`, `FINDINGS.md`,
   the `snapshot()`/`accounts()` discovery surface, and a passing test.
2. **Fill it in** against the contract; log dialect quirks in `FINDINGS.md`;
   keep money `Decimal` and every fact currency-stamped; keep `NOTICE.md`
   accurate; set the manifest `risk_tier`, `flavours.<f>.risk`, and `endorsed:
   false`.
3. **Push to YOUR OWN GitHub repo** (named `sq-<broker>` by convention). Do
   **not** open an empty placeholder repo under `sciqnt/` — the scaffold +
   generator IS the funnel; a repo graduates only once it passes conformance.
4. **Share** `owner/repo`. Anyone installs with `sciqnt modules add owner/repo`,
   which runs YOUR conformance suite locally before installing — trust is earned
   by the harness, not claimed by a registry. Passing conformance in sciqnt's
   scheduled CI earns the **certified** tier.

## What "endorsed" means

`endorsed: false` is the honest default for every community connector. sciqnt
does not vouch for connectors it doesn't own; the conformance gate (on install
and in CI) is the trust mechanism, and the risk tier (official-api > csv/file >
reverse-engineered/browser) is declared, never hidden.
