"""TiingoProvider — `sq_schema.PriceProvider` over Tiingo's daily EOD API.

The official-API rung of the price chain: Yahoo (unofficial, broad)
first, Tiingo (official, free key, US-listed only) when Yahoo can't
answer. Mechanics mirror YahooProvider: one full-range fetch per ticker
per process, in-memory series + negative caches, optional archive
write-through and archive fallback.

Key resolution (BYO-key, sovereignty-clean): keychain service
`sq-tiingo` / `api_token` via sq_secrets, env `TIINGO_API_KEY`
fallback. **No key → every call returns None** (the chain just moves
on); nothing prompts, nothing logs the key.

Ticker dialect gate: Tiingo's namespace is plain US-style symbols.
Anything venue-suffixed (`IB01.L`), index (`^GSPC`) or FX (`EURUSD=X`)
is refused locally — no wasted quota, no 404 noise."""
import pathlib
import re
import sys
import urllib.error
from datetime import date, datetime, timezone
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import Price                                       # noqa: E402

from .price import fetch_chart                                    # noqa: E402

_EPOCH_START = date(1970, 1, 1)
_US_TICKER = re.compile(r"^[A-Za-z][A-Za-z0-9\-]*$")

# A rejected key (HTTP 401/403) must be VISIBLE, not silently identical to
# "Tiingo is down" — the user thinks they configured a key and the chain
# quietly serves Yahoo forever. One stderr line per process, then the
# provider degrades to None exactly as before.
_auth_warned = False


def _warn_auth_rejected(code: int) -> None:
    global _auth_warned
    if _auth_warned:
        return
    _auth_warned = True
    print(f"sq-tiingo: API key rejected (HTTP {code}) — check keychain "
          f"sq-tiingo/api_token (or TIINGO_API_KEY)", file=sys.stderr)


def _supported(ticker: str) -> bool:
    """Plain US-style symbols only. In the canonical (Yahoo-style)
    vocabulary a DOT is always a venue suffix (`IB01.L`, `ASML.AS`) —
    class shares are already dash-spelled (`BRK-B`), which is Tiingo's
    dialect too, so supported symbols pass through verbatim. Indices
    (`^GSPC`) and FX (`EURUSD=X`) are refused."""
    if ticker.startswith("^") or "=" in ticker or "." in ticker:
        return False
    return bool(_US_TICKER.match(ticker))


def _resolve_token() -> Optional[str]:
    try:
        import sq_secrets
        return sq_secrets.get_secret("sq-tiingo", "api_token",
                                     env_var="TIINGO_API_KEY")
    except Exception:                                  # noqa: BLE001
        import os
        return os.environ.get("TIINGO_API_KEY")


class TiingoProvider:
    """`PriceProvider` over Tiingo daily EOD. asof=None serves the most
    recent close (this is an EOD source — no intraday quote; declared).
    Returns None on any error or for unsupported symbols."""

    def __init__(self, *,
                 fetch_chart: Optional[Callable] = None,
                 token: Optional[str] = None,
                 store=None):
        self._fetch_chart = fetch_chart or _default_fetch_chart
        self._token = token
        self._store = store
        self._series_cache: dict = {}
        self._sorted_dates: dict = {}
        self._series_meta: dict = {}
        self._failed: set = set()

    def _get_token(self) -> Optional[str]:
        if self._token is None:
            self._token = _resolve_token() or ""
        return self._token or None

    def _record(self, ticker: str, chart: dict) -> None:
        if self._store is None:
            return
        try:
            self._store.record_series(ticker, chart["series"],
                                      currency=chart.get("currency"),
                                      source="tiingo")
            if chart.get("dividends"):
                self._store.record_events(ticker, chart["dividends"],
                                          kind="div", source="tiingo")
            if chart.get("splits"):
                self._store.record_events(ticker, chart["splits"],
                                          kind="split", source="tiingo")
        except Exception:                              # noqa: BLE001
            pass

    def _load_archived(self, ticker: str) -> Optional[dict]:
        if self._store is None:
            return None
        try:
            arch = self._store.load_series(ticker)
        except Exception:                              # noqa: BLE001
            return None
        if not arch:
            return None
        series = arch["series"]
        self._series_meta[ticker] = {"currency": arch.get("currency"),
                                     "from_archive": True}
        self._series_cache[ticker] = series
        self._sorted_dates[ticker] = sorted(series)
        return series

    def _ensure_series(self, ticker: str) -> Optional[dict]:
        cached = self._series_cache.get(ticker)
        if cached is not None:
            return cached
        if ticker in self._failed:
            return None
        token = self._get_token()
        if token is None:
            return None                       # keyless: chain moves on
        end = datetime.now(timezone.utc).date()
        try:
            chart = self._fetch_chart(ticker, _EPOCH_START, end,
                                      token=token)
            series = chart.get("series") or {}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                _warn_auth_rejected(e.code)            # visible, once
            series = None
        except Exception:                              # noqa: BLE001
            series = None
        if not series:
            archived = self._load_archived(ticker)
            if archived:
                return archived
            self._failed.add(ticker)
            return None
        self._record(ticker, chart)
        self._series_meta[ticker] = {"currency": chart.get("currency")}
        self._series_cache[ticker] = series
        self._sorted_dates[ticker] = sorted(series)
        return series

    def get_price(
        self, ticker: str, *,
        asof: Optional[datetime] = None,
    ) -> Optional[Price]:
        if not _supported(ticker):
            return None
        series = self._ensure_series(ticker)
        if not series:
            return None
        target = (asof.date() if isinstance(asof, datetime) else asof) \
            if asof is not None else datetime.now(timezone.utc).date()
        from bisect import bisect_right
        dates = self._sorted_dates[ticker]
        idx = bisect_right(dates, target)
        if idx == 0:
            return None
        chosen = dates[idx - 1]
        meta = self._series_meta.get(ticker, {})
        return Price(
            valid_at=datetime.combine(chosen, datetime.min.time(),
                                      tzinfo=timezone.utc),
            observed_at=datetime.now(timezone.utc),
            instrument_id=None,
            last_price_local=series[chosen],
            currency=(meta.get("currency") or "USD"),
            source=("tiingo-archive" if meta.get("from_archive")
                    else "tiingo"),
        )


def _default_fetch_chart(ticker, start, end, *, token):
    return fetch_chart(ticker, start, end, token=token)
