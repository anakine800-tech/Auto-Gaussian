from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from ag import cli
from ag import _review_manifest as inventory


def study(tmp_path):
    (tmp_path / 'analyses').mkdir()
    (tmp_path / 'study.md').write_text('# Water study\n')
    for name in ('water-a', 'water-b'):
        directory = tmp_path / 'attempts' / name
        directory.mkdir(parents=True)
        (directory / 'facts.json').write_bytes(b'{"n_imag": 0}\r\n')
        (directory / 'review.md').write_text('Reviewed water\n')
    return tmp_path


def test_manifest_covers_all_facts_reviews_and_referenced_outputs(tmp_path, monkeypatch, capsys):
    root = study(tmp_path)
    (root / 'study.md').write_text('[profile](analyses/profile.json)\n`analyses/result.md`\n'
                                 '`analyses/quoted result.csv`\n')
    (root / 'analyses/quoted result.csv').write_text('energy\n0\n')
    (root / 'analyses/profile.json').write_text(json.dumps({'species': {'water': {'thermo': 'thermo.json'}}}))
    (root / 'analyses/thermo.json').write_text('{"schema":"ag-thermo/1","units":{"energy":"Hartree"}}')
    (root / 'analyses/result.md').write_text('[plot](<plot image.png>)\n[table][t]\n[t]: table.csv\n')
    (root / 'analyses/plot image.png').write_bytes(b'opaque binary\x00\xff')
    (root / 'analyses/table.csv').write_bytes(b'energy\r\n0\r\n')
    (root / 'analyses/unused.json').write_text('{}')
    (root / 'attempts/water-b/review.md').write_text('See ../../analyses/extra.txt\n')
    (root / 'analyses/extra.txt').write_text('Analysis evidence\n')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    monkeypatch.setattr(inventory, 'ag_provenance', lambda: {'git_commit': 'c' * 40, 'dirty': False})
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('manifest must not load configuration'))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('no SSH'))
    assert cli.main(['review', 'manifest', '--study', str(root), '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    destination = root / result['manifest']
    manifest = json.loads(destination.read_bytes())
    assert manifest['ag_provenance']['git_commit'] == 'c' * 40
    assert manifest['ag_provenance']['dirty'] is False
    assert result['sha256'] == sha256(destination.read_bytes()).hexdigest()
    included = {entry['path'] for entry in manifest['files']}
    expected = {p.relative_to(root).as_posix() for p in before if p.name != 'unused.json'}
    assert included == expected
    for entry in manifest['files']:
        data = (root / entry['path']).read_bytes()
        assert entry['size'] == len(data) and entry['sha256'] == sha256(data).hexdigest()
        assert not entry['path'].startswith('/')
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}


def test_manifest_collision_uses_exclusive_create(tmp_path, monkeypatch):
    root = study(tmp_path)
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(inventory, 'datetime', Clock)
    first = inventory.create(root)
    path = root / first['manifest']
    old = path.read_bytes()
    (root / 'attempts/water-a/facts.json').write_text('{"n_imag": 1}')
    with pytest.raises(FileExistsError):
        inventory.create(root)
    assert path.read_bytes() == old
    assert len(list((root / 'analyses').glob('review-manifest-*.json'))) == 1


@pytest.mark.parametrize('reference', [
    '[missing](analyses/missing.json)', '`analyses/missing.csv`',
    'Missing: analyses/missing.md', '[encoded](analyses/missing%20file.json)',
])
def test_missing_reference_is_not_omitted(tmp_path, reference):
    root = study(tmp_path)
    (root / 'study.md').write_text(reference)
    with pytest.raises(ValueError, match='Missing referenced'):
        inventory.create(root)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


def test_missing_transitive_thermo_reference(tmp_path):
    root = study(tmp_path)
    (root / 'study.md').write_text('`analyses/reaction.json`')
    (root / 'analyses/reaction.json').write_text('{"species":{"water":{"thermo":"missing.json"}}}')
    with pytest.raises(ValueError, match='Missing referenced'):
        inventory.create(root)


@pytest.mark.parametrize('kind', ['outside', 'linked_file', 'linked_directory'])
def test_manifest_rejects_escaping_or_linked_evidence(tmp_path, kind):
    root = tmp_path / 'study'
    root.mkdir()
    study(root)
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    if kind == 'outside':
        (root / 'study.md').write_text('`analyses/../../outside.json`')
    elif kind == 'linked_file':
        target = root / 'attempts/water-a/facts.json'
        target.unlink()
        target.symlink_to(outside)
    else:
        (root / 'attempts/linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='escapes|Symbolic links'):
        inventory.create(root)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))
    assert outside.read_text() == '{}'


