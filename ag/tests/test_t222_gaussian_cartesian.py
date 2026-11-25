"""T222: strict Gaussian prepare, plus the shared readers which accept integer coordinates."""
from contextlib import contextmanager
import json

import pytest

from ag import attempt, cli, config, confirm, gaussian_input, status, study, submit
from ag.transport import Result
import test_core
from test_approval import record
from test_autonomy_submission import t186_driver_factory
from test_core import Fake, cfg
from test_counterpoise import prepare_cp
from test_parent_chk_report import local, run_cli
from test_unknown_start_binding import StartFake, assert_read_only_since, frozen


RESOURCES = '%nprocshared=8\n%mem=10GB\n'
WATER = '8 -.0 +0. 0E-2\n1 .0 +0e0 1.0\n1 0.0 1. .0'
GROUP = 'Water\nsecond title line\n\n0 1\n' + WATER


def prepare_cli(cfg, tmp_path, monkeypatch, raw, *options, template='gaussian'):
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    source = tmp_path / ('water.gjf' if template == 'gaussian' else 'water.xyz')
    source.write_bytes(raw)
    code = cli.main(['prepare', '--study', 'water', '--input', str(source),
                     '--template', template, '--tier', 'simple', '--walltime', '00:10:00',
                     '--label', 'sp', '--method-basis', 'synthetic fixture', '--json', *options])
    assert source.read_bytes() == raw
    return code


@pytest.mark.parametrize('resources,token,axis', [
    ('', '0', 'x'), ('%mem=10GB\n', '-2', 'y'), ('%nprocshared=8\n', '+1', 'z'),
    (RESOURCES, '-0', 'z'),
])
def test_integer_is_reported_at_the_source_line(cfg, tmp_path, monkeypatch, capsys, resources, token, axis):
    study.init(cfg, 'water')
    xyz = ['.0', '+0e0', '1.0']
    xyz['xyz'.index(axis)] = token
    row = '1 ' + ' '.join(xyz)
    text = resources + '\n# HF/STO-3G SP\n \n\n' + GROUP.replace('1 .0 +0e0 1.0', row) + '\n\n'
    raw = text.replace('\n', '\r\n').encode()
    code = prepare_cli(cfg, tmp_path, monkeypatch, raw)
    assert code != 0
    error = json.loads(capsys.readouterr().out)['error']
    assert f'line {text.splitlines().index(row) + 1}:' in error
    assert f'{axis} coordinate' in error and f'{token}.0' in error
    assert list((study.locate(cfg, 'water') / 'attempts').iterdir()) == []


@pytest.mark.parametrize('count,group', [(2, 1), (2, 2), (3, 1), (3, 2), (3, 3)])
def test_qst_reports_group_and_source_line(cfg, tmp_path, monkeypatch, capsys, count, group):
    study.init(cfg, 'water')
    groups = [GROUP] * count
    groups[group - 1] = GROUP.replace('1 .0 +0e0 1.0', '1 .0 +0e0 +1')
    text = f'# HF/STO-3G Opt=QST{count}\n\n' + '\n  \n\n'.join(groups) + '\n\n'
    assert prepare_cli(cfg, tmp_path, monkeypatch, text.encode()) != 0
    error = json.loads(capsys.readouterr().out)['error']
    line = text.splitlines().index('1 .0 +0e0 +1') + 1
    assert f'QST{count} group {group}: line {line}:' in error and '+1.0' in error
    assert not list((study.locate(cfg, 'water') / 'attempts').iterdir())


@pytest.mark.parametrize('count', [1, 2, 3])
def test_real_spellings_and_integer_noncoordinates_keep_bytes(cfg, tmp_path, monkeypatch, capsys, count):
    study.init(cfg, 'water')
    route = 'Opt=ModRedundant' if count == 1 else f'Opt=QST{count}'
    text = RESOURCES + f'# HF/STO-3G {route}\n\n' + '\n\n'.join([GROUP] * count) + '\n\n'
    if count == 1:
        text += 'B 1 2 S 2 0.1\n\n'
    raw = text.replace('\n', '\r\n').encode()
    assert prepare_cli(cfg, tmp_path, monkeypatch, raw) == 0
    m = json.loads(capsys.readouterr().out)
    assert m['science']['geometry'] == WATER
    path = attempt.find(cfg, m['attempt_id'])
    files = attempt.verified_files(cfg, path, m)
    assert files['water.gjf'] == raw
    assert attempt.bundle(files) == (m['inputs'], m['bundle_sha256'])


@pytest.mark.parametrize('template', ['xtb', 'crest', 'relaxed'])
def test_integer_coordinates_in_other_formats(cfg, tmp_path, monkeypatch, capsys, template):
    study.init(cfg, 'water')
    rows = 'O 0 0 0\nH 0 0 1\nH 0 1 0'
    if template == 'relaxed':
        raw = (RESOURCES + '# HF/STO-3G SP\n\nWater\n\n0 1\n' + rows + '\n\n').encode()
        code = prepare_cli(cfg, tmp_path, monkeypatch, raw, '--relaxed-input')
    else:
        raw = ('3\nWater\n' + rows + '\n').encode()
        code = prepare_cli(cfg, tmp_path, monkeypatch, raw, template=template)
    assert code == 0
    m = json.loads(capsys.readouterr().out)
    assert m['science']['geometry'] == rows


