"""Transport-owned v2 existing-only guard. No creation or remote authority."""
from contextlib import contextmanager
from collections.abc import Mapping
import os
from pathlib import Path
import sqlite3
import stat
from threading import get_ident, RLock, Lock
from uuid import UUID

from ._canonical import TransportBoundaryError, canonical_bytes, strict_canonical_json

_QUARANTINE = {}


def require(value):
    if not value:
        raise TransportBoundaryError('existing completion store validation failed')


def decode(raw):
    """Decode the existing tagged encoder, accepting only exact round trips."""
    require(type(raw) is bytes)
    pos = 0

    def node():
        nonlocal pos
        require(pos < len(raw))
        tag = raw[pos:pos+1]
        pos += 1
        if tag == b'n':
            require(raw[pos:pos+1] == b';')
            pos += 1
            return None
        if tag in (b'b', b'i'):
            end = raw.index(b';', pos)
            token = raw[pos:end]
            pos = end+1
            if tag == b'b':
                require(token in (b'0', b'1'))
                return token == b'1'
            return int(token)
        require(tag in (b's', b'y', b'a', b'o'))
        end = raw.index(b':', pos)
        count = int(raw[pos:end])
        require(0 <= count <= len(raw))
        pos = end+1
        if tag in (b's', b'y'):
            size = count if tag == b's' else 2*count
            value = raw[pos:pos+size]
            require(len(value) == size)
            pos += size
            return value.decode('utf-8') if tag == b's' else bytes.fromhex(value.decode('ascii'))
        if tag == b'a':
            return tuple(node() for _ in range(count))
        value = {}
        for _ in range(count):
            key = node()
            require(type(key) is str and key not in value)
            value[key] = node()
        return value
    try:
        value = node()
        require(pos == len(raw) and canonical_bytes(value) == raw)
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise TransportBoundaryError('invalid native completion row encoding') from error


class Rows:
    def __init__(self, values, count):
        self.values, self.rowcount = values, count

    def fetchone(self):
        return self.values.pop(0) if self.values else None

    def fetchall(self):
        value, self.values = self.values, []
        return value

    def __iter__(self):
        return iter(self.values)


def rows(connection, sql, args=()):
    cursor = connection.cursor()
    original = None
    try:
        cursor.execute(sql, args)
        return Rows(cursor.fetchall(), cursor.rowcount)
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            cursor.close()
        except BaseException as error:
            if original is None:
                if not isinstance(error, Exception):
                    raise
                raise TransportBoundaryError('completion cursor close failed') from error
            original.add_note('completion cursor close failed: ' + type(error).__name__)


@contextmanager
def preserved(context):
    """Keep the native lock implementation, preserving a body interruption."""
    value = context.__enter__()
    try:
        yield value
    except BaseException as original:
        try:
            context.__exit__(type(original), original, original.__traceback__)
        except BaseException as error:
            original.add_note('completion directory cleanup failed: ' + type(error).__name__)
        raise
    else:
        context.__exit__(None, None, None)


def quarantine(guard, *connections):
    retained = _QUARANTINE.setdefault((os.getpid(), guard.identities[-1]), [guard])
    for value in connections:
        if value is not None and not any(value is item for item in retained):
            retained.append(value)
    guard.poisoned = guard.quarantined = True


def close_connection(guard, connection):
    if guard.pid != os.getpid() or guard.quarantined:
        quarantine(guard, connection)
        raise TransportBoundaryError('completion SQLite resources retained unresolved')
    try:
        connection.close()
    except BaseException as error:
        quarantine(guard, connection)
        if not isinstance(error, Exception):
            raise
        raise TransportBoundaryError('completion SQLite close unresolved') from error