def test_references_cycles_fragments_and_remote_links(tmp_path):
    root = study(tmp_path)
    (root / 'study.md').write_text('[a](analyses/a.md#result)\n[remote](https://example.invalid/analyses/remote.json)')
    (root / 'analyses/a.md').write_text('[b](b.md)\n')
    (root / 'analyses/b.md').write_text('[a](a.md)\n')
    result = inventory.create(root)
    paths = [entry['path'] for entry in result['files']]
    assert paths.count('analyses/a.md') == paths.count('analyses/b.md') == 1
    assert all('remote' not in p for p in paths)


def test_initial_structure_signoff_without_attempts(tmp_path):
    (tmp_path / 'study.md').write_text('Structure confirmation pending\n')
    (tmp_path / 'analyses').mkdir()
    result = inventory.create(tmp_path)
    assert [entry['path'] for entry in result['files']] == ['study.md']


@pytest.mark.parametrize('suffix', ['说明', '，见上', '。', '；见上', '、见上', '!note', 'extra'])
def test_bare_path_stops_at_extension(tmp_path, suffix):
    root = study(tmp_path)
    (root / 'study.md').write_text('Evidence: analyses/a.json' + suffix)
    (root / 'analyses/a.json').write_text('{}')
    result = inventory.create(root)
    assert 'analyses/a.json' in {entry['path'] for entry in result['files']}


@pytest.mark.parametrize('extension', ['json', 'md', 'csv', 'tsv', 'txt', 'xyz', 'pdf', 'png', 'svg', 'html'])
def test_bare_path_uses_last_known_extension(tmp_path, extension):
    path = tmp_path / 'study.md'
    name = f'analyses/a.json.backup.{extension}'
    assert inventory._references(path, (name + '说明').encode()) == [(name, True)]


@pytest.mark.parametrize('reference', ['`analyses/a.json说明`', '[a](analyses/a.json说明)'])
def test_quoted_paths_are_not_truncated(tmp_path, reference):
    root = study(tmp_path)
    (root / 'study.md').write_text(reference)
    (root / 'analyses/a.json说明').write_bytes(b'opaque evidence')
    result = inventory.create(root)
    assert 'analyses/a.json说明' in {entry['path'] for entry in result['files']}


@pytest.mark.parametrize('reference', [
    '`analyses/batch`', '[batch](analyses/batch/)', '[batch](analyses/batch)',
    'json', 'relative_json', 'relative_markdown',
])
def test_explicit_directory_expansion_is_sorted_and_hashed(tmp_path, reference):
    root = study(tmp_path)
    folder = root / 'analyses/batch'
    (folder / 'nested').mkdir(parents=True)
    (folder / 'z.csv').write_bytes(b'energy\r\n0\r\n')
    (folder / 'nested/a.png').write_bytes(b'opaque\x00\xff')
    (folder / 'b.md').write_text('[extra](../extra.txt)')
    (root / 'analyses/extra.txt').write_text('Evidence')
    if reference in {'json', 'relative_json'}:
        value = 'analyses/batch' if reference == 'json' else 'batch/'
        (root / 'analyses/signature.json').write_text(json.dumps({'frozen_evidence': value}))
        reference = '[signature](analyses/signature.json)'
    elif reference == 'relative_markdown':
        (root / 'analyses/selection.md').write_text('[batch](batch/)')
        reference = '[selection](analyses/selection.md)'
    (root / 'study.md').write_text(reference)
    first = inventory.create(root)
    second = inventory.create(root)
    assert first['schema'] == 'ag-review-manifest/1'
    assert first['files'] == second['files']
    assert [entry['path'] for entry in first['files']] == sorted(entry['path'] for entry in first['files'])
    entries = {entry['path']: entry for entry in first['files']}
    members = ['analyses/batch/b.md', 'analyses/batch/nested/a.png', 'analyses/batch/z.csv']
    assert {name for name in entries if name.startswith('analyses/batch/')} == set(members)
    for name in members:
        assert entries[name]['expanded_from'] == ['analyses/batch']
        assert entries[name]['sha256'] == sha256((root / name).read_bytes()).hexdigest()
        assert entries[name]['size'] == (root / name).stat().st_size
    assert 'analyses/extra.txt' in entries
    assert 'expanded_from' not in entries['analyses/extra.txt']


