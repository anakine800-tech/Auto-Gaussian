"""T13-2: inert transports and disposable synthetic checkpoint bytes only."""
from copy import deepcopy
from hashlib import sha256
import ast
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest
from ag import attempt, cli, config, confirm, doctor, gaussian_input, parent_chk, remote, state, submission, submit
from ag.parent_chk_remote import SCRIPT
from ag.transport import READ_OPERATIONS, Result, SSHTransport, TransportError
from test_core import INPUT, Fake, cfg, prepared
from test_slurm import multi


@pytest.fixture
def parent(cfg, prepared):
    path, manifest = prepared
    state.write(path, 'submitting')
    submission.record(path, manifest, '42.fixture')
    state.write(path, 'submitted', job_id=submission.qualified(manifest, '42.fixture'))
    state.write(path, 'finished')
    # Synthetic parent geometry in the Hessian's input frame.
    (path / 'final_input.xyz').write_text('3\nInput orientation\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    return path, manifest


def child(cfg, tmp_path, parent, **changes):
    _, manifest = parent
    source = tmp_path / 'child.gjf'
    source.write_text('%oldchk=parent.chk\n' + INPUT.replace(' SP', ' guess=read irc=(rcfc,forward)'))
    options = dict(study_name='smoke', template='gaussian', input_path=source,
                   tier='simple', walltime='00:30:00', label='irc',
                   parents=[dict(attempt_id=manifest['attempt_id'], relation='irc_from')],
                   parent_chk=manifest['attempt_id'] + ':water.chk')
    options.update(changes)
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', **options)
    return attempt.find(cfg, m['attempt_id']), m


class CheckpointFake(Fake):
    """Runs ONLY the fixed chk copy locally; no SSH, PBS or Gaussian process."""
    def __init__(self, cfg, parent):
        super().__init__(cfg)
        self.source = Path(remote.attempt_dir(cfg, parent)) / 'water.chk'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'synthetic water checkpoint')
        self.copy_result = None
        self.corrupt = False

    def run(self, command):
        if command.operation in ('parent_chk_metadata', 'copy_parent_chk', 'create_attempt'):
            self.calls.append(command)
            if command.operation == 'parent_chk_metadata':
                if sys.platform.startswith('linux'):
                    # CI can exercise the exact stat/sha256sum descriptor command
                    # on fixture paths, still without SSH or any real cluster.
                    result = subprocess.run(['sh', '-c', command.text], capture_output=True, text=True)
                    return Result(result.returncode, result.stdout, result.stderr)
                path = Path(shlex.split(command.text)[-2])
                if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
                    return Result(1)
                data = path.read_bytes()
                return Result(stdout=f'{len(data)}\n{sha256(data).hexdigest()}  {path}\n')
            if command.operation == 'create_attempt':
                path = Path(shlex.split(command.text)[-1])
                if path.exists():
                    return Result(1)
                path.mkdir()
                return Result()
            if self.copy_result:
                if isinstance(self.copy_result, Exception):
                    raise self.copy_result
                return self.copy_result
            # The command itself is exercised against temporary local fixture paths.
            result = subprocess.run(['sh', '-c', command.text], capture_output=True, text=True)
            target = Path(shlex.split(command.text)[-1]) / 'parent.chk'
            if self.corrupt and result.returncode == 0:
                target.write_bytes(b'corrupt fixture')
            return Result(result.returncode, result.stdout, result.stderr)
        return super().run(command)


