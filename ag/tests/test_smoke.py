"""Installation smoke tests and the registration seam used by T2/T5."""

import json
from pathlib import Path
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


@pytest.mark.parametrize("command", ["facts", "thermo", "dedup", "cluster", "graph", "profile"])
def test_registered_command_runs_without_loading_config(monkeypatch, command):
    seen = []

    def register(subparsers):
        subparsers.add_parser(command).set_defaults(func=lambda args: 7)

    def load(name):
        seen.append(name)
        if name == f"ag.{command}":
            return SimpleNamespace(register=register)
        raise ModuleNotFoundError(name=name)

    def unexpected_config_load():
        pytest.fail("Extension commands must not load the core configuration")

    monkeypatch.setattr(cli, "import_module", load)
    monkeypatch.setattr(cli, "load_config", unexpected_config_load)
    assert cli.main([command]) == 7
    assert seen == ["ag.facts", "ag.thermo", "ag.dedup", "ag.cluster", "ag.graph", "ag.irc_compare", "ag.profile"]


def test_dedup_help_and_run_without_config(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert not (tmp_path / ".config/ag/config.toml").exists()
    with pytest.raises(SystemExit) as help_exit:
        cli.main(["dedup", "--help"])
    assert help_exit.value.code == 0
    assert "usage: ag dedup" in capsys.readouterr().out

    data = Path(__file__).parent / "data" / "butane.xyz"
    assert cli.main(["dedup", str(data), "--charge", "0", "--out", str(tmp_path), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["kept"]) == 3
    assert Path(result["output"]).is_file()
    assert (tmp_path / result["xyz_file"]).is_file()


@pytest.mark.parametrize("argv", [
    ["init", "study"],
    ["prepare", "--study", "study", "--template", "gaussian", "--input", "input.gjf",
     "--tier", "simple", "--walltime", "00:30:00", "--label", "sp"],
    ["submit", "attempt"], ["status"], ["fetch", "attempt"],
    ["cancel", "attempt"], ["list"], ["doctor"],
])
def test_core_commands_still_require_config(monkeypatch, tmp_path, capsys, argv):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    def unexpected_command(args):
        pytest.fail("Core commands must validate configuration before running")

    monkeypatch.setattr(cli, "core_command", unexpected_command)
    assert cli.main(argv) == 1
    assert "Missing or invalid local configuration" in capsys.readouterr().err


def test_missing_dependency_is_not_silently_skipped(monkeypatch):
    def load(name):
        raise ModuleNotFoundError(name="missing_dependency")

    monkeypatch.setattr(cli, "import_module", load)
    with pytest.raises(ModuleNotFoundError) as error:
        cli.main(["--version"])
    assert error.value.name == "missing_dependency"
