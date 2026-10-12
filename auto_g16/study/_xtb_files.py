"""Session-owned local evidence, using only retained business parent descriptors."""
from contextlib import contextmanager
import os
import re
import stat
from uuid import UUID, uuid5

from ._model import StudyError, decode, digest, encode, plain, require

_CAP = 2 << 20
_DIRECTORIES = {
    'operations-root': ('operations', 'xtb'),
    'prepared-root': ('prepared', 'xtb'),
    'publisher-root': ('reviews', 'xtb-publisher'),
    'collections-root': ('reviews', 'xtb-collection'),
    'operation-preparation': ('operations-root', 'preparation'),
    'operation-authorization': ('operations-root', 'authorization'),
    'operation-submission': ('operations-root', 'submission'),
}
_FILES = {
    'operations': set(), 'prepared': set(), 'public': set(),
    'reviews': {'xtb-preparation.json', 'xtb-preparation-evidence'},
    'operations-root': set(),
    'prepared-root': {'input.xyz', 'xtb.pbs', 'snapshot.json', 'prepared.json'},
    'publisher-root': {'v31-publisher-pilot-deployment.json', 'reviewed-scope.json'},
    'collections-root': set(),
    'operation-preparation': {'intent.json', 'receipt.json',
        *(f'step-{i:02d}-{kind}.json' for i in range(1, 5) for kind in ('entered', 'capture'))},
    'operation-authorization': {'intent.json', 'receipt.json'},
    'operation-submission': {'intent.json', 'receipt.json'},
}


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


class _OwnedDescriptors:
    """Registered before acquiring the first FD, including partial constructors."""
    def __init__(self, session, kind, parent, name):
        self._study_session, self.parent, self.name = session, parent, name
        self.fds = []
        session.own(self, kind)


class _BusinessDirectory:
    def __init__(self, session, parent, role, *, name=None, resource=None, node=None):
        self.session, self.parent = session, parent
        self.role = role
        self.name, self.resource, self.node = name, resource, node
        self.seen = {}
        self.path = str(parent.path) if name is None else parent.path + '/' + name
        self.chain = tuple(tuple(pair) for pair in parent.chain)
        if node is not None:
            self.chain += (node,)

    def _allowed(self, name):
        if self.role == 'artifacts':
            from ._fresh_model import identities
            return name == identities(self.session.scope.request)['stages']['xtb']['attempt_id']
        names = set(_FILES[self.role])
        for role, (parent, child) in _DIRECTORIES.items():
            if parent == self.role:
                names.update((child, '.xtb-dir-' + role + '-intent.json',
                              '.xtb-dir-' + role + '-receipt.json'))
        return name in names or (self.role == 'publisher-root'
                                 and re.fullmatch('[0-9a-f]{64}', name) is not None)

    @property
    def fd(self):
        self.session.assert_identity()
        self._check_physical()
        return self._fd()

    def _fd(self):
        return self.parent.fd if self.resource is None else self.resource.fds[-1]

    def check(self):
        self.session.assert_current()
        self._check_physical()

    def _check_physical(self):
        if type(self.parent) is _BusinessDirectory:
            self.parent._check_physical()
        else:
            self.parent.check()
        if self.resource is not None:
            require(len(self.resource.fds) == 1, 'runtime-unresolved')
            actual = os.fstat(self.resource.fds[0])
            named = os.stat(self.name, dir_fd=self.parent._fd(), follow_symlinks=False)
            require(stat.S_ISDIR(actual.st_mode) and stat.S_ISDIR(named.st_mode)
                    and (actual.st_dev, actual.st_ino) == self.node
                    and (named.st_dev, named.st_ino) == self.node, 'runtime-unresolved')
        for name, (signature, _) in self.seen.items():
            require(_signature(os.stat(name, dir_fd=self._fd(), follow_symlinks=False)) == signature,
                    'runtime-unresolved')
        require(all(self._allowed(name) for name in os.listdir(self._fd())), 'runtime-unresolved')

    def binding(self):
        self.check()
        return dict(path=self.path, parent_chain=plain(self.chain[:-1]),
                    file_identity=plain(self.chain[-1]))

    def names(self):
        return set(os.listdir(self.fd))

    @contextmanager
    def _file(self, name, flags):
        require(type(name) is str and name not in ('', '.', '..')
                and '/' not in name and '\x00' not in name and self._allowed(name))
        read_flags = os.O_RDONLY | os.O_NONBLOCK
        write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        require(type(flags) is int and flags in (read_flags, write_flags))
        if flags == write_flags:
            self.session.require_writer()
        self.check()
        owned = _OwnedDescriptors(self.session, 'business-file', self, name)
        original = None
        try:
            owned.fds.append(os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     0o600, dir_fd=self.fd))
            if flags == read_flags:
                self.session.guard_existing_file(owned, owned.fds[-1])
            yield owned.fds[-1]
        except BaseException as error:
            original = error
            raise
        finally:
            self.session.close_resource(owned, original=original)

    def read(self, name, cap=_CAP):
        require(type(cap) is int and 0 < cap <= 16 << 20)
        with self._file(name, os.O_RDONLY | os.O_NONBLOCK) as fd:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 < before.st_size <= cap, 'runtime-unresolved')
            blocks, size = [], 0
            while size <= cap:
                block = os.read(fd, min(1048576, cap + 1 - size))
                if not block:
                    break
                blocks.append(block)
                size += len(block)
            raw = b''.join(blocks)
            named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            signature = _signature(before)
            require(size == before.st_size and signature == _signature(os.fstat(fd))
                    == _signature(named), 'runtime-unresolved')
            require(name not in self.seen or self.seen[name] == (signature, raw),
                    'runtime-unresolved')
            self.seen[name] = (signature, raw)
            binding = dict(path=self.path + '/' + name, parent_chain=plain(self.chain),
                file_identity=[before.st_dev, before.st_ino], sha256=digest(raw), size_bytes=size)
            self.check()
            return raw, binding

    def publish(self, name, raw, *, cap=_CAP):
        self.session.require_writer()
        require(type(raw) is bytes and 0 < len(raw) <= cap <= 16 << 20)
        require(name not in self.names(), 'runtime-unresolved')
        with self._file(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL) as fd:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1)
            view = memoryview(raw)
            while view:
                count = os.write(fd, view)
                require(count > 0)
                view = view[count:]
            os.fsync(fd)
            created_signature = _signature(os.fstat(fd))
            require(created_signature == _signature(os.stat(name, dir_fd=self.fd,
                                                            follow_symlinks=False)),
                    'runtime-unresolved')
        os.fsync(self.fd)
        readback, binding = self.read(name, cap)
        require(readback == raw, 'runtime-unresolved')
        require(self.seen[name][0] == created_signature, 'runtime-unresolved')
        return binding


