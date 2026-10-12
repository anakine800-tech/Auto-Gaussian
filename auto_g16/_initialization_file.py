"""Private descriptor-bound publication for three initial native database images."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import stat


class InitialFileError(ValueError):
    pass


def _require(value):
    if not value:
        raise InitialFileError('initial file binding or publication failed')


class _ReservedFile:
    def __init__(self, database, approved_root, parent_chain, filename):
        self.path, self.root = os.fspath(database), os.fspath(approved_root)
        _require(filename in ('approval.sqlite3', 'transport.sqlite3', 'project-journal.sqlite3'))
        for value in (self.path, self.root):
            _require(type(value) is str and value.startswith('/') and value != '/'
                     and all(p not in ('', '.', '..') for p in value[1:].split('/')) and '\x00' not in value)
        _require(Path(self.path).name == filename and str(Path(self.path).parent) == self.root)
        self.parts = Path(self.root).parts
        _require(type(parent_chain) is list and len(parent_chain) == len(self.parts)
                 and all(type(p) is list and len(p) == 2 and all(type(v) is int for v in p)
                         and p[0] >= 0 and p[1] >= 1 for p in parent_chain))
        self.chain = tuple(tuple(p) for p in parent_chain)
        self.fds, self.fd, self.pid = [], None, os.getpid()
        self.published_version = None
        try:
            for component in self.parts:
                self.fds.append(os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                        dir_fd=self.fds[-1] if self.fds else None))
            self.check()
            self.fd = os.open(filename, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                              0o600, dir_fd=self.fds[-1])
            info = os.fstat(self.fd)
            self.physical = (info.st_dev, info.st_ino)
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self):
        _require(os.getpid() == self.pid and len(self.fds) == len(self.parts))
        for index, (part, fd, physical) in enumerate(zip(self.parts, self.fds, self.chain)):
            named = os.stat(part, dir_fd=self.fds[index-1] if index else None, follow_symlinks=False)
            held = os.fstat(fd)
            _require(stat.S_ISDIR(named.st_mode) and stat.S_ISDIR(held.st_mode)
                     and (named.st_dev, named.st_ino) == physical == (held.st_dev, held.st_ino))
        name = Path(self.path).name
        for suffix in ('-journal', '-wal', '-shm'):
            try:
                os.stat(name + suffix, dir_fd=self.fds[-1], follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise InitialFileError('initial file has a sidecar')
        if self.fd is not None:
            named = os.stat(name, dir_fd=self.fds[-1], follow_symlinks=False)
            held = os.fstat(self.fd)
            _require(stat.S_ISREG(named.st_mode) and stat.S_ISREG(held.st_mode)
                     and named.st_nlink == held.st_nlink == 1
                     and (named.st_dev, named.st_ino) == self.physical == (held.st_dev, held.st_ino))
            if self.published_version is not None:
                _require((held.st_size, held.st_mtime_ns, held.st_ctime_ns) == self.published_version
                         == (named.st_size, named.st_mtime_ns, named.st_ctime_ns))

    def publish(self, raw):
        _require(type(raw) is bytes and 100 <= len(raw) <= 16 * 1024 * 1024)
        _require(raw[:16] == b'SQLite format 3\x00' and raw[18:20] == b'\x01\x01')
        self.check()
        _require(os.fstat(self.fd).st_size == 0 and os.lseek(self.fd, 0, os.SEEK_CUR) == 0)
        view = memoryview(raw)
        while view:
            self.check()
            count = os.write(self.fd, view)
            _require(type(count) is int and 0 < count <= len(view))
            view = view[count:]
        os.fsync(self.fd)
        os.fsync(self.fds[-1])
        self.check()
        info = os.fstat(self.fd)
        _require(info.st_size == len(raw))
        self.published_version = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        self.check()
        parts, offset = [], 0
        while offset < len(raw):
            part = os.pread(self.fd, min(1048576, len(raw) - offset), offset)
            _require(bool(part));parts.append(part);offset += len(part)
        _require(b''.join(parts) == raw)
        self.check()
        return dict(file_identity=list(self.physical), size_bytes=len(raw), sha256=sha256(raw).hexdigest())

    def close(self):
        if self.fd is not None:
            os.close(self.fd);self.fd = None
        while self.fds:
            os.close(self.fds.pop())


@contextmanager
def reserve(database, *, approved_root, parent_chain, filename):
    value = _ReservedFile(database, approved_root, parent_chain, filename)
    try:
        yield value
        value.check()
    finally:
        value.close()


def serialize_initial(connection, *, application_id, version, definitions, counts):
    """Validate a native owner's complete memory image before descriptor output."""
    _require(connection.execute('PRAGMA database_list').fetchall() == [(0, 'main', '')])
    _require(not connection.in_transaction)
    _require(connection.execute('PRAGMA application_id').fetchone()[0] == application_id
             and connection.execute('PRAGMA user_version').fetchone()[0] == version)
    actual = dict(connection.execute("SELECT name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"))
    _require(actual == definitions)
    tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    _require(set(tables) == set(counts))
    _require(all(connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] == counts[name] for name in tables))
    _require(connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
             and not connection.execute('PRAGMA foreign_key_check').fetchall())
    return connection.serialize()