def test_local_declaration_cli_and_summary(cfg, parent, tmp_path, monkeypatch, capsys):
    p, m = child(cfg, tmp_path, parent)
    assert m['parent_chk'] == dict(attempt_id=parent[0].name, source_name='water.chk',
                                  target_name='parent.chk', cluster='default')
    assert attempt.read_manifest(p) == m
    assert 'size/SHA256' in attempt.summary(cfg, m)
    assert 'parent.chk' not in {r['name'] for r in m['inputs']}
    attempt.verified_files(cfg, p, m)
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('prepare must be local'))
    assert cli.main(['prepare', '--method-basis', '兜底方法：合成测试', '--study', 'smoke', '--template', 'gaussian',
                     '--input', str(tmp_path / 'child.gjf'), '--tier', 'simple',
                     '--walltime', '00:05:00', '--label', 'cli', '--parent', parent[0].name,
                     '--relation', 'irc_from', '--parent-chk', parent[0].name + ':water.chk', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['parent_chk'] == m['parent_chk']


@pytest.mark.parametrize('bad_state', ['prepared', 'submitted', 'running', 'unknown', 'failed_presubmit', 'cancelled'])
def test_reject_unfinished_parent(cfg, parent, tmp_path, bad_state):
    path, _ = parent
    value = state.read(path)
    value['state'] = bad_state
    (path / 'status.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='finished or fetched'):
        child(cfg, tmp_path, parent)


@pytest.mark.parametrize('name', ['../water.chk', '/water.chk', 'a/water.chk', 'bad name.chk', 'x;bad.chk', 'other.chk'])
def test_reject_bad_source_name(cfg, parent, tmp_path, name):
    with pytest.raises(ValueError):
        child(cfg, tmp_path, parent, parent_chk=parent[0].name + ':' + name)


def test_parent_relationship_required(cfg, parent, tmp_path):
    with pytest.raises(ValueError, match='--parent'):
        child(cfg, tmp_path, parent, parents=[])


@pytest.mark.parametrize('route', ['geom=check', 'geom=allcheck', 'Geom=(Check)',
                                 'Geometry = (AllCheck,NoCrowd)', 'geom(checkpoint)'])
def test_explicit_geometry_cannot_be_overridden(route):
    for attached in (False, True):
        text = INPUT.replace(' SP', ' SP ' + route)
        if attached:
            text = '%oldchk=parent.chk\n' + text
        with pytest.raises(ValueError, match='explicit coordinates'):
            gaussian_input.validate(text, 8, 12, parent_chk=attached)


@pytest.mark.parametrize('text', [INPUT, '%oldchk=other.chk\n' + INPUT,
                                '%oldchk=parent.chk\n' + INPUT.replace('water.chk', 'parent.chk'),
                                '%oldchk=parent.chk\n' + INPUT.replace('%chk=water.chk\n', '')])
def test_attachment_input_must_use_distinct_explicit_chk(text):
    with pytest.raises(ValueError):
        gaussian_input.validate(text, 8, 12, parent_chk=True)


@pytest.mark.parametrize('route', ['guess=read SP', 'guess=read opt=(ts,rcfc) freq', 'irc=(rcfc,reverse)'])
def test_supported_reuse_routes(route):
    parsed = gaussian_input.validate('%oldchk=parent.chk\n' + INPUT.replace(' SP', ' ' + route),
                                     8, 12, parent_chk=True)
    assert parsed['geometry'] == 'O 0 0 0\nH 0 0 1\nH 0 1 0'


def test_parent_input_is_bound_by_manifest(cfg, parent, tmp_path):
    (parent[0] / 'inputs/water.gjf').write_text(INPUT.replace('water.chk', 'different.chk'))
    with pytest.raises(ValueError, match='differs from its manifest'):
        child(cfg, tmp_path, parent)


def test_reject_cross_cluster(multi, parent, tmp_path):
    with pytest.raises(ValueError, match='same cluster'):
        child(multi, tmp_path, parent, cluster='batch')
    p, m = child(multi, tmp_path, parent)
    assert m['cluster'] == m['parent_chk']['cluster'] == 'default'
    selected = config.select_cluster(multi, 'batch')
    with pytest.raises(ValueError, match='cluster mismatch'):
        attempt.verified_files(selected, p, m)


def test_submit_confirm_copy_verify_order(cfg, parent, tmp_path, monkeypatch, capsys):
    state.write(parent[0], 'fetched')
    p, m = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    data = fake.source.read_bytes()
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or True)
    submit.submit(cfg, [p.name], fake)
    assert parent[0].name in seen[0] and 'water.chk -> parent.chk' in seen[0]
    assert f'{len(data)} bytes | SHA256 {sha256(data).hexdigest()[:12]}' in seen[0]
    assert seen[0] in capsys.readouterr().err
    assert fake.source.read_bytes() == data
    assert (Path(remote.attempt_dir(cfg, m)) / 'parent.chk').read_bytes() == data
    ops = fake.operations()
    assert ops.count('copy_parent_chk') == 1 and ops.count('parent_chk_metadata') == 3
    copy = ops.index('copy_parent_chk')
    assert ops[copy - 1:copy + 4] == ['create_attempt', 'copy_parent_chk', 'parent_chk_metadata',
                                   'parent_chk_metadata', 'upload']
    assert ops[-1] == 'submit'
    logs = [json.loads(line) for line in (p.parent.parent / 'journal.jsonl').read_text().splitlines()]
    logs = [r for r in logs if r['action'] == 'copy_parent_chk']
    assert [r['result'] for r in logs] == ['started', 'verified']
    assert logs[-1]['detail']['sha256'] == sha256(data).hexdigest()
    assert attempt.read_manifest(p) == m


@pytest.mark.parametrize('after_confirmation', [False, True])
def test_scheduler_parent_still_present(cfg, parent, tmp_path, monkeypatch, after_confirmation):
    p, _ = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    job = Result(stdout='Job Id: 42.fixture\n    Job_Owner = fixture@fixture\n    job_state = C\n    Resource_List.nodes = 1:ppn=8\n')
    if not after_confirmation:
        fake.qstat = job
    def dialog(text):
        fake.qstat = job
        return True
    monkeypatch.setattr(confirm, 'confirm', dialog)
    with pytest.raises(ValueError, match='still present'):
        submit.submit(cfg, [p.name], fake)
    assert 'create_attempt' not in fake.operations()
    assert state.read(p)['state'] == ('failed_presubmit' if after_confirmation else 'prepared')


@pytest.mark.parametrize('failure', ['source_changed', 'source_link', 'target_exists', 'hash_mismatch', '255', 'timeout'])
def test_copy_failures_stop_without_retry_or_qsub(cfg, parent, tmp_path, monkeypatch, failure):
    p, m = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    target = Path(remote.attempt_dir(cfg, m)) / 'parent.chk'
    def dialog(text):
        if failure == 'source_changed':
            fake.source.write_bytes(b'changed after confirmation')
        elif failure == 'source_link':
            other = fake.source.with_name('other.chk')
            fake.source.rename(other)
            fake.source.symlink_to(other)
        return True
    monkeypatch.setattr(confirm, 'confirm', dialog)
    if failure == 'hash_mismatch':
        fake.corrupt = True
    elif failure == '255':
        fake.copy_result = Result(255)
    elif failure == 'timeout':
        fake.copy_result = TransportError('Synthetic timeout')
    elif failure == 'target_exists':
        original = fake.run
        def run(command):
            result = original(command)
            if command.operation == 'create_attempt':
                target.write_bytes(b'existing')
            return result
        fake.run = run
    with pytest.raises((ValueError, TransportError)):
        submit.submit(cfg, [p.name], fake)
    assert state.read(p)['state'] == 'failed_presubmit'
    assert fake.operations().count('copy_parent_chk') == 1
    assert 'submit' not in fake.operations() and 'upload' not in fake.operations()
    if failure in ('source_changed', 'hash_mismatch', 'target_exists'):
        assert target.exists()
    if failure == 'target_exists':
        assert target.read_bytes() == b'existing'
    before = list(fake.calls)
    with pytest.raises(ValueError, match='consumed'):
        submit.submit(cfg, [p.name], fake)
    assert fake.calls == before


def test_preconfirmation_symlink_refused(cfg, parent, tmp_path, monkeypatch):
    p, _ = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    other = fake.source.with_name('other.chk')
    fake.source.rename(other)
    fake.source.symlink_to(other)
    monkeypatch.setattr(confirm, 'confirm', lambda text: pytest.fail('must not confirm symlink'))
    with pytest.raises(TransportError):
        submit.submit(cfg, [p.name], fake)
    assert 'create_attempt' not in fake.operations()


def test_exact_new_commands_and_write_transport_policy(cfg, parent, tmp_path, monkeypatch):
    _, m = child(cfg, tmp_path, parent)
    source = remote.attempt_dir(cfg, parent[1]) + '/water.chk'
    target = remote.attempt_dir(cfg, m)
    read = remote.parent_chk_metadata(cfg, parent[1], 'water.chk')
    write = remote.copy_parent_chk(cfg, parent[1], m)
    assert read == remote.Command('parent_chk_metadata',
        f'{remote.path_checks(source)} && python3 -c {shlex.quote(SCRIPT)} metadata {shlex.quote(source)} -')
    assert write == remote.Command('copy_parent_chk',
        f'{remote.path_checks(source)} && test -f {shlex.quote(source)} && '
        f'{remote.path_checks(target)} && set -C && '
        f'python3 -c {shlex.quote(SCRIPT)} copy {shlex.quote(source)} {shlex.quote(target)}')
    assert READ_OPERATIONS == frozenset({'identity', 'queues', 'nodes', 'jobs', 'root_check', 'executable',
        'metadata', 'parent_chk_metadata', 'output_exists', 'listing', 'receipt', 'output_observation',
        'completion_marker', 'session_processes', 'slurm_jobs', 'slurm_accounting', 'slurm_find',
        'slurm_history', 'slurm_partitions', 'slurm_tools', 'storage_usage', 'parent_chk_environment',
        'slurm_evidence_config', 'slurm_evidence_version', 'slurm_evidence_job', 'slurm_evidence_history'})
    for command in (read, write):
        assert subprocess.run(['sh', '-n'], input=command.text, text=True).returncode == 0
    transport = SSHTransport(cfg, read_only=True)
    with pytest.raises(ValueError, match='refuses'):
        transport.run(write)
    calls = []
    transport = SSHTransport(cfg)
    monkeypatch.setattr(transport, '_execute', lambda *a: calls.append(a) or Result(255))
    monkeypatch.setattr('ag.transport.time.sleep', lambda *a: pytest.fail('must never retry'))
    assert transport.run(write).returncode == 255
    assert len(calls) == 1
    for bad in ('../escape.chk', 'x;bad.chk', 'water.log'):
        with pytest.raises(ValueError):
            remote.parent_chk_metadata(cfg, parent[1], bad)
    invalid = deepcopy(m)
    invalid['parent_chk']['target_name'] = 'water.chk'
    with pytest.raises(ValueError):
        remote.copy_parent_chk(cfg, parent[1], invalid)


@pytest.mark.parametrize('kind', ['source_link', 'source_directory_link', 'target_directory_link',
                                 'existing_file', 'dangling_link', 'fifo'])
def test_descriptor_helper_refuses_unsafe_paths(cfg, parent, tmp_path, kind):
    _, m = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    target_dir = Path(remote.attempt_dir(cfg, m))
    target_dir.mkdir()
    target = target_dir / 'parent.chk'
    original = fake.source.read_bytes()
    if kind == 'source_link':
        keep = fake.source.with_name('keep.chk')
        fake.source.rename(keep)
        fake.source.symlink_to(keep)
    elif kind in ('source_directory_link', 'target_directory_link'):
        directory = fake.source.parent if kind.startswith('source') else target_dir
        keep = directory.with_name(directory.name + '-keep')
        directory.rename(keep)
        directory.symlink_to(keep, target_is_directory=True)
    elif kind == 'existing_file':
        target.write_bytes(b'existing')
    elif kind == 'dangling_link':
        target.symlink_to(target_dir / 'absent.chk')
    else:
        os.mkfifo(target)
    # Bypass the preliminary shell test here to exercise open-time protection.
    # This remains a fake local transport operation with fixture-only paths.
    command = remote.Command('copy_parent_chk',
        f'{shlex.quote(sys.executable)} -c {shlex.quote(SCRIPT)} copy '
        f'{shlex.quote(str(fake.source))} {shlex.quote(str(target_dir))}')
    assert fake.run(command).returncode != 0
    assert fake.source.read_bytes() == original
    if kind == 'existing_file':
        assert target.read_bytes() == b'existing'


def test_no_attachment_regression(cfg, prepared, monkeypatch):
    p, m = prepared
    assert 'parent_chk' not in m and m['cluster'] == 'default'
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    submit.submit(cfg, [p.name], fake)
    assert fake.operations() == ['identity', 'jobs', 'jobs', 'create_attempt',
                                 'upload', 'metadata', 'upload', 'metadata', 'submit']


@pytest.mark.parametrize('race', ['source_link', 'directory_link', 'target_fifo'])
def test_open_time_replacement_is_rejected(cfg, parent, tmp_path, race):
    _, m = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    target_dir = Path(remote.attempt_dir(cfg, m))
    target_dir.mkdir()
    # Inject a local race immediately before the real open(), AFTER all shell
    # checks. No monkeypatched protection flags: the original open must refuse.
    if race == 'source_link':
        trigger = "name == 'water.chk'"
        fixture = str(fake.source)
        action = 'os.rename(fixture, fixture + "-keep"); os.symlink(fixture + "-keep", fixture)'
    elif race == 'directory_link':
        trigger = f'name == {fake.source.parent.name!r}'
        fixture = str(fake.source.parent)
        action = 'os.rename(fixture, fixture + "-keep"); os.symlink(fixture + "-keep", fixture)'
    else:
        trigger = "name == 'parent.chk'"
        fixture = str(target_dir / 'parent.chk')
        action = 'os.mkfifo(fixture)'
    injection = f'''
real_open = os.open
def raced_open(name, flags, *args, **kwargs):
    if {trigger}:
        fixture = {fixture!r}
        {action}
    return real_open(name, flags, *args, **kwargs)
os.open = raced_open
'''
    script = SCRIPT.replace('\ntry:\n    main()', injection + '\ntry:\n    main()')
    command = remote.Command('copy_parent_chk',
        f'{shlex.quote(sys.executable)} -c {shlex.quote(script)} copy '
        f'{shlex.quote(str(fake.source))} {shlex.quote(str(target_dir))}')
    assert fake.run(command).returncode != 0
    assert fake.source.read_bytes() == b'synthetic water checkpoint'
    if race != 'target_fifo':
        assert not (target_dir / 'parent.chk').exists()


def test_metadata_helper_pins_readonly_file_and_runs_stat_sha256(cfg, parent, tmp_path):
    fake = CheckpointFake(cfg, parent[1])
    # Portable substitutes for the two Linux utilities; validate the actual
    # argv/pass_fds and read from the opened descriptor, not from the pathname.
    injection = '''
import hashlib
def check_output(argv, *, pass_fds):
    assert len(pass_fds) == 1
    fd = pass_fds[0]
    pinned = '/proc/self/fd/' + str(fd)
    if argv[0] == 'stat':
        assert argv == ['stat', '-Lc', '%s', '--', pinned]
        return (str(os.fstat(fd).st_size) + '\\n').encode()
    assert argv == ['sha256sum', '--', pinned]
    return (hashlib.sha256(os.read(fd, 4096)).hexdigest() + '  ' + pinned + '\\n').encode()
subprocess.check_output = check_output
'''
    script = SCRIPT.replace('\ntry:\n    main()', injection + '\ntry:\n    main()')
    result = subprocess.run([sys.executable, '-c', script, 'metadata', str(fake.source), '-'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = fake.source.read_bytes()
    assert result.stdout == f'{len(data)}\n{sha256(data).hexdigest()}  {fake.source}\n'


def test_cancellation_does_not_copy_or_consume(cfg, parent, tmp_path, monkeypatch):
    p, _ = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    monkeypatch.setattr(confirm, 'confirm', lambda text: False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(cfg, [p.name], fake)
    assert fake.operations() == ['identity', 'jobs', 'parent_chk_metadata']
    assert state.read(p)['state'] == 'prepared' and not (p / '.submit-claim').exists()


def test_remote_script_uses_python36_syntax_and_subprocess_api():
    tree = ast.parse(SCRIPT, feature_version=(3, 6))
    # Restrict the remote subprocess surface to APIs/keywords present in 3.6.
    # Local transport/test processes still run on the declared Python >=3.11.
    allowed = {'check_output': {'pass_fds'}, 'run': {'stdin', 'stdout', 'check'}}
    seen = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'):
            assert node.func.attr in allowed
            assert {kw.arg for kw in node.keywords} <= allowed[node.func.attr]
            seen.append(node.func.attr)
    assert sorted(seen) == ['check_output', 'check_output', 'run']
    assert 'text=True' not in SCRIPT and 'capture_output' not in SCRIPT


@pytest.mark.parametrize('cluster', ['default', 'batch'])
@pytest.mark.parametrize('version,proc,expected', [('3.6.8', 'yes', True), ('3.11.15', 'yes', True),
                                                ('3.5.10', 'yes', False), ('3.6.8', 'no', False)])
def test_doctor_reports_checkpoint_environment(multi, cluster, version, proc, expected, capsys):
    from test_slurm import SlurmFake
    selected = config.select_cluster(multi, cluster)
    fake = SlurmFake(selected)
    original = fake.run
    def run(command):
        if command.operation == 'parent_chk_environment':
            fake.calls.append(command)
            return Result(stdout=f'Python {version}\nproc_fd={proc}\n')
        return original(command)
    fake.run = run
    result = doctor.doctor(selected, fake)
    assert result['ok'] is True
    assert result['parent_chk']['ok'] == expected
    assert result['parent_chk']['python_version'] == version
    assert result['parent_chk']['proc_fd'] == (proc == 'yes')
    assert bool(result['parent_chk']['note']) == (not expected)
    assert ('父 chk 功能不可用' in capsys.readouterr().err) == (not expected)
    assert set(fake.operations()) <= READ_OPERATIONS


@pytest.mark.parametrize('cluster', ['default', 'batch'])
def test_doctor_without_python_warns_and_cli_succeeds(multi, cluster, monkeypatch, capsys):
    from test_slurm import SlurmFake
    from test_core import write_config
    selected = config.select_cluster(multi, cluster)
    fake = SlurmFake(selected)
    original = fake.run
    fake.run = lambda command: (Result(127) if command.operation == 'parent_chk_environment'
                                else original(command))
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: fake)
    loaded = config.load_config(write_config(multi))
    monkeypatch.setattr(cli, 'load_config', lambda: loaded)
    assert cli.main(['doctor', '--cluster', cluster, '--json']) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['ok'] and not result['parent_chk']['ok']
    assert '父 chk 功能不可用' in output.err


@pytest.mark.parametrize('response', [Result(127), Result(1)])
def test_parent_chk_unavailable_refuses_before_confirmation(cfg, parent, tmp_path, monkeypatch, response):
    p, m = child(cfg, tmp_path, parent)
    fake = CheckpointFake(cfg, parent[1])
    original = fake.run
    def run(command):
        if command.operation == 'parent_chk_metadata':
            fake.calls.append(command)
            return response
        return original(command)
    fake.run = run
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: pytest.fail('unavailable parent chk must refuse'))
    with pytest.raises(TransportError):
        submit.submit(cfg, [p.name], fake)
    assert state.read(p)['state'] == 'prepared' and not (p / '.submit-claim').exists()
    assert 'submit' not in fake.operations() and 'copy_parent_chk' not in fake.operations()


@pytest.mark.parametrize('response', [Result(255), Result(1),
                                      Result(stdout='unexpected'), Result(stdout='Python 3.6.8\n')])
def test_doctor_environment_failures(cfg, response):
    fake = Fake(cfg)
    original = fake.run
    fake.run = lambda command: response if command.operation == 'parent_chk_environment' else original(command)
    with pytest.raises((ValueError, TransportError)):
        doctor.doctor(cfg, fake)


def test_environment_command_is_fixed_and_readonly(cfg, monkeypatch):
    command = remote.parent_chk_environment()
    assert command == remote.Command('parent_chk_environment',
        "python3 --version && if test -d /proc/self/fd && "
        "test -r /proc/self/fd/0; then printf 'proc_fd=yes\\n'; "
        "else printf 'proc_fd=no\\n'; fi")
    assert subprocess.run(['sh', '-n'], input=command.text, text=True).returncode == 0
    transport = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(transport, '_execute', lambda *a: Result(stdout='Python 3.6.8\nproc_fd=yes\n'))
    assert transport.run(command).returncode == 0


@pytest.mark.parametrize('tamper', ['job_id', 'manifest_sha256', 'cluster'])
def test_parent_submission_binding_tamper_is_rejected(cfg, parent, tmp_path, tamper):
    path = parent[0] / 'submission.json'
    value = json.loads(path.read_text())
    value[tamper] = 'mismatched'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Submission manifest/status/cluster mismatch'):
        child(cfg, tmp_path, parent)


def test_legacy_parent_is_bound_to_default(cfg, prepared, tmp_path):
    p, m = prepared
    m.pop('cluster')
    m.pop('scheduler')
    (p / 'manifest.json').write_text(json.dumps(m))
    state.write(p, 'submitting')
    state.write(p, 'submitted', job_id='42.fixture')
    state.write(p, 'finished')
    (p / 'final_input.xyz').write_text('3\nInput orientation\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    path, child_manifest = child(cfg, tmp_path, (p, m))
    assert child_manifest['parent_chk']['cluster'] == 'default'
    attempt.verified_files(cfg, path, child_manifest)
    with pytest.raises(ValueError, match='still present'):
        parent_chk.resolve(cfg, child_manifest, [{'job_id': '42.fixture'}])


def bound_slurm_parent(multi, tmp_path, parent):
    from ag import budget
    source = tmp_path / 'batch.gjf'
    source.write_text(INPUT)
    manifest = attempt.prepare(multi, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                               tier='simple', walltime='00:30:00', label='batch', cluster='batch')
    path = attempt.find(multi, manifest['attempt_id'])
    selected = config.select_cluster(multi, 'batch')
    budget.reserve(selected, manifest, budget.read(selected))
    submission.record(path, manifest, '42')
    state.write(path, 'submitting')
    state.write(path, 'submitted', job_id='batch:42')
    state.write(path, 'finished')
    budget.settle(selected, manifest, '00:00:00', job_id='42')
    (path / 'final_input.xyz').write_bytes((parent[0] / 'final_input.xyz').read_bytes())
    return path, manifest


@pytest.mark.parametrize('failure', [None, 'active_parent', 'copy_255'])
def test_slurm_parent_copy_retains_binding_and_budget(multi, parent, tmp_path, monkeypatch, failure):
    from ag import budget, cards
    monkeypatch.setattr(cards, 'directory', lambda: Path(__file__).resolve().parents[2] /
                        'skills-next/auto-g16-recipes/cards')
    from test_slurm import SlurmFake
    batch_parent = bound_slurm_parent(multi, tmp_path, parent)
    path, manifest = child(multi, tmp_path, batch_parent, cluster='batch', card='irc')
    assert manifest['scheduler'] == 'slurm' and manifest['card'] is not None
    class SlurmCheckpointFake(CheckpointFake, SlurmFake):
        pass
    fake = SlurmCheckpointFake(config.select_cluster(multi, 'batch'), batch_parent[1])
    monkeypatch.setattr(confirm, 'confirm', lambda *a: True)
    if failure == 'active_parent':
        fake.queue = Result(stdout='42|parent|fixture|RUNNING|8|00:00|fixture\n')
        with pytest.raises(ValueError, match='still present'):
            submit.submit(multi, [path.name], fake)
        assert 'create_attempt' not in fake.operations()
    elif failure == 'copy_255':
        fake.copy_result = Result(255)
        with pytest.raises(TransportError):
            submit.submit(multi, [path.name], fake)
        assert state.read(path)['state'] == 'failed_presubmit'
        assert budget.totals(fake.cfg) == (0, 0)
        assert 'submit' not in fake.operations()
        assert fake.operations().count('copy_parent_chk') == 1
        assert not (path / 'submission.json').exists()
    else:
        submit.submit(multi, [path.name], fake)
        assert state.read(path)['job_id'] == 'batch:123'
        assert submission.verified_job(path, manifest, state.read(path)) == '123'
        assert 'sbatch --parsable job.slurm' in fake.calls[-1].text
        assert fake.operations().count('copy_parent_chk') == 1
        assert budget.totals(fake.cfg) == (0, 8 * 30 * 60)
        assert 'nodes' not in fake.operations() and 'jobs' not in fake.operations()
        assert attempt.read_manifest(path) == manifest


@pytest.fixture
def multiwfn_child(cfg, parent, tmp_path, monkeypatch):
    from ag import nci_report
    cfg['programs']['multiwfn'] = str(tmp_path / 'Multiwfn')
    fragment_file = tmp_path / 'fragments.csv'
    fragment_file.write_text('fragment,atoms\noxygen,1\nhydrogen,2-3\n')
    context = dict(attempt_id=parent[0].name, manifest_sha256='a'*64,
                   log_file='outputs/water.log', log_sha256='b'*64,
                   route='# HF/STO-3G', method_basis='兜底方法：合成测试',
                   charge=0, multiplicity=1, geometry='O 0 0 0\nH 0 0 1\nH 0 1 0', symbols=['O','H','H'])
    monkeypatch.setattr(nci_report, '_parent_context', lambda *a: context)
    return child(cfg, tmp_path, parent, template='multiwfn', input_path=None,
                 analysis='igmh', grid='medium', fragments=fragment_file)


def test_multiwfn_existing_exclusive_chk_copy(cfg, parent, multiwfn_child, monkeypatch):
    p, m = multiwfn_child
    fake = CheckpointFake(cfg, parent[1])
    original = fake.source.read_bytes()
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(cfg, [p.name], fake)
    assert fake.source.read_bytes() == original
    assert (Path(remote.attempt_dir(cfg, m)) / 'parent.chk').read_bytes() == original
    assert fake.operations().count('copy_parent_chk') == 1
    assert fake.operations().count('parent_chk_metadata') == 3
    with pytest.raises(ValueError, match='consumed'):
        submit.submit(cfg, [p.name], fake)


@pytest.mark.parametrize('failure', ['same_attempt', 'other_study', 'other_cluster', 'scheduler_present', 'different_target'])
def test_multiwfn_parent_checks_unchanged(cfg, parent, multiwfn_child, failure):
    _, original = multiwfn_child
    m = deepcopy(original)
    jobs = None
    if failure == 'same_attempt':
        m['attempt_id'] = parent[0].name
    elif failure == 'other_study':
        m['study_id'] = 'different'
    elif failure == 'other_cluster':
        m['parent_chk']['cluster'] = 'different'
    elif failure == 'different_target':
        m['parent_chk']['target_name'] = 'different.chk'
    else:
        jobs = [{'job_id': '42.fixture'}]
    with pytest.raises(ValueError):
        parent_chk.resolve(cfg, m, jobs)


def test_multiwfn_chk_hash_mismatch_retains_single_attempt(cfg, parent, multiwfn_child, monkeypatch):
    p, _ = multiwfn_child
    fake = CheckpointFake(cfg, parent[1])
    fake.corrupt = True
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    with pytest.raises(ValueError, match='hash/size changed'):
        submit.submit(cfg, [p.name], fake)
    assert fake.operations().count('copy_parent_chk') == 1
    assert 'submit' not in fake.operations()
    assert state.read(p)['state'] == 'failed_presubmit'
