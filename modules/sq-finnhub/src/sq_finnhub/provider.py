"""FinnhubNewsProvider — `sq_schema.NewsProvider`, the keyed news rung.

Mechanics mirror RssNewsProvider (process-lifetime per-ticker cache,
failures degrade to []) plus the keyless-inert behaviour of
TiingoProvider: no key → every call returns [] without fetching, and
the platform's news chain falls through to the RSS rung."""
import pathlib
import sys
import urllib.error
from datetime import datetime, timezone
from typing import Callable, Optional

ROOT = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "core"))

from sq_schema import NewsItem                                    # noqa: E402

from .news import fetch_company_news                              # noqa: E402

# A rejected key (HTTP 401/403) must be VISIBLE, not silently identical to
# "Finnhub is down" — otherwise the user thinks the key works and the news
# chain quietly serves RSS forever. One stderr line per process, then the
# provider degrades to [] exactly as before.
_auth_warned = False


def _warn_auth_rejected(code: int) -> None:
    global _auth_warned
    if _auth_warned:
        return
    _auth_warned = True
    print(f"sq-finnhub: API key rejected (HTTP {code}) — check keychain "
          f"sq-finnhub/api_token (or FINNHUB_API_KEY)", file=sys.stderr)


def _resolve_token() -> Optional[str]:
    try:
        import sq_secrets
        return sq_secrets.get_secret("sq-finnhub", "api_token",
                                     env_var="FINNHUB_API_KEY")
    except Exception:                                  # noqa: BLE001
        import os
        return os.environ.get("FINNHUB_API_KEY")


class FinnhubNewsProvider:
    def __init__(self, *, fetch: Optional[Callable] = None,
                 token: Optional[str] = None):
        self._fetch = fetch or fetch_company_news
        self._token = token
        self._cache: dict = {}
        self._failed: set = set()

    def _get_token(self) -> Optional[str]:
        if self._token is None:
            self._token = _resolve_token() or ""
        return self._token or None

    def get_news(self, ticker: str, *, limit: int = 5) -> list:
        token = self._get_token()
        if token is None:
            return []                          # keyless: chain moves on
        cached = self._cache.get(ticker)
        if cached is None:
            if ticker in self._failed:
                return []
            try:
                raw = self._fetch(ticker, token=token)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    _warn_auth_rejected(e.code)        # visible, once
                self._failed.add(ticker)
                return []
            except Exception:                  # noqa: BLE001
                self._failed.add(ticker)
                return []
            now = datetime.now(timezone.utc)
            cached = [
                NewsItem(
                    valid_at=item.get("published_at") or now,
                    observed_at=now,
                    headline=item["headline"],
                    url=item.get("url"),
                    summary=item.get("summary"),
                    ticker=ticker,
                    source="finnhub",
                )
                for item in raw
            ]
            self._cache[ticker] = cached
        return cached[:limit]
