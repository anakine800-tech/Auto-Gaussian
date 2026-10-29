"""T84: synthetic logs, fake transports and Linux-only local shell checks."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from ag import attempt, cli, config, facts, fetch, remote, snapshot, state, submission, transport
from ag import _review_manifest as inventory
from ag.transport import Result, SSHConnectionError, SSHTransport, TransportError
from test_core import cfg, prepared, seed_submission  # noqa: F401
from test_fetch import ReadOnlyFake, snapshot as files_before, unchanged
from test_incomplete_fetch import LOG
from test_slurm import multi, prepare as prepare_cluster  # noqa: F401


TABLE = ('         Item               Value     Threshold  Converged?\n'
         ' Maximum Force            0.000020     0.000450     YES\n'
         ' RMS     Force            0.000010     0.000300     YES\n'
         ' Maximum Displacement     0.000200     0.001800     YES\n'
         ' RMS     Displacement     0.000100     0.001200     YES\n')
PROGRESS = (LOG + ' Step number   1 out of a maximum of 20\n' + TABLE.replace('YES', 'NO') +
            ' SCF Done: E(RHF) = -75.123D+00 A.U.\n Step number   2 out of a maximum of 20\n' +
            TABLE + ' Harmonic frequencies (cm**-1)\n Normal termination of Gaussian\n'
            ' Error termination via Lnk1e\n').encode()


def response(data, limit):
    return Result(stdout=f'{len(data)}\n1790000000\n' + base64.b64encode(data[-limit:]).decode() + '\n')


class Fake:
    def __init__(self, data=PROGRESS, limit=snapshot.DEFAULT_MAX_BYTES):
        self.reply = response(data, limit)
        self.calls = []
        self.record_paths = None
        self.selected = None

    def for_cluster(self, cfg):
        self.selected = cfg['_cluster']
        return self

    def record_to(self, paths):
        self.record_paths = paths

    def run(self, command):
        assert command.operation == 'output_observation'
        self.calls.append(command)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def running(prepared):
    path, manifest = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    state.write(path, 'running')
    return path, manifest


def test_snapshot_preserves_lifecycle_and_reports_progress(cfg, running):
    path, _ = running
    before = files_before(path.parent.parent)
    fake = Fake()
    result = snapshot.capture(cfg, path, fake)
    unchanged(before)
    assert fake.record_paths == [] and len(fake.calls) == 1
    directory = path / result['snapshot']
    assert directory.parent == path / 'snapshots'
    assert directory.name.endswith('Z')
    assert {p.name for p in directory.iterdir()} == {'water.log', 'snapshot.json'}
    assert (directory / 'water.log').read_bytes() == PROGRESS
    assert json.loads((directory / 'snapshot.json').read_text()) == result
    assert result['sha256'] == sha256(PROGRESS).hexdigest()
    assert result['read_bytes'] == result['remote_size'] == len(PROGRESS)
    assert result['latest_status'] == {k: state.read(path)[k] for k in ('state', 'updated_at')}
    assert result['job_id'] == '123.fixture' and result['cluster'] == 'default'
    assert result['notice'] == snapshot.NOTICE
    p = result['progress']
    assert p['scf_done_count'] == 2 and p['last_scf_energy_hartree'] == '-75.123D+00'
    assert p['optimization_step_count'] == 2 and p['last_step_number'] == 2
    assert p['last_convergence_table'] == TABLE.splitlines()[1:]
    assert p['convergence_table_complete'] and p['freq_started']
    assert p['last_termination'] == ' Error termination via Lnk1e'
    assert not list((path / 'outputs').iterdir()) and not (path / 'facts.json').exists()
    second = snapshot.capture(cfg, path, fake)
    assert second['snapshot'] != result['snapshot']
    assert len(list((path / 'snapshots').iterdir())) == 2
    assert (directory / 'water.log').read_bytes() == PROGRESS


def test_run_snapshot_uses_integrated_publication_and_registry_locks(cfg, running, monkeypatch):
    from contextlib import contextmanager
    import sys
    from types import ModuleType
    from ag import autonomy
    from test_autonomy import VERSIONS, spec

    path = running[0]
    name = path.parent.parent.name
    monkeypatch.setattr(autonomy, 'versions', lambda: dict(VERSIONS))
    autonomy.initialize(cfg, name)
    plan = autonomy.create_plan(cfg, name, spec(valid_until=autonomy.now() + 10000))
    autonomy.confirm(cfg, name, plan['plan_id'], plan['sha256'], 'Synthetic plan confirmation')
    autonomy.begin(cfg, name, plan['plan_id'], 'Synthetic round confirmation')
    run = autonomy.start(cfg, name, plan['plan_id'], 'synthetic-owner')
    active, entries = [False], []
    dependency = ModuleType('ag.autonomy_submission')

    @contextmanager
    def machine_lock(*, create):
        assert create is False and not active[0]
        active[0] = True
        entries.append('registry')
        try:
            yield
        finally:
            active[0] = False

    @contextmanager
    def publication(*args, **kwargs):
        with machine_lock(create=False), autonomy.action_guard(*args, **kwargs) as current:
            entries.append('publication')
            yield current['state']

    dependency.machine_lock = machine_lock
    monkeypatch.setitem(sys.modules, 'ag.autonomy_submission', dependency)
    monkeypatch.setattr(autonomy, 'observation_publication_guard', publication, raising=False)

    class OutsideLocks(Fake):
        def run(self, command):
            assert not active[0]
            return super().run(command)

    result = snapshot.capture_for_run(cfg, path, OutsideLocks(), run_id=run['run_id'],
                                      token=run['token'], plan_sha256=plan['sha256'])
    assert entries == ['registry', 'registry', 'publication', 'registry']
    saved = autonomy.status(cfg, name)['state']['snapshots']
    assert saved[path.name + '/' + result['snapshot']]['run_id'] == run['run_id']
    assert not active[0]


@pytest.mark.parametrize('data,limit', [(b'', 8), (b'abcdef', 6), (b'abcdef', 3),
                                      (b'\xff\r\n\x00\xe4\xb8\xad\npartial', 11)])
def test_byte_preserving_bounded_tail(cfg, running, data, limit):
    path, _ = running
    result = snapshot.capture(cfg, path, Fake(data, limit), max_bytes=limit)
    assert (path / result['snapshot'] / result['file']).read_bytes() == data[-limit:]
    assert result['truncated'] == (len(data) > limit)
    assert result['sha256'] == sha256(data[-limit:]).hexdigest()


def test_fragment_summary_does_not_treat_partial_lines_or_route_as_progress():
    p = snapshot.progress(b'SCF Done: E(RHF) = -99.0\n #p HF/STO-3G Freq\n', 'gaussian', truncated=True)
    assert p['scf_done_count'] == 0 and not p['freq_started']
    p = snapshot.progress((TABLE + TABLE.splitlines()[0] + '\n' + TABLE.splitlines()[1] + '\n').encode(), 'gaussian')
    assert not p['convergence_table_complete'] and len(p['last_convergence_table']) == 1


@pytest.mark.parametrize('program', ['xtb', 'crest'])
def test_primary_log_selection(cfg, tmp_path, program):
    from ag import study
    study.init(cfg, 'small')
    source = tmp_path / 'water.xyz'
    source.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    m = attempt.prepare(cfg, study_name='small', template=program, input_path=source,
                        tier='simple', walltime='00:10:00', label=program, method_basis='兜底方法：合成测试')
    path = attempt.find(cfg, m['attempt_id'])
    state.write(path, 'submitting')
    seed_submission(path)
    result = snapshot.capture(cfg, path, Fake(b'program output'))
    assert result['file'] == program + '.out'
    assert 'scf_done_count' not in result['progress']


@pytest.mark.parametrize('current', ['prepared', 'submitting', 'failed_presubmit', 'fetched', 'incomplete'])
def test_ineligible_attempt_never_contacts_remote(cfg, prepared, current):
    path, _ = prepared
    if current != 'prepared':
        state.write(path, 'submitting')
    if current == 'failed_presubmit':
        state.write(path, current)
    if current in ('fetched', 'incomplete'):
        seed_submission(path)
        state.write(path, 'finished')
        if current == 'fetched':
            state.write(path, 'fetched')
        else:
            (path / 'fetch-incomplete-fixture.json').write_text('{}')
    fake = Fake()
    before = files_before(path.parent.parent)
    with pytest.raises(ValueError, match='outputs/|submitted Attempt'):
        snapshot.capture(cfg, path, fake)
    unchanged(before)
    assert fake.calls == [] and not (path / 'snapshots').exists()


@pytest.mark.parametrize('failure', [Result(1), Result(255, stderr='synthetic SSH failure'),
                                   SSHConnectionError('synthetic timeout'), Result(stdout='absent\n'),
                                   Result(stdout='4\n1\nYQ=='), Result(stdout='1\n1\n@'),
                                   Result(stdout='1\n1\nYWI=')])
def test_failure_leaves_state_and_journal_untouched(cfg, running, failure):
    path, _ = running
    fake = Fake()
    fake.reply = failure
    before = files_before(path.parent.parent)
    with pytest.raises((ValueError, TransportError)):
        snapshot.capture(cfg, path, fake)
    unchanged(before)
    assert not (path / 'snapshots').exists() and fake.record_paths == []


def test_timestamp_collision_never_overwrites(cfg, running, monkeypatch):
    class FixedTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(snapshot, 'datetime', FixedTime)
    path, _ = running
    snapshot.capture(cfg, path, Fake())
    before = files_before(path.parent.parent)
    with pytest.raises(FileExistsError):
        snapshot.capture(cfg, path, Fake(b'changed'))
    unchanged(before)


def test_local_symlink_and_remote_escape_rejected(cfg, running, tmp_path):
    path, m = running
    (path / 'snapshots').symlink_to(tmp_path, target_is_directory=True)
    fake = Fake()
    with pytest.raises(ValueError, match='Symbolic links'):
        snapshot.capture(cfg, path, fake)
    assert fake.calls == []
    for remote_dir in ('../escape', '/escape', 'smoke/../escape'):
        with pytest.raises(ValueError, match='relative remote directory'):
            remote.log_snapshot(cfg, dict(m, remote_dir=remote_dir), 10)
    bad = deepcopy(cfg)
    bad['remote']['ag_root'] = str(tmp_path / 'safe/../escape')
    with pytest.raises(ValueError, match='escapes'):
        remote.log_snapshot(bad, m, 10)


@pytest.mark.parametrize('limit', [0, -1, True, 1.5, '1; evil', 2**63])
def test_invalid_limits_before_remote(cfg, running, limit):
    fake = Fake()
    with pytest.raises(ValueError, match='max-bytes'):
        snapshot.capture(cfg, running[0], fake, max_bytes=limit)
    assert fake.calls == []


def test_cli_selects_bound_cluster_and_accepts_study(multi, tmp_path, monkeypatch, capsys):
    path, m = prepare_cluster(multi, tmp_path)
    state.write(path, 'submitting')
    submission.record(path, m, '123')
    state.write(path, 'submitted', job_id='batch:123')
    fake = Fake(PROGRESS, 100)
    selected = []
    def make_transport(cfg, *, read_only):
        selected.append((cfg['_cluster'], read_only))
        return fake
    monkeypatch.setattr(cli, 'load_config', lambda: multi)
    monkeypatch.setattr(transport, 'SSHTransport', make_transport)
    assert cli.main(['snapshot', path.name, '--study', 'water', '--max-bytes', '100', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['cluster'] == 'batch' and result['job_id'] == '123' and result['truncated']
    assert selected == [('batch', True)] and fake.selected == 'batch'
    fake.reply = response(PROGRESS, snapshot.DEFAULT_MAX_BYTES)
    assert cli.main(['snapshot', path.name]) == 0
    assert snapshot.NOTICE in capsys.readouterr().out
    before = len(fake.calls)
    assert cli.main(['snapshot', '../bad', '--study', 'water', '--json']) == 1
    assert 'error' in json.loads(capsys.readouterr().out)
    assert len(fake.calls) == before


def test_submission_mismatch_is_refused(cfg, running):
    path, _ = running
    state.write(path, 'running', job_id='default:456.fixture')
    fake = Fake()
    with pytest.raises(ValueError, match='invalid local record'):
        snapshot.capture(cfg, path, fake)
    assert fake.calls == []


def test_fetch_facts_and_evidence_ignore_generated_snapshots(cfg, running, tmp_path):
    import shutil
    path, _ = running
    control = tmp_path / 'control' / path.parent.parent.name
    shutil.copytree(path.parent.parent, control)
    control_path = control / 'attempts' / path.name
    control_cfg = deepcopy(cfg)
    control_cfg['local']['studies_root'] = str(control.parent)
    snapshot.capture(cfg, path, Fake())
    # Even malformed snapshot metadata and a false SCF value cannot affect facts.
    (path / 'snapshots/irrelevant.json').write_text('{invalid')
    expected_files = {'water.log': (LOG + ' Normal termination of Gaussian\n').encode(), 'job.pbs.out': b''}
    results = []
    for selected, directory in ((cfg, path), (control_cfg, control_path)):
        state.write(directory, 'finished', exit_status=0)
        fake = ReadOnlyFake(expected_files)
        fetched = fetch.fetch(selected, directory, fake)
        parsed = facts.build_facts(directory)
        again = files_before(directory)
        assert facts.build_facts(directory) == parsed
        unchanged(again)
        evidence = inventory.create(directory.parent.parent)
        results.append((fetched['files'], parsed, evidence['files'], fake.calls))
        assert {p.name for p in (directory / 'outputs').iterdir() if p.is_file()} == set(expected_files)
        assert all('snapshots/' not in row['path'] for row in evidence['files'])
    assert results[0] == results[1]
    assert (path / 'outputs/water.log').read_bytes() == expected_files['water.log']


def test_transport_logs_read_operation_without_lifecycle_annotations(cfg, running, monkeypatch):
    path, m = running
    selected = config.for_manifest(cfg, m)
    live_class = SSHTransport(selected, read_only=True)
    live_class.record_to([path])  # capture must clear an inherited error target.
    before = files_before(path.parent.parent)
    monkeypatch.setattr(live_class, '_execute', lambda *a: response(PROGRESS, snapshot.DEFAULT_MAX_BYTES))
    snapshot.capture(cfg, path, live_class)
    unchanged(before)
    logs = list((Path(cfg['_config_dir']) / 'ssh-log').glob('*.jsonl'))
    row = json.loads(logs[0].read_text())
    assert row['operation'] == 'output_observation' and row['outcome'] == 'ok'
    assert set(row) == {'at', 'cluster', 'tool', 'operation', 'attempt', 'outcome', 'returncode', 'duration_s', 'error_class'}


def test_retried_ssh_error_records_only_transport_log(cfg, running, monkeypatch):
    path, m = running
    selected = config.for_manifest(cfg, m)
    ssh = SSHTransport(selected, read_only=True)
    ssh.record_to([path])
    monkeypatch.setattr(ssh, '_execute', lambda *a: Result(255, stderr='synthetic timeout'))
    monkeypatch.setattr(transport.time, 'sleep', lambda _: None)
    before = files_before(path.parent.parent)
    with pytest.raises(TransportError):
        snapshot.capture(cfg, path, ssh)
    unchanged(before)
    assert not (path / 'snapshots').exists()
    log = next((Path(cfg['_config_dir']) / 'ssh-log').glob('*.jsonl'))
    assert [json.loads(line)['returncode'] for line in log.read_text().splitlines()] == [255, 255]


def test_command_is_fixed_readonly_and_quoted(cfg, prepared):
    _, m = prepared
    ordinary = remote.log_snapshot(cfg, m, 12).text
    cfg['remote']['ag_root'] += "/with space ' $(false); literal"
    command = remote.log_snapshot(cfg, m, 12)
    q = shlex.quote(remote.attempt_dir(cfg, m) + '/water.log')
    assert command.operation in transport.READ_OPERATIONS
    assert command.text.startswith(remote.path_checks(remote.attempt_dir(cfg, m) + '/water.log'))
    assert command.text.endswith(') 3< ' + q)
    assert f"stat -c '%s %Y %d:%i' -- {q}" in command.text
    assert 'ag_start=$((ag_size - 12 + 1)); ag_count=12' in command.text
    assert 'tail -c +"$ag_start" -- /proc/self/fd/3 | head -c "$ag_count" | base64' in command.text
    assert 'job.pbs.out' not in command.text
    assert not any(token in shlex.split(ordinary) for token in ('>', '>>', 'tee', 'rm', 'cp', 'mv', 'mkdir', 'touch', 'chmod', 'python', 'qsub', 'sbatch'))
    assert subprocess.run(['sh', '-n'], input=command.text, text=True, capture_output=True).returncode == 0


LINUX = pytest.mark.skipif(sys.platform != 'linux', reason='Fixed remote command requires Linux procfs and GNU stat; Linux CI executes it')


@LINUX
@pytest.mark.parametrize('limit', [1, 7, 10000])
def test_real_local_shell_preserves_bytes_and_leaves_source(cfg, prepared, limit):
    _, m = prepared
    cfg['remote']['ag_root'] += "/space ' $(false); literal"
    directory = Path(remote.attempt_dir(cfg, m))
    directory.mkdir(parents=True)
    log = directory / 'water.log'
    data = b'prefix\r\n\xff\x00last line without newline'
    log.write_bytes(data)
    before = (log.read_bytes(), log.stat().st_mtime_ns)
    command = remote.log_snapshot(cfg, m, limit)
    result = subprocess.run(['sh', '-c', command.text], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    size, _, captured = snapshot._decode(result.stdout, limit)
    assert size == len(data) and captured == data[-limit:]
    assert (log.read_bytes(), log.stat().st_mtime_ns) == before
    assert list(directory.iterdir()) == [log]


@LINUX
@pytest.mark.parametrize('kind', ['missing', 'symlink', 'directory', 'fifo', 'linked-parent'])
def test_real_local_shell_refuses_unsafe_source(cfg, prepared, tmp_path, kind):
    import os
    _, m = prepared
    directory = Path(remote.attempt_dir(cfg, m))
    directory.mkdir(parents=True)
    log = directory / 'water.log'
    if kind == 'symlink':
        outside = tmp_path / 'outside'
        outside.write_bytes(b'private')
        log.symlink_to(outside)
    elif kind == 'directory':
        log.mkdir()
    elif kind == 'fifo':
        os.mkfifo(log)
    elif kind == 'linked-parent':
        directory.rmdir()
        directory.symlink_to(tmp_path, target_is_directory=True)
    result = subprocess.run(['sh', '-c', remote.log_snapshot(cfg, m, 5).text], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and not result.stdout


@LINUX
@pytest.mark.parametrize('replacement', ['symlink', 'regular'])
def test_replacement_between_stat_and_open_is_refused(cfg, prepared, tmp_path, replacement):
    _, m = prepared
    directory = Path(remote.attempt_dir(cfg, m))
    directory.mkdir(parents=True)
    log = directory / 'water.log'
    log.write_bytes(b'original')
    outside = tmp_path / 'other'
    outside.write_bytes(b'private')
    # Test-only shell hook replaces the file after initial metadata, before open.
    swap = (f'ln -s {shlex.quote(str(outside))} {shlex.quote(str(log))}' if replacement == 'symlink'
            else f'cp {shlex.quote(str(outside))} {shlex.quote(str(log))}')
    hook = f'mv {shlex.quote(str(log))} {shlex.quote(str(directory / "old"))} && {swap} && '
    command = remote.log_snapshot(cfg, m, 100).text.replace('( test', hook + '( test', 1)
    result = subprocess.run(['sh', '-c', command], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and not result.stdout


@LINUX
def test_append_after_stat_stays_within_initial_window(cfg, prepared):
    _, m = prepared
    directory = Path(remote.attempt_dir(cfg, m))
    directory.mkdir(parents=True)
    log = directory / 'water.log'
    log.write_bytes(b'1234567890')
    # Only the synthetic writer appends; the production command stays read-only.
    hook = f"printf 'more data' >> {shlex.quote(str(log))} && "
    command = remote.log_snapshot(cfg, m, 4).text.replace('( test', hook + '( test', 1)
    result = subprocess.run(['sh', '-c', command], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    size, _, data = snapshot._decode(result.stdout, 4)
    assert size == 10 and data == b'7890'
