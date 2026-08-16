#!/usr/bin/env python3
"""Run offline unittests with deterministic, readable slow-test statistics."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SELECTOR_PATH = ROOT / "scripts" / "select_validation.py"
SELECTOR_SPEC = importlib.util.spec_from_file_location("validation_selector", SELECTOR_PATH)
assert SELECTOR_SPEC and SELECTOR_SPEC.loader
SELECTOR = importlib.util.module_from_spec(SELECTOR_SPEC)
SELECTOR_SPEC.loader.exec_module(SELECTOR)

SelectionError = SELECTOR.SelectionError


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SelectionError(f"duplicate JSON key is forbidden: {ascii(key)}")
        result[key] = value
    return result


def load_selection(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SelectionError("selection must be a regular non-symlink JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"invalid selection JSON: {exc}") from exc
    return SELECTOR.validate_result(value)


def resolve_authoritative_selection(
    path: Path,
    *,
    repository: Path,
    base: str,
    head: str,
) -> tuple[str, list[str]]:
    serialized = load_selection(path)
    canonical = SELECTOR.compute_selection(repository, base, head)
    mismatches = sorted(
        key for key in SELECTOR.RESULT_KEYS if serialized[key] != canonical[key]
    )
    if mismatches:
        raise SelectionError(
            "serialized selection differs from the recomputed canonical decision: "
            + ", ".join(mismatches)
        )
    return canonical["lane"], canonical["tests"]


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
    parser.add_argument("--base", help="full base SHA independently supplied to the runner")
    parser.add_argument("--head", help="full candidate SHA independently supplied to the runner")
    args = parser.parse_args(argv)
    if args.top_slow < 1 or args.slow_threshold < 0:
        parser.error("--top-slow must be positive and --slow-threshold must be non-negative")

    names = args.names
    if args.selection is not None:
        if names or args.start_directory != "tests" or args.pattern != "test*.py":
            parser.error("--selection cannot be combined with names, --start-directory, or --pattern")
        if args.base is None or args.head is None:
            parser.error("--selection requires independent --base and --head identities")
        try:
            lane, selected = resolve_authoritative_selection(
                args.selection,
                repository=ROOT,
                base=args.base,
                head=args.head,
            )
        except SelectionError as exc:
            parser.error(str(exc))
        names = selected if lane != "legacy-release" else []
        print(f"VALIDATION SELECTION lane={lane} tests={len(selected)}")
    elif args.base is not None or args.head is not None:
        parser.error("--base and --head are valid only with --selection")

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
