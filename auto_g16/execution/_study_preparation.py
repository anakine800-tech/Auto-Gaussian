"""Native finite Project preparation for the internally current Study session."""
from contextlib import contextmanager
import os
import stat
from uuid import UUID, uuid5

from ._identity import ExecutionValueError, semantic_sha256
from . import _study_stage_session as native


def _require(value):
    if not value:
        raise ExecutionValueError('Study Project preparation authority is absent or consumed')


def operation_intent(session, inputs, decision_raw):
    from auto_g16.study._model import digest
    value = inputs.preview
    return dict(schema='auto-g16-study-xtb-operation-intent/1',
        operation_id=str(uuid5(UUID(value['study_id']), 'auto-g16-study-xtb-operation/1:preparation')),
        kind='preparation', study_id=value['study_id'], request_sha256=value['request_sha256'],
        registration_sha256=value['registration_sha256'], predecessor_sha256=digest_bytes(value),
        authorization_sha256=digest(decision_raw))


def digest_bytes(value):
    from auto_g16.study._model import digest, encode
    return digest(encode(value))


class _CaptureSink:
    """One already-entered Project wire owns one preopened diagnostic file."""
    def __init__(self, preparation):
        from auto_g16.study._xtb_files import _OwnedDescriptors, _signature
        self.preparation = preparation
        self.ordinal = preparation.ordinal + 1
        self.name = f'step-{self.ordinal:02d}-capture.json'
        self.attempted = False
        session, directory = preparation.session, preparation.directory
        preparation.assert_current()
        _require(self.name not in directory.names())
        self.resource = _OwnedDescriptors(session, 'business-file', directory, self.name)
        self.resource.fds.append(os.open(self.name, os.O_RDWR | os.O_CREAT | os.O_EXCL
            | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory.fd))
        before = os.fstat(self.resource.fds[0])
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size == 0)
        self.signature = _signature(before)
        _require(self.signature == _signature(os.stat(self.name, dir_fd=directory.fd, follow_symlinks=False)))
        os.fsync(directory.fd)

    def save(self, captured):
        from auto_g16.study._xtb_files import _signature
        from auto_g16.study._model import encode, plain
        from auto_g16.transport._program_rtwin import _ProjectWireCapture
        preparation = self.preparation
        session, directory = preparation.session, preparation.directory
        # Source failure remains sticky. This does not call a general publisher
        # or confer another operation; only this retained native capture can write.
        session.assert_identity()
        _require(native._CURRENT.get() is session and session._preparation is preparation
            and preparation.entered and not preparation.closed and not self.attempted
            and self.ordinal == preparation.ordinal + 1 and type(captured) is _ProjectWireCapture)
        self.attempted = True
        original = None
        try:
            operation = preparation.inputs.preview['preparation_sequence'][self.ordinal - 1]
            _require(captured.evidence is not None and captured.evidence['operation'] == operation)
            directory._check_physical()
            _require(len(self.resource.fds) == 1)
            fd = self.resource.fds[0]
            _require(_signature(os.fstat(fd)) == self.signature
                == _signature(os.stat(self.name, dir_fd=directory.fd, follow_symlinks=False)))
            raw = encode(dict(schema='auto-g16-study-xtb-project-capture/1',
                operation_id=preparation.intent['operation_id'], ordinal=self.ordinal, operation=operation,
                transport_evidence=plain(captured.evidence), process_evidence=plain(captured.process_evidence)))
            _require(0 < len(raw) <= 2 << 20)
            pending = memoryview(raw)
            while pending:
                size = os.write(fd, pending)
                _require(size > 0)
                pending = pending[size:]
            os.fsync(fd)
            signature = _signature(os.fstat(fd))
            _require(signature == _signature(os.stat(self.name, dir_fd=directory.fd, follow_symlinks=False))
                and signature[:3] == self.signature[:3] and signature[3:5] == (len(raw), 1))
            os.lseek(fd, 0, os.SEEK_SET)
            blocks, size = [], 0
            while size <= len(raw):
                block = os.read(fd, min(1048576, len(raw) + 1 - size))
                if not block:
                    break
                blocks.append(block)
                size += len(block)
            _require(b''.join(blocks) == raw)
            _require(signature == _signature(os.fstat(fd))
                == _signature(os.stat(self.name, dir_fd=directory.fd, follow_symlinks=False)))
            directory.seen[self.name] = (signature, raw)
            directory._check_physical()
        except BaseException as error:
            original = error
            raise
        finally:
            session.close_resource(self.resource, original=original)


class _Preparation:
    def __init__(self, session, inputs, directory, intent, decision_raw):
        self.session, self.inputs, self.directory = session, inputs, directory
        self.intent, self.decision_raw = intent, decision_raw
        self.ordinal, self.entered, self.closed = 0, False, False

    def assert_current(self):
        from auto_g16.study._xtb_service import _stored_decision
        _require(native._current() is self.session and self.session._preparation is self
                 and not self.closed)
        self.session.require_action('prepare')
        _require(_stored_decision(self.session, self.inputs.preview, current=True) == self.decision_raw)

    def before(self, attestor, target, path, operation):
        from auto_g16.study._model import encode
        self.assert_current()
        _require(not self.entered and self.ordinal < 4
                 and attestor._study_preparation is self
                 and attestor._profile is self.inputs.current_profile
                 and target is self.inputs.target
                 and path == self.inputs.preview['paths']['remote_project_dir']
                 and operation == self.inputs.preview['preparation_sequence'][self.ordinal])
        expected = {'intent.json', *(f'step-{i:02d}-{kind}.json'
                    for i in range(1, self.ordinal + 1) for kind in ('entered', 'capture'))}
        _require(self.directory.names() == expected)
        ordinal = self.ordinal + 1
        value = dict(schema='auto-g16-study-xtb-effect-step/1', operation_id=self.intent['operation_id'],
            ordinal=ordinal, operation=operation, decision_sha256=self.intent['authorization_sha256'])
        # This native owner publishes the exact step before any request construction.
        self.directory.publish(f'step-{ordinal:02d}-entered.json', encode(value))
        self.entered = True
        self.sink = _CaptureSink(self)
        self.assert_current()

    def capture(self, captured):
        """Retain original native diagnostics even after the effect window expires."""
        self.sink.save(captured)

    def after(self):
        self.assert_current()
        _require(self.entered)
        self.ordinal += 1
        self.entered = False


