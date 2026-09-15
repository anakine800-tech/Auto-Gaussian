#!/usr/bin/env python3
"""Bounded Linux evidence. No execution without exact frozen binding + run scope.

Never downloads, invokes scheduler/network/chemistry, deletes files, retries a
case, mutates candidate code, or uses monkeypatches. All scratch is retained.
"""
import argparse
import base64
import ctypes
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import re
import signal
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
MAX_CASES = 28
CASE_SECONDS = 45
TOTAL_SECONDS = 1500
MAX_FILE_BYTES = 12 * 1024 * 1024
REMOTE = Path('/home/user100/SDL')
ACTOR = Path('/opt/auto-g16-fixtures/bin/xtb')


def check(value, message):
    if not value:
        raise AssertionError(message)


def closed_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            check(key not in result, 'duplicate binding/scope key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('noninteger binding/scope number')
    return json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() + b'\n'


def digest(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def write(path, raw):
    check(len(raw) <= MAX_FILE_BYTES, 'evidence file limit')
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def save(path, value):
    write(path, canonical(value))


def require_chain(path):
    check(path.is_absolute() and str(path) == os.path.normpath(path), 'noncanonical path')
    current = Path('/')
    for part in path.parts[1:]:
        current /= part
        st = current.lstat()
        check(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode), 'unsafe directory chain: ' + str(current))


def proc_identity(pid):
    try:
        raw = Path(f'/proc/{pid}/stat').read_text()
    except FileNotFoundError:
        return None
    fields = raw[raw.rfind(')') + 2:].split()
    return dict(pid=pid, state=fields[0], ppid=int(fields[1]), pgrp=int(fields[2]), session=int(fields[3]), start_ticks=int(fields[19]))


def own_signal(info, sig):
    current = proc_identity(info['pid'])
    check(current and current['start_ticks'] == info['start_ticks'], 'PID identity drift')
    fd = os.pidfd_open(info['pid'])
    try:
        current = proc_identity(info['pid'])
        check(current and current['start_ticks'] == info['start_ticks'], 'pidfd identity drift')
        signal.pidfd_send_signal(fd, sig)
    finally:
        os.close(fd)


def direct_children():
    raw = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children').read_text()
    return [int(pid) for pid in raw.split()]


def collect_owned(seconds):
    """Only direct/adopted children of this otherwise child-free supervisor.

    Exact WNOHANG waitpid per PID; no -1 wait, no unrelated process signalling.
    Compiler containment separately retains the GNU timeout process-group cap.
    """
    events, errors = [], []
    end = time.monotonic() + seconds
    signalled = set()
    while time.monotonic() < end:
        children = direct_children()
        if not children:
            return events, errors
        for pid in children:
            info = proc_identity(pid)
            if not info:
                continue
            try:
                check(info['ppid'] == os.getpid(), 'not a supervisor child')
                waited, status = os.waitpid(pid, os.WNOHANG)
                if waited:
                    events.append(dict(identity=info, action='reap', wait_status=status))
                elif (pid, info['start_ticks']) not in signalled:
                    own_signal(info, signal.SIGKILL)
                    signalled.add((pid, info['start_ticks']))
                    events.append(dict(identity=info, action='owned-watchdog-SIGKILL'))
            except BaseException as exc:
                errors.append(dict(pid=pid, error=repr(exc)))
        time.sleep(0.01)
    errors.append(dict(error='owned-child reap deadline', remaining=direct_children()))
    return events, errors


def wait_for(predicate, seconds, label):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError('bounded wait: ' + label)


def event(path):
    try:
        raw = path.read_bytes()
        check(len(raw) < 4096, 'actor event cap')
        return json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def deadline(signum, frame):
    raise TimeoutError('hard wall-clock ceiling')


def verify_binding(args):
    raw = args.binding.read_bytes()
    check(digest(raw)['sha256'] == args.binding_sha256, 'binding SHA mismatch')
    lock = closed_json(raw)
    check(lock['state'] == 'FROZEN_FOR_REVIEW', 'source/fixture not frozen')
    check(lock['candidate']['head'] and lock['candidate']['tree'], 'candidate missing')
    check(not sys.flags.optimize, 'assertions must be enabled')
    check(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode, 'require -I -S -B')
    check(sys.platform == 'linux', 'real Linux required')
    outer = Path(f'/proc/{os.getppid()}/cmdline').read_bytes().split(b'\0')
    check(outer[:4] == [b'/usr/bin/timeout', b'--signal=TERM', b'--kill-after=15s', b'1500s'], 'required 1500s outer watchdog with 15s cleanup grace')
    check(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'pidfd required')
    sys.path.insert(0, str(HERE))
    from hosted_support import verify_package, replay_scope
    verify_package(HERE, lock)
    repo = args.candidate.absolute()
    require_chain(repo)
    def git(*argv):
        return subprocess.check_output(['/usr/bin/git', '-C', str(repo), *argv], timeout=10, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'})
    check(git('rev-parse', 'HEAD').decode().strip() == lock['candidate']['head'], 'HEAD mismatch')
    check(git('rev-parse', 'HEAD^{tree}').decode().strip() == lock['candidate']['tree'], 'tree mismatch')
    check(not git('status', '--porcelain=v1', '--untracked-files=all'), 'candidate dirty')
    tracked = git('ls-files', 'auto_g16', 'tests', 'scripts/run_v31_publisher_pilot.py').decode().splitlines()
    check(set(tracked) == set(lock['candidate']['files']), 'complete candidate fixture/import inventory required')
    for rel, expected in lock['candidate']['files'].items():
        check(not (repo / rel).is_symlink(), 'candidate file symlink')
        check(digest((repo / rel).read_bytes()) == expected, 'candidate file SHA mismatch: ' + rel)
    scope_raw = args.run_scope.read_bytes()
    check(digest(scope_raw)['sha256'] == args.run_scope_sha256, 'run scope SHA mismatch')
    scope, platform = replay_scope(HERE, lock, args.binding_sha256, scope_raw)
    check(str(Path(sys.executable).resolve(strict=True)) == platform['tools']['python']['path'], 'observed Python path drift')
    check(digest(Path(sys.executable).read_bytes()) == {k: platform['tools']['python'][k] for k in ('sha256', 'size_bytes')}, 'observed Python bytes drift')
    for path, expected in platform['fixture_roots'].items():
        require_chain(Path(path))
        observed = Path(path).lstat()
        check(dict(device=observed.st_dev, inode=observed.st_ino, uid=observed.st_uid, gid=observed.st_gid, mode=stat.S_IMODE(observed.st_mode)) == expected, 'provisioned fixture identity drift')
    check(re.fullmatch('r4-inert-[a-z0-9-]{1,64}', scope['project_prefix']), 'invalid fixed project prefix')
    check(scope['binding_sha256'] == args.binding_sha256, 'scope references another binding')
    check(scope['evidence'] == str(args.evidence.absolute()), 'evidence root not scoped')
    check(scope['actor_path'] == str(ACTOR) and scope['remote_parent'] == str(REMOTE), 'fixed fixture roots')
    check(scope['case_names'] and len(scope['case_names']) <= MAX_CASES, 'finite cases required')
    check(scope['case_names'][0] == 'host_match', 'real matching host control must run first')
    check(len(scope['case_names']) == len(set(scope['case_names'])), 'duplicate case retry')
    check(scope['total_seconds'] == TOTAL_SECONDS and scope['case_seconds'] == CASE_SECONDS, 'budget drift')
    check(scope['cleanup'] == 'owned-pidfd-kill-and-exact-waitpid-only-retain-all-files', 'cleanup scope')
    # Runtime replay binds actual observations to the committed Owner attachment
    # and reviewed static plan. It grants no production authority.
    sys.path[:0] = [str(HERE), str(repo)]
    wrapper = importlib.import_module('auto_g16.execution._program_completion_wrapper')
    check(digest(wrapper._PUBLISHER_WRAPPER_SOURCE.encode()) == lock['source'], 'new source mismatch')
    check(digest(wrapper._PUBLISHER_PROBE_SOURCE.encode()) == lock['probe'], 'probe source mismatch')
    check(digest(wrapper._WRAPPER_SOURCE.encode()) == lock['historical_source'], 'historical source drift')
    return lock, scope, git


def compile_actor(root):
    target = root / 'inert-actor'
    command = ['/usr/bin/timeout', '--signal=KILL', '30s', '/usr/bin/cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', str(HERE / 'r4_actor.c'), '-o', str(target)]
    save(root / 'build-intent.json', dict(command=command, timeout_group_seconds=30, supervisor_wait_seconds=35,
         cc=digest(Path('/usr/bin/cc').read_bytes()), timeout=digest(Path('/usr/bin/timeout').read_bytes())))
    result = {'status': 'FAIL', 'first_error': None, 'cleanup_errors': []}
    proc = None
    try:
        with (root / 'build.stdout').open('xb') as out, (root / 'build.stderr').open('xb') as err:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True,
                                    start_new_session=True, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'TMPDIR': str(root)})
            result['identity'] = proc_identity(proc.pid)
            check(proc.wait(timeout=35) == 0, 'compiler failed')
        check(not direct_children(), 'compiler descendants remained after successful compiler')
        # Exact path is an existing product fixture contract. O_EXCL, never overwrite.
        write(ACTOR, target.read_bytes())
        os.chmod(ACTOR, 0o700)
        result.update(status='PASS', actor=digest(ACTOR.read_bytes()))
    except BaseException as exc:
        result['first_error'] = repr(exc)
    finally:
        if proc and proc.poll() is None:
            try:
                info = proc_identity(proc.pid)
                # Owned timeout session/group is still pinned by the unreaped leader.
                check(info and info['ppid'] == os.getpid() and info['pgrp'] == proc.pid and info['session'] == proc.pid, 'compiler group identity')
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
            except BaseException as exc:
                result['cleanup_errors'].append(repr(exc))
        reaps, errors = collect_owned(8)
        result['reaps'] = reaps
        result['cleanup_errors'] += errors
        if errors or result['cleanup_errors']:
            result['status'] = 'FAIL'
        result['returncode'] = proc.returncode if proc else None
        save(root / 'build-result.json', result)
    check(result['status'] == 'PASS', 'build failed; raw first error retained')


