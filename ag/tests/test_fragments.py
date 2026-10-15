"""Synthetic small molecules only; no research data or cluster access."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from ag import fragments, geometry as geo
from ag.cli import main


# Interleave the separated atom to expose accidental renumbering/reordering.
ROWS = ['O  0.000000 0 0', 'F 10.000  0.0 0', 'H\t0.96 0 0', 'H -2.4D-1  .93 0.000']
XYZ = '4\nsynthetic water and fluorine; no assigned charge\n' + '\n'.join(ROWS) + '\n'


@pytest.fixture
def study(tmp_path, monkeypatch):
    root = tmp_path / 'study'
    root.mkdir()
    (root / 'analyses').mkdir()
    (root / 'attempts').mkdir()
    (root / 'source.xyz').write_text(XYZ)
    monkeypatch.chdir(root)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path / 'no-config'))
    from ag import cli, transport
    def forbidden(*args, **kwargs):
        pytest.fail('Local fragments must not load config or connect to a cluster')
    monkeypatch.setattr(cli, 'load_config', forbidden)
    monkeypatch.setattr(transport.Transport, '__init__', forbidden)
    return root


def run(root, source=None, out='analyses/report.json', *, explicit_study=True):
    argv = ['fragments', str(source or root / 'source.xyz'), '--out', str(out), '--json']
    if explicit_study:
        argv += ['--study', str(root)]
    return main(argv)


def attempt(root, irc=False):
    path = root / 'attempts' / 'water-001'
    path.mkdir()
    (path / 'manifest.json').write_text('{}')
    facts = {'final_geometry': 'final.xyz', 'opt_converged': True}
    if irc:
        facts['irc'] = {'end_geometry': 'irc_end.xyz'}
    (path / 'facts.json').write_text(json.dumps(facts))
    (path / ('irc_end.xyz' if irc else 'final.xyz')).write_text(XYZ)
    if irc:
        (path / 'final.xyz').write_text('1\nunused geometry\nHe 0 0 0\n')
    return path


def snapshot(path):
    return {p.relative_to(path): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('crlf', [False, True])
def test_two_fragments_preserve_raw_coordinate_rows(study, capsys, crlf):
    source = study / 'source.xyz'
    if crlf:
        source.write_bytes(XYZ.replace('\n', '\r\n').encode())
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    assert run(study) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads((study / 'analyses/report.json').read_text())
    assert report['count'] == 2
    assert report['components'] == [dict(atoms=[1, 3, 4], formula='H2O', xyz_file='report.frag1.xyz'),
                                    dict(atoms=[2], formula='F', xyz_file='report.frag2.xyz')]
    assert report['source']['sha256'] == sha256(before[0]).hexdigest()
    assert report['uncertain_contacts'] == []
    for i, indices in enumerate(([1, 3, 4], [2]), 1):
        lines = (study / f'analyses/report.frag{i}.xyz').read_text().splitlines()
        assert int(lines[0]) == len(indices)
        assert 'source=' in lines[1] and f'fragment={i}' in lines[1]
        assert 'original_atoms=' + ','.join(map(str, indices)) in lines[1]
        assert lines[2:] == [ROWS[index - 1] for index in indices]
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    md = (study / 'analyses/report.md').read_text()
    assert fragments.NOTICE in md and '片段数：2' in md
    assert '1, 3, 4' in md and '不推断片段身份' in md
    assert all('charge' not in row and 'multiplicity' not in row for row in report['components'])


@pytest.mark.parametrize('irc', [False, True])
@pytest.mark.parametrize('by_id', [False, True])
def test_attempt_selection_preserves_all_evidence(study, capsys, irc, by_id):
    path = attempt(study, irc)
    before = snapshot(path)
    assert run(study, path.name if by_id else path, explicit_study=by_id) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['count'] == 2
    assert report['source']['file'].endswith('irc_end.xyz' if irc else 'final.xyz')
    assert report['source']['geometry_kind'] == ('irc_endpoint' if irc else 'optimized')
    assert snapshot(path) == before


def test_one_fragment_default_study(study, capsys):
    (study / 'source.xyz').write_text('3\nwater\n' + '\n'.join(ROWS[i] for i in (0, 2, 3)) + '\n')
    assert run(study, explicit_study=False) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['count'] == 1
    assert report['components'] == [dict(atoms=[1, 2, 3], formula='H2O', xyz_file=None)]
    assert sorted(p.name for p in (study / 'analyses').iterdir()) == ['report.json', 'report.md']


@pytest.mark.parametrize(('ratio', 'count', 'contacts', 'clashes'), [
    (0.5, 2, 0, 1), (0.6, 1, 0, 0), (1.19, 1, 0, 0),
    (1.2, 2, 1, 0), (1.35, 2, 1, 0), (1.5, 2, 1, 0), (1.51, 2, 0, 0)])
def test_radius_boundaries(study, capsys, ratio, count, contacts, clashes):
    from rdkit import Chem
    distance = 2 * Chem.GetPeriodicTable().GetRcovalent('H') * ratio
    (study / 'source.xyz').write_text(f'2\nsynthetic pair\nH 0 0 0\nH {distance!r} 0 0\n')
    assert run(study) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['count'] == count
    assert len(report['uncertain_contacts']) == contacts
    assert len(report['clashes']) == clashes
    if contacts:
        item = report['uncertain_contacts'][0]
        assert item['atoms'] == [1, 2] and item['fragments'] == [1, 2]
        assert item['covalent_radius_ratio'] == pytest.approx(ratio)
        assert '可能存在弱键或配位' in (study / 'analyses/report.md').read_text()


def test_intracomponent_contact_is_not_cross_fragment():
    frame = geo.Frame(('C', 'C', 'C'), ((0., 0., 0.), (1.52, 0., 0.), (1.52, 1.1, 0.)))
    report = fragments.analyze(frame)
    assert report['count'] == 1 and report['uncertain_contacts'] == []


@pytest.mark.parametrize('name', ['report.json', 'report.md', 'report.frag1.xyz', 'report.frag2.xyz'])
@pytest.mark.parametrize('kind', ['file', 'directory', 'symlink', 'dangling_symlink'])
def test_existing_output_rejects_entire_export(study, capsys, name, kind):
    path = study / 'analyses' / name
    if kind == 'file':
        path.write_bytes(b'keep existing bytes')
    elif kind == 'directory':
        path.mkdir()
    else:
        path.symlink_to(study / ('source.xyz' if kind == 'symlink' else 'missing.xyz'))
    before = snapshot(study) if kind != 'dangling_symlink' else None
    assert run(study) != 0
    capsys.readouterr()
    assert list((study / 'analyses').iterdir()) == [path]
    if before is not None:
        assert snapshot(study) == before
    if 'symlink' in kind:
        assert path.is_symlink()


@pytest.mark.parametrize('out', ['report.json', 'analyses/../escape.json', '../escape.json', 'analyses/report.xyz'])
def test_outside_or_invalid_output(study, capsys, out):
    before = snapshot(study.parent)
    assert run(study, out=out) != 0
    capsys.readouterr()
    assert snapshot(study.parent) == before


def test_absolute_outside_path(study):
    assert run(study, out=study.parent / 'escape.json') != 0
    assert not (study.parent / 'escape.json').exists()
    assert not list((study / 'analyses').iterdir())


@pytest.mark.parametrize('location', ['study', 'analyses', 'nested', 'source', 'source_parent',
                                      'attempt', 'facts', 'geometry'])
def test_symlink_paths_rejected(study, location):
    source, root, out = study / 'source.xyz', study, 'analyses/report.json'
    if location == 'study':
        root = study.parent / 'alias'
        root.symlink_to(study, target_is_directory=True)
    elif location in {'analyses', 'nested'}:
        external = study.parent / 'external'
        external.mkdir()
        if location == 'analyses':
            (study / 'analyses').rmdir()
            (study / 'analyses').symlink_to(external, target_is_directory=True)
        else:
            (study / 'analyses/alias').symlink_to(external, target_is_directory=True)
            out = 'analyses/alias/report.json'
    elif location in {'source', 'source_parent'}:
        alias = study / 'alias'
        alias.symlink_to(source if location == 'source' else study,
                         target_is_directory=location == 'source_parent')
        source = alias if location == 'source' else alias / 'source.xyz'
    else:
        path = attempt(study)
        if location == 'attempt':
            alias = study / 'attempts/alias'
            alias.symlink_to(path, target_is_directory=True)
            source = alias.name
        else:
            target = path / ('facts.json' if location == 'facts' else 'final.xyz')
            content = target.read_bytes()
            target.unlink()
            external = study / ('saved.json' if location == 'facts' else 'saved.xyz')
            external.write_bytes(content)
            target.symlink_to(external)
            source = path
    assert run(root, source, out=out) != 0
    assert not list(study.parent.rglob('report*'))


def test_late_collision_rolls_back_only_new_files(study, monkeypatch):
    original = os.open
    def collide(path, flags, *args, **kwargs):
        if path == 'report.md':
            (study / 'analyses/report.md').write_bytes(b'concurrent writer')
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(fragments.os, 'open', collide)
    assert run(study) != 0
    assert [p.name for p in (study / 'analyses').iterdir()] == ['report.md']
    assert (study / 'analyses/report.md').read_bytes() == b'concurrent writer'


def test_write_failure_leaves_no_partial_files(study, monkeypatch):
    original = os.fdopen
    class BrokenWriter:
        def write(self, content):
            raise OSError('synthetic disk failure')
    count = 0
    @contextmanager
    def fail(fd, *args, **kwargs):
        nonlocal count
        count += 1
        with original(fd, *args, **kwargs) as handle:
            yield BrokenWriter() if count == 2 else handle
    monkeypatch.setattr(fragments.os, 'fdopen', fail)
    assert run(study) != 0
    assert not list((study / 'analyses').iterdir())


def test_parent_swap_before_write_is_rejected(study, monkeypatch):
    original = fragments._write_outputs
    external = study.parent / 'external'
    external.mkdir()
    def swap(parent, payloads):
        parent.rmdir()
        parent.symlink_to(external, target_is_directory=True)
        original(parent, payloads)
    monkeypatch.setattr(fragments, '_write_outputs', swap)
    assert run(study) != 0
    assert not list(external.iterdir())


@pytest.mark.parametrize('text', ['', XYZ + XYZ, '2\ntruncated\nH 0 0 0\n',
                                 '1\nbad\nH nan 0 0\n', '1\nbad element\nXx 0 0 0\n'])
def test_bad_xyz_no_outputs(study, text):
    (study / 'source.xyz').write_text(text)
    assert run(study) != 0
    assert not list((study / 'analyses').iterdir())


def test_source_changed_during_read_no_outputs(study, monkeypatch):
    original = fragments.load_source
    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        (study / 'source.xyz').write_text('1\nchanged\nHe 0 0 0\n')
        return result
    monkeypatch.setattr(fragments, 'load_source', change)
    assert run(study) != 0
    assert not list((study / 'analyses').iterdir())


@pytest.mark.parametrize('name', ['../source.xyz', '/escape.xyz', '.', None])
def test_invalid_geometry_pointer(study, name):
    path = attempt(study)
    (path / 'facts.json').write_text(json.dumps({'final_geometry': name}))
    assert run(study, path) != 0
    assert not list((study / 'analyses').iterdir())
