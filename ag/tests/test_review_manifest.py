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
