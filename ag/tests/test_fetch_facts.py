"""T52: local synthetic outputs, real parsers, and fake read-only transports."""
import builtins
import json

import pytest

from ag import attempt, cli, facts, fetch, journal, remote, state, transport
from test_core import cfg, prepared, finish  # noqa: F401
from test_fetch import ReadOnlyFake, snapshot, unchanged
from test_incomplete_fetch import LOG, interrupted  # noqa: F401

XYZ = '3\n-5.0\nO 0 0 0\nH 0 0 1\nH 0 1 0\n'


def run_fetch(cfg, path, fake, monkeypatch, capsys, *flags):
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(transport, 'SSHTransport', lambda *a, **kw: fake)
    code = cli.main(['fetch', path.name, '--json', *flags])
    output = capsys.readouterr()
    return code, json.loads(output.out), output.err


def facts_records(path):
    return [row for line in (path.parent.parent / 'journal.jsonl').read_text().splitlines()
            if (row := json.loads(line))['action'] == 'facts']


def assert_record(path, result):
    record = facts_records(path)[-1]
    assert record['attempt_id'] == path.name
    assert record['result'] == 'auto'
    assert record['detail'] == result['facts']


@pytest.fixture
def ready(prepared):
    path, _ = prepared
    finish(path)
    return path, ReadOnlyFake({'water.log': (LOG + ' Normal termination of Gaussian\n').encode(),
                               'job.pbs.out': b''})


@pytest.mark.parametrize('program', ['gaussian', 'crest', 'xtb'])
def test_fetch_writes_real_facts_for_three_templates(cfg, ready, tmp_path, monkeypatch, capsys, program):
    path, fake = ready
    if program != 'gaussian':
        source = tmp_path / 'water.xyz'
        source.write_text(XYZ)
        manifest = attempt.prepare(cfg, study_name='smoke', template=program, input_path=source,
                                   tier='simple', walltime='00:10:00', label=program,
                                   method_basis='兜底方法：合成测试')
        path = attempt.find(cfg, manifest['attempt_id'])
        finish(path)
        files = ({'crest.out': 'CREST terminated normally.\n', 'crest_conformers.xyz': XYZ,
                  'crest.energies': '1 0.000\n', 'crest_best.xyz': XYZ}
                 if program == 'crest' else
                 {'xtb.out': '| TOTAL ENERGY -5.000 Eh |\nGEOMETRY OPTIMIZATION CONVERGED\n',
                  'xtbopt.xyz': XYZ, 'xtbopt.log': XYZ,
                  'job.pbs.out': 'normal termination of xtb\n'})
        fake = ReadOnlyFake({name: data.encode() for name, data in files.items()})
    original_build = facts.build_facts
    saved = {}

    def build(directory, *, refresh):
        assert refresh is False
        assert state.read(directory)['state'] == 'fetched'
        saved.update(status=(path / 'status.json').read_bytes(), calls=list(fake.calls))
        return original_build(directory, refresh=refresh)

    monkeypatch.setattr(facts, 'build_facts', build)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and err == ''
    assert result['facts'] == {'status': 'written'}
    parsed = json.loads((path / 'facts.json').read_text())
    assert parsed['program'] == program and parsed['termination'] == 'normal'
    assert (path / 'final.xyz').is_file()
    assert (path / 'status.json').read_bytes() == saved['status']
    assert fake.calls == saved['calls']
    assert result['files'] == remote.output_names(attempt.read_manifest(path))
    assert_record(path, result)


@pytest.mark.parametrize('conflict', [False, True])
def test_existing_facts_preserve_bytes_mtime_and_provenance(cfg, ready, monkeypatch, capsys, conflict):
    path, fake = ready
    # Build the expected evidence in memory using synthetic local logs; fetch
    # subsequently downloads those same bytes through the normal verification.
    for name, content in fake.files.items():
        (path / 'outputs' / name).write_bytes(content)
    previous, _ = facts.parse_facts(path)
    previous['ag_provenance'] = {'git_commit': 'old-version', 'dirty': False}
    if conflict:
        previous['energies']['scf'] = -99.0
    target = path / 'facts.json'
    target.write_text(json.dumps(previous, ensure_ascii=False))
    before = snapshot(path)
    for name in fake.files:
        (path / 'outputs' / name).unlink()
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and result['state'] == 'fetched'
    unchanged({target: before[target]})
    assert not list(path.glob('facts.*.json'))
    if conflict:
        assert result['facts']['status'] == 'conflict'
        assert result['facts']['reason'].startswith('差异分类')
        assert '\n' not in result['facts']['reason'] and len(result['facts']['reason']) <= 300
        assert 'ag facts --refresh' in err and len(err.splitlines()) == 1
    else:
        assert result['facts'] == {'status': 'unchanged'}
        assert err == ''
    assert_record(path, result)


@pytest.mark.parametrize('error', [ValueError, OSError, RuntimeError])
def test_parse_failure_preserves_success_status_outputs_and_exit(cfg, ready, monkeypatch, capsys, error):
    path, fake = ready
    saved = {}

    def fail(directory, *, refresh):
        assert refresh is False
        saved.update(snapshot(path))
        raise error(f"Cannot parse '{path / 'outputs/water.log'}': " + 'bad' * 150 + '\nsecond line')

    monkeypatch.setattr(facts, 'build_facts', fail)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and result['state'] == 'fetched'
    assert result['facts']['status'] == 'failed'
    reason = result['facts']['reason']
    assert reason.startswith(error.__name__ + ':')
    assert f'attempts/{path.name}/outputs/water.log' in reason
    assert str(path.parent.parent) not in reason
    assert len(reason) <= 300 and '\n' not in reason
    assert len(err.splitlines()) == 1 and '取回已成功' in err
    unchanged(saved)
    assert_record(path, result)


