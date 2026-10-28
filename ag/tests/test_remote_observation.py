"""T175: synthetic local files and fake transports only; never SSH.

Linux executes the complete generated command with native O_PATH. On macOS,
the explicit adapter substitutes O_RDONLY for O_PATH (directory-read permission
is then required); it does NOT prove Linux runtime/search-only compatibility.
"""
import ast
import errno
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ag import fetch, nci_report, remote, state, status
from ag.observation_remote import SCRIPT
from ag.transport import Result, TransportError
from test_core import cfg, prepared
from test_completion import submitted
from test_incomplete_fetch import cancelled
from test_slurm import multi, submitted as slurm_submitted


def run_local(command):
    prefix = ''
    if sys.platform != 'linux':
        wrapper = ('import os,sys; os.O_PATH=os.O_RDONLY; '
                   'offset=sys.argv.index("-c",1)+1; source=sys.argv[offset]; sys.argv=sys.argv[offset:]; '
                   'exec(compile(source,"<adapted-observation>","exec"))')
        prefix = 'python3() { ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(wrapper) + ' "$@"; };\n'
        # Only the unchanged strict observer still invokes GNU-format stat.
        prefix += r'''
stat() {
  ag_size=$(command stat -f %z "$4") || return
  printf '%s 2026-01-01 00:00:00.000000001 +0000\n' "$ag_size"
}
'''
    p = subprocess.run(['sh', '-c', prefix + command.text], capture_output=True,
                       text=True, timeout=5)
    return Result(p.returncode, p.stdout, p.stderr)


@pytest.fixture
def local_files(tmp_path):
    root = tmp_path.resolve()
    cfg = {'remote': {'ag_root': str(root / 'ag')}}
    manifest = dict(study_id='smoke', attempt_id='smoke-001-sp',
                    remote_dir='smoke/smoke-001-sp', template='gaussian',
                    inputs=[{'name': 'water.gjf'}], scheduler='pbs')
    directory = Path(remote.attempt_dir(cfg, manifest))
    directory.mkdir(parents=True)
    for name in ('ag-start.json', 'ag-exit.json'):
        key = 'started_at' if name == 'ag-start.json' else 'finished_at'
        (directory / name).write_text(json.dumps(dict(
            PBS_JOBID='123.fixture', job_id='123', returncode=0,
            **{key: '2026-01-01T00:00:00+08:00'})) + '\n')
    for name in ('water.log', 'job.pbs.out', 'job.slurm.out', 'job.slurm.err'):
        (directory / name).write_bytes(b'synthetic water output\n')
    return cfg, manifest, directory