class Guard:
    def __init__(self, database, root, chain, physical, instance, application):
        self.fds = []
        self.pid, self.thread = os.getpid(), get_ident()
        self.poisoned = self.quarantined = self.transaction = False
        self.startup = True
        self.journal_identity = None
        self.cursors = 0
        try:
            self.path, self.root = os.fspath(database), os.fspath(root)
            for path in (self.path, self.root):
                require(type(path) is str and path.startswith('/') and '\x00' not in path
                        and (path == '/' or all(p not in ('', '.', '..') for p in path.split('/')[1:])))
            require(self.path != self.root and os.path.commonpath((self.path, self.root)) == self.root)
            self.parts = Path(self.path).parts
            require(type(chain) is tuple and len(chain) == len(self.parts)-1)
            for identity in (*chain, physical):
                require(type(identity) is tuple and len(identity) == 2
                        and all(type(x) is int for x in identity) and identity[0] >= 0 and identity[1] >= 1)
            require(type(instance) is str and str(UUID(instance)) == instance)
            self.identities = (*chain, physical)
            self.instance = instance
            require((self.pid, physical) not in _QUARANTINE)
            from . import program as p
            for handle in tuple(p._STORE_HANDLES):
                require(not (handle._creator_pid == self.pid and handle._file_identity == physical
                             and not handle._closed))
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            for i, part in enumerate(self.parts):
                fd = os.open(part, flags | (os.O_NONBLOCK if i == len(self.parts)-1 else os.O_DIRECTORY),
                             dir_fd=self.fds[-1] if self.fds else None)
                self.fds.append(fd)
            self.check()
            self.version = self.signature()
            header = os.pread(self.fds[-1], 100, 0)
            require(len(header) == 100 and header[:16] == b'SQLite format 3\0'
                    and header[18:20] == b'\x01\x01'
                    and int.from_bytes(header[60:64], 'big') == 2
                    and int.from_bytes(header[68:72], 'big') == application)
            self.startup_check()
        except BaseException as error:
            self.close(error)
            if isinstance(error, (OSError, TypeError, ValueError)):
                raise TransportBoundaryError('existing completion binding rejected') from error
            raise

    def owner(self):
        try:
            require(self.pid == os.getpid() and self.thread == get_ident()
                    and not self.poisoned and len(self.fds) == len(self.parts))
        except BaseException:
            self.poisoned = True
            raise

    def check(self):
        try:
            self.owner()
            for i, (part, fd, physical) in enumerate(zip(self.parts, self.fds, self.identities)):
                opened = os.fstat(fd)
                named = os.stat(part, dir_fd=self.fds[i-1] if i else None, follow_symlinks=False)
                require((opened.st_dev, opened.st_ino) == physical == (named.st_dev, named.st_ino))
                require((stat.S_ISREG(opened.st_mode) and stat.S_ISREG(named.st_mode)
                         and opened.st_nlink == named.st_nlink == 1) if i == len(self.parts)-1
                        else stat.S_ISDIR(opened.st_mode) and stat.S_ISDIR(named.st_mode))
            for suffix in ('-wal', '-shm', '-journal'):
                try:
                    item = os.stat(self.parts[-1]+suffix, dir_fd=self.fds[-2], follow_symlinks=False)
                except FileNotFoundError:
                    continue
                require(suffix == '-journal' and self.transaction and stat.S_ISREG(item.st_mode)
                        and item.st_nlink == 1)
                identity = item.st_dev, item.st_ino
                if self.journal_identity is None:
                    self.journal_identity = identity
                require(self.journal_identity == identity)
        except BaseException:
            self.poisoned = True
            raise

    def signature(self):
        s = os.fstat(self.fds[-1])
        return s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def startup_check(self):
        try:
            self.check()
            require(self.version == self.signature())
        except BaseException:
            self.poisoned = True
            raise

    def statement(self, connection, sql, args=()):
        try:
            self.check()
            require(self.cursors == 0)
            self.cursors += 1
            try:
                return rows(connection, sql, args)
            finally:
                self.cursors -= 1
        except sqlite3.IntegrityError:
            raise
        except BaseException:
            self.poisoned = True
            raise

    def rollback(self, store, original):
        if self.pid != os.getpid():
            quarantine(self, store._connection)
            return
        if self.quarantined:
            return
        try:
            if store._connection.in_transaction:
                rows(store._connection, 'ROLLBACK')
        except BaseException as error:
            original.add_note('completion rollback failed: ' + type(error).__name__)
            quarantine(self, store._connection)

    @contextmanager
    def write(self, store):
        owned = False
        try:
            self.check()
            require(not store._connection.in_transaction and not self.transaction)
            self.transaction = owned = True
            store._sql('BEGIN IMMEDIATE')
            yield
            self.check()
            store._sql('COMMIT')
            self.transaction = False
            self.journal_identity = None
            self.check()
        except BaseException as error:
            if owned:
                self.rollback(store, error)
            raise
        finally:
            if owned:
                self.transaction = False
                self.journal_identity = None

    def close(self, original=None):
        if self.quarantined:
            return
        pending, self.fds = self.fds, []
        failure = None
        for fd in reversed(pending):
            try:
                os.close(fd)
            except BaseException as error:
                if failure is None:
                    failure = error
        if failure is not None:
            self.poisoned = True
            if original is None:
                if not isinstance(failure, Exception):
                    raise failure
                raise TransportBoundaryError('completion descriptor close failed') from failure
            original.add_note('completion descriptor close failed: ' + type(failure).__name__)


