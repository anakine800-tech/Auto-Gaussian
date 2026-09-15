"""External synthetic fixture using real product factories. Linux invocation only.

Never patches product code, argv, spec, material, source, or approved records.
Q evidence entries deliberately reference a pre-existing SYNTHETIC artifact;
its PASS strings are grammar fixtures, not qualification results.
"""
import base64
from dataclasses import replace
import hashlib
import json
import copy
from pathlib import Path
import shlex

from linux_observer import observe

ACTOR = Path('/opt/auto-g16-fixtures/bin/xtb')
REMOTE = Path('/home/user100/SDL')
XYZ = b'2\nR4 INERT ONLY\nH 0 0 0\nH 0 0 0.74\n'
DATA_FILES = ('.param_gfnff.xtb', 'config_env.bash', 'config_env.csh', 'param_gfn0-xtb.txt',
              'param_gfn1-si-xtb.txt', 'param_gfn1-xtb.txt', 'param_gfn2-xtb.txt', 'param_ipea-xtb.txt')


def digest(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}


def new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def build(case, case_root, project_dir, python, lock, mutate_expected):
    # Imports happen only AFTER parent runner checks the exact committed tree/files.
    from auto_g16 import core, execution
    from auto_g16.execution import program
    from auto_g16.execution import _program_completion as completion
    from auto_g16.execution.project_provisioning import (
        _SYNTHETIC_TEST_HARNESS_PRIVILEGE as privilege,
        _SyntheticRemoteProjectAttestor, _ProjectProvisioningService,
    )
    from auto_g16.execution._identity import semantic_sha256, freeze_mapping

    canonical = completion._receipt_json
    semantic = lambda value: semantic_sha256(freeze_mapping(value, 'R4 harness'))
    assert ACTOR.is_file() and ACTOR == Path('/opt/auto-g16-fixtures/bin/xtb')
    assert project_dir.parent == REMOTE
    workspace = project_dir / 'attempt-1'
    workspace.mkdir(mode=0o700)
    data_root = project_dir / 'runtime-data'
    data_root.mkdir(mode=0o700)
    data_entries = {}
    for name in DATA_FILES:
        content = ('INERT R4 DATA ' + name + '\n').encode()
        new(data_root / name, content)
        data_entries[name] = digest(content)
    data_raw = canonical({'schema': 'auto-g16-v31-xtb-runtime-data-manifest/1', 'files': data_entries})
    actor_raw, python_raw = ACTOR.read_bytes(), python.read_bytes()
    roots = {}
    for name, (platform, attestation) in completion._ROOT_RULES.items():
        shell = name == 'server_remote_shell'
        payload = ('SYNTHETIC UNEXECUTED ' + name + '\n').encode()
        roots[name] = dict(path='/opt/auto-g16-fixtures/bin/' + name, platform=platform,
                           attestation_mode=attestation, deployment_identity='R4-SYNTHETIC-NOT-INSTALLED',
                           expected_sha256=None if shell else digest(payload)['sha256'],
                           expected_size_bytes=None if shell else len(payload),
                           shell_grammar='posix-sh-v1' if shell else None)
    roots['server_python'].update(path=str(python), expected_sha256=digest(python_raw)['sha256'], expected_size_bytes=len(python_raw))
    deployment_raw = canonical(dict(schema='auto-g16-v3-transport-deployment-manifest/3',
                                    deployment_id='R4-INERT-LINUX-NOT-PRODUCTION',
                                    bootstrap_protocol='auto-g16-v31-rtwin-bootstrap/1', trust_roots=roots))
    profile = execution.ServerProfile(
        server_profile_id='r4-linux-inert', profile_revision=1, transport_kind='legacy_rtwin_pbs',
        target_host='invalid.example', target_port=22, remote_user='user100', jump_topology=[],
        host_key_policy='strict', batch_mode=True, identities_only=True, remote_root=str(REMOTE),
        platform_paths={'rtwin_root': r'C:\RTWIN', 'xtb_executable_path': str(ACTOR), 'xtb_data_path': str(data_root)},
        config_files=[('synthetic_config', b'Host invalid.example\n')],
        runtime_contents={'xtb': actor_raw, completion._DEPLOYMENT_NAME: deployment_raw, completion._DATA_NAME: data_raw})
    before_q = execution.resolve_server_profile(profile)
    runtime = dict(deployment_manifest=digest(deployment_raw), server_python={'path': str(python), **digest(python_raw)},
                   xtb={'path': str(ACTOR), **digest(actor_raw)}, xtb_runtime_data_manifest=digest(data_raw))
    actual, raw_observations = observe(runtime, str(REMOTE), str(data_root), semantic)
    for name, raw in raw_observations.items():
        new(case_root / name, raw)
    new(case_root / 'actual-host.json', canonical(actual))
    # This independent immutable fixture precedes Q; no result of this run is fed into Q.
    synthetic_raw = (Path(__file__).parent / 'synthetic-evidence.txt').read_bytes()
    evidence = digest(synthetic_raw)
    window = {'started_at': '2026-09-15T00:00:00.000000Z', 'finished_at': '2026-09-15T00:00:00.000000Z'}
    host = json.loads(canonical(actual))
    mutate_expected(host)
    for loc in host['locations']:
        loc['evidence'] = evidence
    host.update(observed_window=window, identity_evidence=digest(canonical(actual)), probes=[
        dict(case_id=f'P{i:02d}', outcome='PASS', evidence=evidence, observed_window=window) for i in range(1, 8)])
    payload = dict(schema='auto-g16-v31-publisher-qualification/1', contract_sha256=lock['contract_packet_sha256'],
                   scope=dict(backend='legacy_rtwin_pbs', program_kind='xtb', adapter_id='auto-g16-v31-xtb',
                              adapter_contract_version=3, completion_mode='receipt-on-absence-v1', operations=['optimize', 'single-point']),
                   implementation=dict(commit=lock['candidate']['head'], tree=lock['candidate']['tree'],
                                       wrapper_source=lock['source'], probe_source=lock['probe']),
                   profile_basis_sha256=completion._publisher_profile_basis(before_q), runtime=runtime,
                   execution_domain=dict(target_identity_sha256=semantic_sha256(before_q.target_identity),
                                         remote_user='user100', remote_root=str(REMOTE), queue='simple',
                                         eligible_host_keys=[host['host_key']], scheduler_scope_evidence=evidence),
                   hosts=[host], observation_window=window, evidence_manifest_sha256=evidence['sha256'],
                   controller_probe=dict(case_id='P08', outcome='PASS', evidence=evidence, observed_window=window))
    if case['name'] == 'large_q':
        for i in range(12):
            extra = copy.deepcopy(host)
            extra['machine_id_sha256'] = hashlib.sha256(('SYNTHETIC-ELIGIBLE-' + str(i)).encode()).hexdigest()
            extra['host_key'] = semantic({'machine_id_sha256': extra['machine_id_sha256']})
            for loc in extra['locations']:
                loc['mount']['source'] = 'SYNTHETIC-' + 'x' * 4000
            payload['hosts'].append(extra)
        payload['hosts'].sort(key=lambda entry: entry['host_key'])
        payload['execution_domain']['eligible_host_keys'] = [entry['host_key'] for entry in payload['hosts']]
    q_raw = canonical({'payload': payload, 'payload_sha256': semantic(payload)})
    if case['name'] == 'large_q':
        assert 131072 < len(q_raw) <= 1024 * 1024
    new(case_root / 'SYNTHETIC-expected-Q.json', q_raw)
    profile = replace(profile, runtime_contents={**profile.runtime_contents, completion._Q_NAME: q_raw})
    resolved = execution.resolve_server_profile(profile)
    resolved.assert_identity_closed()
    material = completion._prepare_publisher_pilot_rendering_material(profile, resolved)
    new(case_root / 'material.json', canonical(material))
    local_root = case_root / 'local'
    local_root.mkdir(mode=0o700)
    (local_root / 'project-1').mkdir(mode=0o700)
    database = case_root / 'core.sqlite3'
    store = core.SQLiteRuntimeStore(database)
    try:
        project = core.Project(project_id='project-1')
        store.store_project(project)
        store.store_workflow_run(core.WorkflowRun(workflow_run_id='run-1', project_id='project-1', workflow_name='inert-r4'))
        store.store_task(core.Task(task_id='task-1', workflow_run_id='run-1', task_kind='successor-program'))
        store.store_calculation_plan(core.CalculationPlan(calculation_plan_id='plan-1', task_id='task-1', revision=1, intent={'program': 'xtb', 'inert': True}))
        resource = core.ResourceSpec(resource_spec_id='resource-1', task_id='task-1', resources={'tier': 'simple'})
        store.store_resource_spec(resource)
        store.create_attempt(core.Attempt(attempt_id='attempt-1', task_id='task-1', ordinal=1))
        physical = lambda path: 'r4-device-inode-' + str(path.stat().st_dev) + '-' + str(path.stat().st_ino)
        attestor = _SyntheticRemoteProjectAttestor._from_privileged_test_fixture(
            privilege=privilege, target=resolved, observed_project_dir=str(project_dir), observed_state='ABSENT',
            observed_parent_physical_identity=physical(REMOTE), observed_project_physical_identity=None,
            provisioned_project_physical_identity=physical(project_dir))
        provisioning = _ProjectProvisioningService._from_privileged_synthetic_attestor(privilege=privilege, attestor=attestor)
        binding = provisioning.provision_remote_project(project=project, target=resolved, remote_project_dir=str(project_dir), evidence_identity='SYNTHETIC-INERT-NO-REMOTE-EFFECT')
        service = program._ProgramExecutionSnapshotService._for_privileged_synthetic_tests(privilege=privilege, project_provisioning=provisioning)
        resources = execution.ResolvedResourceRequest(resource_spec=resource, cores=1, memory_mb=128,
                                                      walltime_seconds=1 if case['name'] == 'descendant_timeout' else 10, queue='simple')
        wb = execution.WorkspaceBinding(project=project, attempt_id='attempt-1', local_approved_root=str(local_root),
                                        local_attempt_dir=str(local_root / 'project-1' / 'attempt-1'), rtwin_approved_root=r'C:\RTWIN',
                                        rtwin_attempt_dir=r'C:\RTWIN\project-1\attempt-1', remote_approved_root=str(REMOTE), remote_attempt_dir=str(workspace))
        spec = program._prepare_program_execution_spec(program_kind='xtb', executable_path=str(ACTOR),
            executable_size_bytes=len(actor_raw), executable_sha256=digest(actor_raw)['sha256'], input_name='input.xyz', input_bytes=XYZ,
            program_data={'model': 'gfn2', 'charge': 0, 'unpaired_electrons': 0, 'task': 'single-point', 'solvent': None},
            resolved_profile=resolved, completion_mode='receipt-on-absence-v1')
        snapshot = service.prepare(store, attempt_id='attempt-1', calculation_plan_id='plan-1', resource_spec_id='resource-1',
                                   program_execution_spec=spec, project_physical_binding=binding, resolved_resource_request=resources,
                                   resolved_server_profile=resolved, workspace_binding=wb, completion_rendering_material=material)
        snapshot.assert_identity_closed()
        expanded = canonical(snapshot._approval_semantics())
        new(case_root / 'expanded-review.json', expanded)
        reopened = program._validate_program_review_semantics(json.loads(expanded))
        assert canonical(reopened) == expanded
    finally:
        store.close()
    reopened_core = core.SQLiteRuntimeStore(database)
    try:
        snapshot._assert_current_core(reopened_core)
    finally:
        reopened_core.close()
    scheduler = snapshot.scheduler_artifacts[0]['content_utf8']
    new(case_root / 'scheduler.pbs', scheduler.encode())
    assert scheduler.splitlines()[1] == '# auto-g16-v31-scheduler/3'
    # Parse the product's fixed quoted heredoc without evaluating shell text.
    header, remainder = scheduler.split('\nexec ', 1)
    delimiter = "AUTO_G16_PUBLISHER_CONFIG"
    launch, stdin_section = remainder.split(" <<'" + delimiter + "'\n", 1)
    assert stdin_section.endswith('\n' + delimiter + '\n')
    config_line = stdin_section[:-(len(delimiter) + 2)]
    assert '\n' not in config_line
    command = shlex.split(launch)
    assert command[:5] == [str(python), '-I', '-S', '-B', '-c'] and len(command) == 6
    assert digest(command[5].encode()) == lock['source']
    config_raw = base64.b64decode(config_line, validate=True)
    config = json.loads(config_raw)
    assert canonical(config) == config_raw
    new(case_root / 'config.json', config_raw)
    new(case_root / 'config.stdin', (config_line + '\n').encode())
    new(workspace / 'input.xyz', XYZ)
    new(workspace / '.auto-g16-v31-submit-intent', canonical({'program_execution_snapshot_id': snapshot.program_execution_snapshot_id, 'effect_intent_id': snapshot.effect_intent_id}))
    return dict(command=['/bin/bash', str(case_root / 'scheduler.pbs')], python_command=command, snapshot=snapshot, workspace=workspace, data_root=data_root, actual=actual)


def accept_receipt(raw, fixture):
    from auto_g16.execution import _program_completion as completion
    value = completion._decode_receipt(raw)
    import os
    import stat
    path = fixture['workspace']
    current = Path('/')
    chain = [[current.stat().st_dev, current.stat().st_ino]]
    for part in path.parts[1:]:
        current /= part
        info = current.lstat()
        assert stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
        chain.append([info.st_dev, info.st_ino])
    expected_token = base64.b64encode(completion._receipt_json(['v31-directory/1', str(path), chain])).decode()
    assert value['workspace_physical_token'] == expected_token
    bound = completion._bound_receipt(raw, fixture['snapshot'], 'r4.synthetic', expected_token)
    return completion._plain(bound)
