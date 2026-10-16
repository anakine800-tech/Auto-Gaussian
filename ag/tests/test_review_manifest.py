from datetime import datetime, timezone
from hashlib import sha256
import errno
from pathlib import Path
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
    with pytest.raises(inventory.UnresolvedReferences) as error:
        inventory.create(root)
    assert error.value.references[0]['reason'] == 'missing'
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


def test_missing_transitive_thermo_reference(tmp_path):
    root = study(tmp_path)
    (root / 'study.md').write_text('`analyses/reaction.json`')
    (root / 'analyses/reaction.json').write_text('{"species":{"water":{"thermo":"missing.json"}}}')
    with pytest.raises(ValueError, match='Invalid evidence reference.*missing'):
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
    with pytest.raises(ValueError, match='Unresolved|Symbolic links'):
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


@pytest.mark.parametrize('suffix', ['说明', '，见上', '。', '；见上', '、见上', '!note', '.', ',', ';'])
def test_bare_path_stops_at_ascii_boundary(tmp_path, suffix):
    root = study(tmp_path)
    (root / 'study.md').write_text('Evidence: analyses/a.json' + suffix)
    (root / 'analyses/a.json').write_text('{}')
    result = inventory.create(root)
    assert 'analyses/a.json' in {entry['path'] for entry in result['files']}


