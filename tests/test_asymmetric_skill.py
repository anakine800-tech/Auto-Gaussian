#!/usr/bin/env python3
"""Offline checks for the asymmetric-catalysis planning Skill."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-asymmetric-catalysis"


class AsymmetricCatalysisSkillTests(unittest.TestCase):
    def test_skill_has_no_scaffold_placeholders(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("TODO", skill_text)
        self.assertIn("name: auto-g16-asymmetric-catalysis", skill_text)
        self.assertIn("offline scientific-orchestration Skill", skill_text)

    def test_transition_metal_boundary_is_preserved(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        protocol_text = (
            SKILL / "references" / "candidate-and-selectivity-protocol.md"
        ).read_text(encoding="utf-8")
        for text in (skill_text, protocol_text):
            self.assertIn("unsupported_requires_extension", text)
        self.assertIn("calculation_ready: false", skill_text)
        self.assertIn("does not support transition-metal cases", protocol_text)

    def test_literature_methods_are_not_defaults(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        precedents = (
            SKILL / "references" / "wang-group-computational-precedents.md"
        ).read_text(encoding="utf-8")
        self.assertIn("never\nbecome defaults", skill_text)
        self.assertIn("No one stack is a Wang-\n   group default", precedents)
        self.assertIn("10.1021/jacs.5c13835", precedents)
        self.assertIn("SI checked - no DFT section", precedents)


if __name__ == "__main__":
    unittest.main()
