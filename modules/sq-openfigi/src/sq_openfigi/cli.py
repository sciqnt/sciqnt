#!/usr/bin/env python3
"""sq-openfigi CLI — resolve an ISIN to ticker/listing metadata on the command
line, so the bundle is usable standalone and appears in the module browser."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                 # bundle src/

from sq_openfigi.resolve import resolve_metadata          # noqa: E402


def main(argv):
    if len(argv) >= 2 and argv[0] == "resolve":
        isin = argv[1].strip().upper()
        try:
            meta = resolve_metadata(isin)
        except Exception as e:                               # noqa: BLE001
            print(f"resolve failed for {isin}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
        if not meta:
            print(f"{isin}: no OpenFIGI match")
            return 1
        for k in ("isin", "name", "ticker", "yahoo_ticker",
                  "asset_class", "exch_code"):
            print(f"  {k:<13} {meta.get(k) or '—'}")
        return 0
    print("usage: sq-openfigi resolve <ISIN>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
