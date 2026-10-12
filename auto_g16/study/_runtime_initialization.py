"""Local four-owner initialization; no installed session or scientific effects."""
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import stat
import sqlite3
from uuid import UUID, uuid5

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.core.store import RuntimeStoreError
from auto_g16.approval import SQLiteApprovalStore
from auto_g16.approval.store import ApprovalStoreError
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.execution.project_provisioning import _ProductionProvisioningJournal
from . import _fresh_model as model, _fresh_service as fresh
from ._files import Directory, identity
from ._model import StudyError, closed, decode, digest, encode, require

SCHEMA = 'auto-g16-study-local-initialization/1'
ROLES = ('core', 'approval', 'transport', 'project')
DATABASES = ('core.sqlite3', 'approval.sqlite3', 'transport.sqlite3', 'project-journal.sqlite3')
OWNERS = (SQLiteRuntimeStore, SQLiteApprovalStore, _ProgramTransportStore, _ProductionProvisioningJournal)
VERSIONS = (1, 1, 2, 3)
DIRECTORIES = ('operations', 'prepared', 'artifacts', 'reviews', 'public')
FILES = ('0001-intent.json', '0002-core-intent.json', '0003-core-receipt.json',
         '0004-approval-intent.json', '0005-approval-receipt.json',
         '0006-transport-intent.json', '0007-transport-receipt.json',
         '0008-project-intent.json', '0009-project-receipt.json', '0010-complete.json')
KINDS = ('INITIALIZATION_INTENT', *('STORE_INTENT', 'STORE_RECEIPT') * 4, 'LOCAL_COMPLETE')
CAP = 2 * 1024 * 1024


