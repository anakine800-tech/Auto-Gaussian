"""Fail-closed V31 conformer scientific-core test aggregation."""

from __future__ import annotations

from pathlib import Path
import unittest


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, "test*.py"}:
        return standard_tests
    root = Path(__file__).resolve().parent
    modules = sorted(
        f"{__name__}.{candidate.stem}"
        for candidate in root.glob("test*.py")
        if candidate.is_file() and not candidate.is_symlink()
    )
    if not modules:
        if pattern == "test*.py":
            return standard_tests
        raise RuntimeError("V31 conformer test ownership discovered no modules")
    suite = loader.loadTestsFromNames(modules)
    if suite.countTestCases() == 0:
        raise RuntimeError("V31 conformer test ownership discovered no tests")
    return suite
