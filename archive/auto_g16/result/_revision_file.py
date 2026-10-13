"""Private exclusive local revision publication; never opens a disk SQL writer."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import stat

from .models import ProvenanceConflictError


def _require(ok, message):
    if not ok:
        raise ProvenanceConflictError(message)


def _identity(info):
    return info.st_dev, info.st_ino


@contextmanager
def _parent(path, root):
    path, root = os.fspath(path), os.fspath(root)
    _require(os.path.isabs(path) and path == os.path.abspath(path)
             and os.path.isabs(root) and root == os.path.abspath(root)
             and '//' not in path and '//' not in root,
             'revision paths must be canonical absolute paths')
    _require(Path(path).is_relative_to(root) and path != root, 'revision escapes selected local root')
    parts = Path(path).parts
    fds, identities = [], []
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY | os.O_CLOEXEC
    def check():
        for index, (fd, identity) in enumerate(zip(fds, identities)):
            named = os.stat(parts[index], dir_fd=fds[index-1] if index else None, follow_symlinks=False)
            _require(stat.S_ISDIR(named.st_mode) and _identity(named) == identity
                     and _identity(os.fstat(fd)) == identity, 'revision parent identity drift')
    try:
        for index, part in enumerate(parts[:-1]):
            fd = os.open(part, flags, dir_fd=fds[-1] if fds else None)
            fds.append(fd)
            identities.append(_identity(os.fstat(fd)))
        check()
        yield fds[-1], parts[-1], check
        check()
    finally:
        for fd in reversed(fds):
            os.close(fd)


def publish_revision(raw, *, path, root, forbidden_identities=()):
    """One exact new file or explicit complete-byte replay; failures are retained."""
    _require(type(raw) is bytes and raw.startswith(b'SQLite format 3\x00'), 'revision is not SQLite bytes')
    expected = sha256(raw).hexdigest()
    with _parent(path, root) as (parent, name, check_parent):
        check_parent()
        created = False
        flags = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        try:
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | flags, 0o600, dir_fd=parent)
            created = True
        except FileExistsError:
            fd = os.open(name, os.O_RDONLY | flags, dir_fd=parent)
        try:
            identity = _identity(os.fstat(fd))
            _require(identity not in forbidden_identities, 'revision aliases an input database')
            def check_file():
                check_parent()
                info = os.fstat(fd)
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
                _require(stat.S_ISREG(info.st_mode) and stat.S_ISREG(named.st_mode)
                         and info.st_nlink == named.st_nlink == 1
                         and _identity(info) == _identity(named) == identity,
                         'revision file identity drift')
            check_file()
            if created:
                offset = 0
                while offset < len(raw):
                    written = os.write(fd, raw[offset:offset+1048576])
                    _require(written > 0, 'revision short write')
                    offset += written
            def readback():
                _require(os.fstat(fd).st_size == len(raw), 'existing revision is incomplete or conflicts')
                os.lseek(fd, 0, os.SEEK_SET)
                digest, count = sha256(), 0
                while count < len(raw):
                    block = os.read(fd, min(1048576, len(raw)-count))
                    _require(bool(block), 'revision short read')
                    digest.update(block)
                    count += len(block)
                _require(not os.read(fd, 1) and digest.hexdigest() == expected, 'revision content conflicts')
            readback()
            check_file()
            os.fsync(fd)
            os.fsync(parent)
            readback()
            check_file()
        finally:
            os.close(fd)
    return {'path': os.fspath(path), 'sha256': expected, 'size_bytes': len(raw)}