def test_missing_chemistry_dependency_is_skipped(cfg, ready, monkeypatch, capsys):
    path, fake = ready
    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == 'ag._parse_outputs':
            raise ImportError('synthetic unavailable chemistry dependency')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', missing)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and err == ''
    assert result['facts'] == {'status': 'skipped', 'reason': 'dependency-unavailable'}
    assert state.read(path)['state'] == 'fetched'
    assert not (path / 'facts.json').exists()
    assert_record(path, result)


def test_incomplete_fetch_parses_and_exports_input_without_changing_state(cfg, interrupted, monkeypatch, capsys):
    path, _, fake = interrupted
    before = (path / 'status.json').read_bytes()
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys, '--incomplete')
    assert code == 0 and err == '' and result['facts'] == {'status': 'written'}
    assert json.loads((path / 'facts.json').read_text())['termination'] == 'incomplete'
    assert (path / 'final_input.xyz').is_file()
    assert (path / 'status.json').read_bytes() == before
    assert_record(path, result)


@pytest.mark.parametrize('flags', [('--no-facts',), ('--add-missing',), ('--add-missing', '--no-facts')])
def test_explicit_skips_never_call_parser(cfg, ready, monkeypatch, capsys, flags):
    path, fake = ready
    if '--add-missing' in flags:
        state.write(path, 'fetched')
        (path / 'outputs/water.log').write_bytes(fake.files['water.log'])
    before_status = (path / 'status.json').read_bytes()
    old_journal = (path.parent.parent / 'journal.jsonl').read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail('Skipped automatic facts must not invoke parser')

    monkeypatch.setattr(facts, 'build_facts', forbidden)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys, *flags)
    reason = 'add-missing' if '--add-missing' in flags else 'no-facts'
    assert code == 0 and err == ''
    assert result['facts'] == {'status': 'skipped', 'reason': reason}
    assert not (path / 'facts.json').exists()
    if reason == 'add-missing':
        assert (path / 'status.json').read_bytes() == before_status
    assert (path.parent.parent / 'journal.jsonl').read_bytes().startswith(old_journal)
    assert_record(path, result)


@pytest.mark.parametrize('failure', ['state', 'hash'])
def test_refused_or_failed_fetch_does_not_call_auto_facts(cfg, ready, monkeypatch, capsys, failure):
    path, fake = ready
    if failure == 'state':
        state.write(path, 'fetched')
    else:
        fake.corrupt = True

    def forbidden(*args, **kwargs):
        pytest.fail('Failed fetch must not call auto_facts')

    monkeypatch.setattr(fetch, 'auto_facts', forbidden)
    code, result, _ = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 1 and 'error' in result and 'facts' not in result
    assert not facts_records(path)


def test_external_absolute_paths_and_empty_errors_are_safe(ready, tmp_path):
    path, _ = ready
    external = tmp_path / 'outside with spaces' / 'file.log'
    reason = fetch._facts_reason(OSError(f"Cannot read '{external}'\nprivate detail"), path)
    assert str(tmp_path) not in reason and 'file.log' not in reason and '\n' not in reason
    assert '[path omitted]' in reason
    assert fetch._facts_reason(ValueError(), path) == 'ValueError: '


def test_journal_failure_cannot_fail_completed_fetch(cfg, ready, monkeypatch, capsys):
    path, fake = ready
    original = journal.append

    def fail_facts(study, action, *args, **kwargs):
        if action == 'facts':
            raise OSError(str(study / 'journal.jsonl'))
        return original(study, action, *args, **kwargs)

    monkeypatch.setattr(journal, 'append', fail_facts)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and result['facts'] == {'status': 'written'}
    assert state.read(path)['state'] == 'fetched'
    assert 'journal 记录写入失败' in err and str(path.parent.parent) not in err


@pytest.mark.parametrize('existing', ['invalid-json', 'symlink', 'geometry'])
def test_existing_invalid_evidence_is_never_overwritten(cfg, ready, tmp_path, monkeypatch, capsys, existing):
    path, fake = ready
    target = path / ('final.xyz' if existing == 'geometry' else 'facts.json')
    if existing == 'symlink':
        outside = tmp_path / 'reviewed-facts.json'
        outside.write_bytes(b'reviewed evidence')
        target.symlink_to(outside)
    else:
        target.write_bytes(b'reviewed evidence')
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    code, result, _ = run_fetch(cfg, path, fake, monkeypatch, capsys)
    assert code == 0 and result['state'] == 'fetched'
    assert result['facts']['status'] == ('conflict' if existing == 'invalid-json' else 'failed')
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    if existing == 'symlink':
        assert target.is_symlink()
    assert_record(path, result)


def test_incomplete_no_facts_skips_parser(cfg, interrupted, monkeypatch, capsys):
    path, _, fake = interrupted
    before = (path / 'status.json').read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail('--incomplete --no-facts must not parse')

    monkeypatch.setattr(facts, 'build_facts', forbidden)
    code, result, err = run_fetch(cfg, path, fake, monkeypatch, capsys, '--incomplete', '--no-facts')
    assert code == 0 and err == ''
    assert result['facts'] == {'status': 'skipped', 'reason': 'no-facts'}
    assert (path / 'status.json').read_bytes() == before
    assert not (path / 'facts.json').exists()
    assert_record(path, result)
