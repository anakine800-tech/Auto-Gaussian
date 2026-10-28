"""Synthetic water logs; no cluster access, configuration or scientific claims."""
from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from ag import attempt, cli, facts, fetch, remote, render, state, study, submission
from ag import crest_diagnostics as cd
from test_core import cfg, prepared, finish, seed_submission  # noqa: F401
from test_fetch import ReadOnlyFake
from test_incomplete_fetch import IncompleteFake, observe
from test_slurm import multi  # noqa: F401

WATER = '3\n-5.0\nO 0 0 0\nH 0 0 1\nH 0 1 0\n'
NORMAL = b'CREST terminated normally.\n'


def local_attempt(tmp_path, *, mdopt=False, scheduler='pbs'):
    path = tmp_path / 'attempts' / 'synthetic-crest'
    output = path / 'outputs'
    output.mkdir(parents=True)
    manifest = dict(template='crest', scheduler=scheduler, inputs=[{'name': 'water.xyz'}],
                    template_params={'--mdopt': ''} if mdopt else {}, science={'n_frames': 1})
    (path / 'manifest.json').write_text(json.dumps(manifest))
    (output / 'crest.out').write_bytes(NORMAL)
    if mdopt:
        (output / 'crest_ensemble.xyz').write_text(WATER)
        (output / 'ensemble_energies.log').write_text('-5\n')
    else:
        (output / 'crest_conformers.xyz').write_text(WATER)
        (output / 'crest.energies').write_text('1 0.0\n')
        (output / 'crest_best.xyz').write_text(WATER)
    names = ('job.slurm.out', 'job.slurm.err') if scheduler == 'slurm' else ('job.pbs.out',)
    for name in names:
        (output / name).write_bytes(b'')
    return path


@pytest.mark.parametrize('scheduler,text,rule', [
    ('pbs', 'PBS: job killed: walltime exceeded limit', 'scheduler_time_limit'),
    ('pbs', 'PBS: job killed: memory exceeded limit', 'scheduler_oom'),
    ('slurm', 'slurmstepd: error: *** JOB 123 CANCELLED DUE TO TIME LIMIT ***', 'scheduler_time_limit'),
    ('slurm', 'slurmstepd: error: Detected 1 oom_kill event in step', 'scheduler_oom'),
    ('slurm', 'Fortran runtime error: End of file', 'runtime_error'),
    ('pbs', 'Program received signal SIGSEGV: Segmentation fault', 'runtime_error'),
    ('pbs', '[ERROR] xTB run failed', 'program_error'),
])
@pytest.mark.parametrize('mdopt', [False, True])
def test_explicit_errors_override_normal_with_hash_and_lines(tmp_path, scheduler, text, rule, mdopt):
    path = local_attempt(tmp_path, scheduler=scheduler, mdopt=mdopt)
    name = 'job.slurm.err' if scheduler == 'slurm' else 'job.pbs.out'
    raw = ('\n' + text + '\n').encode()
    (path / 'outputs' / name).write_bytes(raw)
    result = facts.build_facts(path)
    diagnostic = result['crest_diagnostics']
    assert result['termination'] == 'error' and result['n_conformers'] == 1
    assert result['best_energy'] == -5 and result['final_geometry'] == 'final.xyz'
    assert diagnostic['status'] == 'identified'
    match = next(f for f in diagnostic['findings'] if f['rule'] == rule)
    assert diagnostic['sources'][match['source_index']] == dict(
        file=name, sha256=sha256(raw).hexdigest(), line_start=2, line_end=2)
    assert '尚不能据此证明根因' in diagnostic['summary']
    assert text not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize('text,expected', [
    ('', 'none'), ('WARNING: fatal error is only an example\n', 'none'),
    ('OpenBLAS : Warning. Detect OpenMP Loop\n', 'none'),
    ('walltime limit = 300\n', 'unresolved'), ('error\n', 'unresolved'),
    ('exit code 9\n', 'unresolved'), ('killed\n', 'unresolved'),
    ('unknown diagnostic text\n', 'unresolved'),
])
def test_warning_empty_and_unrecognized_are_not_errors(tmp_path, text, expected):
    path = local_attempt(tmp_path)
    (path / 'outputs/job.pbs.out').write_text(text)
    result = facts.build_facts(path)
    diagnostic = result['crest_diagnostics']
    assert result['termination'] == 'normal'
    assert diagnostic['status'] == expected
    assert all(f['level'] != 'error' for f in diagnostic['findings'])
    if not text:
        assert not any(s['file'] == 'job.pbs.out' for s in diagnostic['sources'])
        assert next(f for f in diagnostic['files'] if f['file'] == 'job.pbs.out')['sha256'] == sha256(b'').hexdigest()