CASES = ['present', 'missing', 'file_000', 'parent_000', 'ancestor_000',
         'parent_missing', 'not_directory', 'symlink', 'dangling_symlink',
         'parent_symlink', 'directory', 'fifo']


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('kind', ['ag-start.json', 'ag-exit.json', 'output', 'incomplete'])
@pytest.mark.parametrize('case', CASES)
def test_filesystem_matrix(local_files, scheduler, kind, case):
    cfg, manifest, directory = local_files
    manifest['scheduler'] = scheduler
    target = directory / (kind if kind.endswith('.json') else 'water.log')
    blocked = None
    if case == 'missing':
        target.unlink()
    elif case.endswith('_000'):
        blocked = {'file_000': target, 'parent_000': directory,
                   'ancestor_000': directory.parent}[case]
        blocked.chmod(0)
    elif case in ('parent_missing', 'not_directory', 'parent_symlink'):
        saved = directory.with_name('saved')
        directory.rename(saved)
        if case == 'not_directory':
            directory.write_text('not a directory')
        elif case == 'parent_symlink':
            directory.symlink_to(saved, target_is_directory=True)
    elif case in ('symlink', 'dangling_symlink', 'directory', 'fifo'):
        target.unlink()
        if case == 'symlink':
            target.symlink_to(directory / 'job.pbs.out')
        elif case == 'dangling_symlink':
            target.symlink_to(directory / 'missing')
        elif case == 'directory':
            target.mkdir()
        else:
            os.mkfifo(target)
    try:
        if case in ('parent_000', 'ancestor_000'):
            if os.access(directory, os.X_OK):
                pytest.skip('root/ACL permits traversal despite mode 000')
            with pytest.raises(OSError) as error:
                target.stat()
            assert error.value.errno == errno.EACCES
        if case == 'file_000':
            if os.access(target, os.R_OK):
                pytest.skip('root/ACL permits reading despite mode 000')
            assert target.stat().st_size > 0  # metadata still visible
        if case == 'not_directory':
            with pytest.raises(OSError) as error:
                target.stat()
            assert error.value.errno == errno.ENOTDIR
        if kind.endswith('.json'):
            command = remote.receipt(cfg, manifest, kind)
        elif kind == 'output':
            command = remote.output_observation(cfg, manifest)
        else:
            command = remote.incomplete_output_observation(cfg, manifest, 'water.log')
        result = run_local(command)
        ok = (case in ('present', 'missing') or
              (case == 'parent_missing' and kind != 'incomplete') or
              (case == 'file_000' and kind == 'output'))
        assert (result.returncode == 0) == ok, result.stderr
        if not ok:
            assert result.stdout == ''
            if kind != 'incomplete':
                assert result.stderr.startswith('observation ')
                assert str(directory) not in result.stderr
        elif case in ('missing', 'parent_missing'):
            assert 'absent\n' in result.stdout
        elif kind.endswith('.json'):
            assert result.stdout == target.read_text()
        else:
            assert '2026-' in result.stdout or ' +0000' in result.stdout
    finally:
        if blocked:
            blocked.chmod(0o600 if case == 'file_000' else 0o700)


@pytest.fixture
def helper(monkeypatch):
    module = ModuleType('fixed_observation')
    exec(compile(SCRIPT, '<fixed-observation>', 'exec'), module.__dict__)
    if sys.platform != 'linux':
        monkeypatch.setattr(os, 'O_PATH', os.O_RDONLY, raising=False)
    return module


@pytest.mark.parametrize('name', ['ag-start.json', 'ag-exit.json'])
@pytest.mark.parametrize('replacement', ['regular', 'symlink', 'parent', 'fifo'])
@pytest.mark.parametrize('timing', ['before_open', 'after_open', 'before_read'])
def test_receipt_replacement_never_reads_replacement(local_files, helper, monkeypatch,
                                                   name, replacement, timing):
    _, _, directory = local_files
    target = directory / name
    old = target.read_bytes()
    changed = old.replace(b'2026-01-01', b'2026-01-02')
    assert len(old) == len(changed)
    before = (target.stat().st_dev, target.stat().st_ino)
    substitute = directory / 'substitute'
    if replacement == 'symlink':
        other = directory / 'other.json'
        other.write_bytes(changed)
        substitute.symlink_to(other)
    elif replacement == 'fifo':
        os.mkfifo(substitute)
    else:
        substitute.write_bytes(changed)
    mutated, read_bytes = [], []
    real_open, real_read = os.open, os.read

    def mutate():
        if mutated:
            return
        mutated.append(True)
        if replacement == 'parent':
            directory.rename(directory.with_name('saved'))
            directory.mkdir()
            target.write_bytes(changed)
        else:
            substitute.replace(target)

    def injected_open(path, flags, *args, **kwargs):
        if path == name and timing == 'before_open':
            mutate()
        fd = real_open(path, flags, *args, **kwargs)
        if path == name and timing == 'after_open':
            mutate()
        return fd

    def injected_read(fd, count):
        if timing == 'before_read':
            mutate()
        data = real_read(fd, count)
        read_bytes.append(data)
        return data

    monkeypatch.setattr(os, 'open', injected_open)
    monkeypatch.setattr(os, 'read', injected_read)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {injected_open})
    code, data, error = helper.execute('receipt', str(directory), [name])
    assert mutated and before != (target.lstat().st_dev, target.lstat().st_ino)
    assert code != 0 and data == b'' and 'observation ' in error
    assert changed not in b''.join(read_bytes)
    if timing == 'before_open':
        assert not read_bytes


