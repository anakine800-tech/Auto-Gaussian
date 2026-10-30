"""T215: synthetic short PBS jobs; no scheduler or private configuration IO."""
from copy import deepcopy
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ag import attempt, autonomy, fetch, node_targeting as nt, remote, render, state, status
from ag.transport import Result
from test_autonomy import env, _publication_context, _late_observation, image_tree
from test_completion import ObservationFake, exit_receipt
from test_core import cfg, job_text, seed_submission
from test_node_targeting import targeted


START = dict(PBS_JOBID='123.fixture', started_at='2026-01-01T00:00:00Z')


def pending(targeted, *, whole=False, alter=None):
    config, args = targeted
    args = dict(args)
    if whole:
        args['input_path'].write_bytes(args['input_path'].read_bytes().replace(
            b'%nprocshared=24\n%mem=40GB\n', b''))
        args.update(tier='max', node_fraction='1')
    manifest = attempt.prepare(config, **args)
    path = attempt.find(config, manifest['attempt_id'])
    if alter is not None:
        # Only synthesize historical or forged bytes BEFORE the test's binding.
        # Production must never rewrite an already submitted manifest/bundle.
        script = path / 'inputs/job.pbs'
        script.write_bytes(alter(script.read_bytes()))
        files = {p.name: p.read_bytes() for p in (path / 'inputs').iterdir()}
        manifest['inputs'], manifest['bundle_sha256'] = attempt.prepared_bundle(files)
        (path / 'manifest.json').write_text(json.dumps(manifest))
    state.write(path, 'submitting')
    seed_submission(path)
    nt.retain_placement(path, manifest, dict(job_state='Q'))
    fake = ObservationFake(config, manifest)
    fake.receipts = {'ag-start.json': json.dumps(START), 'ag-exit.json': exit_receipt()}
    return config, path, manifest, fake


def scheduler(fake, manifest, value, *, hosts=None):
    fake.job = (Result(153, '', 'qstat: Unknown Job Id') if value is None else
                Result(stdout=job_text(manifest, cores=manifest['cores'], state_=value)))
    if hosts is not None:
        fake.job.stdout += f'    exec_host = {hosts}\n'


def frozen(path):
    return {p: p.read_bytes() for p in [path / 'manifest.json', path / 'submission.json',
                                       *(path / 'inputs').iterdir()]}


@pytest.mark.parametrize('whole', [False, True])
@pytest.mark.parametrize('pbs_state', [None, 'R', 'C'])
@pytest.mark.parametrize('owned', [False, True])
def test_short_job_start_proves_placement_and_allows_fetch(targeted, env, whole, pbs_state, owned):
    config, path, manifest, fake = pending(targeted, whole=whole)
    scheduler(fake, manifest, pbs_state)
    publication = _publication_context(env, config, path)[3] if owned else None
    before = frozen(path)
    result = status.check(config, path, fake, publication=publication)
    assert result['state'] == 'finished' and result['exit_status'] == 0
    assert result['completion_source'] == 'ag-exit.json'
    assert result['scheduler_residue'] is (pbs_state == 'R')
    placement = result['node_placement']
    assert placement['state'] == 'verified'
    assert placement['source'] == 'node-guard+ag-start.json'
    assert placement['target'] == manifest['node_target']['name']
    assert placement['exec_host'] == ''
    assert placement['job_id'] == 'default:123.fixture'
    assert placement['script_sha256'] == sha256((path / 'inputs/job.pbs').read_bytes()).hexdigest()
    assert placement['bundle_sha256'] == manifest['bundle_sha256']
    assert placement['start_receipt'] == START
    assert not {'submit', 'cancel', 'create_attempt', 'nodes'} & set(fake.operations())
    fake.files = {'water.log': b'Synthetic output', 'job.pbs.out': b'Synthetic scheduler output'}
    assert fetch.fetch(config, path, fake, publication=publication)['state'] == 'fetched'
    assert state.read(path)['node_placement'] == placement
    assert frozen(path) == before