def test_missing_legacy_error_output_preserves_termination(tmp_path):
    path = local_attempt(tmp_path)
    (path / 'outputs/job.pbs.out').unlink()
    result = facts.build_facts(path)
    assert result['termination'] == 'normal'
    diagnostic = result['crest_diagnostics']
    assert diagnostic['status'] == 'unavailable'
    assert '错误输出未取回／来源缺失' in diagnostic['summary']
    assert diagnostic['missing_sources'] == ['job.pbs.out']
    assert all(s['file'] != 'job.pbs.out' for s in diagnostic['sources'])


def test_multiple_errors_keep_separate_sources_without_choosing_cause(tmp_path):
    path = local_attempt(tmp_path, scheduler='slurm')
    (path / 'outputs/crest.out').write_bytes(b'[ERROR] energy failed\n' + NORMAL)
    (path / 'outputs/job.slurm.err').write_text(
        'slurmstepd: error: *** JOB 123 CANCELLED DUE TO TIME LIMIT ***\n'
        'slurmstepd: error: Detected 1 oom_kill event\n')
    result = facts.build_facts(path)
    diagnostic = result['crest_diagnostics']
    assert result['termination'] == 'error'
    assert {f['rule'] for f in diagnostic['findings']} >= {
        'program_error', 'normal_termination', 'scheduler_time_limit', 'scheduler_oom'}
    assert '与正常终止标记并存' in diagnostic['summary']


def test_large_repetitive_log_and_long_line_are_bounded(tmp_path, monkeypatch):
    path = local_attempt(tmp_path)
    monkeypatch.setattr(cd, 'MAX_LINE_BYTES', 80)
    monkeypatch.setattr(cd, 'MAX_SUMMARY_CHARS', 40)
    data = b'OpenBLAS : Warning. Detect OpenMP Loop\n' * 10000
    data += b'X' * 10000 + b'\nPBS: job killed: walltime exceeded limit\n'
    (path / 'outputs/job.pbs.out').write_bytes(data)
    result = facts.build_facts(path)
    diagnostic = result['crest_diagnostics']
    assert diagnostic['scan_truncated'] and diagnostic['summary_truncated']
    assert len(diagnostic['summary']) <= 40 and diagnostic['summary'].endswith('…')
    assert len(diagnostic['findings']) <= cd.MAX_FINDINGS
    match = next(f for f in diagnostic['findings'] if f['rule'] == 'scheduler_time_limit')
    source = diagnostic['sources'][match['source_index']]
    assert source['line_start'] == source['line_end'] == 10002
    assert source['sha256'] == sha256(data).hexdigest()
    assert len(json.dumps(diagnostic)) < 6000


@pytest.mark.parametrize('mdopt', [False, True])
@pytest.mark.parametrize('problem', ['missing', 'count', 'bad_energy', 'primary_missing'])
def test_conformer_failures_keep_diagnostics_and_still_fail(tmp_path, mdopt, problem, monkeypatch):
    path = local_attempt(tmp_path, mdopt=mdopt)
    geometry = path / 'outputs' / ('crest_ensemble.xyz' if mdopt else 'crest_conformers.xyz')
    if problem == 'missing':
        geometry.unlink()
    elif problem == 'primary_missing':
        (path / 'outputs/crest.out').unlink()
    elif problem == 'count':
        geometry.write_text(WATER * 2)
    elif mdopt:
        geometry.write_text(WATER.replace('-5.0', '!failed'))
    else:
        (path / 'outputs/crest.energies').write_text('1 nan\n')
    # Parsing is local even when data is incomplete.
    import ag.transport
    monkeypatch.setattr(ag.transport, 'SSHTransport', lambda *a, **k: pytest.fail('no Transport'))
    with pytest.raises(facts.CrestParseIncomplete):
        facts.build_facts(path)
    result = json.loads((path / 'facts.json').read_text())
    diagnostic = result['crest_diagnostics']
    assert diagnostic['parse_status'] == 'incomplete' and diagnostic['parse_error']
    assert diagnostic['summary'].startswith('解析未完成')
    assert result['n_conformers'] is result['best_energy'] is result['n_atoms'] is None
    assert result['final_geometry'] is None
    assert result['termination'] == ('incomplete' if problem == 'primary_missing' else 'normal')
    assert not (path / 'final.xyz').exists() and not (path / 'mdopt.xyz').exists()
    old = (path / 'facts.json').read_bytes()
    assert fetch.auto_facts(path)['status'] == 'failed'
    assert (path / 'facts.json').read_bytes() == old


