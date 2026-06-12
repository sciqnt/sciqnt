#!/usr/bin/env python3
"""sq-yahoo CLI — line-output quote / historical-close lookups, so the bundle
is usable standalone and shows up in the module browser (`--describe` /
`--commands` contract lives in bin/sq-yahoo; this is just the doing)."""
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))                 # bundle src/

from sq_yahoo.price import (fetch_chart, fetch_historical_close,  # noqa: E402
                            fetch_quote)


def main(argv):
    if len(argv) >= 2 and argv[0] == "quote":
        try:
            q = fetch_quote(argv[1])
        except Exception as e:                               # noqa: BLE001
            print(f"quote failed for {argv[1]}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
        print(f"{q['ticker']}  {q['price']} {q.get('currency') or ''}  "
              f"({q.get('exchange') or 'n/a'})")
        return 0
    if len(argv) >= 2 and argv[0] == "history":
        try:
            c = fetch_chart(argv[1], date(1970, 1, 1), date.today())
        except Exception as e:                               # noqa: BLE001
            print(f"history failed for {argv[1]}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
        series = c["series"]
        if not series:
            print(f"{argv[1]}: no history")
            return 1
        first, last = min(series), max(series)
        print(f"{argv[1]}  {len(series)} daily closes  "
              f"{first} → {last}  ccy={c.get('currency') or '?'}  "
              f"dividends={len(c['dividends'])}  splits={len(c['splits'])}")
        for d in sorted(series)[-5:]:
            print(f"  {d}  {series[d]}")
        return 0
    if len(argv) >= 3 and argv[0] == "close":
        try:
            d = date.fromisoformat(argv[2])
        except ValueError:
            print(f"bad date {argv[2]!r} — use YYYY-MM-DD", file=sys.stderr)
            return 2
        try:
            q = fetch_historical_close(argv[1], d)
        except Exception as e:                               # noqa: BLE001
            print(f"close failed for {argv[1]} @ {d}: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            return 1
        sess = q.get("valid_at")
        sess = f"  (session {sess})" if sess else ""
        print(f"{q['ticker']}  {q['price']} {q.get('currency') or ''}{sess}")
        return 0
    print("usage: sq-yahoo quote <ticker> | close <ticker> <YYYY-MM-DD>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
