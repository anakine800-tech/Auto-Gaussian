"""Exact local approval import using the original registered native owners."""
from uuid import UUID, uuid5
import unicodedata

from auto_g16 import approval
from auto_g16.approval.models import canonical_bytes as approval_canonical_bytes
from auto_g16.execution import _program_completion as completion
from auto_g16.transport import _driver, _program_rtwin as rtwin
from scripts import run_v31_publisher_pilot as controller
from . import _installation, _xtb_files
from ._model import binding, closed, decode, digest, encode, plain, require

_BASIS = 'v31-publisher-pilot-deployment.json'
_EXPECTED = 'expected-native-approvals.json'
_SUMMARY = 'authorization-receipt.json'
_IDS = ('scientific_approval_id', 'batch_submit_approval_id', 'operational_confirmation_id')


def publisher_file(value):
    binding(value)
    return rtwin._PublisherFileBinding(value['path'], tuple(tuple(n) for n in value['parent_chain']),
        tuple(value['file_identity']), value['sha256'], value['size_bytes'])


def packet(raw, session, inputs, prepared):
    value = closed(decode(raw, 'invalid-request', 2 << 20), {'schema', 'study_id', 'prepared_sha256', 'scientific',
                                 'batch', 'operational', 'publisher'}, 'invalid-request')
    require(raw == encode(value) and value['schema'] == 'auto-g16-study-xtb-authorization/1'
        and value['study_id'] == inputs.preview['study_id']
        and value['prepared_sha256'] == digest(encode(prepared['record'])), 'invalid-request')
    for role in ('scientific', 'batch', 'operational'):
        decision = closed(value[role], {'decision', 'reviewer_id', 'evidence'}, 'invalid-request')
        reviewer = decision['reviewer_id']
        require(decision['decision'] == 'APPROVED' and type(reviewer) is str
            and 0 < len(reviewer) <= 256 and reviewer.strip()
            and not any(unicodedata.category(c).startswith('C') for c in reviewer), 'invalid-request')
        binding(decision['evidence'], 'invalid-request')
    publisher = closed(value['publisher'], {'window', 'qualification', 'evidence',
        'owner_q_acceptance_sha256', 'pilot_live_gate_sha256'}, 'invalid-request')
    require(publisher['qualification'] == plain(session.context.facts.qualification_binding),
            'qualification-required')
    binding(publisher['qualification'], 'invalid-request')
    evidence = publisher['evidence']
    require(type(evidence) is list and 1 <= len(evidence) <= 256, 'invalid-request')
    for item in evidence:
        binding(item, 'invalid-request')
        require(item['size_bytes'] <= 16 << 20, 'invalid-request')
    hashes = {item['sha256'] for item in evidence}
    require(len(hashes) == len(evidence), 'invalid-request')
    for key in ('owner_q_acceptance_sha256', 'pilot_live_gate_sha256'):
        _installation._hash(publisher[key])
        require(publisher[key] in hashes, 'qualification-required')
    return value


def _documents(session, inputs, prepared, value, raw_evidence):
    snapshot, facts = prepared['snapshot'], session.context.facts
    q = completion._decode_publisher_qualification(inputs.current_profile.runtime_contents[completion._Q_NAME])
    publisher, qualified = value['publisher'], plain(facts.qualification_binding)
    rtwin._publisher_window(publisher['window'], q['payload']['observation_window'])
    payload = q['payload']
    required = [payload['execution_domain']['scheduler_scope_evidence'],
                payload['controller_probe']['evidence']]
    for host in payload['hosts']:
        required.extend([host['identity_evidence'], *(row['evidence'] for row in host['locations']),
                         *(row['evidence'] for row in host['probes'])])
    require(all(row['sha256'] in raw_evidence and len(raw_evidence[row['sha256']]) == row['size_bytes']
                for row in required), 'qualification-required')
    require(raw_evidence.get(payload['evidence_manifest_sha256'])
            == completion._receipt_json(controller._probe_index(payload)), 'qualification-required')
    basis = dict(schema='auto-g16-v31-publisher-pilot-deployment/1',
        source_commit=facts.source_commit, source_tree=facts.source_tree,
        resolved_server_profile_id=inputs.target.resolved_server_profile_id,
        effective_config_sha256=inputs.target.effective_config_sha256,
        program_execution_snapshot_id=snapshot.program_execution_snapshot_id,
        qualification_payload_sha256=q['payload_sha256'], qualification_file_sha256=qualified['sha256'],
        qualification_size_bytes=qualified['size_bytes'], qualification_path=qualified['path'],
        qualification_parent_chain=[dict(device=d, inode=i) for d, i in qualified['parent_chain']],
        qualification_file_identity=dict(zip(('device', 'inode'), qualified['file_identity'])),
        probe_evidence_manifest_sha256=q['payload']['evidence_manifest_sha256'],
        owner_q_acceptance_evidence_sha256=publisher['owner_q_acceptance_sha256'],
        pilot_live_gate_evidence_sha256=publisher['pilot_live_gate_sha256'], pilot_window=publisher['window'])
    require(set(basis) == rtwin._PUBLISHER_BASIS_KEYS)
    qscope = {k: basis[k] for k in ('qualification_payload_sha256', 'qualification_file_sha256')}
    live = {**qscope, **{k: basis[k] for k in ('resolved_server_profile_id',
                'program_execution_snapshot_id', 'pilot_window')}, 'attempt_id': snapshot.attempt_id}
    reviewed = dict(schema='v31-publisher-reviewed-scope/1')
    for role, scope, key in (('owner_exact_q', qscope, 'owner_q_acceptance_sha256'),
                             ('live_gate', live, 'pilot_live_gate_sha256')):
        sha = publisher[key]
        reviewed[role] = dict(raw=dict(sha256=sha, size_bytes=len(raw_evidence[sha])), scope=scope)
    return basis, completion._receipt_json(basis), completion._receipt_json(reviewed)


