"""Read-only installation facts. Self-consistency never grants execution authority."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
from types import MappingProxyType


class InstallationFactsError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(value, code='invalid-installation'):
    if not value:
        raise InstallationFactsError(code)


def _path(value, *, absolute):
    _require(type(value) is str and 0 < len(value.encode()) <= 4096, 'invalid-input')
    _require(value.startswith('/') == absolute and value != '/' and not value.endswith('/')
             and not any(c in value for c in '\x00\r\n\\')
             and all(p not in ('', '.', '..', '.git') for p in value.split('/')[int(absolute):]), 'invalid-input')
    return value


def _closed(value, keys):
    _require(type(value) is dict and set(value) == set(keys))
    return value


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result)
            result[key] = value
        return result
    def depth(value, n=0):
        _require(n <= 16)
        for v in value.values() if type(value) is dict else value if type(value) is list else ():
            depth(v, n + 1)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: _require(False))
    depth(value)
    _require(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                        allow_nan=False).encode() == raw)
    return value


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if type(value) is list:
        return tuple(_freeze(v) for v in value)
    return value


def _hash(value, length=64):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value))


def _physical(value):
    _require(type(value) is list and len(value) == 2 and all(type(v) is int for v in value)
             and value[0] >= 0 and value[1] >= 1)


def _validate_binding(value, *, file=False):
    _closed(value, {'path', 'parent_chain', 'file_identity'} | ({'sha256', 'size_bytes'} if file else set()))
    _path(value['path'], absolute=True)
    _require(type(value['parent_chain']) is list)
    for item in [*value['parent_chain'], value['file_identity']]:
        _physical(item)
    _require(len(value['parent_chain']) == len(Path(value['path']).parts) - int(file))
    if file:
        _hash(value['sha256'])
        _require(type(value['size_bytes']) is int and value['size_bytes'] >= 1)
    else:
        _require(value['file_identity'] == value['parent_chain'][-1])


def _signature(info, file):
    _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 if file else stat.S_ISDIR(info.st_mode), 'identity-drift')
    base = (info.st_dev, info.st_ino)
    return (*base, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_nlink) if file else base


class _Pins:
    def __init__(self):
        self.nodes = {}
        self.pid = os.getpid()

    def open(self, path, *, file=False):
        _path(path, absolute=True)
        if path in self.nodes:
            fd, kind, before = self.nodes[path]
            _require(kind == file, 'identity-drift')
            self.check_one(path)
            return fd
        if '/' not in self.nodes:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                self.nodes['/'] = (fd, False, _signature(os.fstat(fd), False))
            except BaseException as error:
                try:
                    os.close(fd)
                except OSError:
                    error.add_note('invalid-installation')
                raise
        parent = str(Path(path).parent)
        parent_fd = self.nodes['/'][0] if parent == '/' else self.open(parent)
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | (os.O_NONBLOCK if file else os.O_DIRECTORY)
        fd = os.open(Path(path).name, flags, dir_fd=parent_fd)
        try:
            self.nodes[path] = (fd, file, _signature(os.fstat(fd), file))
            self.check_one(path)
        except BaseException as error:
            if path in self.nodes:
                self.nodes.pop(path)
            try:
                os.close(fd)
            except OSError:
                error.add_note('invalid-installation')
            raise
        return fd

    def check_one(self, path):
        _require(os.getpid() == self.pid, 'forked-process')
        fd, file, before = self.nodes[path]
        try:
            named = os.stat('/', follow_symlinks=False) if path == '/' else os.stat(
                Path(path).name, dir_fd=self.nodes[str(Path(path).parent)][0], follow_symlinks=False)
            _require(_signature(named, file) == before == _signature(os.fstat(fd), file), 'identity-drift')
        except OSError:
            raise InstallationFactsError('identity-drift') from None

    def check(self):
        for path in self.nodes:
            self.check_one(path)

    def read(self, path, cap, *, empty=False, collect=True):
        fd = self.open(path, file=True)
        for parent in reversed(Path(path).parents):
            self.check_one(str(parent))
        self.check_one(path)
        size = self.nodes[path][2][2]
        _require(int(not empty) <= size <= cap)
        sha, blob = sha256(), sha1(b'blob ' + str(size).encode() + b'\0')
        raw, total = [], 0
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            part = os.read(fd, min(1048576, size + 1 - total))
            if not part:
                break
            total += len(part)
            _require(total <= size, 'identity-drift')
            sha.update(part); blob.update(part)
            if collect:
                raw.append(part)
        self.check_one(path)
        _require(total == size, 'identity-drift')
        return b''.join(raw), sha.hexdigest(), blob.digest(), size

    def binding(self, path, *, file=False, digest=None, size=None):
        self.open(path, file=file)
        ancestors = list(reversed(Path(path).parents)) + ([] if file else [Path(path)])
        value = dict(path=path, parent_chain=[list(self.nodes[str(p)][2][:2]) for p in ancestors],
                     file_identity=list(self.nodes[path][2][:2]))
        if file:
            value.update(sha256=digest, size_bytes=size)
        return value

    def close(self, original=None):
        failed = False
        nodes = tuple(self.nodes.values())
        self.nodes.clear()  # An ambiguous close is never retried against a reused FD.
        for fd, _kind, _version in reversed(nodes):
            try:
                os.close(fd)
            except OSError:
                failed = True
        if failed:
            if original is not None:
                original.add_note('invalid-installation')
            else:
                raise InstallationFactsError('invalid-installation')
        return not failed


@dataclass(frozen=True, slots=True)
class InstallationFacts:
    state: str
    source_commit: str
    source_tree: str
    source_manifest_sha256: str
    locator_sha256: str
    readback_binding: object
    bundle_binding: object
    roots: object
    profile_binding: object
    qualification_binding: object
    loaded_path_consistency: str
    executed_code_attested: bool = False
    qualification_state: str = 'not-assessed'
    execution_enabled: bool = False


_FILES = {'study-runtime.json': 2 << 20, 'study-runtime-readback.json': 2 << 20,
          'source-manifest.json': 16 << 20, 'git-commit.bin': 2 << 20,
          'profile.json': 1 << 20, 'qualification.json': 1 << 20}
_REQUIRED = {'auto_g16/__init__.py', 'auto_g16/study/__init__.py', 'auto_g16/study/_installation.py',
             'scripts/run_v31_publisher_pilot.py', 'pyproject.toml'}


class _SourceTree:
    """Complete source validation shared by reader and exclusive local publisher."""
    def __init__(self, pins, source, manifest_raw, commit):
        self.pins, self.source = pins, source
        self.manifest = _closed(_json(manifest_raw), {'schema', 'source_commit', 'source_tree', 'entries'})
        _require(self.manifest['schema'] == 'auto-g16-study-source-manifest/1')
        for key in ('source_commit', 'source_tree'):
            _hash(self.manifest[key], 40)
        self._source_entries()
        self._inventory()
        tree = self._git_tree()
        _require(tree.hex() == self.manifest['source_tree'], 'source-mismatch')
        _require(sha1(b'commit ' + str(len(commit)).encode() + b'\0' + commit).hexdigest()
                 == self.manifest['source_commit'], 'source-mismatch')
        _require(b'\n\n' in commit)
        headers = commit.split(b'\n\n', 1)[0].split(b'\n')
        _require(headers[0] == b'tree ' + self.manifest['source_tree'].encode()
                 and sum(line.startswith(b'tree ') for line in headers) == 1, 'source-mismatch')

    def _source_entries(self):
        entries = self.manifest['entries']
        _require(type(entries) is list and 1 <= len(entries) <= 20000)
        self.entries, self.dirs = {}, {'': set()}
        paths, total = [], 0
        for entry in entries:
            _closed(entry, {'path', 'mode', 'size_bytes', 'sha256'})
            path = _path(entry['path'], absolute=False)
            parts = path.split('/')
            _require(len(parts) <= 64 and '__pycache__' not in parts)
            _require(type(entry['mode']) is str and entry['mode'] in ('100644', '100755'))
            _hash(entry['sha256'])
            _require(type(entry['size_bytes']) is int and 0 <= entry['size_bytes'] <= 128 << 20)
            total += entry['size_bytes']
            _require(total <= 1 << 30)
            paths.append(path)
            self.entries[path] = entry
            for n, part in enumerate(parts):
                parent = '/'.join(parts[:n])
                self.dirs.setdefault(parent, set()).add(part)
        _require(paths == sorted(set(paths), key=lambda x: x.encode()))
        _require(_REQUIRED <= set(paths) and not (set(paths) & set(self.dirs)))

    def _cache(self, parent, path):
        fd = self.pins.open(path)
        names = os.listdir(fd)
        tag = sys.implementation.cache_tag
        _require(type(tag) is str and bool(tag))
        allowed = set()
        for name in self.dirs[parent]:
            relative = (parent + '/' if parent else '') + name
            if name.endswith('.py') and relative in self.entries:
                allowed.update(name[:-3] + '.' + tag + suffix for suffix in ('.pyc', '.opt-1.pyc', '.opt-2.pyc'))
        _require(set(names) <= allowed)
        for name in names:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 16 << 20)

    def _inventory(self):
        for relative, expected in self.dirs.items():
            path = self.source + ('/' + relative if relative else '')
            actual = set(os.listdir(self.pins.open(path)))
            _require(actual - {'__pycache__'} == expected)
            if '__pycache__' in actual:
                self._cache(relative, path + '/__pycache__')

    def _git_tree(self):
        objects, physical = {}, set()
        for relative, entry in self.entries.items():
            path = self.source + '/' + relative
            _, digest, blob, size = self.pins.read(path, 128 << 20, empty=True, collect=False)
            node = self.pins.nodes[path][2]
            _require(node[:2] not in physical)
            physical.add(node[:2])
            mode = node[5]
            _require(not mode & 0o7000 and mode & 0o111 == (0o111 if entry['mode'] == '100755' else 0))
            _require((size, digest) == (entry['size_bytes'], entry['sha256']), 'source-mismatch')
            objects[relative] = (entry['mode'], blob)
        for directory in sorted(self.dirs, key=lambda p: p.count('/') + bool(p), reverse=True):
            children = []
            for name in self.dirs[directory]:
                path = (directory + '/' if directory else '') + name
                mode, oid = objects[path]
                children.append((name.encode() + (b'/' if mode == '40000' else b''),
                                 mode.encode() + b' ' + name.encode() + b'\0' + oid))
            payload = b''.join(value for _key, value in sorted(children))
            objects[directory] = ('40000', sha1(b'tree ' + str(len(payload)).encode() + b'\0' + payload).digest())
        return objects[''][1]

    def check(self):
        self.pins.check()
        self._inventory()
        _require(self._git_tree().hex() == self.manifest["source_tree"], "source-mismatch")
        self.pins.check()


class _Inspection:
    def __init__(self, bundle, *, loaded):
        self.pins = _Pins()
        self._held_verified = False
        self._held_failed = False
        try:
            self.bundle = _path(bundle, absolute=True)
            self.source, self.installation = bundle + '/source', bundle + '/installation'
            self.loaded = loaded
            for path in (bundle, self.source, self.installation):
                self.pins.open(path)
            self._layout()
            raw, bindings = {}, {}
            for name, cap in _FILES.items():
                path = self.installation + '/' + name
                data, digest, _, size = self.pins.read(path, cap)
                raw[name] = data
                bindings[name] = self.pins.binding(path, file=True, digest=digest, size=size)
            self.source_tree = _SourceTree(self.pins, self.source, raw["source-manifest.json"], raw["git-commit.bin"])
            self.manifest = self.source_tree.manifest
            locator = _closed(_json(raw['study-runtime.json']), {'schema', 'source_commit', 'source_tree',
                'source_manifest', 'commit_object', 'profile', 'qualification', 'roots'})
            _require(locator['schema'] == 'auto-g16-study-installation-locator/1')
            for key, name in (('source_manifest', 'source-manifest.json'), ('commit_object', 'git-commit.bin'),
                              ('profile', 'profile.json'), ('qualification', 'qualification.json')):
                _validate_binding(locator[key], file=True)
                _require(locator[key] == bindings[name], 'identity-drift')
            roots = _closed(locator['roots'], {'creation', 'runtime', 'registry'})
            root_paths = [bundle]
            root_ids = [self.pins.nodes[bundle][2]]
            for value in roots.values():
                _validate_binding(value)
                path = value['path']
                _require(all(os.path.commonpath((path, other)) not in (path, other) for other in root_paths))
                observed = self.pins.binding(path)
                _require(value == observed and tuple(value['file_identity']) not in root_ids, 'identity-drift')
                root_paths.append(path); root_ids.append(tuple(value['file_identity']))
            readback = _closed(_json(raw['study-runtime-readback.json']), {'schema', 'bundle', 'source',
                'installation', 'locator', 'source_commit', 'source_tree'})
            _require(readback['schema'] == 'auto-g16-study-installation-readback/1')
            for key, path in (('bundle', bundle), ('source', self.source), ('installation', self.installation)):
                _validate_binding(readback[key])
                _require(readback[key] == self.pins.binding(path), 'identity-drift')
            _validate_binding(readback['locator'], file=True)
            _require(readback['locator'] == bindings['study-runtime.json'], 'identity-drift')
            _require(all(v[k] == self.manifest[k] for v in (locator, readback)
                         for k in ('source_commit', 'source_tree')), 'source-mismatch')
            if loaded:
                self._origins()
            self.facts = InstallationFacts('mechanically-verified', self.manifest['source_commit'],
                self.manifest['source_tree'], bindings['source-manifest.json']['sha256'],
                bindings['study-runtime.json']['sha256'], _freeze(bindings['study-runtime-readback.json']),
                _freeze(readback['bundle']), _freeze(roots), _freeze(locator['profile']),
                _freeze(locator['qualification']), 'matched' if loaded else 'not-assessed')
            self.check()
        except BaseException as error:
            self.pins.close(error)
            raise

    def _layout(self):
        _require(set(os.listdir(self.pins.nodes[self.bundle][0])) == {'source', 'installation'})
        names = set(os.listdir(self.pins.nodes[self.installation][0]))
        _require(set(_FILES) <= names, 'installation-unavailable')
        _require(names == set(_FILES))

    def _origins(self):
        for name, relative in (('auto_g16', 'auto_g16/__init__.py'),
                               ('auto_g16.study', 'auto_g16/study/__init__.py'),
                               (__name__, 'auto_g16/study/_installation.py')):
            module = sys.modules.get(name)
            expected = self.source + '/' + relative
            _require(module is not None and module.__file__ == expected
                     and module.__spec__ is not None and module.__spec__.origin == expected, 'identity-drift')

    def check(self):
        _require(not self._held_failed, 'identity-drift')
        try:
            self.pins.check()
            self._layout()
            self.source_tree.check()
            if self.loaded:
                self._origins()
            self.pins.check()
            self._held_verified = True
        except BaseException:
            self._held_failed = True
            raise

    def assert_held_current(self):
        """Internal checkpoints retain the first full hash and every open file signature."""
        _require(self._held_verified and not self._held_failed, 'identity-drift')
        try:
            self.pins.check()
            self._layout()
            self.source_tree._inventory()
            if self.loaded:
                self._origins()
            self.pins.check()
        except BaseException:
            self._held_failed = True
            raise


def _mapped(error):
    if isinstance(error, InstallationFactsError):
        return error
    if isinstance(error, FileNotFoundError):
        return InstallationFactsError('installation-unavailable')
    return InstallationFactsError('invalid-installation')


def _inspect(bundle, loaded):
    try:
        return _Inspection(bundle, loaded=loaded)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise _mapped(error) from None


def _exit_check(inspection):
    try:
        inspection.check()
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise _mapped(error) from None


@contextmanager
def inspect_bundle(bundle_directory):
    inspection = _inspect(bundle_directory, False)
    original = None
    try:
        try:
            yield inspection.facts
        except BaseException as error:
            try:
                _exit_check(inspection)
            except InstallationFactsError as drift:
                error.add_note(drift.code)
            raise
        else:
            _exit_check(inspection)
    except BaseException as error:
        original = error
        raise
    finally:
        inspection.pins.close(original)


_PID, _LOCK, _FACTS, _PIN_STATE, _INVALID = os.getpid(), threading.Lock(), None, None, False


@contextmanager
def load_installed_runtime():
    global _FACTS, _PIN_STATE, _INVALID
    _require(os.getpid() == _PID, 'forked-process')
    _require(_LOCK.acquire(blocking=False), 'busy')
    inspection, original, publish = None, None, False
    try:
        _require(not _INVALID, 'installation-invalidated')
        try:
            module = _path(__file__, absolute=True)
            suffix = '/source/auto_g16/study/_installation.py'
            _require(module.endswith(suffix), 'installation-unavailable')
            inspection = _inspect(module[:-len(suffix)], True)
            pin_state = tuple(sorted((p, kind, version) for p, (_fd, kind, version) in inspection.pins.nodes.items()
                                     if '__pycache__' not in Path(p).parts))
            _require(_FACTS is None or (inspection.facts == _FACTS and pin_state == _PIN_STATE), 'identity-drift')
        except InstallationFactsError:
            if _FACTS is not None:
                _INVALID = True
            raise
        candidate = _FACTS if _FACTS is not None else inspection.facts
        try:
            yield candidate
        except BaseException as error:
            try:
                _exit_check(inspection)
            except InstallationFactsError as drift:
                _INVALID = True
                error.add_note(drift.code)
            raise
        else:
            try:
                _exit_check(inspection)
            except InstallationFactsError:
                _INVALID = True
                raise
            publish = _FACTS is None
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            if inspection is not None and not inspection.pins.close(original):
                _INVALID = True
            if publish and not _INVALID and original is None:
                _FACTS = candidate
                _PIN_STATE = pin_state
        except InstallationFactsError:
            _INVALID = True
            raise
        finally:
            _LOCK.release()
