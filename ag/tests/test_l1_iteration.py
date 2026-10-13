"""T8 offline regressions, using synthetic observations and convergence tables."""
import json

import pytest

from ag import cli, fetch, state, status
from ag._parse_outputs import frequency_convergence, parse_gaussian
from ag.transport import Result
from test_core import cfg, prepared, job_text
from test_completion import submitted, exit_receipt


@pytest.mark.parametrize('scheduler', [None, 'C'])
def test_wait_then_finish_without_early_fetch(cfg, prepared, monkeypatch, scheduler):
    p, m, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(stdout=job_text(m, state_='C') + '    session_id = 321\n') if scheduler else Result(153)
    fake.marker = 'present\n'
    clock = [1000.0]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    for now in (1000, 1059):
        clock[0] = now
        result = status.check(cfg, p, fake)
        assert result['state'] == 'awaiting_second_observation'
        assert result['wait_seconds'] == now - 1000
        assert result['next_observation_at'] == 1060
        assert '等待第二次观察' in status.format_status([dict(attempt_id=p.name, **result)])
        with pytest.raises(ValueError, match='finished'):
            fetch.fetch(cfg, p, fake)
    clock[0] = 1060
    assert status.check(cfg, p, fake)['state'] == 'finished'
    assert not {'submit', 'cancel', 'download'} & set(fake.operations())


def test_explicit_failure_never_waits_or_uses_legacy_marker(cfg, prepared, monkeypatch):
    p, m, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(stdout=job_text(m, state_='C').replace('exit_status = 0', 'exit_status = 9') +
                      '    session_id = 321\n')
    fake.marker = 'present\n'
    clock = [1000]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    assert status.check(cfg, p, fake)['state'] == 'interrupted'
    clock[0] += 60
    assert status.check(cfg, p, fake)['state'] == 'interrupted'
    assert 'completion_marker' not in fake.operations()
    fake.receipts['ag-exit.json'] = exit_receipt(9)
    result = status.check(cfg, p, fake)
    assert result['state'] == 'finished' and result['exit_status'] == 9


def test_wait_can_return_to_running(cfg, prepared):
    p, m, fake = submitted(prepared, cfg)
    fake.job = Result(153)
    assert status.check(cfg, p, fake)['state'] == 'awaiting_second_observation'
    fake.job = Result(stdout=job_text(m))
    assert status.check(cfg, p, fake)['state'] == 'running'


@pytest.mark.parametrize('cpu', ['00:01:07', None])
@pytest.mark.parametrize('as_json', [False, True])
def test_status_cli_activity_and_missing_values(cfg, prepared, monkeypatch, capsys, cpu, as_json):
    p, m, fake = submitted(prepared, cfg)
    fake.job = Result(stdout=job_text(m) + (f'    resources_used.cput = {cpu}\n' if cpu else ''))
    fake.sizes['job.pbs.out'] = None
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: fake)
    assert cli.main(['status', p.name] + (['--json'] if as_json else [])) == 0
    output = capsys.readouterr().out
    if as_json:
        result = json.loads(output)[0]
        assert result['state'] == 'running' and result['cput'] == cpu
        assert result['observation']['outputs']['water.log']['mtime'] == fake.mtime
        assert result['observation']['outputs']['job.pbs.out'] is None
    else:
        assert f'resources_used.cput: {cpu or "未知"}' in output
        assert 'water.log: size=100 bytes; mtime=' + fake.mtime in output
        assert 'job.pbs.out: 未发现' in output
        assert '输出观察时间:' in output and '查询时间' in output


@pytest.mark.parametrize('receipt', [False, True])
def test_terminal_observation_is_refreshed(cfg, prepared, monkeypatch, receipt):
    p, _, fake = submitted(prepared, cfg)
    clock = [1000]
    monkeypatch.setattr(status.time, 'time', lambda: clock[0])
    status.check(cfg, p, fake)
    if receipt:
        fake.receipts['ag-exit.json'] = exit_receipt()
    else:
        state.write(p, 'finished', completion_source='legacy-marker-stable-session-absent')
    clock[0] += 120
    fake.sizes['water.log'] = 200
    fake.job = Result(153)
    result = status.check(cfg, p, fake)
    assert result['observation']['at'] == clock[0]
    assert result['observation']['outputs']['water.log']['size'] == 200
    assert result['cput'] is None and not result['scheduler_residue']
    assert result['outputs_unchanged_60s'] is None and result['session_processes'] is None
    assert '残留 (PBS R)' not in result['note']
    fake.files = {'water.log': b'output', 'job.pbs.out': b'output'}
    fetch.fetch(cfg, p, fake)
    clock[0] += 60
    result = status.check(cfg, p, fake)
    assert result['state'] == 'fetched' and result['observation']['at'] == clock[0]


