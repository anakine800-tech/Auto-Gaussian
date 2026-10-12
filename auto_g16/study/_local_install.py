"""Exclusive local package publication; no qualification or scientific execution."""
import fcntl
import os
from pathlib import Path
from collections.abc import Mapping
from hashlib import sha256

from . import _installation as facts
from ._model import StudyError, encode


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _summary(value):
    return {key: _plain(getattr(value, key)) for key in (
        'bundle_binding', 'readback_binding', 'source_commit', 'source_tree',
        'source_manifest_sha256', 'locator_sha256')}


def _disjoint(paths):
    facts._require(all(os.path.commonpath((a, b)) not in (a, b)
                       for i, a in enumerate(paths) for b in paths[i + 1:]), 'invalid-request')


def _outside(path, directories):
    facts._require(all(os.path.commonpath((path, d)) != d for d in directories), 'invalid-request')


class _Writer(facts._Pins):
    def __init__(self):
        super().__init__()
        self.mutable = set()

    def check_one(self, path):
        if path not in self.mutable:
            return super().check_one(path)
        facts._require(os.getpid() == self.pid, 'forked-process')
        fd, file, before = self.nodes[path]
        named = os.stat(Path(path).name, dir_fd=self.nodes[str(Path(path).parent)][0], follow_symlinks=False)
        facts._require(facts._signature(named, True)[:2] == before[:2]
                       == facts._signature(os.fstat(fd), True)[:2], 'identity-drift')

    def chain(self, path):
        for p in reversed(Path(path).parents):
            self.check_one(str(p))
        self.check_one(path)

    def mkdir(self, path):
        parent = str(Path(path).parent)
        self.chain(parent)
        os.mkdir(Path(path).name, 0o700, dir_fd=self.nodes[parent][0])
        self.open(path)
        self.chain(path)
        os.fsync(self.nodes[parent][0])

    def publish(self, path, raw, mode=0o600):
        parent = str(Path(path).parent)
        self.chain(parent)
        fd = os.open(Path(path).name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.nodes[parent][0])
        try:
            self.nodes[path] = (fd, True, facts._signature(os.fstat(fd), True))
        except BaseException as error:
            try:
                os.close(fd)
            except OSError:
                error.add_note('installation-publication-failed')
            raise
        self.mutable.add(path)
        offset = 0
        while offset < len(raw):
            self.chain(path)
            count = os.write(fd, memoryview(raw)[offset:offset + 1048576])
            facts._require(type(count) is int and 0 < count <= min(1048576, len(raw) - offset),
                           'installation-publication-failed')
            offset += count
        self.chain(path)
        os.fchmod(fd, mode)
        os.fsync(fd)
        os.fsync(self.nodes[parent][0])
        self.chain(path)
        self.nodes[path] = (fd, True, facts._signature(os.fstat(fd), True))
        self.mutable.remove(path)  # Freeze BEFORE the first readback.
        saved, digest, _, size = self.read(path, max(1, len(raw)), empty=True)
        facts._require(saved == raw, 'installation-publication-failed')
        return self.binding(path, file=True, digest=digest, size=size)


def _request(pins, path, digest):
    try:
        facts._path(path, absolute=True)
        facts._hash(digest)
        raw, observed, _, _ = pins.read(path, 2 << 20)
        facts._require(observed == digest)
        value = facts._closed(facts._json(raw), {'schema', 'destination', 'source_directory',
            'source_manifest', 'commit_object', 'profile', 'qualification', 'roots'})
        facts._require(value['schema'] == 'auto-g16-study-local-install-request/1')
        target = facts._closed(value['destination'], {'path', 'parent_chain'})
        facts._path(target['path'], absolute=True)
        facts._require(type(target['parent_chain']) is list and
                       len(target['parent_chain']) == len(Path(target['path']).parents))
        for item in target['parent_chain']:
            facts._physical(item)
        for key in ('source_manifest', 'commit_object', 'profile', 'qualification'):
            facts._validate_binding(value[key], file=True)
        facts._validate_binding(value['source_directory'])
        facts._closed(value['roots'], {'creation', 'runtime', 'registry'})
        for binding in value['roots'].values():
            facts._validate_binding(binding)
        return value
    except FileNotFoundError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError, OSError):
        raise StudyError('invalid-request') from None


def _absent(writer, target):
    parent = str(Path(target).parent)
    try:
        os.stat(Path(target).name, dir_fd=writer.nodes[parent][0], follow_symlinks=False)
    except FileNotFoundError:
        return
    raise StudyError('destination-exists')