def mutate_host(name, host):
    if name == 'wrong_boot':
        host['boot_id'] = '00000000-0000-0000-0000-000000000001' if host['boot_id'] != '00000000-0000-0000-0000-000000000001' else '00000000-0000-0000-0000-000000000002'
    elif name in {'wrong_mount_namespace', 'wrong_pid_namespace'}:
        host['namespaces']['mount' if name == 'wrong_mount_namespace' else 'pid']['inode'] += 1
    elif name == 'wrong_mount':
        host['locations'][0]['mount']['mount_id'] += 1
    elif name == 'wrong_root':
        host['locations'][0]['object']['inode'] += 1
    elif name == 'wrong_runtime':
        host['locations'][2]['object']['inode'] += 1


def no_final(workspace):
    check(not os.path.lexists(workspace / 'v31-completion.json'), 'unexpected final receipt')


def no_publication(workspace):
    no_final(workspace)
    check(not os.path.lexists(workspace / 'v31-completion.pending'), 'unexpected pending receipt')


def preserve_replace(path, suffix, symlink=False):
    """Only owned fixture paths; retain old inode, no overwrite/unlink."""
    old = path.with_name(path.name + suffix)
    check(not os.path.lexists(old), 'retention name exists')
    before = path.lstat()
    path.rename(old)
    if symlink:
        path.symlink_to(old.name, target_is_directory=stat.S_ISDIR(before.st_mode))
    elif stat.S_ISDIR(before.st_mode):
        path.mkdir(mode=0o700)
        for child in old.iterdir():
            check(child.is_file() and not child.is_symlink(), 'bounded data-only directory')
            write(path / child.name, child.read_bytes())
    else:
        write(path, old.read_bytes())
    return {'before': [before.st_dev, before.st_ino], 'old_path': str(old), 'after': [path.lstat().st_dev, path.lstat().st_ino]}