@pytest.mark.parametrize('pbs_state', ['R', 'E', 'S', 'C', None])
def test_start_alone_is_placement_not_completion(targeted, pbs_state):
    config, path, manifest, fake = pending(targeted)
    fake.receipts.pop('ag-exit.json')
    scheduler(fake, manifest, pbs_state)
    result = status.check(config, path, fake)
    assert result['node_placement']['source'] == 'node-guard+ag-start.json'
    assert result['node_placement']['state'] == 'verified'
    assert result['state'] not in ('finished', 'fetched')


@pytest.mark.parametrize('raw', [None, '{', '{}', '[]', 'x' * 4097,
    json.dumps(START | dict(PBS_JOBID='999.fixture')),
    json.dumps(START | dict(started_at='2026-01-01T00:00:00')),
    '{"PBS_JOBID":"123.fixture","PBS_JOBID":"123.fixture","started_at":"2026-01-01T00:00:00Z"}'])
@pytest.mark.parametrize('pbs_state', [None, 'C'])
def test_missing_wrong_or_damaged_start_never_uses_exit_as_placement(targeted, raw, pbs_state):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, pbs_state)
    if raw is None:
        fake.receipts.pop('ag-start.json')
    else:
        fake.receipts['ag-start.json'] = raw
    with pytest.raises(ValueError):
        status.check(config, path, fake)
    assert state.read(path)['state'] == 'submitted'
    assert state.read(path)['node_placement']['state'] != 'verified'
    assert not {'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('mutation', ['script', 'input', 'manifest', 'submission', 'status', 'missing-binding'])
def test_start_cannot_bypass_frozen_bytes_or_job_binding(targeted, mutation):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, None)
    if mutation in ('script', 'input'):
        name = 'job.pbs' if mutation == 'script' else 'water.gjf'
        member = path / 'inputs' / name
        member.write_bytes(member.read_bytes() + b'\nchanged synthetic bytes\n')
    elif mutation == 'manifest':
        changed = deepcopy(manifest)
        changed['node_target']['name'] = 'compute-b'
        (path / 'manifest.json').write_text(json.dumps(changed))
    elif mutation == 'submission':
        target = path / 'submission.json'
        binding = json.loads(target.read_text())
        binding['job_id'] = 'default:999.fixture'
        target.write_text(json.dumps(binding))
    elif mutation == 'status':
        state.write(path, 'submitted', job_id='default:999.fixture')
    else:
        (path / 'submission.json').unlink()
    with pytest.raises(ValueError):
        status.check(config, path, fake)
    assert state.read(path)['state'] == 'submitted'
    assert state.read(path)['node_placement']['state'] != 'verified'


@pytest.mark.parametrize('alter', [
    lambda raw: raw[:raw.index(b'# Named-node launch guard')] + raw[raw.index(b'# Adapted from'):],
    lambda raw: raw.replace(b'|| exit 43', b'|| exit 44'),
    lambda raw: raw.replace(b'test "$ag_node" = "compute-a" || exit 43', b':'),
    lambda raw: raw.replace(b'set -eu\n', b'set +e\n', 1),
    lambda raw: raw.replace(b'# Named-node launch guard', b'exit 0\n# Named-node launch guard'),
])
def test_hash_bound_unreviewed_script_does_not_gain_guard_proof(targeted, alter):
    config, path, manifest, fake = pending(targeted, alter=alter)
    scheduler(fake, manifest, None)
    before = frozen(path)
    with pytest.raises(ValueError):
        status.check(config, path, fake)
    assert state.read(path)['state'] == 'submitted'
    assert state.read(path)['node_placement']['state'] != 'verified'
    assert frozen(path) == before