@pytest.mark.parametrize('name', ['ag-start.json', 'ag-exit.json'])
@pytest.mark.parametrize('case', ['boundary', 'oversize', 'grow', 'shrink', 'partial_error'])
def test_receipt_bounded_read(local_files, helper, monkeypatch, name, case):
    _, _, directory = local_files
    target = directory / name
    raw = target.read_bytes().rstrip(b'\n')
    expected = raw + b' ' * (4096 - len(raw))
    target.write_bytes(expected + (b' ' if case == 'oversize' else b''))
    real_read, calls = os.read, []

    def read(fd, count):
        calls.append(count)
        if len(calls) == 1:
            if case == 'grow':
                with target.open('ab') as handle:
                    handle.write(b' ')
            elif case == 'shrink':
                target.write_bytes(raw)
        if case == 'partial_error':
            if len(calls) > 1:
                raise OSError(errno.EIO, 'synthetic read failure')
            count = 8
        return real_read(fd, count)

    monkeypatch.setattr(os, 'read', read)
    code, data, error = helper.execute('receipt', str(directory), [name])
    assert (code == 0) == (case == 'boundary')
    assert data == (expected if case == 'boundary' else b'')
    assert all(count <= 4097 for count in calls)
    if case == 'partial_error':
        assert 'receipt-read EIO' in error


@pytest.mark.skipif(sys.platform != 'linux', reason='native O_PATH search-only directory semantics require Linux')
@pytest.mark.parametrize('mode', ['receipt', 'output'])
def test_search_only_directories_need_no_listing(local_files, mode):
    cfg, manifest, directory = local_files
    directory.chmod(0o111)
    directory.parent.chmod(0o111)
    try:
        if os.access(directory, os.R_OK):
            pytest.skip('root/ACL permits listing; cannot verify search-only fixture')
        assert os.access(directory, os.X_OK)
        cmd = remote.receipt(cfg, manifest, 'ag-start.json') if mode == 'receipt' else remote.output_observation(cfg, manifest)
        result = run_local(cmd)
        assert result.returncode == 0, result.stderr
    finally:
        directory.parent.chmod(0o700)
        directory.chmod(0o700)


@pytest.mark.parametrize('fault', ['version', 'flag', 'dir_fd', 'no_python'])
def test_runtime_failure_is_not_absence(local_files, helper, monkeypatch, fault):
    cfg, manifest, directory = local_files
    if fault == 'no_python':
        command = remote.receipt(cfg, manifest, 'ag-start.json')
        result = subprocess.run(['/bin/sh', '-c', command.text], env={'PATH': str(directory / 'no-tools')},
                                capture_output=True, text=True, timeout=5)
        assert result.returncode != 0 and result.stdout == ''
        assert result.stderr == 'observation runtime PYTHON_MISSING\n'
        return
    if fault == 'version':
        monkeypatch.setattr(sys, 'version_info', (3, 5, 10))
    elif fault == 'flag':
        monkeypatch.delattr(os, 'O_PATH')
    else:
        monkeypatch.setattr(os, 'supports_dir_fd', set())
    code, data, error = helper.execute('receipt', str(directory), ['ag-start.json'])
    assert code != 0 and data == b'' and error.startswith('observation runtime ')


@pytest.mark.parametrize('error_number', [errno.EACCES, errno.ENOTDIR, errno.EIO])
def test_stat_failure_uses_errno_not_language(local_files, helper, monkeypatch, error_number):
    _, _, directory = local_files
    real_stat = os.stat

    def failed_stat(name, *args, **kwargs):
        if name == 'water.log':
            raise OSError(error_number, 'No such file or directory')
        return real_stat(name, *args, **kwargs)

    monkeypatch.setattr(os, 'stat', failed_stat)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {failed_stat})
    monkeypatch.setattr(os, 'supports_follow_symlinks', os.supports_follow_symlinks | {failed_stat})
    code, data, error = helper.execute('output', str(directory), ['job.pbs.out', 'water.log'])
    assert code != 0 and data == b'' and errno.errorcode[error_number] in error
    assert 'No such' not in error


