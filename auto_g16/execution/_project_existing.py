"""Project-owned existing-file guard; no Study, creating open or remote effects."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat
import threading
from uuid import UUID

from ._identity import ExecutionValueError


def require(value):
    if not value:
        raise ExecutionValueError('existing Project journal validation failed')


# Unknown SQLite closure/fork state retains locks until process exit/exec.
# It has no reset or automatic cleanup path and never changes persisted state.
_QUARANTINE = {}


def quarantine(guard, *connections):
    key = (os.getpid(), guard.identities[-1])
    retained = _QUARANTINE.setdefault(key, [guard])
    for connection in connections:
        if connection is not None and not any(connection is item for item in retained):
            retained.append(connection)
    guard.poisoned = guard.quarantined = True


def close_sqlite(guard, connection, *other_connections):
    if guard.pid != os.getpid() or guard.quarantined:
        quarantine(guard, connection, *other_connections)
        raise ExecutionValueError('Project SQLite resources retained unresolved')
    try:
        connection.close()
    except BaseException as error:
        quarantine(guard, connection, *other_connections)
        raise ExecutionValueError('Project SQLite close unresolved; resources retained') from None


class _Rows:
    def __init__(self, rows, rowcount):
        self.rows, self.rowcount = rows, rowcount

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def __iter__(self):
        return iter(self.rows)


def rows(connection, sql, parameters=()):
    cursor = connection.cursor()
    original = None
    try:
        cursor.execute(sql, parameters)
        return _Rows(cursor.fetchall(), cursor.rowcount)
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            cursor.close()
        except BaseException as error:
            if original is None:
                raise ExecutionValueError('Project cursor close failed') from None
            original.add_note('Project cursor close failed: ' + type(error).__name__)


class Guard:
    def __init__(self, database, root, parent_chain, file_identity, journal_identity, application_id):
        self.fds = []
        self.pid, self.thread = os.getpid(), threading.get_ident()
        self.poisoned = self.readback_active = self.transaction_active = self.quarantined = False
        self.cursors = 0
        try:
            self.path, self.root = os.fspath(database), os.fspath(root)
            for path in (self.path, self.root):
                require(type(path) is str and path.startswith('/') and path != '/'
                        and not any(c in path for c in '\x00\r\n\\')
                        and all(part not in ('', '.', '..') for part in path.split('/')[1:]))
            require(self.path != self.root and os.path.commonpath((self.path, self.root)) == self.root)
            self.parts = Path(self.path).parts
            require(type(parent_chain) is tuple and len(parent_chain) == len(self.parts) - 1)
            for value in (*parent_chain, file_identity):
                require(type(value) is tuple and len(value) == 2 and all(type(v) is int for v in value)
                        and value[0] >= 0 and value[1] >= 1)
            require(type(journal_identity) is str and str(UUID(journal_identity)) == journal_identity)
            require((self.pid, file_identity) not in _QUARANTINE)
            self.journal_identity = journal_identity
            self.identities = (*parent_chain, file_identity)
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
            for i, part in enumerate(self.parts):
                fd = os.open(part, flags | (os.O_NONBLOCK if i == len(self.parts)-1 else os.O_DIRECTORY),
                             dir_fd=self.fds[-1] if self.fds else None)
                self.fds.append(fd)
            self.check(idle=True)
            self.version = self._version()
            header = os.pread(self.fds[-1], 100, 0)
            require(len(header) == 100 and header[:16] == b'SQLite format 3\0'
                    and header[18:20] == b'\x01\x01'
                    and int.from_bytes(header[60:64], 'big') == 3
                    and int.from_bytes(header[68:72], 'big') == application_id)
            self.startup_check()
        except BaseException as error:
            self.close(error)
            if isinstance(error, (TypeError, ValueError, OSError)) and not isinstance(error, FileNotFoundError):
                raise ExecutionValueError('existing Project journal binding rejected') from None
            raise

    def _version(self):
        s = os.fstat(self.fds[-1])
        return s.st_size, s.st_mtime_ns, s.st_ctime_ns

    def owner(self):
        require(not self.poisoned and self.pid == os.getpid() and self.thread == threading.get_ident()
                and len(self.fds) == len(self.parts))

    def check(self, *, idle=False):
        try:
            self.owner()
            for i, (part, fd, physical) in enumerate(zip(self.parts, self.fds, self.identities)):
                opened = os.fstat(fd)
                named = os.stat(part, dir_fd=self.fds[i-1] if i else None, follow_symlinks=False)
                final = i == len(self.parts)-1
                require((opened.st_dev, opened.st_ino) == physical == (named.st_dev, named.st_ino))
                require((stat.S_ISREG(opened.st_mode) and stat.S_ISREG(named.st_mode)
                         and opened.st_nlink == named.st_nlink == 1) if final else (
                         stat.S_ISDIR(opened.st_mode) and stat.S_ISDIR(named.st_mode)))
            for suffix in ('-wal', '-shm', *(('-journal',) if idle else ())):
                try:
                    os.stat(self.parts[-1] + suffix, dir_fd=self.fds[-2], follow_symlinks=False)
                except FileNotFoundError:
                    continue
                require(False)
        except BaseException:
            self.poisoned = True
            raise

    def startup_check(self):
        self.check(idle=True)
        require(self.version == self._version())

    def statement(self, connection, sql, parameters=()):
        try:
            self.check(idle=not self.transaction_active)
            require(not self.readback_active and self.cursors == 0)
            self.cursors += 1
            try:
                return rows(connection, sql, parameters)
            finally:
                self.cursors -= 1
        except sqlite3.IntegrityError:
            raise
        except BaseException:
            self.poisoned = True
            raise

    def rollback(self, store, original):
        try:
            if self.pid == os.getpid() and not self.quarantined and store._connection.in_transaction:
                rows(store._connection, 'ROLLBACK')
        except BaseException as error:
            self.poisoned = True
            original.add_note('Project rollback failed: ' + type(error).__name__)
            try:
                store.close()
            except BaseException as close_error:
                original.add_note('Project close failed: ' + type(close_error).__name__)

    @contextmanager
    def transaction(self, store):
        connection = store._connection
        owns_begin = False
        try:
            self.check(idle=True)
            require(not connection.in_transaction and not self.transaction_active and not self.readback_active)
            self.transaction_active = True
            owns_begin = True
            store._sql('BEGIN IMMEDIATE')
            self.check()
            yield
            store._attest()
            self.check()
            store._sql('COMMIT')
            self.transaction_active = False
            self.check(idle=True)
            store._validate_existing_rows()
        except BaseException as error:
            if owns_begin:
                self.rollback(store, error)
            raise
        finally:
            if owns_begin:
                self.transaction_active = False

    def readback(self, store, query, parameters, expected):
        connection, reader, original = store._connection, None, None
        try:
            self.check(idle=True)
            require(not connection.in_transaction and not self.transaction_active and not self.readback_active
                    and self.cursors == 0)
            require(store._sql('PRAGMA locking_mode').fetchone() == ('normal',))
            self.readback_active = True
            reader = sqlite3.connect(Path(self.path).as_uri() + '?mode=ro&cache=private',
                                     uri=True, isolation_level=None)
            configure(reader)
            self.check(idle=True)
            require(rows(reader, 'PRAGMA database_list').fetchall() == [(0, 'main', self.path)])
            require(rows(reader, 'PRAGMA query_only').fetchone() == (1,))
            require(rows(reader, query, parameters).fetchall() == expected)
            self.check(idle=True)
        except BaseException as error:
            self.poisoned = True
            original = error
            raise
        finally:
            try:
                if reader is not None:
                    try:
                        close_sqlite(self, reader, connection)
                    except BaseException as error:
                        self.poisoned = True
                        if original is not None:
                            original.add_note('Project readback close failed: ' + type(error).__name__)
                        else:
                            raise ExecutionValueError('Project readback close failed') from None
                if original is None:
                    self.check(idle=True)
            finally:
                self.readback_active = False

    def close(self, original=None):
        if self.quarantined:
            return
        pending, self.fds = self.fds, []
        failed = False
        for fd in reversed(pending):
            try:
                os.close(fd)
            except OSError:
                failed = True
        if failed:
            if original is not None:
                original.add_note('Project descriptor close failed')
            else:
                raise ExecutionValueError('Project descriptor close failed')


def configure(connection):
    for sql in ('PRAGMA query_only=ON', 'PRAGMA foreign_keys=ON', 'PRAGMA trusted_schema=OFF',
                'PRAGMA synchronous=FULL'):
        rows(connection, sql)
    require(rows(connection, 'PRAGMA journal_mode').fetchone() == ('delete',))
    require(rows(connection, 'PRAGMA locking_mode').fetchone() == ('normal',))
    require(rows(connection, 'PRAGMA read_uncommitted').fetchone() == (0,))


@contextmanager
def open_existing(cls, database, *, approved_root, expected_parent_chain, expected_file_identity,
                  expected_journal_identity, application_id):
    guard = Guard(database, approved_root, expected_parent_chain, expected_file_identity,
                  expected_journal_identity, application_id)
    store, reader, original = None, None, None
    try:
        store = object.__new__(cls)
        store._path, store._root, store._file_identity = guard.path, guard.root, expected_file_identity
        store._read_only, store._version, store._identity = False, 3, expected_journal_identity
        store._existing_guard = guard
        store._closed = False
        for mode in ('ro', 'rw'):
            guard.startup_check()
            reader = sqlite3.connect(Path(guard.path).as_uri() + '?mode=' + mode + '&cache=private',
                                     uri=True, isolation_level=None)
            store._connection = reader
            configure(reader)
            guard.startup_check()
            store._validate_existing_rows()
            guard.startup_check()
            if mode == 'ro':
                closing, reader = reader, None
                close_sqlite(guard, closing)
                guard.startup_check()
        store._sql('PRAGMA query_only=OFF')
        try:
            yield store
            guard.check(idle=not guard.transaction_active)
            require(not store._closed and not store._connection.in_transaction)
            store._validate_existing_rows()
            guard.check(idle=True)
        except BaseException as error:
            guard.rollback(store, error)
            try:
                store._validate_existing_rows()
                guard.check(idle=True)
            except BaseException as check_error:
                error.add_note('Project exit validation failed: ' + type(check_error).__name__)
            raise
    except BaseException as error:
        original = error
        raise
    finally:
        cleanup = original
        try:
            if guard.pid != os.getpid():
                quarantine(guard, reader, getattr(store, '_connection', None))
                if cleanup is None:
                    cleanup = ExecutionValueError('forked Project resources retained unresolved')
            if reader is not None and not guard.quarantined and (store is None or not store._closed):
                try:
                    close_sqlite(guard, reader)
                except BaseException as error:
                    if cleanup is None:
                        cleanup = ExecutionValueError('Project SQLite close failed')
                    else:
                        cleanup.add_note('Project SQLite close failed: ' + type(error).__name__)
            if store is not None:
                store._closed = True
            guard.close(cleanup)
        finally:
            if original is None and cleanup is not None:
                raise cleanup
