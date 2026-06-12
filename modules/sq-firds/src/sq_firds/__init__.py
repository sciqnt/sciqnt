"""sq-firds — ESMA FIRDS reference-data source (official, free, no key).

`resolve_metadata(isin) -> dict | None` mirrors sq-openfigi's contract
(plus `currency` / `cfi` / `lei`). The enrichment rung AFTER OpenFIGI:
FIRDS classifies and names EU-venue instruments (incl. delisted ones)
but carries no tickers — the two complement each other."""
from .resolve import asset_class_from_cfi, resolve_isin, resolve_metadata

__all__ = ["asset_class_from_cfi", "resolve_isin", "resolve_metadata"]