@pytest.mark.parametrize('kind', ['receipt', 'output', 'incomplete'])
@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('response', ['valid', 'absent', 'unverifiable', 'nonzero', 'valid_nonzero', 'ssh255', 'lost'])
def test_three_parsers_reject_failure_before_stdout(local_files, kind, scheduler, response):
    cfg, manifest, directory = local_files
    manifest['scheduler'] = scheduler
    name = 'ag-start.json'
    value = (directory / name).read_text() if kind == 'receipt' else '4 2026-01-01 00:00:00.000000001 +0000\n'
    if response == 'absent':
        value = 'absent\n'
    elif response == 'unverifiable':
        value = 'unreadable\n'
    elif response == 'nonzero':
        value = ''
    if kind == 'output':
        value = ''.join(n + ' ' + value for n in remote.output_names(manifest))
    code = 255 if response == 'ssh255' else (1 if response in ('nonzero', 'valid_nonzero') else 0)

    def run(command):
        if response == 'lost':
            raise TransportError('synthetic response failure')
        return Result(code, value, 'observation file-stat EIO' if code else '')

    fake = SimpleNamespace(run=run)
    def parse():
        if kind == 'receipt':
            return status.read_receipt(cfg, manifest, fake, name, '123' if scheduler == 'slurm' else '123.fixture')
        return (status.outputs if kind == 'output' else fetch._presence)(cfg, manifest, fake)
    if response in ('valid', 'absent'):
        result = parse()
        if response == 'absent':
            assert result is None or all(v is None for v in result.values())
    else:
        with pytest.raises(ValueError if response == 'unverifiable' else TransportError):
            parse()


@pytest.mark.parametrize('current', ['submitted', 'running', 'cancelled', 'finished', 'fetched'])
@pytest.mark.parametrize('failed_at', ['start', 'exit', 'output'])
@pytest.mark.parametrize('targeted', [False, True])
def test_pbs_observation_failure_keeps_exact_status(cfg, prepared, monkeypatch, current, failed_at, targeted):
    path, manifest, fake = submitted(prepared, cfg)
    if targeted:
        # Synthetic binding: bypass prepare's unrelated node discovery.
        manifest['node_target'] = {'name': 'node-a', 'fraction': '1/2', 'slots': 16, 'queue': 'batch'}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        # Binding is immutable in production; re-seed this synthetic submission.
        record = json.loads((path / 'submission.json').read_text())
        from hashlib import sha256
        record['manifest_sha256'] = sha256((path / 'manifest.json').read_bytes()).hexdigest()
        (path / 'submission.json').write_text(json.dumps(record))
        monkeypatch.setattr('ag.node_targeting.retain_placement',
                            lambda *args: pytest.fail('placement must not write before observations succeed'))
    if current == 'fetched':
        state.write(path, 'finished')
    state.write(path, current, observation={'preserved': True}, unchanged_since=1,
                incomplete_observations=[{'preserved': True}])
    before = (path / 'status.json').read_bytes()
    original = fake.run

    def failed(command):
        if ((command.operation == 'receipt' and ('ag-' + failed_at + '.json') in command.text)
                or (command.operation == 'output_observation' and failed_at == 'output')):
            return Result(1, 'absent\n', 'observation file-stat EACCES')
        return original(command)

    monkeypatch.setattr(fake, 'run', failed)
    with pytest.raises(TransportError, match='EACCES'):
        status.check(cfg, path, fake)
    assert (path / 'status.json').read_bytes() == before


