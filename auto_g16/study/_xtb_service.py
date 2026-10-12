"""Fixed installed xTB coordination; native owners retain all authority."""
from datetime import datetime, timezone
import re
import unicodedata
from auto_g16.execution._study_stage_session import _open_study_xtb_session
from . import _registered_runtime as registered, _xtb_preview, _xtb_files
from ._model import binding, closed, decode, digest, encode, plain, require
from .service import operate


def _response(session, action, state, data):
    registration = plain(session.scope.registration_ref)
    value = registration['registration']
    return dict(schema='auto-g16-study-xtb-response/1', action=action,
        study_id=value['study_id'], stage='xtb', request_sha256=value['request_sha256'],
        registration_sha256=registration['file_binding']['sha256'], state=state, data=data)


def _decision(raw, preview, *, current=False):
    value = closed(decode(raw, cap=2 << 20), {'schema', 'preview_sha256', 'study_id',
        'attempt_id', 'decision', 'reviewer_id', 'evidence', 'window', 'effects'})
    require(raw == encode(value) and value['schema'] == 'auto-g16-study-xtb-preparation-decision/1'
            and value['decision'] == 'APPROVED' and value['preview_sha256'] == digest(encode(preview))
            and value['study_id'] == preview['study_id']
            and value['attempt_id'] == preview['identities']['attempt_id'], 'invalid-request')
    reviewer = value['reviewer_id']
    require(type(reviewer) is str and 0 < len(reviewer) <= 256 and reviewer.strip()
            and not any(unicodedata.category(c).startswith('C') for c in reviewer), 'invalid-request')
    binding(value['evidence'], 'invalid-request')
    window = closed(value['window'], {'starts_at', 'expires_at'}, 'invalid-request')
    for stamp in window.values():
        require(type(stamp) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', stamp),
                'invalid-request')
        datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%S.%fZ')
    require(window['starts_at'] < window['expires_at'], 'invalid-request')
    require(encode(value['effects']) == encode(dict(observe_project=3, provision_project=1, submit_qsub=0)),
            'invalid-request')
    if current:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        require(window['starts_at'] <= now <= window['expires_at'], 'preparation-required')
    return value


def _stored_decision(session, preview, *, current=False):
    reviews = _xtb_files.root(session, 'reviews')
    names = reviews.names() & {'xtb-preparation.json', 'xtb-preparation-evidence'}
    if not names:
        return None
    require(len(names) == 2, 'preparation-unresolved')
    raw, _ = reviews.read('xtb-preparation.json')
    value = _decision(raw, preview, current=current)
    evidence, _ = reviews.read('xtb-preparation-evidence', 16 << 20)
    require(digest(evidence) == value['evidence']['sha256']
            and len(evidence) == value['evidence']['size_bytes'], 'preparation-unresolved')
    return raw


def authorize_preparation(directory, captured):
    creation = operate('status', directory)
    require(creation['schema'] == 'auto-g16-direct-study-response/2', 'stage-not-supported')
    with registered.open_registered(creation['study_id']) as scope:
        require(scope.registration_ref['registration']['creation_binding']['path'] == directory,
                'runtime-unresolved')
        with _open_study_xtb_session(scope, 'authorize-preparation') as session:
            captured.assert_current(scope)
            inputs = _xtb_preview.build(session)
            raw = captured.raw
            _decision(raw, inputs.preview)
            existing = _stored_decision(session, inputs.preview)
            if existing is None:
                reviews = _xtb_files.root(session, 'reviews')
                captured.assert_current(scope)
                reviews.publish('xtb-preparation-evidence', captured.evidence_raw, cap=16 << 20)
                reviews.publish('xtb-preparation.json', raw)
            else:
                require(existing == raw, 'preparation-unresolved')
            require(_stored_decision(session, inputs.preview) == raw, 'preparation-unresolved')
            captured.assert_current(scope)
            result = _response(session, 'authorize-preparation', 'preparation-authorized',
                               dict(request_sha256=digest(raw), receipt=None))
    return result


def review(directory):
    creation = operate('status', directory)
    require(creation['schema'] == 'auto-g16-direct-study-response/2', 'stage-not-supported')
    with registered.open_registered(creation['study_id']) as scope:
        require(scope.registration_ref['registration']['creation_binding']['path'] == directory,
                'runtime-unresolved')
        with _open_study_xtb_session(scope, 'review') as session:
            inputs = _xtb_preview.build(session)
            from . import _xtb_prepared
            decision = _stored_decision(session, inputs.preview)
            prepared = _xtb_prepared.load(session, inputs, decision)
            result = _response(session, 'review', 'local-only' if prepared is None else 'prepared', dict(
                preview=plain(inputs.preview), preview_sha256=digest(encode(inputs.preview)),
                prepared=None if prepared is None else prepared['record'], missing=['collection-authorization', 'native-approvals']
                    + (['preparation-decision'] if decision is None else [])))
    return result


def prepare(directory):
    from auto_g16.execution import _study_preparation as native, program, project_provisioning
    from auto_g16.transport._program_rtwin import _RTWinProjectAttestor
    from . import _xtb_prepared
    creation = operate('status', directory)
    require(creation['schema'] == 'auto-g16-direct-study-response/2', 'stage-not-supported')
    with registered.open_registered(creation['study_id']) as scope:
        require(scope.registration_ref['registration']['creation_binding']['path'] == directory,
                'runtime-unresolved')
        with _open_study_xtb_session(scope, 'prepare') as session:
            inputs = _xtb_preview.build(session)
            decision = _stored_decision(session, inputs.preview)
            require(decision is not None, 'preparation-required')
            loaded = _xtb_prepared.load(session, inputs, decision)
            if loaded is None:
                with native.prepare_once(session, inputs):
                    attestor = _RTWinProjectAttestor(current_profile=inputs.current_profile, target=inputs.target)
                    service = project_provisioning._ProjectProvisioningService._from_project_attestor(
                        attestor=attestor, target=inputs.target, journal=scope.stores['project'])
                    project_binding = service.provision_remote_project(project=inputs.project,
                        target=inputs.target, remote_project_dir=inputs.preview['paths']['remote_project_dir'],
                        evidence_identity=None, stored_binding=None)
                    factory = program._ProgramExecutionSnapshotService._for_production(
                        project_provisioning=service, target=inputs.target)
                    ids = inputs.preview['identities']
                    snapshot = factory.prepare(scope.stores['core'], attempt_id=ids['attempt_id'],
                        calculation_plan_id=ids['calculation_plan_id'], resource_spec_id=ids['resource_spec_id'],
                        program_execution_spec=inputs.spec, project_physical_binding=project_binding,
                        resolved_resource_request=inputs.resources, resolved_server_profile=inputs.target,
                        workspace_binding=inputs.workspace, completion_rendering_material=inputs.material)
                loaded = _xtb_prepared.publish(session, inputs, decision, snapshot)
            _xtb_prepared.acknowledge(session, loaded)
            require(_xtb_prepared.load(session, inputs, decision)['acknowledged'], 'preparation-unresolved')
            state = scope.stores['core'].attempt_state(inputs.preview['identities']['attempt_id']).value
            result = _response(session, 'prepare', 'prepared', dict(
                operation_id=loaded['receipt']['operation_id'], acknowledgement='acknowledged',
                native_state=dict(actual_core_state=state, lifecycle=None, unavailable_reason='job-not-established')))
    return result
