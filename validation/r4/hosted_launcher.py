#!/usr/bin/env python3
"""One reviewed hosted-VM run. This file is inert when imported locally."""
import os
from pathlib import Path
import pwd
import signal
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from hosted_support import (ENV_KEYS, canonical, check, closed_json, derive_scope, digest,
    git, load_plan, nproc_budget, read, uid_threads, validate_ci, verify_candidate, verify_package)


def write(path, raw):
    check(len(raw) <= 4 * 1024 * 1024, 'supervisor evidence file cap')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def node(path):
    value = path.lstat()
    check(stat.S_ISDIR(value.st_mode), 'directory required: ' + str(path))
    return dict(device=value.st_dev, inode=value.st_ino, uid=value.st_uid, gid=value.st_gid, mode=stat.S_IMODE(value.st_mode))


def chain(path):
    current = Path('/')
    for component in path.parts[1:]:
        current /= component
        node(current)


def main():
    # Before any sudo, freeze package, both checkouts, owner record, environment,
    # tool observations, paths and per-UID thread budget. No product imports.
    check(len(sys.argv) == 1, 'no path or scope overrides')
    check(sys.platform == 'linux' and os.getuid() > 0, 'ordinary Linux runner required')
    check(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode and not sys.flags.optimize, 'require -I -S -B')
    check(pwd.getpwuid(os.getuid()).pw_name == 'runner', 'hosted runner account required')
    binding_raw = read(HERE / 'binding.json')
    binding = closed_json(binding_raw)
    binding_sha = digest(binding_raw)['sha256']
    verify_package(HERE, binding)
    plan, plan_sha, owner = load_plan(HERE, binding)
    ci = validate_ci(plan, owner, {key: os.environ.get(key, '') for key in ENV_KEYS})
    workspace, supervisor = Path(plan['workspace']), Path(plan['supervisor'])
    check(HERE == workspace / 'validation-package/validation/r4', 'launcher checkout location')
    chain(supervisor)
    check(node(supervisor)['uid'] == os.getuid() and node(supervisor)['mode'] == 0o700, 'private supervisor directory')
    harness = workspace / 'validation-package'
    candidate = workspace / 'candidate'
    check(git(harness, 'rev-parse', 'HEAD').decode().strip() == ci['GITHUB_SHA'], 'workflow/checkout HEAD drift')
    check(not git(harness, 'status', '--porcelain=v1', '--untracked-files=all'), 'harness checkout dirty')
    verify_candidate(candidate, binding)
    for path in (Path(plan['evidence']), Path('/opt/auto-g16-fixtures'), Path('/home/user100')):
        chain(path.parent)
        check(not os.path.lexists(path), 'existing run target: ' + str(path))
    for name in (Path('/opt'), Path('/home')):
        info = node(name)
        check(info['uid'] == 0 and not info['mode'] & 0o022, 'system parent ownership')
    raw_files = {}
    def record(name, raw):
        write(supervisor / name, raw)
        raw_files[name] = digest(raw)
    python = Path(sys.executable).resolve(strict=True)
    tools = {}
    for name, entry in (('python', python), ('cc', Path('/usr/bin/cc')), ('timeout', Path('/usr/bin/timeout')),
                        ('bash', Path('/bin/bash')), ('sudo', Path('/usr/bin/sudo'))):
        physical = entry.resolve(strict=True)
        tools[name] = {'path': str(physical), **digest(read(physical, 64 * 1024 * 1024))}
    record('os-release.raw', read('/usr/lib/os-release'))
    os_release = dict(line.split('=', 1) for line in read('/usr/lib/os-release').decode().splitlines() if '=' in line)
    check(os_release['ID'].strip('"') == 'ubuntu' and os_release['VERSION_ID'].strip('"') == '24.04', 'Ubuntu 24.04 required')
    record('machine-id.raw', read('/etc/machine-id', 4096))
    record('boot-id.raw', read('/proc/sys/kernel/random/boot_id', 128))
    record('mountinfo.raw', read(f'/proc/{os.getpid()}/mountinfo'))
    namespaces = {}
    for name in ('mnt', 'pid'):
        ns = os.stat(f'/proc/{os.getpid()}/ns/{name}')
        namespaces[name] = {'device': ns.st_dev, 'inode': ns.st_ino}
    baseline = uid_threads(os.getuid())
    nproc_budget(plan, baseline)
    record('uid-baseline.json', canonical(baseline))
    # Record observation/intent before the one bounded root operation.
    intent = dict(ci=ci, plan_sha256=plan_sha, binding_sha256=binding_sha, owner_request_sha256=plan['owner_request_sha256'],
        tools=tools, uname=list(os.uname()), namespaces=namespaces, uid=os.getuid(), raw_files=dict(raw_files), production_qualified=False)
    record('platform-before-provision.json', canonical(intent))
    command = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-S', '-B', str(HERE / 'provision_fixture_roots.py')]
    record('provision-intent.json', canonical({'command': command, 'self_deadline_seconds': 10, 'wait_seconds': 15, 'retries': 0}))
    # The root helper has its own hard deadline. Exact sudo child only; timeout
    # records failure and never invokes a second sudo or retries provisioning.
    with (supervisor / 'provision.stdout').open('xb') as out, (supervisor / 'provision.stderr').open('xb') as err:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err, close_fds=True,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        try:
            rc = process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            # Ordinary runner cannot safely signal a root sudo process. The root
            # helper timer and job ceiling contain it; preserve UNKNOWN and stop.
            record('provision-timeout.json', canonical({'status': 'UNKNOWN', 'sudo_pid': process.pid, 'retry': False}))
            raise
    for name in ('provision.stdout', 'provision.stderr'):
        raw_files[name] = digest(read(supervisor / name))
    provision = closed_json(read(supervisor / 'provision.stdout'))
    check(rc == 0 and provision['status'] == 'PASS' and not provision['cleanup_errors'], 'fixture provisioning failed')
    roots = {}
    for path in owner['temporary_fixture_directories']:
        target = Path(path)
        chain(target)
        info = node(target)
        check(info['uid'] == os.getuid() and info['gid'] == os.getgid() and info['mode'] == 0o700, 'new fixture root ownership')
        recorded = [item['owned'] for item in provision['observations'] if item.get('path') == path and 'owned' in item]
        check(recorded == [info], 'fixture root identity differs from retained provisioning descriptor')
        roots[path] = info
    platform = dict(status='OBSERVED', ci=ci, uid=os.getuid(), uid_baseline=baseline, tools=tools,
        uname=list(os.uname()), namespaces=namespaces, fixture_roots=roots, raw_files=raw_files, production_qualified=False)
    write(supervisor / 'platform.json', canonical(platform))
    scope_raw = canonical(derive_scope(plan, plan_sha, binding_sha, platform))
    write(supervisor / 'run-scope.json', scope_raw)
    command = ['/usr/bin/timeout', '--signal=TERM', '--kill-after=15s', '1500s', str(python), '-I', '-S', '-B', str(HERE / 'run_r4.py'),
        '--candidate', str(candidate), '--binding', str(HERE / 'binding.json'), '--binding-sha256', binding_sha,
        '--run-scope', str(supervisor / 'run-scope.json'), '--run-scope-sha256', digest(scope_raw)['sha256'], '--evidence', plan['evidence']]
    write(supervisor / 'execution-intent.json', canonical({'command': command, 'automatic_retry': False, 'production_qualified': False}))
    os.execve(command[0], command, {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        # Workflow redirects this to a fresh regular log retained on failure.
        print(canonical({'status': 'FAIL', 'first_error': repr(exc), 'retry': False}).decode(), file=sys.stderr, flush=True)
        sys.exit(125)
