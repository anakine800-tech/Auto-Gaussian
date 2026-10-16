"""T62: synthetic observations and local shell commands; never SSH."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import pytest

from ag import fetch, remote, state, status
from ag.transport import Result
from test_core import cfg, prepared  # noqa: F401
from test_completion import submitted, exit_receipt

MTIME = '2026-01-01 00:00:00.000000001 +0000'


class Output:
    def __init__(self, text):
        self.text = text

    def run(self, command):
        return Result(stdout=self.text)


@pytest.mark.parametrize('mode', ['present', 'absent', 'unreadable'])
def test_output_three_way_parse(cfg, prepared, mode):
    _, m = prepared
    info = f'4 {MTIME}' if mode == 'present' else mode
    fake = Output(''.join(f'{name} {info}\n' for name in remote.output_names(m)))
    if mode == 'unreadable':
        with pytest.raises(ValueError, match='water.log'):
            status.outputs(cfg, m, fake)
    else:
        result = status.outputs(cfg, m, fake)
        assert result['water.log'] == (dict(size=4, mtime=MTIME) if mode == 'present' else None)


@pytest.mark.parametrize('name', ['ag-start.json', 'ag-exit.json'])
@pytest.mark.parametrize('mode', ['present', 'absent', 'unreadable'])
def test_receipt_three_way_parse(cfg, prepared, name, mode):
    _, m = prepared
    value = (dict(PBS_JOBID='123.fixture', started_at='2026-01-01T00:00:00Z')
             if name == 'ag-start.json' else json.loads(exit_receipt()))
    raw = json.dumps(value) if mode == 'present' else mode + '\n'
    if mode == 'unreadable':
        with pytest.raises(ValueError, match=name):
            status.read_receipt(cfg, m, Output(raw), name, '123.fixture')
    else:
        assert status.read_receipt(cfg, m, Output(raw), name, '123.fixture') == (
            value if mode == 'present' else None)


@pytest.mark.parametrize('current_state', ['submitted', 'running', 'stalled', 'interrupted',
                                         'awaiting_second_observation', 'finished', 'fetched'])
@pytest.mark.parametrize('unreadable', ['ag-start.json', 'ag-exit.json', 'water.log', 'job.pbs.out'])
def test_status_unreadable_preserves_all_state_bytes(cfg, prepared, current_state, unreadable):
    path, m, fake = submitted(prepared, cfg)
    current = state.read(path)
    current.update(state=current_state, observation={'at': 900}, incomplete_observations=[{'old': True}])
    (path / 'status.json').write_text(json.dumps(current))
    before = (path / 'status.json').read_bytes()
    original = fake.run
    def run(command):
        if command.operation == 'receipt' and unreadable in command.text:
            return Result(stdout='unreadable\n')
        if command.operation == 'output_observation' and unreadable.endswith(('.log', '.out')):
            return Result(stdout=''.join(f'{n} unreadable\n' if n == unreadable else f'{n} absent\n'
                                         for n in remote.output_names(m)))
        return original(command)
    fake.run = run
    result = status.check(cfg, path, fake)
    assert result['state'] == current_state
    assert (path / 'status.json').read_bytes() == before
    assert '无法判断' in status.format_status([{'attempt_id': path.name, **result}]) and '人工核对' in result['note']
    rows = [json.loads(line) for line in (path.parent.parent / 'journal.jsonl').read_text().splitlines()]
    assert rows[-1]['result'] == 'unreadable' and unreadable in rows[-1]['detail']


def test_unreadable_during_legacy_recheck_does_not_finish(cfg, prepared, monkeypatch):
    path, m, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(153)
    monkeypatch.setattr(status.time, 'time', lambda: 1000)
    assert status.check(cfg, path, fake)['state'] == 'awaiting_second_observation'
    fake.marker = 'present\n'
    before = (path / 'status.json').read_bytes()
    original = fake.run
    observations = 0
    def run(command):
        nonlocal observations
        if command.operation == 'output_observation':
            observations += 1
            if observations == 2:
                return Result(stdout='water.log unreadable\njob.pbs.out absent\n')
        return original(command)
    fake.run = run
    monkeypatch.setattr(status.time, 'time', lambda: 1061)
    result = status.check(cfg, path, fake)
    assert observations == 2 and '无法判断' in result['note']
    assert (path / 'status.json').read_bytes() == before


def test_incomplete_unreadable_cannot_be_collected_as_absent(cfg, prepared):
    _, m = prepared
    with pytest.raises(ValueError, match='Cannot verify'):
        fetch._presence(cfg, m, Output('unreadable\n'))


@pytest.mark.parametrize('kind', ['output', 'incomplete', 'receipt'])
@pytest.mark.parametrize('case', ['present', 'absent', 'file_000', 'parent_000', 'ancestor_000', 'not_directory'])
def test_fixed_commands_locally_distinguish_access(cfg, prepared, kind, case):
    if os.geteuid() == 0 and case.endswith('_000'):
        pytest.skip('permission checks require unprivileged user')
    _, m = prepared
    cfg['remote'] = {k: str(Path(v).resolve()) for k, v in cfg['remote'].items()}
    directory = Path(remote.attempt_dir(cfg, m))
    directory.mkdir(parents=True)
    for name in remote.output_names(m):
        (directory / name).write_text('data')
    (directory / 'ag-exit.json').write_text(exit_receipt())
    target = directory / ('ag-exit.json' if kind == 'receipt' else 'water.log')
    blocked = None
    if case == 'absent':
        target.unlink()
    elif case == 'file_000':
        blocked = target
    elif case == 'parent_000':
        blocked = directory
    elif case == 'ancestor_000':
        blocked = directory.parent
    elif case == 'not_directory':
        # A regular file in the directory chain is ENOTDIR, never absence.
        directory.rename(directory.with_name('saved'))
        directory.write_text('not a directory')
    if blocked:
        blocked.chmod(0)
    command = (remote.output_observation(cfg, m) if kind == 'output' else
               remote.incomplete_output_observation(cfg, m, 'water.log') if kind == 'incomplete' else
               remote.receipt(cfg, m, 'ag-exit.json'))
    # GNU stat is unavailable on macOS; only metadata formatting is faked.
    # The ls/test/head permission and ENOENT operations run against real local files.
    stat = "stat() { case \"$2\" in '%s') printf '4\\n';; *) printf '4 " + MTIME + "\\n';; esac; }; "
    try:
        result = subprocess.run(['sh', '-c', stat + command.text], capture_output=True, text=True)
    finally:
        if blocked:
            blocked.chmod(0o700 if blocked.is_dir() else 0o600)
    prefix = 'water.log ' if kind == 'output' else ''
    if case == 'present':
        assert result.returncode == 0
        assert result.stdout.startswith(exit_receipt() if kind == 'receipt' else prefix + '4 ' + MTIME)
    elif case == 'absent':
        assert result.returncode == 0 and result.stdout.startswith(prefix + 'absent\n')
    else:
        assert 'unreadable' in result.stdout and 'absent' not in result.stdout
        assert result.returncode == (1 if kind == 'incomplete' else 0)


def test_full_command_snapshots():
    cfg = {'remote': {'ag_root': '/fixture/ag'}}
    m = {'study_id': 'water', 'attempt_id': 'water-001-sp', 'remote_dir': 'water/water-001-sp',
         'template': 'gaussian', 'inputs': [{'name': 'water.gjf'}]}
    commands = [remote.output_observation(cfg, m),
                remote.incomplete_output_observation(cfg, m, 'water.log'),
                remote.receipt(cfg, m, 'ag-exit.json')]
    assert [sha256(c.text.encode()).hexdigest() for c in commands] == [
        '9508b826bc7608d7c47d7fba8abf1820d908c8a7686e4dd00e975db0a056ee6a',
        '904c622f89a3c9ce0f312078ca7aa5b2b40bb318b32e307b2e0c07377d0dacc6',
        '3440a743aab86b4c8313f636cc1c60c76ae1bbd1c2cc7620f8451d601a67cff1',
    ]
    for command in commands:
        assert subprocess.run(['sh', '-n'], input=command.text, text=True).returncode == 0


LS_FAILURES = [
    ("ls: cannot access /x: No such file or directory", 'absent'),
    ("ls: cannot access '/x': No such file or directory", 'absent'),
    ("No such file or directory", 'absent'),
    ("ls: cannot access /x: Permission denied", 'unreadable'),
    ("ls: cannot access '/x': Permission denied", 'unreadable'),
    ("ls: cannot access /x: Input/output error", 'unreadable'),
]


def run_with_ls_failure(command, diagnostic):
    # Run the complete generated shell command. Only ls is faked, so locale,
    # quoting, case matching and the incomplete-fetch parent checks still run.
    fake_ls = "ls() { printf '%s\\n' \"$AG_TEST_LS_ERROR\" >&2; return 2; }; "
    return subprocess.run(['sh', '-c', fake_ls + command.text], capture_output=True, text=True,
                          env={**os.environ, 'AG_TEST_LS_ERROR': diagnostic})


@pytest.mark.parametrize('kind', ['output', 'incomplete', 'receipt'])
@pytest.mark.parametrize('diagnostic,expected', LS_FAILURES)
def test_ls_diagnostic_formats(cfg, prepared, kind, diagnostic, expected):
    _, m = prepared
    cfg['remote'] = {k: str(Path(v).resolve()) for k, v in cfg['remote'].items()}
    Path(remote.attempt_dir(cfg, m)).mkdir(parents=True)
    command = (remote.output_observation(cfg, m) if kind == 'output' else
               remote.incomplete_output_observation(cfg, m, 'water.log') if kind == 'incomplete' else
               remote.receipt(cfg, m, 'ag-exit.json'))
    result = run_with_ls_failure(command, diagnostic)
    lines = ([f'{name} {expected}' for name in remote.output_names(m)]
             if kind == 'output' else [expected])
    assert result.stdout == '\n'.join(lines) + '\n'
    assert result.stderr == ''
    assert result.returncode == (1 if kind == 'incomplete' and expected == 'unreadable' else 0)


@pytest.mark.parametrize('diagnostic', [row[0] for row in LS_FAILURES[:2]])
def test_missing_exit_receipt_formats_allow_running_status(cfg, prepared, diagnostic):
    path, _, fake = submitted(prepared, cfg)
    original = fake.run
    def run(command):
        if command.operation == 'receipt':
            result = run_with_ls_failure(command, diagnostic)
            return Result(result.returncode, result.stdout, result.stderr)
        return original(command)
    fake.run = run
    result = status.check(cfg, path, fake)
    assert result['state'] == 'running'
    assert state.read(path)['state'] == 'running'
    assert '无法判断' not in result['note']