def test_new_template_cannot_bless_unknown_frozen_guard(targeted, tmp_path, monkeypatch):
    # This script and its hashes are mutually consistent with a hypothetical
    # template revision, but that guard revision has never been reviewed here.
    config, path, manifest, fake = pending(targeted, alter=lambda raw: raw.replace(b'|| exit 43', b'|| exit 44'))
    templates = tmp_path / 'synthetic-templates'
    templates.mkdir()
    for name in ('node-target.pbs', '_guard.sh', 'gaussian.pbs', 'gaussian.toml'):
        raw = (render.TEMPLATES / name).read_bytes()
        if name == 'node-target.pbs':
            raw = raw.replace(b'|| exit 43', b'|| exit 44')
        (templates / name).write_bytes(raw)
    monkeypatch.setattr(render, 'TEMPLATES', templates)
    assert attempt.verified_files(config, path, manifest)  # Byte equality alone is insufficient.
    scheduler(fake, manifest, None)
    with pytest.raises(ValueError):
        status.check(config, path, fake)
    assert state.read(path)['node_placement']['state'] != 'verified'


def test_renderer_cannot_move_known_guard_after_receipt_creation(targeted, monkeypatch):
    def moved(raw):
        begin, end = raw.index(b'# Named-node launch guard'), raw.index(b'# Adapted from')
        # Every known guard byte remains present, but only after ag_run exits.
        return raw[:begin] + raw[end:] + raw[begin:end]
    config, path, manifest, fake = pending(targeted, alter=moved)
    script = (path / 'inputs/job.pbs').read_text()
    monkeypatch.setattr(render, 'render', lambda *args: script)
    assert attempt.verified_files(config, path, manifest)
    scheduler(fake, manifest, None)
    with pytest.raises(ValueError):
        status.check(config, path, fake)
    assert state.read(path)['node_placement']['state'] != 'verified'


@pytest.mark.parametrize('pbs_state', ['R', 'E', 'S', 'C'])
@pytest.mark.parametrize('hosts', ['compute-b/0-23', 'compute-a/0-22', 'compute-a/0-11+compute-b/0-11', 'malformed'])
def test_explicit_exec_host_mismatch_is_never_overridden(targeted, pbs_state, hosts):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, pbs_state, hosts=hosts)
    with pytest.raises(ValueError, match='placement'):
        status.check(config, path, fake)
    placement = state.read(path)['node_placement']
    assert placement['state'] == 'mismatch' and placement['exec_host'] == hosts
    assert placement.get('source') != 'node-guard+ag-start.json'
    before = len(fake.calls)
    with pytest.raises(ValueError, match='human review'):
        status.check(config, path, fake)
    assert len(fake.calls) == before


@pytest.mark.parametrize('pbs_state', ['Q', 'H', 'W', 'T'])
def test_queued_record_is_not_upgraded_by_start_receipt(targeted, pbs_state):
    config, path, manifest, fake = pending(targeted)
    fake.receipts.pop('ag-exit.json')
    scheduler(fake, manifest, pbs_state)
    result = status.check(config, path, fake)
    assert result['state'] == 'submitted'
    assert result['node_placement']['state'] == 'pending'
    assert result['node_placement'].get('source') != 'node-guard+ag-start.json'


@pytest.mark.parametrize('pbs_state', [None, 'C'])
def test_previous_verified_scheduler_evidence_is_preserved(targeted, pbs_state):
    config, path, manifest, fake = pending(targeted)
    nt.retain_placement(path, manifest, dict(job_state='R', exec_host='compute-a/0-23'))
    prior = state.read(path)['node_placement']
    # Recreate the old evidence shape; older status records had no source key.
    prior.pop('source', None)
    state.write(path, 'submitted', node_placement=prior)
    fake.receipts.pop('ag-start.json')
    scheduler(fake, manifest, pbs_state)
    result = status.check(config, path, fake)
    assert result['state'] == 'finished'
    assert result['node_placement'] == prior


def test_repeated_running_residue_revalidates_guard_receipt(targeted):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, 'R')
    first = status.check(config, path, fake)
    second = status.check(config, path, fake)
    for result in (first, second):
        assert result['state'] == 'finished' and result['scheduler_residue'] is True
        assert result['node_placement']['state'] == 'verified'
        assert result['node_placement']['source'] == 'node-guard+ag-start.json'
        assert result['node_placement']['exec_host'] == ''
        assert result['node_placement']['start_receipt'] == START
    assert not {'submit', 'cancel'} & set(fake.operations())


