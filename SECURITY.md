# Security policy

sciqnt is local-first: your credentials live in your OS keyring
(`sq_secrets`), your data on your disk. There is no server of ours to
breach — most reports will concern the code itself.

## Reporting a vulnerability

Use **GitHub Security Advisories** ("Report a vulnerability" on the repo's
Security tab) — privately, please. You'll get an acknowledgement within
7 days. Coordinated disclosure: we ask for up to 90 days before publishing.

In scope, especially:
- anything that moves money or could (the execute tier is gated; a bypass
  of the capability gate is critical)
- credential handling (`sq_secrets`, session stores, connector setup flows)
- a connector exfiltrating data beyond its declared capabilities
- conformance-harness bypasses (the trust tier rests on it)

Out of scope: vulnerabilities in the brokers' own APIs/websites, and the
inherent risks of the unofficial broker SDKs we wrap (documented per-bundle
in `manifest.yaml: risk_tier` + FINDINGS).
