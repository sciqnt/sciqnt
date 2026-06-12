"""sq-edgar — SEC EDGAR filings + fundamentals (official, free, no key).

`resolve_cik(ticker)`, `recent_filings(ticker, forms=…)` and
`fundamentals_lite(ticker)` over the SEC's public JSON APIs. CONTEXT
ONLY — nothing here feeds the deterministic money core. Set
`SQ_EDGAR_CONTACT` to your email (SEC fair-access policy)."""
from .edgar import fundamentals_lite, recent_filings, resolve_cik

__all__ = ["fundamentals_lite", "recent_filings", "resolve_cik"]
