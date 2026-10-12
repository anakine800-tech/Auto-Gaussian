"""Capture CLI authorization bytes before opening any registered native store."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import os
import stat
import sys
import threading

from . import _installation, _registered_runtime as registered
from ._model import binding, decode, digest, encode, plain, require

_ENTERED = False


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


class _CaptureParent(registered._Directory):
    def read(self, name, cap):
        with self._file(name, os.O_RDONLY | os.O_NONBLOCK) as fd:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                    and 0 < before.st_size <= cap, 'invalid-request')
            chunks, size = [], 0
            while size <= cap:
                block = os.read(fd, min(1048576, cap + 1 - size))
                if not block:
                    break
                chunks.append(block)
                size += len(block)
            raw = b''.join(chunks)
            named = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            require(size == before.st_size and _signature(before) == _signature(os.fstat(fd))
                    == _signature(named), 'runtime-unresolved')
            observed = (_signature(before), raw)
            require(name not in self.seen or self.seen[name] == observed, 'runtime-unresolved')
            self.seen[name] = observed
            self.check()
            return raw, [before.st_dev, before.st_ino]

    def __exit__(self, kind, original, traceback):
        # Generic Directory exit rereads seen files. That is forbidden here:
        # registered teardown may have quarantined still-open SQLite owners.
        failure = original
        try:
            self.check()
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note('captured parent validation failed: ' + type(error).__name__)
        try:
            self.close()
        except BaseException as error:
            if failure is None:
                failure = error
            else:
                failure.add_note('captured parent close unresolved: ' + type(error).__name__)
        if original is None and failure is not None:
            raise failure


class _Captured:
    def __init__(self, installation, roots, files):
        self.installation, self.roots, self.files = installation, roots, files
        self.pid, self.thread = os.getpid(), threading.get_ident()
        self.closed = False

    def assert_current(self, scope=None):
        require(not self.closed and (self.pid, self.thread) == (os.getpid(), threading.get_ident()),
                'runtime-unresolved')
        nodes = set()
        if scope is not None:
            require(plain(scope.registration_ref['registration']['installation']) == self.installation,
                    'runtime-source-mismatch')
            nodes = {tuple(store.assert_existing_binding()['file_identity']) for store in scope.stores.values()}
        for directory, name, raw, file_binding in self.files:
            directory.check()  # Only already-held parent descriptors, no file reopen.
            current = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
            require(stat.S_ISREG(current.st_mode) and directory.seen[name] == (_signature(current), raw)
                    and (current.st_dev, current.st_ino) not in nodes, 'runtime-unresolved')
            require(all(os.path.commonpath((file_binding['path'], root['path'])) != root['path']
                        and list(root['file_identity']) not in directory.chain for root in self.roots),
                    'invalid-request')

    def content(self, expected):
        self.assert_current()
        values = [raw for _, _, raw, observed in self.files[1:] if observed == expected]
        require(values and all(raw == values[0] for raw in values), 'invalid-request')
        return values[0]

    @property
    def raw(self):
        self.assert_current()
        return self.files[0][2]

    @property
    def evidence_raw(self):
        self.assert_current()
        return self.files[1][2]


@contextmanager
def _capture(request_path, request_sha256, kind):
    """First phase of one actual -m CLI process, never a nested callable import."""
    global _ENTERED
    main = sys.modules.get('__main__')
    require(not _ENTERED and getattr(getattr(main, '__spec__', None), 'name', None)
            == 'auto_g16.study.__main__' and threading.active_count() == 1
            and registered._ACTIVE_SCOPE.get() is None, 'invalid-request')
    require(kind in ('preparation', 'authorization'), 'invalid-request')
    _ENTERED = True
    capture = None
    with ExitStack() as parents:
        # No native store is open anywhere in this fixed CLI call graph yet.
        with _installation.load_installed_runtime() as facts:
            roots = [plain(facts.bundle_binding), *(plain(v) for v in facts.roots.values())]
            files = []
            def read(path, cap):
                _installation._path(path, absolute=True)
                require(all(os.path.commonpath((path, root['path'])) != root['path'] for root in roots), 'invalid-request')
                parent = parents.enter_context(_CaptureParent(str(Path(path).parent), lock=False))
                require(all(root['file_identity'] not in parent.chain for root in roots), 'invalid-request')
                name = Path(path).name
                raw, physical = parent.read(name, cap)
                file_binding = dict(path=path, parent_chain=plain(parent.chain),
                    file_identity=physical, sha256=digest(raw), size_bytes=len(raw))
                files.append((parent, name, raw, file_binding))
                return raw, file_binding
            raw, _ = read(request_path, 2 << 20)
            _installation._hash(request_sha256)
            require(digest(raw) == request_sha256, 'invalid-request')
            packet = decode(raw, 'invalid-request', 2 << 20)
            require(type(packet) is dict and raw == encode(packet), 'invalid-request')
            if kind == 'preparation':
                require(packet.get('schema') == 'auto-g16-study-xtb-preparation-decision/1', 'invalid-request')
                references = [plain(packet.get('evidence'))]
            else:
                require(packet.get('schema') == 'auto-g16-study-xtb-authorization/1', 'invalid-request')
                decisions = [packet.get(role) for role in ('scientific', 'batch', 'operational')]
                publisher = packet.get('publisher')
                require(all(type(value) is dict for value in decisions) and type(publisher) is dict,
                        'invalid-request')
                evidence = publisher.get('evidence')
                require(type(evidence) is list and 1 <= len(evidence) <= 256, 'invalid-request')
                references = [value.get('evidence') for value in decisions] + evidence
            seen = []
            for expected in references:
                binding(expected, 'invalid-request')
                if expected in seen:
                    continue
                _, observed = read(expected['path'], 16 << 20)
                require(observed == expected, 'invalid-request')
                seen.append(expected)
            capture = _Captured(registered._installation_ref(facts), roots, files)
            capture.assert_current()
        original = None
        try:
            yield capture
        except BaseException as error:
            original = error
            raise
        finally:
            try:
                capture.assert_current()
            except BaseException as error:
                if original is None:
                    raise
                original.add_note('captured input changed: ' + type(error).__name__)
            finally:
                capture.closed = True


@contextmanager
def preparation(request_path, request_sha256):
    with _capture(request_path, request_sha256, 'preparation') as captured:
        yield captured


@contextmanager
def authorization(request_path, request_sha256):
    with _capture(request_path, request_sha256, 'authorization') as captured:
        yield captured