def test_diagnostic_cli_is_not_success(tmp_path, capsys):
    path = local_attempt(tmp_path)
    (path / 'outputs/crest.energies').unlink()
    assert cli.main(['facts', str(path), '--json']) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)['crest_diagnostics']['parse_status'] == 'incomplete'
    assert '解析未完成' in captured.err


@pytest.mark.parametrize('name', ['job.pbs.out', 'crest.out', 'crest_conformers.xyz', 'outputs'])
def test_symlink_is_hard_refusal_without_facts(tmp_path, name):
    path = local_attempt(tmp_path)
    target = path / 'outputs' if name == 'outputs' else path / 'outputs' / name
    outside = tmp_path / 'outside'
    target.rename(outside)
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='Symbolic links'):
        facts.build_facts(path)
    assert not (path / 'facts.json').exists()


def test_changed_source_is_hard_refusal_even_during_parse_error(tmp_path, monkeypatch):
    import ag._parse_outputs as parser
    path = local_attempt(tmp_path)
    def changed(*args, **kwargs):
        (path / 'outputs/job.pbs.out').write_text('changed')
        raise ValueError('bad geometry')
    monkeypatch.setattr(parser, 'parse_crest', changed)
    with pytest.raises(cd.IntegrityError, match='changed'):
        facts.build_facts(path)
    assert not (path / 'facts.json').exists()


def test_prior_facts_unchanged_or_explicit_conflict_and_refresh(tmp_path):
    path = local_attempt(tmp_path)
    first = facts.build_facts(path)
    target = path / 'facts.json'
    before = target.read_bytes(), target.stat().st_mtime_ns
    assert facts.build_facts(path) == first
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    # Changing even a no-error file changes its source binding.
    (path / 'outputs/job.pbs.out').write_text('WARNING: benign\n')
    with pytest.raises(facts.FactsConflictError):
        facts.build_facts(path)
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    result = facts.build_facts(path, refresh=True)
    assert result['crest_diagnostics']['status'] == 'none'
    assert next(path.glob('facts.*.json')).read_bytes() == before[0]


def prepare_crest(cfg, tmp_path, mdopt=False, legacy=False, cluster='default'):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.xyz'
    source.write_text(WATER)
    manifest = attempt.prepare(cfg, study_name='smoke', template='crest', input_path=source,
                               params={'--mdopt': ''} if mdopt else {}, tier='simple', cluster=cluster,
                               walltime='00:30:00', label='crest', method_basis='兜底方法：合成水')
    path = attempt.find(cfg, manifest['attempt_id'])
    if legacy:
        # Emulate an old immutable manifest before any submission/receipt exists.
        manifest.pop('crest_output_set', None)
        (path / 'manifest.json').write_text(json.dumps(manifest))
    return path, manifest


