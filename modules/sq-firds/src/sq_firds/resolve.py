#!/usr/bin/env python3
"""Source unit: resolve an ISIN to instrument reference data via ESMA FIRDS
(the EU's regulatory Financial Instruments Reference Data System).

OFFICIAL and completely free, no key: every instrument traded on an EU/EEA
venue since MiFID II (2018) is in here — including DELISTED ones OpenFIGI
has forgotten (live-verified: Premier Oil, pre-split Harbour Energy and
Anywhere Real Estate all resolve here after OpenFIGI returned nothing).
This is also the home of the schema's chosen classification standard:
FIRDS carries the **CFI code** (ISO 10962) natively.

Endpoint: the public Solr core behind registers.esma.europa.eu —
  GET /solr/esma_registers_firds/select?q=isin:"<ISIN>"...
Records are per (ISIN, venue MIC); many rows per ISIN. Rows can be
attribute-less tombstones (status CANC with null names) — the picker
requires a non-empty full name and prefers non-cancelled rows.

Limits: pre-2018 delistings are absent (NL0010661914 stays unknown
everywhere). US-listed-only instruments appear ONLY if also traded on an
EU venue. No ticker — FIRDS identifies by ISIN+MIC; pair with
sq-openfigi for tickers.

Usage: python3 resolve.py ISIN [ISIN ...]
"""
import json
import sys
import urllib.parse
import urllib.request

FIRDS_SOLR = ("https://registers.esma.europa.eu/solr/"
              "esma_registers_firds/select")

# CFI (ISO 10962) category/group → canonical AssetClass KEY strings.
# Same convention as sq-openfigi: strings, not the enum, so this bundle
# stays free of a sq_schema dependency; consumers re-map on their side.
# First char = category; for Collective investment (C) the second char
# distinguishes ETFs (E) from other funds.
_CFI_TO_ASSET_CLASS = {
    "E": "STOCK",      # equities (ESVUFR = common/ordinary shares) ✓ verified
    "D": "BOND",       # debt ✓ verified
    "C": "FUND",       # collective investment (CE… overridden to ETF below) ✓
    "O": "OPTION",
    "F": "FUTURE",
    "R": "WARRANT",    # entitlements / rights / warrants
    # Categories deliberately UNMAPPED → instrument stays AssetClass.OTHER
    # (honest): the audit flagged earlier guesses 'I'→INDEX and 'J'→CFD as
    # unverified against ISO 10962 (in the 2015 edition J = Forwards and I
    # is not a category at all). Better OTHER than wrong. Add a mapping
    # only with the standard in hand — see FINDINGS.
}


def asset_class_from_cfi(cfi: str | None) -> str | None:
    """Map a CFI code to a canonical AssetClass key (None = unknown)."""
    if not cfi:
        return None
    cfi = cfi.upper()
    if cfi.startswith("CE"):
        return "ETF"
    return _CFI_TO_ASSET_CLASS.get(cfi[0])


def resolve_isin(isin: str) -> list[dict]:
    """Raw FIRDS rows for `isin` that carry a full name, newest first.
    Raises on transport errors; [] when FIRDS has nothing.

    The attribute-presence filtering happens CLIENT-side: a server-side
    `gnr_full_name:["" TO *]` range filter looked clever but is expensive
    on their Solr (live-observed: it pushed responses past 20s while the
    plain ISIN query answers in ~1s). Fetch a page, filter here."""
    params = {
        "q": f'isin:"{isin}"',
        "rows": "50",
        "wt": "json",
        "sort": "valid_from_date desc",
    }
    url = f"{FIRDS_SOLR}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "sciqnt/0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    docs = data.get("response", {}).get("docs", []) or []
    return [d for d in docs if d.get("gnr_full_name")]


def _pick(docs: list[dict]) -> dict | None:
    """Prefer the newest non-cancelled row; fall back to the newest row
    of any status (a fully-delisted instrument may only have TERM/CANC
    rows — its reference data is still good)."""
    for doc in docs:
        if doc.get("status") != "CANC":
            return doc
    return docs[0] if docs else None


def resolve_metadata(isin: str) -> dict | None:
    """Single normalized metadata dict for `isin` (or None when FIRDS has
    nothing). Same shape-contract as `sq_openfigi.resolve_metadata`, plus
    the FIRDS-specific extras (`currency`, `cfi`, `lei`)::

        {
          "isin":         str,
          "ticker":       None,          # FIRDS has no tickers
          "yahoo_ticker": None,
          "name":         str | None,
          "asset_class":  str | None,    # canonical key, mapped from CFI
          "exch_code":    str | None,    # the venue MIC
          "currency":     str | None,    # notional currency
          "cfi":          str | None,
          "lei":          str | None,
        }

    Raises on transport errors — callers wrap (typically via a disk
    cache helper that degrades silently)."""
    chosen = _pick(resolve_isin(isin))
    if chosen is None:
        return None
    cfi = chosen.get("gnr_cfi_code")
    return {
        "isin":         isin,
        "ticker":       None,
        "yahoo_ticker": None,
        # FIRDS pads some full names with trailing whitespace — strip at the
        # source so consumers never see it; all-whitespace → None.
        "name":         (chosen.get("gnr_full_name") or "").strip() or None,
        "asset_class":  asset_class_from_cfi(cfi),
        "exch_code":    chosen.get("mic"),
        "currency":     chosen.get("gnr_notional_curr_code"),
        "cfi":          cfi,
        "lei":          chosen.get("lei"),
    }


if __name__ == "__main__":
    for isin in sys.argv[1:] or ["GB00B43G0577"]:
        try:
            m = resolve_metadata(isin)
            if m is None:
                print(f"{isin}: (not in FIRDS)")
            else:
                print(f"{isin}: {m['name']} · {m['asset_class']} "
                      f"({m['cfi']}) · {m['currency']} · {m['exch_code']}")
        except Exception as e:                                 # noqa: BLE001
            print(f"{isin}: ERROR {type(e).__name__}: {e}")