def _native_approvals(session, inputs, prepared, value, raw, basis, basis_ref):
    core = session.scope.stores['core']
    snapshot = prepared['snapshot']
    def provenance(role):
        return dict(request_sha256=digest(raw), evidence=value[role]['evidence'])
    scientific = approval.ScientificApproval.for_plan(core,
        core.load_calculation_plan(snapshot.calculation_plan_id),
        displayed_semantic_meaning=inputs.preview['displayed_semantic_meaning'],
        reviewer_id=value['scientific']['reviewer_id'], reviewer_evidence=provenance('scientific'),
        decision=approval.ApprovalDecision.APPROVED)
    batch = approval.BatchSubmitApproval.for_existing_attempts(core, [(snapshot.attempt_id, scientific)],
        reviewer_id=value['batch']['reviewer_id'], reviewer_evidence=provenance('batch'),
        decision=approval.ApprovalDecision.APPROVED)
    attachment = {key: basis[key] for key in controller._PILOT_ATTACHMENT_KEYS
                  if key != 'deployment_readback_evidence_sha256'}
    attachment['deployment_readback_evidence_sha256'] = basis_ref['sha256']
    operational = approval.ExactOperationalConfirmation.for_snapshot(core, snapshot,
        confirmer_id=value['operational']['reviewer_id'],
        confirmer_evidence={**provenance('operational'), 'publisher_pilot': attachment},
        decision=approval.ApprovalDecision.APPROVED)
    return scientific, batch, operational


def _run_package(session, inputs, prepared, records, reviewed_ref):
    from auto_g16.execution import _program_artifacts, _program_completion_wrapper, program, program_runtime
    bindings = []
    for role in ('core', 'approval', 'transport'):
        store = session.scope.stores[role]
        value = store.assert_existing_binding()
        bindings.append(controller._PilotStoreBinding(role, store, value['path'],
            tuple(tuple(p) for p in value['parent_chain']), tuple(value['file_identity'])))
    pins, code = session.context.inspection.pins, []
    for module in (_program_artifacts, completion, _program_completion_wrapper,
                   program, program_runtime, rtwin, controller):
        path = module.__file__
        require(path in pins.nodes, 'runtime-source-mismatch')
        _, sha, _, size = pins.read(path, 4 << 20)
        code.append(publisher_file(pins.binding(path, file=True, digest=sha, size=size)))
    return controller._FixedPilotRun(prepared['snapshot'], inputs.current_profile, tuple(bindings),
        *(getattr(record, identity) for record, identity in zip(records, _IDS)),
        inputs.preview['displayed_semantic_meaning'], inputs.preview['input']['content_utf8'].encode(),
        prepared['snapshot'].scheduler_artifacts[0]['content_utf8'].encode(),
        publisher_file(reviewed_ref), tuple(code))


