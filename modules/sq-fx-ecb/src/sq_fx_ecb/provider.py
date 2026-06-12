"""ECBProvider — `FxRateProvider` backed by ECB's public daily reference rates.

ECB ships rates as `1 EUR = rate units of CCY`. For non-EUR pairs we
triangulate via EUR (no precision loss at ECB's quoted scale; the inverse
introduces ~1e-10 rounding which is well below money-display granularity).

No auth, no rate limits worth fearing. Cache TTL handles courtesy.
"""
import pathlib
import sys
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

# Resolve sq_schema from core/
ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import FxRate                                       # noqa: E402

from .cache import DEFAULT_CACHE_DIR, TTL_DAILY, TTL_HIST, get_or_fetch
from .parser import parse_ecb_xml

ECB_DAILY_URL    = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_HIST_90D_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
ECB_HIST_FULL_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"


def _http_fetch(url: str) -> bytes:
    """Default fetcher — stdlib only so the bundle has zero runtime deps."""
    with urllib.request.urlopen(url, timeout=15) as resp:           # noqa: S310 (well-known public URL)
        return resp.read()


class ECBProvider:
    """`FxRateProvider` over ECB EUR-cross reference rates.

    Construction takes optional `cache_dir` and `fetch` callables for
    testability — production code uses the XDG default cache + urllib.
    """

    def __init__(
        self,
        *,
        cache_dir: Optional[Path] = None,
        fetch: Optional[Callable[[str], bytes]] = None,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._fetch = fetch or _http_fetch
        # In-memory cache of the parsed XML — keyed by URL. Without this,
        # every `get_rate(asof=…)` call re-parses ~1MB of XML (~470ms),
        # which dominates the TWR build's wall-clock when sampling 50
        # dates × N currencies. The on-disk cache handles fetch
        # avoidance; this handles parse avoidance.
        self._parsed_cache: dict = {}

    # ── internal: load the right ECB file for `asof` ───────────────────
    def _load(self, url: str, key: str, ttl: int) -> dict[date, dict[str, Decimal]]:
        cached = self._parsed_cache.get(url)
        if cached is not None:
            return cached
        xml_bytes = get_or_fetch(
            self.cache_dir, key,
            lambda: self._fetch(url),
            ttl_seconds=ttl,
        )
        parsed = parse_ecb_xml(xml_bytes)
        self._parsed_cache[url] = parsed
        return parsed

    def _eur_rates_for(self, asof: Optional[date]) -> Optional[tuple[date, dict[str, Decimal]]]:
        """Return (date, {ccy: rate_eur_to_ccy}) closest to `asof` (≤ asof).
        None = use the latest daily file (fast path).

        Within the last 90 days we use the small `eurofxref-hist-90d.xml`
        (~30 KB). Beyond that we transparently fall back to the full
        `eurofxref-hist.xml` (everything since 1999, ~1 MB) so historical
        TWR / drawdown / PIT views work back to the start of EUR."""
        if asof is None:
            data = self._load(ECB_DAILY_URL, "daily", TTL_DAILY)
            if not data:
                return None
            latest = max(data.keys())
            return latest, data[latest]

        from datetime import timedelta
        today = datetime.now(timezone.utc).date()
        # Pick the smaller file when the request is recent enough
        if (today - asof).days <= 80:                # buffer under 90
            data = self._load(ECB_HIST_90D_URL, "hist90d", TTL_HIST)
        else:
            data = self._load(ECB_HIST_FULL_URL, "hist_full", TTL_HIST)
        if not data:
            return None
        # ECB skips weekends/holidays; pick the most recent published date <= asof
        candidates = sorted(d for d in data.keys() if d <= asof)
        if not candidates:
            return None
        chosen = candidates[-1]
        return chosen, data[chosen]

    # ── FxRateProvider interface ───────────────────────────────────────
    def get_rate(
        self,
        from_currency: str,
        to_currency: str,
        asof: Optional[date] = None,
    ) -> Optional[FxRate]:
        # Identity short-circuit — consumer can rely on us being safe here
        if from_currency == to_currency:
            now = datetime.now(timezone.utc)
            return FxRate(
                valid_at=now, observed_at=now,
                from_currency=from_currency, to_currency=to_currency,
                rate=Decimal("1"), source="ecb",
            )

        loaded = self._eur_rates_for(asof)
        if loaded is None:
            return None
        rate_date, eur_rates = loaded

        # Three cases: EUR-to-X, X-to-EUR (invert), X-to-Y (triangulate via EUR)
        if from_currency == "EUR":
            rate = eur_rates.get(to_currency)
            if rate is None:
                return None
        elif to_currency == "EUR":
            r = eur_rates.get(from_currency)
            if r is None or r == 0:
                return None
            rate = Decimal(1) / r
        else:
            from_rate = eur_rates.get(from_currency)
            to_rate   = eur_rates.get(to_currency)
            if from_rate is None or to_rate is None or from_rate == 0:
                return None
            rate = to_rate / from_rate

        valid_at = datetime.combine(rate_date, datetime.min.time(), tzinfo=timezone.utc)
        return FxRate(
            valid_at=valid_at,
            observed_at=datetime.now(timezone.utc),
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            source="ecb",
        )
