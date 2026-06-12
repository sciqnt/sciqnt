#!/usr/bin/env python3
"""sq-fx-ecb show — fetch and print an FX rate."""
import argparse
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(ROOT / "modules" / "sq-fx-ecb" / "src"))

from sq_fx_ecb import ECBProvider                          # noqa: E402
from sq_tui import BOLD, DIM, RST, status                  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Fetch and print an FX rate from ECB.")
    ap.add_argument("from_ccy", help="source currency (e.g. EUR / USD)")
    ap.add_argument("to_ccy",   help="target currency (e.g. USD / EUR)")
    ap.add_argument("--asof",   help="historical date YYYY-MM-DD (default: latest daily)")
    args = ap.parse_args()

    asof = None
    if args.asof:
        try:
            asof = date.fromisoformat(args.asof)
        except ValueError:
            sys.exit(f"invalid --asof date: {args.asof!r} (expected YYYY-MM-DD)")

    src = args.from_ccy.upper()
    dst = args.to_ccy.upper()
    status(f"fetching ECB rate {src} → {dst}{'  asof ' + str(asof) if asof else ''} …")
    provider = ECBProvider()
    rate = provider.get_rate(src, dst, asof=asof)
    if rate is None:
        sys.exit("no rate available (unknown currency, or asof outside 90-day window)")

    print()
    print(f"  {BOLD}1 {rate.from_currency} = {rate.rate} {rate.to_currency}{RST}")
    print(f"  {DIM}source: {rate.source}  ·  valid_at: {rate.valid_at.date()}{RST}")
    print()


if __name__ == "__main__":
    main()
