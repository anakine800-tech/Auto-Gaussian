"""Exact V31 thermochemistry test ownership."""

from __future__ import annotations

import unittest


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, "test*.py"}:
        return standard_tests
    suite = loader.loadTestsFromName(f"{__name__}.test_core")
    if suite.countTestCases() != 29:
        raise RuntimeError("V31 thermochemistry ownership requires exactly 29 contract tests")
    return suite
