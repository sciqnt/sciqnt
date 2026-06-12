# sq-polymarket — findings & quirks

Second `AssetClass.EVENT` connector + first WALLET-based (non-broker) source.
Read-only, USDC-base. Positions read is **public, no auth** — the only input is
a wallet address (public, not secret).

## Architecture
- `canonical.py` — pure `to_canonical(positions, cash_usdc=…)` →
  `PortfolioSnapshot` of EVENT positions. Fixture-tested (10 tests).
- `live.py` — public GET `https://data-api.polymarket.com/positions?user=<addr>`
  (stdlib urllib; no auth). `CredentialsMissing` if no address configured.
- `__init__.py` — `snapshot(asof=None, *, account=None)` + `accounts()`.

## Endpoint + fields (verified live 2026-06-01, research/)
`GET https://data-api.polymarket.com/positions?user=<address>` — no auth;
`[]` if empty; HTTP 400 if `user` omitted. The `gamma-api` host 404s this path
(a WebFetch summary that said otherwise was wrong — live-tested).

Position fields used: `size` (shares), `avgPrice`/`curPrice` (already 0..1 —
NO /100 needed, unlike Kalshi), `initialValue`, `currentValue`, `realizedPnl`,
`asset` (ERC-1155 outcome-token id → instrument_id), `conditionId` (market →
terms.event_id), `outcome` ("Yes"/"No"), `title`/`slug`, `endDate` (→
resolution_date).
- **REFUTED 0-3, do NOT use:** `eventId`, `eventSlug`, `oppositeOutcome`. We
  rely on `conditionId / asset / outcome / title / slug / endDate` only.

## Mapping + quirks
- `size → quantity`, `avgPrice → break_even_price_local`, `curPrice →
  last_price_local`, `initialValue → cost_basis_base` (fallback size×avgPrice),
  `currentValue → value_base` (fallback size×curPrice), `currentValue −
  initialValue → unrealized`, `realizedPnl → realized_product_pl_base`.
- **Prices are already probabilities in [0,1]** → the EVENT conformance band
  check passes without conversion (contrast Kalshi's cents).
- **Cash is read on-chain** (onchain.py). The positions API returns no cash, so
  we `eth_call` ERC-20 `balanceOf(funder)` on Polygon for BOTH native USDC
  (`0x3c49…3359`) and bridged USDC.e (`0x2791…4174`) and sum them (6 decimals).
  Stdlib urllib JSON-RPC, no web3 dep; tries public RPCs in order
  (`POLYMARKET_RPC` env var overrides). Best-effort → None on total RPC failure
  (cash omitted, never fabricated). Live-verified: a real funder shows native
  USDC while most capital sits deployed in positions.
- **Proxy wallet = FUNDER address.** For Magic/browser-wallet logins, positions
  + USDC live at the FUNDER (proxy) address, NOT the signing EOA. Setup tells
  the user to use the profile's funder address.
- **CredentialsMissing is a RuntimeError, never sys.exit** (shared fix) so the
  aggregated view downgrades just this source.

## Honest gaps (also in manifest.yaml)
- no_history / no_asof
- trading (CLOB) auth (EIP-712 L1 + HMAC L2) not implemented — read-only
- pending a real-wallet run (adapter fixture-proven against the verified field
  shapes; not yet pointed at a live wallet with positions)
