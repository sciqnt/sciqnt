"""sq_agents — detect installed coding agents and launch the user's preferred
one with context. The INWARD half of sciqnt's bidirectional LLM-native design:
a component hands the agent a prompt + the on-screen data and hands off the
terminal ("use agent to X"); on exit, control returns to the TUI.

Design + provenance: research/llm-native-integration.md. Detection is
`shutil.which` (stdlib); launch is `subprocess` with a list-of-args (no shell,
no injection). A "preferred agent" is resolved like a default browser:
explicit arg → `sq_config.preferred_agent` → first detected (priority order).

Per-agent invocation: claude / codex / aider headless forms are doc-verified;
gemini / openclaw are best-effort and flagged (probe at runtime). Because the
interactive seed differs per agent, we ALSO write the full instruction +
context to a task file in the working dir and reference it — so even an agent
we can't seed on the command line just needs to read one file.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Ordered by preference for "auto". Each adapter:
#   bin     — the executable to look for on PATH
#   label   — human name
#   seed    — given (bin, prompt) → argv to start the agent INTERACTIVELY seeded
#             with prompt, or None to launch bare (the task file carries the prompt)
#   install — one-line install hint when nothing is detected
_AGENTS = [
    {"name": "claude", "bin": "claude", "label": "Claude Code",
     "seed": lambda b, p: [b, p],
     "install": "npm install -g @anthropic-ai/claude-code"},
    {"name": "codex", "bin": "codex", "label": "Codex CLI",
     "seed": lambda b, p: [b, p],
     "install": "npm install -g @openai/codex"},
    {"name": "openclaw", "bin": "openclaw", "label": "OpenClaw",
     "seed": lambda b, p: [b, p],                 # best-effort — verify at runtime
     "install": "see the OpenClaw docs"},
    {"name": "gemini", "bin": "gemini", "label": "Gemini CLI",
     "seed": lambda b, p: [b],                    # launch bare; task file carries prompt
     "install": "npm install -g @google/gemini-cli"},
    {"name": "aider", "bin": "aider", "label": "Aider",
     "seed": lambda b, p: [b],                    # no clean interactive seed; task file
     "install": "python -m pip install aider-install && aider-install"},
]
_BY_NAME = {a["name"]: a for a in _AGENTS}

NAMES = [a["name"] for a in _AGENTS]              # for the config enum / picker
TASK_FILE = ".sciqnt-agent-task.md"               # written into the launch cwd
LAUNCH_SCRIPT = ".sciqnt-agent-launch.command"    # new-window launcher (macOS)


def detect() -> list[str]:
    """Names of the known agent CLIs found on PATH, in preference order."""
    return [a["name"] for a in _AGENTS if shutil.which(a["bin"])]


def label(name: str) -> str:
    a = _BY_NAME.get(name)
    return a["label"] if a else name


def status() -> list[dict]:
    """Every known agent with live install state — detection is on-demand
    (`shutil.which` each call), so installing/uninstalling an agent after sciqnt
    is reflected immediately. [{name,label,installed,install}], preference order."""
    present = set(detect())
    return [{"name": a["name"], "label": a["label"],
             "installed": a["name"] in present, "install": a["install"]}
            for a in _AGENTS]


def install_hints() -> list[tuple[str, str]]:
    """[(label, install-command)] for every known agent — shown when none are
    installed so the user knows how to get one."""
    return [(a["label"], a["install"]) for a in _AGENTS]


def resolve(preferred: Optional[str] = None) -> Optional[str]:
    """The agent to use: explicit `preferred` (if installed) → the configured
    `preferred_agent` (if a real installed name) → the first detected. None when
    nothing is installed. 'auto'/None/unknown fall through to first-detected."""
    installed = detect()
    if not installed:
        return None
    if preferred and preferred in installed:
        return preferred
    try:
        import sq_config
        cfg = sq_config.preferred_agent(fallback="auto")
    except Exception:                                          # noqa: BLE001
        cfg = "auto"
    if cfg and cfg != "auto" and cfg in installed:
        return cfg
    return installed[0]


RECENCY_FILE = "agent_recency.json"               # MRU list, next to config.json


def _recency_path() -> Path:
    import sq_config
    return sq_config.path().parent / RECENCY_FILE


def recent_installed() -> list[str]:
    """Installed agents in most-recently-USED order (front = last launched);
    installed-but-never-used ones follow in detection-preference order. The TUI
    renders the framework toggle in this order, so the last-used one sits first
    (in the 'SciQnt Agent + …' slot). Falls back to the configured/preferred
    agent leading when no recency is recorded yet."""
    installed = detect()
    try:
        raw = json.loads(_recency_path().read_text())
        mru = [n for n in raw if isinstance(n, str) and n in installed]
    except Exception:                                       # noqa: BLE001
        mru = []
    if not mru and installed:
        pref = resolve()
        if pref in installed:
            mru = [pref]
    return mru + [n for n in installed if n not in mru]


def mark_used(name: str) -> None:
    """Record `name` as the most recently used agent (front of the MRU list).
    Best-effort persistence — a failed write never breaks a launch."""
    try:
        cur = json.loads(_recency_path().read_text())
        if not isinstance(cur, list):
            cur = []
    except Exception:                                       # noqa: BLE001
        cur = []
    cur = [name] + [n for n in cur if n != name]
    try:
        p = _recency_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cur[:10]))
    except Exception:                                       # noqa: BLE001
        pass


def _argv(spec: dict, prompt: str) -> list[str]:
    return spec["seed"](spec["bin"], prompt)


def _pointer_prompt() -> str:
    """The short seed used when launching in a NEW window: the full instruction
    + context list live in the task file, so the CLI/AppleScript quoting stays
    trivial — we just point the agent at the file."""
    return f"Read {TASK_FILE} in this directory and follow its instructions."


def can_new_window() -> bool:
    """True if we can open the agent in a SEPARATE terminal window (macOS, via
    LaunchServices `open`). Lets callers phrase the UI honestly. We deliberately
    do NOT script Terminal over AppleEvents (`osascript do script`) — that wedges
    with -1712 timeouts on this host; `open`-ing a launch script is robust."""
    return sys.platform == "darwin" and shutil.which("open") is not None


def _open_in_new_window(work: Path, argv: list[str]) -> bool:
    """Open `argv` in a fresh terminal window (cwd=`work`) so the launching TUI
    keeps its screen. macOS only. Writes an executable `.command` launch script
    and hands it to `open -a <terminal>` (LaunchServices — no AppleEvents, so no
    -1712 wedge). Targets the host terminal (iTerm if that's TERM_PROGRAM, else
    Terminal.app). Returns True on success, False to let `launch` fall back to
    in-place. The window leaves a live shell after the agent exits (the script
    just `cd`s + runs), so the user lands in the working dir."""
    if not can_new_window():
        return False
    cmd = ("#!/bin/bash\n"
           "cd " + shlex.quote(str(work)) + "\n"
           + " ".join(shlex.quote(a) for a in argv) + "\n")
    script = work / LAUNCH_SCRIPT
    try:
        script.write_text(cmd)
        script.chmod(0o755)
        app = "iTerm" if os.environ.get("TERM_PROGRAM") == "iTerm.app" else "Terminal"
        subprocess.run(["open", "-a", app, str(script)], check=True,
                       capture_output=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def launch(prompt: str, *, seed: Optional[str] = None, cwd=None,
           context: Optional[dict] = None, agent: Optional[str] = None,
           task_intro: str = "", new_window: bool = False) -> Optional[int]:
    """Launch the preferred agent in `cwd` (default: a temp dir), handing it
    `prompt` + any `context` files. Returns the process exit code (0 for a
    detached new-window launch), or None if no agent is installed (caller should
    show `install_hints()`).

    `context`: {filename: text} written into `cwd` before launch (e.g. the
    on-screen portfolio dump). The full instruction + a list of the context
    files is ALSO written to `<cwd>/.sciqnt-agent-task.md` and the agent is told
    to read it — so any agent works even if we can't seed it on the CLI.

    `seed`: the SHORT line typed into the agent's visible input instead of
    the full prompt — one clean pointer, not a lecture (the full prompt
    always lands in the task file). Omitted → the prompt itself seeds.

    `new_window=True`: open the agent in a SEPARATE terminal window (macOS) so
    the launching TUI keeps its screen — control returns immediately and the
    agent runs alongside. Falls back to running in-place where that's not
    possible (`can_new_window()` is False). In-place runs inherit the terminal;
    the caller must have left any full-screen TUI first (returns on exit).

    Security: only pass non-secret context (portfolio figures, code) — NEVER
    credentials. See research/llm-native-integration.md §5."""
    name = resolve(agent)
    if name is None:
        return None
    spec = _BY_NAME[name]

    work = Path(cwd) if cwd is not None else Path(tempfile_mkdtemp())
    work.mkdir(parents=True, exist_ok=True)
    written = []
    for fname, text in (context or {}).items():
        (work / fname).write_text(text)
        written.append(fname)

    files_line = (f"\nContext files in this directory: {', '.join(written)}\n"
                  if written else "")
    (work / TASK_FILE).write_text(
        f"{task_intro}\n\n{prompt}\n{files_line}".strip() + "\n")

    if new_window:
        # Seed a short pointer prompt — the full instruction is in the task
        # file, so the shell/AppleScript quoting stays trivial.
        if _open_in_new_window(work, _argv(spec, _pointer_prompt())):
            return 0
        # couldn't open a window → run in-place below

    argv = _argv(spec, seed if seed is not None else prompt)
    try:
        return subprocess.run(argv, cwd=str(work)).returncode
    except KeyboardInterrupt:
        return 130
    except FileNotFoundError:
        return None


def tempfile_mkdtemp() -> str:
    # Wrapped so tests can monkeypatch without importing tempfile at call sites.
    import tempfile
    return tempfile.mkdtemp(prefix="sciqnt-agent-")
