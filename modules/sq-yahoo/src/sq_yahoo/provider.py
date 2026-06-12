"""YahooProvider — `sq_schema.PriceProvider` over Yahoo's chart endpoint.

Supports current and PIT historical queries via `get_price(ticker,
asof=<datetime>)`. When multiple `asof` queries hit the same ticker
within a run, the provider transparently fetches the entire daily-bar
series once (full range, with dividend/split events) and serves
subsequent lookups from memory — turning what would be O(N events ×
M tickers) HTTP calls into O(M).

Archive write-through (optional `store=`, a `sq_price_store.PriceStore`):
every fetched series/event/spot is recorded into the local append-only
bitemporal archive, and when Yahoo itself fails the provider serves the
last archived series instead (source `"yahoo-archive"`) — the portfolio
stays renderable from local data alone. Archive failures never break
pricing (best-effort, both directions). The store is wired by the
APP layer (`sq_platform._make_market_data_providers`); bare library
constructions stay archive-free unless they opt in.
"""
import pathlib
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import Price                                       # noqa: E402

from .price import (fetch_chart, fetch_historical_close,          # noqa: E402
                    fetch_intraday, fetch_quote)

# Full-history window start. Yahoo serves whatever it has from here; one
# wide fetch per ticker per process replaces the old adaptive-widening
# logic AND feeds the archive its maximum depth.
_EPOCH_START = date(1970, 1, 1)


def _normalize_quote(price, raw_ccy):
    """Normalize Yahoo's currency quirks BEFORE any .upper() destroys them:
    LSE instruments quote in PENCE with currency "GBp" (and some feeds "GBX").
    Treating pence as pounds silently overvalues 100× — the classic trap that
    turned a £10k position into £1m in a year-end MTM. Returns (price, "GBP")
    divided by 100 for pence; otherwise (price, CCY.upper())."""
    c = (raw_ccy or "USD")
    if c == "GBp" or c.upper() == "GBX":
        return price / Decimal("100"), "GBP"
    return price, c.upper()


