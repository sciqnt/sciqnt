#!/usr/bin/env python3
"""Launcher for the interactive TUI — all logic lives in core/sq_platform."""
from pathlib import Path
from sq_platform import run_interactive

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    try:
        run_interactive(ROOT)
    except KeyboardInterrupt:
        print()
