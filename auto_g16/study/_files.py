"""Descriptor-relative, exclusive local evidence publication with held directory lock."""
import fcntl
import os
from pathlib import Path
import stat

from ._model import StudyError, require

CAP = 64 * 1024 * 1024


def identity(info):
    return [info.st_dev, info.st_ino]


class Directory:
    def __init__(self, path, *, write=False, lock=True):
        self.path = Path(path)
        require(type(path) is str and path.startswith('/') and path != '/'
                and all(p not in {'', '.', '..'} for p in path[1:].split('/')))
        self.parts = path[1:].split('/')
        self.fds, self.seen = [], {}
        self.expected_names = None
        self.write = write
        try:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            self.fds.append(os.open('/', flags))
            for part in self.parts:
                self.fds.append(os.open(part, flags, dir_fd=self.fds[-1]))
            self.chain = [identity(os.fstat(fd)) for fd in self.fds]
            if lock:
                try:
                    fcntl.flock(self.fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise StudyError('busy') from exc
            self.check()
        except BaseException:
            self.close()
            raise

    @property
    def fd(self):
        return self.fds[-1]

    def check(self):
        for i, fd in enumerate(self.fds):
            named = os.stat('/', follow_symlinks=False) if i == 0 else os.stat(
                self.parts[i - 1], dir_fd=self.fds[i - 1], follow_symlinks=False)
            require(stat.S_ISDIR(named.st_mode) and identity(named) == self.chain[i]
                    and identity(os.fstat(fd)) == self.chain[i])

    def names(self):
        self.check()
        return set(os.listdir(self.fd))

    def seal(self, expected_names):
        require(self.names() == expected_names)
        self.expected_names = frozenset(expected_names)

    def read(self, name, cap=CAP):
        require(type(name) is str and name not in {'', '.', '..'} and '/' not in name)
        self.check()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 < before.st_size <= cap, 'initialization-unresolved')
            chunks, size = [], 0
            while size <= cap:
                block = os.read(fd, min(1048576, cap + 1 - size))
                if not block:
                    break
                chunks.append(block)
                size += len(block)
            raw = b''.join(chunks)
            named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_nlink, s.st_mtime_ns, s.st_ctime_ns)
            require(size == before.st_size and signature(before) == signature(os.fstat(fd))
                    == signature(named))
            value = (signature(before), raw)
            require(name not in self.seen or self.seen[name] == value)
            self.seen[name] = value
            self.check()
            return raw, identity(before)
        finally:
            os.close(fd)

    def publish(self, name, raw):
        require(self.write and type(raw) is bytes and 0 < len(raw) <= CAP)
        require(name not in self.names())
        self.check()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        try:
            require(stat.S_ISREG(os.fstat(fd).st_mode) and os.fstat(fd).st_nlink == 1)
            view = memoryview(raw)
            while view:
                n = os.write(fd, view)
                require(n > 0)
                view = view[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fd)
        self.check()
        require(self.read(name)[0] == raw)

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.check()
            for name in tuple(self.seen):
                self.read(name)
            if self.expected_names is not None:
                require(self.names() == self.expected_names)
            self.check()
        finally:
            self.close()


def read_request(path):
    require(type(path) is str and Path(path).is_absolute(), 'invalid-request')
    with Directory(str(Path(path).parent), lock=False) as directory:
        raw, _ = directory.read(Path(path).name, 1024 * 1024)
    return raw
