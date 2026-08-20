"""Closed package aggregation for the frozen V30-4 Workflow slice."""

from __future__ import annotations

from pathlib import Path
import unittest


_TEST_PATTERN = "test*.py"
_OWNED_MODULES = (
    "test_acceptance_inventory",
    "test_contract",
    "test_store_replay",
    "test_validation",
)


def _direct_test_module_names() -> tuple[str, ...]:
    directory = Path(__file__).resolve().parent
    candidates = tuple(sorted(directory.glob(_TEST_PATTERN), key=lambda path: path.name))
    if any(path.is_symlink() for path in candidates):
        raise RuntimeError("Workflow evidence tests may not be symlinked")
    observed = tuple(
        path.stem for path in candidates if path.parent == directory and path.is_file()
    )
    if observed != _OWNED_MODULES:
        raise RuntimeError(
            "Workflow test ownership is incomplete or ambiguous: "
            f"expected {_OWNED_MODULES!r}, observed {observed!r}"
        )
    return tuple(f"{__name__}.{module}" for module in _OWNED_MODULES)


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, _TEST_PATTERN}:
        return standard_tests
    suite = loader.loadTestsFromNames(_direct_test_module_names())
    if suite.countTestCases() == 0:
        raise RuntimeError("Workflow ownership discovered zero validation evidence")
    return suite