def test_counterpoise_keeps_its_existing_coordinate_grammar(cfg, tmp_path):
    path, m = prepare_cp(cfg, tmp_path, geometry='He 0 0 0\nHe 0 0 5',
                         csv='fragment,atoms,charge,multiplicity\na,1,0,1\nb,2,0,1\n')
    files = attempt.verified_files(cfg, path, m)
    assert b'He(Fragment=1) 0 0 0\nHe(Fragment=2) 0 0 5' in files['water.gjf']


def test_archived_integer_input_and_log_still_verify(local):
    root, parent, child = local
    files = {p: p.read_bytes() for directory in (parent, child)
             for p in directory.rglob('*') if p.is_file()}
    assert b'O 0 0 0' in files[parent / 'inputs/water.gjf']
    assert run_cli(local) == 0
    report = json.loads((root / 'analyses/report.json').read_bytes())
    assert report['frequency']['status'] == 'normal_frequency_found'
    assert report['checkpoint']['binding']['status'] == 'matched'
    assert all(p.read_bytes() == raw for p, raw in files.items())


@contextmanager
def pre_t222_parser(monkeypatch):
    """Reproduce only the earlier coordinate grammar while building a historical fixture."""
    validate = gaussian_input.validate

    def legacy_validate(*args, **kwargs):
        kwargs['require_real_coordinates'] = False
        return validate(*args, **kwargs)

    with monkeypatch.context() as old:
        old.setattr(gaussian_input, 'validate', legacy_validate)
        yield


def legacy_attempt(cfg, tmp_path, monkeypatch, capsys, count):
    study.init(cfg, 'water')
    groups = [GROUP] * count
    groups[-1] = GROUP.replace('1 .0 +0e0 1.0', '1 .0 +0e0 -1')
    route = 'SP' if count == 1 else f'Opt=QST{count}'
    raw = (RESOURCES + f'# HF/STO-3G {route}\n\n' + '\n\n'.join(groups) + '\n\n').encode()
    with pre_t222_parser(monkeypatch):
        assert prepare_cli(cfg, tmp_path, monkeypatch, raw) == 0
    m = json.loads(capsys.readouterr().out)
    return attempt.find(cfg, m['attempt_id']), m, raw


@pytest.mark.parametrize('count', [1, 2, 3])
def test_legacy_unclaimed_refused_before_authorization_or_transport(cfg, tmp_path, monkeypatch, capsys, count):
    path, m, raw = legacy_attempt(cfg, tmp_path, monkeypatch, capsys, count)
    before = {p: p.read_bytes() for p in path.rglob('*') if p.is_file()}
    monkeypatch.setattr(confirm, 'confirm', lambda *_: pytest.fail('unexpected confirmation'))
    fake = Fake(cfg)
    line = raw.splitlines().index(b'1 .0 +0e0 -1') + 1
    prefix = f'QST{count} group {count}: ' if count > 1 else ''
    with pytest.raises(ValueError) as caught:
        submit.submit(cfg, [path.name], fake)
    assert f'{prefix}line {line}: bare integer z coordinate' in str(caught.value)
    assert '-1.0' in str(caught.value) and 'prepare a new Attempt' in str(caught.value)
    assert fake.operations() == [] and not (path / '.submit-claim').exists()
    assert before == {p: p.read_bytes() for p in path.rglob('*') if p.is_file()}
    assert attempt.read_manifest(path) == m


def test_autonomous_dispatch_refuses_same_unclaimed_input(request, monkeypatch):
    with pre_t222_parser(monkeypatch), monkeypatch.context() as old:
        old.setattr(test_core, 'INPUT', test_core.INPUT.replace('O 0.0 0.0 0.0', 'O 0.0 0 0.0'))
        driver = request.getfixturevalue('t186_driver_factory')
        cfg, path, m, context, _, _ = driver('integer-legacy')
    before = (path / 'inputs/water.gjf').read_bytes()
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='line 9: bare integer y coordinate.*prepare a new Attempt'):
        submit.submit(cfg, [path.name], fake, autonomous=context)
    assert fake.operations() == [] and not (path / '.submit-claim').exists()
    assert (path / 'inputs/water.gjf').read_bytes() == before and attempt.read_manifest(path) == m


def test_claimed_legacy_bundle_recovers_receipt_without_resubmission(cfg, tmp_path, monkeypatch, capsys):
    path, m, raw = legacy_attempt(cfg, tmp_path, monkeypatch, capsys, 1)
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    fake = StartFake(cfg, m)
    fake.qsub = Result(255, '', 'Synthetic lost response')
    with pre_t222_parser(monkeypatch), pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [path.name], fake, approval_id=record(cfg, path)['id'])
    before = frozen(path)
    first = len(fake.calls)
    assert attempt.verified_files(cfg, path, m)['water.gjf'] == raw
    result = status.check(cfg, path, fake)
    assert result['job_id'] == 'default:123.fixture'
    assert result['start_reconciliation']['remote_input_verification'] == 'size+sha256'
    with pytest.raises(ValueError, match='consumed'):
        submit.submit(cfg, [path.name], fake)
    assert frozen(path) == before
    assert_read_only_since(fake, first)
