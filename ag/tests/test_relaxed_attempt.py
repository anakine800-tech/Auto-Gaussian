"""T188 synthetic preparation/submission checks; no real configuration or jobs."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from ag import attempt, confirm, remote, state, study, submit
from test_core import cfg, prepared, Fake, INPUT
from test_parent_chk import parent, CheckpointFake


INCLUDED = INPUT.replace('B3LYP/6-31G(d)', 'HF/Gen') + '@a-basis.inc\n'
BASIS = b'O H 0\nSTO-3G\n****\n'
LINKED = INPUT + ('--Link1--\n%nprocshared=8\n%mem=10GB\n%chk=water.chk\n'
                  '# HF/STO-3G Geom=AllCheck Guess=Read SP\n\n')

W7_INPUTS = [
    ('gen', '# HF/Gen SP', 'O H 0\nSTO-3G\n****\n', 'general_basis_semantics'),
    ('genecp', '# HF/GenECP SP', 'O H 0\nSTO-3G\n****\n\nO 0\nLANL2DZ\n', 'ecp_semantics'),
    ('scrf-read', '# HF/STO-3G SCRF=(PCM,Read)', 'eps=20.5\nepsinf=2.0\n', 'scrf_read_semantics'),
    ('nbo', '# HF/STO-3G Pop=NBORead', '$NBO NPA BNDIDX $END\n', 'nbo_section_semantics'),
    ('ts-modredundant', '# HF/STO-3G Opt=(TS,CalcFC,ModRedundant)', 'B 1 2 F\n', 'modredundant_semantics'),
    ('three-coordinates-200-steps', '# HF/STO-3G Opt=ModRedundant',
     'B 1 2 S 200 0.01\nB 1 3 S 200 0.01\nA 2 1 3 S 200 1.0\n', 'modredundant_semantics'),
    ('wildcards-cartesian-freeze', '# HF/STO-3G Opt=ModRedundant',
     'B * * F\nX 1 F\n', 'modredundant_semantics'),
    ('units-multiple-tails', '# HF/Gen Opt=ModRedundant Units=Bohr SCRF=(PCM,Read) Pop=NBORead',
     'B 1 2 S 200 0.01\n\nO H 0\nSTO-3G\n****\n\neps=20.5\n\n$NBO NPA $END\n',
     'coordinate_unit_semantics'),
]


def prepare(cfg, tmp_path, *, text=INPUT, include=False, relaxed=True, **kwargs):
    if not (Path(cfg['local']['studies_root']) / 'smoke').exists():
        study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(text)
    attachments = []
    if include:
        attachment = tmp_path / 'a-basis.inc'
        attachment.write_bytes(BASIS)
        attachments.append(attachment)
    m = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='sp',
                        method_basis='兜底方法：合成测试', relaxed_input=relaxed,
                        include_files=attachments, **kwargs)
    return attempt.find(cfg, m['attempt_id']), m


def write_manifest(path, value):
    (path / 'manifest.json').write_text(json.dumps(value))


def rebind_bundle(path, manifest):
    files = {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()}
    records, manifest['bundle_sha256'] = attempt.bundle(files)
    records.sort(key=lambda row: (row['name'] != 'water.gjf', row['name']))
    manifest['inputs'] = records
    write_manifest(path, manifest)


def test_default_strict_input_and_bundle_remain_unchanged(cfg, tmp_path):
    path, manifest = prepare(cfg, tmp_path, relaxed=False)
    files = attempt.verified_files(cfg, path, manifest)
    assert files['water.gjf'] == INPUT.encode()
    assert set(files) == {'water.gjf', 'job.pbs'}
    assert 'input_validation' not in manifest
    assert 'sections' not in manifest['science']
    assert (manifest['inputs'], manifest['bundle_sha256']) == attempt.bundle(files)
    assert (tmp_path / 'water.gjf').read_bytes() == INPUT.encode()


@pytest.mark.parametrize('name,route,tail,feature', W7_INPUTS, ids=[case[0] for case in W7_INPUTS])
def test_w7_positive_prepare_verify_and_fake_submit(cfg, tmp_path, monkeypatch, name, route, tail, feature):
    text = INPUT.replace('# B3LYP/6-31G(d) SP', route) + tail
    path, manifest = prepare(cfg, tmp_path, text=text)
    assert feature in manifest['input_validation']['skipped_checks']
    verified = attempt.verified_files(cfg, path, manifest)
    assert verified['water.gjf'] == text.encode()
    assert manifest['science']['geometry'] == 'O 0 0 0\nH 0 0 1\nH 0 1 0'
    shown = []
    monkeypatch.setattr(confirm, 'confirm', lambda summary: shown.append(summary) or True)
    fake = Fake(cfg)
    assert submit.submit(cfg, [path.name], fake)[0]['state'] == 'submitted'
    assert fake.operations().count('submit') == 1
    assert fake.files == verified
    assert text in shown[0] and feature in shown[0]
    assert attempt.read_manifest(path) == manifest


def test_relaxed_exact_marker_even_for_strict_looking_input(cfg, tmp_path):
    path, manifest = prepare(cfg, tmp_path)
    assert manifest['input_validation'] == {
        'mode': 'relaxed', 'method_verified': False, 'skipped_checks': ['scientific_method']}
    files = attempt.verified_files(cfg, path, manifest)
    assert files['water.gjf'] == INPUT.encode()
    record = json.loads(files['input-validation.json'])
    assert record == {'main_input': 'water.gjf', 'attachments': [],
                      'input_validation': manifest['input_validation']}
    assert '未核验' in attempt.summary(cfg, manifest)
    assert 'scan-peak' in attempt.summary(cfg, manifest)


def test_includes_bound_without_mutation_main_input_first(cfg, tmp_path):
    path, manifest = prepare(cfg, tmp_path, text=INCLUDED, include=True)
    files = attempt.verified_files(cfg, path, manifest)
    assert (tmp_path / 'water.gjf').read_bytes() == files['water.gjf'] == INCLUDED.encode()
    assert (tmp_path / 'a-basis.inc').read_bytes() == files['a-basis.inc'] == BASIS
    assert manifest['inputs'][0]['name'] == 'water.gjf'
    assert attempt.program_input_name(manifest) == 'water.gjf'
    assert attempt.prepared_bundle(files) == (manifest['inputs'], manifest['bundle_sha256'])
    assert attempt.bundle(files)[1] == manifest['bundle_sha256']
    assert remote.output_names(manifest)[0] == 'water.log'
    record = json.loads(files['input-validation.json'])
    assert record['attachments'] == [dict(name='a-basis.inc', size=len(BASIS),
                                        sha256=sha256(BASIS).hexdigest())]
    assert 'general_basis_semantics' in manifest['input_validation']['skipped_checks']
    summary = attempt.summary(cfg, manifest)
    assert INCLUDED in summary and BASIS.decode() in summary


@pytest.mark.parametrize('main_name,include_name', [
    ('water.gjf', 'a-basis.gjf'),
    ('water..gjf', 'a..basis.inc'),
])
def test_main_identity_and_plain_double_dot_basenames(cfg, tmp_path, main_name, include_name):
    study.init(cfg, 'smoke')
    source, attachment = tmp_path / main_name, tmp_path / include_name
    text = INCLUDED.replace('a-basis.inc', include_name)
    source.write_text(text)
    attachment.write_bytes(BASIS)
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:30:00', label='sp',
                               method_basis='兜底方法：合成测试', relaxed_input=True,
                               include_files=[attachment])
    path = attempt.find(cfg, manifest['attempt_id'])
    files = attempt.verified_files(cfg, path, manifest)
    assert include_name < main_name
    assert manifest['inputs'][0]['name'] == main_name
    assert attempt.program_input_name(manifest) == main_name
    assert attempt.prepared_bundle(files) == (manifest['inputs'], manifest['bundle_sha256'])
    assert remote.output_names(manifest)[0] == Path(main_name).stem + '.log'
    assert files[main_name] == source.read_bytes() == text.encode()
    assert files[include_name] == attachment.read_bytes() == BASIS
    record = json.loads(files['input-validation.json'])
    assert record['main_input'] == main_name
    assert record['attachments'] == [dict(name=include_name, size=len(BASIS),
                                        sha256=sha256(BASIS).hexdigest())]


@pytest.mark.parametrize('template', ['gaussian-cp', 'xtb', 'crest'])
def test_relaxed_input_never_expands_other_template_boundaries(cfg, tmp_path, template):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    with pytest.raises(ValueError, match='ordinary gaussian template'):
        attempt.prepare(cfg, study_name='smoke', template=template, input_path=source,
                        tier='simple', walltime='00:30:00', label='sp',
                        method_basis='兜底方法：合成测试', relaxed_input=True)
    assert list((Path(cfg['local']['studies_root']) / 'smoke/attempts').iterdir()) == []


@pytest.mark.parametrize('damage', ['external', 'second-resources', 'third-external',
                                   'missing-include', 'symlink', 'hardlink', 'duplicate'])
def test_invalid_input_never_allocates_attempt(cfg, tmp_path, damage):
    study.init(cfg, 'smoke')
    root = Path(cfg['local']['studies_root']) / 'smoke'
    source = tmp_path / 'water.gjf'
    text = INPUT
    includes = []
    if damage == 'external':
        text = INPUT.replace(' SP', ' External=(bad)')
    elif damage == 'second-resources':
        text = LINKED.replace('--Link1--\n%nprocshared=8', '--Link1--\n%nprocshared=44')
    elif damage == 'third-external':
        text = LINKED + '--Link1--\n' + INPUT.replace(' SP', ' ExTeRnAl\n=(bad)')
    elif damage == 'missing-include':
        text = INCLUDED
    source.write_text(text)
    if damage == 'symlink':
        real = tmp_path / 'real.gjf'
        source.rename(real)
        source.symlink_to(real)
    if damage in {'hardlink', 'duplicate'}:
        extra = tmp_path / 'a-basis.inc'
        if damage == 'hardlink':
            os.link(source, extra)
        else:
            extra.write_bytes(BASIS)
        includes = [extra] * (2 if damage == 'duplicate' else 1)
    before = list((root / 'attempts').iterdir())
    with pytest.raises(ValueError):
        attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='sp',
                        method_basis='兜底方法：合成测试', relaxed_input=True, include_files=includes)
    assert list((root / 'attempts').iterdir()) == before == []


@pytest.mark.parametrize('damage', ['marker-removed', 'mode', 'method', 'skip', 'science',
                                   'sidecar-removed', 'sidecar-bytes', 'include-bytes',
                                   'rebound-sidecar', 'rebound-skips',
                                   'rebound-main-missing', 'rebound-main-path', 'rebound-main-suffix',
                                   'rebound-record-list', 'rebound-record-extra', 'rebound-record-missing'])
def test_verify_and_submit_refuse_tampering_before_remote(cfg, tmp_path, monkeypatch, damage):
    path, manifest = prepare(cfg, tmp_path, text=INCLUDED, include=True)
    changed = deepcopy(manifest)
    if damage == 'marker-removed':
        changed.pop('input_validation')
    elif damage == 'mode':
        changed['input_validation']['mode'] = 'strict'
    elif damage == 'method':
        changed['input_validation']['method_verified'] = True
    elif damage == 'skip':
        changed['input_validation']['skipped_checks'] = []
    elif damage == 'science':
        changed['science']['route'] = '# HF/STO-3G SP'
    elif damage == 'sidecar-removed':
        (path / 'inputs/input-validation.json').unlink()
    elif damage in {'sidecar-bytes', 'rebound-sidecar'}:
        (path / 'inputs/input-validation.json').write_text('{}')
    elif damage == 'include-bytes':
        (path / 'inputs/a-basis.inc').write_bytes(BASIS.replace(b'STO-3G', b'6-31G'))
    elif damage == 'rebound-skips':
        changed['input_validation']['skipped_checks'] = []
        record = json.loads((path / 'inputs/input-validation.json').read_text())
        record['input_validation'] = changed['input_validation']
        (path / 'inputs/input-validation.json').write_text(json.dumps(record))
    elif damage.startswith(('rebound-main-', 'rebound-record-')):
        record = json.loads((path / 'inputs/input-validation.json').read_text())
        if damage.startswith('rebound-main-'):
            record['main_input'] = {'rebound-main-missing': 'absent.gjf',
                                    'rebound-main-path': '../water.gjf',
                                    'rebound-main-suffix': 'a-basis.inc'}[damage]
        elif damage == 'rebound-record-list':
            record = []
        elif damage == 'rebound-record-extra':
            record['unexpected'] = True
        else:
            del record['attachments']
        (path / 'inputs/input-validation.json').write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    if damage.startswith('rebound-'):
        rebind_bundle(path, changed)
    else:
        write_manifest(path, changed)
    with pytest.raises(ValueError):
        attempt.verified_files(cfg, path, changed)
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: pytest.fail('invalid inputs must not reach dialog'))
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake)
    assert not fake.calls and not (path / '.submit-claim').exists()
    assert state.read(path)['state'] == 'prepared'


@pytest.mark.parametrize('allow_relaxed', [False, True])
def test_legacy_policy_cannot_authorize_relaxed_input(cfg, tmp_path, monkeypatch, allow_relaxed):
    path, manifest = prepare(cfg, tmp_path)
    policy = dict(studies=['smoke'], templates=['gaussian'], clusters=['default'],
                  max_cores_per_job=8, max_walltime='00:30:00',
                  quote='Synthetic local test only', set_at='2026-10-23T00:00:00+00:00')
    if allow_relaxed:
        policy['allow_relaxed'] = True
    cfg['approval'] = {'policies': {'validation': policy}}
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: pytest.fail('policy must not fall back'))
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake, policy_name='validation')
    assert not fake.calls and not (path / '.submit-claim').exists()


def test_submit_dialog_archives_full_relaxed_summary(cfg, tmp_path, monkeypatch):
    path, manifest = prepare(cfg, tmp_path, text=LINKED)
    sections = manifest['science']['sections']
    assert len(sections) == 2 and sections[1]['charge'] is None
    assert sections[1]['multiplicity'] is None and sections[1]['geometry'] is None
    shown = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: shown.append(text) or True)
    fake = Fake(cfg)
    assert submit.submit(cfg, [path.name], fake)[0]['state'] == 'submitted'
    assert fake.operations().count('submit') == 1 and len(shown) == 1
    text = shown[0]
    assert LINKED in text
    for section in sections:
        assert section['route'] in text
    for record in manifest['inputs']:
        assert record['sha256'] in text
    for required in ['未核验', 'scan-peak', 'profile', 'unknown', 'water.chk',
                     manifest['bundle_sha256'], 'scientific_method']:
        assert required in text
    archived = json.loads((path / 'submission-summary.json').read_text())
    assert archived['summary'] == text
    assert archived['manifest_sha256'] == sha256((path / 'manifest.json').read_bytes()).hexdigest()
    assert attempt.read_manifest(path)['input_validation']['method_verified'] is False


def test_submit_dialog_shows_exact_include_text(cfg, tmp_path, monkeypatch):
    path, manifest = prepare(cfg, tmp_path, text=INCLUDED, include=True)
    shown = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: shown.append(text) or False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(cfg, [path.name], Fake(cfg))
    assert len(shown) == 1 and INCLUDED in shown[0] and BASIS.decode() in shown[0]
    assert manifest['bundle_sha256'] in shown[0]
    assert not (path / '.submit-claim').exists()


@pytest.mark.parametrize('damage', ['include', 'marker'])
def test_post_confirmation_mutation_has_no_remote_writes(cfg, tmp_path, monkeypatch, damage):
    path, manifest = prepare(cfg, tmp_path, text=INCLUDED, include=True)
    fake = Fake(cfg)
    def accept_then_change(text):
        if damage == 'include':
            (path / 'inputs/a-basis.inc').write_text('changed bytes')
        else:
            changed = deepcopy(manifest)
            changed['input_validation']['method_verified'] = True
            write_manifest(path, changed)
        return True
    monkeypatch.setattr(confirm, 'confirm', accept_then_change)
    with pytest.raises(ValueError):
        submit.submit(cfg, [path.name], fake)
    assert fake.operations() == ['identity', 'jobs']
    assert not (path / '.submit-claim').exists()
    assert not (path / 'submission-summary.json').exists()


@pytest.mark.parametrize('mode', ['Check', 'AllCheck'])
def test_checkpoint_geometry_uses_existing_parent_copy(cfg, parent, tmp_path, monkeypatch, mode):
    source = tmp_path / 'child.gjf'
    text = ('%nprocshared=8\n%mem=10GB\n%oldchk=parent.chk\n%chk=child.chk\n'
            f'# HF/STO-3G Geom={mode} Guess=Read SP\n\n')
    if mode == 'Check':
        text += 'Synthetic water restart\n\n0 1\n\n'
    source.write_text(text)
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:30:00', label='check',
                               method_basis='兜底方法：合成测试', relaxed_input=True,
                               parents=[dict(attempt_id=parent[0].name, relation='restart_from')],
                               parent_chk=parent[0].name + ':water.chk')
    path = attempt.find(cfg, manifest['attempt_id'])
    science = manifest['science']
    assert science['geometry'] is None and science['n_atoms'] is None
    assert science['charge'] == (0 if mode == 'Check' else None)
    assert science['multiplicity'] == (1 if mode == 'Check' else None)
    assert science['geometry_source'] == dict(kind='parent_chk', attempt_id=parent[0].name,
                                             filename='parent.chk')
    assert 'parent.chk' not in attempt.verified_files(cfg, path, manifest)
    fake = CheckpointFake(cfg, parent[1])
    original = fake.source.read_bytes()
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    assert submit.submit(cfg, [path.name], fake)[0]['state'] == 'submitted'
    assert fake.source.read_bytes() == original
    assert (Path(remote.attempt_dir(cfg, manifest)) / 'parent.chk').read_bytes() == original
    assert fake.operations().count('copy_parent_chk') == 1
    assert fake.operations().count('parent_chk_metadata') == 3


def test_parent_input_replacement_blocks_relaxed_child_before_remote(cfg, parent, tmp_path, monkeypatch):
    source = tmp_path / 'child.gjf'
    source.write_text('%nprocshared=8\n%mem=10GB\n%oldchk=parent.chk\n%chk=child.chk\n'
                      '# HF/STO-3G Geom=AllCheck SP\n\n')
    manifest = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:30:00', label='check',
                               method_basis='兜底方法：合成测试', relaxed_input=True,
                               parents=[dict(attempt_id=parent[0].name, relation='restart_from')],
                               parent_chk=parent[0].name + ':water.chk')
    path = attempt.find(cfg, manifest['attempt_id'])
    (parent[0] / 'inputs/water.gjf').write_text(INPUT.replace('water.chk', 'other.chk'))
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('parent damage must be rejected locally'))
    with pytest.raises(ValueError, match='Parent input differs'):
        submit.submit(cfg, [path.name], fake)
    assert not fake.calls and not (path / '.submit-claim').exists()


def input_race_fixture(tmp_path, kind):
    directory = tmp_path / 'reviewed-input'
    replacement = tmp_path / 'replacement'
    for root in (directory, replacement):
        (root / 'nested').mkdir(parents=True)
    basename = 'water.gjf' if kind == 'source' else 'a-basis.inc'
    original = INPUT.encode() if kind == 'source' else BASIS
    substituted = (INPUT.replace('Water smoke', 'Unreviewed input').encode() if kind == 'source'
                   else BASIS.replace(b'STO-3G', b'6-31G'))
    source = directory / 'nested' / basename
    source.write_bytes(original)
    (replacement / 'nested' / basename).write_bytes(substituted)
    return directory, replacement, source, original, substituted


@pytest.mark.parametrize('kind', ['source', 'attachment'])
def test_ancestor_replaced_before_open_refuses_before_sequence(cfg, tmp_path, monkeypatch, kind):
    study.init(cfg, 'smoke')
    directory, replacement, raced_path, original, substituted = input_race_fixture(tmp_path, kind)
    source = raced_path
    includes = []
    if kind == 'attachment':
        source = tmp_path / 'water.gjf'
        source.write_text(INCLUDED)
        includes = [raced_path]
    real_open = os.open
    raced = []
    def replace_before_open(name, flags, *args, **kwargs):
        # The component form targets the descriptor walk; the absolute form
        # reproduces the old check-then-open implementation's vulnerable call.
        if not raced and os.fspath(name) in (directory.name, str(raced_path)):
            directory.rename(tmp_path / 'retained-original')
            directory.symlink_to(replacement, target_is_directory=True)
            raced.append(True)
        return real_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', replace_before_open)
    with pytest.raises((ValueError, OSError)):
        attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='sp',
                        method_basis='兜底方法：合成测试', relaxed_input=True, include_files=includes)
    assert raced == [True]
    assert list((Path(cfg['local']['studies_root']) / 'smoke/attempts').iterdir()) == []
    assert (tmp_path / 'retained-original/nested' / raced_path.name).read_bytes() == original
    assert raced_path.read_bytes() == substituted


@pytest.mark.parametrize('kind', ['source', 'attachment'])
def test_ancestor_replaced_after_parent_pin_never_reads_substitute(tmp_path, monkeypatch, kind):
    directory, replacement, source, original, substituted = input_race_fixture(tmp_path, kind)
    before = source.stat()
    real_open = os.open
    raced = []
    def replace_before_file(name, flags, *args, **kwargs):
        if not raced and Path(os.fsdecode(name)).name == source.name:
            directory.rename(tmp_path / 'retained-original')
            directory.symlink_to(replacement, target_is_directory=True)
            raced.append(True)
        return real_open(name, flags, *args, **kwargs)
    monkeypatch.setattr(os, 'open', replace_before_file)
    try:
        raw, identity = attempt._regular_input(source)
    except (ValueError, OSError):
        pass  # Rejecting the changed namespace is also safe.
    else:
        assert raw == original and raw != substituted
        assert identity == (before.st_dev, before.st_ino)
    assert raced == [True]
    assert (tmp_path / 'retained-original/nested' / source.name).read_bytes() == original
    assert source.read_bytes() == substituted
