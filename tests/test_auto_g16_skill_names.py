#!/usr/bin/env python3
"""Repository-wide naming checks for project-owned Auto-G16 Skills."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILLS = ROOT / "skills"
EXPECTED = {
    "auto-g16-asymmetric-catalysis",
    "auto-g16-chemdraw-pipeline",
    "auto-g16-chemdraw-structures",
    "auto-g16-reaction-workflow",
    "auto-g16-rtwin-pbs",
    "auto-g16-ts-irc",
    "auto-g16-view-rt-win",
}


class AutoG16SkillNameTests(unittest.TestCase):
    def test_all_project_skills_use_the_auto_g16_namespace(self) -> None:
        skill_dirs = {
            path.name
            for path in SKILLS.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        self.assertEqual(skill_dirs, EXPECTED)

        for name in sorted(skill_dirs):
            with self.subTest(skill=name):
                skill_text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                metadata = (SKILLS / name / "agents" / "openai.yaml").read_text(
                    encoding="utf-8"
                )
                frontmatter_name = re.search(r"(?m)^name: ([a-z0-9-]+)$", skill_text)
                self.assertIsNotNone(frontmatter_name)
                self.assertEqual(frontmatter_name.group(1), name)
                self.assertIn('display_name: "Auto-G16', metadata)
                self.assertIn(f"Use ${name}", metadata)

        policy = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("Name every repository-owned Skill", policy)
        self.assertIn("machine prefix `auto-g16-`", policy)
        self.assertIn("Use `Auto-G16`", policy)


if __name__ == "__main__":
    unittest.main()
