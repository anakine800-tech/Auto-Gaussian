"""Explicit method provenance is required before any local Attempt is reserved."""
import json
from pathlib import Path

import pytest

from ag import attempt, cli, study
from test_core import INPUT, cfg  # noqa: F401 - synthetic configuration fixture


@pytest.fixture(params=('gaussian', 'xtb', 'crest'))
def prepare_case(cfg, tmp_path, monkeypatch, request):
    study.init(cfg, 'smoke')
    template = request.param
    source = tmp_path / ('water.gjf' if template == 'gaussian' else 'water.xyz')
    source.write_text(INPUT if template == 'gaussian' else '3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport',
                        lambda *a, **k: pytest.fail('prepare must not connect'))
    options = dict(study_name='smoke', template=template, input_path=source,
                   tier='simple', walltime='00:30:00', label='basis')
    args = ['prepare', '--study', 'smoke', '--template', template, '--input', str(source),
            '--tier', 'simple', '--walltime', '00:30:00', '--label', 'basis', '--json']
    return args, options, Path(cfg['local']['studies_root']) / 'smoke'


def test_cli_missing_method_basis_does_not_create_attempt(prepare_case, monkeypatch, capsys):
    args, _, directory = prepare_case
    journal = (directory / 'journal.jsonl').read_bytes()
    monkeypatch.setattr(cli, 'load_config', lambda: pytest.fail('missing argument must fail before config'))
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert '--method-basis' in error
    for category in ('文献先例', '本课题既有方案', '兜底方法'):
        assert category in error
    assert list((directory / 'attempts').iterdir()) == []
    assert (directory / 'journal.jsonl').read_bytes() == journal


@pytest.mark.parametrize('basis', ('', ' ', '\t\n', '\u3000'))
def test_cli_blank_method_basis_does_not_create_attempt(prepare_case, capsys, basis):
    args, _, directory = prepare_case
    journal = (directory / 'journal.jsonl').read_bytes()
    assert cli.main(args + ['--method-basis', basis]) == 1
    error = json.loads(capsys.readouterr().out)['error']
    for category in ('文献先例', '本课题既有方案', '兜底方法'):
        assert category in error
    assert list((directory / 'attempts').iterdir()) == []
    assert (directory / 'journal.jsonl').read_bytes() == journal


@pytest.mark.parametrize('basis', (
    '文献先例：10.0000/synthetic；SI p. S1（合成测试占位）',
    '本课题既有方案：synthetic-study；不是文献先例，精度未经验证',
    '兜底方法：合成流程验收',
    '  本课题既有方案：synthetic-study；不是文献先例，精度未经验证  ',
))
def test_cli_preserves_explicit_basis_in_manifest_and_summary(cfg, prepare_case, capsys, basis):
    args, _, directory = prepare_case
    assert cli.main(args + ['--method-basis', basis]) == 0
    result = json.loads(capsys.readouterr().out)
    path = directory / 'attempts' / result['attempt_id']
    manifest = json.loads((path / 'manifest.json').read_text())
    assert result['science']['method_basis'] == basis
    assert manifest['science']['method_basis'] == basis
    assert basis in attempt.summary(cfg, manifest)


def test_python_prepare_also_requires_method_basis(cfg, prepare_case):
    _, options, directory = prepare_case
    with pytest.raises(TypeError, match='method_basis'):
        attempt.prepare(cfg, **options)
    for basis in ('', ' \t\n', None):
        with pytest.raises(ValueError, match='Method basis must be nonblank'):
            attempt.prepare(cfg, method_basis=basis, **options)
    assert list((directory / 'attempts').iterdir()) == []
