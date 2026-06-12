"""sq-config — user-level configuration substrate for sciqnt.

Stores small JSON config under `~/.config/sciqnt/config.json` by default
(XDG-style, NOT in the repo — the user's settings are user-owned, sovereign,
and survive `git clean -fdx`). Test/CI override the path via `SQ_CONFIG_PATH`.

Schema-driven. Every user-facing setting is declared once in `SCHEMA` (key,
type, allowed values, default, help, which engine consumes it). From that the
module can:
  * MATERIALISE a documented config.json on first run (so the file exists, is
    discoverable, and is hand-editable — no more "it's lazy and invisible"),
  * default `get()` from the schema (callers needn't hard-code fallbacks),
  * VALIDATE `set()` against the allowed values,
  * render `config show` with value + default + help per setting.

API:
  get(key, default=None) -> value          (file → arg → schema default)
  set(key, value)        -> None           (validates; atomic write)
  all()                  -> dict           (raw file contents)
  materialise()          -> dict           (write defaults for any missing key)
  schema()               -> list[Setting]
  path()                 -> Path

Bundles that need configuration MUST go through this module (never read
their own JSON / dotenv for user-level settings).
"""
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class Setting:
    """One configurable setting. `allowed=None` means free-form; otherwise the
    value must be one of `allowed`. `mvp=False` marks a setting whose consuming
    engine isn't fully wired yet (declared now, honoured later)."""
    key: str
    default: Any
    type: str = "str"                 # str | enum | bool | int
    allowed: Optional[list] = None
    group: str = "general"
    help: str = ""
    consumed_by: str = ""
    mvp: bool = True


# ── the schema (single source of truth) ────────────────────────────────────
# Seeded with the settings we're confident about today. The jurisdiction- and
# methodology-nuanced ones (tax_jurisdiction, performance_basis, dividend
# treatment, FX timing, …) are being pinned by research and will be ADDED here
# — the registry mechanism below doesn't change when they land.
# `mvp=True`  → wired: an engine actually reads it and behaviour changes.
# `mvp=False` → declared but not yet honoured (grounded by research, shown in
#               `config show` as forward-looking). See
#               research/config-settings-cross-asset.md for the full rationale,
#               jurisdiction defaults, and honest gaps behind each setting.
SCHEMA: list[Setting] = [
    # ── display (global, wired) ─────────────────────────────────────────────
    Setting(
        key="display_currency", default="USD", type="str", group="display",
        help="Currency for cross-asset totals & summaries.",
        consumed_by="sq_aggregator, summary/home",
    ),
    # ── agents (the 'use agent to …' launcher) ───────────────────────────────
    Setting(
        key="preferred_agent", default="auto", type="enum",
        allowed=["auto", "claude", "codex", "openclaw", "gemini", "aider"],
        group="agents",
        help="Coding agent the 'use agent to …' actions launch (like a default "
             "browser). 'auto' = first installed. Only installed agents run; if "
             "none are installed the action shows install hints. (Allowed list "
             "mirrors sq_agents.NAMES.)",
        consumed_by="sq_agents",
    ),
    # ── accounting (cost basis is wired; fees-toggle declared) ───────────────
    Setting(
        key="cost_basis_method", default="FIFO", type="enum",
        allowed=["FIFO", "LIFO", "AVG"], group="accounting",
        help="Lot-matching for realised P&L. AVG = average-cost / ACB / "
             "Section-104 pool / Degiro BEP. (HIFO & UK same-day/30-day "
             "matching not yet implemented.)",
        consumed_by="sq_compute.fold_position",
    ),
    Setting(
        key="fees_in_cost_basis", default=True, type="bool", group="accounting",
        help="Capitalise commissions/fees into cost basis (vs expensing them). "
             "The engine is currently always fees-inclusive; the off-toggle is "
             "not yet wired.",
        consumed_by="sq_compute.fold_position", mvp=False,
    ),
    # ── tax / jurisdiction (declared; no tax engine yet) ─────────────────────
    Setting(
        key="tax_jurisdiction", default="OTHER", type="enum",
        allowed=["US", "UK", "CA", "AU", "IE", "EU", "OTHER"], group="tax",
        help="Tax residency. The anchor that should set the legal defaults for "
             "cost basis, tax-year boundaries, CGT allowance & wash-sale. No "
             "tax engine consumes it yet.",
        consumed_by="(future) tax engine", mvp=False,
    ),
    Setting(
        key="tax_year_start", default="01-01", type="str", group="tax",
        help="Personal tax-year start (MM-DD). UK=04-06, AU=07-01, US/most "
             "jurisdictions=01-01.",
        consumed_by="(future) tax engine", mvp=False,
    ),
    # ── performance methodology (both computed; selector + GIPS guard wired) ─
    Setting(
        key="performance_return_method", default="TWR", type="enum",
        allowed=["TWR", "MWR"], group="performance",
        help="Headline return: time-weighted (manager skill, GIPS default) vs "
             "money-weighted / XIRR (your personal cash-flow experience). The "
             "engine computes both; this flags which the summary marks primary.",
        consumed_by="sq_platform.aggregated (summary)",
    ),
    Setting(
        key="annualize_sub_year_returns", default=False, type="bool",
        group="performance",
        help="Annualise the time-weighted return for holding periods under one "
             "year. GIPS I.5.A.4 prohibits this; keep false. (Applies to TWR; "
             "XIRR is annualised by construction — an honest gap.)",
        consumed_by="sq_platform.aggregated (per-broker TWR)",
    ),
    Setting(
        key="benchmark", default="IWDA.AS", type="str", group="performance",
        help="Ticker compared against each broker's TWR over the same period "
             "(any symbol the price source knows: IWDA.AS = MSCI World UCITS, "
             "CSPX.AS / ^GSPC = S&P 500, …). PRICE return of the benchmark — "
             "distributing-fund dividends aren't added back; accumulating "
             "ETFs (IWDA, CSPX) compare honestly. 'none' disables.",
        consumed_by="sq_platform.aggregated (per-broker benchmark line)",
    ),
]

