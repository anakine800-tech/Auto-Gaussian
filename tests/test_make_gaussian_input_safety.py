#!/usr/bin/env python3
"""Pure offline safety tests for ChemDraw-to-Gaussian draft defaults."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "skills" / "auto-g16-chemdraw-pipeline" / "scripts"
MODULE = SCRIPTS / "make_gaussian_input.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("make_gaussian_input", MODULE)
assert SPEC and SPEC.loader
MAKE_INPUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MAKE_INPUT)


class MakeGaussianInputSafetyTests(unittest.TestCase):
    def test_nonradical_keeps_existing_default_route_and_singlet(self) -> None:
        route, multiplicity, warnings = MAKE_INPUT.resolve_draft_protocol(0, None, None)
        self.assertEqual(route, "#p b3lyp/6-31g(d) opt")
        self.assertEqual(multiplicity, 1)
        self.assertEqual(warnings, [])

    def test_radical_requires_explicit_multiplicity_and_route(self) -> None:
        with self.assertRaisesRegex(SystemExit, "--multiplicity explicitly"):
            MAKE_INPUT.resolve_draft_protocol(1, "#p ub3lyp/6-31g(d) opt", None)
        with self.assertRaisesRegex(SystemExit, "--route explicitly"):
            MAKE_INPUT.resolve_draft_protocol(1, None, 2)

    def test_explicit_radical_draft_warns_and_never_claims_acceptance(self) -> None:
        route, multiplicity, warnings = MAKE_INPUT.resolve_draft_protocol(
            1, "#p ub3lyp/6-31g(d) opt stable=opt", 2
        )
        self.assertEqual(route, "#p ub3lyp/6-31g(d) opt stable=opt")
        self.assertEqual(multiplicity, 2)
        self.assertEqual(warnings, [MAKE_INPUT.OPEN_SHELL_DRAFT_WARNING])
        self.assertIn("do not confer", warnings[0])
        source = MODULE.read_text(encoding="utf-8")
        self.assertIn('"scientific_acceptance": False', source)
        self.assertIn('"no_submission_authorization": True', source)


if __name__ == "__main__":
    unittest.main()
