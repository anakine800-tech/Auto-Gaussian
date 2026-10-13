"""Installation smoke tests and the registration seam used by T2/T5."""

import subprocess
from types import SimpleNamespace

import pytest

from ag import __version__, cli


def test_import():
    assert __version__ == "0.1.0"


def test_installed_version():
    result = subprocess.run(["ag", "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.strip() == __version__
    assert result.stderr == ""


def test_registered_command_runs(monkeypatch):
    seen = []

    def register(subparsers):
        subparsers.add_parser("facts").set_defaults(func=lambda args: 7)

    def load(name):
        seen.append(name)
        if name == "ag.facts":
            return SimpleNamespace(register=register)
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(cli, "import_module", load)
    assert cli.main(["facts"]) == 7
    assert seen == ["ag.facts", "ag.thermo", "ag.dedup", "ag.cluster", "ag.graph"]


def test_missing_dependency_is_not_silently_skipped(monkeypatch):
    def load(name):
        raise ModuleNotFoundError(name="missing_dependency")

    monkeypatch.setattr(cli, "import_module", load)
    with pytest.raises(ModuleNotFoundError) as error:
        cli.main(["--version"])
    assert error.value.name == "missing_dependency"