_BY_KEY = {s.key: s for s in SCHEMA}


def schema() -> list[Setting]:
    """The setting registry (single source of truth). Ordered as declared."""
    return list(SCHEMA)


def path():
    """Resolve the config file path. SQ_CONFIG_PATH overrides for tests/CI."""
    env = os.environ.get("SQ_CONFIG_PATH")
    if env:
        return Path(env)
    return Path.home() / ".config" / "sciqnt" / "config.json"


def all():
    """Return the full config dict. {} if the file doesn't exist."""
    p = path()
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        # Corrupt / unreadable -> treat as empty so callers degrade gracefully.
        return {}


def get(key, default=None):
    """Read a setting. Precedence: file value → explicit `default` arg →
    the schema default → None. So callers needn't repeat fallbacks for
    schema-declared keys."""
    data = all()
    if key in data:
        return data[key]
    if default is not None:
        return default
    s = _BY_KEY.get(key)
    return s.default if s else None


def _validate(key, value):
    """Coerce/validate `value` for a schema-declared key. Raises ValueError on
    a bad enum / non-boolean. Unknown keys pass through (forward-compatible)."""
    s = _BY_KEY.get(key)
    if s is None:
        return value
    if s.type == "enum" and s.allowed is not None and value not in s.allowed:
        raise ValueError(f"{key!r} must be one of {s.allowed}; got {value!r}")
    if s.type == "bool" and not isinstance(value, bool):
        low = str(value).lower()
        if low in ("true", "1", "yes", "on"):
            return True
        if low in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key!r} must be a boolean; got {value!r}")
    if s.type == "int" and not isinstance(value, bool):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key!r} must be an integer; got {value!r}")
    return value


def _write(data: dict):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    os.replace(tmp, p)


def set(key, value):
    """Write a single config value (validated against the schema). Creates the
    parent dir; writes atomically (tmp + rename) so a crash mid-write can't
    corrupt the file."""
    value = _validate(key, value)
    data = all()
    data[key] = value
    _write(data)


def materialise() -> dict:
    """Ensure config.json exists and carries every schema key. Missing keys are
    written with their defaults; existing user values are LEFT UNTOUCHED
    (non-destructive). Called on first run so the file is discoverable +
    hand-editable. Returns the resulting config dict.

    (British spelling intentional — this codebase is British-English.)"""
    data = all()
    changed = not path().is_file()
    for s in SCHEMA:
        if s.key not in data:
            data[s.key] = s.default
            changed = True
    if changed:
        _write(data)
    return data


# ── well-known accessors ───────────────────────────────────────────────────
DISPLAY_CURRENCY = "display_currency"
PREFERRED_AGENT = "preferred_agent"
COST_BASIS_METHOD = "cost_basis_method"
PERFORMANCE_RETURN_METHOD = "performance_return_method"
ANNUALIZE_SUB_YEAR_RETURNS = "annualize_sub_year_returns"
BENCHMARK = "benchmark"


def display_currency(fallback=None):
    """User's preferred currency for cross-asset totals / summary displays.
    Modules MUST use this — never hard-code a display currency."""
    return get(DISPLAY_CURRENCY, fallback)


def preferred_agent(fallback=None):
    """User's preferred coding agent for the 'use agent to …' actions
    ('auto'|'claude'|'codex'|…). `sq_agents.resolve()` maps this to an installed
    agent (or the first detected) — the core never launches anything itself."""
    return get(PREFERRED_AGENT, fallback)


def cost_basis_method(fallback=None):
    """User's lot-matching method ('FIFO'|'LIFO'|'AVG'). Engines pass this to
    `sq_compute.fold_position(method=…)` — the deterministic core stays pure
    and never imports config itself."""
    return get(COST_BASIS_METHOD, fallback)


def performance_return_method(fallback=None):
    """User's headline return method ('TWR'|'MWR'). The engine always computes
    BOTH time-weighted and money-weighted/XIRR returns; this only selects which
    the summary flags as primary. Resolution + garbage-handling happen at the
    rendering boundary (the pure core never imports config)."""
    return get(PERFORMANCE_RETURN_METHOD, fallback)


def annualize_sub_year_returns(fallback=None):
    """Whether to annualise the time-weighted return for holding periods under
    one year. Default False (GIPS I.5.A.4). Consumed at the rendering boundary
    by the per-broker TWR computation."""
    return get(ANNUALIZE_SUB_YEAR_RETURNS, fallback)


def benchmark(fallback=None):
    """Benchmark ticker for the 'vs the market' comparison ('none' disables).
    Consumed at the rendering boundary; the pure performance core never
    fetches prices itself."""
    return get(BENCHMARK, fallback)
