"""sq-polymarket — on-chain USDC balance read (funder address).

The Data API /positions call returns no cash, so to complete the snapshot we
read the funder address's USDC balance directly from Polygon via a public
JSON-RPC `eth_call` to ERC-20 `balanceOf` — stdlib urllib only, no web3 dep.

Polymarket collateral has been BOTH bridged USDC.e and native USDC across the
platform's history (they migrated); a given funder address may hold either, so
we sum both. USDC has 6 decimals on Polygon.

Best-effort: any RPC failure returns None (cash simply doesn't show) — never
raises into the snapshot path. Users can point at their own node via the
`POLYMARKET_RPC` env var.
"""
import json
import os
import urllib.request
from decimal import Decimal

# Polygon USDC contracts (6 decimals). Sum both — a funder may hold either.
USDC_NATIVE  = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDC_BRIDGED = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"   # USDC.e
USDC_DECIMALS = 6
_BALANCEOF_SELECTOR = "0x70a08231"

# Public Polygon RPCs, tried in order. Override with POLYMARKET_RPC.
_DEFAULT_RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://1rpc.io/matic",
]


def _balanceof_calldata(address: str) -> str:
    """ERC-20 balanceOf(address) calldata: selector + 32-byte-padded address."""
    addr = address.lower().replace("0x", "")
    return _BALANCEOF_SELECTOR + addr.rjust(64, "0")


def decode_balance(hex_result, decimals: int = USDC_DECIMALS) -> Decimal:
    """Pure: decode an eth_call hex result → Decimal token amount.
    '0x' / None / empty → 0 (an address that never held the token returns 0x)."""
    if not hex_result or hex_result == "0x":
        return Decimal("0")
    try:
        raw = int(hex_result, 16)
    except (TypeError, ValueError):
        return Decimal("0")
    return Decimal(raw) / (Decimal(10) ** decimals)


def _eth_call(rpc_url: str, to: str, data: str):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
               "params": [{"to": to, "data": data}, "latest"]}
    req = urllib.request.Request(
        rpc_url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "sciqnt/0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r).get("result")


def fetch_usdc_balance(address: str, rpc_urls=None):
    """Sum native + bridged USDC at `address` on Polygon. Returns a Decimal,
    or None if every RPC failed (so the caller omits cash rather than
    fabricating a zero). Best-effort — never raises."""
    if not address:
        return None
    env_rpc = os.environ.get("POLYMARKET_RPC")
    rpcs = ([env_rpc] if env_rpc else []) + (rpc_urls or _DEFAULT_RPCS)
    calldata = _balanceof_calldata(address)
    for rpc in rpcs:
        try:
            native  = decode_balance(_eth_call(rpc, USDC_NATIVE,  calldata))
            bridged = decode_balance(_eth_call(rpc, USDC_BRIDGED, calldata))
            return native + bridged
        except Exception:                                  # noqa: BLE001
            continue        # try the next RPC
    return None             # all RPCs failed → caller omits cash