class _DatabasePin:
    """Keep each inspected store unchanged until the whole Study call exits."""
    def __init__(self, runtime, name):
        self.runtime, self.name, self.pid = runtime, name, os.getpid()
        self.fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                          dir_fd=runtime.fd)
        try:
            self.version = self.signature(os.fstat(self.fd))
            self.physical = self.version[:2]
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    @staticmethod
    def signature(info):
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'initialization-unresolved')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def check(self):
        require(self.pid == os.getpid(), 'initialization-unresolved')
        self.runtime.check()
        named = os.stat(self.name, dir_fd=self.runtime.fd, follow_symlinks=False)
        require(self.signature(named) == self.version == self.signature(os.fstat(self.fd)),
                'initialization-unresolved')
        for suffix in ('-journal', '-wal', '-shm'):
            try:
                os.stat(self.name + suffix, dir_fd=self.runtime.fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise StudyError('initialization-unresolved')

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.check()
        finally:
            os.close(self.fd)


def _binding(directory):
    directory.check()
    return dict(path=str(directory.path), parent_chain=directory.chain, file_identity=directory.chain[-1])


def _decode(raw):
    try:
        value = decode(raw, 'initialization-unresolved', CAP)
        def depth(item, n=0):
            require(n <= 24, 'initialization-unresolved')
            for child in item.values() if type(item) is dict else item if type(item) is list else ():
                depth(child, n + 1)
        depth(value)
        require(encode(value) == raw, 'initialization-unresolved')
        return value
    except RecursionError as error:
        raise StudyError('initialization-unresolved') from error


def _event_id(value, n):
    return str(uuid5(UUID(value['creation_key']), SCHEMA + ':event:' + str(n)))


def _read_events(journal, value):
    names = journal.names()
    require(names <= set(FILES), 'initialization-unresolved')
    events = []
    for index, name in enumerate(FILES):
        if name not in names:
            require(names == set(FILES[:index]), 'initialization-unresolved')
            break
        event = closed(_decode(journal.read(name, CAP)[0]),
                       {'schema', 'sequence', 'previous_sha256', 'event_id', 'kind', 'data'})
        require(event['schema'] == 'auto-g16-study-local-initialization-event/1'
                and type(event['sequence']) is int and event['sequence'] == index + 1
                and event['previous_sha256'] == (digest(encode(events[-1])) if events else None)
                and event['kind'] == KINDS[index] and event['event_id'] == _event_id(value, index + 1),
                'initialization-unresolved')
        events.append(event)
    journal.seal(set(FILES[:len(events)]))
    return events


def _append(journal, events, value, data):
    n = len(events)
    event = dict(schema='auto-g16-study-local-initialization-event/1', sequence=n + 1,
        previous_sha256=digest(encode(events[-1])) if events else None,
        event_id=_event_id(value, n + 1), kind=KINDS[n], data=data)
    journal.publish(FILES[n], encode(event))
    events.append(event)
    journal.seal(set(FILES[:len(events)]))


def _inspect(runtime, role_index, value, stack, pins):
    name = DATABASES[role_index]
    pin = stack.enter_context(_DatabasePin(runtime, name))
    pins.append(pin)
    kwargs = dict(approved_root=str(runtime.path), expected_file_identity=pin.physical)
    if role_index == 0:
        kwargs['expected_records'] = model.records(value)
    state = OWNERS[role_index].inspect_initialization(str(runtime.path / name), **kwargs)
    pin.check()
    return dict(path=str(runtime.path / name), parent_chain=runtime.chain, file_identity=list(pin.physical)), state


def _create_store(runtime, index, value):
    runtime.check()
    require(DATABASES[index] not in runtime.names(), 'initialization-unresolved')
    path = runtime.path / DATABASES[index]
    if index == 0:
        runtime.publish(DATABASES[index], model.core_image(value))
        runtime.seal(set(runtime.expected_names) | {DATABASES[index]})
        return
    OWNERS[index].create_initialization_at(str(path), approved_root=str(runtime.path), parent_chain=runtime.chain)
    os.fsync(runtime.fd)
    runtime.check()
    runtime.seal(set(runtime.expected_names) | {DATABASES[index]})


def _store_intent(index, intent, value):
    return dict(role=ROLES[index], filename=DATABASES[index], initialization_intent_sha256=intent,
        expected_schema_version=VERSIONS[index], expected_state=(dict(records=model.record_receipts(value))
        if index == 0 else dict(empty=True)))


def _response(value, sha, events, next_step):
    return dict(schema=SCHEMA, study_id=model.identities(value)['project_id'], request_sha256=sha,
        state='local-initialized' if len(events) == 10 else 'initializing',
        initialization_receipt_id=events[-1]['event_id'] if len(events) == 10 else None,
        journal=[dict(sequence=e['sequence'], kind=e['kind'], event_id=e['event_id'],
                      sha256=digest(encode(e))) for e in events], next_local_step=next_step,
        execution_performed=False, installation_state='uninstalled')


def _inside(source, parent, runtime, journal, creation, value, *, write, newly_reserved, stack):
    pins = []
    def check_pins():
        for pin in pins:
            pin.check()
    events = _read_events(journal, value)
    sha = creation['request_sha256']
    require(events or newly_reserved, 'initialization-unresolved')
    base = dict(mode='local-uninstalled', study_id=creation['study_id'], request_sha256=sha,
        creation_binding=_binding(source), creation_event_sha256=[e['sha256'] for e in creation['data']['journal']],
        creation_core_sha256=creation['data']['creation_snapshot']['sha256'],
        runtime_binding=_binding(runtime), lock_binding=_binding(journal),
        core_image_generator=model.generator(), expected_records=model.record_receipts(value), store_order=list(ROLES))
    if events:
        saved = closed(events[0]['data'], set(base))
        # A committed image can outlive its generator. Unacknowledged bytes cannot.
        generator = closed(saved['core_image_generator'], {'schema', 'python', 'sqlite', 'source_sha256'})
        require(generator['schema'] == 'auto-g16-direct-study-core-image/2', 'initialization-unresolved')
        require(type(generator['python']) is str and type(generator['sqlite']) is str
                and type(generator['source_sha256']) is dict
                and set(generator['source_sha256']) == {'core/models.py', 'core/store.py', 'study/_fresh_model.py'},
                'initialization-unresolved')
        import re
        require(all(re.fullmatch(r'\d+\.\d+(?:\.\d+)?', generator[k])
                    for k in ('python', 'sqlite')), 'initialization-unresolved')
        require(all(type(h) is str and re.fullmatch('[0-9a-f]{64}', h)
                    for h in generator['source_sha256'].values()), 'initialization-unresolved')
        base['core_image_generator'] = generator
        require(encode(saved) == encode(base), 'initialization-unresolved')
    else:
        _append(journal, events, value, base)
    intent = digest(encode(events[0]))
    names = runtime.names()
    require(names <= {'initialization', *DIRECTORIES, *DATABASES, 'binding.json'}, 'initialization-unresolved')
    runtime.seal(names)
    # Existing directories must be a prefix and every one must remain empty.
    present = [name for name in DIRECTORIES if name in names]
    require(present == list(DIRECTORIES[:len(present)]), 'initialization-unresolved')
    require(len(events) == 1 or len(present) == len(DIRECTORIES), 'initialization-unresolved')
    for name in present:
        child = stack.enter_context(Directory(str(runtime.path / name), lock=False))
        child.seal(set())
    if len(present) != len(DIRECTORIES):
        require(names == {'initialization', *present}, 'initialization-unresolved')
        if not write:
            return _response(value, sha, events, 'create-directories')
        for name in DIRECTORIES[len(present):]:
            os.mkdir(name, 0o700, dir_fd=runtime.fd)
            os.fsync(runtime.fd)
            runtime.check()
            runtime.seal(set(runtime.expected_names) | {name})
            child = stack.enter_context(Directory(str(runtime.path / name), lock=False))
            child.seal(set())
    # No database may precede its durable role intent, even if schema-valid.
    for i, name in enumerate(DATABASES):
        require(name not in names or len(events) >= 2 + 2 * i, 'initialization-unresolved')
    require('binding.json' not in names or len(events) >= 9, 'initialization-unresolved')
    for index, name in enumerate(DATABASES):
        check_pins()
        intent_index = 1 + index * 2
        expected_intent = _store_intent(index, intent, value)
        if len(events) == intent_index:
            if not write:
                return _response(value, sha, events, ROLES[index] + '-intent')
            _append(journal, events, value, expected_intent)
        require(encode(events[intent_index]['data']) == encode(expected_intent), 'initialization-unresolved')
        if name not in runtime.names():
            require(len(events) == intent_index + 1, 'initialization-unresolved')
            if not write:
                return _response(value, sha, events, ROLES[index] + '-store')
            if index == 0:
                require(base['core_image_generator'] == model.generator(), 'initialization-unresolved')
            _create_store(runtime, index, value)
        binding, state = _inspect(runtime, index, value, stack, pins)
        check_pins()
        expected_receipt = dict(role=ROLES[index], intent_sha256=digest(encode(events[intent_index])),
                                file_binding=binding, state=state)
        if len(events) == intent_index + 1:
            if index == 0:
                require(base['core_image_generator'] == model.generator(), 'initialization-unresolved')
                require(runtime.read(name)[0] == model.core_image(value), 'initialization-unresolved')
            if not write:
                return _response(value, sha, events, ROLES[index] + '-receipt')
            _append(journal, events, value, expected_receipt)
        require(encode(events[intent_index + 1]['data']) == encode(expected_receipt), 'initialization-unresolved')
    binding = dict(schema='auto-g16-study-local-runtime-binding/1', mode='local-uninstalled',
        study_id=creation['study_id'], request_sha256=sha, creation_binding=_binding(source),
        runtime_binding=_binding(runtime), lock_binding=_binding(journal),
        initialization_intent_sha256=intent, store_receipt_sha256=[digest(encode(events[i])) for i in (2, 4, 6, 8)])
    if 'binding.json' not in runtime.names():
        require(len(events) == 9, 'initialization-unresolved')
        if not write:
            return _response(value, sha, events, 'binding')
        runtime.publish('binding.json', encode(binding))
        runtime.seal(set(runtime.expected_names) | {'binding.json'})
    require(runtime.read('binding.json', CAP)[0] == encode(binding), 'initialization-unresolved')
    check_pins()
    complete = dict(study_id=creation['study_id'], request_sha256=sha,
                    binding_sha256=digest(encode(binding)), store_receipt_sha256=binding['store_receipt_sha256'])
    if len(events) == 9:
        if not write:
            return _response(value, sha, events, 'complete')
        _append(journal, events, value, complete)
    require(encode(events[9]['data']) == encode(complete), 'initialization-unresolved')
    journal.seal(set(FILES))
    runtime.seal({'initialization', *DIRECTORIES, *DATABASES, 'binding.json'})
    parent.check()
    check_pins()
    return _response(value, sha, events, None)


def _operate(creation_directory, runtime_root, *, write, expected_creation_chain=None, expected_runtime_chain=None):
    require(type(creation_directory) is str and type(runtime_root) is str, 'invalid-request')
    require(all(p.startswith('/') and p != '/' and not p.endswith('/')
                and all(v not in {'', '.', '..'} for v in p[1:].split('/'))
                for p in (creation_directory, runtime_root)), 'invalid-request')
    require(os.path.commonpath((creation_directory, runtime_root)) not in (creation_directory, runtime_root),
            'invalid-request')
    with Directory(creation_directory) as source:
        require(expected_creation_chain is None or source.chain == expected_creation_chain, 'identity-drift')
        creation = fresh.operate_locked('status', source, None, None)
        require(creation['status'] == 'local-created', 'invalid-evidence')
        value = fresh._intent(source, fresh._events(source)[0])
        info = os.stat('core.sqlite3', dir_fd=source.fd, follow_symlinks=False)
        SQLiteRuntimeStore.inspect_initialization(str(source.path / 'core.sqlite3'),
            approved_root=creation_directory, expected_file_identity=tuple(identity(info)),
            expected_records=model.records(value))
        try:
            with ExitStack() as stack:
                parent = stack.enter_context(Directory(runtime_root, write=write))
                require(expected_runtime_chain is None or parent.chain == expected_runtime_chain, 'identity-drift')
                source.check(); parent.check()
                study_id = creation['study_id']
                newly_reserved = study_id not in parent.names()
                if newly_reserved:
                    require(write, 'not-found')
                    os.mkdir(study_id, 0o700, dir_fd=parent.fd)
                    os.fsync(parent.fd)
                runtime = stack.enter_context(Directory(str(parent.path / study_id), write=write, lock=False))
                if newly_reserved:
                    os.mkdir('initialization', 0o700, dir_fd=runtime.fd)
                    os.fsync(runtime.fd)
                journal = stack.enter_context(Directory(str(runtime.path / 'initialization'), write=write))
                fcntl.flock(parent.fd, fcntl.LOCK_UN)
                return _inside(source, parent, runtime, journal, creation, value,
                               write=write, newly_reserved=newly_reserved, stack=stack)
        except StudyError as error:
            if str(error) in {'busy', 'not-found', 'initialization-unresolved'}:
                raise
            raise StudyError('initialization-unresolved') from error
        except (OSError, ValueError, TypeError, KeyError, sqlite3.Error,
                RuntimeStoreError, ApprovalStoreError) as error:
            raise StudyError('initialization-unresolved') from error


def initialize_local(creation_directory, runtime_root):
    return _operate(creation_directory, runtime_root, write=True)


def inspect_local(creation_directory, runtime_root):
    return _operate(creation_directory, runtime_root, write=False)


def _initialize_bound(creation_directory, runtime_root, *, creation_chain, runtime_chain):
    """Installed CLI handoff: compare owner-held chains before any runtime write."""
    require(type(creation_chain) is list and type(runtime_chain) is list, 'invalid-request')
    return _operate(creation_directory, runtime_root, write=True,
                    expected_creation_chain=creation_chain, expected_runtime_chain=runtime_chain)
