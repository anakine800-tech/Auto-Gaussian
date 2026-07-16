#!/usr/bin/env python3
"""Offline checks for public Auto-G16 release hygiene."""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
THIS_FILE = Path(__file__).resolve()
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        candidates = [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]
    else:
        # GitHub source archives intentionally contain no .git directory. In
        # that environment every regular archive file is release material.
        candidates = [
            path
            for path in ROOT.rglob("*")
            if path.is_file() and not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
        ]
    return [path for path in candidates if path.resolve() != THIS_FILE]


class ReleaseHygieneTests(unittest.TestCase):
    def test_release_metadata_is_present(self) -> None:
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())
        changelog = (ROOT / "CHANGELOG.md").read_text()
        pyproject = (ROOT / "pyproject.toml").read_text()
        self.assertRegex(pyproject, r'(?m)^version = "2\.3\.0"$')
        self.assertIn("## [Unreleased]\n\n## [2.3.0] - 2026-07-16", changelog)
        self.assertIn(
            "[Unreleased]: https://github.com/anakine800-tech/"
            "Auto-Gaussian/compare/v2.3.0...HEAD",
            changelog,
        )
        self.assertIn(
            "[2.3.0]: https://github.com/anakine800-tech/"
            "Auto-Gaussian/compare/v2.2.0...v2.3.0",
            changelog,
        )
        self.assertIn("Auto-Gaussian 2.3.0", (ROOT / "README.md").read_text())
        self.assertTrue((ROOT / "docs" / "release-2.3.0-checklist.md").is_file())

        # Preserve the prior release entry, compare link, and checklist as
        # immutable public history rather than rewriting them for 2.3.0.
        self.assertIn("## [2.2.0]", changelog)
        self.assertIn("[2.2.0]:", changelog)
        self.assertTrue((ROOT / "docs" / "release-2.2.0-checklist.md").is_file())
        workflow = ROOT / ".github" / "workflows" / "offline-tests.yml"
        self.assertTrue(workflow.is_file())
        self.assertIn("unittest discover", workflow.read_text())

    def test_optional_chemistry_dependencies_are_declared(self) -> None:
        requirements = ROOT / "requirements" / "chemistry.txt"
        lock = ROOT / "requirements" / "chemistry.lock.txt"
        self.assertTrue(requirements.is_file())
        self.assertTrue(lock.is_file())
        self.assertIn("-r chemistry.lock.txt", requirements.read_text(encoding="utf-8"))
        declared = lock.read_text(encoding="utf-8").lower()
        for dependency in ("numpy", "pillow", "rdkit"):
            self.assertRegex(declared, rf"(?m)^{dependency}==[^\s]+$")

    def test_offline_ci_uses_audited_actions_and_supported_python_matrix(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "offline-tests.yml"
        ).read_text(encoding="utf-8")
        action_uses = re.findall(
            r"(?m)^\s*- uses: (actions/(?:checkout|setup-python))@([^\s]+)$",
            workflow,
        )
        self.assertEqual(len(action_uses), 4)
        for action, revision in action_uses:
            self.assertRegex(revision, r"^[0-9a-f]{40}$", action)
        versions = set(re.findall(r'"(3\.1[123])"', workflow))
        self.assertEqual(versions, {"3.11", "3.12", "3.13"})

    def test_chemistry_ci_resolution_is_constrained(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "offline-tests.yml"
        ).read_text(encoding="utf-8")
        lock_path = "requirements/chemistry.lock.txt"
        self.assertIn("--requirement requirements/chemistry.txt", workflow)
        self.assertIn(lock_path, workflow)
        constraints = (ROOT / lock_path).read_text(encoding="utf-8").lower()
        for dependency in ("numpy", "pillow", "rdkit"):
            self.assertRegex(constraints, rf"(?m)^{dependency}==[^\s]+$")

    def test_repository_status_separates_current_and_historical_evidence(self) -> None:
        status = (ROOT / "docs" / "repository-status.md").read_text(encoding="utf-8")
        self.assertIn("## Current mainline state", status)
        self.assertIn("external fact outside this checkout", status)
        for evidence_type in ("Feature", "Deployment", "Test"):
            self.assertRegex(
                status,
                rf"(?m)^### {evidence_type} evidence — \d{{4}}-\d{{2}}-\d{{2}} — commit [0-9a-f]{{40}}$",
            )
        for stale in (
            "current Unreleased feature branch",
            "current feature branch adds",
            "remains undeployed",
            "## Working-tree note",
        ):
            self.assertNotIn(stale, status)

    def test_no_machine_specific_identity_or_address_is_tracked(self) -> None:
        retired_machine_values = [
            "".join(("sun", "deli")),
            "".join(("102", "61")),
            ".".join(("100", "76", "152", "81")),
            ".".join(("10", "40", "11", "7")),
        ]
        forbidden = re.compile(
            "|".join(map(re.escape, retired_machine_values))
            + r"|/Users/[^/< ]+|C:\\Users\\(?!<WINDOWS_USER>)",
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

    def test_studies_are_publication_backed_and_not_marked_confidential(self) -> None:
        studies = ROOT / "studies"
        doi = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
        confidential = re.compile(
            r"\bunpublished\b|\bconfidential\b|\bproprietary\b|"
            r"\bembargo(?:ed)?\b|\binternal[-_ ]only\b",
            re.IGNORECASE,
        )
        offenders: list[str] = []
        release_files = tracked_files()
        for directory in sorted(path for path in studies.iterdir() if path.is_dir()):
            readme = directory / "README.md"
            if not readme.is_file():
                offenders.append(f"{directory.name}: missing README.md")
                continue
            text = readme.read_text(encoding="utf-8")
            if not doi.search(text):
                offenders.append(f"{directory.name}: missing publication DOI")
            for path in release_files:
                if directory not in path.parents:
                    continue
                try:
                    candidate = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if confidential.search(candidate):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_private_study_directory_names_are_never_tracked(self) -> None:
        forbidden_parts = {"private-studies", "unpublished", "confidential", "studies-private"}
        offenders = [
            str(path.relative_to(ROOT))
            for path in tracked_files()
            if forbidden_parts.intersection(path.relative_to(ROOT).parts)
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