def _publish(pins, writer, path, digest):
    value = _request(pins, path, digest)
    target, source = value['destination']['path'], value['source_directory']['path']
    roots = value['roots']
    directories = [target, source, *(b['path'] for b in roots.values())]
    _disjoint(directories)
    _outside(path, directories)
    for key in ('source_manifest', 'commit_object', 'profile', 'qualification'):
        _outside(value[key]['path'], directories)
    ids = set()
    for binding in (value['source_directory'], *roots.values()):
        observed = pins.binding(binding['path'])
        physical = tuple(observed['file_identity'])
        facts._require(binding == observed and physical not in ids, 'identity-drift')
        ids.add(physical)
    parent = str(Path(target).parent)
    writer.open(parent)
    expected = [list(writer.nodes[str(p)][2][:2]) for p in reversed(Path(target).parents)]
    facts._require(value['destination']['parent_chain'] == expected, 'identity-drift')
    # Lexical disjointness is insufficient when an ancestor is another bound root.
    bound = (value['source_directory'], *roots.values())
    for i, b in enumerate(bound):
        physical = b['file_identity']
        facts._require(physical not in expected and all(physical not in other['parent_chain']
            for j, other in enumerate(bound) if j != i), 'invalid-request')
    _absent(writer, target)
    request_binding = pins.binding(path, file=True, digest=digest, size=pins.nodes[path][2][2])
    facts._require(all(root['file_identity'] not in request_binding['parent_chain'] for root in bound), 'invalid-request')
    raw = {}
    artifact_ids = {pins.nodes[path][2][:2]}
    names = (('source_manifest', 'source-manifest.json'), ('commit_object', 'git-commit.bin'),
             ('profile', 'profile.json'), ('qualification', 'qualification.json'))
    for key, name in names:
        b = value[key]
        data, hashed, _, size = pins.read(b['path'], facts._FILES[name])
        observed = pins.binding(b['path'], file=True, digest=hashed, size=size)
        physical = tuple(observed['file_identity'])
        facts._require(observed == b and physical not in artifact_ids, 'identity-drift')
        facts._require(all(root['file_identity'] not in observed['parent_chain'] for root in bound), 'invalid-request')
        artifact_ids.add(physical)
        raw[name] = data
    try:
        tree = facts._SourceTree(pins, source, raw['source-manifest.json'], raw['git-commit.bin'])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        raise facts._mapped(error) from None
    facts._require(not any(pins.nodes[source + '/' + rel][2][:2] in artifact_ids
                           for rel in tree.entries), 'identity-drift')
    try:
        fcntl.flock(writer.nodes[parent][0], fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise StudyError('busy') from None
    # The pinned parent FD holds this lock until every publication FD is closed.
    pins.check(); writer.check(); _absent(writer, target)
    writer.mkdir(target)
    writer.mkdir(target + '/source'); writer.mkdir(target + '/installation')
    for rel, entry in tree.entries.items():
        destination = target + '/source/' + rel
        for p in list(reversed(Path(destination).parents))[len(Path(target + '/source').parts):]:
            if str(p) not in writer.nodes:
                writer.mkdir(str(p))
        data, _, _, _ = pins.read(source + '/' + rel, 128 << 20, empty=True)
        writer.publish(destination, data, 0o711 if entry['mode'] == '100755' else 0o600)
        pins.check_one(source + '/' + rel)
    bindings = {}
    for key, name in names:
        bindings[key] = writer.publish(target + '/installation/' + name, raw[name])
    manifest = tree.manifest
    identities = {key: manifest[key] for key in ('source_commit', 'source_tree')}
    locator = dict(schema='auto-g16-study-installation-locator/1', roots=roots, **identities, **bindings)
    locator_binding = writer.publish(target + '/installation/study-runtime.json', encode(locator))
    readback = dict(schema='auto-g16-study-installation-readback/1', **identities,
        bundle=writer.binding(target), source=writer.binding(target + '/source'),
        installation=writer.binding(target + '/installation'), locator=locator_binding)
    writer.publish(target + '/installation/study-runtime-readback.json', encode(readback))
    with facts.inspect_bundle(target) as accepted:
        result = dict(schema='auto-g16-study-local-install-response/1', command='install-local',
            request_sha256=digest, state='local-package-published', installation=_summary(accepted),
            qualification_state='not-assessed', execution_performed=False)
        tree.check(); writer.check()
    # inspect_bundle's exit follows the final source check and revalidates the full target inventory.
    writer.check()
    return result


def publish_local(request_path, request_sha256):
    pins, writer, original = facts._Pins(), _Writer(), None
    try:
        result = _publish(pins, writer, request_path, request_sha256)
    except (StudyError, FileNotFoundError) as error:
        original = error
        # Only a missing request is the CLI's not-found condition.
        if isinstance(error, FileNotFoundError) and request_path in pins.nodes:
            original = StudyError('installation-unavailable')
        raise original from None
    except facts.InstallationFactsError as error:
        original = StudyError(error.code)
        raise original from None
    except Exception:
        original = StudyError('installation-publication-failed')
        raise original from None
    except BaseException as error:
        original = error
        raise
    finally:
        cleanup = original
        for held in (pins, writer):
            try:
                held.close(cleanup)
            except facts.InstallationFactsError:
                cleanup = StudyError('installation-publication-failed')
        if original is None and cleanup is not None:
            raise cleanup
    return result


def initialize_installed(creation_directory):
    from ._runtime_initialization import _initialize_bound
    pins, original = facts._Pins(), None
    try:
        with facts.load_installed_runtime() as installed:
            directory = facts._path(creation_directory, absolute=True)
            root = installed.roots['creation']['path']
            facts._require(directory != root and os.path.commonpath((root, directory)) == root, 'invalid-request')
            pins.open(directory)
            # initialize_local validates the complete native /2 creation before runtime mutation.
            creation_binding = pins.binding(directory)
            expected_root = _plain(installed.roots['creation']['parent_chain'])
            facts._require(creation_binding['parent_chain'][:len(expected_root)] == expected_root, 'identity-drift')
            initialized = _initialize_bound(directory, installed.roots['runtime']['path'],
                creation_chain=creation_binding['parent_chain'],
                runtime_chain=_plain(installed.roots['runtime']['parent_chain']))
            pins.check()
            result = dict(schema='auto-g16-study-installed-local-response/1', command='run',
                action='initialize-local', installation=_summary(installed), initialization=initialized,
                qualification_state='not-assessed', execution_performed=False)
    except facts.InstallationFactsError as error:
        original = StudyError(error.code)
        raise original from None
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            pins.close(original)
        except facts.InstallationFactsError as error:
            raise StudyError(error.code) from None
    return result