def _validate_rows(store):
    from . import program as p
    store._attest_locked()
    sql = store._sql
    databases = sql('PRAGMA database_list').fetchall()
    require(databases in ([(0, 'main', store._path)], [(0, 'main', store._path), (1, 'temp', '')]))
    if len(databases) == 2:
        require(sql('SELECT name FROM temp.sqlite_master').fetchall() == [])
    require(sql('PRAGMA integrity_check').fetchall() == [('ok',)])
    require(sql('PRAGMA foreign_key_check').fetchall() == [])
    require(store.store_instance_id == store._existing_guard.instance)
    runtime = {}
    for row in sql('SELECT * FROM program_runtime_attestation'):
        payload = decode(row[-1])
        p._exact_keys(payload, {'schema', 'program_transport_store_id', 'store_instance_id',
            'program_execution_snapshot_id', 'resolved_server_profile_id', 'protocol',
            'operation_table_sha256', 'qualified_runtime'}, 'runtime row')
        identity, _columns, values = store._runtime_attestation_record(
            program_execution_snapshot_id=payload['program_execution_snapshot_id'],
            resolved_server_profile_id=payload['resolved_server_profile_id'], qualification=payload['qualified_runtime'])
        require(tuple(row) == values)
        runtime[identity] = payload
    for row in sql('SELECT * FROM program_effect_physical_authority'):
        raw = row[-1]
        if type(row[0]) is str and row[0].startswith(p._SCHEDULER_RAW_PREFIX):
            payload = strict_canonical_json(raw, 'scheduler raw row')
            p._exact_keys(payload, {'schema','purpose','acquired_at','binding','request',
                'request_sha256','job_id','raw_result','stdout_sha256','stderr_sha256',
                'raw_result_sha256'}, 'scheduler raw row')
            request = payload['request']
            rebuilt = p._scheduler_raw_payload(request, payload['raw_result'], payload['acquired_at'])
            binding = p._base_binding(request['binding'])
            p._validate_program_effect_request(request, request['binding'])
            require(payload == rebuilt and tuple(row) == store._scheduler_raw_values(rebuilt, binding))
        else:
            payload = decode(raw)
            p._exact_keys(payload, {'schema','program_transport_store_id','store_instance_id',
                'runtime_attestation_id','attempt_id','program_execution_snapshot_id','effect_intent_id',
                'operation','request','request_sha256','effect_classification','response','job_id'}, 'effect row')
            request = payload['request']
            binding = p._base_binding(request['binding'])
            p._validate_program_effect_request(request, request['binding'])
            classification, job = payload['effect_classification'], payload['job_id']
            require(classification in {'SUCCEEDED','FAILED','UNKNOWN'} and isinstance(payload['response'], Mapping))
            if job is not None:
                p._job_id(job)
            rebuilt = dict(schema=store._schema, program_transport_store_id=store.program_transport_store_id,
                store_instance_id=store.store_instance_id, runtime_attestation_id=binding['runtime_attestation_id'],
                attempt_id=binding['attempt_id'], program_execution_snapshot_id=binding['program_execution_snapshot_id'],
                effect_intent_id=binding['effect_intent_id'], operation=request['operation'], request=dict(request),
                request_sha256=p._digest(request), effect_classification=classification,
                response=dict(payload['response']), job_id=job)
            key = p._identity('program-submit-once', {k: binding[k] for k in
                ('attempt_id','program_execution_snapshot_id','effect_intent_id')}) if request['operation'] == 'SUBMIT_QSUB_ONCE' else None
            values = (p._identity('program-physical-effect', rebuilt), store.program_transport_store_id,
                store.store_instance_id, binding['runtime_attestation_id'], binding['attempt_id'],
                binding['program_execution_snapshot_id'], binding['effect_intent_id'], request['operation'],
                p._digest(request), classification, job, key, canonical_bytes(rebuilt))
            require(payload == rebuilt and tuple(row) == values)
        parent = runtime.get(binding['runtime_attestation_id'])
        require(parent is not None and all(binding[k] == parent[k] for k in
            ('program_transport_store_id','store_instance_id','program_execution_snapshot_id','resolved_server_profile_id')))


