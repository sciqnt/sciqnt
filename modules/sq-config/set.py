#!/usr/bin/env python3
"""sq-config set — change user settings. Two surfaces, one writer:

  set KEY VALUE   non-interactive (scripts / agents): validated via
                  `sq_config.set()`, prints the saved value, exits non-zero
                  on an invalid value.
  set  (bare)     the full-screen interactive settings screen
                  (sq_config_ui.run_settings — sq_tui, NOT questionary).
                  When the streams aren't interactive (piped / non-TTY) it
                  prints the plain dump (show.py) instead of entering a
                  menu loop.

`sciqnt config` (bare) routes here too, so bare config == the settings screen.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent          # modules/sq-config
ROOT = HERE.parents[1]                                  # repo root
sys.path.insert(0, str(ROOT / "core"))
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE))                           # for `import show`
import sq_config                                  # noqa: E402
import sq_tui                                     # noqa: E402


def main(argv):
    if len(argv) == 2:                  # script surface: set KEY VALUE
        key, value = argv
        try:
            sq_config.set(key, value)
        except ValueError as e:
            sys.exit(f"invalid value: {e}")
        print(f"{key} -> {sq_config.get(key)}  (saved to {sq_config.path()})")
        return 0
    if argv:
        sys.exit("usage: sq-config set [KEY VALUE]   "
                 "(no args opens the interactive settings screen)")
    if not sq_tui._streams_interactive():
        # Piped / non-TTY: never a menu loop into a pipe — the plain dump is
        # the script/agent-facing surface (same numbers, no interaction).
        import show
        show.main()
        return 0
    from sq_config_ui import run_settings          # noqa: E402
    run_settings()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print()
