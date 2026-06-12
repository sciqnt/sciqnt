#!/usr/bin/env python3
"""sq-config show — print current user config: location, and every setting with
its value, default, and what it's for. Materialises the file on first run so it
exists and is hand-editable."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))
import sq_config                                  # noqa: E402
from sq_tui import (BOLD, DIM, GREEN, RST,  # noqa: E402
                    format_table)


def main():
    data = sq_config.materialise()        # ensure the file exists + is complete
    p = sq_config.path()
    print(f"\n  {DIM}config file: {p}{RST}")

    schema = sq_config.schema()
    known = {s.key for s in schema}

    rows, styles = [], []
    for s in schema:
        value = data.get(s.key, s.default)
        is_default = value == s.default
        val_cell = str(value) if is_default else f"{GREEN}{value}{RST}"
        # mvp=False settings are declared but not yet honoured by any engine —
        # mark them so the user knows they're forward-looking, not live knobs.
        status = "" if s.mvp else "soon"
        rows.append([s.key, val_cell, str(s.default), status, s.help])
        styles.append(None if s.mvp else DIM)
    # Any ad-hoc keys not in the schema (forward-compatible / hand-added).
    for k in sorted(set(data) - known):
        rows.append([k, str(data[k]), "—", "", f"{DIM}(not in schema){RST}"])
        styles.append(DIM)

    print()
    print(format_table(
        ["setting", "value", "default", "", "purpose"],
        rows, align=["l", "l", "l", "l", "l"], title="user config",
        row_styles=styles,
    ))
    print(f"\n  {DIM}values changed from default in {RST}{GREEN}green{RST}"
          f"{DIM}; {RST}{DIM}'soon' = declared, not yet wired. "
          f"change one with `sciqnt config set`.{RST}\n")


if __name__ == "__main__":
    main()
