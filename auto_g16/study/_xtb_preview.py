"""Local xTB inputs from the original installed Study; no native effects."""
from dataclasses import dataclass, fields
import os

from auto_g16.execution import models, program
from auto_g16.execution._identity import freeze_mapping
from auto_g16.execution import _program_completion as completion
from auto_g16.execution._project_association_source import _profile
from auto_g16.transport import _driver
from . import _fresh_model, _xtb_files
from ._model import digest, encode, plain, require


@dataclass(frozen=True, slots=True)
class _Inputs:
    preview: object
    current_profile: object
    target: object
    project: object
    spec: object
    resources: object
    workspace: object
    material: object


def build(session):
    """Build only the unallocated original xTB Attempt preview."""
    session.require_action('review', 'authorize-preparation', 'prepare', 'authorize')
    context, scope = session.context, session.scope
    facts, pins = context.facts, context.inspection.pins

    def original_file(value):
        expected = plain(value)
        # Both inputs were opened by the installation owner before native stores.
        require(expected['path'] in pins.nodes, 'runtime-source-mismatch')
        raw, sha, _, size = pins.read(expected['path'], 1 << 20)
        require(pins.binding(expected['path'], file=True, digest=sha, size=size) == expected,
                'runtime-source-mismatch')
        return raw

    current, target = _profile(original_file(facts.profile_binding))
    qraw = original_file(facts.qualification_binding)
    require(current.runtime_contents.get(completion._Q_NAME) == qraw,
            'qualification-required')
    q = completion._decode_publisher_qualification(qraw)
    implementation = q['payload']['implementation']
    require((implementation['commit'], implementation['tree'])
            == (facts.source_commit, facts.source_tree), 'qualification-required')
    require(q['payload']['scope']['program_kind'] == 'xtb', 'qualification-required')
    material = completion._prepare_publisher_pilot_rendering_material(current, target)
    require(material['schema'] == completion._PILOT_MATERIAL_SCHEMA,
            'qualification-required')
    _driver._resolve_closed_profile_authority(target, current,
        target.resolved_server_profile_id, successor=True)

    request = plain(scope.request)
    ids = _fresh_model.identities(request)
    stage = ids['stages']['xtb']
    core = scope.stores['core']
    project = core.load_project(ids['project_id'])
    original = _fresh_model.records(request)
    for expected, method in zip(original, ('load_project', 'load_workflow_run', 'load_task',
            'load_calculation_plan', 'load_resource_spec', 'load_attempt')):
        identity = getattr(expected, fields(expected)[0].name)
        require(encode(getattr(core, method)(identity)) == encode(expected), 'runtime-unresolved')
    require(core.attempt_state(stage['attempt_id']).value == 'PLANNED'
            and core.load_submission_intent(stage['attempt_id']) is None,
            'runtime-unresolved')
    resource = core.load_resource_spec(stage['resource_id'])
    resources = models.ResolvedResourceRequest(resource_spec=resource, **request['resources']['xtb'])
    require(q['payload']['execution_domain']['queue'] == resources.queue,
            'qualification-required')
    raw = request['structure']['xyz_utf8'].encode('utf-8')
    executable = target.runtime_identities['xtb']
    spec = program._prepare_program_execution_spec(program_kind='xtb',
        executable_path=target.platform_paths['xtb_executable_path'],
        executable_size_bytes=executable['size_bytes'], executable_sha256=executable['sha256'],
        input_name='input.xyz', input_bytes=raw,
        program_data=dict(model='gfn2', task='optimize', charge=0, unpaired_electrons=0, solvent=None),
        resolved_profile=target, completion_mode=completion._MODE, startup_mode=None)
    artifacts = _xtb_files.root(session, 'artifacts')
    try:
        os.stat(stage['attempt_id'], dir_fd=artifacts.fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        require(False, 'runtime-unresolved')
    paths = dict(remote_project_dir=target.remote_root + '/' + project.project_id,
        remote_attempt_dir=target.remote_root + '/' + project.project_id + '/' + stage['attempt_id'],
        local_approved_root=artifacts.path, local_attempt_dir=artifacts.path + '/' + stage['attempt_id'],
        rtwin_attempt_dir=None)
    workspace = models.WorkspaceBinding(project=project, attempt_id=stage['attempt_id'],
        local_approved_root=paths['local_approved_root'], local_attempt_dir=paths['local_attempt_dir'],
        remote_approved_root=target.remote_root, remote_attempt_dir=paths['remote_attempt_dir'],
        rtwin_approved_root=None, rtwin_attempt_dir=None)
    registration = plain(scope.registration_ref)
    value = dict(schema='auto-g16-study-xtb-preview/1',
        study_id=registration['registration']['study_id'],
        request_sha256=registration['registration']['request_sha256'],
        registration_sha256=registration['file_binding']['sha256'],
        identities=dict(project_id=ids['project_id'], workflow_run_id=ids['workflow_run_id'],
            task_id=stage['task_id'], calculation_plan_id=stage['plan_id'],
            resource_spec_id=stage['resource_id'], attempt_id=stage['attempt_id']),
        installation=registration['registration']['installation'],
        profile_binding=plain(facts.profile_binding), qualification_binding=plain(facts.qualification_binding),
        program_execution_spec=plain(spec.semantic_payload()), resources=plain(resources.semantic_payload()),
        paths=paths, input=dict(portable_name='input.xyz', sha256=digest(raw), size_bytes=len(raw),
                               content_utf8=raw.decode('utf-8')),
        displayed_semantic_meaning=dict(structure=request['structure'], protocol=request['protocol']['xtb'],
            resources=request['resources']['xtb'], input_sha256=digest(raw),
            program_execution_spec_id=spec.program_execution_spec_id,
            resolved_server_profile_id=target.resolved_server_profile_id),
        preparation_sequence=['OBSERVE_PROJECT', 'OBSERVE_PROJECT', 'PROVISION_PROJECT', 'OBSERVE_PROJECT'])
    session.assert_current()
    return _Inputs(freeze_mapping(value, 'Study xTB preview'), current, target, project, spec,
                   resources, workspace, material)
