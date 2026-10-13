#!/usr/bin/env python3
"""Offline tests for the progressive dependency-free static-quality policy."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "static_quality.py"
SPEC = importlib.util.spec_from_file_location("auto_g16_static_quality_test", MODULE_PATH)
assert SPEC and SPEC.loader
QUALITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALITY)


class StaticQualityTests(unittest.TestCase):
    def test_progressive_config_and_selected_sources_pass(self) -> None:
        config = QUALITY.load_config()
        self.assertEqual(config["schema"], QUALITY.SCHEMA)
        self.assertEqual(QUALITY.run(config), [])

    def test_rules_report_high_risk_python_constructs(self) -> None:
        source = """
from module import *
try:
    eval('1')
except:
    subprocess.run(['tool'], shell=True)
"""
        violations = QUALITY.inspect_source(source, "synthetic.py", QUALITY.SUPPORTED_RULES)
        combined = "\n".join(violations)
        for expected in ("star import", "builtin eval", "bare except", "shell=True"):
            self.assertIn(expected, combined)


if __name__ == "__main__":
    unittest.main()
