"""Fail-closed direct-module loader for the V30 Transport evidence package."""

from __future__ import annotations

import fnmatch
import importlib
import os
import unittest


_DISCOVERY_GLOB = "test*.py"


def _owned_module_names() -> tuple[str, ...]:
    package_directory = os.path.dirname(__file__)
    discovered: list[str] = []
    with os.scandir(package_directory) as entries:
        for entry in entries:
            if not fnmatch.fnmatchcase(entry.name, _DISCOVERY_GLOB):
                continue
            if entry.is_symlink():
                raise RuntimeError("Transport validation refuses symlinked modules")
            if not entry.is_file(follow_symlinks=False):
                continue
            discovered.append(f"{__name__}.{entry.name[:-3]}")
    return tuple(sorted(discovered, key=lambda value: value.encode("utf-8")))


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    if pattern not in {None, _DISCOVERY_GLOB}:
        return standard_tests
    names = _owned_module_names()
    if not names:
        if pattern == _DISCOVERY_GLOB:
            return standard_tests
        raise RuntimeError("Transport validation discovered no direct modules")
    aggregate = unittest.TestSuite()
    for name in names:
        aggregate.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    if aggregate.countTestCases() == 0:
        raise RuntimeError("Transport validation discovered zero test cases")
    return aggregate