@pytest.mark.parametrize('targeted', [False, True])
def test_legacy_second_output_failure_keeps_status(cfg, prepared, monkeypatch, targeted):
    if targeted:
        path, manifest = prepared
        manifest['node_target'] = {'name': 'node-a', 'fraction': '1/2', 'slots': 16, 'queue': 'batch'}
        (path / 'manifest.json').write_text(json.dumps(manifest))
        monkeypatch.setattr('ag.node_targeting.retain_placement', lambda *args: None)
    path, manifest, fake = submitted(prepared, cfg, legacy=True)
    fake.job = Result(153)
    fake.marker = 'present\n'
    monkeypatch.setattr(status.time, 'time', lambda: 1000)
    status.check(cfg, path, fake)
    before = (path / 'status.json').read_bytes()
    if targeted:
        monkeypatch.setattr('ag.node_targeting.retain_placement',
                            lambda *args: pytest.fail('placement must wait for the second output observation'))
    monkeypatch.setattr(status.time, 'time', lambda: 1061)
    original, observations = fake.run, []

    def failed(command):
        if command.operation == 'output_observation':
            observations.append(command)
            if len(observations) == 2:
                return Result(1, 'water.log absent\n', 'observation file-stat EIO')
        return original(command)

    monkeypatch.setattr(fake, 'run', failed)
    with pytest.raises(TransportError, match='EIO'):
        status.check(cfg, path, fake)
    assert len(observations) == 2 and (path / 'status.json').read_bytes() == before


def test_slurm_status_does_not_claim_receipt_coverage(multi, tmp_path, monkeypatch):
    path, _, fake = slurm_submitted(multi, tmp_path, monkeypatch)
    assert status.check(multi, path, fake)['state'] == 'finished'
    assert fake.operations() == ['identity', 'slurm_jobs', 'slurm_accounting']


@pytest.mark.parametrize('cancelled', ['pbs', 'slurm'], indirect=True)
def test_cancelled_incomplete_rejects_unverifiable_presence(cancelled, monkeypatch):
    cfg, path, _, fake = cancelled
    before, original = (path / 'status.json').read_bytes(), fake.run

    def failed(command):
        if command.operation == 'output_observation':
            return Result(1, 'absent\n', 'observation directory-stat EACCES')
        return original(command)

    monkeypatch.setattr(fake, 'run', failed)
    with pytest.raises(TransportError):
        fetch.fetch(cfg, path, fake, incomplete=True)
    assert fake.downloaded == [] and (path / 'status.json').read_bytes() == before


def test_fixed_command_arguments_and_syntax(local_files):
    cfg, manifest, _ = local_files
    ast.parse(SCRIPT, feature_version=(3, 6))
    for command in (remote.receipt(cfg, manifest, 'ag-start.json'), remote.output_observation(cfg, manifest)):
        assert subprocess.run(['sh', '-n'], input=command.text, text=True, capture_output=True).returncode == 0
        assert ' /proc/' not in command.text
        assert command.operation in ('receipt', 'output_observation')
    for name in ('water.log', '../ag-start.json', 'ag-start.json;evil', '/ag-start.json'):
        with pytest.raises(ValueError):
            remote.receipt(cfg, manifest, name)
    for value in ('../escape', '/elsewhere', 'smoke/a;evil'):
        with pytest.raises(ValueError):
            remote.output_observation(cfg, {**manifest, 'remote_dir': value})