def run_case(case, root, project_dir, python, lock):
    name = case['name']
    from product_fixture import build, accept_receipt
    case_root = root / name
    case_root.mkdir(mode=0o700)
    project_dir.mkdir(mode=0o700)
    result = dict(case=name, status='FAIL', first_error=None, cleanup_errors=[], raw_evidence_scope='actual-Linux-unmodified-newsource-inert-actor')
    started = time.monotonic()
    proc = None
    other = None
    input_stream = None
    signal.setitimer(signal.ITIMER_REAL, CASE_SECONDS)
    try:
        fixture = build(case, case_root, project_dir, python, lock, lambda host: mutate_host(name, host))
        workspace = fixture['workspace']
        events = project_dir / 'events'
        events.mkdir(mode=0o700)
        direct_rc, descendant_rc = case.get('direct_rc', 0), case.get('descendant_rc', 0)
        mode = 'signal' if name == 'direct_signal' else 'normal'
        write(workspace / 'r4-actor.control', f'{events}\n{mode}\n{direct_rc}\n{descendant_rc}\n6000\n'.encode())
        command = fixture['command']
        if name == 'prctl_denied':
            command = [str(ACTOR), '--deny-prctl', *command]
        rejected = name.startswith('wrong_') or name in {'prctl_denied', 'preexisting_lock', 'preexisting_log', 'preexisting_pending', 'preexisting_final', 'input_symlink', 'attempt_symlink', 'stdin_trailing', 'stdin_over_cap', 'extra_argv', 'runtime_root_before_child'}
        existing = {'preexisting_lock': 'v31-completion-launch.lock', 'preexisting_log': 'xtb.out', 'preexisting_pending': 'v31-completion.pending', 'preexisting_final': 'v31-completion.json'}
        if name in existing:
            write(workspace / existing[name], b'PREEXISTING RETAIN EXACT BYTES\n')
        if name == 'runtime_root_before_child':
            result['replacement'] = preserve_replace(fixture['data_root'], '.retained')
        if name == 'input_symlink':
            result['replacement'] = preserve_replace(workspace / 'input.xyz', '.retained', symlink=True)
        if name == 'attempt_symlink':
            result['replacement'] = preserve_replace(workspace, '.retained', symlink=True)
        if name in {'stdin_trailing', 'stdin_over_cap', 'extra_argv'}:
            command = fixture['python_command']
            raw = (case_root / 'config.stdin').read_bytes()
            if name == 'stdin_trailing':
                raw += b'not-base64\n'
            elif name == 'stdin_over_cap':
                raw = b'A' * (8 * 1024 * 1024 + 1) + b'\n'
            else:
                command = [*command, 'unexpected']
            write(case_root / 'invalid.stdin', raw)
            input_stream = (case_root / 'invalid.stdin').open('rb')
            result['wire_negative'] = 'real product source, deliberately invalid transport input; not a valid scheduler artifact'
        save(case_root / 'intent.json', {'command': command, 'case_seconds': CASE_SECONDS, 'direct_rc': direct_rc,
                                        'descendant_rc': descendant_rc, 'snapshot_id': fixture['snapshot'].program_execution_snapshot_id})
        with (case_root / 'wrapper.stdout').open('xb') as out, (case_root / 'wrapper.stderr').open('xb') as err:
            proc = subprocess.Popen(command, stdin=input_stream or subprocess.DEVNULL, stdout=out, stderr=err,
                                    close_fds=True, start_new_session=True, env={'PBS_JOBID': 'r4.synthetic', 'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'})
            wrapper = wait_for(lambda: proc_identity(proc.pid), 1, 'wrapper identity')
            result['wrapper'] = wrapper
            if rejected:
                check(proc.wait(timeout=12) == 125, 'pre-child rejection must exit infrastructure 125')
                check(not (events / 'direct.json').exists(), 'rejected case started actor')
                if name in existing:
                    check((workspace / existing[name]).read_bytes() == b'PREEXISTING RETAIN EXACT BYTES\n', 'preexisting file changed')
                    if name != 'preexisting_final':
                        no_final(workspace)
                else:
                    no_publication(workspace)
                if name == 'prctl_denied':
                    check(b'FC06_REAL_PRCTL_DENIED errno=1' in (case_root / 'wrapper.stderr').read_bytes(), 'seccomp denial evidence missing')
                result['actor_launches'] = 0
            else:
                direct = wait_for(lambda: event(events / 'direct.json'), 4, 'direct actor')
                adopted = wait_for(lambda: event(events / 'adopted.json'), 4, 'adopted descendant')
                descendant = proc_identity(adopted['pid'])
                check(direct['ppid'] == proc.pid and adopted['ppid'] == proc.pid, 'wrapper adoption')
                check(descendant and descendant['ppid'] == proc.pid and descendant['state'] != 'Z', 'live descendant')
                check(descendant['start_ticks'] == adopted['start_ticks'], 'descendant event identity')
                result.update(direct=direct, adopted=adopted, descendant=descendant)
                held, log = Path(f"/proc/{descendant['pid']}/fd/1").stat(), (workspace / 'xtb.out').stat()
                check((held.st_dev, held.st_ino) == (log.st_dev, log.st_ino), 'inherited log descriptor')
                result['held_log'] = [held.st_dev, held.st_ino]
                no_publication(workspace)
                if name == 'concurrent':
                    with (case_root / 'loser.stdout').open('xb') as lo, (case_root / 'loser.stderr').open('xb') as le:
                        other = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=lo, stderr=le, close_fds=True,
                                                 env={'PBS_JOBID': 'r4.synthetic', 'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'})
                        check(other.wait(timeout=10) == 125, 'second publisher did not reject')
                    result['second_returncode'] = other.returncode
                if name == 'direct_signal':
                    identity = proc_identity(direct['pid'])
                    check(identity and identity['ppid'] == proc.pid, 'owned direct process')
                    own_signal(identity, signal.SIGTERM)
                    result['signal_target'] = identity
                if name == 'wrapper_death':
                    middle_event = wait_for(lambda: event(events / 'middle.json'), 2, 'middle event')
                    wait_for(lambda: proc_identity(direct['pid']) is None and proc_identity(middle_event['pid']) is None, 2, 'wrapper reaped direct and middle')
                    own_signal(wrapper, signal.SIGKILL)
                    check(proc.wait(timeout=3) == -signal.SIGKILL, 'wrapper kill result')
                if name == 'descendant_timeout':
                    check(proc.wait(timeout=4) == 125, 'descendant timeout infrastructure status')
                if name == 'publication_data_root_drift':
                    result['replacement'] = preserve_replace(fixture['data_root'], '.retained')
                if name == 'publication_input_inode_drift':
                    result['replacement'] = preserve_replace(workspace / 'input.xyz', '.retained')
                if name == 'publication_final_eexist':
                    write(workspace / 'v31-completion.json', b'FOREIGN FINAL RETAIN\n')
                write(events / 'release', b'R4 owned release\n')
                if name in {'wrapper_death', 'descendant_timeout'}:
                    no_publication(workspace)
                    survivor = proc_identity(descendant['pid'])
                    check(survivor and survivor['ppid'] == os.getpid(), 'supervisor adoption after wrapper exit')
                    wait_for(lambda: event(events / 'descendant_exit.json'), 7, 'survivor finite self-exit')
                    def reap_exact():
                        pid, status = os.waitpid(descendant['pid'], os.WNOHANG)
                        return (pid, status) if pid else None
                    pid, status = wait_for(reap_exact, 2, 'exact adopted reap')
                    check(os.waitstatus_to_exitcode(status) == descendant_rc, 'adopted exit status')
                    result['survivor_reap'] = {'pid': pid, 'wait_status': status}
                    no_publication(workspace)
                elif name.startswith('publication_'):
                    check(proc.wait(timeout=12) == 125, 'publication drift must exit infrastructure 125')
                    if name == 'publication_final_eexist':
                        check((workspace / 'v31-completion.json').read_bytes() == b'FOREIGN FINAL RETAIN\n', 'EEXIST overwrite')
                        check((workspace / 'v31-completion.pending').is_file(), 'pending evidence missing')
                    else:
                        no_publication(workspace)
                else:
                    expected_rc = 143 if name == 'direct_signal' else direct_rc
                    check(proc.wait(timeout=12) == expected_rc, 'direct status lost')
                    pending, final = workspace / 'v31-completion.pending', workspace / 'v31-completion.json'
                    check(pending.is_file() and final.is_file(), 'receipt absent')
                    check((pending.stat().st_dev, pending.stat().st_ino) == (final.stat().st_dev, final.stat().st_ino), 'atomic link inode')
                    raw = final.read_bytes()
                    check(raw == pending.read_bytes(), 'pending/final bytes')
                    receipt = accept_receipt(raw, fixture)
                    term = {'kind': 'signaled', 'returncode': None, 'signal': 15} if name == 'direct_signal' else {'kind': 'exited', 'returncode': direct_rc, 'signal': None}
                    check(receipt['termination'] == term, 'receipt direct status')
                    check((workspace / 'xtb.out').read_bytes() == b'FC06_DESCENDANT_FINAL_BYTES\n', 'final writer bytes')
                    middle = event(events / 'middle.json')
                    check(middle is not None, 'middle evidence')
                    for pid in (direct['pid'], middle['pid'], descendant['pid']):
                        check(proc_identity(pid) is None, 'publication before complete reap')
                    result['receipt'] = {'digest': digest(raw), 'termination': term, 'full_product_consumer': True}
                result['actor_launches'] = 1
        result['status'] = 'PASS'
    except BaseException as exc:
        result['first_error'] = repr(exc)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        if input_stream:
            input_stream.close()
        for process in (other, proc):
            if process is not None and process.poll() is None:
                try:
                    info = proc_identity(process.pid)
                    check(info and info['ppid'] == os.getpid(), 'watchdog owns wrapper')
                    own_signal(info, signal.SIGKILL)
                    process.wait(timeout=3)
                except BaseException as exc:
                    result['cleanup_errors'].append(repr(exc))
        reaps, errors = collect_owned(8)
        result['cleanup_reaps'] = reaps
        result['cleanup_errors'] += errors
        if result['cleanup_errors'] or reaps:
            # Unexpected cleanup on a nominal PASS is not a clean successful case.
            result['status'] = 'FAIL'
        result['wrapper_returncode'] = proc.returncode if proc else None
        result['seconds'] = time.monotonic() - started
        save(case_root / 'result.json', result)
    return result


