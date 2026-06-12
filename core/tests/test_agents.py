"""sq_agents — detect installed coding agents + launch the preferred one.

Mocks shutil.which (detection) and subprocess.run (launch) so nothing real is
invoked. SQ_CONFIG_PATH isolates the preferred-agent config.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_agents                                          # noqa: E402
import sq_config                                          # noqa: E402


class TestDetectResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pz-agents-test-")
        self._prev = os.environ.get("SQ_CONFIG_PATH")
        os.environ["SQ_CONFIG_PATH"] = str(Path(self.tmp) / "config.json")

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("SQ_CONFIG_PATH", None)
        else:
            os.environ["SQ_CONFIG_PATH"] = self._prev

    def _which(self, *present):
        present = set(present)
        return mock.patch.object(sq_agents.shutil, "which",
                                 side_effect=lambda b: f"/usr/bin/{b}" if b in present else None)

    def test_detect_returns_installed_in_preference_order(self):
        with self._which("aider", "claude"):            # given out of order
            self.assertEqual(sq_agents.detect(), ["claude", "aider"])  # preference order

    def test_resolve_none_when_nothing_installed(self):
        with self._which():
            self.assertIsNone(sq_agents.resolve())

    def test_resolve_explicit_preferred_wins_if_installed(self):
        with self._which("claude", "codex"):
            self.assertEqual(sq_agents.resolve("codex"), "codex")

    def test_resolve_falls_back_to_first_detected(self):
        with self._which("codex", "aider"):
            self.assertEqual(sq_agents.resolve("notinstalled"), "codex")  # explicit missing
            self.assertEqual(sq_agents.resolve(), "codex")                # auto

    def test_resolve_reads_config_preferred(self):
        sq_config.set("preferred_agent", "aider")
        with self._which("claude", "aider"):
            self.assertEqual(sq_agents.resolve(), "aider")               # config beats first-detected
        with self._which("claude"):                                      # configured not installed
            self.assertEqual(sq_agents.resolve(), "claude")              # → first detected

    def test_install_hints_nonempty(self):
        hints = sq_agents.install_hints()
        self.assertTrue(hints and all(len(h) == 2 for h in hints))

    def test_recent_installed_orders_by_use(self):
        with self._which("claude", "codex", "aider"):
            self.assertEqual(sq_agents.recent_installed(),
                             ["claude", "codex", "aider"])  # no history → preference
            sq_agents.mark_used("codex")
            self.assertEqual(sq_agents.recent_installed(),
                             ["codex", "claude", "aider"])  # last used leads
            sq_agents.mark_used("aider")
            self.assertEqual(sq_agents.recent_installed(),
                             ["aider", "codex", "claude"])
            sq_agents.mark_used("codex")                    # re-use bumps to front
            self.assertEqual(sq_agents.recent_installed(),
                             ["codex", "aider", "claude"])

    def test_recent_installed_drops_uninstalled(self):
        with self._which("claude", "codex"):
            sq_agents.mark_used("codex")
            sq_agents.mark_used("gemini")                   # later uninstalled
        with self._which("claude", "codex"):                # gemini not on PATH
            self.assertEqual(sq_agents.recent_installed(), ["codex", "claude"])


class TestLaunch(unittest.TestCase):
    def test_launch_writes_context_and_task_then_runs(self):
        work = tempfile.mkdtemp(prefix="pz-agents-launch-")
        ran = {}

        class _CP:
            returncode = 0

        def fake_run(argv, cwd=None):
            ran["argv"] = argv
            ran["cwd"] = cwd
            return _CP()

        with mock.patch.object(sq_agents, "resolve", return_value="claude"), \
             mock.patch.object(sq_agents.subprocess, "run", side_effect=fake_run):
            rc = sq_agents.launch("Explain portfolio.txt",
                                  cwd=work, context={"portfolio.txt": "NW 100"})
        self.assertEqual(rc, 0)
        self.assertEqual(ran["argv"], ["claude", "Explain portfolio.txt"])  # seeded
        self.assertEqual(ran["cwd"], work)
        self.assertEqual((Path(work) / "portfolio.txt").read_text(), "NW 100")
        task = (Path(work) / sq_agents.TASK_FILE).read_text()
        self.assertIn("Explain portfolio.txt", task)
        self.assertIn("portfolio.txt", task)                 # context file referenced

    def test_launch_returns_none_when_no_agent(self):
        with mock.patch.object(sq_agents, "resolve", return_value=None):
            self.assertIsNone(sq_agents.launch("anything"))

    def test_new_window_opens_window_and_skips_inplace(self):
        work = tempfile.mkdtemp(prefix="pz-agents-win-")
        with mock.patch.object(sq_agents, "resolve", return_value="claude"), \
             mock.patch.object(sq_agents, "_open_in_new_window",
                               return_value=True) as win, \
             mock.patch.object(sq_agents.subprocess, "run") as run:
            rc = sq_agents.launch("explain", cwd=work, new_window=True)
        self.assertEqual(rc, 0)
        win.assert_called_once()                      # opened a window
        run.assert_not_called()                       # did NOT run in-place
        # the full instruction still lands in the task file...
        self.assertIn("explain", (Path(work) / sq_agents.TASK_FILE).read_text())
        # ...while the window is seeded with the short pointer prompt
        seeded_argv = win.call_args.args[1]
        self.assertIn(sq_agents.TASK_FILE, " ".join(seeded_argv))

    def test_new_window_falls_back_to_inplace(self):
        work = tempfile.mkdtemp(prefix="pz-agents-win-")
        ran = {}

        def fake_run(argv, cwd=None):
            ran["argv"] = argv
            return type("CP", (), {"returncode": 0})()

        with mock.patch.object(sq_agents, "resolve", return_value="claude"), \
             mock.patch.object(sq_agents, "_open_in_new_window",
                               return_value=False), \
             mock.patch.object(sq_agents.subprocess, "run", side_effect=fake_run):
            rc = sq_agents.launch("explain", cwd=work, new_window=True)
        self.assertEqual(rc, 0)
        self.assertEqual(ran["argv"], ["claude", "explain"])   # full prompt in-place


if __name__ == "__main__":
    unittest.main()
