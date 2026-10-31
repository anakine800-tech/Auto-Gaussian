"""The diagnostic CLI loads no runtime guards and leaves a fresh HOME empty."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ag import autonomy, autonomy_submission, cli, config


@pytest.mark.parametrize('ok', [True, False])
def test_audit_cli_reports_all_rows_and_returns_health_exit_code(monkeypatch, capsys, ok):
    configured = {'local': {'studies_root': 'synthetic'}, 'clusters': {}}
    calls = []
    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return configured
    result = dict(ok=ok, coverage={'complete': True, 'errors': []}, records=[
        {'attempt_id': 'water-a', 'classification': 'refused' if not ok else 'unconsumed'},
        {'attempt_id': 'water-b', 'classification': 'unconsumed'},
    ])
    def audit(cfg, *, configuration_error):
        assert cfg is configured and configuration_error is None
        assert sys.dont_write_bytecode is True
        return result
    monkeypatch.setattr(config, 'load_config', load)
    monkeypatch.setattr(autonomy_submission, 'audit_reservations', audit, raising=False)
    monkeypatch.setattr(cli, 'register', lambda *args: pytest.fail('Broad runtime command registration'))
    monkeypatch.setattr(autonomy, 'run', lambda *args: pytest.fail('Autonomy mutation dispatch'))
    previous = sys.dont_write_bytecode
    assert cli.main(['autonomy', 'audit-reservations', '--json']) == (0 if ok else 1)
    assert json.loads(capsys.readouterr().out) == result
    assert calls == [((), {})]  # Full local configuration, not local_only's stripped view.
    assert sys.dont_write_bytecode is previous


def test_bad_configuration_still_dispatches_registry_audit(monkeypatch, capsys):
    def load():
        raise config.ConfigError('Synthetic invalid configuration')
    def audit(cfg, *, configuration_error):
        assert cfg is None
        assert configuration_error == (
            'Cannot read complete local configuration; configured studies coverage is unknown')
        return dict(ok=False, coverage={'complete': False, 'errors': [configuration_error]},
                    records=[{'attempt_id': 'water-a', 'classification': 'refused'}])
    monkeypatch.setattr(config, 'load_config', load)
    monkeypatch.setattr(autonomy_submission, 'audit_reservations', audit, raising=False)
    assert cli.main(['autonomy', 'audit-reservations']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['coverage']['complete'] is False
    assert result['records'][0]['attempt_id'] == 'water-a'


def test_audit_cli_rejects_study_filter_before_reading(monkeypatch, capsys):
    monkeypatch.setattr(config, 'load_config', lambda: pytest.fail('Unexpected configuration read'))
    previous = sys.dont_write_bytecode
    with pytest.raises(SystemExit) as error:
        cli.main(['autonomy', 'audit-reservations', '--study', 'water'])
    assert error.value.code == 2
    assert 'unrecognized arguments' in capsys.readouterr().err
    assert sys.dont_write_bytecode is previous


def test_fresh_home_cli_writes_no_files_or_bytecode(tmp_path, monkeypatch):
    home = tmp_path / 'empty-home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    assert Path.home() == home
    cache = tmp_path / 'bytecode'
    environment = dict(os.environ)
    environment.pop('PYTHONDONTWRITEBYTECODE', None)
    environment['PYTHONPYCACHEPREFIX'] = str(cache)
    environment['PYTHONPATH'] = str(Path(cli.__file__).parents[1])
    result = subprocess.run(
        [sys.executable, '-B', '-m', 'ag.cli', 'autonomy', 'audit-reservations', '--json'],
        cwd=home, env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report['ok'] is False and report['coverage']['complete'] is False
    assert isinstance(report['records'], list)
    assert not list(home.iterdir())
    assert not cache.exists()