def current(session):
    _require(native._current() is session)
    value = getattr(session, '_preparation', None)
    _require(type(value) is _Preparation)
    value.assert_current()
    return value


@contextmanager
def prepare_once(session, inputs):
    from auto_g16.study import _xtb_files, _xtb_preview
    from auto_g16.study._xtb_service import _stored_decision
    from auto_g16.study._model import encode
    session.require_action('prepare')
    _require(type(inputs) is _xtb_preview._Inputs and getattr(session, '_preparation', None) is None)
    decision_raw = _stored_decision(session, inputs.preview, current=True)
    _require(decision_raw is not None)
    session.scope.stores['project'].assert_no_creation_history(inputs.project.project_id)
    directory = _xtb_files.directory(session, 'operation-preparation', create=True)
    _require(not directory.names())
    _xtb_files.directory(session, 'prepared-root', create=True)
    intent = operation_intent(session, inputs, decision_raw)
    directory.publish('intent.json', encode(intent))
    value = _Preparation(session, inputs, directory, intent, decision_raw)
    session._preparation = value
    try:
        yield value
        value.assert_current()
        _require(value.ordinal == 4 and not value.entered)
    finally:
        value.closed = True
        session._preparation = None


def preparation_references(session, snapshot):
    """Original native lineage and exact native digests, not a Study replacement."""
    session.assert_current()
    snapshot.assert_identity_closed()
    source = session.scope.stores['project'].inspect_creation_receipts(snapshot.workspace_binding.project_id)
    _require(source['original_binding'] == snapshot.project_physical_binding.semantic_payload())
    intent = source['intent']
    return [dict(role='project-intent', id=intent['intent_id'], sha256=intent['payload_sha256']),
        dict(role='project-result', id=intent['intent_id'], sha256=source['creation_result']['payload_sha256']),
        dict(role='project-binding', id=snapshot.project_physical_binding_id,
             sha256=semantic_sha256(source['original_binding'])),
        dict(role='snapshot', id=snapshot.program_execution_snapshot_id,
             sha256=semantic_sha256(snapshot._approval_semantics()))]


def verify_capture(session, inputs, snapshot, ordinal, value):
    """Pure replay against original native creation lineage; no attestor or wire."""
    from types import SimpleNamespace
    from auto_g16.transport import _bridge, _driver, _program_rtwin as rtwin
    from auto_g16.transport._canonical import canonical_json_bytes
    session.assert_current()
    _require(type(ordinal) is int and 1 <= ordinal <= 4)
    op = inputs.preview['preparation_sequence'][ordinal - 1]
    target = snapshot.resolved_server_profile
    original = snapshot.project_physical_binding
    lineage = session.scope.stores['project'].inspect_creation_receipts(original.project_id)
    binding = rtwin._wire_binding(target, target.resolved_server_profile_id, original.remote_project_dir)
    if ordinal == 3:
        binding['parent_physical_identity'] = original.parent_physical_identity
    request = dict(protocol=_bridge._PROGRAM_BOOTSTRAP_PROTOCOL, operation=op, binding=binding,
        payload={'provision_intent_id': lineage['intent']['intent_id']} if ordinal == 3 else {})
    evidence, process = value['transport_evidence'], value['process_evidence']
    _require(type(evidence) is dict)
    output = _driver._canonical_b64(evidence.get('stdout_base64'))
    errors = _driver._canonical_b64(evidence.get('stderr_base64'))
    operation = rtwin._project_operation(op)
    _require(not errors and len(output) <= operation.stdout_cap)
    expected = rtwin._ProjectWireCapture()
    expected.record(SimpleNamespace(operation=operation, request=request), output, errors,
                    0, 'completed', True, True)
    _require(canonical_json_bytes(evidence) == canonical_json_bytes(rtwin._plain(expected.evidence)))
    frame = _bridge._decode_frame(output, cap=operation.stdout_cap, field='Study Project capture')
    result = dict(state='ABSENT' if ordinal < 3 else 'EXISTING',
        parent_physical_identity=original.parent_physical_identity,
        project_physical_identity=None if ordinal < 3 else original.project_physical_identity)
    _require(canonical_json_bytes(frame) == canonical_json_bytes(dict(
        protocol=request['protocol'], operation=op, status='ok', result=result)))
    if process is not None:
        _require(type(process) is dict and set(process) == {'schema', 'capture_sha256', 'process'})
        rebuilt = rtwin._process_companion(evidence, process['process'], operation.stdin_cap)
        _require(rebuilt is not None and canonical_json_bytes(process) == canonical_json_bytes(rtwin._plain(rebuilt)))
