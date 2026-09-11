"""Auto-G16 V31 offline tooling test package ownership."""

from pathlib import Path


def load_tests(loader, standard_tests, pattern):
    if pattern not in (None, "test*.py"):
        return standard_tests
    directory = Path(__file__).parent
    entries = sorted(directory.glob("test*.py"))
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise RuntimeError("V31 tooling test modules must be regular files")
    if not entries:
        if pattern == "test*.py":
            return standard_tests
        raise RuntimeError("V31 tooling has no owned test modules")
    for entry in entries:
        suite = loader.loadTestsFromName(f"{__name__}.{entry.stem}")
        if not suite.countTestCases():
            raise RuntimeError(f"V31 tooling module has no tests: {entry.stem}")
        standard_tests.addTests(suite)
    return standard_tests
