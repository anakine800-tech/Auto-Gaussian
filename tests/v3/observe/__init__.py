"""Deterministic package-level discovery for minimal Observe evidence."""

from __future__ import annotations

from pathlib import Path
import unittest


_OWNED_PATTERN = "test*.py"


def _owned_test_modules() -> tuple[str, ...]:
    package_directory = Path(__file__).resolve().parent
    entries = tuple(
        sorted(package_directory.glob(_OWNED_PATTERN), key=lambda path: path.name)
    )
    irregular = tuple(path for path in entries if path.is_symlink() or not path.is_file())
    if irregular:
        raise RuntimeError("Observe owned test modules must be regular files")
    return tuple(f"{__name__}.{path.stem}" for path in entries)


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern is not None and pattern != _OWNED_PATTERN:
        return standard_tests
    module_names = _owned_test_modules()
    if not module_names:
        if pattern == _OWNED_PATTERN:
            return standard_tests
        raise RuntimeError("Observe ownership discovered zero test modules")
    discovered = loader.loadTestsFromNames(module_names)
    if discovered.countTestCases() < 1:
        raise RuntimeError("Observe ownership discovered zero tests")
    return discovered
