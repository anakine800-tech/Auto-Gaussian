"""Own the focused tests for the V31 functional thermochemistry kernel."""

import unittest


_OWNED_TEST_MODULES = (
    "tests.v31.thermochemistry.test_core",
    "tests.v31.thermochemistry.test_goodvibes_qualification",
)


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, "test*.py"}:
        return standard_tests
    suite = loader.loadTestsFromNames(_OWNED_TEST_MODULES)
    if suite.countTestCases() == 0:
        raise RuntimeError("V31 thermochemistry package ownership resolved to zero tests")
    return suite