def import_approvals(session, inputs, prepared, captured):
    from auto_g16.execution._study_authorization import review_material
    session.require_action('authorize')
    require(prepared is not None and prepared['acknowledged'], 'preparation-required')
    captured.assert_current(session.scope)
    raw = captured.raw
    value = packet(raw, session, inputs, prepared)
    originals = [value[role]['evidence'] for role in ('scientific', 'batch', 'operational')]
    originals += value['publisher']['evidence']
    raw_evidence = {}
    for original in originals:
        content = captured.content(original)
        require(original['size_bytes'] == len(content) and original['sha256'] == digest(content))
        raw_evidence[original['sha256']] = content
    basis, basis_raw, reviewed_raw = _documents(session, inputs, prepared, value, raw_evidence)
    blobs = {'authorization.json': raw, _BASIS: basis_raw, 'reviewed-scope.json': reviewed_raw,
             **raw_evidence}
    reviews = _xtb_files.root(session, 'reviews')
    fresh = 'xtb-publisher' not in reviews.names()
    publisher = _xtb_files.directory(session, 'publisher-root', create=fresh)
    if fresh:
        require(not publisher.names(), 'runtime-unresolved')
        for name in ('authorization.json', *sorted(raw_evidence), _BASIS, 'reviewed-scope.json'):
            captured.assert_current(session.scope)
            publisher.publish(name, blobs[name], cap=16 << 20 if name in raw_evidence else 2 << 20)
    require(publisher.names() in (set(blobs), set(blobs) | {_SUMMARY}), 'runtime-unresolved')
    refs = {}
    for name, content in blobs.items():
        observed, refs[name] = publisher.read(name, 16 << 20 if name in raw_evidence else 2 << 20)
        require(observed == content, 'runtime-unresolved')
    records = _native_approvals(session, inputs, prepared, value, raw, basis, refs[_BASIS])
    identities = {identity: getattr(record, identity) for record, identity in zip(records, _IDS)}
    registration = plain(session.scope.registration_ref)
    intent = dict(schema='auto-g16-study-xtb-operation-intent/1',
        operation_id=str(uuid5(UUID(value['study_id']), 'auto-g16-study-xtb-operation/1:authorization')),
        kind='authorization', study_id=value['study_id'], request_sha256=inputs.preview['request_sha256'],
        registration_sha256=registration['file_binding']['sha256'],
        predecessor_sha256=value['prepared_sha256'], authorization_sha256=digest(raw))
    expected = dict(schema='auto-g16-study-xtb-expected-native-approvals/1',
        intent_sha256=digest(encode(intent)), request_sha256=digest(raw),
        prepared_sha256=value['prepared_sha256'], **identities)
    operation = _xtb_files.directory(session, 'operation-authorization', create=fresh)
    if fresh:
        require(not operation.names(), 'runtime-unresolved')
        operation.publish('intent.json', encode(intent))
        operation.publish(_EXPECTED, encode(expected))
    require(operation.names() in ({'intent.json', _EXPECTED}, {'intent.json', _EXPECTED, 'receipt.json'}),
            'runtime-unresolved')
    require(operation.read('intent.json')[0] == encode(intent), 'runtime-unresolved')
    observed, expected_ref = operation.read(_EXPECTED)
    require(observed == encode(expected), 'runtime-unresolved')
    installation = rtwin._FixedPublisherInstallation(publisher_file(refs[_BASIS]),
        publisher_file(plain(session.context.facts.qualification_binding)),
        tuple(publisher_file(refs[item['sha256']]) for item in value['publisher']['evidence']),
        session.context.facts.source_commit, session.context.facts.source_tree)
    run = _run_package(session, inputs, prepared, records, refs['reviewed-scope.json'])
    authority = _driver._resolve_closed_profile_authority(inputs.target, inputs.current_profile,
        prepared['snapshot'].program_execution_snapshot_id, successor=True)
    store, references = session.scope.stores['approval'], []
    with review_material(session, installation, authority, prepared['snapshot']) as deployment:
        controller._validate_pilot_qualification_evidence(run, deployment, records[2])
        for role, identity, record, suffix in zip(('scientific', 'batch', 'operational'), _IDS, records,
                ('scientific_approval', 'batch_submit_approval', 'operational_confirmation')):
            captured.assert_current(session.scope)
            session.require_action('authorize')
            deployment.assert_current()
            try:
                existing = getattr(store, 'load_' + suffix)(identities[identity])
            except approval.ApprovalStoreNotFoundError:
                require('receipt.json' not in operation.names() and _SUMMARY not in publisher.names(),
                        'runtime-unresolved')
                getattr(store, 'store_' + suffix)(record)
                existing = getattr(store, 'load_' + suffix)(identities[identity])
            require(existing.persisted_payload() == record.persisted_payload(), 'runtime-unresolved')
            references.append(dict(role=role, id=identities[identity],
                                   sha256=digest(approval_canonical_bytes(existing.persisted_payload()))))
        approval.validate_effect_authority(runtime_store=session.scope.stores['core'],
            attempt=session.scope.stores['core'].load_attempt(prepared['snapshot'].attempt_id),
            plan=session.scope.stores['core'].load_calculation_plan(prepared['snapshot'].calculation_plan_id),
            displayed_semantic_meaning=inputs.preview['displayed_semantic_meaning'],
            scientific_approval=records[0], batch_submit_approval=records[1],
            execution_snapshot=prepared['snapshot'], operational_confirmation=records[2])
    summary = dict(schema='auto-g16-study-xtb-authorization-receipt/1', request_sha256=digest(raw),
        prepared_sha256=value['prepared_sha256'], **identities, basis=refs[_BASIS],
        reviewed_scope=refs['reviewed-scope.json'])
    if _SUMMARY not in publisher.names():
        publisher.publish(_SUMMARY, encode(summary))
    observed, summary_ref = publisher.read(_SUMMARY)
    require(observed == encode(summary), 'runtime-unresolved')
    receipt = dict(schema='auto-g16-study-xtb-operation-receipt/1', operation_id=intent['operation_id'],
        intent_sha256=digest(encode(intent)), outcome='acknowledged', native_references=references,
        artifacts=[refs[name] for name in ('authorization.json', _BASIS, 'reviewed-scope.json',
                                            *sorted(raw_evidence))] + [expected_ref, summary_ref])
    if 'receipt.json' not in operation.names():
        operation.publish('receipt.json', encode(receipt))
    require(operation.read('receipt.json')[0] == encode(receipt), 'runtime-unresolved')
    captured.assert_current(session.scope)
    return receipt
