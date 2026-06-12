"""sq_skills — installing reusable Agent Skills into a coding agent.

Uses a temp HOME so the real ~/.claude / ~/.codex are never touched. Verifies
per-agent on-disk shape (folder SKILL.md vs slash-prompt), frontmatter, idempotent
overwrite, unsupported-agent → None, and the invocation hint.
"""
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))                    # core/

import sq_skills                                          # noqa: E402


class TestCatalog(unittest.TestCase):
    def test_skills_present(self):
        self.assertIn("sq-portfolio", sq_skills.names())
        self.assertIn("sq-connectors", sq_skills.names())

    def test_skill_md_has_frontmatter(self):
        md = sq_skills.skill_md("sq-portfolio")
        self.assertTrue(md.startswith("---\nname: sq-portfolio\n"))
        self.assertIn("description:", md)
        self.assertIn("sciqnt --help", md)               # body teaches discovery

    def test_connectors_body_points_at_contract(self):
        md = sq_skills.skill_md("sq-connectors")
        self.assertIn("conformance", md)
        self.assertIn("run_tests.sh", md)
        self.assertIn("sciqnt --list", md)

    def test_for_group(self):
        self.assertEqual(sq_skills.for_group("portfolio"), "sq-portfolio")
        self.assertEqual(sq_skills.for_group("connectors"), "sq-connectors")
        self.assertIsNone(sq_skills.for_group("nope"))

    def test_unsupported_agent(self):
        self.assertFalse(sq_skills.supported("aider"))
        self.assertIsNone(sq_skills.installed_path("aider", "sq-portfolio"))


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="sq-skills-test-"))

    def test_claude_folder_skill(self):
        p = sq_skills.install("claude", "sq-portfolio", home=self.home)
        self.assertEqual(p, self.home / ".claude" / "skills" / "sq-portfolio" / "SKILL.md")
        self.assertTrue(p.is_file())
        self.assertIn("name: sq-portfolio", p.read_text())     # full frontmatter

    def test_codex_prompt_file(self):
        p = sq_skills.install("codex", "sq-portfolio", home=self.home)
        self.assertEqual(p, self.home / ".codex" / "prompts" / "sq-portfolio.md")
        self.assertTrue(p.is_file())
        self.assertNotIn("---\nname:", p.read_text())          # body only, no frontmatter
        self.assertIn("sciqnt --help", p.read_text())

    def test_unsupported_returns_none_and_writes_nothing(self):
        self.assertIsNone(sq_skills.install("aider", "sq-portfolio", home=self.home))
        self.assertFalse((self.home / ".claude").exists())

    def test_unknown_skill_returns_none(self):
        self.assertIsNone(sq_skills.install("claude", "nope", home=self.home))

    def test_idempotent_overwrite(self):
        p1 = sq_skills.install("claude", "sq-portfolio", home=self.home)
        p2 = sq_skills.install("claude", "sq-portfolio", home=self.home)
        self.assertEqual(p1, p2)
        self.assertIn("name: sq-portfolio", p2.read_text())

    def test_connectors_installs_subskill_file(self):
        p = sq_skills.install("claude", "sq-connectors", home=self.home)
        sub = p.parent / "building-a-connector.md"
        self.assertTrue(sub.is_file())                         # supporting file as sibling
        self.assertIn("discovery contract", sub.read_text().lower())

    def test_codex_prompt_appends_subskill(self):
        p = sq_skills.install("codex", "sq-connectors", home=self.home)
        text = p.read_text()                                   # single file
        self.assertIn("building-a-connector.md", text)         # appended, not a sibling
        self.assertIn("snapshot()", text)

    def test_invocation_hint(self):
        self.assertEqual(sq_skills.invocation_hint("claude", "sq-portfolio"),
                         "the sq-portfolio skill")
        self.assertEqual(sq_skills.invocation_hint("codex", "sq-portfolio"),
                         "/sq-portfolio")


if __name__ == "__main__":
    unittest.main()