@pytest.mark.parametrize('mdopt', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_new_and_legacy_output_sets_keep_bundle_bytes(cfg, tmp_path, mdopt, legacy):
    path, manifest = prepare_crest(cfg, tmp_path, mdopt, legacy)
    expected = ['crest.out', 'crest_ensemble.xyz', 'ensemble_energies.log'] if mdopt else [
        'crest.out', 'crest_conformers.xyz', 'crest.energies', 'crest_best.xyz']
    if not legacy:
        assert manifest['crest_output_set'] == 'diagnostics-v1'
        expected += ['job.pbs.out']
    assert remote.output_names(manifest) == expected
    old = dict(manifest)
    old.pop('crest_output_set', None)
    assert render.render(cfg, old, 'water.xyz') == (path / 'inputs/job.pbs').read_text()
    assert attempt.verified_files(cfg, path, manifest)['job.pbs'] == (path / 'inputs/job.pbs').read_bytes()
    slurm = dict(manifest, scheduler='slurm')
    assert remote.output_names(slurm) == [n.replace('job.pbs.out', 'job.slurm.out') for n in expected] + ['job.slurm.err']


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('mdopt', [False, True])
def test_regular_fetch_and_add_missing_keep_old_files(cfg, tmp_path, mdopt, legacy):
    path, manifest = prepare_crest(cfg, tmp_path, mdopt, legacy)
    finish(path)
    all_files = {name: b'' for name in remote.output_names(manifest)}
    all_files['crest.out'] = NORMAL
    all_files['crest_ensemble.xyz' if mdopt else 'crest_conformers.xyz'] = WATER.encode()
    if not mdopt:
        all_files['crest.energies'] = b'1 0.0\n'
    fake = ReadOnlyFake(all_files)
    fetch.fetch(cfg, path, fake)
    assert facts.build_facts(path)['termination'] == 'normal'
    before = {p: p.read_bytes() for p in (path / 'outputs').iterdir() if p.is_file()}
    status_bytes = (path / 'status.json').read_bytes()
    if legacy:
        fake.files['job.pbs.out'] = b'previously undeclared remote output'
    else:
        (path / 'outputs/job.pbs.out').unlink()
    assert fetch.fetch(cfg, path, fake, add_missing=True)['files'] == ([] if legacy else ['job.pbs.out'])
    assert {p: p.read_bytes() for p in before} == before
    assert (path / 'status.json').read_bytes() == status_bytes


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('mdopt', [False, True])
def test_pbs_incomplete_receipt_union_is_stable(cfg, tmp_path, monkeypatch, legacy, mdopt):
    path, manifest = prepare_crest(cfg, tmp_path, mdopt, legacy)
    state.write(path, 'submitting')
    seed_submission(path)
    available = {'crest.out': NORMAL}
    if not legacy:
        available['job.pbs.out'] = b'PBS: job killed: walltime exceeded limit\n'
    fake = IncompleteFake(manifest, available)
    assert observe(cfg, path, fake, monkeypatch, 1000)['state'] == 'awaiting_second_observation'
    assert observe(cfg, path, fake, monkeypatch, 1300)['state'] == 'interrupted'
    before = (path / 'manifest.json').read_bytes(), (path / 'status.json').read_bytes()
    result = fetch.fetch(cfg, path, fake, incomplete=True)
    receipt_path = path / result['record']
    receipt_bytes = receipt_path.read_bytes()
    record = fetch.incomplete_record(path)[1]
    assert set(record['outputs']) | set(record['missing']) == set(remote.output_names(manifest))
    with pytest.raises(facts.CrestParseIncomplete):
        facts.build_facts(path)
    parsed = json.loads((path / 'facts.json').read_text())
    assert parsed['termination'] == ('incomplete' if legacy else 'error')
    assert receipt_path.read_bytes() == receipt_bytes
    assert ((path / 'manifest.json').read_bytes(), (path / 'status.json').read_bytes()) == before
    for options in ({}, {'add_missing': True}, {'incomplete': True}):
        with pytest.raises(FileExistsError):
            fetch.fetch(cfg, path, fake, **options)
    (path / 'outputs/crest.out').write_bytes(b'changed')
    with pytest.raises(ValueError, match='differs from record'):
        facts.build_facts(path)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('mdopt', [False, True])
@pytest.mark.parametrize('incomplete', [False, True])
def test_slurm_fetch_old_new_with_empty_stderr(multi, tmp_path, legacy, mdopt, incomplete):
    path, manifest = prepare_crest(multi, tmp_path, mdopt, legacy, cluster='batch')
    state.write(path, 'submitting')
    submission.record(path, manifest, '123')
    state.write(path, 'submitted', job_id='batch:123')
    state.write(path, 'finished')
    files = {name: b'' for name in remote.output_names(manifest)}
    files['crest.out'] = NORMAL
    if incomplete:
        del files['crest.out']
        files['job.slurm.err'] = b'Fortran runtime error: End of file\n'
        fake = IncompleteFake(manifest, files)
    else:
        files['crest_ensemble.xyz' if mdopt else 'crest_conformers.xyz'] = WATER.encode()
        if not mdopt:
            files['crest.energies'] = b'1 0.0\n'
        fake = ReadOnlyFake(files)
    result = fetch.fetch(multi, path, fake, incomplete=incomplete)
    assert (path / 'outputs/job.slurm.err').read_bytes() == files['job.slurm.err']
    if incomplete:
        receipt = (path / result['record']).read_bytes()
        with pytest.raises(facts.CrestParseIncomplete):
            facts.build_facts(path)
        parsed = json.loads((path / 'facts.json').read_text())
        assert parsed['termination'] == 'error'
        assert parsed['crest_diagnostics']['status'] == 'identified'
        record = fetch.incomplete_record(path)[1]
        assert set(record['outputs']) | set(record['missing']) == set(remote.output_names(manifest))
        assert (path / result['record']).read_bytes() == receipt
    else:
        assert facts.build_facts(path)['n_conformers'] == 1


@pytest.mark.parametrize('incomplete', [False, True])
def test_new_scheduler_download_mismatch_never_published(cfg, tmp_path, monkeypatch, incomplete):
    path, manifest = prepare_crest(cfg, tmp_path)
    files = {name: b'' for name in remote.output_names(manifest)}
    files['crest.out'] = NORMAL
    if incomplete:
        files.pop('crest_conformers.xyz')
        fake = IncompleteFake(manifest, files)
        state.write(path, 'submitting')
        seed_submission(path)
        observe(cfg, path, fake, monkeypatch, 1000)
        observe(cfg, path, fake, monkeypatch, 1300)
    else:
        finish(path)
        fake = ReadOnlyFake(files)
    original = fake.download
    def download(manifest, name, local):
        original(manifest, name, local)
        if name == 'job.pbs.out':
            local.write_bytes(b'corrupt')
    fake.download = download
    with pytest.raises(ValueError, match='hash|mismatch'):
        fetch.fetch(cfg, path, fake, incomplete=incomplete)
    assert not (path / 'outputs/job.pbs.out').exists()
    assert not (path / 'facts.json').exists()
    assert not list(path.glob('fetch-incomplete-*.json'))


def test_source_changed_during_stream_and_nonregular_refused(tmp_path):
    source = tmp_path / 'job.pbs.out'
    source.write_text('warning\n')
    with pytest.raises(cd.IntegrityError, match='changed'):
        cd._read(source, lambda *_: source.write_text('replaced'))
    source.unlink()
    os.mkfifo(source)
    with pytest.raises(cd.IntegrityError, match='regular'):
        cd.diagnose(tmp_path)
    with pytest.raises(cd.IntegrityError, match='Unsupported'):
        cd.source_snapshot(tmp_path, ['../secret'])


def test_unknown_output_version_rejected_and_noncrest_unchanged(cfg, prepared):
    _, manifest = prepared
    assert 'crest_output_set' not in manifest
    before = remote.output_names(manifest)
    assert remote.output_names(dict(manifest, crest_output_set='invalid')) == before
    with pytest.raises(ValueError, match='output set'):
        remote.output_names(dict(manifest, template='crest', crest_output_set='invalid'))


@pytest.mark.parametrize('preview', [False, True])
def test_explicit_reparse_preserves_old_facts_and_reports_failure(tmp_path, preview):
    path = local_attempt(tmp_path / 'study')
    facts.build_facts(path)
    (path / 'status.json').write_text('{"state":"fetched"}')
    old = (path / 'facts.json').read_bytes()
    (path / 'outputs/crest.energies').unlink()
    destination = tmp_path / 'preview.json'
    with pytest.raises(facts.CrestParseIncomplete) as error:
        facts.reparse_facts(path, dry_run=preview, out=destination if preview else None)
    assert error.value.facts['crest_diagnostics']['parse_status'] == 'incomplete'
    if preview:
        assert (path / 'facts.json').read_bytes() == old
        assert json.loads(destination.read_text())['crest_diagnostics']['parse_status'] == 'incomplete'
    else:
        assert next((path / 'facts-history').glob('*.json')).read_bytes() == old
        assert json.loads((path / 'facts.json').read_text())['crest_diagnostics']['parse_status'] == 'incomplete'


@pytest.mark.parametrize('text', ['error', 'some step failed', 'aborted', 'killed'])
def test_unclassified_program_text_is_unresolved_not_a_cause(tmp_path, text):
    path = local_attempt(tmp_path)
    (path / 'outputs/crest.out').write_bytes(text.encode() + b'\n' + NORMAL)
    result = facts.build_facts(path)
    assert result['termination'] == 'normal'
    assert result['crest_diagnostics']['status'] == 'unresolved'
    assert not any(f['level'] == 'error' for f in result['crest_diagnostics']['findings'])
