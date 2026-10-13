"""T1d: sanitized Torque incident and offline completion/fetch regressions."""
import pytest

from ag import fetch, state, status
from ag.transport import Result, TransportError
from test_core import cfg, prepared
from test_completion import submitted, exit_receipt


# Sanitized verbatim stderr from the incident; no actual endpoint or job ID.
TORQUE_UNKNOWN = 'qstat: Unknown Job Id Error [redacted]'
MISSING_REPLIES = [
    Result(153, '', TORQUE_UNKNOWN),
    Result(153),  # Torque missing-job exit status remains evidence on its own.
    Result(1, '', TORQUE_UNKNOWN),
    Result(1, TORQUE_UNKNOWN),
    Result(1, '', 'qstat: Unknown Job Id'),
    Result(1, '', 'qstat: Unknown Job Id [redacted]'),
    Result(1, '', 'qstat: Unknown Job Id Error'),
    Result(1, '', 'Unknown Job Id Error [redacted]\n'),
    Result(1, '', '  qstat: unknown job id error [redacted]\n'),
]


@pytest.mark.parametrize('reply', MISSING_REPLIES)
@pytest.mark.parametrize('receipt', [True, False])
def test_torque_absence_receipt_or_stable_legacy(cfg, prepared, monkeypatch, reply, receipt):
    p, _, fake = submitted(prepared, cfg, legacy=not receipt)
    fake.job = reply
    fake.marker = 'present\n'
    if receipt: fake.receipts['ag-exit.json'] = exit_receipt(9)
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    first = status.check(cfg, p, fake)
    assert first['scheduler_state'] is None and not first['scheduler_residue']
    if receipt:
        assert first['state'] == 'finished' and first['exit_status'] == 9
    else:
        assert first['state'] == 'interrupted'
        clock[0] += 59
        assert status.check(cfg, p, fake)['state'] == 'interrupted'
        clock[0] += 1
        result = status.check(cfg, p, fake)
        assert result['state'] == 'finished' and result['exit_status'] is None
        assert result['completion_source'] == 'legacy-marker-stable-scheduler-absent'
    assert 'session_processes' not in fake.operations()
    fake.files = {'water.log': b'Normal termination of Gaussian', 'job.pbs.out': b'output'}
    assert fetch.fetch(cfg, p, fake)['state'] == 'fetched'
    assert not {'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('reason', ['no_marker', 'changed_size', 'changed_mtime', 'new_attempt', 'has_start_receipt'])
def test_absent_job_without_required_evidence_remains_interrupted(cfg, prepared, monkeypatch, reason):
    p, _, fake = submitted(prepared, cfg, legacy=reason != 'new_attempt')
    fake.job = Result(153, '', TORQUE_UNKNOWN)
    fake.marker = 'absent\n' if reason == 'no_marker' else 'present\n'
    if reason == 'has_start_receipt':
        fake.receipts['ag-start.json'] = '{"PBS_JOBID":"123.fixture","started_at":"2026-01-01T00:00:00Z"}'
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    assert status.check(cfg, p, fake)['state'] == 'interrupted'
    clock[0] += 60
    if reason == 'changed_size': fake.sizes['water.log'] += 1
    if reason == 'changed_mtime': fake.mtime = fake.mtime.replace('000000001', '000000002')
    assert status.check(cfg, p, fake)['state'] == 'interrupted'
    with pytest.raises(ValueError): fetch.fetch(cfg, p, fake)
    assert not {'session_processes', 'download', 'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('reply', [Result(255, '', TORQUE_UNKNOWN), Result(-9, '', TORQUE_UNKNOWN),
                                  Result(1, '', 'qstat: cannot connect'),
                                  Result(1, '', 'permission denied'), Result(2)])
def test_other_failures_are_not_scheduler_absence(cfg, prepared, reply):
    p, _, fake = submitted(prepared, cfg)
    fake.job = reply
    with pytest.raises(TransportError): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'
    assert 'output_observation' not in fake.operations()
    assert not status.scheduler_absent(reply)


def test_success_with_no_scheduler_record_is_not_absence(cfg, prepared):
    p, _, fake = submitted(prepared, cfg)
    fake.job = Result(stdout='')
    with pytest.raises(ValueError): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'
    assert not status.scheduler_absent(fake.job)


def test_output_drift_after_marker_cannot_finish_absent_legacy(cfg, prepared, monkeypatch):
    p, _, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(153, '', TORQUE_UNKNOWN); fake.marker = 'present\n'
    clock = [1000]; monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake); clock[0] += 60
    original = fake.run
    def run(command):
        if command.operation == 'completion_marker': fake.sizes['water.log'] += 1
        return original(command)
    fake.run = run
    result = status.check(cfg, p, fake)
    assert result['state'] == 'interrupted' and not result['outputs_unchanged_60s']
