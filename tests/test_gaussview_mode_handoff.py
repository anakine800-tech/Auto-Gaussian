#!/usr/bin/env python3
"""Offline tests for GaussView structure-file handoff."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
MODULE = ROOT / "skills" / "gaussian-view-rt-win" / "scripts" / "windows_gaussview.py"
SPEC = importlib.util.spec_from_file_location("windows_gaussview", MODULE)
assert SPEC and SPEC.loader
GVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GVIEW)


class GaussViewModeHandoffTests(unittest.TestCase):
    def test_xyz_is_allowed_for_visual_mode_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode_plus.xyz"
            path.write_text("1\nmode\nH 0 0 0\n", encoding="utf-8")
            self.assertEqual(GVIEW.validate_open_source(path), path.resolve())

    def test_log_is_not_an_open_structure_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "job.log"
            path.write_text("Normal termination", encoding="utf-8")
            with self.assertRaises(ValueError):
                GVIEW.validate_open_source(path)


if __name__ == "__main__":
    unittest.main()
