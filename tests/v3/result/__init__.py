"""Deterministic package aggregation for V30 result tests."""

from __future__ import annotations

import unittest
from pathlib import Path


_TEST_PATTERN = "test*.py"


def _direct_test_module_names() -> list[str]:
    directory = Path(__file__).resolve().parent
    candidates = sorted(directory.glob(_TEST_PATTERN), key=lambda path: path.name)
    if any(path.is_symlink() for path in candidates):
        raise RuntimeError(f"{__name__} refuses symlinked test modules")
    return [
        f"{__name__}.{path.stem}"
        for path in candidates
        if path.parent == directory and path.is_file()
    ]


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, _TEST_PATTERN}:
        return standard_tests
    module_names = _direct_test_module_names()
    if not module_names:
        raise RuntimeError(f"{__name__} contains no direct {_TEST_PATTERN} test modules")
    suite = loader.loadTestsFromNames(module_names)
    if suite.countTestCases() == 0:
        raise RuntimeError(f"{__name__} discovered zero tests")
    return suite