@pytest.mark.parametrize('residue', [False, True])
def test_fetch_cli_residue_hint_never_cancels(cfg, prepared, monkeypatch, capsys, residue):
    p, _, fake = submitted(prepared, cfg)
    fake.receipts['ag-exit.json'] = exit_receipt()
    if not residue:
        fake.job = Result(153)
    status.check(cfg, p, fake)
    fake.files = {'water.log': b'output', 'job.pbs.out': b'output'}
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: fake)
    assert cli.main(['fetch', p.name, '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'fetched'
    hint = result['cleanup_hint']
    if residue:
        assert f'ag cancel {p.name}' in hint and '亲手点击' in hint
        assert f'ag status {p.name}' in hint
    else:
        assert hint is None
    assert not {'submit', 'cancel'} & set(fake.operations())
    assert not (p / '.cancel-claim').exists()


# Synthetic water-like numbers only; no copied study log or geometry.
TABLE = '''         Item               Value     Threshold  Converged?
 Maximum Force            0.000010     0.000450     YES
 RMS     Force            0.000002     0.000300     YES
 Maximum Displacement     0.000100     0.001800     YES
 RMS     Displacement     0.000050     0.001200     YES
'''
FAILED = TABLE.replace('0.000100     0.001800     YES', '0.003000     0.001800     NO')
HARMONIC = ' Harmonic frequencies (cm**-1), IR intensities (KM/Mole)\n'
ROUTE = ' #p HF/STO-3G Freq\n ----------------\n'
END = ' Normal termination of Gaussian\n'


@pytest.mark.parametrize('text,expected', [
    (TABLE, None),  # Opt-only table cannot prove frequency convergence.
    (ROUTE + TABLE, None),  # Route requests Freq, but it has not run.
    (HARMONIC, None),
    (HARMONIC + TABLE, True),
    (HARMONIC + FAILED, False),
    (HARMONIC + ' ! Non-Optimized Parameters !\n', False),
    (FAILED + HARMONIC + TABLE, True),  # Earlier Opt NO is not relevant.
    (HARMONIC + FAILED + 'Non-Optimized Parameters\n' + TABLE, True),
    (HARMONIC + TABLE + FAILED, False),  # Only final frequency check.
    (HARMONIC + TABLE + HARMONIC, None),
    (HARMONIC + TABLE + END + ROUTE, None),  # New Freq step truncated.
    (HARMONIC + END + TABLE, None),  # Table outside frequency step.
    (HARMONIC + END + ' #p HF/STO-3G Opt\n ----->\n' + TABLE, None),
    (HARMONIC + TABLE + END + ROUTE + HARMONIC + FAILED, False),
    (HARMONIC + FAILED + END + ROUTE + HARMONIC + TABLE, True),
    (HARMONIC + TABLE.rsplit(' RMS', 1)[0], None),  # Truncated table.
    (HARMONIC + TABLE.replace('0.000100', '********'), None),
    (HARMONIC + TABLE.replace('0.000100', '1.000D-04'), True),
])
def test_frequency_stage_boundaries_and_tristate(text, expected):
    assert frequency_convergence(text)['freq_step_converged'] is expected


def test_frequency_table_evidence_and_cclib_failure(tmp_path):
    text = ' Optimization completed.\n' + HARMONIC + FAILED + ' ! Non-Optimized Parameters !\n' + END
    log = tmp_path / 'synthetic-water.log'
    log.write_text(text)
    facts, _ = parse_gaussian(log)
    assert facts['opt_converged'] is True and facts['termination'] == 'normal'
    assert facts['freq_step_converged'] is False
    check = facts['freq_step_convergence']
    assert check['frequency_line'] == 2 and check['table_line'] == 3
    assert check['non_optimized_parameters_line'] == 8
    assert check['criteria']['maximum_displacement'] == {
        'value': 0.003, 'threshold': 0.0018, 'converged': False, 'line': 6}
    assert json.loads(json.dumps(check, allow_nan=False)) == check