@pytest.mark.parametrize('extension', ['json', 'md', 'csv', 'tsv', 'txt', 'xyz', 'pdf', 'png', 'svg', 'html'])
def test_bare_path_preserves_dotted_names(tmp_path, extension):
    path = tmp_path / 'study.md'
    name = f'analyses/a.json.backup.{extension}'
    assert inventory._references(path, (name + '说明').encode()) == [(name, True, 'line 1', '')]


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
                                  'outside_study', 'empty', 'only_empty_subdirectory'])
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
    elif kind == 'outside_study':
        reference = '[batch](../outside/)'
        error = 'Unresolved'
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
    (root / 'study.md').write_text('The batch is ready. '
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


@pytest.mark.parametrize('reference', [
    '../attempts/water-a/', '../attempts/water-a', '../analyses/../attempts/water-a/',
])
def test_review_directory_link_outside_analyses_is_information_only(tmp_path, reference):
    root = study(tmp_path)
    review = root / 'reviews/review.md'
    review.parent.mkdir()
    review.write_text(f'[attempt]({reference})')
    (root / 'attempts/water-a/input.txt').write_text('Synthetic input, not analysis evidence')
    result = inventory.create(root)
    paths = {entry['path'] for entry in result['files']}
    assert paths == {'study.md', 'reviews/review.md',
                     'attempts/water-a/facts.json', 'attempts/water-a/review.md',
                     'attempts/water-b/facts.json', 'attempts/water-b/review.md'}
    assert all('expanded_from' not in entry for entry in result['files'])


@pytest.mark.parametrize(('text', 'path'), [
    ('analyses/a.json说明', 'analyses/a.json'),
    ('见analyses/a.json', 'analyses/a.json'),
    ('analyses/run.gjf，见上', 'analyses/run.gjf'),
    ('analyses/x.jsonl。', 'analyses/x.jsonl'),
    ('analyses/script.py', 'analyses/script.py'),
    ('analyses/output', 'analyses/output'),
    ('analyses/a.jsonextra', 'analyses/a.jsonextra'),
])
def test_bare_references_use_ascii_boundaries_without_extension_filter(tmp_path, text, path):
    root = study(tmp_path)
    assert inventory._references(root / 'study.md', text.encode()) == [(path, True, 'line 1', '')]
    (root / 'study.md').write_text(text)
    (root / path).write_bytes(b'{}')
    result = inventory.create(root)
    assert path in {entry['path'] for entry in result['files']}


@pytest.mark.parametrize('prefix', ['a', '9', '_', '/', '.'])
def test_bare_references_require_forward_boundary(tmp_path, prefix):
    assert inventory._references(tmp_path / 'study.md', (prefix + 'analyses/a.json').encode()) == []


@pytest.mark.parametrize('path', ['analyses/missing', 'analyses/missing.log', 'analyses/missing.sdf'])
def test_arbitrary_explicit_missing_paths_require_acceptance(tmp_path, path):
    root = study(tmp_path)
    (root / 'study.md').write_text(path)
    with pytest.raises(inventory.UnresolvedReferences) as error:
        inventory.create(root)
    assert error.value.references[0]['reason'] == 'missing'


@pytest.mark.parametrize('description', ['Long description ' * 40, 'first line\nsecond line', '汉' * 86])
def test_long_or_multiline_nonexplicit_json_description_is_ignored(tmp_path, description):
    root = study(tmp_path)
    (root / 'study.md').write_text('[review](analyses/review.json)')
    (root / 'analyses/review.json').write_text(json.dumps({'description': description}))
    result = inventory.create(root)
    assert len(result['files']) == 6


@pytest.mark.parametrize('value', ['analyses/' + 'x' * 256 + '.json', 'analyses/' + '汉' * 86 + '.json',
                                  'analyses/first\nsecond.json', 'analyses/first%0Asecond.json'])
def test_invalid_explicit_json_reference_names_source_and_field(tmp_path, value):
    root = study(tmp_path)
    (root / 'study.md').write_text('[review](analyses/review.json)')
    (root / 'analyses/review.json').write_text(json.dumps({'evidence': [{'path': value}]}))
    with pytest.raises(ValueError) as error:
        inventory.create(root)
    message = str(error.value)
    assert 'analyses/review.json' in message
    assert '$["evidence"][0]["path"]' in message
    assert '255 bytes' in message or 'newline' in message
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('value', ['x' * 256, '汉' * 86, 'a\nb', 'a\rb'])
def test_invalid_path_is_checked_before_filesystem_access(tmp_path, monkeypatch, explicit, value):
    monkeypatch.setattr(Path, 'is_symlink', lambda *_: pytest.fail('invalid string reached filesystem'))
    if explicit:
        with pytest.raises(ValueError, match='study.md.*field input'):
            inventory._analysis_reference(tmp_path, tmp_path / 'study.md', value, True, 'input')
    else:
        assert inventory._analysis_reference(tmp_path, tmp_path / 'study.md', value, False) is None


@pytest.mark.parametrize('explicit', [False, True])
def test_filesystem_enametoolong_is_handled_with_reference_context(tmp_path, monkeypatch, explicit):
    def too_long(*args):
        raise OSError(errno.ENAMETOOLONG, 'raw OS message')
    monkeypatch.setattr(Path, 'is_symlink', too_long)
    if explicit:
        with pytest.raises(ValueError, match='study.md.*field input.*ENAMETOOLONG') as error:
            inventory._analysis_reference(tmp_path, tmp_path / 'study.md', 'analyses/a.json', True, 'input')
        assert 'raw OS message' not in str(error.value)
    else:
        assert inventory._analysis_reference(tmp_path, tmp_path / 'study.md', 'description', False) is None


def test_unrelated_filesystem_error_is_not_ignored(tmp_path, monkeypatch):
    def denied(*args):
        raise PermissionError(errno.EACCES, 'denied')
    monkeypatch.setattr(Path, 'is_symlink', denied)
    with pytest.raises(PermissionError):
        inventory._analysis_reference(tmp_path, tmp_path / 'study.md', 'description', False)


@pytest.mark.parametrize('key', ['file', 'source', 'path', 'definition'])
@pytest.mark.parametrize('exists', [False, True])
def test_json_attempt_basename_only_counts_when_present_beside_source(tmp_path, key, exists):
    root = study(tmp_path)
    (root / 'study.md').write_text('[topology](analyses/topology.json)')
    (root / 'analyses/topology.json').write_text(json.dumps({
        'schema': 'ag-topology/1', 'sources': {'final': {key: 'final.xyz'}}}))
    (root / 'attempts/water-a/final.xyz').write_text('1\nsynthetic\nH 0 0 0\n')
    if exists:
        (root / 'analyses/final.xyz').write_text('1\nsynthetic\nH 0 0 0\n')
    entries = {e['path']: e for e in inventory.create(root)['files']}
    assert ('analyses/final.xyz' in entries) is exists
    assert 'attempts/water-a/final.xyz' not in entries
    assert len(entries) == 6 + exists


@pytest.mark.parametrize('key', ['thermo', 'frozen_evidence'])
def test_explicit_json_basename_still_requires_evidence(tmp_path, key):
    root = study(tmp_path)
    (root / 'study.md').write_text('[report](analyses/report.json)')
    (root / 'analyses/report.json').write_text(json.dumps({key: 'missing.json'}))
    with pytest.raises(ValueError, match='Invalid evidence reference.*missing'):
        inventory.create(root)


@pytest.mark.parametrize('key', ['file', 'source', 'path', 'definition'])
def test_json_path_with_slash_falls_back_without_including_attempt_files(tmp_path, key):
    root = study(tmp_path)
    (root / 'study.md').write_text('[report](analyses/report.json)')
    (root / 'analyses/report.json').write_text(json.dumps({key: 'batch/item.xyz'}))
    (root / 'batch').mkdir()
    (root / 'batch/item.xyz').write_text('synthetic')
    result = inventory.create(root)
    assert result['referenced_outside_analyses'] == [dict(
        source='analyses/report.json', location=f'$["{key}"]', path='batch/item.xyz',
        resolved_from='study_root')]
    assert 'unresolved_references' not in result
    assert 'batch/item.xyz' not in {e['path'] for e in result['files']}


@pytest.mark.parametrize('suffix', ['md', 'txt'])
@pytest.mark.parametrize('reference', ['[item]({path})', '`{path}`'])
@pytest.mark.parametrize('target', ['structures/x.xyz', 'analyses/y.json'])
def test_snapshot_reference_falls_back_to_study_root(tmp_path, suffix, reference, target):
    root = study(tmp_path)
    (root / 'structures').mkdir()
    (root / target).write_text('{}')
    (root / 'study.md').write_text(f'[snapshot](analyses/snapshot.{suffix})')
    (root / f'analyses/snapshot.{suffix}').write_text(reference.format(path=target))
    entries = {e['path']: e for e in inventory.create(root)['files']}
    if target.startswith('analyses/'):
        assert 'resolved_from' not in entries[target]
    else:
        assert target not in entries
    assert 'resolved_from' not in entries[f'analyses/snapshot.{suffix}']


@pytest.mark.parametrize('target', ['y.json', 'structures/x.xyz'])
def test_snapshot_ambiguous_reference_is_rejected_even_outside_analyses(tmp_path, target):
    root = study(tmp_path)
    (root / 'study.md').write_text('[snapshot](analyses/snapshot.md)')
    (root / 'analyses/snapshot.md').write_text(f'[item]({target})')
    for parent in (root, root / 'analyses'):
        path = parent / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')  # Equal bytes do not make distinct files identical.
    with pytest.raises(ValueError, match='Ambiguous evidence reference.*snapshot.md.*line 1'):
        inventory.create(root)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


def test_snapshot_hardlinks_to_same_file_are_not_ambiguous(tmp_path):
    root = study(tmp_path)
    (root / 'study.md').write_text('[snapshot](analyses/snapshot.md)')
    (root / 'analyses/snapshot.md').write_text('[item](analyses/y.json)')
    (root / 'analyses/analyses').mkdir()
    (root / 'analyses/y.json').write_text('{}')
    (root / 'analyses/analyses/y.json').hardlink_to(root / 'analyses/y.json')
    entries = {e['path']: e for e in inventory.create(root)['files']}
    assert 'resolved_from' not in entries['analyses/y.json']
    assert 'analyses/analyses/y.json' not in entries


@pytest.mark.parametrize('value', ['./analyses/y.json', '../analyses/y.json'])
def test_dot_relative_text_never_uses_study_root_fallback(tmp_path, value):
    root = study(tmp_path)
    (root / 'analyses/nested').mkdir()
    (root / 'study.md').write_text('[snapshot](analyses/nested/snapshot.md)')
    (root / 'analyses/nested/snapshot.md').write_text(f'[item]({value})')
    (root / 'analyses/y.json').write_text('{}')
    with pytest.raises(inventory.UnresolvedReferences) as error:
        inventory.create(root)
    assert error.value.references[0]['reason'] == 'missing'


def test_fallback_directory_marks_members_and_preserves_direct_reference_origin(tmp_path):
    root = study(tmp_path)
    (root / 'analyses/batch').mkdir()
    (root / 'analyses/batch/item.json').write_text('{}')
    (root / 'study.md').write_text('[direct](analyses/batch/item.json) [snapshot](analyses/z.md)')
    (root / 'analyses/z.md').write_text('[batch](analyses/batch/)')
    entries = {e['path']: e for e in inventory.create(root)['files']}
    assert 'resolved_from' not in entries['analyses/batch/item.json']
    assert entries['analyses/batch/item.json']['expanded_from'] == ['analyses/batch']


@pytest.mark.parametrize('key', ['file', 'source', 'path', 'definition'])
def test_bare_json_filename_retains_long_path_error(tmp_path, key):
    root = study(tmp_path)
    (root / 'study.md').write_text('[report](analyses/report.json)')
    (root / 'analyses/report.json').write_text(json.dumps({key: 'x' * 256 + '.xyz'}))
    with pytest.raises(ValueError, match='255 bytes'):
        inventory.create(root)


@pytest.mark.parametrize('reference', ['[item](analyses/y.json)', '`analyses/y.json`', 'analyses/y.json'])
def test_analysis_prefix_ignores_source_directory_shadow(tmp_path, reference):
    root = study(tmp_path)
    (root / 'study.md').write_text('[snapshot](analyses/snapshot.md)')
    (root / 'analyses/snapshot.md').write_text(reference)
    (root / 'analyses/y.json').write_text('{}')
    (root / 'analyses/analyses').mkdir()
    (root / 'analyses/analyses/y.json').write_text('{"unrelated": true}')
    entries = {e['path']: e for e in inventory.create(root)['files']}
    assert entries['analyses/y.json']['sha256'] == sha256(b'{}').hexdigest()
    assert 'resolved_from' not in entries['analyses/y.json']
    assert 'analyses/analyses/y.json' not in entries


def test_other_text_reference_still_records_real_root_fallback(tmp_path):
    root = study(tmp_path)
    (root / 'study.md').write_text('[snapshot](analyses/nested/snapshot.md)')
    (root / 'analyses/nested').mkdir()
    (root / 'analyses/y.json').write_text('{}')
    (root / 'bundle').mkdir()
    (root / 'analyses/nested/snapshot.md').write_text('[item](bundle/../analyses/y.json)')
    entries = {e['path']: e for e in inventory.create(root)['files']}
    assert entries['analyses/y.json']['resolved_from'] == 'study_root'


@pytest.mark.parametrize('homonyms', [False, True])
@pytest.mark.parametrize('positional', [False, True])
def test_cli_diagnostic_references_require_only_relevant_confirmation(tmp_path, capsys, homonyms, positional):
    root = study(tmp_path)
    (root / 'analyses/reports').mkdir()
    (root / 'study.md').write_text('[report](analyses/reports/notes.md)')
    (root / 'analyses/reports/notes.md').write_text(
        '`manifest.json`\n`final_input.xyz`\n[card](reaction-plan.md#step)\n'
        '[other](../../../other-study/analyses/review.md)\n')
    if homonyms:
        (root / 'analyses/elsewhere').mkdir()
        for name in ('manifest.json', 'final_input.xyz', 'reaction-plan.md'):
            (root / 'analyses/elsewhere' / name).write_text('{}')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
    command = ['review', 'manifest', *([] if positional else ['--study']), str(root), '--json']
    assert cli.main(command) == 4
    output = capsys.readouterr()
    result = json.loads(output.out)
    refs = result['unresolved_references']
    assert len(refs) == (4 if homonyms else 1)
    assert [e['reason'] for e in refs].count('missing') == (3 if homonyms else 0)
    assert [e['reason'] for e in refs].count('escapes_study') == 1
    assert all(e['source'] == 'analyses/reports/notes.md' for e in refs)
    assert all(e['location'] in {'line 1', 'line 2', 'line 3', 'line 4'} for e in refs)
    assert '--accept-unresolved' in result['error']
    assert not list((root / 'analyses').glob('review-manifest-*.json'))
    assert ('unqualified_name: 3' in output.err) is not homonyms
    assert cli.main([*command, '--accept-unresolved']) == 0
    accepted = json.loads(capsys.readouterr().out)
    saved = json.loads((root / accepted['manifest']).read_text())
    assert saved['schema'] == 'ag-review-manifest/1'
    assert saved['unresolved_references'] == refs
    assert saved['unresolved_accepted'] is True
    assert datetime.fromisoformat(saved['unresolved_accepted_at']).tzinfo is not None
    assert saved['unresolved_accepted_at'] == saved['created_at']
    assert len(saved.get('unqualified_names', [])) == (0 if homonyms else 3)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    assert not any('elsewhere' in e['path'] for e in saved['files'])


def test_information_only_references_do_not_require_acceptance(tmp_path, capsys):
    root = study(tmp_path)
    (root / 'study.md').write_text('[file](attempts/water-a/final.xyz)\n`unqualified.xyz`')
    (root / 'attempts/water-a/final.xyz').write_text('synthetic')
    assert cli.main(['review', 'manifest', str(root)]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    saved = json.loads((root / result['manifest']).read_text())
    assert saved['referenced_outside_analyses'] == [dict(
        source='study.md', location='line 1', path='attempts/water-a/final.xyz')]
    assert saved['unqualified_names'] == [dict(source='study.md', location='line 2', value='unqualified.xyz')]
    assert 'unresolved_accepted' not in saved and 'unresolved_references' not in saved
    assert 'referenced_outside_analyses' not in result and 'unqualified_names' not in result
    assert result['outside_analyses_count'] == result['unqualified_name_count'] == 1
    assert output.err.count('无需确认') == 2
    assert 'unqualified.xyz' not in output.out + output.err
    assert not any(e['path'].endswith('final.xyz') for e in saved['files'])


@pytest.mark.parametrize('kind', ['md', 'txt', 'json'])
@pytest.mark.parametrize('homonym', [False, True])
def test_unqualified_name_never_selects_a_recursive_homonym(tmp_path, kind, homonym):
    root = study(tmp_path)
    (root / 'study.md').write_text(f'[report](analyses/report.{kind})')
    value = 'result[0].xyz'
    text = json.dumps({'path': value}) if kind == 'json' else f'`{value}`'
    (root / f'analyses/report.{kind}').write_text(text)
    (root / 'analyses/nested').mkdir()
    (root / 'analyses/nested' / (value if homonym else 'result0.xyz')).write_text('synthetic')
    if homonym:
        with pytest.raises(inventory.UnresolvedReferences) as error:
            inventory.create(root)
        assert error.value.references[0]['value'] == value
        assert error.value.references[0]['reason'] == 'missing'
    else:
        result = inventory.create(root)
        assert result['unqualified_names'][0]['value'] == value
        assert 'unresolved_references' not in result
        assert all('nested' not in e['path'] for e in result['files'])


@pytest.mark.parametrize(('target', 'kind'), [
    ('analyses/batch/item.json', 'root_only'), ('analyses/batch', 'root_only'),
    ('analyses/batch/item.json', 'ambiguous'), ('analyses/batch', 'ambiguous'),
    ('analyses/batch/item.json', 'same_file'),
])
def test_json_source_and_root_resolution(tmp_path, target, kind):
    root = study(tmp_path)
    (root / 'study.md').write_text('[report](analyses/report.json)')
    (root / 'analyses/report.json').write_text(json.dumps({'path': target}))
    file = root / 'analyses/batch/item.json'
    file.parent.mkdir()
    file.write_text('{}')
    if kind != 'root_only':
        other = root / 'analyses/analyses/batch/item.json'
        other.parent.mkdir(parents=True)
        if kind == 'same_file':
            other.hardlink_to(file)
        else:
            other.write_bytes(file.read_bytes())
    if kind == 'ambiguous':
        with pytest.raises(ValueError, match='Ambiguous.*report.json'):
            inventory.create(root, accept_unresolved=True)
    else:
        result = inventory.create(root)
        path = 'analyses/batch/item.json' if kind == 'root_only' else 'analyses/analyses/batch/item.json'
        entry = next(e for e in result['files'] if e['path'] == path)
        assert entry.get('resolved_from') == ('study_root' if kind == 'root_only' else None)
        if target.endswith('batch'):
            assert entry['expanded_from'] == ['analyses/batch']


@pytest.mark.parametrize('key', ['thermo', 'frozen_evidence'])
@pytest.mark.parametrize('value', ['missing.json', 'batch/item.json', '../../outside.json'])
@pytest.mark.parametrize('accept', [False, True])
def test_strict_pointers_cannot_be_accepted_or_gain_fallback(tmp_path, key, value, accept):
    root = study(tmp_path)
    (root / 'batch').mkdir()
    (root / 'batch/item.json').write_text('{}')
    (root / 'study.md').write_text('[report](analyses/report.json)')
    (root / 'analyses/report.json').write_text(json.dumps({key: value}))
    with pytest.raises(ValueError, match='Invalid evidence reference') as error:
        inventory.create(root, accept_unresolved=accept)
    assert not isinstance(error.value, inventory.UnresolvedReferences)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


@pytest.mark.parametrize('absolute', [False, True])
def test_escaped_references_do_not_probe_outside_symlinks(tmp_path, monkeypatch, absolute):
    root = study(tmp_path)
    value = str(root.parent / 'external-link/report.json') if absolute else '../external-link/report.json'
    monkeypatch.setattr(Path, 'is_symlink', lambda *_: pytest.fail('escaped reference probed filesystem'))
    monkeypatch.setattr(Path, 'exists', lambda *_: pytest.fail('escaped reference probed filesystem'))
    assert inventory._analysis_reference(root, root / 'study.md', value, True) == (None, 'escapes_study')


def test_absolute_unresolved_path_is_redacted_in_cli_and_saved_manifest(tmp_path, capsys):
    root = study(tmp_path)
    value = str(root.parent / 'external-link' / 'private-name.json')
    (root / 'study.md').write_text(f'[report](<{value}>)')
    for accept in (False, True):
        command = ['review', 'manifest', str(root)] + (['--accept-unresolved'] if accept else [])
        assert cli.main(command) == (0 if accept else 4)
        output = capsys.readouterr()
        assert value not in output.out + output.err
        result = json.loads(output.out)
        assert result['unresolved_references'][0]['value'] == '<absolute path>'
        if accept:
            assert value not in (root / result['manifest']).read_text()


@pytest.mark.parametrize('accept', [False, True])
@pytest.mark.parametrize('reference', ['analyses/link/../absent.json', 'analyses/link/../../outside.json'])
def test_internal_symlink_remains_hard_even_when_normalization_hides_it(tmp_path, accept, reference):
    root = study(tmp_path)
    (root / 'analyses/link').symlink_to(root.parent, target_is_directory=True)
    (root / 'study.md').write_text(f'[{reference}]({reference})')
    with pytest.raises(ValueError, match='Symbolic links'):
        inventory.create(root, accept_unresolved=accept)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


@pytest.mark.parametrize('accept', [False, True])
def test_changed_evidence_is_hard_error_before_unresolved_confirmation(tmp_path, monkeypatch, accept):
    root = study(tmp_path)
    (root / 'study.md').write_text('analyses/missing.json')
    original = Path.read_bytes
    reads = 0
    def changed(path):
        nonlocal reads
        data = original(path)
        if path == root / 'study.md':
            reads += 1
            if reads == 2:
                return data + b'changed'
        return data
    monkeypatch.setattr(Path, 'read_bytes', changed)
    with pytest.raises(ValueError, match='Evidence changed while collecting'):
        inventory.create(root, accept_unresolved=accept)
    assert not list((root / 'analyses').glob('review-manifest-*.json'))


def test_no_reference_changes_preserve_legacy_manifest_bytes(tmp_path, monkeypatch):
    (tmp_path / 'analyses').mkdir()
    (tmp_path / 'study.md').write_text('Structure confirmation pending\n')
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(inventory, 'datetime', Clock)
    monkeypatch.setattr(inventory, 'ag_provenance', lambda: {'git_commit': 'c' * 40, 'dirty': False})
    result = inventory.create(tmp_path)
    # Captured from main after T49b with the same clock, provenance and input.
    assert result['sha256'] == 'd7fb1a628ef83d555b20a93750580463e53bd2701ad4ff44f7d11829b1070857'
