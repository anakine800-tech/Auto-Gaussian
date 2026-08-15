#!/usr/bin/env python3
"""Run offline unittests with deterministic, readable slow-test statistics."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SELECTION_SCHEMA = "auto-g16-validation-selection-result/1"
SELECTION_KEYS = {
    "schema",
    "version",
    "base",
    "head",
    "merge_base",
    "head_tree",
    "changed_paths",
    "changes",
    "lane",
    "tests",
    "matched_routes",
    "safety_evidence",
    "fail_closed",
    "reasons",
}
SELECTION_LANES = {"focused", "affected", "v3-full", "legacy-release"}
FULL_SHA = re.compile(r"[0-9a-f]{40}")


class SelectionError(ValueError):
    """A selector result cannot safely determine a unittest suite."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SelectionError(f"duplicate JSON key is forbidden: {ascii(key)}")
        result[key] = value
    return result


def load_selection(path: Path) -> tuple[str, list[str]]:
    if path.is_symlink() or not path.is_file():
        raise SelectionError("selection must be a regular non-symlink JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"invalid selection JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != SELECTION_KEYS:
        raise SelectionError("selection result must be a closed object")
    if value["schema"] != SELECTION_SCHEMA or value["version"] != 1:
        raise SelectionError("unsupported selection result schema/version")
    for key in ("base", "head", "merge_base", "head_tree"):
        item = value[key]
        if item is not None and (not isinstance(item, str) or not FULL_SHA.fullmatch(item)):
            raise SelectionError(f"selection result {key} must be null or a full SHA")
    for key in ("changed_paths", "matched_routes", "safety_evidence", "reasons"):
        items = value[key]
        if not isinstance(items, list) or not all(
            isinstance(item, str) and item and item == item.strip() for item in items
        ):
            raise SelectionError(f"selection result {key} must be a trimmed string array")
        if len(items) != len(set(items)):
            raise SelectionError(f"selection result {key} must not contain duplicates")
    if not value["reasons"]:
        raise SelectionError("selection result reasons must not be empty")
    if not isinstance(value["changes"], list) or not isinstance(value["fail_closed"], bool):
        raise SelectionError("selection result changes/fail_closed fields are invalid")
    change_paths: list[str] = []
    for change in value["changes"]:
        if not isinstance(change, dict) or set(change) != {"status", "paths"}:
            raise SelectionError("selection result change must be a closed status/path object")
        if not isinstance(change["status"], str) or not change["status"]:
            raise SelectionError("selection result change status is invalid")
        paths = change["paths"]
        if not isinstance(paths, list) or not paths or not all(
            isinstance(item, str) and item and item == item.strip() for item in paths
        ):
            raise SelectionError("selection result change paths are invalid")
        change_paths.extend(paths)
    if value["changed_paths"] != sorted(set(change_paths)):
        raise SelectionError("selection result changed_paths do not match change records")
    lane = value["lane"]
    tests = value["tests"]
    if lane not in SELECTION_LANES:
        raise SelectionError("selection result lane is unsupported")
    if not isinstance(tests, list) or not all(
        isinstance(item, str) and item.startswith("tests.") and item == item.strip()
        for item in tests
    ):
        raise SelectionError("selection result tests must be dotted tests.* names")
    if len(tests) != len(set(tests)):
        raise SelectionError("selection result tests must not contain duplicates")
    if lane == "legacy-release" and tests:
        raise SelectionError("legacy-release must use full discovery, not a partial test list")
    if lane != "legacy-release" and not tests:
        raise SelectionError("non-legacy selections must contain at least one test")
    if value["fail_closed"] and lane != "legacy-release":
        raise SelectionError("fail-closed selection must expand to legacy-release")
    return lane, tests


class TimingResult(unittest.TextTestResult):
    """Collect per-test wall time without changing unittest semantics."""

    def startTest(self, test: unittest.case.TestCase) -> None:
        self._started_at = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test: unittest.case.TestCase) -> None:
        duration = time.perf_counter() - self._started_at
        self.test_timings.append((duration, self.getDescription(test)))
        super().stopTest(test)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.test_timings: list[tuple[float, str]] = []


def print_slow_tests(
    timings: list[tuple[float, str]],
    *,
    top: int,
    threshold: float,
) -> None:
    selected = [item for item in sorted(timings, reverse=True) if item[0] >= threshold][:top]
    print(f"\nSLOW TESTS (top {top}, threshold {threshold:.3f}s)")
    if not selected:
        print("  none")
        return
    width = max(len(f"{duration:.3f}s") for duration, _name in selected)
    for duration, name in selected:
        print(f"  {duration:.3f}s".rjust(width + 2), name)


def build_suite(names: list[str], start_directory: str, pattern: str) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    if names:
        return loader.loadTestsFromNames(names)
    requested = Path(start_directory)
    start = requested if requested.is_absolute() else ROOT / requested
    return loader.discover(str(start), pattern=pattern)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="optional dotted unittest names")
    parser.add_argument("--start-directory", default="tests")
    parser.add_argument("--pattern", default="test*.py")
    parser.add_argument("--top-slow", type=int, default=15)
    parser.add_argument("--slow-threshold", type=float, default=1.0)
    parser.add_argument("--verbosity", type=int, choices=(0, 1, 2), default=2)
    parser.add_argument("--selection", type=Path, help="closed selector result JSON")
    args = parser.parse_args(argv)
    if args.top_slow < 1 or args.slow_threshold < 0:
        parser.error("--top-slow must be positive and --slow-threshold must be non-negative")

    names = args.names
    if args.selection is not None:
        if names or args.start_directory != "tests" or args.pattern != "test*.py":
            parser.error("--selection cannot be combined with names, --start-directory, or --pattern")
        try:
            lane, selected = load_selection(args.selection)
        except SelectionError as exc:
            parser.error(str(exc))
        names = selected if lane != "legacy-release" else []
        print(f"VALIDATION SELECTION lane={lane} tests={len(selected)}")

    suite = build_suite(names, args.start_directory, args.pattern)
    runner = unittest.TextTestRunner(verbosity=args.verbosity, resultclass=TimingResult)
    result = runner.run(suite)
    assert isinstance(result, TimingResult)
    print_slow_tests(
        result.test_timings,
        top=args.top_slow,
        threshold=args.slow_threshold,
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
