# sq-tiingo — findings & quirks

Living log. Update the moment anything new is learned.

## Why this bundle exists (2026-06-11)
The MVP wanted a SECOND free price source so Yahoo (unofficial) breaking
doesn't blind the portfolio. **Stooq was the original pick and is dead
programmatically**: its classic CSV endpoint (`/q/d/l/?s=…&i=d`) 404s and
the whole site now sits behind a JavaScript proof-of-work wall (SHA-256
challenge, verified 2026-06-11) — scraping through an anti-bot wall is
browser-tier fragility, against the flavour rules. Tiingo is the official
replacement: real API, free key, 30+ years of history.

## Tier & licensing (verified 3-0 against tiingo.com/about/pricing, 2026-06-11)
- Free "Starter": **500 unique symbols/month, 50 req/hour, 1,000 req/day,
  1 GB/month** — a 50-instrument portfolio with full-history backfill and
  daily refresh fits comfortably.
- License is **"Internal Use Only"** on free AND paid tiers: fine for a
  bring-your-own-key personal tool; sciqnt must never redistribute the data.
- Coverage: **US & Chinese stocks + ETFs/mutual funds.** European venue
  listings (.L/.DE/.AS) are NOT available — the provider gates them out
  locally (`_supported`), so they never burn quota.

## Key resolution
`sq_secrets.get_secret("sq-tiingo", "api_token", env_var="TIINGO_API_KEY")`.
Keyless = inert provider (every call None; the chain moves on). The key is
never logged and never leaves the machine — requests go direct to Tiingo.

## API shape
- `GET /tiingo/daily/<symbol>/prices?startDate=…&endDate=…&format=json` with
  the key in an `Authorization: Token <token>` header (Tiingo accepts both
  header and `&token=` query form; we use the header so the key never lands
  in URLs or logs).
  → list of rows: `date` (ISO), `close`, `adjClose`, `divCash`,
  `splitFactor`, OHLCV. We take `close` (as-traded), `divCash` > 0 →
  dividend event, `splitFactor` ≠ 1 → split event.
- **Series semantics differ from Yahoo (declared):** Tiingo `close` is the
  as-traded raw close; Yahoo's chart series is split-adjusted. Identical on
  any window with no split inside — which is the fallback rung's job. A
  cross-source conformance check on a split-crossing instrument WILL show
  divergence; that's the two sources being honest about different bases.
- Payload has **no currency field**; the US daily feed quotes USD —
  hardcoded, declared here.
- Ticker dialect: class shares are dash-spelled (`BRK-B`) in BOTH the
  canonical (Yahoo-style) vocabulary and Tiingo's — verbatim pass-through.
  A dot in a canonical ticker is therefore ALWAYS a venue suffix → gated.

## Open issues / TODO
- [ ] **Live conformance pending a real key** — fetch shapes implemented
      from the documented API; first run with a key should reconcile one
      ticker against Yahoo (`AAPL` close within rounding) and record the
      result here. (Owner: create the free account when convenient.)
- [ ] IEX intraday endpoint could add a true spot quote later; EOD-only for
      now (asof=None serves the most recent close — declared).