def validate_rows(store):
    try:
        _validate_rows(store)
    except BaseException as error:
        store._existing_guard.poisoned = True
        if isinstance(error, (ValueError, TypeError, KeyError, IndexError, sqlite3.DatabaseError)) and not isinstance(error, TransportBoundaryError):
            raise TransportBoundaryError('invalid native completion store rows') from error
        raise


def insert(store, table, columns, values, identity):
    with store._store_access(), store._lock:
        store._attest()
        with store._existing_guard.write(store):
            marks = ','.join('?' for _ in values)
            try:
                store._sql(f"INSERT INTO {table}({','.join(columns)}) VALUES({marks})", values)
            except sqlite3.IntegrityError:
                existing = store._sql(f"SELECT {','.join(columns)} FROM {table} WHERE {columns[0]}=?", (identity,)).fetchone()
                require(existing is not None and tuple(existing) == values)
            loaded = store._sql(f"SELECT {','.join(columns)} FROM {table} WHERE {columns[0]}=?", (identity,)).fetchall()
            require(len(loaded) == 1 and tuple(loaded[0]) == values)


@contextmanager
def completion_guard(store):
    from . import program as p
    guard = store._existing_guard
    guard.check()
    try:
        with preserved(p._directory_guard(store._path, store._root)) as (binding, descriptor, lock):
            require(binding == store._guard_binding)
            guard.check()
            store._completion_lock = lock
            token = store._set_completion_owner(descriptor)
            try:
                store._require_completion_guard(token)
                yield token
                store._require_completion_guard(token)
                require(not store._connection.in_transaction and guard.cursors == 0)
            finally:
                store._completion_owner = None
    except p._DirectoryReleaseError:
        guard.poisoned = True
        raise


def close_store(store):
    guard = store._existing_guard
    if guard.pid != os.getpid():
        quarantine(guard, store._connection)
        raise TransportBoundaryError('forked completion resources retained unresolved')
    require(guard.thread == get_ident())
    if guard.quarantined:
        raise TransportBoundaryError('completion SQLite resources retained unresolved')
    with store._lock:
        require(store._completion_owner is None)
        if store._closed:
            return
        original = None
        if not guard.poisoned:
            try:
                guard.check()
                require(not store._connection.in_transaction and guard.cursors == 0)
            except BaseException as error:
                original = error
                guard.poisoned = True
        if store._connection.in_transaction:
            interrupted = original or TransportBoundaryError('completion close left an active transaction')
            guard.rollback(store, interrupted)
            original = interrupted
        try:
            close_connection(guard, store._connection)
            store._closed = True
        except BaseException as error:
            if original is None:
                raise
            original.add_note('completion SQLite close failed: ' + type(error).__name__)
        finally:
            guard.close(original)
        if original is not None:
            raise original


