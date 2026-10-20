"""T47: synthetic outputs only; no network, scheduler submission or Gaussian."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from ag import attempt, cancel, cli, config, facts, fetch, parent_chk, remote, state, status, submission
from ag.transport import Result, TransportError
from test_core import cfg, prepared, seed_submission, job_text
from test_slurm import multi, prepare

MTIME = '2026-01-01 00:00:00.000000000 +0000'
LOG = ("""Gaussian, Inc.
 --------------------
 #p HF/STO-3G Opt
 --------------------
 Charge = 0 Multiplicity = 1
 Input orientation:
 --------------------
 Center Atomic Atomic Coordinates (Angstroms)
 Number Number Type X Y Z
 --------------------
 1 8 0 0.0 0.0 0.0
 2 1 0 0.0 0.0 1.0
 3 1 0 0.0 1.0 0.0
 --------------------
 Standard orientation:
 --------------------
 Center Atomic Atomic Coordinates (Angstroms)
 Number Number Type X Y Z
 --------------------
 1 8 0 0.0 0.0 0.0
 2 1 0 0.0 0.0 1.0
 3 1 0 0.0 1.0 0.0
 --------------------
 SCF Done: E(RHF) = -75.0 A.U.
""")


class IncompleteFake:
    def __init__(self, manifest, files=None):
        self.manifest = manifest
        self.files = {'water.log': LOG.encode()} if files is None else files
        self.calls = []
        self.downloaded = []
        self.queue = Result(153, stderr='qstat: Unknown Job Id Error')
        self.slurm_queue = Result()
        self.accounting_state = 'TIMEOUT'
        self.accounting = None
        self.receipt = 'absent\n'
        self.corrupt = False
        self.failure = None
        self.after_download = lambda: None

    def run(self, command):
        self.calls.append(command)
        if self.failure == command.operation:
            return Result(255, stderr='synthetic connection failure')
        if command.operation == 'output_observation':
            if 'test -x' in command.text:  # new per-file strict observer
                name = next(n for n in remote.output_names(self.manifest)
                            if ('/' + n) in command.text)
                data = self.files.get(name)
                return Result(stdout='absent\n' if data is None else f'{len(data)} {MTIME}\n')
            return Result(stdout=''.join(
                f'{name} absent\n' if name not in self.files else f'{name} {len(self.files[name])} {MTIME}\n'
                for name in remote.output_names(self.manifest)))
        if command.operation == 'metadata':
            name = Path(shlex.split(command.text)[-1]).name
            data = self.files.get(name)
            return Result(1) if data is None else Result(
                stdout=f'{len(data)}\n{sha256(data).hexdigest()}  {shlex.split(command.text)[-1]}\n')
        if command.operation == 'receipt':
            return Result(stdout=self.receipt if 'ag-exit.json' in command.text else 'absent\n')
        if command.operation == 'jobs':
            return self.queue
        if command.operation == 'identity':
            return Result(stdout='fixture\n')
        if command.operation == 'slurm_jobs':
            return self.slurm_queue
        if command.operation == 'slurm_accounting':
            return self.accounting or Result(stdout=f"123|{self.manifest['attempt_id']}|fixture|{self.accounting_state}|1:9|00:05:00|8\n")
        if command.operation == 'completion_marker':
            return Result(stdout='absent\n')
        if command.operation in ('cancel', 'slurm_cancel'):
            return Result()
        raise AssertionError(command.operation)

    def download(self, manifest, name, local):
        self.downloaded.append(name)
        with local.open('xb') as handle:
            handle.write(self.files[name] + (b'corrupt' if self.corrupt else b''))
        self.after_download()


def observe(cfg, path, fake, monkeypatch, at):
    monkeypatch.setattr(status.time, 'time', lambda: at)
    return status.check(cfg, path, fake)


@pytest.fixture
def interrupted(cfg, prepared, monkeypatch):
    path, manifest = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    fake = IncompleteFake(manifest)
    assert observe(cfg, path, fake, monkeypatch, 1000)['state'] == 'awaiting_second_observation'
    assert observe(cfg, path, fake, monkeypatch, 1300)['state'] == 'interrupted'
    return path, manifest, fake


def assert_unpublished(path):
    assert not [p for p in (path / 'outputs').iterdir() if p.name != '.partial']
    assert not list(path.glob('fetch-incomplete-*.json'))


def test_pbs_success_record_state_preservation_and_repeat(cfg, interrupted):
    path, manifest, fake = interrupted
    before = (path / 'status.json').read_bytes()
    result = fetch.fetch(cfg, path, fake, incomplete=True)
    assert result['files'] == ['water.log'] and result['missing'] == ['job.pbs.out']
    assert (path / 'status.json').read_bytes() == before
    record = json.loads((path / result['record']).read_text())
    assert record['manifest_sha256'] == sha256((path / 'manifest.json').read_bytes()).hexdigest()
    assert record['ag_version'] and record['complete'] is True
    assert record['end_evidence']['observations'][0]['at'] == 1000
    assert record['end_evidence']['observations'][1]['at'] == 1300
    assert record['outputs']['water.log']['sha256'] == sha256(fake.files['water.log']).hexdigest()
    assert fetch.incomplete_record(path)[1] == record
    for kwargs in ({'incomplete': True}, {}, {'add_missing': True}):
        with pytest.raises(FileExistsError, match='record already exists'):
            fetch.fetch(cfg, path, fake, **kwargs)
    assert fake.downloaded == ['water.log']


@pytest.mark.parametrize('value', ['unknown', 'submitting', 'running', 'submitted', 'stalled',
                                   'awaiting_second_observation', 'finished', 'fetched'])
def test_pbs_reject_other_states(cfg, interrupted, value):
    path, _, fake = interrupted
    current = state.read(path)
    current['state'] = value
    (path / 'status.json').write_text(json.dumps(current))
    fake.calls.clear()
    with pytest.raises(ValueError, match='requires interrupted'):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert not fake.calls
    assert_unpublished(path)


@pytest.mark.parametrize('failure', ['one', 'too_soon', 'changed', 'Q', 'R', 'E', 'receipt', 'ssh',
                                    'bad_job', 'future'])
def test_pbs_end_evidence_refusal(cfg, interrupted, failure):
    path, manifest, fake = interrupted
    current = state.read(path)
    if failure == 'one':
        current['incomplete_observations'].pop()
    elif failure == 'too_soon':
        current['incomplete_observations'][-1]['at'] = 1299
    elif failure == 'changed':
        current['incomplete_observations'][0]['outputs']['water.log']['size'] += 1
    elif failure in ('Q', 'R', 'E'):
        fake.queue = Result(stdout=job_text(manifest, state_=failure))
    elif failure == 'receipt':
        fake.receipt = json.dumps(dict(PBS_JOBID='123.fixture', finished_at='2026-01-01T00:00:00Z', returncode=0))
    elif failure == 'ssh':
        fake.failure = 'jobs'
    elif failure == 'bad_job':
        current['incomplete_observations'][0]['job_id'] = '456.fixture'
    elif failure == 'future':
        current['incomplete_observations'][-1]['at'] = 2000
    (path / 'status.json').write_text(json.dumps(current))
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert_unpublished(path)


def test_status_resets_evidence_when_output_changes_or_job_reappears(cfg, interrupted, monkeypatch):
    path, manifest, fake = interrupted
    fake.files['water.log'] += b'changed'
    result = observe(cfg, path, fake, monkeypatch, 1400)
    assert len(result['incomplete_observations']) == 1
    assert result['incomplete_observations'][0]['at'] == 1400
    fake.queue = Result(stdout=job_text(manifest, state_='R'))
    result = observe(cfg, path, fake, monkeypatch, 1450)
    assert result['state'] == 'running' and result['incomplete_observations'] == []
    fake.queue = Result(153)
    observe(cfg, path, fake, monkeypatch, 1600)
    result = observe(cfg, path, fake, monkeypatch, 1660)
    assert result['state'] == 'interrupted'
    with pytest.raises(ValueError, match='300 seconds'):
        fetch.fetch(cfg, path, fake, incomplete=True)


@pytest.mark.parametrize('failure', ['corrupt', 'change', 'appear', 'ssh', 'late_change', 'active'])
def test_no_publication_on_download_failure(cfg, interrupted, failure):
    path, manifest, fake = interrupted
    if failure == 'corrupt':
        fake.corrupt = True
    elif failure == 'change':
        fake.after_download = lambda: fake.files.update({'water.log': b'changed'})
    elif failure == 'appear':
        fake.after_download = lambda: fake.files.update({'job.pbs.out': b'new'})
    elif failure == 'ssh':
        fake.after_download = lambda: setattr(fake, 'failure', 'metadata')
    elif failure == 'active':
        fake.after_download = lambda: setattr(fake, 'queue', Result(stdout=job_text(manifest, state_='R')))
    else:
        # Same-size replacement is invisible to size+mtime, but not SHA-256.
        fake.after_download = lambda: fake.files.update({'water.log': b'x' * len(fake.files['water.log'])})
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert_unpublished(path)
    assert list((path / 'outputs/.partial').rglob('water.log'))


def test_unverifiable_is_not_missing(cfg, interrupted):
    path, _, fake = interrupted
    fake.failure = 'output_observation'
    with pytest.raises(TransportError, match='Cannot verify.*无法核实'):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert_unpublished(path)
    assert fake.downloaded == []


@pytest.fixture
def slurm_finished(multi, tmp_path):
    path, manifest = prepare(multi, tmp_path)
    state.write(path, 'submitting')
    submission.record(path, manifest, '123')
    state.write(path, 'submitted', job_id='batch:123')
    state.write(path, 'finished')
    return path, manifest, IncompleteFake(manifest)


@pytest.mark.parametrize('terminal', ['TIMEOUT', 'CANCELLED', 'FAILED', 'OUT_OF_MEMORY', 'NODE_FAIL', 'COMPLETED'])
@pytest.mark.parametrize('purged', [False, True])
def test_slurm_terminal_with_missing_outputs(multi, slurm_finished, terminal, purged):
    path, _, fake = slurm_finished
    fake.accounting_state = terminal
    if purged:
        fake.slurm_queue = Result(1, stderr='squeue: error: Invalid job id specified\n')
    before = (path / 'status.json').read_bytes()
    result = fetch.fetch(multi, path, fake, incomplete=True)
    assert result['missing'] == ['job.slurm.out', 'job.slurm.err']
    assert (path / 'status.json').read_bytes() == before
    assert fetch.incomplete_record(path)[1]['end_evidence']['accounting']['state'] == terminal
    queries = [c for c in fake.calls if c.operation in ('slurm_jobs', 'slurm_accounting')]
    assert [c.operation for c in queries] == ['slurm_jobs', 'slurm_accounting'] * 2
    assert all(' -j 123 ' in c.text for c in queries)
    assert fake.downloaded == ['water.log']
    assert (path / 'outputs/water.log').read_bytes() == fake.files['water.log']
    with pytest.raises(FileExistsError, match='record already exists'):
        fetch.fetch(multi, path, fake, incomplete=True)
    assert fake.downloaded == ['water.log']


@pytest.mark.parametrize('failure', ['active', 'nonterminal', 'complete_all', 'ssh', 'cancelled'])
def test_slurm_refuses_without_terminal_evidence(multi, slurm_finished, failure):
    path, manifest, fake = slurm_finished
    if failure == 'active':
        fake.slurm_queue = Result(stdout=f"123|{manifest['attempt_id']}|fixture|RUNNING|8|00:00|fixture\n")
    elif failure == 'nonterminal':
        fake.accounting_state = 'RUNNING'
    elif failure == 'complete_all':
        fake.accounting_state = 'COMPLETED'
        fake.files.update({'job.slurm.out': b'', 'job.slurm.err': b''})
    elif failure == 'ssh':
        fake.failure = 'slurm_accounting'
    else:
        current = state.read(path)
        current['state'] = 'cancelled'
        (path / 'status.json').write_text(json.dumps(current))
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(multi, path, fake, incomplete=True)
    assert_unpublished(path)


def test_local_collision_rolls_back_own_links_keeps_stage(cfg, interrupted, monkeypatch):
    path, _, fake = interrupted
    original = fetch.os.link
    def collide(source, target):
        if Path(target).name.startswith('fetch-incomplete-'):
            raise FileExistsError('synthetic record collision')
        return original(source, target)
    monkeypatch.setattr(fetch.os, 'link', collide)
    with pytest.raises(FileExistsError):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert_unpublished(path)
    assert list((path / 'outputs/.partial').rglob('water.log'))


@pytest.mark.parametrize('case', ['parent_000', 'absent', 'file_000', 'symlink', 'parent_symlink', 'no_parent'])
def test_strict_command_permissions_and_absence(cfg, prepared, case):
    if os.geteuid() == 0:
        pytest.skip('Permission test requires unprivileged user')
    _, manifest = prepared
    # Resolve macOS temporary-root symlinks; test only intentionally added links.
    cfg['remote'] = {k: str(Path(v).resolve()) for k, v in cfg['remote'].items()}
    directory = Path(remote.attempt_dir(cfg, manifest))
    directory.mkdir(parents=True)
    target = directory / 'water.log'
    target.write_text('synthetic water output')
    if case == 'parent_000':
        directory.chmod(0)
    elif case == 'file_000':
        target.chmod(0)
    elif case == 'symlink':
        target.unlink()
        target.symlink_to(directory / 'absent')
    elif case == 'parent_symlink':
        saved = directory.with_name('saved')
        directory.rename(saved)
        directory.symlink_to(saved, target_is_directory=True)
    elif case in ('absent', 'no_parent'):
        target.unlink()
        if case == 'no_parent':
            directory.rmdir()
    try:
        result = subprocess.run(['sh', '-c', remote.incomplete_output_observation(cfg, manifest, 'water.log').text],
                                capture_output=True, text=True)
        if case == 'absent':
            assert result.returncode == 0 and result.stdout == 'absent\n'
        else:
            assert result.returncode != 0 and 'absent' not in result.stdout
    finally:
        if case == 'parent_000':
            directory.chmod(0o700)
        if case == 'file_000':
            target.chmod(0o600)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='remote stat uses GNU/Linux format')
def test_strict_command_present_gnu_stat(cfg, prepared):
    _, manifest = prepared
    directory = Path(remote.attempt_dir(cfg, manifest))
    directory.mkdir(parents=True)
    (directory / 'water.log').write_bytes(b'water')
    fake = type('Local', (), {'run': lambda self, command: Result(*(
        lambda p: (p.returncode, p.stdout, p.stderr))(
        subprocess.run(['sh', '-c', command.text], capture_output=True, text=True)))})()
    observed = fetch._presence(cfg, manifest, fake)
    assert observed['water.log']['size'] == 5 and observed['job.pbs.out'] is None


def test_parent_requires_valid_record_and_preserves_checks(cfg, interrupted):
    path, manifest, fake = interrupted
    with pytest.raises(ValueError, match='finished or fetched'):
        parent_chk._parent(cfg, path.name, 'water.chk')
    fetch.fetch(cfg, path, fake, incomplete=True)
    assert parent_chk._parent(cfg, path.name, 'water.chk')[0] == manifest
    with pytest.raises(ValueError, match='same cluster'):
        parent_chk._parent({**cfg, '_cluster': 'other'}, path.name, 'water.chk')
    with pytest.raises(ValueError, match='differs'):
        parent_chk._parent(cfg, path.name, 'other.chk')
    (path / 'outputs/water.log').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='differs from record'):
        parent_chk._parent(cfg, path.name, 'water.chk')


def test_empty_record_does_not_unlock_parent(cfg, interrupted):
    path, _, _ = interrupted
    (path / 'fetch-incomplete-empty.json').write_text('{}')
    with pytest.raises(ValueError, match='binding mismatch'):
        parent_chk._parent(cfg, path.name, 'water.chk')


@pytest.mark.parametrize('scheduler_name,message', [
    ('job.pbs.out', 'walltime 301 exceeded limit 300'),
    ('job.slurm.err', 'CANCELLED DUE TO TIME LIMIT'),
    ('job.slurm.out', 'CANCELLED DUE TO TIME LIMIT'),
    (None, None),
])
def test_facts_and_downstream_reject_incomplete(cfg, interrupted, multi, slurm_finished,
                                               scheduler_name, message, monkeypatch):
    path, manifest, fake = slurm_finished if scheduler_name and 'slurm' in scheduler_name else interrupted
    selected_cfg = multi if manifest.get('scheduler') == 'slurm' else cfg
    # A complete-looking old segment cannot certify an incompletely collected job.
    complete = (' Step number 1\n'
                '         Item               Value     Threshold  Converged?\n'
                ' Maximum Force 0.0 0.001 YES\n RMS Force 0.0 0.001 YES\n'
                ' Maximum Displacement 0.0 0.001 YES\n RMS Displacement 0.0 0.001 YES\n'
                ' Optimization completed.\n Normal termination of Gaussian\n')
    fake.files['water.log'] = (LOG + complete).encode()
    if scheduler_name:
        fake.files[scheduler_name] = message.encode()
    if manifest.get('scheduler') != 'slurm':
        # Produce fresh observations for the new synthetic bytes.
        observe(cfg, path, fake, monkeypatch, 2000)
        observe(cfg, path, fake, monkeypatch, 2300)
    fetch.fetch(selected_cfg, path, fake, incomplete=True)
    result = facts.build_facts(path)
    assert result['termination'] == 'incomplete'
    assert result['opt_converged'] is not True
    assert result['incomplete_fetch']['record']
    assert (path / 'final_input.xyz').is_file()
    if message:
        assert result['error_hint'] == 'walltime'
        assert result['error_hint_sources'] == [scheduler_name]
    from ag.thermo import calculate_thermo
    with pytest.raises(ValueError, match='requires normal termination'):
        calculate_thermo([path])
    from ag._profile_sources import attempt_facts
    for cached in (False, True):
        with pytest.raises(ValueError, match='non-normal termination'):
            attempt_facts(path.parent.parent, path.name, cached=cached)


def test_cli_option(cfg, interrupted, monkeypatch, capsys):
    path, _, fake = interrupted
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: fake)
    assert cli.main(['fetch', path.name, '--incomplete', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'interrupted'
    with pytest.raises(SystemExit):
        cli.main(['fetch', path.name, '--incomplete', '--add-missing'])


def test_first_ssh_failure_stops_and_read_only_enforcement_remains(cfg, interrupted, monkeypatch):
    from ag.transport import SSHTransport
    # This subclass intentionally overrides an internal hook. A rename must
    # fail here even if the replacement happens to avoid retries on this path.
    assert callable(SSHTransport.__dict__.get('_perform'))
    path, _, _ = interrupted
    calls = []
    def fail(self, argv, timeout):
        calls.append(argv)
        return Result(255, stderr='synthetic SSH failure')
    monkeypatch.setattr(SSHTransport, '_execute', fail)
    monkeypatch.setattr('ag.transport.time.sleep', lambda *a: pytest.fail('must not retry'))
    transport = SSHTransport(config.for_manifest(cfg, attempt.read_manifest(path)), read_only=True)
    with pytest.raises(TransportError, match='无法核实'):
        fetch.fetch(cfg, path, transport, incomplete=True)
    assert len(calls) == 1
    strict = fetch._IncompleteSSHTransport(transport.cfg)
    assert strict.read_only is True
    with pytest.raises(ValueError, match='refuses remote writes'):
        strict.run(remote.cancel('123.fixture'))
    with pytest.raises(ValueError, match='refuses uploads'):
        strict.upload(path / 'inputs/water.gjf', attempt.read_manifest(path), 'water.gjf')
    assert len(calls) == 1
    assert_unpublished(path)


def test_first_download_ssh_failure_does_not_retry(cfg, prepared, tmp_path, monkeypatch):
    from test_fetch import fake_scp
    _, manifest = prepared
    clock = fake_scp(monkeypatch, [dict(duration=1, returncode=255)])
    transport = fetch._IncompleteSSHTransport(config.for_manifest(cfg, manifest))
    with pytest.raises(TransportError):
        transport.download(manifest, 'water.log', tmp_path / 'download.log')
    assert len(clock.processes) == 1 and clock.sleeps == [] and not (tmp_path / 'download.log').exists()


def test_facts_partial_opt_and_last_geometry(cfg, interrupted):
    path, _, fake = interrupted
    fetch.fetch(cfg, path, fake, incomplete=True)
    result = facts.build_facts(path)
    assert result['termination'] == 'incomplete'
    assert result['opt_converged'] is not True
    assert result['final_geometry'] == 'final.xyz'
    assert result['final_input_geometry'] == 'final_input.xyz'


def test_existing_and_racing_local_files_preserved(cfg, interrupted):
    path, _, fake = interrupted
    target = path / 'outputs/water.log'
    fake.after_download = lambda: target.write_bytes(b'concurrent')
    with pytest.raises(FileExistsError):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert target.read_bytes() == b'concurrent'
    assert not list(path.glob('fetch-incomplete-*.json'))
    fake.calls.clear()
    with pytest.raises(FileExistsError):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert fake.calls == []


def test_slurm_final_accounting_must_match(multi, slurm_finished):
    path, _, fake = slurm_finished
    fake.after_download = lambda: setattr(fake, 'accounting_state', 'FAILED')
    with pytest.raises(ValueError, match='accounting changed'):
        fetch.fetch(multi, path, fake, incomplete=True)
    assert_unpublished(path)


def test_no_program_log_yields_only_incomplete_source_facts(cfg, interrupted, monkeypatch):
    path, _, fake = interrupted
    fake.files = {}
    observe(cfg, path, fake, monkeypatch, 2000)
    observe(cfg, path, fake, monkeypatch, 2300)
    result = fetch.fetch(cfg, path, fake, incomplete=True)
    assert result['files'] == []
    parsed = facts.build_facts(path)
    assert parsed['termination'] == 'incomplete'
    assert parsed['final_geometry'] is None and parsed['opt_converged'] is None
    assert set(parsed['incomplete_fetch']['missing']) == {'water.log', 'job.pbs.out'}
    from ag.thermo import calculate_thermo
    with pytest.raises(ValueError, match='requires normal termination'):
        calculate_thermo([path])


@pytest.mark.parametrize('scheduler_name', ['job.pbs.out', 'job.slurm.err', 'job.slurm.out'])
@pytest.mark.parametrize('tail,expected', [
    (' Normal termination of Gaussian\n', 'normal'),
    ('', 'incomplete'),
    (' Error termination via Lnk1e in PATH/l502.exe\n', 'error'),
])
@pytest.mark.parametrize('message', ['Resource summary: walltime 10, limit 300',
                                     'walltime exceeded limit; DUE TO TIME LIMIT'])
def test_scheduler_walltime_hint_preserves_log_termination(
        prepared, slurm_finished, scheduler_name, tail, expected, message):
    # No incomplete-fetch record: normal, partial and error logs retain their
    # own termination, even with the broad resource-summary walltime match.
    path, _ = prepared if scheduler_name == 'job.pbs.out' else slurm_finished[:2]
    (path / 'outputs/water.log').write_text(LOG + tail)
    baseline, baseline_geometry = facts.parse_facts(path)
    (path / 'outputs' / scheduler_name).write_text(message)
    parsed, geometry = facts.parse_facts(path)
    assert parsed['termination'] == baseline['termination'] == expected
    assert parsed['error_hint'] == 'walltime'
    assert parsed['error_hint_sources'] == [scheduler_name]
    assert parsed['opt_converged'] == baseline['opt_converged']
    assert geometry == baseline_geometry


def test_fetch_lock_is_staged_and_excluded_from_review_manifest(cfg, interrupted):
    from ag._review_manifest import create
    path, _, fake = interrupted
    fetch.fetch(cfg, path, fake, incomplete=True)
    facts.build_facts(path)
    assert not (path / '.fetch-incomplete.lock').exists()
    lock = path / 'outputs/.partial/.fetch-incomplete.lock'
    assert lock.is_file()
    result = create(path.parent.parent)
    selected = {entry['path'] for entry in result['files']}
    assert (path / 'facts.json').relative_to(path.parent.parent).as_posix() in selected
    assert lock.relative_to(path.parent.parent).as_posix() not in selected
    assert all('.partial' not in name for name in selected)


@pytest.mark.parametrize('late', [False, True])
@pytest.mark.parametrize('failure', ['empty', 'duplicate', 'job', 'owner', 'name',
                                    'running', 'pending', 'error', 'ssh'])
def test_slurm_purged_requires_matching_terminal_accounting(multi, slurm_finished, failure, late):
    path, manifest, fake = slurm_finished
    fake.slurm_queue = Result(1, stderr='squeue: error: Invalid job id specified\n')
    row = f"123|{manifest['attempt_id']}|fixture|TIMEOUT|1:9|00:05:00|8\n"
    bad = {
        'empty': Result(),
        'duplicate': Result(stdout=row * 2),
        'job': Result(stdout=row.replace('123|', '456|')),
        'owner': Result(stdout=row.replace('|fixture|', '|other|')),
        'name': Result(stdout=row.replace(manifest['attempt_id'], 'water-other')),
        'running': Result(stdout=row.replace('TIMEOUT', 'RUNNING')),
        'pending': Result(stdout=row.replace('TIMEOUT', 'PENDING')),
        'error': Result(1, stderr='sacct: accounting unavailable'),
        'ssh': Result(255, stderr='synthetic SSH failure'),
    }[failure]
    if late:
        fake.after_download = lambda: setattr(fake, 'accounting', bad)
    else:
        fake.accounting = bad
    before = (path / 'status.json').read_bytes()
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(multi, path, fake, incomplete=True)
    assert_unpublished(path)
    assert (path / 'status.json').read_bytes() == before
    operations = [c.operation for c in fake.calls]
    assert operations.count('slurm_jobs') == operations.count('slurm_accounting') == (2 if late else 1)
    assert fake.downloaded == (['water.log'] if late else [])


@pytest.mark.parametrize('late', [False, True])
@pytest.mark.parametrize('queue', [
    Result(1, stderr='squeue: controller unavailable'),
    Result(1, stdout='Invalid job id specified'),
    Result(1, stderr='squeue: Invalid job id'),
    Result(255, stderr='synthetic SSH failure'),
    Result(255, stderr='Invalid job id specified'),
    Result(stdout='invalid queue output', stderr='Invalid job id specified'),
])
def test_slurm_queue_errors_never_enable_fetch(multi, slurm_finished, queue, late):
    path, _, fake = slurm_finished
    if late:
        fake.after_download = lambda: setattr(fake, 'slurm_queue', queue)
    else:
        fake.slurm_queue = queue
    before = (path / 'status.json').read_bytes()
    with pytest.raises((ValueError, TransportError)):
        fetch.fetch(multi, path, fake, incomplete=True)
    assert_unpublished(path)
    assert (path / 'status.json').read_bytes() == before
    operations = [c.operation for c in fake.calls]
    assert operations.count('slurm_jobs') == (2 if late else 1)
    assert operations.count('slurm_accounting') == (1 if late else 0)
    assert fake.downloaded == (['water.log'] if late else [])


@pytest.mark.parametrize('failure', ['exit255', 'exception'])
def test_slurm_exact_query_ssh_failure_never_retries(multi, slurm_finished, monkeypatch, failure):
    from ag.transport import SSHConnectionError, SSHTransport
    path, manifest, fake = slurm_finished
    selected = config.for_manifest(multi, manifest)
    commands = []
    def execute(self, argv, timeout):
        command = argv[-1]
        commands.append(command)
        if command == remote.slurm_jobs('123').text:
            if failure == 'exception':
                raise SSHConnectionError('synthetic connection failure')
            return Result(255, stderr='Invalid job id specified')
        if command == remote.identity().text:
            return Result(stdout='fixture\n')
        for name in remote.output_names(manifest):
            if command == remote.incomplete_output_observation(selected, manifest, name).text:
                return fake.run(remote.incomplete_output_observation(selected, manifest, name))
        pytest.fail('unexpected command after failed exact query')
    monkeypatch.setattr(SSHTransport, '_execute', execute)
    monkeypatch.setattr('ag.transport.time.sleep', lambda *a: pytest.fail('must not retry'))
    before = (path / 'status.json').read_bytes()
    with pytest.raises(TransportError):
        fetch.fetch(multi, path, SSHTransport(selected, read_only=True), incomplete=True)
    assert commands.count(remote.slurm_jobs('123').text) == 1
    assert remote.slurm_accounting('123').text not in commands
    assert (path / 'status.json').read_bytes() == before
    assert_unpublished(path)


@pytest.fixture
def cancelled(request, cfg, multi, prepared, tmp_path, monkeypatch):
    kind = getattr(request, 'param', 'pbs')
    if kind == 'pbs':
        path, manifest = prepared
        selected = cfg
        state.write(path, 'submitting')
        seed_submission(path)
    else:
        path, manifest = prepare(multi, tmp_path)
        selected = multi
        state.write(path, 'submitting')
        submission.record(path, manifest, '123')
        state.write(path, 'submitted', job_id='batch:123')
    fake = IncompleteFake(manifest)
    fake.accounting_state = 'CANCELLED'
    monkeypatch.setattr(cancel.confirm, 'confirm', lambda *a: True)
    assert cancel.cancel(selected, path, fake)['state'] == 'cancelled'
    if kind == 'pbs':
        assert observe(selected, path, fake, monkeypatch, 1000)['state'] == 'cancelled'
        assert observe(selected, path, fake, monkeypatch, 1300)['state'] == 'cancelled'
    fake.calls.clear()
    return selected, path, manifest, fake


@pytest.mark.parametrize('cancelled', ['pbs', 'slurm'], indirect=True)
def test_cancelled_fetch_binds_outputs_and_preserves_state(cancelled):
    cfg, path, manifest, fake = cancelled
    before = (path / 'status.json').read_bytes()
    result = fetch.fetch(cfg, path, fake, incomplete=True)
    assert result['state'] == 'cancelled' and result['files'] == ['water.log']
    assert (path / 'status.json').read_bytes() == before
    _, record = fetch.incomplete_record(path)
    assert record['complete'] is True
    assert record['manifest_sha256'] == sha256((path / 'manifest.json').read_bytes()).hexdigest()
    assert record['job_id'] == submission.verified_job(path, manifest, state.read(path))
    assert record['outputs']['water.log']['sha256'] == sha256(fake.files['water.log']).hexdigest()
    if manifest['scheduler'] == 'slurm':
        assert record['end_evidence']['accounting']['state'] == 'CANCELLED'
    else:
        first, last = record['end_evidence']['observations']
        assert last['at'] - first['at'] == 300 and first['outputs'] == last['outputs']
    for options in ({'incomplete': True}, {}, {'add_missing': True}):
        with pytest.raises(FileExistsError):
            fetch.fetch(cfg, path, fake, **options)
    assert fake.downloaded == ['water.log']


@pytest.mark.parametrize('failure', ['claim', 'claim_symlink', 'succeeded', 'wrong_attempt',
                                    'job', 'cluster', 'binding', 'journal_missing', 'malformed'])
@pytest.mark.parametrize('cancelled', ['pbs', 'slurm'], indirect=True)
def test_cancelled_local_proof_required_before_remote_calls(cancelled, failure):
    cfg, path, manifest, fake = cancelled
    log = path.parent.parent / 'journal.jsonl'
    if failure in ('claim', 'claim_symlink'):
        (path / '.cancel-claim').unlink()
        if failure == 'claim_symlink':
            (path / '.cancel-claim').symlink_to(path / 'status.json')
    elif failure == 'binding':
        value = json.loads((path / 'submission.json').read_text())
        value['manifest_sha256'] = '0' * 64
        (path / 'submission.json').write_text(json.dumps(value))
    elif failure == 'journal_missing':
        log.unlink()
    elif failure == 'malformed':
        log.write_text('invalid journal\n')
    else:
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        row = next(r for r in rows if r['action'] == 'cancel' and r['result'] == 'succeeded')
        if failure == 'succeeded':
            row['result'] = 'failed_or_unknown'
        elif failure == 'wrong_attempt':
            row['attempt_id'] = 'water-999-other'
        else:
            row['detail']['job_id'] = ('other:' if failure == 'cluster' else '') + '456'
        log.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with pytest.raises(ValueError):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert fake.calls == []
    assert_unpublished(path)


@pytest.mark.parametrize('failure', ['receipt', 'active', 'changed', 'hash', 'ssh'])
@pytest.mark.parametrize('late', [False, True])
@pytest.mark.parametrize('cancelled', ['pbs', 'slurm'], indirect=True)
def test_cancelled_rechecks_end_evidence_and_hashes(cancelled, failure, late):
    cfg, path, manifest, fake = cancelled
    def change():
        if failure == 'receipt':
            key = 'job_id' if manifest['scheduler'] == 'slurm' else 'PBS_JOBID'
            fake.receipt = json.dumps({key: submission.verified_job(path, manifest, state.read(path)),
                                      'finished_at': '2026-01-01T00:00:00Z', 'returncode': 0})
        elif failure == 'active':
            fake.queue = Result(stdout=job_text(manifest, state_='R'))
            fake.slurm_queue = Result(stdout=f"123|{manifest['attempt_id']}|fixture|RUNNING|8|00:00|fixture\n")
        elif failure == 'ssh':
            fake.failure = 'metadata' if late else 'receipt'
        elif failure == 'hash':
            if late:
                fake.files['water.log'] = b'x' * len(fake.files['water.log'])
            else:
                fake.corrupt = True
        else:
            fake.files['water.log'] += b'changed'
    # For Slurm there is no stored size observation; mutate during download.
    if failure == 'changed' and manifest['scheduler'] == 'slurm' and not late:
        fake.after_download = change
    elif late:
        fake.after_download = change
    else:
        change()
    before = (path / 'status.json').read_bytes()
    with pytest.raises((ValueError, TransportError)) as error:
        fetch.fetch(cfg, path, fake, incomplete=True)
    if failure == 'receipt':
        assert 'ordinary status/fetch' in str(error.value)
    assert (path / 'status.json').read_bytes() == before
    assert_unpublished(path)


@pytest.mark.parametrize('failure', ['one', 'too_soon', 'changed_size', 'changed_mtime', 'bad_job', 'future'])
def test_cancelled_pbs_requires_two_stable_observations(cancelled, failure):
    cfg, path, manifest, fake = cancelled
    current = state.read(path)
    observations = current['incomplete_observations']
    if failure == 'one':
        observations.pop()
    elif failure == 'too_soon':
        observations[1]['at'] = 1299
    elif failure == 'changed_size':
        observations[0]['outputs']['water.log']['size'] += 1
    elif failure == 'changed_mtime':
        observations[0]['outputs']['water.log']['mtime'] = '2026-01-02 00:00:00 +0000'
    elif failure == 'bad_job':
        observations[0]['job_id'] = '456.fixture'
    else:
        observations[1]['at'] = 1400
    (path / 'status.json').write_text(json.dumps(current))
    with pytest.raises(ValueError, match='PBS requires'):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert fake.downloaded == []
    assert_unpublished(path)


def test_cancelled_pbs_status_resets_evidence_and_keeps_lifecycle(cancelled, monkeypatch):
    cfg, path, manifest, fake = cancelled
    fake.files['water.log'] += b'new'
    changed = observe(cfg, path, fake, monkeypatch, 1400)
    assert changed['state'] == 'cancelled' and len(changed['incomplete_observations']) == 1
    fake.queue = Result(stdout=job_text(manifest, state_='R'))
    active = observe(cfg, path, fake, monkeypatch, 1500)
    assert active['state'] == 'cancelled' and active['incomplete_observations'] == []
    fake.queue = Result(stdout=job_text(manifest, state_='C'))
    observe(cfg, path, fake, monkeypatch, 1600)
    stable = observe(cfg, path, fake, monkeypatch, 1900)
    assert stable['state'] == 'cancelled' and len(stable['incomplete_observations']) == 2
    assert fetch.fetch(cfg, path, fake, incomplete=True)['state'] == 'cancelled'


def test_cancelled_pbs_receipt_returns_to_normal_status_fetch(cancelled, monkeypatch):
    cfg, path, manifest, fake = cancelled
    fake.files['job.pbs.out'] = b'done'
    fake.receipt = json.dumps(dict(PBS_JOBID='123.fixture', finished_at='2026-01-01T00:00:00Z', returncode=0))
    result = observe(cfg, path, fake, monkeypatch, 1400)
    assert result['state'] == 'finished' and result['incomplete_observations'] == []
    assert fetch.fetch(cfg, path, fake)['state'] == 'fetched'
