"""sq-price-store — the local, append-only, bitemporal price archive.

Every price/dividend/split observation any provider fetches is written
through here. Rationale (research/mvp-connectors.md "PIT price archive"):

- **Independence**: unofficial sources (Yahoo) break or rewrite history;
  the archive keeps the portfolio renderable from local data alone.
- **Self-originated PIT data**: survivorship-free, as-it-was-known-then
  history is exactly what vendors charge for. Ours accrues from $0 the
  day the archive starts. Knowledge-time (`obs`) on every row makes
  honest "what did we believe on date X" queries possible later.
- **The one irreversible decision** (FOUNDATION): append-only with
  valid-time + knowledge-time from day one. This file IS that decision
  applied to market data.

Storage: one JSONL file per ticker under the archive root
(default `~/.local/share/sciqnt/price-archive/`, override with the
`SQ_PRICE_ARCHIVE_PATH` env var or the `root=` parameter). Rows are
never rewritten or deleted; a re-fetch that disagrees with a recorded
value (split-adjustment, restatement) APPENDS the new observation and
reads resolve last-observation-wins. Re-fetching identical values
appends nothing (dedup at write time), so daily refreshes stay O(new).

Prices are stored RAW as the source reported them (including quirks
like GBp pence) plus the raw currency code — normalisation is the
consumer's job at read time, the archive's job is faithfulness.

Stdlib only. Decimals serialised as strings. A malformed line (torn
write, manual edit) is skipped on read, never fatal.
"""
import json
import os
import urllib.parse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

DEFAULT_ROOT = Path.home() / ".local" / "share" / "sciqnt" / "price-archive"


def _archive_root(root: Optional[Path]) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("SQ_PRICE_ARCHIVE_PATH")
    if env:
        return Path(env)
    return DEFAULT_ROOT


def _fname(ticker: str) -> str:
    """Reversible, filesystem-safe name. Tickers carry `^` (indices),
    `=X` (FX), `.L`/`.AS` (venues) — percent-encode everything unsafe."""
    return urllib.parse.quote(ticker, safe="") + ".jsonl"


class PriceStore:
    """Append-only per-ticker archive of price / dividend / split
    observations. All writes dedup against the latest recorded value
    per (kind, date); all reads resolve last-observation-wins."""

    def __init__(self, root: Optional[Path] = None):
        self.root = _archive_root(root)
        # Per-ticker latest-value index used for write-side dedup:
        # {ticker: {(kind, iso_date): value_repr}}
        self._latest: dict = {}

    # ── internals ──────────────────────────────────────────────────────
    def _path(self, ticker: str) -> Path:
        return self.root / _fname(ticker)

    def _read_rows(self, ticker: str) -> list[dict]:
        path = self._path(ticker)
        if not path.is_file():
            return []
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue                      # torn line — skip, never fatal
        return rows

    def _ensure_index(self, ticker: str) -> dict:
        idx = self._latest.get(ticker)
        if idx is None:
            idx = {}
            for row in self._read_rows(ticker):
                key = (row.get("t"), row.get("d"))
                idx[key] = row.get("v")
            self._latest[ticker] = idx
        return idx

    def _append(self, ticker: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        self.root.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r, separators=(",", ":")) + "\n"
                          for r in rows)
        with open(self._path(ticker), "a", encoding="utf-8") as f:
            f.write(payload)
        return len(rows)

    # ── write side ─────────────────────────────────────────────────────
    def record_series(
        self,
        ticker: str,
        series: dict,                  # {date: Decimal} raw source values
        *,
        currency: Optional[str],       # raw source code (may be "GBp"/None)
        source: str,
    ) -> int:
        """Record a daily close series. Appends only dates whose value
        isn't already the latest recorded one. Returns rows appended."""
        idx = self._ensure_index(ticker)
        obs = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for d in sorted(series):
            v = str(series[d])
            key = ("price", d.isoformat())
            if idx.get(key) == v:
                continue
            rows.append({"t": "price", "d": d.isoformat(), "v": v,
                         "ccy": currency, "src": source, "obs": obs})
            idx[key] = v
        return self._append(ticker, rows)

    def record_events(
        self,
        ticker: str,
        events: dict,                  # {date: value} value: Decimal or str
        *,
        kind: str,                     # "div" | "split"
        source: str,
    ) -> int:
        """Record corporate-action events (dividend per share, split
        ratio). Same dedup + append-only semantics as prices."""
        idx = self._ensure_index(ticker)
        obs = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rows = []
        for d in sorted(events):
            v = str(events[d])
            key = (kind, d.isoformat())
            if idx.get(key) == v:
                continue
            rows.append({"t": kind, "d": d.isoformat(), "v": v,
                         "src": source, "obs": obs})
            idx[key] = v
        return self._append(ticker, rows)

    # ── read side ──────────────────────────────────────────────────────
    def load_series(self, ticker: str) -> Optional[dict]:
        """Last-observation-wins daily close series.

        Returns `{"series": {date: Decimal}, "currency": str|None}` or
        None when the archive has nothing for this ticker. Currency is
        the most recently observed raw code (faithful — normalise at the
        consumer, exactly like a live fetch)."""
        rows = self._read_rows(ticker)
        if not rows:
            return None
        series: dict = {}
        currency = None
        for row in rows:                       # file order == append order
            if row.get("t") != "price":
                continue
            try:
                d = date.fromisoformat(row["d"])
                series[d] = Decimal(row["v"])
            except (KeyError, ValueError, InvalidOperation, TypeError):
                continue
            if row.get("ccy"):
                currency = row["ccy"]
        if not series:
            return None
        return {"series": series, "currency": currency}

    def load_events(self, ticker: str, *, kind: str) -> dict:
        """Last-observation-wins event stream ({date: Decimal})."""
        out: dict = {}
        for row in self._read_rows(ticker):
            if row.get("t") != kind:
                continue
            try:
                out[date.fromisoformat(row["d"])] = Decimal(row["v"])
            except (KeyError, ValueError, InvalidOperation, TypeError):
                continue
        return out

    def coverage(self, ticker: str):
        """(first_date, last_date) of archived prices, or None."""
        loaded = self.load_series(ticker)
        if not loaded:
            return None
        dates = loaded["series"].keys()
        return min(dates), max(dates)

    def tickers(self) -> list[str]:
        """Every ticker with an archive file (decoded from filenames)."""
        if not self.root.is_dir():
            return []
        return sorted(
            urllib.parse.unquote(p.name[:-len(".jsonl")])
            for p in self.root.glob("*.jsonl")
        )