@pytest.mark.parametrize('frames,fragments', [(1, 2), (3, 3), (50, 4)])
@pytest.mark.parametrize('bad', [False, True])
def test_multiwfn_real_layout_all_or_nothing(local_files, frames, fragments, bad):
    cfg, manifest, directory = local_files
    manifest.update(template='multiwfn', science=dict(
        n_frames=frames, nci=dict(analysis='igm', grid='medium',
                                 fragments=[{'atoms': [i]} for i in range(fragments)])))
    actual_frames, pairs = nci_report.layout(manifest)
    names = remote.output_names(manifest)
    assert actual_frames == frames and len(pairs) == fragments * (fragments - 1) // 2
    for i, name in enumerate(names):
        if i % 3 != 2:
            (directory / name).write_text('synthetic output')
    if bad:
        # Last file fails after a full valid prefix; no prefix may escape.
        target = directory / names[-1]
        target.unlink(missing_ok=True)
        target.symlink_to(directory / 'missing')
    command = remote.output_observation(cfg, manifest)
    assert len(command.text.encode()) < 64 * 1024
    result = run_local(command)
    if bad:
        assert result.returncode != 0 and result.stdout == ''
    else:
        parsed = status.outputs(cfg, manifest, SimpleNamespace(run=lambda _: result))
        assert len(parsed) == len(names)
        assert parsed[names[2]] is None and parsed[names[0]]['size'] > 0


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('name', ['ag-start.json', 'ag-exit.json'])
@pytest.mark.parametrize('case', ['valid', 'duplicate', 'wrong_job', 'no_timezone', 'bad_returncode'])
def test_receipt_parser_compatibility(local_files, scheduler, name, case):
    cfg, manifest, directory = local_files
    manifest['scheduler'] = scheduler
    raw = (directory / name).read_text()
    if case == 'duplicate':
        raw = raw.replace('{', '{"returncode": 0,', 1)
    elif case == 'wrong_job':
        raw = raw.replace('123', '456')
    elif case == 'no_timezone':
        raw = raw.replace('+08:00', '')
    elif case == 'bad_returncode':
        raw = raw.replace('"returncode": 0', '"returncode": 256')
    fake = SimpleNamespace(run=lambda _: Result(0, raw))
    def parse():
        return status.read_receipt(cfg, manifest, fake, name,
                                   '123' if scheduler == 'slurm' else '123.fixture')
    if case == 'valid' or (case == 'bad_returncode' and name == 'ag-start.json'):
        assert parse()
    else:
        with pytest.raises(ValueError):
            parse()


@pytest.mark.parametrize('kind', ['output', 'receipt'])
def test_directory_link_replacement_before_open(local_files, helper, monkeypatch, kind):
    _, _, directory = local_files
    real_open = os.open
    replaced = []

    def replaced_open(name, flags, *args, **kwargs):
        if name == directory.name and not replaced:
            saved = directory.with_name('saved')
            directory.rename(saved)
            directory.symlink_to(saved, target_is_directory=True)
            replaced.append(True)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(os, 'open', replaced_open)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {replaced_open})
    code, data, error = helper.execute(kind, str(directory),
                                      ['water.log'] if kind == 'output' else ['ag-start.json'])
    assert replaced and code != 0 and data == b'' and 'directory-open' in error


def test_output_identity_change_rejects_metadata(local_files, helper, monkeypatch):
    _, _, directory = local_files
    real_stat, seen = os.stat, []

    def replaced_stat(name, *args, **kwargs):
        result = real_stat(name, *args, **kwargs)
        if name == 'water.log' and not seen:
            replacement = directory / 'replacement'
            replacement.write_text('synthetic replacement')
            replacement.replace(directory / name)
            seen.append(True)
        return result

    monkeypatch.setattr(os, 'stat', replaced_stat)
    monkeypatch.setattr(os, 'supports_dir_fd', os.supports_dir_fd | {replaced_stat})
    monkeypatch.setattr(os, 'supports_follow_symlinks', os.supports_follow_symlinks | {replaced_stat})
    code, data, error = helper.execute('output', str(directory), ['water.log'])
    assert seen and code != 0 and data == b'' and 'FILE_CHANGED' in error


def test_metadata_preserves_nanoseconds_in_utc(local_files):
    cfg, manifest, directory = local_files
    nanos = 1767225600123456789
    os.utime(directory / 'water.log', ns=(nanos, nanos))
    result = run_local(remote.output_observation(cfg, manifest))
    assert result.returncode == 0, result.stderr
    parsed = status.outputs(cfg, manifest, SimpleNamespace(run=lambda _: result))
    # macOS/APFS may store fewer digits; compare to what the real filesystem kept.
    actual = (directory / 'water.log').stat().st_mtime_ns % 10**9
    assert parsed['water.log']['mtime'] == f'2026-01-01 00:00:00.{actual:09d} +0000'


def test_quoted_root_cannot_execute_shell(local_files):
    cfg, manifest, directory = local_files
    unusual = directory.parent.parent.with_name("ag'$(false); spaced")
    directory.parent.parent.rename(unusual)
    cfg['remote']['ag_root'] = str(unusual)
    result = run_local(remote.receipt(cfg, manifest, 'ag-start.json'))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['PBS_JOBID'] == '123.fixture'
