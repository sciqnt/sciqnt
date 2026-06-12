# examples — composition layer

These show units **composed** by the app/agent layer. Units never import each other; the
composition (e.g. resolve→validate→price) lives here, which is what keeps each module
independently usable.

## Canonical / agent-native examples (preferred starting point)

These use the canonical `sq_schema` + `sq_compute` layer. **Read these first**
if you're a code-execution agent figuring out how to use sciqnt.

- `fold_position_demo.py` — FIFO vs LIFO vs AVG cost-basis on the same
  Transaction stream. Demonstrates `sq_compute.fold_position` with all three
  methods; same log → three different realized-P/L outcomes.
- `historical_pit.py` — PIT-correct historical Position via the `asof` parameter.
  Same log, different historical viewpoints, deterministic answers, and the
  returned `Position.valid_at` mirrors the `asof` you asked for (bitemporal honesty).
- `csv_to_canonical_demo.py` — parse a Degiro CSV pair (transactions + account)
  → canonical Transactions → fold into Positions per instrument → fold cash
  balances. The full historical-flavour pipeline against the synthetic fixtures
  (works the same on real exports).

## Older composition examples

These predate the canonical layer; they still work but the canonical path
above is the preferred shape for new work.

- `portfolio_value.py` — composes **sq-degiro** (realized) + **sq-openfigi**
  (ISIN→ticker) + **sq-yahoo** (price + FX) → live multi-currency total for
  the open position.
- `reconcile_check.py` — investigation: do currency-converted dividends close
  the Total-P/L gap vs Degiro's displayed figure?

Each script puts the module `src/` dirs on `sys.path` so it runs without installing. For real
use, `pip install` each bundle (e.g. `pip install ./modules/sq-degiro`).
