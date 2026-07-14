#!/usr/bin/env python3
"""Offline checks for public Auto-G16 release hygiene."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
THIS_FILE = Path(__file__).resolve()


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [
        path
        for item in result.stdout.split(b"\0")
        if item and (path := ROOT / item.decode()).resolve() != THIS_FILE
    ]


class ReleaseHygieneTests(unittest.TestCase):
    def test_release_metadata_is_present(self) -> None:
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())
        self.assertIn("## [2.1.0]", (ROOT / "CHANGELOG.md").read_text())
        workflow = ROOT / ".github" / "workflows" / "offline-tests.yml"
        self.assertTrue(workflow.is_file())
        self.assertIn("unittest discover", workflow.read_text())

    def test_no_machine_specific_identity_or_address_is_tracked(self) -> None:
        forbidden = re.compile(
            r"sundeli|10261|100\.76\.152\.81|10\.40\.11\.7|"
            r"/Users/[^/< ]+|C:\\Users\\(?!<WINDOWS_USER>)",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        for path in tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if forbidden.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_no_high_confidence_secret_pattern_is_tracked(self) -> None:
        secret = re.compile(
            r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----|"
            r"AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
            r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-|sk-[A-Za-z0-9]{20,}"
        )
        offenders: list[str] = []
        for path in tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if secret.search(text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
