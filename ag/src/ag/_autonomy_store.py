"""Local durability for autonomy; never repair or truncate evidence.

The existing study path checks are reused. Descriptor-relative, no-follow IO
also closes path replacement races. The persistent flock is held only during
short local transactions, never for the duration of a run or a remote action.
"""
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from ag import study


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite JSON number')
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def directory(path):
    """Walk from the filesystem root without following any symbolic link."""
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Path escapes study')
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class Store:
    def __init__(self, fd):
        self.fd = fd
        self.lockfd = None

    def verify_lock(self):
        if self.lockfd is not None:
            current = os.stat('store.lock', dir_fd=self.fd, follow_symlinks=False)
            held = os.fstat(self.lockfd)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1 or held.st_nlink != 1
                    or (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)):
                raise ValueError('Autonomy mutex was replaced; preserve files for inspection')

    def open(self, name, flags, *, mode=0o600):
        # Internal filenames only, including content-addressed plan files.
        if not name or Path(name).name != name or name in ('.', '..'):
            raise ValueError('Invalid autonomy filename')
        fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, mode, dir_fd=self.fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            os.close(fd)
            raise ValueError('Autonomy records must be regular files with one link')
        return fd

    def read(self, name):
        with os.fdopen(self.open(name, os.O_RDONLY), 'rb') as handle:
            return handle.read()

    def exclusive(self, name, data):
        with os.fdopen(self.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(self.fd)

    def append(self, data):
        with os.fdopen(self.open('journal.jsonl', os.O_WRONLY | os.O_APPEND), 'wb') as handle:
            if handle.write(data) != len(data):
                raise OSError('Incomplete autonomy journal append')
            handle.flush()
            os.fsync(handle.fileno())

    def publish(self, value):
        name = '.state-' + uuid4().hex
        # Keep temporary evidence on failure; never clean up another writer.
        self.exclusive(name, encode(value))
        try:
            fd = self.open('state.json', os.O_RDONLY)
        except FileNotFoundError:
            pass
        else:
            os.close(fd)
        os.replace(name, 'state.json', src_dir_fd=self.fd, dst_dir_fd=self.fd)
        os.fsync(self.fd)

    def load(self, apply, *, allow_stale=False):
        """Only an exact historical snapshot may be explicitly replayed.

        Missing/truncated/edited state is not presumed empty. A missing initial
        snapshot is recoverable only from a complete journal starting at init.
        """
        self.verify_lock()
        data = self.read('journal.jsonl')
        state, previous, snapshots = None, None, []
        try:
            for seq, line in enumerate(data.splitlines(keepends=True), 1):
                event = decode(line)
                if (not line.endswith(b'\n') or encode(event) != line
                        or set(event) != {'seq', 'prev_sha256', 'op', 'at', 'data'}
                        or type(event['seq']) is not int or event['seq'] != seq
                        or event['prev_sha256'] != previous):
                    raise ValueError('Invalid autonomy journal chain')
                state = apply(state, event)
                previous = sha256(line).hexdigest()
                snapshots.append(dict(seq=seq, journal_sha256=previous, state=state))
            if not snapshots:
                raise ValueError('Missing autonomy initialization event')
            try:
                saved = decode(self.read('state.json'))
            except FileNotFoundError:
                saved = None
            if saved is None or encode(saved) != encode(snapshots[-1]):
                if not allow_stale:
                    raise ValueError('Autonomy state is stale; explicit recovery required')
                if saved is None and len(snapshots) != 1:
                    raise ValueError('Missing autonomy state; cannot verify recovery checkpoint')
                if saved is not None and not any(encode(saved) == encode(s) for s in snapshots):
                    raise ValueError('Damaged autonomy state; cannot recover unverifiable counters')
            return snapshots[-1], saved is None or encode(saved) != encode(snapshots[-1])
        except (KeyError, TypeError, UnicodeError, OverflowError) as exc:
            raise ValueError('Damaged autonomy records; preserve files for inspection') from exc

    def commit(self, snapshot, op, at, data, apply):
        self.verify_lock()
        event = dict(seq=snapshot['seq'] + 1 if snapshot else 1,
                     prev_sha256=snapshot['journal_sha256'] if snapshot else None,
                     op=op, at=at, data=data)
        state = apply(snapshot['state'] if snapshot else None, event)
        raw = encode(event)
        self.append(raw)  # Durable event first: never roll an action back on failure.
        result = dict(seq=event['seq'], journal_sha256=sha256(raw).hexdigest(), state=state)
        self.publish(result)
        return result


@contextmanager
def locked(cfg, name, *, write=False, initialize=False):
    root = study.locate(cfg, name)
    rootfd = directory(root)
    fd = lockfd = None
    try:
        # Existing study only; do not create or modify study.md / attempts.
        attempts = os.open('attempts', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd)
        os.close(attempts)
        if initialize:
            os.mkdir('autonomy', 0o700, dir_fd=rootfd)
            os.fsync(rootfd)
        fd = os.open('autonomy', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd)
        store = Store(fd)
        if initialize:
            store.exclusive('store.lock', b'Persistent local operation mutex\n')
            store.exclusive('journal.jsonl', b'')
        lockfd = store.open('store.lock', os.O_RDONLY)
        fcntl.flock(lockfd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        store.lockfd = lockfd
        store.verify_lock()
        yield store
    finally:
        if lockfd is not None:
            os.close(lockfd)
        if fd is not None:
            os.close(fd)
        os.close(rootfd)
