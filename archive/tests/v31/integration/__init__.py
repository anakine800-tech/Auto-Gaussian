"""Authoritative discovery owner for the V31 offline end-to-end lane."""

from __future__ import annotations

import unittest


_OWNED_MODULES = ("tests.v31.integration.test_v31_offline_end_to_end",)


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for module_name in _OWNED_MODULES:
        suite.addTests(loader.loadTestsFromName(module_name))
    if suite.countTestCases() == 0:
        raise RuntimeError("V31 offline end-to-end discovery selected zero tests")
    return suite
