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

        metal_evidence = (
            SKILL / "references" / "transition-metal-computational-strategy-evidence.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(metal_evidence.startswith("# Auto-G16"))
        for doi in (
            "10.1021/acs.jctc.8b00578",
            "10.1039/D2SC01714H",
            "10.1021/jacs.7b05917",
            "10.1063/1.2007708",
            "10.1021/ct2006852",
            "10.1021/acs.jpclett.4c01657",
        ):
            self.assertIn(doi, metal_evidence)
        self.assertIn("not a protocol menu", metal_evidence)
        self.assertIn("does not support selecting one automatically", metal_evidence)

        ni_gap = (
            SKILL / "references" / "wang-2025-borane-nickel-m1-gap-audit.md"
        ).read_text(encoding="utf-8")
        self.assertTrue(ni_gap.startswith("# Auto-G16"))
        self.assertIn("10.1021/jacs.5c13835", ni_gap)
        self.assertIn("metal_m1_scientific_review: pending_scientific_review", ni_gap)
        self.assertIn("not a default", ni_gap)

    def test_m1_sidecar_never_grants_scientific_or_live_authority(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        design = (
            SKILL / "references" / "transition-metal-support-design.md"
        ).read_text(encoding="utf-8")
        for text in (skill_text, design):
            self.assertIn("build-metal-scientific-review", text)
            self.assertIn("scientific_acceptance_decision: not_granted_by_artifact", text)
            self.assertIn("metal_m1_scientific_review", text)
        self.assertIn("not_satisfied_synthetic_fixture", skill_text)
        self.assertIn("execution_selection_status", design)

    def test_m2c_existing_input_observer_never_accepts_or_renders(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        design = (
            SKILL / "references" / "transition-metal-support-design.md"
        ).read_text(encoding="utf-8")
        for text in (skill_text, design):
            self.assertIn("audit-metal-input", text)
            self.assertIn("input_acceptance_decision: not_granted_by_artifact", text)
            self.assertIn("metal_m2c_input_observation", text)
        self.assertIn("never renders or modifies the input", skill_text)
        self.assertIn("protocol_selection_decision: absent_not_authorized", design)

    def test_m2d_manual_decisions_never_grant_top_level_authority(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        design = (
            SKILL / "references" / "transition-metal-support-design.md"
        ).read_text(encoding="utf-8")
        for text in (skill_text, design):
            self.assertIn("build-metal-acceptance-review", text)
            self.assertIn("accepted_for_bounded_offline_review", text)
            self.assertIn("mode_acceptance_decision", text)
            self.assertIn("metal_m2d_acceptance_review_contract", text)
        self.assertIn("not_satisfied_synthetic_fixture", skill_text)
        self.assertIn("promotion_decision: refused", design)


if __name__ == "__main__":
    unittest.main()
