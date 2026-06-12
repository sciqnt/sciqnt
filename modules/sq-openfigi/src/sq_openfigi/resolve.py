#!/usr/bin/env python3
"""Source unit: resolve an ISIN to candidate Yahoo Finance tickers via the free
OpenFIGI mapping API (the identifier spine from the schema research). Stdlib only,
deterministic. No key needed at low volume (rate-limited).

OpenFIGI returns one listing per exchange; we map exchange codes to Yahoo
suffixes. Pair with market_price.fetch_quote to pick the candidate that actually
prices (resolve -> validate = self-checking).

Usage: python3 resolve.py ISIN [ISIN ...]
"""
import json
import sys
import urllib.request

OPENFIGI = "https://api.openfigi.com/v3/mapping"

# OpenFIGI exchCode -> Yahoo suffix (common venues; extend as needed)
EXCH_YF = {
    "LN": ".L",                       # London
    "GR": ".DE", "GY": ".DE", "GF": ".DE",  # Germany / Xetra
    "NA": ".AS",                      # Amsterdam
    "FP": ".PA",                      # Paris
    "SW": ".SW", "VX": ".SW",         # Switzerland
    "IM": ".MI",                      # Milan
    "SM": ".MC",                      # Madrid
    "PL": ".LS",                      # Lisbon
    "BB": ".BR",                      # Brussels
    # US venues -> no suffix
    "UN": "", "UW": "", "UQ": "", "US": "", "UA": "", "UP": "", "UR": "", "UV": "", "PQ": "",
}


def resolve_isin(isin):
    body = json.dumps([{"idType": "ID_ISIN", "idValue": isin}]).encode()
    req = urllib.request.Request(
        OPENFIGI, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "sciqnt/0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.load(r)
    out = []
    for block in res:
        for d in block.get("data", []):
            exch = d.get("exchCode", "") or ""
            suffix = EXCH_YF.get(exch)
            tkr = d.get("ticker")
            yahoo = (tkr + suffix) if (tkr is not None and suffix is not None) else None
            out.append({
                "ticker": tkr, "exchCode": exch, "name": d.get("name"),
                "securityType": d.get("securityType"), "yahoo": yahoo,
            })
    return out


def yahoo_candidates(isin, prefer_suffix=None):
    """PURE: ordered, de-duped list of candidate Yahoo tickers (prefer_suffix first).
    No pricing — the composition layer validates by trying to fetch each. This keeps
    sq-openfigi independent of any price source (modularity)."""
    cands = [c["yahoo"] for c in resolve_isin(isin) if c["yahoo"]]
    cands.sort(key=lambda y: 0 if (prefer_suffix and y.endswith(prefer_suffix)) else 1)
    seen, out = set(), []
    for y in cands:
        if y not in seen:
            seen.add(y)
            out.append(y)
    return out


# OpenFIGI's `securityType` strings → canonical AssetClass names. We
# expose strings here (not the enum) so sq-openfigi stays free of a
# sq_schema dependency; consumers map "STOCK" → AssetClass.STOCK on
# their side.
_SEC_TYPE_TO_ASSET_CLASS = {
    "Common Stock":           "STOCK",
    "REIT":                   "STOCK",
    "ADR":                    "STOCK",
    "Depositary Receipt":     "STOCK",
    "ETP":                    "ETF",
    "ETF":                    "ETF",
    "Closed-End Fund":        "FUND",
    "Mutual Fund":            "FUND",
    "Open-End Fund":          "FUND",
    "Bond":                   "BOND",
    "Bill":                   "BOND",
    "Sovereign Bond":         "BOND",
    "Corporate Bond":         "BOND",
    "Future":                 "FUTURE",
    "Option":                 "OPTION",
    "Warrant":                "WARRANT",
    "CFD":                    "CFD",
    "Index":                  "INDEX",
}


def _pick_listing(listings):
    """Pick the most useful single listing from OpenFIGI's per-exchange
    results. Preference: a listing that resolves to a Yahoo ticker
    (most useful for downstream price overlay). Falls back to the first
    listing that has SOME usable fields. None when nothing usable."""
    if not listings:
        return None
    with_yahoo = [l for l in listings if l.get("yahoo")]
    if with_yahoo:
        return with_yahoo[0]
    with_ticker = [l for l in listings if l.get("ticker")]
    if with_ticker:
        return with_ticker[0]
    return listings[0]


def resolve_metadata(isin):
    """Return a single normalized metadata dict for `isin` (or None when
    OpenFIGI has nothing). Shape::

        {
          "isin":         str,
          "ticker":       str | None,    # bare exchange ticker
          "yahoo_ticker": str | None,    # ticker.SUFFIX for sq-yahoo lookups
          "name":         str | None,
          "asset_class":  str | None,    # canonical key ("STOCK" / "ETF" / …)
          "exch_code":    str | None,
        }

    Use this for display enrichment + (optionally) downstream price
    overlay on delisted-from-broker instruments. Raises on transport
    errors — the calling layer should wrap in try/except (typically
    via the disk cache helper, which silently degrades on failure)."""
    listings = resolve_isin(isin)
    chosen = _pick_listing(listings)
    if chosen is None:
        return None
    return {
        "isin":         isin,
        "ticker":       chosen.get("ticker"),
        "yahoo_ticker": chosen.get("yahoo"),
        "name":         chosen.get("name"),
        "asset_class":  _SEC_TYPE_TO_ASSET_CLASS.get(
                            chosen.get("securityType") or ""),
        "exch_code":    chosen.get("exchCode"),
    }


if __name__ == "__main__":
    for isin in sys.argv[1:] or ["IE00BGSF1X88"]:
        print(f"\n{isin}:")
        for c in resolve_isin(isin):
            print(f"  {str(c['ticker']):8} {str(c['exchCode']):4} -> "
                  f"yahoo {str(c['yahoo']):10} {c['name']}")
