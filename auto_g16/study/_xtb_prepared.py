"""Exact local preparation readback; only native owners produce the snapshot."""
from auto_g16.execution import program, _study_preparation as native
from . import _xtb_files
from ._model import decode, digest, encode, plain, require

_NAMES = {'input.xyz', 'xtb.pbs', 'snapshot.json', 'prepared.json'}
_CAPS = {'input.xyz': 16 << 20, 'snapshot.json': 8 << 20,
         'xtb.pbs': 2 << 20, 'prepared.json': 2 << 20}


def _record(inputs, decision, snapshot, input_binding, pbs_binding):
    preview = inputs.preview
    return dict(schema='auto-g16-study-xtb-prepared/1', study_id=preview['study_id'],
        request_sha256=preview['request_sha256'], preview_sha256=digest(encode(preview)),
        preparation_decision_sha256=digest(decision),
        project_binding=plain(snapshot.project_physical_binding.semantic_payload()),
        snapshot_semantics=plain(snapshot._approval_semantics()), input=input_binding, pbs=pbs_binding,
        displayed_semantic_meaning=plain(preview['displayed_semantic_meaning']),
        installation=plain(preview['installation']))


def _validate_snapshot(session, inputs, snapshot):
    snapshot.assert_identity_closed()
    snapshot._assert_current_core(session.scope.stores['core'])
    ids = inputs.preview['identities']
    require(snapshot.attempt_id == ids['attempt_id']
        and snapshot.calculation_plan_id == ids['calculation_plan_id']
        and snapshot.program_execution_spec == inputs.spec
        and snapshot.resolved_resource_request == inputs.resources
        and snapshot.resolved_server_profile == inputs.target
        and snapshot.workspace_binding.semantic_payload() == inputs.workspace.semantic_payload()
        and snapshot._completion_material() == inputs.material, 'preparation-unresolved')
    return native.preparation_references(session, snapshot)


def load(session, inputs, decision):
    """No output reconstruction or remote call when a partial record exists."""
    root = _xtb_files.root(session, 'prepared')
    if not root.names():
        require(not _xtb_files.root(session, 'operations').names(), 'preparation-unresolved')
        return None
    require(decision is not None, 'preparation-unresolved')
    prepared = _xtb_files.directory(session, 'prepared-root')
    require(prepared.names() == _NAMES, 'preparation-unresolved')
    blobs = {name: prepared.read(name, _CAPS[name]) for name in sorted(_NAMES)}
    snapshot_raw = blobs['snapshot.json'][0]
    semantics = decode(snapshot_raw, cap=_CAPS['snapshot.json'])
    require(snapshot_raw == encode(semantics), 'preparation-unresolved')
    snapshot = program._decode_program_review_semantics(semantics)
    references = _validate_snapshot(session, inputs, snapshot)
    require(blobs['input.xyz'][0] == inputs.preview['input']['content_utf8'].encode('utf-8')
        and len(snapshot.scheduler_artifacts) == 1
        and snapshot.scheduler_artifacts[0]['portable_name'] == 'xtb.pbs'
        and blobs['xtb.pbs'][0] == snapshot.scheduler_artifacts[0]['content_utf8'].encode('utf-8'),
        'preparation-unresolved')
    expected = _record(inputs, decision, snapshot, blobs['input.xyz'][1], blobs['xtb.pbs'][1])
    require(blobs['prepared.json'][0] == encode(expected), 'preparation-unresolved')
    operation = _xtb_files.directory(session, 'operation-preparation')
    intent = native.operation_intent(session, inputs, decision)
    intent_raw = operation.read('intent.json')[0]
    require(intent_raw == encode(intent), 'preparation-unresolved')
    names = {'intent.json', *(f'step-{i:02d}-{kind}.json'
              for i in range(1, 5) for kind in ('entered', 'capture'))}
    require(operation.names() in (names, names | {'receipt.json'}), 'preparation-unresolved')
    captures = []
    for i, op in enumerate(inputs.preview['preparation_sequence'], 1):
        step = dict(schema='auto-g16-study-xtb-effect-step/1', operation_id=intent['operation_id'],
                    ordinal=i, operation=op, decision_sha256=intent['authorization_sha256'])
        require(operation.read(f'step-{i:02d}-entered.json')[0] == encode(step), 'preparation-unresolved')
        raw, reference = operation.read(f'step-{i:02d}-capture.json')
        capture = decode(raw)
        require(type(capture) is dict and set(capture) == {'schema', 'operation_id', 'ordinal',
            'operation', 'transport_evidence', 'process_evidence'} and raw == encode(capture)
            and capture['schema'] == 'auto-g16-study-xtb-project-capture/1'
            and capture['operation_id'] == intent['operation_id'] and type(capture['ordinal']) is int
            and capture['ordinal'] == i and capture['operation'] == op, 'preparation-unresolved')
        native.verify_capture(session, inputs, snapshot, i, capture)
        captures.append(reference)
    receipt = dict(schema='auto-g16-study-xtb-operation-receipt/1', operation_id=intent['operation_id'],
        intent_sha256=digest(intent_raw), outcome='acknowledged', native_references=references,
        artifacts=[blobs[name][1] for name in ('input.xyz', 'xtb.pbs', 'snapshot.json', 'prepared.json')] + captures)
    acknowledged = 'receipt.json' in operation.names()
    if acknowledged:
        require(operation.read('receipt.json')[0] == encode(receipt), 'preparation-unresolved')
    return dict(record=expected, snapshot=snapshot, receipt=receipt, acknowledged=acknowledged,
                operation=operation)


def publish(session, inputs, decision, snapshot):
    session.require_action('prepare')
    _validate_snapshot(session, inputs, snapshot)
    prepared = _xtb_files.directory(session, 'prepared-root')
    require(not prepared.names(), 'preparation-unresolved')
    input_binding = prepared.publish('input.xyz', inputs.preview['input']['content_utf8'].encode('utf-8'),
                                     cap=_CAPS['input.xyz'])
    require(len(snapshot.scheduler_artifacts) == 1
            and snapshot.scheduler_artifacts[0]['portable_name'] == 'xtb.pbs', 'preparation-unresolved')
    pbs_binding = prepared.publish('xtb.pbs', snapshot.scheduler_artifacts[0]['content_utf8'].encode('utf-8'),
                                  cap=_CAPS['xtb.pbs'])
    prepared.publish('snapshot.json', encode(snapshot._approval_semantics()), cap=_CAPS['snapshot.json'])
    prepared.publish('prepared.json', encode(_record(inputs, decision, snapshot, input_binding, pbs_binding)),
                     cap=_CAPS['prepared.json'])
    return load(session, inputs, decision)


def acknowledge(session, loaded):
    session.require_action('prepare')
    if not loaded['acknowledged']:
        loaded['operation'].publish('receipt.json', encode(loaded['receipt']))
    require(loaded['operation'].read('receipt.json')[0] == encode(loaded['receipt']),
            'preparation-unresolved')