@contextmanager
def open_existing(cls, database, *, approved_root, expected_parent_chain, expected_file_identity,
                  expected_store_instance_id):
    from . import program as p
    p._require_store_process()
    guard, store, connection, original = None, None, None, None
    try:
        path, root = os.fspath(database), os.fspath(approved_root)
        with preserved(p._directory_guard(path, root)) as (binding, parent, lock):
            guard = Guard(database, approved_root, expected_parent_chain, expected_file_identity,
                          expected_store_instance_id, p._PROGRAM_STORE_APPLICATION_ID)
            require(tuple(map(tuple, binding['component_identities'])) == expected_parent_chain)
            store = object.__new__(cls)
            store._path, store._root, store._file_identity = guard.path, guard.root, expected_file_identity
            store._creator_pid, store._version, store._schema = guard.pid, 2, p._COMPLETION_STORE_SCHEMA
            store._lock, store._completion_lock = RLock(), Lock()
            store._completion_owner, store._guard_binding = None, binding
            store._invalid = store._closed = False
            store._existing_guard = guard
            with p._DIRECTORY_MUTEX:
                p._STORE_HANDLES.add(store)
            for mode in ('ro','rw'):
                guard.startup_check()
                connection = sqlite3.connect(Path(guard.path).as_uri()+'?mode='+mode+'&cache=private',
                                             uri=True, isolation_level=None, check_same_thread=False)
                store._connection = connection
                for statement in ('PRAGMA query_only=ON', 'PRAGMA foreign_keys=ON',
                                  'PRAGMA trusted_schema=OFF', 'PRAGMA synchronous=FULL'):
                    store._sql(statement)
                require(store._sql('PRAGMA journal_mode').fetchone() == ('delete',))
                require(store._sql('PRAGMA locking_mode').fetchone() == ('normal',))
                token = store._set_completion_owner(parent)
                try:
                    store._sql('BEGIN')
                    validate_rows(store)
                    store._sql('ROLLBACK')
                    guard.startup_check()
                finally:
                    store._completion_owner = None
                if mode == 'ro':
                    closing, connection = connection, None
                    close_connection(guard, closing)
                    guard.startup_check()
            store._sql('PRAGMA query_only=OFF')
            guard.startup_check()
        guard.startup = False
        try:
            yield store
            if not store._closed:
                with store._completion_guard():
                    validate_rows(store)
                    guard.check()
        except BaseException as error:
            guard.rollback(store, error)
            raise
    except BaseException as error:
        original = error
        raise
    finally:
        cleanup = original
        try:
            if guard is not None and guard.pid != os.getpid():
                quarantine(guard, connection)
                if cleanup is None:
                    cleanup = TransportBoundaryError('forked completion resources retained unresolved')
            if connection is not None and not guard.quarantined and not store._closed:
                try:
                    if connection.in_transaction:
                        residual = TransportBoundaryError('completion context left an active transaction')
                        guard.poisoned = True
                        guard.rollback(store, residual)
                        if cleanup is None:
                            cleanup = residual
                    if not guard.quarantined:
                        close_connection(guard, connection)
                        store._closed = True
                except BaseException as error:
                    if cleanup is None:
                        cleanup = error
                    else:
                        cleanup.add_note('completion close failed: ' + type(error).__name__)
            if guard is not None:
                guard.close(cleanup)
        finally:
            if original is None and cleanup is not None:
                raise cleanup
