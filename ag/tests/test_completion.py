"""Offline T1c regressions: receipts, stalled sessions, legacy completion and SSH."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from ag import attempt, cancel, fetch, remote, render, state, status, submit
from ag.transport import Result, SSHTransport, TransportError, redact_stderr
from test_core import cfg, prepared, Fake, allow, job_text, seed_submission


class ObservationFake(Fake):
    def __init__(self, cfg, manifest):
        super().__init__(cfg)
        self.manifest = manifest
        self.job = Result(stdout=job_text(manifest) + '    session_id = 321\n    resources_used.cput = 00:01:07\n')
        self.receipts = {}
        self.sizes = {name: 100 for name in remote.output_names(manifest)}
        self.mtime = '2026-01-01 00:00:00.000000001 +0000'
        self.ps = Result(1)
        self.marker = 'absent\n'
        self.fail_operation = None

    def run(self, command):
        op = command.operation
        if op == self.fail_operation:
            self.calls.append(command)
            return Result(255, '', 'synthetic connection failure')
        if op in ('receipt', 'output_observation', 'session_processes', 'completion_marker'):
            self.calls.append(command)
            if op == 'receipt':
                name = 'ag-start.json' if 'ag-start.json' in command.text else 'ag-exit.json'
                return Result(stdout=self.receipts.get(name, 'absent\n'))
            if op == 'output_observation':
                return Result(stdout=''.join(f'{name} {size} {self.mtime}\n' if size is not None
                                            else f'{name} absent\n' for name, size in self.sizes.items()))
            if op == 'session_processes':
                return self.ps
            return Result(stdout=self.marker)
        return super().run(command)


def submitted(prepared, cfg, legacy=False):
    p, m = prepared
    if legacy:
        m.pop('completion_receipts')
        (p / 'manifest.json').write_text(json.dumps(m))  # simulate a pre-T1c fixture
    state.write(p, 'submitting')
    seed_submission(p)
    return p, m, ObservationFake(cfg, m)


def exit_receipt(code=0, job='123.fixture'):
    return json.dumps({'PBS_JOBID': job, 'returncode': code, 'finished_at': '2026-01-01T00:00:00Z'})


@pytest.mark.parametrize('code', [0, 7, 137])
@pytest.mark.parametrize('scheduler', ['R', 'C', None])
def test_exit_receipt_finishes_even_with_pbs_r(cfg, prepared, code, scheduler):
    p, m, fake = submitted(prepared, cfg)
    fake.receipts['ag-exit.json'] = exit_receipt(code)
    fake.job = Result(stdout=job_text(m, state_=scheduler)) if scheduler else Result(153, '', 'qstat: Unknown Job Id')
    result = status.check(cfg, p, fake)
    assert result['state'] == 'finished' and result['exit_status'] == code
    assert result['scheduler_residue'] == (scheduler == 'R')
    assert result['completion_source'] == 'ag-exit.json'
    assert 'session_processes' not in fake.operations()
    assert 'cancel' not in fake.operations()
    fake.files = {'water.log': b'output', 'job.pbs.out': b'PBS output'}
    assert fetch.fetch(cfg, p, fake)['state'] == 'fetched'
    assert state.read(p)['scheduler_residue'] == (scheduler == 'R')


@pytest.mark.parametrize('receipt', [exit_receipt(job='999.fixture'), exit_receipt(True), exit_receipt(-1),
    '{', '{}', '[]', 'x' * 4097, '{"PBS_JOBID":"123.fixture","PBS_JOBID":"123.fixture"}',
    exit_receipt().replace('00:00:00Z', '00:00:00')])
def test_bad_receipt_never_completes(cfg, prepared, receipt):
    p, _, fake = submitted(prepared, cfg)
    fake.receipts['ag-exit.json'] = receipt
    with pytest.raises(ValueError):
        status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'


def test_running_stalled_elapsed_observations_and_recovery(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg)
    clock = [1000.0]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    first = status.check(cfg, p, fake)
    assert first['state'] == 'running' and first['cput'] == '00:01:07'
    assert first['observation']['outputs']['water.log']['size'] == 100
    for offset in (5, 59):
        clock[0] = 1000 + offset
        assert status.check(cfg, p, fake)['state'] == 'running'
    assert 'session_processes' not in fake.operations()
    clock[0] = 1060
    stalled = status.check(cfg, p, fake)
    assert stalled['state'] == 'stalled' and stalled['session_processes']['absent']
    assert stalled['outputs_unchanged_60s']
    fake.sizes['water.log'] = 101
    assert status.check(cfg, p, fake)['state'] == 'running'
    clock[0] += 60
    assert status.check(cfg, p, fake)['state'] == 'stalled'
    assert not {'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('change', ['mtime', 'size', 'session', 'clock_backwards'])
def test_changes_reset_stability(cfg, prepared, monkeypatch, change):
    p, _, fake = submitted(prepared, cfg)
    clock = [1000.0]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake)
    clock[0] = 1060
    if change == 'mtime': fake.mtime = fake.mtime.replace('000000001', '000000002')
    if change == 'size': fake.sizes['water.log'] += 1
    if change == 'session': fake.job.stdout = fake.job.stdout.replace('session_id = 321', 'session_id = 322')
    if change == 'clock_backwards': clock[0] = 999
    result = status.check(cfg, p, fake)
    assert result['state'] == 'running' and not result['outputs_unchanged_60s']


@pytest.mark.parametrize('missing', ['process_absence', 'marker', 'session', 'stable', 'legacy'])
def test_legacy_completion_requires_every_condition(cfg, prepared, monkeypatch, missing):
    p, _, fake = submitted(prepared, cfg, legacy=missing != 'legacy')
    fake.marker = 'present\n'
    if missing == 'process_absence': fake.ps = Result(stdout='42 321 R crest\n')
    if missing == 'marker': fake.marker = 'absent\n'
    if missing == 'session': fake.job.stdout = fake.job.stdout.replace('    session_id = 321\n', '')
    clock = [1000.0]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake)
    clock[0] += 59 if missing == 'stable' else 60
    result = status.check(cfg, p, fake)
    assert result['state'] != 'finished'
    assert not {'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('scheduler', ['R', 'C', None])
def test_legacy_completion_then_fetch_and_scheduler_cleanup(cfg, prepared, monkeypatch, scheduler):
    p, m, fake = submitted(prepared, cfg, legacy=True)
    fake.marker = 'present\n'
    clock = [1000.0]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake)  # retain session ID even if PBS removes the record later
    fake.job = (Result(stdout=job_text(m, state_=scheduler) + '    session_id = 321\n')
                if scheduler else Result(153, '', 'qstat: Unknown Job Id'))
    clock[0] += 60
    result = status.check(cfg, p, fake)
    assert result['state'] == 'finished' and result['exit_status'] is None
    assert result['scheduler_residue'] == (scheduler == 'R')
    fake.files = {'water.log': b'normal', 'job.pbs.out': b'PBS output'}
    assert fetch.fetch(cfg, p, fake)['state'] == 'fetched'
    if scheduler == 'R':
        allow(monkeypatch)
        assert cancel.cancel(cfg, p, fake)['state'] == 'fetched'
        assert fake.operations().count('cancel') == 1
        with pytest.raises(ValueError): cancel.cancel(cfg, p, fake)
        assert fake.operations().count('cancel') == 1
    else:
        with pytest.raises(ValueError): cancel.cancel(cfg, p, fake)


def test_absent_legacy_job_finishes_without_saved_session_after_stable_marker(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(153, '', 'qstat: Unknown Job Id')
    fake.marker = 'present\n'
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    assert status.check(cfg, p, fake)['state'] == 'awaiting_second_observation'
    clock[0] += 60
    result = status.check(cfg, p, fake)
    assert result['state'] == 'finished'
    assert result['completion_source'] == 'legacy-marker-stable-scheduler-absent'
    assert 'session_processes' not in fake.operations()


def test_legacy_change_during_ps_does_not_finish(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg, legacy=True)
    fake.marker = 'present\n'
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake); clock[0] += 60
    original = fake.run
    def run(command):
        if command.operation == 'session_processes': fake.sizes['water.log'] += 1
        return original(command)
    fake.run = run
    result = status.check(cfg, p, fake)
    assert result['state'] == 'running' and not result['outputs_unchanged_60s']


@pytest.mark.parametrize('reply', [Result(255, '', 'error'), Result(1, '', 'ps: failed'),
                                 Result(0), Result(stdout='42 999 R crest\n')])
def test_ps_failure_is_not_process_absence(cfg, prepared, monkeypatch, reply):
    p, _, fake = submitted(prepared, cfg, legacy=True)
    fake.ps, fake.marker = reply, 'present\n'
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake); clock[0] += 60
    with pytest.raises((ValueError, TransportError)): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'running'


def test_qstat_ssh_error_never_interrupted(cfg, prepared):
    p, _, fake = submitted(prepared, cfg)
    fake.job = Result(255, '', 'qstat: Unknown Job Id')
    with pytest.raises(TransportError): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'


def test_finished_residue_cancel_before_fetch_preserves_result(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg)
    fake.receipts['ag-exit.json'] = exit_receipt(7)
    status.check(cfg, p, fake); allow(monkeypatch)
    assert cancel.cancel(cfg, p, fake)['state'] == 'finished'
    assert state.read(p)['exit_status'] == 7
    fake.files = {'water.log': b'failed calculation', 'job.pbs.out': b'output'}
    assert fetch.fetch(cfg, p, fake)['state'] == 'fetched'


def test_cancel_failure_claim_blocks_second_qdel(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg)
    allow(monkeypatch); fake.fail_operation = 'cancel'
    with pytest.raises(TransportError): cancel.cancel(cfg, p, fake)
    with pytest.raises(ValueError): cancel.cancel(cfg, p, fake)
    assert fake.operations().count('cancel') == 1


def test_ssh_stderr_redacted_in_status_and_journal_even_after_recovery(cfg, prepared, monkeypatch):
    p, _, _ = submitted(prepared, cfg)
    # Synthetic identifiers, assembled so no real endpoint data enters fixtures.
    host, user = 'example' + '.invalid', 'test' + 'person'
    address = '.'.join(['192', '0', '2', '1'])
    Path(cfg['ssh']['config_file']).write_text(f'Host fixture\n HostName {host}\n User {user}\n')
    stderr = f'{user}@{host}: Connection reset by {address} port 22\nuser {user}'
    t = SSHTransport(cfg, read_only=True); t.record_to([p])
    replies = iter([Result(255, '', stderr), Result(stdout='ok')])
    monkeypatch.setattr(t, '_execute', lambda *a: next(replies))
    monkeypatch.setattr('ag.transport.time.sleep', lambda _: None)
    assert t.run(remote.jobs()).stdout == 'ok'
    saved = (p / 'status.json').read_text() + (p.parent.parent / 'journal.jsonl').read_text()
    for secret in (host, user, address): assert secret not in saved
    assert 'Connection reset by' in saved and 'ssh_error' in saved
    assert state.read(p)['state'] == 'submitted'


def test_timeout_stderr_recorded(cfg, prepared, monkeypatch):
    p, _, _ = submitted(prepared, cfg)
    t = SSHTransport(cfg); t.record_to([p])
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('ssh', 60, stderr=b'Connection to example.invalid timed out')
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(TransportError): t.run(remote.jobs())
    assert 'example.invalid' not in (p / 'status.json').read_text()
    assert 'timed out' in state.read(p)['ssh_error']['stderr']


@pytest.mark.parametrize('template', ['gaussian', 'xtb', 'crest'])
@pytest.mark.parametrize('code', [0, 9])
def test_actual_template_launch_receipts_and_return_code(cfg, prepared, tmp_path, template, code):
    _, base = prepared
    root = (tmp_path / 'remote').resolve(); root.mkdir()
    cfg['remote'] = {'allowed_root': str(root), 'ag_root': str(root / 'ag')}
    m = dict(base, template=template, template_params={})
    work = Path(remote.attempt_dir(cfg, m)); work.mkdir(parents=True)
    binary = (tmp_path / 'bin').resolve(); binary.mkdir()
    if sys.platform != 'linux':
        # The production guard targets GNU realpath. Adapt only this fixture's
        # executable on macOS; Linux CI runs the actual GNU command unchanged.
        realpath = binary / 'realpath'
        realpath.write_text(f'#!{sys.executable}\nimport pathlib, sys\n'
                            "assert sys.argv[1:3] == ['-e', '--']\n"
                            'print(pathlib.Path(sys.argv[3]).resolve(strict=True))\n')
        realpath.chmod(0o700)

    cfg['programs']['gaussian']['g16root'] = str(binary)
    cfg['programs']['xtb']['root'] = str(binary.parent)
    program = 'g16' if template == 'gaussian' else template
    executable = binary / program
    executable.write_text(f'#!{sys.executable}\nimport json, pathlib, sys\n'
                          "assert json.loads(pathlib.Path('ag-start.json').read_text())['PBS_JOBID'] == '123.fixture'\n"
                          "assert not pathlib.Path('ag-exit.json').exists()\n"
                          "pathlib.Path('program-was-run').write_text('yes')\n"
                          f'sys.exit({code})\n')
    executable.chmod(0o700)
    script = render.render(cfg, m, 'water.gjf' if template == 'gaussian' else 'water.xyz')
    env = dict(os.environ, PBS_JOBID='123.fixture', PBS_O_WORKDIR=str(work),
               PATH=str(binary) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['sh'], input=script, text=True, cwd=work, env=env, capture_output=True)
    assert result.returncode == code, result.stderr
    assert json.loads((work / 'ag-exit.json').read_text())['returncode'] == code
    before = {p.name: p.read_bytes() for p in work.glob('ag-*.json')}
    again = subprocess.run(['sh'], input=script, text=True, cwd=work, env=env, capture_output=True)
    assert again.returncode != 0
    assert before == {p.name: p.read_bytes() for p in work.glob('ag-*.json')}


def test_read_commands_fixed_selectors_syntax_and_receipt_paths(cfg, prepared):
    _, m = prepared
    cmds = [remote.receipt(cfg, m, 'ag-start.json'), remote.receipt(cfg, m, 'ag-exit.json'),
            remote.output_observation(cfg, m), remote.completion_marker(cfg, m), remote.session_processes('321')]
    for command in cmds:
        assert subprocess.run(['sh', '-n'], input=command.text, text=True).returncode == 0
        assert not {'qsub', 'qdel', 'rm', 'mv', '>', '>>'} & set(shlex.split(command.text))
    for invalid in ('../ag-exit.json', 'job.pbs', '/escape'):
        with pytest.raises(ValueError): remote.receipt(cfg, m, invalid)
    for invalid in ('0', '-1', '321;evil', 'x', 321):
        with pytest.raises(ValueError): remote.session_processes(invalid)


@pytest.mark.skipif(sys.platform != 'linux', reason='Remote stat/ps dialect is Linux; exercised by Linux CI')
def test_remote_receipt_limit_and_symlink_output_rules(cfg, prepared, tmp_path):
    _, m = prepared
    root = tmp_path.resolve() / 'remote'; root.mkdir()
    cfg['remote'] = {'allowed_root': str(root), 'ag_root': str(root / 'ag')}
    work = Path(remote.attempt_dir(cfg, m)); work.mkdir(parents=True)
    def run(command): return subprocess.run(['sh', '-c', command.text], capture_output=True, text=True)
    cmd = remote.receipt(cfg, m, 'ag-exit.json')
    assert run(cmd).stdout == 'absent\n'
    receipt = work / 'ag-exit.json'; receipt.write_text('x' * 4096)
    assert len(run(cmd).stdout) == 4096
    receipt.write_text('x' * 4097)
    assert run(cmd).returncode != 0 and not run(cmd).stdout
    receipt.unlink(); receipt.symlink_to(tmp_path / 'missing')
    assert run(cmd).returncode != 0
    log = work / 'water.log'; log.write_text('Normal termination of Gaussian\n')
    assert run(remote.completion_marker(cfg, m)).stdout == 'present\n'
    assert 'water.log' in run(remote.output_observation(cfg, m)).stdout
    log.unlink(); log.symlink_to(receipt)
    assert run(remote.completion_marker(cfg, m)).returncode != 0
    assert run(remote.output_observation(cfg, m)).returncode != 0


@pytest.mark.parametrize('name', ['ag-start.json', 'ag-exit.json'])
@pytest.mark.parametrize('kind', ['file', 'symlink', 'fifo'])
def test_receipts_refuse_existing_objects_before_program(tmp_path, name, kind):
    receipt = tmp_path / name
    if kind == 'file': receipt.write_text('preserve')
    if kind == 'symlink': receipt.symlink_to(tmp_path / 'missing')
    if kind == 'fifo': os.mkfifo(receipt)
    function = (render.TEMPLATES / '_guard.sh').read_text().split('ag_run() {', 1)[1]
    script = 'set -euC\nag_run() {' + function.replace('$$', '$') + "\nag_run sh -c 'touch ran'\n"
    result = subprocess.run(['sh'], input=script, text=True, cwd=tmp_path,
                            env=dict(os.environ, PBS_JOBID='123.fixture'), timeout=3, capture_output=True)
    assert result.returncode != 0 and not (tmp_path / 'ran').exists()
    if kind == 'file': assert receipt.read_text() == 'preserve'
    if kind == 'symlink': assert receipt.is_symlink()


def test_real_transport_status_failure_retains_redacted_evidence(cfg, prepared, monkeypatch):
    p, _, _ = submitted(prepared, cfg)
    t = SSHTransport(cfg)
    monkeypatch.setattr(t, '_execute', lambda *a: Result(255, '', 'ssh: connect to host example.invalid port 22: refused'))
    with pytest.raises(TransportError): status.check(cfg, p, t)
    saved = state.read(p)
    assert saved['state'] == 'submitted' and 'refused' in saved['ssh_error']['stderr']
    assert 'example.invalid' not in json.dumps(saved)


def test_upload_ssh_failure_logged_without_retry(cfg, prepared, monkeypatch):
    p, m = prepared
    t = SSHTransport(cfg); t.record_to([p]); calls = []
    monkeypatch.setattr(t, 'run', lambda *a: Result())
    monkeypatch.setattr(t, '_execute', lambda *a: calls.append('upload') or Result(255, '', 'Connection to example.invalid closed'))
    with pytest.raises(TransportError): t.upload(p / 'inputs/water.gjf', m, 'water.gjf')
    assert calls == ['upload']
    assert 'ssh_error' in state.read(p) and 'example.invalid' not in (p / 'status.json').read_text()


def test_cancel_declined_residue_keeps_claim_unused(cfg, prepared, monkeypatch):
    from ag import confirm
    p, _, fake = submitted(prepared, cfg)
    fake.receipts['ag-exit.json'] = exit_receipt()
    status.check(cfg, p, fake)
    monkeypatch.setattr(confirm, 'confirm', lambda *a: False)
    with pytest.raises(submit.UserCancelled): cancel.cancel(cfg, p, fake)
    assert not (p / '.cancel-claim').exists() and 'cancel' not in fake.operations()


@pytest.mark.parametrize('bad_session', ['0', '321;touch injected', '-1'])
def test_bad_scheduler_session_never_becomes_command(cfg, prepared, bad_session):
    p, _, fake = submitted(prepared, cfg)
    fake.job.stdout = fake.job.stdout.replace('session_id = 321', 'session_id = ' + bad_session)
    with pytest.raises(ValueError): status.check(cfg, p, fake)
    assert 'session_processes' not in fake.operations()


def test_ps_flags_and_positive_session_rows():
    class Process:
        def run(self, command): return Result(stdout='42 321 Ssl+ crest\n')
    assert not status.processes(Process(), '321')['absent']


@pytest.mark.parametrize('address', [':'.join(['', '', '1']), ':'.join(['2001', 'db8', '', '1']),
                                     ':'.join(['fe80', '', '1234']) + '%eth0'])
def test_ipv6_ssh_diagnostics_do_not_leak_endpoint(cfg, address):
    stderr = f"debug1: Authenticating to unlisted-node [{address}] as 'unlisted-user'"
    safe = redact_stderr(stderr, cfg)
    for secret in (address, 'unlisted-node', 'unlisted-user'):
        assert secret not in safe
    assert 'Authenticating to' in safe
