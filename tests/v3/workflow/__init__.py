"""Fail-closed discovery for the frozen V30-4 Workflow evidence package."""

from __future__ import annotations

from pathlib import Path
import unittest


_DISCOVERY_PATTERN = "test*.py"
_WORKFLOW_EVIDENCE_FILES = frozenset(
    {
        "test_acceptance_inventory.py",
        "test_contract.py",
        "test_store_replay.py",
        "test_validation.py",
    }
)


def _owned_test_files() -> tuple[str, ...]:
    package_directory = Path(__file__).resolve().parent
    observed: set[str] = set()
    for entry in package_directory.iterdir():
        if not entry.name.startswith("test") or entry.suffix != ".py":
            continue
        if entry.is_symlink():
            raise RuntimeError(
                f"Workflow evidence file must not be a symlink: {entry.name}"
            )
        if not entry.is_file():
            raise RuntimeError(
                f"Workflow evidence entry must be a regular file: {entry.name}"
            )
        observed.add(entry.name)

    if observed != _WORKFLOW_EVIDENCE_FILES:
        missing = tuple(sorted(_WORKFLOW_EVIDENCE_FILES - observed))
        unexpected = tuple(sorted(observed - _WORKFLOW_EVIDENCE_FILES))
        raise RuntimeError(
            "Workflow test ownership does not match the frozen evidence set: "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )
    return tuple(sorted(observed))


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, _DISCOVERY_PATTERN}:
        return standard_tests

    suite = unittest.TestSuite()
    for filename in _owned_test_files():
        module_name = Path(filename).stem
        suite.addTests(loader.loadTestsFromName(f"{__name__}.{module_name}"))
    if suite.countTestCases() == 0:
        raise RuntimeError("Workflow ownership discovered zero validation evidence")
    return suite
