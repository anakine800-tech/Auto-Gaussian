#!/usr/bin/env python3
"""Offline checks for the imported Auto-G16 Gaussian learning library."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = ROOT / "skills" / "auto-g16-gaussian-learning-library"


class GaussianLearningLibraryTests(unittest.TestCase):
    def test_library_audit_passes(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SKILL / "scripts" / "audit_library.py"),
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["knowledge_card_count"], 72)
        self.assertEqual(report["reference_count"], 8)
        self.assertEqual(report["file_count"], 12)

    def test_search_finds_frequency_guidance(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SKILL / "scripts" / "search_knowledge.py"),
                "--query",
                "频率计算为什么要做",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        hits = json.loads(completed.stdout)
        self.assertTrue(hits)
        self.assertTrue(
            any(hit["path"].startswith("references/") for hit in hits)
        )


if __name__ == "__main__":
    unittest.main()
