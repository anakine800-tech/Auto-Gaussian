"""Installed local Study registry and guarded existing owners; no execution authority."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from dataclasses import dataclass, fields
import fcntl
import os
from pathlib import Path
import re
import sys
import stat
import threading
from types import MappingProxyType
from uuid import UUID

from auto_g16.core import store as core
from auto_g16.approval import store as approval
from auto_g16.execution import project_provisioning as project, _project_existing
from auto_g16.transport import program as transport, _program_existing
from . import _installation as installed, _fresh_model as model, _fresh_service as fresh
from . import _runtime_initialization as initialization
from ._files import Directory
from ._model import StudyError, closed, digest, encode, plain, require

_SCHEMA = 'auto-g16-study-runtime-registration/1'
_RETAINED = []
_FILE_UNRESOLVED = {}
_CAP = 2 << 20
_ACTIVE_SCOPE = ContextVar('registered-study-scope', default=None)


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


class _Directory(Directory):
    """This slice owns PID-bound directory pins; never release inherited locks."""
    def __init__(self, path, *, write=False, lock=True):
        self.pid, self.thread = os.getpid(), threading.get_ident()
        self.path = Path(path)
        require(type(path) is str and path.startswith('/') and path != '/'
                and all(part not in {'', '.', '..'} for part in path[1:].split('/')))
        self.parts = path[1:].split('/')
        self.fds, self.seen = [], {}
        self.expected_names, self.write = None, write
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            self.fds.append(os.open('/', flags))
            for part in self.parts:
                self.fds.append(os.open(part, flags, dir_fd=self.fds[-1]))
            self.chain = [[info.st_dev, info.st_ino]
                          for info in (os.fstat(fd) for fd in self.fds)]
            if lock:
                try:
                    fcntl.flock(self.fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise StudyError('busy') from error
            self.check()
        except BaseException as original:
            try:
                self.close()
            except BaseException as cleanup:
                original.add_note('runtime constructor cleanup unresolved: ' + type(cleanup).__name__)
            raise

    def check(self):
        require((self.pid, self.thread) == (os.getpid(), threading.get_ident()), 'runtime-unresolved')
        require((self.pid,tuple(self.chain[-1])) not in _FILE_UNRESOLVED, 'registry-unresolved')
        super().check()

    @contextmanager
    def _file(self, name, flags):
        require(type(name) is str and name not in {'','.','..'} and '/' not in name)
        self.check()
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd)
        failure = None
        try:
            yield fd
        except BaseException as error:
            failure = error
            raise
        finally:
            if self.pid != os.getpid():
                _FILE_UNRESOLVED[(os.getpid(),tuple(self.chain[-1]))] = (self,fd)
                if failure is None:raise StudyError('registry-unresolved')
                failure.add_note('inherited registry file retained unresolved')
            else:
                try:
                    os.close(fd)  # One attempt; the numeric descriptor is never reused here.
                except BaseException as error:
                    _FILE_UNRESOLVED[(self.pid,tuple(self.chain[-1]))] = (self,fd)
                    if failure is None:raise
                    failure.add_note('registry file close unresolved: '+type(error).__name__)

    def read(self, name, cap=64 << 20):
        with self._file(name, os.O_RDONLY | os.O_NONBLOCK) as fd:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= cap)
            chunks, size = [], 0
            while size <= cap:
                block = os.read(fd,min(1048576,cap+1-size))
                if not block:break
                chunks.append(block);size+=len(block)
            raw = b''.join(chunks)
            signature = lambda item:(item.st_dev,item.st_ino,item.st_size,item.st_nlink,
                                     item.st_mtime_ns,item.st_ctime_ns)
            named = os.stat(name,dir_fd=self.fd,follow_symlinks=False)
            require(size == before.st_size and signature(before) == signature(os.fstat(fd)) == signature(named))
            observed = (signature(before),raw)
            require(name not in self.seen or self.seen[name] == observed)
            self.seen[name] = observed
            self.check()
            return raw,[before.st_dev,before.st_ino]

    def publish(self, name, raw):
        require(self.write and type(raw) is bytes and 0 < len(raw) <= _CAP and name not in self.names())
        with self._file(name,os.O_WRONLY | os.O_CREAT | os.O_EXCL) as fd:
            info=os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
            view=memoryview(raw)
            while view:
                count=os.write(fd,view)
                require(count>0)
                view=view[count:]
            os.fsync(fd)
        os.fsync(self.fd)
        require(self.read(name,_CAP)[0] == raw)

    def close(self):
        if self.pid != os.getpid():
            _RETAINED.append(self)
            raise StudyError('runtime-unresolved')
        fds, self.fds = self.fds, []
        failure = None
        for fd in reversed(fds):
            try:
                os.close(fd)
            except BaseException as error:
                if failure is None:
                    failure = error
                else:
                    failure.add_note('runtime descriptor close failed: ' + type(error).__name__)
        if failure is not None:
            # Even a directory close can leave the registry flock unresolved.
            if hasattr(self, 'chain'):
                _FILE_UNRESOLVED[(self.pid,tuple(self.chain[-1]))] = (self,tuple(fds))
            else:
                _RETAINED.append((self,tuple(fds)))
            raise failure

    def __exit__(self, kind, original, traceback):
        try:
            super().__exit__(kind, original, traceback)
        except BaseException as error:
            if original is None:
                raise
            original.add_note('runtime directory exit failed: ' + type(error).__name__)


def _installation_ref(facts):
    return {key: plain(getattr(facts, key)) for key in ('source_commit', 'source_tree',
        'source_manifest_sha256', 'locator_sha256', 'readback_binding')}


def _origin_paths(inspection):
    for module in (sys.modules[__name__], installed, model, fresh, initialization,
                   sys.modules[Directory.__module__], sys.modules[encode.__module__], core, approval, project,
                   _project_existing, transport, _program_existing):
        expected = inspection.source + '/' + module.__name__.replace('.', '/') + '.py'
        require(module.__file__ == expected and module.__spec__ is not None
                and module.__spec__.origin == expected, 'runtime-source-mismatch')


def _origins(inspection):
    _origin_paths(inspection)
    inspection.check()


def _registry(registry):
    names = registry.names()
    require(len(names) <= 64 and names == {f'{i:04d}-runtime.json' for i in range(1, len(names)+1)},
            'registry-unresolved')
    entries, seen = [], set()
    for i in range(1, len(names)+1):
        name = f'{i:04d}-runtime.json'
        raw, physical = registry.read(name, _CAP)
        value = closed(initialization._decode(raw), {'schema', 'sequence', 'previous_sha256',
            'study_id', 'request_sha256', 'creation_binding', 'runtime_binding',
            'initialization_receipt', 'installation'})
        require(value['schema'] == _SCHEMA and type(value['sequence']) is int and value['sequence'] == i
                and value['previous_sha256'] == (entries[-1]['file_binding']['sha256'] if entries else None)
                and type(value['study_id']) is str and str(UUID(value['study_id'])) == value['study_id']
                and value['study_id'] not in seen, 'registry-unresolved')
        installed._hash(value['request_sha256'])
        for key in ('creation_binding', 'runtime_binding'):
            installed._validate_binding(value[key])
        receipt = closed(value['initialization_receipt'], {'event_id', 'sha256'})
        require(type(receipt['event_id']) is str and str(UUID(receipt['event_id'])) == receipt['event_id'])
        installed._hash(receipt['sha256'])
        ref = closed(value['installation'], {'source_commit', 'source_tree', 'source_manifest_sha256',
            'locator_sha256', 'readback_binding'})
        for key in ('source_commit', 'source_tree'):
            installed._hash(ref[key], 40)
        for key in ('source_manifest_sha256', 'locator_sha256'):
            installed._hash(ref[key])
        installed._validate_binding(ref['readback_binding'], file=True)
        seen.add(value['study_id'])
        entries.append(dict(registration=value, file_binding=dict(path=str(registry.path/name),
            parent_chain=registry.chain, file_identity=physical, sha256=digest(raw), size_bytes=len(raw))))
    return entries


def _historical(source, runtime, journal, creation, value):
    """Reclose immutable receipts without applying initial row counts to live stores."""
    events = initialization._read_events(journal, value)
    require(len(events) == 10, 'runtime-unresolved')
    first = closed(events[0]['data'], {'mode','study_id','request_sha256','creation_binding',
        'creation_event_sha256','creation_core_sha256','runtime_binding','lock_binding',
        'core_image_generator','expected_records','store_order'})
    generator = closed(first['core_image_generator'], {'schema','python','sqlite','source_sha256'})
    require(generator['schema'] == 'auto-g16-direct-study-core-image/2')
    for key in ('python','sqlite'):
        require(type(generator[key]) is str and re.fullmatch(r'\d+\.\d+(?:\.\d+)?',generator[key]))
    hashes = closed(generator['source_sha256'], {'core/models.py','core/store.py','study/_fresh_model.py'})
    for sha in hashes.values():
        installed._hash(sha)
    expected = dict(mode='local-uninstalled', study_id=creation['study_id'],
        request_sha256=creation['request_sha256'], creation_binding=initialization._binding(source),
        creation_event_sha256=[e['sha256'] for e in creation['data']['journal']],
        creation_core_sha256=creation['data']['creation_snapshot']['sha256'],
        runtime_binding=initialization._binding(runtime), lock_binding=initialization._binding(journal),
        core_image_generator=generator, expected_records=model.record_receipts(value),
        store_order=list(initialization.ROLES))
    require(encode(first) == encode(expected), 'runtime-unresolved')
    initial_hash = digest(encode(events[0]))
    for index, role in enumerate(initialization.ROLES):
        intent, receipt = events[1+2*index], events[2+2*index]
        require(intent['data'] == initialization._store_intent(index, initial_hash, value), 'runtime-unresolved')
        data = closed(receipt['data'], {'role','intent_sha256','file_binding','state'})
        require(data['role'] == role and data['intent_sha256'] == digest(encode(intent)))
        binding = closed(data['file_binding'], {'path','parent_chain','file_identity'})
        require(binding['path'] == str(runtime.path/initialization.DATABASES[index])
                and binding['parent_chain'] == runtime.chain)
        installed._physical(binding['file_identity'])
        state = closed(data['state'], {'schema','role','file_identity','schema_version','schema_sha256','owner_state'})
        require(state['schema'] == 'auto-g16-native-initial-store-state/1' and state['role'] == role
                and state['file_identity'] == binding['file_identity']
                and type(state['schema_version']) is int and state['schema_version'] == initialization.VERSIONS[index])
        installed._hash(state['schema_sha256'])
        owner_state = closed(state['owner_state'], (
            {'table_counts','records'} if index == 0 else {'evidence_count'} if index == 1
            else {'program_transport_store_id','store_instance_id','table_counts'} if index == 2
            else {'journal_id','table_counts'}))
        if index == 0:
            require(owner_state['records'] == model.record_receipts(value))
        elif index == 1:
            require(type(owner_state['evidence_count']) is int and owner_state['evidence_count'] == 0)
        else:
            for key in ('program_transport_store_id','store_instance_id') if index == 2 else ('journal_id',):
                require(type(owner_state[key]) is str and str(UUID(owner_state[key])) == owner_state[key])
        if index != 1:
            counts = owner_state['table_counts']
            require(type(counts) is dict and all(type(k) is str and type(n) is int and n >= 0
                                               for k,n in counts.items()))
    binding = dict(schema='auto-g16-study-local-runtime-binding/1', mode='local-uninstalled',
        study_id=creation['study_id'], request_sha256=creation['request_sha256'],
        creation_binding=initialization._binding(source), runtime_binding=initialization._binding(runtime),
        lock_binding=initialization._binding(journal), initialization_intent_sha256=initial_hash,
        store_receipt_sha256=[digest(encode(events[i])) for i in (2,4,6,8)])
    require(runtime.read('binding.json', _CAP)[0] == encode(binding), 'runtime-unresolved')
    require(events[9]['data'] == dict(study_id=creation['study_id'], request_sha256=creation['request_sha256'],
        binding_sha256=digest(encode(binding)), store_receipt_sha256=binding['store_receipt_sha256']))
    return events


@dataclass(frozen=True, slots=True)
class _ExecutionContext:
    _scope: object
    facts: object
    inspection: object
    directories: object

    def assert_current(self):
        self._scope._get('request')
        _origin_paths(self.inspection)
        self.inspection.assert_held_current()
        for directory in self.directories.values():
            directory.check()


class _Scope:
    def __init__(self, request, registration, receipts, stores, facts, inspection, directories):
        self._pid, self._thread, self._closed = os.getpid(), threading.get_ident(), False
        self._session_unresolved, self._retained_session = False, None
        self._values = dict(request=_freeze(request), registration_ref=_freeze(registration),
            initialization_receipts=_freeze(receipts), stores=MappingProxyType(stores))
        self._context = _ExecutionContext(self, facts, inspection, MappingProxyType(directories))

    def _get(self, name):
        require(_ACTIVE_SCOPE.get() is self and not self._closed and not self._session_unresolved
                and (self._pid,self._thread) == (os.getpid(),threading.get_ident()),
                'runtime-scope-closed')
        return self._values[name]

    def _execution_context(self):
        self._get('request')
        self._context.assert_current()
        return self._context

    def _retain_unresolved_session(self, session):
        # Only the native close site can issue this monotonic lifetime fact.
        from auto_g16.execution import _study_stage_session as native
        require(_ACTIVE_SCOPE.get() is self and not self._closed
                and (self._pid,self._thread) == (os.getpid(),threading.get_ident())
                and native._has_current_close_unknown(self, session), 'runtime-unresolved')
        require(self._retained_session is None or self._retained_session is session,
                'runtime-unresolved')
        self._retained_session, self._session_unresolved = session, True

    request = property(lambda self:self._get('request'))
    registration_ref = property(lambda self:self._get('registration_ref'))
    initialization_receipts = property(lambda self:self._get('initialization_receipts'))
    stores = property(lambda self:self._get('stores'))


def _unresolved(events):
    for index, module, name in ((0,core,'_UNRESOLVED_EXISTING'),(1,approval,'_UNRESOLVED_EXISTING'),
                               (2,_program_existing,'_QUARANTINE'),(3,_project_existing,'_QUARANTINE')):
        physical = tuple(events[2+2*index]['data']['file_binding']['file_identity'])
        key = (os.getpid(),*physical) if index < 2 else (os.getpid(),physical)
        if key in getattr(module,name):
            return True
    return False


@contextmanager
def _operate(creation_directory, study_id, *, register):
    # The original loader pins remain held through all owner and directory exits.
    loader = installed.load_installed_runtime()
    facts = loader.__enter__()
    try:
        inspection = installed._inspect(facts.bundle_binding['path'], True)
    except BaseException as error:
        try:
            loader.__exit__(type(error), error, error.__traceback__)
        except BaseException as cleanup:
            error.add_note('installation exit failed: ' + type(cleanup).__name__)
        raise
    directories, owners = ExitStack(), ExitStack()
    scope = registry = events = active_token = None
    registry_locked = False
    original = None
    pid = os.getpid()
    try:
        require(inspection.facts == facts, 'runtime-source-mismatch')
        _origins(inspection)
        roots = plain(facts.roots)
        registry = directories.enter_context(_Directory(roots['registry']['path'], write=register))
        registry_locked = True
        require(initialization._binding(registry) == roots['registry'])
        entries = _registry(registry)
        if not register:
            require(type(study_id) is str and str(UUID(study_id)) == study_id, 'invalid-request')
            matches = [e for e in entries if e['registration']['study_id'] == study_id]
            require(len(matches) == 1, 'not-found')
            selected = matches[0]
            creation_directory = selected['registration']['creation_binding']['path']
            registry.seen = {Path(selected['file_binding']['path']).name:
                             registry.seen[Path(selected['file_binding']['path']).name]}
            fcntl.flock(registry.fd, fcntl.LOCK_UN)
            registry_locked = False
        installed._path(creation_directory, absolute=True)
        require(creation_directory != roots['creation']['path'] and
                os.path.commonpath((creation_directory, roots['creation']['path'])) == roots['creation']['path'])
        source = directories.enter_context(_Directory(creation_directory))
        require(source.chain[:len(roots['creation']['parent_chain'])] == roots['creation']['parent_chain'])
        creation = fresh.operate_locked('status', source, None, None)
        require(creation['status'] == 'local-created')
        value = fresh._intent(source, fresh._events(source)[0])
        require(register or study_id == creation['study_id'])
        study_id = creation['study_id']
        runtime = directories.enter_context(_Directory(roots['runtime']['path']+'/'+study_id, lock=False))
        require(runtime.chain[:-1] == roots['runtime']['parent_chain'])
        runtime.seal({'initialization',*initialization.DIRECTORIES,*initialization.DATABASES,'binding.json'})
        journal = directories.enter_context(_Directory(str(runtime.path/'initialization'),write=True))
        business = {name: directories.enter_context(_Directory(str(runtime.path/name),lock=False))
                    for name in initialization.DIRECTORIES}
        events = _historical(source, runtime, journal, creation, value)
        stores = {}
        for index in (3,0,1,2):
            receipt = events[2+2*index]['data']; binding = receipt['file_binding']
            kwargs = dict(approved_root=str(runtime.path),expected_file_identity=tuple(binding['file_identity']))
            if index in (2,3):
                kwargs['expected_parent_chain'] = tuple(map(tuple,binding['parent_chain']))
                key = 'expected_store_instance_id' if index == 2 else 'expected_journal_identity'
                kwargs[key] = receipt['state']['owner_state']['store_instance_id' if index == 2 else 'journal_id']
            stores[initialization.ROLES[index]] = owners.enter_context(
                initialization.OWNERS[index].open_existing_mutable(binding['path'],**kwargs))
        for index, role in enumerate(initialization.ROLES):
            store = stores[role]
            schema_facts = store.registration_schema_facts()
            state = events[2+2*index]['data']['state']
            require(state['schema_sha256'] == schema_facts['schema_sha256'], 'runtime-unresolved')
            owner_state = state['owner_state']
            if index == 0:
                counts = {name:0 for name in schema_facts['table_names']}
                counts.update({name:1 for name in ('projects','workflow_runs','tasks','calculation_plans',
                                                   'resource_specs','attempts')})
                require(owner_state['table_counts'] == counts)
            elif index == 2:
                require(owner_state['program_transport_store_id'] == store.program_transport_store_id
                        and owner_state['table_counts'] == dict(program_transport_meta=1,
                            program_runtime_attestation=0,program_effect_physical_authority=0))
            elif index == 3:
                require(owner_state['table_counts'] == dict(provisioning_meta=1,project_physical_bindings=0,
                    provisioning_intents=0,provisioning_results=0))
        expected_records = model.records(value)
        for record, method in zip(expected_records, ('load_project','load_workflow_run','load_task',
                                   'load_calculation_plan','load_resource_spec','load_attempt')):
            require(encode(getattr(stores['core'],method)(getattr(record,fields(record)[0].name))) == encode(record))
        stores['core'].attempt_state(expected_records[-1].attempt_id)
        data = dict(schema=_SCHEMA,study_id=study_id,request_sha256=creation['request_sha256'],
            creation_binding=initialization._binding(source), runtime_binding=initialization._binding(runtime),
            initialization_receipt=dict(event_id=events[9]['event_id'],sha256=digest(encode(events[9]))),
            installation=_installation_ref(facts))
        matches = [e for e in entries if e['registration']['study_id'] == study_id]
        if matches:
            selected = matches[0]
            existing = selected['registration']
            require(existing == dict(data,sequence=existing['sequence'],previous_sha256=existing['previous_sha256']),
                    'registry-unresolved')
        else:
            require(register and len(entries)<64,'registry-unresolved')
            data.update(sequence=len(entries)+1,previous_sha256=entries[-1]['file_binding']['sha256'] if entries else None)
            registry.publish(f'{len(entries)+1:04d}-runtime.json',encode(data))
            selected = _registry(registry)[-1]
        if register:
            registry.seen = {Path(selected['file_binding']['path']).name:
                             registry.seen[Path(selected['file_binding']['path']).name]}
            fcntl.flock(registry.fd,fcntl.LOCK_UN)
            registry_locked = False
        scope = _Scope(value, selected, [events[i] for i in (2,4,6,8)], stores,
                       facts, inspection, dict(source=source, runtime=runtime, **business))
        active_token = _ACTIVE_SCOPE.set(scope)
        yield scope
        if not scope._session_unresolved:
            _origins(inspection)
    except BaseException as error:
        original = error
        raise
    finally:
        if scope is not None:
            scope._closed = True
        failure = original
        if registry is not None and registry_locked and pid == os.getpid():
            try:
                fcntl.flock(registry.fd,fcntl.LOCK_UN)
            except BaseException as error:
                if failure is None:failure=error
                else:failure.add_note('registry unlock unresolved: '+type(error).__name__)
        session_unknown = scope is not None and scope._session_unresolved
        if pid == os.getpid() and not session_unknown:
            try:
                owners.__exit__(type(original) if original else None,original,
                                original.__traceback__ if original else None)
            except BaseException as error:
                if failure is None:failure=error
                else:failure.add_note('runtime owner exit failed: '+type(error).__name__)
        if pid != os.getpid() or session_unknown or (events is not None and _unresolved(events)):
            _RETAINED.append((scope,directories,owners,inspection,loader))
            if failure is None:failure=StudyError('runtime-unresolved')
            elif session_unknown:failure.add_note('native session resource lifetime unresolved')
        else:
            try:
                directories.__exit__(type(failure) if failure else None,failure,
                                     failure.__traceback__ if failure else None)
            except BaseException as error:
                if failure is None:failure=error
                else:failure.add_note('runtime pins exit failed: '+type(error).__name__)
            try:
                _origins(inspection)
            except BaseException as error:
                if failure is None:failure=error
                else:failure.add_note('runtime source exit failed: '+type(error).__name__)
            try:
                inspection.pins.close(failure)
            finally:
                try:
                    loader.__exit__(type(failure) if failure else None,failure,
                                    failure.__traceback__ if failure else None)
                except BaseException as error:
                    if failure is None:failure=error
                    else:failure.add_note('installation exit failed: '+type(error).__name__)
        if active_token is not None and pid == os.getpid():
            _ACTIVE_SCOPE.reset(active_token)
        if original is None and failure is not None:
            raise failure


def register_local(creation_directory):
    with _operate(creation_directory,None,register=True) as scope:
        result=scope.registration_ref
    return result


@contextmanager
def open_registered(study_id):
    with _operate(None,study_id,register=False) as scope:
        yield scope
