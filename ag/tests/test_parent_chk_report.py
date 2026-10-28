"""Synthetic water evidence only; no checkpoints, real logs or remote calls."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from ag import attempt, cli, gaussian_input, parent_chk_report as report
from ag._parse_outputs import gaussian_orientation

PARENT = 'water-001-freq'
CHILD = 'water-002-ts'
ROWS = ['O 0 0 0', 'H 0.95 0 0', 'H -0.24 0.92 0']


def orientation(kind='Standard', rows=ROWS):
    return (f' {kind} orientation:\n'
            ' ---------------------------------------------------------------------\n'
            ' Center     Atomic      Atomic             Coordinates (Angstroms)\n'
            ' Number     Number       Type             X           Y           Z\n'
            ' ---------------------------------------------------------------------\n' + ''.join(
                f'{i:7d}{8 if row.startswith("O") else 1:11d}{0:12d}'
                + ''.join(f'{float(x):16.6f}' for x in row.split()[1:]) + '\n'
                for i, row in enumerate(rows, 1)) +
            ' ---------------------------------------------------------------------\n')


def log(route='# B3LYP/6-31G(d) freq', end=' Normal termination of Gaussian\n', modes=True, start='launch'):
    prefix = ' Entering Gaussian System\n Gaussian, Inc.\n' if start == 'launch' else ' --Link1--\n'
    return (prefix + ' -----\n ' + route + '\n -----\n NAtoms=    3\n'
            ' Charge = 0 Multiplicity = 1\n'
            ' Standard basis: 6-31G(d) (6D, 7F)\n'
            ' SCF Done: E(RB3LYP) = -76.0 A.U. after 8 cycles\n'
            + orientation('Input') + orientation() +
            (' Harmonic frequencies (cm**-1)\n'
             '                      1          2          3\n'
             '                      A          A          A\n'
             ' Frequencies --   1000.0000  2000.0000  3000.0000\n'
             ' Red. masses --      1.0000     1.0000     1.0000\n'
             ' Frc consts  --      1.0000     1.0000     1.0000\n'
             ' IR Inten    --      1.0000     1.0000     1.0000\n'
             '  Atom  AN      X      Y      Z        X      Y      Z        X      Y      Z\n'
             '     1   8     1.00   0.00   0.00     0.00   1.00   0.00     0.00   0.00   1.00\n'
             '     2   1    -1.00   0.00   0.00     0.00  -1.00   0.00     0.00   0.00  -1.00\n'
             '     3   1     0.00   0.00   0.00     0.00   0.00   0.00     0.00   0.00   0.00\n\n'
             if modes else '') + end)


def make_attempt(root, aid, *, child=False, rows=ROWS, route=None, parent_id=PARENT):
    directory = root / 'attempts' / aid
    (directory / 'inputs').mkdir(parents=True)
    (directory / 'outputs').mkdir()
    route = route or ('# B3LYP/6-31G(d) opt=(ts,rcfc)' if child else '# B3LYP/6-31G(d) freq')
    text = ('%nprocshared=1\n%mem=1GB\n%chk=water.chk\n' + ('%oldchk=parent.chk\n' if child else '')
            + route + '\n\nwater\n\n0 1\n' + '\n'.join(rows) + '\n\n')
    files = {'water.gjf': text.encode(), 'job.pbs': b'# synthetic script\n'}
    inputs, digest = attempt.bundle(files)
    manifest = dict(attempt_id=aid, study_id=root.name, template='gaussian', cores=1, mem_gb=2,
                    inputs=inputs, bundle_sha256=digest, cluster='default', scheduler='pbs',
                    science=gaussian_input.validate(text, 1, 2, parent_chk=child), parents=[])
    if child:
        manifest.update(parent_chk=dict(attempt_id=parent_id, source_name='water.chk',
                                        target_name='parent.chk', cluster='default'),
                        parents=[dict(attempt_id=parent_id, relation='ts_from')])
    for name, data in files.items():
        (directory / 'inputs' / name).write_bytes(data)
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return directory


@pytest.fixture
def local(tmp_path):
    root = tmp_path / 'synthetic-water'
    root.mkdir()
    (root / 'analyses').mkdir()
    (root / 'study.md').write_text('# synthetic water\n')
    parent = make_attempt(root, PARENT)
    child = make_attempt(root, CHILD, child=True)
    (parent / 'outputs' / 'water.log').write_text(log())
    (parent / 'final_input.xyz').write_text(gaussian_orientation(log(), 'Input'))
    (parent / 'final.xyz').write_text(gaussian_orientation(log(), 'Standard'))
    return root, parent, child


def create(local, name='report', child=CHILD):
    return report.create(PARENT, local[0], 'analyses/' + name + '.json', child)


def run_cli(local, *extra):
    return cli.main(['parent-chk-report', PARENT, '--study', str(local[0]), '--child', CHILD,
                     '--out', 'analyses/report.json', *extra])


def add_receipt(parent, *, digest=None):
    raw = (parent / 'outputs' / 'water.log').read_bytes()
    path = parent / 'fetch-add-missing-synthetic.json'
    path.write_text(json.dumps(dict(attempt_id=parent.name, files=['water.log'], outputs={
        'water.log': dict(size=len(raw), sha256=digest or sha256(raw).hexdigest())})))
    return path


def copy_record(**changes):
    detail = dict(source_attempt=PARENT, source_name='water.chk', target_attempt=CHILD,
                  target_name='parent.chk', size=42, sha256='a' * 64)
    detail.update(changes)
    return dict(action='copy_parent_chk', attempt_id=CHILD, result='verified',
                ts='2026-01-01T00:00:00+00:00', detail=detail)


def test_success_without_remote_credentials_subprocess_or_binary(local, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Must not use credentials, Transport, submit admission or subprocess')
    monkeypatch.setattr(cli, 'load_config', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr('ag.transport.SSHTransport.__init__', forbidden)
    monkeypatch.setattr('ag.parent_chk.resolve', forbidden)
    monkeypatch.setattr('ag.parent_chk.validate_force_constant_frame', forbidden)
    # An unusable binary/link must never be opened or followed.
    (local[1] / 'water.chk').symlink_to(local[0] / 'missing-binary')
    before = {p: p.read_bytes() for p in local[0].rglob('*') if p.is_file() and not p.is_symlink()}
    assert run_cli(local) == 0
    data = json.loads((local[0] / 'analyses/report.json').read_text())
    assert data['frequency']['status'] == 'normal_frequency_found'
    assert data['frequency']['mode_count'] == 3
    assert data['checkpoint']['binding']['status'] == 'matched'
    assert data['checkpoint']['internal_force_constants'] == 'unverified'
    assert data['scientific_suitability'] == 'requires_human_review'
    assert data['frame_comparisons'][0]['status'] == 'matched'
    assert all(r['status'] == 'matched' for r in data['frame_comparisons'])
    assert all(r['atom_identity'].startswith('unknown') for r in data['frame_comparisons'])
    assert all(path.read_bytes() == raw for path, raw in before.items())
    assert '内部力常数未核验' in (local[0] / 'analyses/report.md').read_text()


@pytest.mark.parametrize('text,expected', [
    (log('# B3LYP/6-31G(d) opt', modes=False), 'not_found'),
    (log('# B3LYP/6-31G(d) opt', modes=False, end=''), 'not_found'),
    (log(modes=False), 'not_found'),
    (log(modes=False, end=''), 'ambiguous_or_incomplete'),
    (log(end=' Error termination\n'), 'ambiguous_or_incomplete'),
    (log('# B3LYP/6-31G(d) opt', modes=False) + log(end=' Error termination\n', start='link'), 'ambiguous_or_incomplete'),
    (log() + log(start='link'), 'ambiguous_or_incomplete'),
    (log() + log(start='link', modes=False), 'ambiguous_or_incomplete'),
    (log() + ' unexplained trailing output\n', 'ambiguous_or_incomplete'),
    (log().replace('3000.0000', ''), 'ambiguous_or_incomplete'),
])
def test_frequency_execution_boundaries(local, text, expected):
    (local[1] / 'outputs' / 'water.log').write_text(text)
    result = create(local)
    assert result['frequency']['status'] == expected
    assert result['checkpoint']['internal_force_constants'] == 'unverified'
    assert result['report_status'] == 'complete'


def test_internal_opt_freq_and_raw_crlf_hash(local):
    first = log('# B3LYP/6-31G(d) opt freq', modes=False)
    second = log(start='link').replace(' --Link1--', ' Proceeding to internal job step number 2.')
    raw = (first + second).replace('\n', '\r\n').encode()
    (local[1] / 'outputs/water.log').write_bytes(raw)
    result = create(local)
    frequency = result['frequency']
    assert frequency['status'] == 'normal_frequency_found'
    assert frequency['selected_section'] == 2
    selected = frequency['sections'][1]
    assert selected['source']['section_sha256'] == sha256(second.replace('\n', '\r\n').encode()).hexdigest()
    assert frequency['log']['sha256'] == sha256(raw).hexdigest()
    assert selected['printed']['method'][0]['value'] == ['RB3LYP']


@pytest.mark.parametrize('rows', [
    ['O 0 0 0', 'H 0 0.95 0', 'H -0.92 -0.24 0'],
    [ROWS[0], ROWS[2], ROWS[1]],
    ['O 0 0 0', 'H 0.96 0 0', ROWS[2]],
])
def test_fixed_rows_detect_rotation_reordering_and_change(local, rows):
    child = 'water-003-changed'
    make_attempt(local[0], child, child=True, rows=rows)
    data = create(local, child=child)
    checks = [r for r in data['frame_comparisons'] if r['right'].startswith('child')]
    assert checks and all(r['status'] == 'different' for r in checks)
    assert all(r['different_rows'] == [2, 3] if rows[1] != 'H 0.96 0 0' else r['different_rows'] == [2] for r in checks)
    assert all(r['atom_identity'].startswith('unknown') for r in checks)


def test_coincident_or_symmetric_identity_never_proven():
    geometry = report._geometry(report._frame(['H 0 0 0', 'H 0 0 0']), {})
    assert report._compare(geometry, geometry)['status'] == 'matched'
    assert report._compare(geometry, geometry)['atom_identity'].startswith('unknown')


def test_missing_historical_evidence_and_stale_facts(local):
    (local[1] / 'facts.json').write_text(json.dumps(dict(termination='normal', n_imag=0,
        job_sections=[dict(index=1, route='# opt', start_line=1, end_line=10, termination='normal')])))
    (local[1] / 'outputs/water.log').unlink()
    data = create(local)
    assert data['frequency']['status'] == 'source_unverifiable'
    assert data['checkpoint']['copies']['status'] == 'not_found'
    assert data['saved']['geometries']['final_input.xyz']['origin'] == 'source_unverifiable'
    assert data['saved']['facts']['fields']['termination']['value'] == 'normal'
    assert data['checkpoint']['internal_force_constants'] == 'unverified'


@pytest.mark.parametrize('changes,expected', [({}, 'historically_verified'),
    ({'source_attempt': 'water-004-other'}, 'binding_mismatch'),
    ({'source_name': 'wrong.chk'}, 'binding_mismatch'),
    ({'sha256': None}, 'unverified')])
def test_copy_journal_binding_and_missing_hash(local, changes, expected):
    record = copy_record(**changes)
    (local[0] / 'journal.jsonl').write_text(json.dumps(record) + '\n')
    data = create(local)
    assert data['checkpoint']['copies']['status'] == expected
    assert data['checkpoint']['copies']['records'][0]['source']['line'] == 1
    assert data['checkpoint']['internal_force_constants'] == 'unverified'


def test_wrong_child_parent_binding_is_not_verified_by_copy_record(local):
    child = 'water-003-wrong'
    make_attempt(local[0], child, child=True, parent_id='water-004-other')
    record = copy_record(target_attempt=child)
    record['attempt_id'] = child
    (local[0] / 'journal.jsonl').write_text(json.dumps(record) + '\n')
    data = create(local, child=child)
    assert data['checkpoint']['binding']['status'] == 'mismatch'
    assert data['checkpoint']['copies']['status'] == 'binding_mismatch'


def test_historical_log_hash_is_verified(local):
    receipt = add_receipt(local[1])
    data = create(local)
    ref = data['frequency']['historical_hash_records'][0]
    assert ref['sha256'] == sha256(receipt.read_bytes()).hexdigest()
    assert ref['pointer'] == '/outputs/water.log'


@pytest.mark.parametrize('corrupt', ['input', 'log', 'identity', 'xyz', 'json'])
def test_integrity_errors_nonzero_and_no_report(local, corrupt):
    if corrupt == 'input':
        (local[1] / 'inputs/water.gjf').write_text('corrupted')
    elif corrupt == 'log':
        add_receipt(local[1], digest='0' * 64)
    elif corrupt == 'identity':
        path = local[1] / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['attempt_id'] = 'water-other'
        path.write_text(json.dumps(manifest))
    elif corrupt == 'xyz':
        (local[1] / 'final_input.xyz').write_text('3\nbad\nH nan 0 0\n')
    else:
        (local[1] / 'facts.json').write_text('{broken')
    assert run_cli(local) != 0
    assert not list((local[0] / 'analyses').iterdir())


@pytest.mark.parametrize('relative', ['inputs/water.gjf', 'outputs/water.log', 'manifest.json', 'facts.json', 'final_input.xyz'])
def test_source_symlinks_refused(local, tmp_path, relative):
    target = local[1] / relative
    external = tmp_path / 'external'
    external.write_bytes(target.read_bytes() if target.exists() else b'{}')
    if target.exists():
        target.unlink()
    target.symlink_to(external)
    assert run_cli(local) != 0
    assert not list((local[0] / 'analyses').iterdir())


@pytest.mark.parametrize('option', ['parent', 'child', 'out', 'study_link', 'outputs_link', 'analysis_link'])
def test_escape_and_directory_links(local, tmp_path, option):
    root, parent, _ = local
    args = [PARENT, root, 'analyses/report.json', CHILD]
    if option == 'parent':
        args[0] = '../' + PARENT
    elif option == 'child':
        args[3] = str(parent)
    elif option == 'out':
        args[2] = str(tmp_path / 'report.json')
    elif option == 'study_link':
        link = tmp_path / 'linked-study'
        link.symlink_to(root, target_is_directory=True)
        args[1] = link
    else:
        directory = parent / 'outputs' if option == 'outputs_link' else root / 'analyses'
        other = tmp_path / 'moved'
        directory.rename(other)
        directory.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        report.create(*args)
    assert not (tmp_path / 'report.json').exists()


@pytest.mark.parametrize('suffix', ['json', 'md'])
def test_collision_keeps_existing_and_no_half_pair(local, suffix):
    path = local[0] / ('analyses/report.' + suffix)
    path.write_bytes(b'old')
    assert run_cli(local) != 0
    assert list((local[0] / 'analyses').iterdir()) == [path]
    assert path.read_bytes() == b'old'


def test_publication_collision_after_preflight_rolls_back(local, monkeypatch):
    original = report._publish
    def collide(parent, payloads):
        (parent / 'report.md').write_bytes(b'other writer')
        return original(parent, payloads)
    monkeypatch.setattr(report, '_publish', collide)
    with pytest.raises(FileExistsError):
        create(local)
    assert not (local[0] / 'analyses/report.json').exists()
    assert (local[0] / 'analyses/report.md').read_bytes() == b'other writer'


def test_write_failure_rolls_back_pair(local, monkeypatch):
    def fail(*args):
        raise OSError('synthetic fsync failure')
    monkeypatch.setattr(report.os, 'fsync', fail)
    assert run_cli(local) == 2
    assert not list((local[0] / 'analyses').iterdir())


def test_changed_evidence_before_publication(local, monkeypatch):
    original = report._Sources.verify
    def change(self):
        (local[1] / 'outputs/water.log').write_bytes(b'changed')
        return original(self)
    monkeypatch.setattr(report._Sources, 'verify', change)
    assert run_cli(local) == 1
    assert not list((local[0] / 'analyses').iterdir())


def test_parent_only_and_help(local, capsys):
    data = create(local, child=None)
    assert data['checkpoint']['binding']['status'] == 'not_requested'
    with pytest.raises(SystemExit) as exc:
        cli.main(['parent-chk-report', '--help'])
    assert exc.value.code == 0
    assert '--child' in capsys.readouterr().out


def test_no_input_checkpoint_is_a_gap(local):
    path = local[1] / 'inputs/water.gjf'
    path.write_bytes(path.read_bytes().replace(b'%chk=water.chk\n', b''))
    manifest_path = local[1] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files = {r['name']: (local[1] / 'inputs' / r['name']).read_bytes() for r in manifest['inputs']}
    manifest['inputs'], manifest['bundle_sha256'] = attempt.bundle(files)
    manifest_path.write_text(json.dumps(manifest))
    data = create(local)
    assert data['checkpoint']['parent_input_chk'] is None
    assert data['checkpoint']['binding']['status'] == 'mismatch'


def test_units_are_not_silently_compared_as_angstrom(local):
    child = 'water-003-bohr'
    make_attempt(local[0], child, child=True, route='# B3LYP/6-31G(d) opt=(ts,readfc) units=bohr')
    data = create(local, child=child)
    assert data['child']['coordinate_units'] == 'not_compared'
    assert all(r['status'] == 'unknown' for r in data['frame_comparisons'] if r['right'].startswith('child'))


def test_saved_geometry_claim_cannot_borrow_another_section(local):
    (local[1] / 'facts.json').write_text(json.dumps(dict(final_input_geometry='final_input.xyz',
        fact_sources={'final_input_geometry': 99})))
    data = create(local)
    geometry = data['saved']['geometries']['final_input.xyz']
    assert geometry['matching_log_sections'] == [1]
    assert geometry['saved_source_claim']['agrees_with_coordinates'] is False


def test_incomplete_fetch_record_hash_and_missing_binding(local):
    parent = local[1]
    raw = (parent / 'outputs/water.log').read_bytes()
    manifest = (parent / 'manifest.json').read_bytes()
    receipt = dict(complete=True, attempt_id=PARENT, manifest_sha256=sha256(manifest).hexdigest(),
                   cluster='default', scheduler='pbs', missing=['job.pbs.out'],
                   outputs={'water.log': dict(size=len(raw), sha256=sha256(raw).hexdigest())})
    path = parent / 'fetch-incomplete-synthetic.json'
    path.write_text(json.dumps(receipt))
    data = create(local, name='valid')
    assert len(data['frequency']['historical_hash_records']) == 1
    (parent / 'outputs/job.pbs.out').write_bytes(b'new')
    assert run_cli(local) == 1
    assert not (local[0] / 'analyses/report.json').exists()


@pytest.mark.parametrize('kind', ['manifest_hash', 'foreign_attempt', 'missing_list'])
def test_invalid_fetch_record_binding(local, kind):
    parent = local[1]
    record = dict(complete=True, attempt_id=PARENT,
                  manifest_sha256=sha256((parent / 'manifest.json').read_bytes()).hexdigest(),
                  cluster='default', scheduler='pbs', missing=[], outputs={})
    if kind == 'manifest_hash':
        record['manifest_sha256'] = '0' * 64
    elif kind == 'foreign_attempt':
        record['attempt_id'] = 'water-other'
    else:
        record['missing'] = [{}]
    (parent / 'fetch-incomplete-synthetic.json').write_text(json.dumps(record))
    assert run_cli(local) == 1
    assert not list((local[0] / 'analyses').iterdir())


def test_checkpoint_attachment_is_rejected_before_read(local, monkeypatch):
    manifest_path = local[1] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['inputs'].insert(0, dict(name='binary.chk', size=42, sha256='a' * 64))
    manifest_path.write_text(json.dumps(manifest))
    original = report._Sources.read
    def guarded(self, path, **kwargs):
        assert path.suffix != '.chk', 'Never read a checkpoint'
        return original(self, path, **kwargs)
    monkeypatch.setattr(report._Sources, 'read', guarded)
    assert run_cli(local) == 1


def test_missing_required_input_is_io_error(local):
    (local[1] / 'inputs/water.gjf').unlink()
    assert run_cli(local) == 2
    assert not list((local[0] / 'analyses').iterdir())


def test_two_conflicting_verified_copy_records_remain_conflicting(local):
    records = [copy_record(), copy_record(sha256='b' * 64)]
    (local[0] / 'journal.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in records))
    data = create(local)
    assert data['checkpoint']['copies']['status'] == 'conflicting_records'


def test_structurally_invalid_records_have_controlled_exit(local):
    path = local[1] / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['inputs'] = [None]
    path.write_text(json.dumps(manifest))
    assert run_cli(local, '--json') == 1
    assert not list((local[0] / 'analyses').iterdir())


def test_output_ancestor_replaced_before_publish_is_not_followed(local, tmp_path, monkeypatch):
    original = report._publish
    outside = tmp_path / 'outside'
    outside.mkdir()
    def swap(parent, payloads):
        parent.rename(parent.with_name('old-analyses'))
        parent.symlink_to(outside, target_is_directory=True)
        return original(parent, payloads)
    monkeypatch.setattr(report, '_publish', swap)
    with pytest.raises(OSError):
        create(local)
    assert not list(outside.iterdir())


def test_qst_child_compares_each_explicit_structure(local):
    child = 'water-003-qst'
    directory = make_attempt(local[0], child, child=True)
    input_path = directory / 'inputs/water.gjf'
    text = ('%nprocshared=1\n%mem=1GB\n%chk=water.chk\n%oldchk=parent.chk\n'
            '# B3LYP/6-31G(d) opt=(qst2,readfc)\n\n'
            'first\n\n0 1\n' + '\n'.join(ROWS) + '\n\n'
            'second\n\n0 1\n' + '\n'.join([ROWS[0], ROWS[2], ROWS[1]]) + '\n\n')
    input_path.write_text(text)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files = {r['name']: (directory / 'inputs' / r['name']).read_bytes() for r in manifest['inputs']}
    manifest['inputs'], manifest['bundle_sha256'] = attempt.bundle(files)
    manifest['science'] = gaussian_input.validate(text, 1, 2, parent_chk=True)
    manifest_path.write_text(json.dumps(manifest))
    data = create(local, child=child)
    assert all(r['status'] == 'matched' for r in data['frame_comparisons'] if r['right'] == 'child_structure_1')
    assert all(r['status'] == 'different' for r in data['frame_comparisons'] if r['right'] == 'child_structure_2')


def test_checkpoint_in_title_is_not_a_link0_binding(local):
    path = local[1] / 'inputs/water.gjf'
    text = path.read_text().replace('%chk=water.chk\n', '').replace('\n\nwater\n', '\n\n%chk=title.chk\n')
    path.write_text(text)
    manifest_path = local[1] / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    files = {r['name']: (local[1] / 'inputs' / r['name']).read_bytes() for r in manifest['inputs']}
    manifest['inputs'], manifest['bundle_sha256'] = attempt.bundle(files)
    manifest['science']['method_basis'] = 'declared method note'
    manifest_path.write_text(json.dumps(manifest))
    data = create(local)
    assert data['checkpoint']['parent_input_chk'] is None
    assert data['parent']['manifest_method_basis']['value'] == 'declared method note'
    assert data['parent']['manifest_method_basis']['source']['pointer'] == '/science/method_basis'
