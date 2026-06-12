#!/usr/bin/env python3
"""SEC EDGAR — official, free filings + fundamentals for US-listed companies.

The highest-value FREE dataset in finance (research/05): company facts
(XBRL financial statements as JSON), submissions (every filing incl.
8-K material events and Form 4 insider trades), and the ticker→CIK map.

CONTEXT ONLY: nothing from EDGAR feeds the deterministic money core —
fundamentals and filings inform the reader/agent, like news.

SEC fair-access rules: declared User-Agent with contact info (set
`SQ_EDGAR_CONTACT` to your email — default is the project string), max
10 req/s (we do single-digit requests with on-disk caching).

Usage:
    python3 edgar.py AAPL            # fundamentals + recent filings
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "sciqnt" / "edgar"
TTL_TICKER_MAP = 7 * 24 * 3600          # the map churns slowly
TTL_SUBMISSIONS = 12 * 3600
TTL_FACTS = 24 * 3600

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _ua() -> str:
    """SEC's fair-access policy requires an email-shaped contact token in
    the User-Agent (live-verified: a UA without one gets 403). Set
    `SQ_EDGAR_CONTACT` to YOUR email — the default is a deliberate
    placeholder that passes but identifies nobody; be a good citizen."""
    contact = os.environ.get("SQ_EDGAR_CONTACT",
                             "unconfigured@sciqnt.invalid")
    return f"sciqnt/0 {contact}"


def _get_json(url: str, cache_key: str, ttl: int) -> dict:
    """Fetch with a tiny on-disk cache (atomic writes, XDG-style dir).
    Bundles stay independent — this is the same shape as sq-fx-ecb's
    helper, deliberately not imported from it."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{cache_key}.json"
    if path.is_file() and (time.time() - path.stat().st_mtime) < ttl:
        try:
            return json.loads(path.read_text())
        except Exception:                              # noqa: BLE001
            pass                                       # corrupt → refetch
    req = urllib.request.Request(url, headers={"User-Agent": _ua()})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)
    return data


def resolve_cik(ticker: str) -> int | None:
    """Ticker → CIK via the SEC's published map (cached 7 days)."""
    data = _get_json(TICKER_MAP_URL, "company_tickers", TTL_TICKER_MAP)
    want = ticker.upper()
    for row in data.values():
        if row.get("ticker") == want:
            return int(row["cik_str"])
    return None


def recent_filings(ticker: str, *, forms=None, limit: int = 20) -> list[dict]:
    """Most recent filings for `ticker`, newest first. `forms` filters
    (e.g. {"8-K", "4", "10-K"}). Each item:
    `{form, filed (date str), accession, primary_doc, url, description}`.
    [] when the ticker isn't SEC-registered."""
    cik = resolve_cik(ticker)
    if cik is None:
        return []
    data = _get_json(SUBMISSIONS_URL.format(cik=cik),
                     f"submissions_{cik}", TTL_SUBMISSIONS)
    recent = data.get("filings", {}).get("recent", {})
    out = []
    rows = zip(recent.get("form", []), recent.get("filingDate", []),
               recent.get("accessionNumber", []),
               recent.get("primaryDocument", []),
               recent.get("primaryDocDescription", []))
    for form, filed, accession, doc, desc in rows:
        if forms and form not in forms:
            continue
        acc_nodash = accession.replace("-", "")
        out.append({
            "form": form,
            "filed": filed,
            "accession": accession,
            "primary_doc": doc,
            "url": (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                    f"{acc_nodash}/{doc}") if doc else None,
            "description": desc or None,
        })
        if len(out) >= limit:
            break
    return out


# us-gaap tag fallback chains for the fundamentals-lite picks. Filers
# use different tags for the same concept; first present wins.
_FACT_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "total_assets": ["Assets"],
    "equity": ["StockholdersEquity",
               ("StockholdersEquityIncludingPortionAttributableTo"
                "NoncontrollingInterest")],
}


def _latest_annual(units: dict) -> dict | None:
    """The most recent FY (10-K) datapoint across whatever unit the tag
    reports in (USD, USD/shares, …)."""
    best = None
    for rows in units.values():
        for row in rows:
            if row.get("form") != "10-K" or row.get("fp") != "FY":
                continue
            if row.get("val") is None or not row.get("end"):
                continue
            if best is None or row["end"] > best["end"]:
                best = row
    return best


def fundamentals_lite(ticker: str) -> dict | None:
    """Latest-fiscal-year headline figures from companyfacts XBRL.
    Decimal-valued, source-dated; None when the ticker isn't SEC-
    registered. Shape::

        {"entity": str, "fiscal_year_end": str,
         "revenue": Decimal|None, "net_income": Decimal|None,
         "eps_diluted": Decimal|None, "total_assets": Decimal|None,
         "equity": Decimal|None}
    """
    cik = resolve_cik(ticker)
    if cik is None:
        return None
    data = _get_json(FACTS_URL.format(cik=cik), f"facts_{cik}", TTL_FACTS)
    gaap = data.get("facts", {}).get("us-gaap", {})
    out = {"entity": data.get("entityName"), "fiscal_year_end": None}
    for key, tags in _FACT_TAGS.items():
        value = None
        for tag in tags:
            fact = gaap.get(tag)
            if not fact:
                continue
            row = _latest_annual(fact.get("units", {}))
            if row is not None:
                value = Decimal(str(row["val"]))
                if out["fiscal_year_end"] is None or \
                        row["end"] > out["fiscal_year_end"]:
                    out["fiscal_year_end"] = row["end"]
                break
        out[key] = value
    return out


if __name__ == "__main__":
    for t in sys.argv[1:] or ["AAPL"]:
        try:
            f = fundamentals_lite(t)
            if f is None:
                print(f"{t}: not SEC-registered")
                continue
            print(f"{t}: {f['entity']} (FY end {f['fiscal_year_end']})")
            for k in ("revenue", "net_income", "eps_diluted",
                      "total_assets", "equity"):
                print(f"  {k:13} {f[k]:,}" if f[k] is not None
                      else f"  {k:13} —")
            print("  recent filings:")
            for item in recent_filings(t, forms={"10-K", "10-Q", "8-K", "4"},
                                       limit=5):
                print(f"    {item['filed']}  {item['form']:5} "
                      f"{item['description'] or ''}")
        except Exception as e:                                 # noqa: BLE001
            # One ticker failing (network, 403 UA, schema drift) must not
            # kill the whole batch — same convention as sibling CLIs.
            print(f"{t}: ERROR: {type(e).__name__}: {e}")