class YahooProvider:
    """`PriceProvider` wrapping `fetch_chart` (series + events + meta in
    one request) with an in-memory per-ticker cache, optional archive
    write-through, and a per-date `fetch_historical_close` fallback.
    Returns `None` on any error — never fabricates a price.

    Injection points (testability / alternative sources):
      fetch            — spot quote        (default `fetch_quote`)
      fetch_historical — per-date close    (default `fetch_historical_close`)
      fetch_chart      — full series+events (default `fetch_chart`)
      fetch_series     — LEGACY: series-only callable `(ticker, start, end)
                         → {date: Decimal}`; when given (and no
                         fetch_chart), the provider uses it plus a one-off
                         quote for currency meta — the pre-archive contract.
      store            — `sq_price_store.PriceStore` or None (off)."""

    def __init__(self, *,
                 fetch: Optional[Callable[[str], dict]] = None,
                 fetch_historical: Optional[Callable] = None,
                 fetch_series: Optional[Callable] = None,
                 fetch_chart: Optional[Callable] = None,
                 store=None):
        self._fetch            = fetch            or fetch_quote
        self._fetch_historical = fetch_historical or fetch_historical_close
        self._fetch_series     = fetch_series
        if fetch_chart is not None:
            self._fetch_chart = fetch_chart
        elif fetch_series is not None:
            self._fetch_chart = None              # legacy injected path
        else:
            from .price import fetch_chart as _default_chart
            self._fetch_chart = _default_chart
        self._store = store
        # Per-ticker cache: ticker -> {date: Decimal} raw closes; meta
        # (currency/exchange/window) lives in _series_meta. Series are
        # fetched lazily on the first asof query and reused for the
        # process lifetime.
        self._series_cache: dict = {}
        # Pre-sorted list of session dates per ticker — built once on
        # ingest so per-asof lookups are O(log n) bisect instead of
        # O(n log n) re-sort.
        self._sorted_dates: dict = {}
        self._series_meta:  dict = {}
        # Negative caches: tickers whose series fetch failed (skip series
        # re-fetch) and whose per-date FALLBACK also failed (skip entirely —
        # dead/delisted symbol). Without these, a history full of dead tickers
        # re-hits Yahoo on EVERY price lookup — seconds of hang per build.
        self._series_failed: set = set()
        self._fallback_failed: set = set()

    # ── archive plumbing (best-effort both directions) ─────────────────
    def _record_chart(self, ticker: str, chart: dict) -> None:
        if self._store is None:
            return
        try:
            self._store.record_series(
                ticker, chart["series"],
                currency=chart.get("currency"), source="yahoo")
            if chart.get("dividends"):
                self._store.record_events(
                    ticker, chart["dividends"], kind="div", source="yahoo")
            if chart.get("splits"):
                self._store.record_events(
                    ticker, chart["splits"], kind="split", source="yahoo")
        except Exception:                              # noqa: BLE001
            pass                  # the archive must never break pricing

    # An archived series may stand in for the live source only this far
    # past its last close. Beyond it, serving the archive would present a
    # months-old close as "current" — return None instead, so the per-date
    # fallback gets its shot and the caller degrades VISIBLY.
    _ARCHIVE_GRACE = timedelta(days=7)

    def _load_archived(self, ticker: str) -> Optional[dict]:
        """Load the last archived series (staleness-bounded: valid_until =
        last archived close + grace, NOT today)."""
        if self._store is None:
            return None
        try:
            arch = self._store.load_series(ticker)
        except Exception:                              # noqa: BLE001
            return None
        if not arch:
            return None
        series = arch["series"]
        self._series_meta[ticker] = {
            "currency": arch.get("currency"), "exchange": None,
            "valid_from": min(series),
            "valid_until": max(series) + self._ARCHIVE_GRACE,
            "from_archive": True,
        }
        self._series_cache[ticker] = series
        self._sorted_dates[ticker] = sorted(series)
        return series

    def _archive_or_fail(self, ticker: str, target: date) -> Optional[dict]:
        """Live fetch failed: serve the archive if it covers `target`
        (within grace), else negative-cache the ticker and return None."""
        archived = self._load_archived(ticker)
        if archived and target <= self._series_meta[ticker]["valid_until"]:
            return archived
        self._series_failed.add(ticker)
        return None

    def _ensure_series(
        self, ticker: str, asof: datetime,
    ) -> Optional[dict]:
        """Ensure we have a daily-bar series for `ticker`. Full range
        (epoch → today) on first use; archive fallback when the live
        fetch fails or returns nothing. Returns the series dict or None."""
        target = asof.date() if isinstance(asof, datetime) else asof
        cached = self._series_cache.get(ticker)
        if cached is not None:
            meta = self._series_meta.get(ticker, {})
            covers_from = meta.get("valid_from")
            if (target <= meta.get("valid_until", target)
                    and (covers_from is None or target >= covers_from)):
                return cached
        if ticker in self._series_failed:                  # known-dead ticker
            return None
        end = datetime.now(timezone.utc).date()
        try:
            if self._fetch_chart is not None:
                chart = self._fetch_chart(ticker, _EPOCH_START, end)
                series = chart.get("series") or {}
                meta = {"currency": chart.get("currency"),
                        "exchange": chart.get("exchange")}
                if series:
                    self._record_chart(ticker, chart)
            else:                                    # legacy injected path
                from datetime import timedelta
                start = min(end - timedelta(days=5 * 366),
                            target - timedelta(days=30))
                series = self._fetch_series(ticker, start, end)
                meta = self._series_meta.get(ticker)
                if meta is None:
                    try:
                        q = self._fetch(ticker)
                        meta = {"currency": q.get("currency"),
                                "exchange": q.get("exchange")}
                    except Exception:                  # noqa: BLE001
                        meta = {"currency": None, "exchange": None}
                if series and self._store is not None:
                    self._record_chart(ticker, {
                        "series": series,
                        "currency": meta.get("currency")})
        except Exception:                              # noqa: BLE001
            return self._archive_or_fail(ticker, target)
        if not series:
            return self._archive_or_fail(ticker, target)
        meta["valid_until"] = end
        meta["valid_from"] = _EPOCH_START if self._fetch_chart else min(series)
        self._series_meta[ticker] = meta
        self._series_cache[ticker] = series
        self._sorted_dates[ticker] = sorted(series.keys())
        return series

    # Intraday bars go stale in minutes — short TTL, NOT process-lifetime.
    _INTRADAY_TTL = 120.0          # seconds

    def get_intraday(self, ticker: str):
        """Today's 5-minute close bars, pence-normalised:
        `({datetime: Decimal}, currency)` or None. 120s in-memory TTL;
        deliberately NOT archived (the price store is daily-keyed)."""
        import time as _time
        cached = getattr(self, "_intraday_cache", None)
        if cached is None:
            cached = self._intraday_cache = {}
        hit = cached.get(ticker)
        if hit and (_time.monotonic() - hit[0]) < self._INTRADAY_TTL:
            return hit[1]
        try:
            raw = fetch_intraday(ticker)
        except Exception:                              # noqa: BLE001
            return hit[1] if hit else None     # stale beats nothing
        bars = raw.get("bars") or {}
        if not bars:
            result = None
        else:
            ccy = raw.get("currency")
            norm = {}
            for dt, px in bars.items():
                npx, nccy = _normalize_quote(px, ccy)
                norm[dt] = npx
            result = (norm, nccy)
        cached[ticker] = (_time.monotonic(), result)
        return result

    def get_price(
        self, ticker: str, *,
        asof: Optional[datetime] = None,
    ) -> Optional[Price]:
        if asof is None:
            try:
                q = self._fetch(ticker)
            except Exception:                              # noqa: BLE001
                return None
            if not q or q.get("price") is None:
                return None
            # Record the spot into the archive (raw price, raw ccy) — it
            # is today's best-known value until a real close lands and
            # supersedes it (last-observation-wins on read).
            if self._store is not None:
                try:
                    self._store.record_series(
                        ticker,
                        {datetime.now(timezone.utc).date(): q["price"]},
                        currency=q.get("currency"), source="yahoo-spot")
                except Exception:                          # noqa: BLE001
                    pass
            px, ccy = _normalize_quote(q["price"], q.get("currency"))
            return Price(
                valid_at=datetime.now(timezone.utc),
                observed_at=datetime.now(timezone.utc),
                instrument_id=None,
                last_price_local=px,
                currency=ccy,
                source="yahoo",
            )

        # asof path: try the in-memory series first
        series = self._ensure_series(ticker, asof)
        if series:
            target = asof.date() if isinstance(asof, datetime) else asof
            # Bisect into the pre-sorted dates: O(log n) per lookup
            # instead of resorting the whole series on every call.
            from bisect import bisect_right
            dates = self._sorted_dates.get(ticker) or sorted(series.keys())
            idx = bisect_right(dates, target)
            if idx > 0:
                chosen = dates[idx - 1]
                meta = self._series_meta.get(ticker, {})
                px, ccy = _normalize_quote(series[chosen],
                                           meta.get("currency"))
                return Price(
                    valid_at=datetime.combine(chosen, datetime.min.time(),
                                              tzinfo=timezone.utc),
                    observed_at=datetime.now(timezone.utc),
                    instrument_id=None,
                    last_price_local=px,
                    currency=ccy,
                    source=("yahoo-archive" if meta.get("from_archive")
                            else "yahoo"),
                )
        # Fallback: per-date fetch (small window) — preserves the older
        # contract for callers that injected only fetch_historical (a failed
        # SERIES fetch must still get one shot here). But a ticker whose
        # fallback ALSO failed is dead — skip it from then on, or a history
        # full of delisted tickers costs one network round-trip per
        # (ticker, date) on every summary build.
        if ticker in self._fallback_failed:
            return None
        try:
            q = self._fetch_historical(ticker, asof)
        except Exception:                                  # noqa: BLE001
            self._fallback_failed.add(ticker)
            return None
        if not q or q.get("price") is None:
            return None
        px, ccy = _normalize_quote(q["price"], q.get("currency"))
        return Price(
            valid_at=q.get("valid_at") or datetime.now(timezone.utc),
            observed_at=datetime.now(timezone.utc),
            instrument_id=None,
            last_price_local=px,
            currency=ccy,
            source="yahoo",
        )
