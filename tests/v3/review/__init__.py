"""Review-owned deterministic test aggregation."""

from __future__ import annotations

from pathlib import Path
import unittest


class ReviewTestDiscoveryError(RuntimeError):
    pass


def _owned_modules() -> tuple[str, ...]:
    root = Path(__file__).resolve().parent
    modules: list[str] = []
    for candidate in root.iterdir():
        if not candidate.name.startswith("test") or candidate.suffix != ".py":
            continue
        if candidate.parent != root or candidate.is_symlink() or not candidate.is_file():
            raise ReviewTestDiscoveryError(
                "Review test ownership requires direct regular Python modules"
            )
        modules.append(f"{__name__}.{candidate.stem}")
    return tuple(sorted(modules))


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, "test*.py"}:
        return standard_tests
    modules = _owned_modules()
    if not modules:
        if pattern == "test*.py":
            return standard_tests
        raise ReviewTestDiscoveryError("Review test ownership has no modules")
    suite = loader.loadTestsFromNames(modules)
    if suite.countTestCases() == 0:
        raise ReviewTestDiscoveryError("Review test ownership has no cases")
    return suite