def inventory(roots):
    records = []
    total = 0
    for root in roots:
        for current, dirs, files in os.walk(root, followlinks=False):
            for name in sorted(dirs + files):
                p = Path(current) / name
                st = p.lstat()
                item = {'path': str(p), 'mode': st.st_mode, 'size': st.st_size, 'device': st.st_dev, 'inode': st.st_ino}
                if stat.S_ISREG(st.st_mode):
                    check(st.st_size <= MAX_FILE_BYTES, 'single file exceeds ceiling')
                    item['sha256'] = digest(p.read_bytes())['sha256']
                    total += st.st_size
                elif stat.S_ISLNK(st.st_mode):
                    item['target'] = os.readlink(p)
                records.append(item)
                check(len(records) <= 4096 and total <= 256 * 1024 * 1024, 'run file budget exceeded')
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--binding', type=Path, required=True)
    parser.add_argument('--binding-sha256', required=True)
    parser.add_argument('--run-scope', type=Path, required=True)
    parser.add_argument('--run-scope-sha256', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, deadline)
    lock, scope, git = verify_binding(args)
    cases = json.loads((HERE / 'cases.json').read_bytes())
    selected = [case for case in cases if case['name'] in scope['case_names']]
    check([case['name'] for case in selected] == scope['case_names'], 'unknown/order of cases')
    require_chain(args.evidence.absolute().parent)
    require_chain(ACTOR.parent)
    require_chain(REMOTE)
    check(not os.path.lexists(ACTOR), 'fixture actor already exists; no replace/reuse')
    check(not (ACTOR.parent.stat().st_mode & 0o022) and not (REMOTE.stat().st_mode & 0o022), 'fixture roots must not be group/world writable')
    check(ACTOR.parent.stat().st_uid == os.getuid() and REMOTE.stat().st_uid == os.getuid(), 'dedicated Linux fixture roots must be owned')
    check(not direct_children(), 'must be a dedicated supervisor with no prior children')
    check(os.getuid() != 0, 'nonroot hosted runner UID required for RLIMIT_NPROC')
    for item in ('/usr/bin/cc', '/usr/bin/timeout', '/bin/bash'):
        check(Path(item).is_file(), 'preinstalled tool missing: ' + item)
    root = args.evidence.absolute()
    root.mkdir(mode=0o700)
    summary = dict(status='FAIL', first_error=None, cleanup_errors=[], case_results=[], production_qualified=False,
                   binding_sha256=args.binding_sha256, run_scope_sha256=args.run_scope_sha256)
    started = time.monotonic()
    projects = []
    signal.signal(signal.SIGALRM, deadline)
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES, MAX_FILE_BYTES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
        from hosted_support import uid_threads
        current_uid = uid_threads(os.getuid())
        save(root / 'uid-before-limits.json', current_uid)
        check(current_uid['threads'] <= scope['nproc_limit'] - 16, 'UID contention consumed required process margin')
        resource.setrlimit(resource.RLIMIT_NPROC, (scope['nproc_limit'], scope['nproc_limit']))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (1200, 1200))
        libc = ctypes.CDLL(None, use_errno=True)
        check(libc.prctl(36, 1, 0, 0, 0) == 0, 'supervisor subreaper set')
        got = ctypes.c_int()
        check(libc.prctl(37, ctypes.byref(got), 0, 0, 0) == 0 and got.value == 1, 'supervisor subreaper readback')
        save(root / 'environment.json', dict(python=sys.version, executable=sys.executable, python_digest=digest(Path(sys.executable).read_bytes()),
             platform=sys.platform, uname=list(os.uname()), uid=os.getuid(), supervisor=proc_identity(os.getpid()), subreaper_readback=got.value,
             started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), production_qualified=False))
        write(root / 'binding.json', args.binding.read_bytes())
        write(root / 'run-scope.json', args.run_scope.read_bytes())
        compile_actor(root)
        python = Path(sys.executable).resolve(strict=True)
        for index, case in enumerate(selected):
            check(time.monotonic() - started < TOTAL_SECONDS - CASE_SECONDS - 30, 'global budget exhausted')
            project = REMOTE / (scope['project_prefix'] + '-' + str(index))
            check(project.parent == REMOTE and project.name.startswith('r4-inert-'), 'project root scope')
            check(not os.path.lexists(project), 'existing project path')
            projects.append(project)
            print('START ' + case['name'], flush=True)
            result = run_case(case, root, project, python, lock)
            summary['case_results'].append(result)
            print(result['status'] + ' ' + case['name'], flush=True)
            check(result['status'] == 'PASS', 'first case failure; no subsequent cases/retry')
        check(not git('status', '--porcelain=v1', '--untracked-files=all'), 'candidate changed')
        summary['status'] = 'PASS'
    except BaseException as exc:
        summary['first_error'] = repr(exc)
    finally:
        reaps, errors = collect_owned(8)
        summary['final_reaps'] = reaps
        summary['cleanup_errors'] += errors
        if errors or reaps:
            summary['status'] = 'FAIL'
        try:
            save(root / 'inventory.json', {'files': inventory([root, *projects]), 'actor': {'path': str(ACTOR), **digest(ACTOR.read_bytes())} if ACTOR.exists() else None})
        except BaseException as exc:
            summary['cleanup_errors'].append('inventory: ' + repr(exc))
            summary['status'] = 'FAIL'
        summary['seconds'] = time.monotonic() - started
        summary['not_run'] = [c['name'] for c in selected[len(summary['case_results']):]]
        save(root / 'summary.json', summary)
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
