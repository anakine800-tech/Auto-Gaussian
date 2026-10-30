"""T99 version preservation, read-only preview and failure handling; synthetic logs."""
from hashlib import sha256
import json

import pytest

from ag import cli, facts
from test_route_wrap import opt_freq


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    directory = tmp_path / 'study' / 'attempts' / 'water'
    (directory / 'outputs').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps({
        'template': 'gaussian', 'inputs': [{'name': 'input.gjf'}]}))
    (directory / 'status.json').write_text('{"state": "fetched"}')
    (directory / 'outputs' / 'input.log').write_text(opt_freq())
    monkeypatch.setattr(facts, 'ag_provenance', lambda: {'git_commit': 'a' * 40, 'dirty': False})
    current, _ = facts.parse_facts(directory)
    # Same physical log and line numbers, with the old route-joining defect.
    current['ag_provenance'] = facts.ag_provenance()
    current.pop('parser')
    current['termination'] = 'incomplete'
    current['parser_warning'] = 'Unexpected or unrecognized job section 2'
    current['route'] = current['route'].replace('Freq', 'Fre q')
    current['job_sections'][0]['route'] = current['route']
    current['job_sections'][1]['route'] = current['job_sections'][1]['route'].replace('Freq', 'Fr eq')
    (directory / 'facts.json').write_bytes((json.dumps(current) + '\r\n').encode())
    digest = sha256((directory / 'facts.json').read_bytes()).hexdigest()
    study = directory.parent.parent
    (study / 'study.md').write_text(f'Signed facts: {digest}\n')
    (directory / 'review.md').write_text(f'Review: {digest}\n')
    (study / 'analysis.json').write_text(json.dumps({'sha256': digest}))
    (study / 'index.csv').write_text(f'name,hash\nwater,{digest}\n')
    (study / 'partial.md').write_text(f'{digest[:12]} {digest}a 0{digest}\n')
    (study / 'ignored.txt').write_text(digest)
    # Neither configuration loading nor Transport construction is allowed.
    def forbidden(*args, **kwargs):
        raise AssertionError('reparse must stay local')
    monkeypatch.setattr(cli, 'load_config', forbidden)
    monkeypatch.setattr('ag.transport.SSHTransport', forbidden)
    return directory


