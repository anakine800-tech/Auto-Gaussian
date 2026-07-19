#!/usr/bin/env python3
"""Run offline unittests with deterministic, readable slow-test statistics."""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
    args = parser.parse_args(argv)
    if args.top_slow < 1 or args.slow_threshold < 0:
        parser.error("--top-slow must be positive and --slow-threshold must be non-negative")

    suite = build_suite(args.names, args.start_directory, args.pattern)
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