def root(session, role):
    session.assert_current()
    require(role in ('operations', 'prepared', 'artifacts', 'reviews', 'public'))
    cache = session._business_directories
    if role not in cache:
        cache[role] = _BusinessDirectory(session, session.context.directories[role], role)
    cache[role].check()
    return cache[role]


def directory(session, role, *, create=False):
    """A fixed role resolves its parent; no caller-selected filesystem path."""
    session.assert_current()
    require(role in _DIRECTORIES)
    cache = session._business_directories
    if role in cache:
        cache[role].check()
        return cache[role]
    parent_role, name = _DIRECTORIES[role]
    parent = (directory(session, parent_role, create=create) if parent_role in _DIRECTORIES
              else root(session, parent_role))
    intent_name = '.xtb-dir-' + role + '-intent.json'
    receipt_name = '.xtb-dir-' + role + '-receipt.json'
    registration = session.scope.registration_ref['registration']
    operation = str(uuid5(UUID(registration['study_id']), 'auto-g16-study-xtb-directory/1:' + role))
    intent = dict(schema='auto-g16-study-xtb-directory-intent/1', operation_id=operation,
                  name=name, parent_binding=parent.binding())
    names = parent.names()
    if receipt_name in names:
        require(intent_name in names and name in names, 'runtime-unresolved')
        original, _ = parent.read(intent_name)
        require(original == encode(intent), 'runtime-unresolved')
        raw, _ = parent.read(receipt_name)
        receipt = decode(raw, cap=_CAP)
        require(type(receipt) is dict and set(receipt) == {'schema', 'intent_sha256', 'binding'}
                and receipt['schema'] == 'auto-g16-study-xtb-directory-receipt/1'
                and receipt['intent_sha256'] == digest(original) and raw == encode(receipt),
                'runtime-unresolved')
    else:
        # An unacknowledged mkdir is never replayed or adopted, even when empty.
        require(intent_name not in names and name not in names, 'runtime-unresolved')
        require(create, 'not-found')
        session.require_writer()
        parent.publish(intent_name, encode(intent))
        parent.check()
        os.mkdir(name, 0o700, dir_fd=parent.fd)
        os.fsync(parent.fd)
        receipt = None
    owned = _OwnedDescriptors(session, 'business-directory', parent, name)
    try:
        owned.fds.append(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 dir_fd=parent.fd))
        info = os.fstat(owned.fds[-1])
        child = _BusinessDirectory(session, parent, role, name=name, resource=owned,
                                   node=(info.st_dev, info.st_ino))
        child.check()
        observed = child.binding()
        if receipt is None:
            require(not child.names(), 'runtime-unresolved')
            receipt = dict(schema='auto-g16-study-xtb-directory-receipt/1',
                           intent_sha256=digest(encode(intent)), binding=observed)
            parent.publish(receipt_name, encode(receipt))
        else:
            require(receipt['binding'] == observed, 'runtime-unresolved')
        cache[role] = child
        return child
    except BaseException as error:
        session.close_resource(owned, original=error)
        raise