def test_overlapping_directory_references_preserve_all_origins(tmp_path):
    root = study(tmp_path)
    (root / 'analyses/batch/nested').mkdir(parents=True)
    (root / 'analyses/batch/nested/a.csv').write_text('energy\n0\n')
    (root / 'study.md').write_text('[all](analyses/batch) [subset](analyses/batch/nested) '
                                 '[file](analyses/batch/nested/a.csv)')
    result = inventory.create(root)
    entries = [entry for entry in result['files'] if entry['path'] == 'analyses/batch/nested/a.csv']
    assert len(entries) == 1
    assert entries[0]['expanded_from'] == ['analyses/batch', 'analyses/batch/nested']


@pytest.mark.parametrize('kind', ['directory_link', 'nested_directory_link', 'file_link', 'dangling_link',
                                  'outside_analyses', 'outside_study', 'empty', 'only_empty_subdirectory'])
def test_directory_expansion_rejects_unsafe_or_empty_targets(tmp_path, kind):
    root = tmp_path / 'study'
    root.mkdir()
    study(root)
    folder = root / 'analyses/batch'
    folder.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'a.txt').write_text('unchanged')
    reference = '[batch](analyses/batch/)'
    error = 'Symbolic links'
    if kind == 'directory_link':
        (root / 'analyses/linked').symlink_to(outside, target_is_directory=True)
        reference = '[batch](analyses/linked/)'
    elif kind == 'nested_directory_link':
        (folder / 'nested').mkdir()
        (folder / 'nested/linked').symlink_to(outside, target_is_directory=True)
    elif kind in {'file_link', 'dangling_link'}:
        (folder / 'linked.txt').symlink_to(outside / ('a.txt' if kind == 'file_link' else 'missing.txt'))
    elif kind == 'outside_analyses':
        reference = '[batch](analyses/../attempts/)'
        error = 'must be inside analyses'
    elif kind == 'outside_study':
        reference = '[batch](../outside/)'
        error = 'escapes'
    else:
        if kind == 'only_empty_subdirectory':
            (folder / 'empty').mkdir()
        error = 'Empty referenced'
    (root / 'study.md').write_text(reference)
    with pytest.raises(ValueError, match=error):
        inventory.create(root)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))
    assert (outside / 'a.txt').read_text() == 'unchanged'


def test_directory_expansion_rejects_non_regular_file(tmp_path):
    root = study(tmp_path)
    folder = root / 'analyses/batch'
    folder.mkdir()
    inventory.os.mkfifo(folder / 'pipe')
    (root / 'study.md').write_text('[batch](analyses/batch)')
    with pytest.raises(ValueError, match='regular file'):
        inventory.create(root)


def test_does_not_guess_directory_references_from_prose(tmp_path):
    root = study(tmp_path)
    (root / 'analyses/batch').mkdir()
    (root / 'analyses/batch/a.csv').write_text('energy\n0\n')
    (root / 'analyses/notes.json').write_text('{"description":"batch"}')
    (root / 'study.md').write_text('The batch is ready; analyses/batch is a label. '
                                 '[notes](analyses/notes.json)')
    result = inventory.create(root)
    assert all('batch' not in entry['path'] for entry in result['files'])


@pytest.mark.parametrize('reference', ['[old](analyses/batch/signed.json)', '[batch](analyses/batch)'])
def test_prior_signed_manifest_is_hashed_without_expansion(tmp_path, reference):
    root = study(tmp_path)
    (root / 'analyses/batch').mkdir()
    old = root / 'analyses/batch/signed.json'
    old.write_text(json.dumps({'schema': 'ag-review-manifest/1', 'files': [
        {'path': 'analyses/missing.json', 'sha256': 'a' * 64},
        {'path': 'analyses/../../outside.json', 'sha256': 'b' * 64},
    ]}))
    before = (old.read_bytes(), old.stat().st_mtime_ns)
    (root / 'study.md').write_text(reference)
    result = inventory.create(root)
    entries = {entry['path']: entry for entry in result['files']}
    assert entries['analyses/batch/signed.json']['sha256'] == sha256(before[0]).hexdigest()
    assert not any('missing' in name or 'outside' in name for name in entries)
    assert (old.read_bytes(), old.stat().st_mtime_ns) == before
