"""Auto-G16 V31 Transport direct test-module ownership."""

from pathlib import Path


def load_tests(loader, standard_tests, pattern):
    if pattern not in (None, "test*.py"):
        return standard_tests
    directory = Path(__file__).parent
    names = [f"{__name__}.{entry.stem}" for entry in sorted(directory.iterdir())
             if entry.name.startswith("test") and entry.suffix == ".py"]
    if not names:
        raise RuntimeError("V31 Transport has no owned test modules")
    for name in names:
        module_suite = loader.loadTestsFromName(name)
        if module_suite.countTestCases() == 0:
            raise RuntimeError(f"V31 Transport module has no tests: {name}")
        standard_tests.addTests(module_suite)
    return standard_tests