@pytest.mark.parametrize('change_owner', [False, True])
def test_guard_receipt_cannot_publish_after_owner_expiry_or_takeover(targeted, env, change_owner):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, None)
    context, plan, _, publication = _publication_context(env, config, path)
    original = fake.run
    def run(command):
        result = original(command)
        if command.operation == 'output_observation':
            _late_observation(context, plan, change_owner)
        return result
    fake.run = run
    before = image_tree(path)
    journal = path.parent.parent / 'journal.jsonl'
    before_journal = journal.read_bytes()
    with pytest.raises(autonomy.PublicationRefused):
        status.check(config, path, fake, publication=publication)
    assert image_tree(path) == before and journal.read_bytes() == before_journal


@pytest.mark.parametrize('member', ['manifest.json', 'submission.json', 'status.json',
                                   'inputs/job.pbs', 'inputs/water.gjf'])
def test_guard_receipt_rechecks_local_sources_at_publication(targeted, env, member):
    config, path, manifest, fake = pending(targeted)
    scheduler(fake, manifest, None)
    _, _, _, actual = _publication_context(env, config, path)
    before_status = (path / 'status.json').read_bytes()
    @contextmanager
    def publication():
        with actual() as verified:
            source = path / member
            # Same bytes and restored mtime still change the pinned inode metadata.
            previous = source.stat()
            source.write_bytes(source.read_bytes())
            os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
            yield verified
    with pytest.raises(ValueError):
        status.check(config, path, fake, publication=publication)
    assert (path / 'status.json').read_bytes() == before_status
    assert state.read(path)['node_placement']['state'] != 'verified'


@pytest.mark.parametrize('nodefile_kind', ['correct', 'wrong-node', 'wrong-count', 'missing', 'symlink'])
def test_actual_frozen_guard_runs_before_any_start_receipt(targeted, tmp_path, nodefile_kind):
    config, args = targeted
    binary = Path(config['programs']['gaussian']['g16root'])
    binary.mkdir()
    if sys.platform != 'linux':
        # Match the established GNU-realpath test adaptation on macOS only.
        tool = binary / 'realpath'
        tool.write_text(f'#!{sys.executable}\nimport pathlib, sys\n'
                        "assert sys.argv[1:3] == ['-e', '--']\n"
                        'print(pathlib.Path(sys.argv[3]).resolve(strict=True))\n')
        tool.chmod(0o700)
    program = binary / 'g16'
    program.write_text('#!/bin/sh\ntest -f ag-start.json\ntest ! -e ag-exit.json\n'
                       'printf synthetic > program-was-run\n')
    program.chmod(0o700)
    manifest = attempt.prepare(config, **args)
    path = attempt.find(config, manifest['attempt_id'])
    script = attempt.verified_files(config, path, manifest)['job.pbs']
    work = Path(remote.attempt_dir(config, manifest))
    work.mkdir(parents=True)
    nodefile = tmp_path / 'synthetic-nodefile'
    if nodefile_kind != 'missing':
        nodefile.write_text(('compute-b\n' if nodefile_kind == 'wrong-node' else 'compute-a\n') *
                            (23 if nodefile_kind == 'wrong-count' else 24))
    if nodefile_kind == 'symlink':
        link = tmp_path / 'nodefile-link'
        link.symlink_to(nodefile)
        nodefile = link
    environment = dict(os.environ, PBS_NODEFILE=str(nodefile), PBS_JOBID='123.fixture',
                       PBS_O_WORKDIR=str(work), PATH=str(binary) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['sh'], input=script, cwd=work, env=environment, capture_output=True)
    assert (result.returncode == 0) is (nodefile_kind == 'correct'), result.stderr
    for name in ('scratch', 'ag-start.json', 'ag-exit.json', 'program-was-run'):
        assert (work / name).exists() is (nodefile_kind == 'correct')
    if nodefile_kind == 'correct':
        assert json.loads((work / 'ag-start.json').read_text())['PBS_JOBID'] == START['PBS_JOBID']
