"""Fail-closed package discovery for ScientificValidation evidence."""

from __future__ import annotations

from pathlib import Path
import unittest


_PATTERN = "test*.py"


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, _PATTERN}:
        return standard_tests
    directory = Path(__file__).resolve().parent
    candidates = sorted(directory.glob(_PATTERN), key=lambda item: item.name)
    if any(item.is_symlink() or not item.is_file() for item in candidates):
        raise RuntimeError("ScientificValidation test evidence must be regular files")
    if not candidates:
        if pattern == _PATTERN:
            return standard_tests
        raise RuntimeError("ScientificValidation ownership discovered zero test modules")
    suite = loader.loadTestsFromNames(
        [f"{__name__}.{item.stem}" for item in candidates]
    )
    if suite.countTestCases() == 0:
        raise RuntimeError("ScientificValidation ownership discovered zero tests")
    return suite
