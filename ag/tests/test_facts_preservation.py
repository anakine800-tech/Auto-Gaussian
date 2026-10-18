"""Evidence remains byte-identical until an explicit, version-preserving refresh."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from ag import facts
from ag.cli import main
from ag.thermo import calculate_thermo
from test_facts import attempt
from test_thermo import sp_input


def snapshot(directory):
    return {str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in directory.rglob('*') if p.is_file()}


def test_parse_has_no_writes(tmp_path):
    directory = attempt(tmp_path)
    before = snapshot(directory)
    parsed, geometries = facts.parse_facts(directory)
    assert parsed['n_imag'] == 0 and 'final.xyz' in geometries
    assert snapshot(directory) == before


@pytest.mark.parametrize('stored', [False, True])
@pytest.mark.parametrize('spc', [False, True])
def test_thermo_preserves_attempt_bytes_including_spc(tmp_path, stored, spc):
    from test_thermo_sections import explicit_water
    directory = explicit_water(attempt(tmp_path))
    sp = explicit_water(attempt(tmp_path, 'sp')) if spc else None
    if spc:
        sp_input(sp, directory)
        # SPC pairing must work from memory even without exported facts/XYZ.
        for name in ('facts.json', 'final.xyz', 'final_input.xyz', '.facts.lock'):
            (directory / name).unlink(missing_ok=True)
    if stored:
        for path in [directory] + ([sp] if spc else []):
            (path / 'facts.json').write_bytes(b'{"previous_parser": true}\r\n')
            (path / 'final.xyz').write_text('Previously reviewed geometry\n')
    before = snapshot(tmp_path)
    result = calculate_thermo([directory], spc={str(directory): str(sp)} if spc else None)
    assert len(result['rows']) == 1
    assert snapshot(tmp_path) == before


def test_thermo_cli_preserves_facts(tmp_path, capsys):
    from test_thermo_sections import explicit_water
    directory = explicit_water(attempt(tmp_path))
    facts.build_facts(directory)
    before = snapshot(directory)
    assert main(['thermo', str(directory), '--json']) == 0
    assert json.loads(capsys.readouterr().out)
    assert snapshot(directory) == before


def test_refusal_diff_refresh_backup_and_identical_noop(tmp_path, capsys):
    directory = attempt(tmp_path)
    target = directory / 'facts.json'
    old = b'{"n_imag": null}\r\n'
    target.write_bytes(old)
    before = target.stat()
    assert main(['facts', str(directory), '--json']) == 1
    error = capsys.readouterr().err
    assert '--refresh' in error and '--- facts.json (existing)' in error
    assert '+++ facts.json (parsed)' in error and '"n_imag": null' in error
    assert target.read_bytes() == old and target.stat().st_mtime_ns == before.st_mtime_ns
    assert not list(directory.glob('*.xyz'))
    assert main(['facts', str(directory), '--refresh', '--json']) == 0
    parsed = json.loads(capsys.readouterr().out)
    archive = directory / f'facts.{sha256(old).hexdigest()[:12]}.json'
    assert archive.read_bytes() == old
    assert json.loads(target.read_bytes()) == parsed
    assert parsed['n_imag'] == 0
    before = snapshot(directory)
    assert main(['facts', str(directory), '--json']) == 0
    capsys.readouterr()
    assert snapshot(directory) == before
    assert main(['facts', str(directory), '--refresh']) == 0
    assert snapshot(directory) == before


def test_multiple_refreshes_retain_every_version(tmp_path, monkeypatch):
    directory = attempt(tmp_path)
    target = directory / 'facts.json'
    versions = []
    for index, digit in enumerate(('a', 'b', 'c')):
        # Actual parsed values must differ; provenance-only changes are a no-op.
        monkeypatch.setattr(facts, 'parse_facts', lambda path, i=index:
                            ({'n_atoms': 3, 'energies': {'scf': -75.0 + i}}, {}))
        monkeypatch.setattr(facts, 'ag_provenance', lambda d=digit: dict(git_commit=d * 40, dirty=False))
        facts.build_facts(directory, refresh=True)
        versions.append(target.read_bytes())
    for old in versions[:-1]:
        assert (directory / f'facts.{sha256(old).hexdigest()[:12]}.json').read_bytes() == old
    assert target.read_bytes() == versions[-1]


@pytest.mark.parametrize('refresh', [False, True])
def test_commit_only_change_preserves_facts_bytes(tmp_path, monkeypatch, capsys, refresh):
    directory = attempt(tmp_path)
    monkeypatch.setattr(facts, 'ag_provenance', lambda: dict(git_commit='a' * 40, dirty=False))
    original = facts.build_facts(directory)
    before = snapshot(directory)
    monkeypatch.setattr(facts, 'ag_provenance', lambda: dict(git_commit='b' * 40, dirty=False))
    assert main(['facts', str(directory), '--json'] + (['--refresh'] if refresh else [])) == 0
    assert json.loads(capsys.readouterr().out) == original
    assert snapshot(directory) == before
    assert not list(directory.glob('facts.*.json'))


@pytest.mark.parametrize('refresh', [False, True])
def test_legacy_without_provenance_preserves_facts_bytes(tmp_path, capsys, refresh):
    directory = attempt(tmp_path)
    original = facts.build_facts(directory)
    original.pop('ag_provenance')
    # Legacy formatting and line endings are part of the signed bytes too.
    (directory / 'facts.json').write_bytes((json.dumps(original, sort_keys=True) + '\r\n').encode())
    before = snapshot(directory)
    assert main(['facts', str(directory), '--json'] + (['--refresh'] if refresh else [])) == 0
    assert json.loads(capsys.readouterr().out) == original
    assert snapshot(directory) == before
    assert not list(directory.glob('facts.*.json'))


@pytest.mark.parametrize('kind', ['collision', 'symlink', 'directory', 'identical'])
def test_existing_backup_is_never_overwritten(tmp_path, kind):
    directory = attempt(tmp_path)
    old = b'{"old": true}\n'
    target = directory / 'facts.json'
    target.write_bytes(old)
    archive = directory / f'facts.{sha256(old).hexdigest()[:12]}.json'
    if kind == 'directory':
        archive.mkdir()
    elif kind == 'symlink':
        archive.symlink_to(target)
    else:
        archive.write_bytes(old if kind == 'identical' else b'preserve this too')
    if kind == 'identical':
        facts.build_facts(directory, refresh=True)
        assert archive.read_bytes() == old
    else:
        with pytest.raises(ValueError):
            facts.build_facts(directory, refresh=True)
        assert target.read_bytes() == old
        if kind == 'collision':
            assert archive.read_bytes() == b'preserve this too'


def test_failed_publish_keeps_original_and_backup(tmp_path, monkeypatch):
    directory = attempt(tmp_path)
    target = directory / 'facts.json'
    old = b'old raw bytes\n'
    target.write_bytes(old)
    def fail(*args):
        raise OSError('injected publish failure')
    monkeypatch.setattr(facts.os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        facts.build_facts(directory, refresh=True)
    assert target.read_bytes() == old
    assert (directory / f'facts.{sha256(old).hexdigest()[:12]}.json').read_bytes() == old
    assert not list(directory.glob('.facts-*'))


@pytest.mark.parametrize('refresh', [False, True])
def test_facts_symlink_is_not_followed(tmp_path, refresh):
    directory = attempt(tmp_path)
    outside = tmp_path / 'evidence.json'
    outside.write_bytes(b'unchanged')
    (directory / 'facts.json').symlink_to(outside)
    with pytest.raises(ValueError, match='符号链接'):
        facts.build_facts(directory, refresh=refresh)
    assert outside.read_bytes() == b'unchanged'


def test_provenance_is_parser_checkout_not_skills(tmp_path, monkeypatch):
    source = tmp_path / 'ag/src/ag/facts.py'
    source.parent.mkdir(parents=True)
    source.write_text('# parser\n')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args], text=True).strip()
    git('init', '-q')
    git('add', 'ag')
    git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Parser fixture')
    monkeypatch.setattr(facts, '__file__', str(source))
    assert facts.ag_provenance() == {'git_commit': git('rev-parse', 'HEAD'), 'dirty': False}
    source.write_text('# changed parser\n')
    assert facts.ag_provenance()['dirty'] is True
    monkeypatch.setattr(facts, '__file__', str(tmp_path / 'installed/ag/src/ag/facts.py'))
    assert facts.ag_provenance() == {'git_commit': None, 'dirty': None}


@pytest.mark.parametrize('old_value,new_value', [(0, 1), (False, 0), (1, 1.0),
                                                 (None, 0), ([], [100.0])])
def test_refusal_summary_reports_nested_changes_without_writes(tmp_path, monkeypatch, capsys,
                                                               old_value, new_value):
    directory = attempt(tmp_path)
    target = directory / 'facts.json'
    old = {'energies': {'scf': -75.0, 'g': old_value, 'old_energy': 1},
           'freq_step_convergence': {'criteria': {'rms_force': {'converged': True}}},
           'removed': {'nested': 1}, 'ag_provenance': {'git_commit': 'old'}}
    new = {'energies': {'scf': -75.0, 'g': new_value, 'new_energy': 2},
           'freq_step_convergence': {'criteria': {'rms_force': {'converged': False}}},
           'job_sections': [{'index': 1}], 'ag_provenance': {'git_commit': 'new'}}
    target.write_text(json.dumps(old) + '\n')
    before = snapshot(directory)
    monkeypatch.setattr(facts, 'parse_facts', lambda path: (new, {'final.xyz': 'not written'}))
    assert main(['facts', str(directory), '--json']) == 1
    error = capsys.readouterr().err
    summary = error.split('facts.json 内容不同')[0]
    assert summary.startswith('差异分类（不含 ag_provenance）：既有值发生变化。')
    assert '新增的键：energies.new_energy, job_sections\n' in summary
    assert '删除的键：energies.old_energy, removed\n' in summary
    assert ('既有值变化的键：energies.g, '
            'freq_step_convergence.criteria.rms_force.converged\n') in summary
    assert 'ag_provenance.git_commit' not in summary
    assert '--- facts.json (existing)' in error and '+++ facts.json (parsed)' in error
    assert not (directory / 'final.xyz').exists()
    assert not list(directory.glob('facts.*.json'))
    after = snapshot(directory)
    after.pop('.facts.lock')  # Existing write-entry lock, not evidence content.
    assert after == before


@pytest.mark.parametrize('old', [b'{bad', b'[]', b'null', b'{"g": NaN}'])
def test_unclassifiable_old_facts_still_refuses_with_diff(tmp_path, capsys, old):
    directory = attempt(tmp_path)
    target = directory / 'facts.json'
    target.write_bytes(old)
    assert main(['facts', str(directory), '--json']) == 1
    error = capsys.readouterr().err
    assert error.startswith('差异分类：') and '无法分类' in error
    assert '--- facts.json (existing)' in error and '--refresh' in error
    assert target.read_bytes() == old and not list(directory.glob('*.xyz'))
    assert not list(directory.glob('facts.*.json'))


def test_deletion_only_summary_and_object_type_change():
    assert '删除的键：energies.g' in facts._difference_summary({'energies': {'g': 1}}, {'energies': {}})
    summary = facts._difference_summary({'energies': {'g': 1}}, {'energies': None})
    assert '既有值变化的键：energies\n' in summary
    assert '删除的键：无' in summary
