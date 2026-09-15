"""Mechanical replay of the reviewed hosted plan; no authority tokens."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

PACKAGE_FILES = frozenset(('run_r4.py', 'linux_observer.py', 'product_fixture.py', 'r4_actor.c',
    'cases.json', 'synthetic-evidence.txt', 'hosted_launcher.py', 'hosted_support.py',
    'provision_fixture_roots.py', 'run-plan.json', 'owner-request-and-scope.json'))
OWNER_SHA = 'b5d2bf7385c5eeeeb0abdfb30460ac61d43794d98d04daf01703ea239925b1cb'
ENV_KEYS = ('GITHUB_REPOSITORY', 'GITHUB_REPOSITORY_ID', 'GITHUB_REF', 'GITHUB_SHA',
    'GITHUB_EVENT_NAME', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_WORKSPACE', 'RUNNER_TEMP', 'RUNNER_OS', 'RUNNER_ENVIRONMENT')


def check(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() + b'\n'


def digest(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def closed_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            check(key not in result, 'duplicate key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('noninteger JSON number')
    return json.loads(raw, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)


def read(path, cap=4 * 1024 * 1024):
    # This also pins every parent component without following symlinks.
    from linux_observer import read_regular
    return read_regular(str(path), cap)


def git(repo, *args):
    return subprocess.check_output(['/usr/bin/git', '-C', str(repo), *args], timeout=10,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null'})


def verify_package(here, binding):
    check(set(binding['package_files']) == PACKAGE_FILES, 'complete hosted package inventory')
    for name in sorted(PACKAGE_FILES):
        check(digest(read(here / name)) == binding['package_files'][name], 'package drift: ' + name)


def verify_candidate(repo, binding):
    candidate = binding['candidate']
    check(git(repo, 'rev-parse', 'HEAD').decode().strip() == candidate['head'], 'product HEAD drift')
    check(git(repo, 'rev-parse', 'HEAD^{tree}').decode().strip() == candidate['tree'], 'product tree drift')
    check(not git(repo, 'status', '--porcelain=v1', '--untracked-files=all'), 'product dirty')
    names = git(repo, 'ls-files', 'auto_g16', 'tests', 'scripts/run_v31_publisher_pilot.py').decode().splitlines()
    check(set(names) == set(candidate['files']), 'product inventory drift')
    for name, expected in candidate['files'].items():
        check(not Path(name).is_absolute() and '..' not in Path(name).parts, 'product manifest path')
        check(digest(read(repo / name, 16 * 1024 * 1024)) == expected, 'product bytes drift: ' + name)


def load_plan(here, binding):
    raw = read(here / 'run-plan.json')
    plan = closed_json(raw)
    owner_raw = read(here / 'owner-request-and-scope.json')
    check(digest(owner_raw)['sha256'] == OWNER_SHA == plan['owner_request_sha256'], 'owner attachment drift')
    owner = closed_json(owner_raw)
    check(plan['schema'] == 'v31-r4-hosted-run-plan/1', 'plan schema')
    for key in ('product_head', 'product_tree', 'case_names', 'repository'):
        check(plan[key] == owner[key], 'plan/owner mismatch: ' + key)
    check(plan['product_head'] == binding['candidate']['head'] and plan['product_tree'] == binding['candidate']['tree'], 'plan/product drift')
    check(plan['branch'] == owner['validation_branch'] and plan['owner_request'] == owner['owner_message_exact'], 'owner request mismatch')
    check(plan['controller_task_id'] == owner['source_thread_id'], 'controller mismatch')
    check(plan['scope_is_authority_token'] is False and plan['production_qualified'] is False, 'no authority expansion')
    for key, owner_key in (('case_seconds', 'case_timeout_seconds'), ('total_seconds', 'run_timeout_seconds'),
                            ('kill_grace_seconds', 'timeout_cleanup_seconds'), ('job_minutes', 'ci_timeout_minutes')):
        check(type(plan[key]) is int and plan[key] == owner['bounds'][owner_key], 'budget mismatch')
    check(plan['nproc_headroom'] == 32 and plan['nproc_maximum'] == 256, 'process budget drift')
    return plan, digest(raw)['sha256'], owner


def validate_ci(plan, owner, env):
    expected = {'GITHUB_REPOSITORY': plan['repository'], 'GITHUB_REPOSITORY_ID': str(owner['repository_id']),
        'GITHUB_REF': 'refs/heads/' + plan['branch'], 'GITHUB_EVENT_NAME': 'push',
        'GITHUB_RUN_ATTEMPT': str(plan['run_attempt']), 'GITHUB_WORKSPACE': plan['workspace'],
        'RUNNER_TEMP': plan['runner_temp'], 'RUNNER_OS': 'Linux', 'RUNNER_ENVIRONMENT': 'github-hosted'}
    check(set(env) == set(ENV_KEYS), 'closed CI environment projection')
    for key, value in expected.items():
        check(env[key] == value, 'CI scope mismatch: ' + key)
    check(re.fullmatch('[0-9a-f]{40}', env['GITHUB_SHA']), 'CI head required')
    check(re.fullmatch('[1-9][0-9]{0,19}', env['GITHUB_RUN_ID']), 'CI run id required')
    return dict(env)


def uid_threads(uid, proc_root=Path('/proc')):
    """Finite contemporaneous per-real-UID thread observation, not a reservation."""
    entries = []
    with os.scandir(proc_root) as scan:
        for item in scan:
            entries.append(item.name)
            check(len(entries) <= 8192, 'proc inventory cap')
    count, statuses, vanished = 0, [], []
    for name in sorted(entries):
        if not name.isascii() or not name.isdigit():
            continue
        try:
            raw = read(proc_root / name / 'status', 65536)
        except (FileNotFoundError, ProcessLookupError):
            vanished.append(int(name))
            continue
        # Inaccessible/malformed processes fail closed rather than undercount.
        fields = dict(line.split(':', 1) for line in raw.decode().splitlines() if ':' in line)
        if int(fields['Uid'].split()[0]) == uid:
            threads = int(fields['Threads'].strip())
            check(1 <= threads <= 256, 'thread count outside bound')
            count += threads
            statuses.append({'pid': int(name), 'uid': uid, 'threads': threads,
                             'status_sha256': digest(raw)['sha256']})
    check(count > 0, 'UID baseline empty')
    return {'uid': uid, 'threads': count, 'processes': statuses, 'vanished_pids': vanished}


def nproc_budget(plan, baseline):
    check(type(baseline['uid']) is int and baseline['uid'] > 0, 'ordinary UID required')
    count = baseline['threads']
    check(type(count) is int and count > 0, 'invalid UID thread baseline')
    limit = count + plan['nproc_headroom']
    check(limit <= plan['nproc_maximum'], 'insufficient finite UID thread headroom')
    return limit


def derive_scope(plan, plan_sha, binding_sha, platform):
    check(platform['status'] == 'OBSERVED' and platform['production_qualified'] is False, 'observed platform required')
    return dict(state='INSTANTIATED_FROM_REVIEWED_PLAN', execution_plan_sha256=plan_sha,
        binding_sha256=binding_sha, owner_request_sha256=plan['owner_request_sha256'],
        platform_evidence_sha256=digest(canonical(platform))['sha256'],
        ci=platform['ci'], uid=platform['uid'], nproc_limit=nproc_budget(plan, platform['uid_baseline']),
        case_names=plan['case_names'], project_prefix=plan['project_prefix'], evidence=plan['evidence'],
        actor_path=plan['actor_path'], remote_parent=plan['remote_parent'], total_seconds=plan['total_seconds'],
        case_seconds=plan['case_seconds'], cleanup=plan['cleanup'], production_qualified=False, scope_is_authority_token=False)


def replay_scope(here, binding, binding_sha, scope_raw):
    plan, plan_sha, owner = load_plan(here, binding)
    platform_raw = read(Path(plan['supervisor']) / 'platform.json')
    platform = closed_json(platform_raw)
    check(platform_raw == canonical(platform), 'platform serialization drift')
    validate_ci(plan, owner, platform['ci'])
    for name, expected in platform['raw_files'].items():
        check(Path(name).name == name, 'platform evidence path')
        check(digest(read(Path(plan['supervisor']) / name)) == expected, 'raw platform evidence drift')
    check(platform['uid'] == os.getuid() == platform['uid_baseline']['uid'], 'UID drift')
    expected = derive_scope(plan, plan_sha, binding_sha, platform)
    check(scope_raw == canonical(expected), 'scope differs from mechanical plan instantiation')
    return expected, platform