def test_dry_run_exact_field_diff_and_no_study_writes(attempt, tmp_path, capsys):
    study = attempt.parent.parent
    before = snapshot(study)
    output = tmp_path / 'preview.json'
    assert cli.main(['facts', str(attempt), '--reparse', '--dry-run', '--out', str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert snapshot(study) == before
    assert not (attempt / '.facts.lock').exists()
    assert not (attempt / 'facts-history').exists()
    assert report['new_sha256'] == sha256(output.read_bytes()).hexdigest()
    assert report['old_sha256'] == sha256((attempt / 'facts.json').read_bytes()).hexdigest()
    assert {item['path'] for item in report['differences']} == {
        '/termination', '/parser_warning', '/parser', '/route',
        '/job_sections/0/route', '/job_sections/1/route'}
    assert json.loads(output.read_bytes())['termination'] == 'normal'
    assert report['references_to_old_sha256'] == [
        'analysis.json', 'attempts/water/review.md', 'index.csv', 'study.md']


@pytest.mark.usefixtures("synthetic_cwd")
def test_formal_reparse_preserves_old_bytes_and_lists_references(attempt, capsys):
    study = attempt.parent.parent
    before = snapshot(study)
    old = (attempt / 'facts.json').read_bytes()
    assert cli.main(['facts', 'water', '--study', str(study), '--reparse']) == 0
    report = json.loads(capsys.readouterr().out)
    archive = study / report['archive']
    assert archive.parent == attempt / 'facts-history'
    assert archive.name.endswith(f"-{sha256(old).hexdigest()[:12]}.json")
    assert archive.read_bytes() == old
    assert sha256(archive.read_bytes()).hexdigest() == report['old_sha256']
    assert sha256((attempt / 'facts.json').read_bytes()).hexdigest() == report['new_sha256']
    after = snapshot(study)
    for name, original in before.items():
        if name != 'attempts/water/facts.json':
            assert after[name] == original
    assert not list(attempt.glob('.facts-reparse-*'))
    assert report['references_to_old_sha256'] == [
        'analysis.json', 'attempts/water/review.md', 'index.csv', 'study.md']


def test_archive_collision_writes_nothing(attempt, monkeypatch):
    monkeypatch.setattr(facts, '_archive_stamp', lambda: '20261017T000000.000000Z')
    old = (attempt / 'facts.json').read_bytes()
    history = attempt / 'facts-history'
    history.mkdir()
    archive = history / f'20261017T000000.000000Z-{sha256(old).hexdigest()[:12]}.json'
    archive.write_bytes(old)  # Even an identical existing archive must refuse.
    before = snapshot(attempt.parent.parent)
    with pytest.raises(FileExistsError, match='already exists'):
        facts.reparse_facts(attempt)
    assert snapshot(attempt.parent.parent) == before


@pytest.mark.parametrize('failure', ['stage', 'copy', 'hash', 'publish'])
def test_midway_failure_keeps_original_and_no_partial_files(attempt, monkeypatch, failure):
    old = (attempt / 'facts.json').read_bytes()
    original_write = facts._write_synced
    count = 0
    def fail_write(handle, content):
        nonlocal count
        count += 1
        if (failure == 'stage' and count == 1) or (failure == 'copy' and count == 2):
            handle.write(b'partial')
            raise OSError('injected write failure')
        original_write(handle, b'bad hash' if failure == 'hash' and count == 2 else content)
    monkeypatch.setattr(facts, '_write_synced', fail_write)
    def fail_replace(*args):
        raise OSError('injected publish failure')
    if failure == 'publish':
        monkeypatch.setattr(facts.os, 'replace', fail_replace)
    with pytest.raises((OSError, ValueError), match='injected|hash mismatch'):
        facts.reparse_facts(attempt)
    assert (attempt / 'facts.json').read_bytes() == old
    assert not list(attempt.glob('.facts-reparse-*'))
    archives = list((attempt / 'facts-history').glob('*.json'))
    assert len(archives) == (1 if failure == 'publish' else 0)
    assert all(path.read_bytes() == old for path in archives)


@pytest.mark.parametrize('state', ['prepared', 'submitting', 'submitted', 'running',
                                  'finished', 'interrupted', 'unknown', 'cancelled'])
def test_unfetched_rejected_without_writes(attempt, state):
    (attempt / 'status.json').write_text(json.dumps({'state': state}))
    before = snapshot(attempt.parent.parent)
    with pytest.raises(ValueError, match='state fetched'):
        facts.reparse_facts(attempt)
    assert snapshot(attempt.parent.parent) == before


@pytest.mark.parametrize('bad', ['log_missing', 'facts_missing', 'invalid_json', 'invalid_object',
                                'nonfinite', 'history_file'])
def test_bad_evidence_rejected_before_any_write(attempt, bad):
    if bad == 'log_missing':
        (attempt / 'outputs/input.log').unlink()
    elif bad == 'facts_missing':
        (attempt / 'facts.json').unlink()
    elif bad == 'history_file':
        (attempt / 'facts-history').write_text('preserve')
    else:
        value = {'invalid_json': '{bad', 'invalid_object': '[]',
                 'nonfinite': '{"schema":"ag-facts/1","energy":NaN}'}[bad]
        (attempt / 'facts.json').write_text(value)
    before = snapshot(attempt.parent.parent)
    with pytest.raises((ValueError, OSError)):
        facts.reparse_facts(attempt)
    assert snapshot(attempt.parent.parent) == before


@pytest.mark.parametrize('name', ['facts.json', 'manifest.json', 'status.json', 'outputs/input.log',
                                 'outputs', 'facts-history', 'review.md'])
def test_symlinks_rejected_without_writes(attempt, tmp_path, name):
    path = attempt / name
    outside = tmp_path / 'outside'
    if path.exists():
        path.rename(outside)
    else:
        outside.mkdir()
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match='links|符号链接'):
        facts.reparse_facts(attempt)
    assert snapshot(tmp_path) == before


def test_attempt_symlink_and_escape_rejected_by_cli(attempt, tmp_path, capsys):
    link = tmp_path / 'alias'
    link.symlink_to(attempt, target_is_directory=True)
    before = snapshot(tmp_path)
    for path in (str(link), str(attempt / '..' / 'water')):
        assert cli.main(['facts', path, '--reparse']) == 1
        capsys.readouterr()
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('kind', ['inside', 'existing', 'suffix', 'symlink', 'parent_link', 'escape'])
def test_invalid_preview_destination_writes_nothing(attempt, tmp_path, kind):
    output = tmp_path / 'preview.json'
    if kind == 'inside':
        output = attempt.parent.parent / 'preview.json'
    elif kind == 'existing':
        output.write_bytes(b'preserve')
    elif kind == 'suffix':
        output = tmp_path / 'preview.txt'
    elif kind == 'symlink':
        output.symlink_to(tmp_path / 'missing.json')
    elif kind == 'parent_link':
        (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
        output = tmp_path / 'alias' / 'preview.json'
    elif kind == 'escape':
        output = tmp_path / 'study' / '..' / 'preview.json'
    before = snapshot(tmp_path)
    with pytest.raises((ValueError, OSError)):
        facts.reparse_facts(attempt, dry_run=True, out=output)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('flags', [['--dry-run'], ['--out', 'preview.json'],
                                  ['--reparse', '--dry-run'], ['--reparse', '--out', 'preview.json']])
def test_invalid_option_combinations_write_nothing(attempt, capsys, flags):
    before = snapshot(attempt.parent.parent)
    assert cli.main(['facts', str(attempt), *flags]) == 1
    assert capsys.readouterr().err
    assert snapshot(attempt.parent.parent) == before


def test_field_diff_preserves_types_and_escapes_pointers():
    assert facts._field_differences({'x/y': [False, 1], 'a~b': None}, {'x/y': [0, 1.0]}) == [
        {'path': '/a~0b', 'change': 'removed', 'old': None},
        {'path': '/x~1y/0', 'change': 'changed', 'old': False, 'new': 0},
        {'path': '/x~1y/1', 'change': 'changed', 'old': 1, 'new': 1.0}]
