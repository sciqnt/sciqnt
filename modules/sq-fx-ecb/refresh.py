#!/usr/bin/env python3
"""sq-fx-ecb refresh — clear cache + refetch latest rates."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-fx-ecb" / "src"))

from sq_fx_ecb import ECBProvider                          # noqa: E402
from sq_fx_ecb.cache import DEFAULT_CACHE_DIR              # noqa: E402
from sq_tui import DIM, RST, status                        # noqa: E402


def main():
    if DEFAULT_CACHE_DIR.exists():
        for f in DEFAULT_CACHE_DIR.glob("*.xml"):
            f.unlink()
            print(f"  removed {f.name}")
    status("refetching latest daily rates from ECB …")
    provider = ECBProvider()
    rate = provider.get_rate("EUR", "USD")
    if rate is None:
        sys.exit("refresh failed (network? — ECB endpoint unreachable)")
    print(f"  {DIM}cache dir: {DEFAULT_CACHE_DIR}{RST}")
    print(f"  {DIM}1 EUR = {rate.rate} USD on {rate.valid_at.date()}{RST}")


if __name__ == "__main__":
    main()
