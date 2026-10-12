"""Native, process-bound xTB session; no global pilot rebinding or claim owner."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import sys
from threading import Lock, get_ident

from ._identity import ExecutionValueError

_ACTIONS = frozenset(('prepare', 'submit', 'collect', 'authorize-preparation', 'authorize',
    'authorize-collection', 'review', 'review-collection', 'status', 'query', 'audit', 'recover'))
_WRITERS = frozenset(('prepare', 'submit', 'collect', 'authorize-preparation', 'authorize',
                      'authorize-collection'))
_CURRENT = ContextVar('native-study-xtb-session', default=None)
_PROCESS_LOCK, _PROCESS_PID = Lock(), os.getpid()
_QUARANTINE = []


def _require(value):
    if not value:
        raise ExecutionValueError('Study stage session is absent, stale or outside its action')


def _current():
    value = _CURRENT.get()
    if value is not None:
        value.assert_current()
    return value


def _has_current_close_unknown(scope, session):
    return (type(session) is _Session and _CURRENT.get() is session
            and session.scope is scope and session.pid == os.getpid()
            and session.thread == get_ident() and bool(session._unknown)
            and all(any(item is row for row in session._resources)
                    and item['attempted'] and 'error_kind' in item for item in session._unknown))


class _Session:
    def __init__(self, scope, action, continuation_sha256):
        self.scope, self.action, self.continuation_sha256 = scope, action, continuation_sha256
        self.pid, self.thread = os.getpid(), get_ident()
        self.closed = self.consumed = False
        self.context = None
        self._unknown, self._resources = [], []
        self._closing = None
        self._business_directories = {}
        self.run = self.publisher = self.collection_run = self.collection = None

    def assert_current(self):
        self.assert_identity()
        context = self.scope._execution_context()
        _require(context is self.context)
        source = context.inspection.source
        for directory in self._business_directories.values():
            directory._check_physical()

        self._assert_origins(source)
        for role, store in self.scope.stores.items():
            observed = store.assert_existing_binding()
            expected = self._store_bindings[role]
            _require(observed == expected and self._stores[role] is store)

    def assert_identity(self):
        _require(_CURRENT.get() is self and not self.closed and not self._unknown
                 and (self.pid, self.thread) == (os.getpid(), get_ident()))
        self.scope._get('request')
        from auto_g16.transport import _program_rtwin as rtwin
        _require(rtwin._STUDY_SESSION.get() is self)

    def _assert_origins(self, source):
        for name, module in tuple(sys.modules.items()):
            if name == 'auto_g16' or name.startswith('auto_g16.') or name == 'scripts.run_v31_publisher_pilot':
                spec = getattr(module, '__spec__', None)
                suffix = '/__init__.py' if spec is not None and spec.submodule_search_locations is not None else '.py'
                expected = source + '/' + name.replace('.', '/') + suffix
                _require(spec is not None and spec.origin == expected
                         and getattr(module, '__file__', None) == expected)

    def require_action(self, *actions):
        self.assert_current()
        _require(self.action in actions)

    def require_writer(self):
        self.require_action(*_WRITERS)

    def _record_unknown(self, record, error):
        # This method is called only by the native mechanical close paths below.
        _require(record is self._closing and record['attempted']
                 and any(record is row for row in self._resources))
        record['error_kind'] = type(error).__name__
        self._unknown.append(record)
        _QUARANTINE.append(self)
        self.scope._retain_unresolved_session(self)

    def own(self, resource, kind):
        self.assert_current()
        _require(kind in ('driver', 'publisher-pin', 'business-file', 'business-directory'))
        from auto_g16.transport import _program_rtwin as rtwin
        if kind == 'driver':
            self.require_action('submit', 'collect')
            expected = rtwin._RTWinProgramEffectDriver
        elif kind == 'publisher-pin':
            expected = rtwin._PinnedPublisherFile
        else:
            from auto_g16.study import _xtb_files
            expected = _xtb_files._OwnedDescriptors
        _require(type(resource) is expected and resource._study_session is self)
        _require(not any(row['resource'] is resource for row in self._resources))
        self._resources.append(dict(resource=resource, kind=kind, attempted=False, descriptors=()))

    def close_resource(self, resource, *, original=None):
        _require(_CURRENT.get() is self)
        rows = [row for row in self._resources if row['resource'] is resource]
        _require(len(rows) == 1)
        record = rows[0]
        if record['attempted']:
            return
        if self.pid != os.getpid():
            _QUARANTINE.append(self)
            if original is None:
                raise ExecutionValueError('inherited Study resources retained unresolved')
            original.add_note('inherited Study resources retained unresolved')
            return
        _require(self.thread == get_ident() and not self.closed)
        if self._unknown:
            # The first uncertain close already quarantined the entire session.
            # Outer cleanup retains untouched resources and the original exception.
            return
        # Keep the complete inventory before legacy pin.close can pop an FD.
        if record['kind'] == 'driver':
            publisher = resource._publisher
            pins = tuple(publisher.pins) if publisher is not None else ()
            record['retained'] = (publisher, pins)
            record['descriptors'] = tuple(fd for pin in pins for fd in pin.fds)
        else:
            record['descriptors'] = tuple(resource.fds)
        record['attempted'] = True
        previous_closing, self._closing = self._closing, record
        try:
            if record['kind'] == 'driver':
                resource._close_study_owned()
            else:
                descriptors, resource.fds = tuple(resource.fds), []
                failure = None
                for descriptor in reversed(descriptors):
                    try:
                        os.close(descriptor)
                    except BaseException as error:
                        if failure is None:
                            failure = error
                        else:
                            failure.add_note('native descriptor close failed: ' + type(error).__name__)
                if failure is not None:
                    raise failure
        except BaseException as error:
            self._record_unknown(record, error)
            if original is None:
                raise
            original.add_note('native resource close unresolved: ' + type(error).__name__)
        finally:
            self._closing = previous_closing

    def select(self, name, fixed):
        self.assert_current()
        _require(fixed is None)
        allowed = {'run': ('submit',), 'publisher': ('submit', 'collect'),
                   'collection_run': ('collect',), 'collection': ('collect',)}
        _require(name in allowed and self.action in allowed[name])
        value = getattr(self, name)
        _require(value is not None)
        return value

def _selection(name, fixed):
    session = _current()
    return fixed if session is None else session.select(name, fixed)


@contextmanager
def _open_study_xtb_session(scope, action, *, continuation_sha256=None):
    from auto_g16.study import _registered_runtime as registered
    _require(type(scope) is registered._Scope and registered._ACTIVE_SCOPE.get() is scope)
    _require(type(action) is str and action in _ACTIONS)
    _require((type(continuation_sha256) is str and re.fullmatch('[0-9a-f]{64}', continuation_sha256))
             if action == 'collect' else continuation_sha256 is None)
    _require(os.getpid() == _PROCESS_PID and _CURRENT.get() is None)
    if not _PROCESS_LOCK.acquire(blocking=False):
        raise ExecutionValueError('Study stage session is busy')
    session = _Session(scope, action, continuation_sha256)
    token = _CURRENT.set(session)
    transport_token = None
    original = None
    try:
        session.context = scope._execution_context()
        from auto_g16.transport import _program_rtwin as rtwin
        from scripts import run_v31_publisher_pilot as controller
        _require(rtwin._STUDY_SESSION.get() is None)
        _require(all(value is None for value in (rtwin._FIXED_PUBLISHER_INSTALLATION,
            rtwin._FIXED_COLLECTION_INSTALLATION, controller._FIXED_PILOT_RUN,
            controller._FIXED_COLLECTION_RUN)))
        session._stores = dict(scope.stores)
        session._store_bindings = {role: store.assert_existing_binding()
                                   for role, store in scope.stores.items()}
        for receipt in scope.initialization_receipts:
            data = receipt['data']
            binding = data['file_binding']
            observed = session._store_bindings[data['role']]
            _require(observed['path'] == binding['path']
                     and tuple(observed['parent_chain']) == tuple(tuple(p) for p in binding['parent_chain'])
                     and observed['file_identity'] == tuple(binding['file_identity']))
            state = data['state']['owner_state']
            if data['role'] == 'transport':
                _require(observed['native_identity'] == dict(
                    program_transport_store_id=state['program_transport_store_id'],
                    store_instance_id=state['store_instance_id']))
            elif data['role'] == 'project':
                _require(observed['native_identity'] == dict(journal_identity=state['journal_id']))
            else:
                _require(observed['native_identity'] is None)
        session.context.assert_current()
        session._assert_origins(session.context.inspection.source)
        transport_token = rtwin._STUDY_SESSION.set(session)
        session.assert_current()
        yield session
        if not session._unknown:
            session.assert_current()
    except BaseException as error:
        original = error
        raise
    finally:
        failure = original
        if session.pid != os.getpid():
            _QUARANTINE.append(session)
            if failure is None:
                failure = ExecutionValueError('inherited Study resources retained unresolved')
        else:
            if original is not None and not session._unknown and session.context is not None:
                try:
                    session.assert_current()
                except BaseException as error:
                    original.add_note('native session exit validation failed: ' + type(error).__name__)
            if not session._unknown:
                for record in reversed(session._resources):
                    try:
                        session.close_resource(record['resource'], original=failure)
                    except BaseException as error:
                        if failure is None:
                            failure = error
                        else:
                            failure.add_note('native resource cleanup failed: ' + type(error).__name__)
                    if session._unknown:
                        break
            session.closed = True
            if transport_token is not None:
                rtwin._STUDY_SESSION.reset(transport_token)
            _CURRENT.reset(token)
            if not session._unknown:
                _PROCESS_LOCK.release()
        if original is None and failure is not None:
            raise failure
