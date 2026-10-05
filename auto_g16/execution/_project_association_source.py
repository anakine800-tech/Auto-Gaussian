"""Private, fixed-source Project association owner and detached replay.

Installation supplies locators, never HTTP or a scientific input. A decoded
binding is only an identity; only this owner can establish its creation source.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, asdict
from pathlib import Path
import base64
from datetime import datetime
from hashlib import sha256
import os
import stat

from auto_g16.transport._canonical import canonical_json_bytes, strict_canonical_json
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from . import _project_association as a
from ._identity import freeze_mapping, semantic_id, semantic_sha256


@dataclass(frozen=True, slots=True)
class _AssociationInstallation:
    project_id: str
    journal: _PublisherFileBinding
    old_profile: _PublisherFileBinding
    new_profile: _PublisherFileBinding
    source_manifest: _PublisherFileBinding
    reviewed_installation: _PublisherFileBinding
    owner_acceptance: _PublisherFileBinding
    installation_readback: _PublisherFileBinding
    source_commit: str
    source_tree: str
    code_files: tuple[_PublisherFileBinding, ...]
    output_directory: str
    output_parent_chain: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _AssociationSource:
    installation: _AssociationInstallation
    proof: _PublisherFileBinding
    request: _PublisherFileBinding
    capture: _PublisherFileBinding
    operation: _PublisherFileBinding


# No discovery, environment override or public setter. A reviewed Controller
# installation fixes these, separately from execution authority.
_FIXED_ASSOCIATION_INSTALLATION = None
_FIXED_ASSOCIATION_SOURCE = None


def _plain(value):
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _raw(value):
    return canonical_json_bytes(_plain(value))


def _binding(value):
    a.closed(value, {'path', 'parent_chain', 'file_identity', 'sha256', 'size_bytes'})
    return _PublisherFileBinding(value['path'], tuple(tuple(n) for n in value['parent_chain']),
                                 tuple(value['file_identity']), value['sha256'], value['size_bytes'])


def decode_source(value):
    """Closed private startup registration, not a runtime or HTTP path selector."""
    a.closed(value, {'installation', 'proof', 'request', 'capture', 'operation'})
    inst = dict(a.closed(value['installation'], set(_AssociationInstallation.__dataclass_fields__)))
    for name in ('journal', 'old_profile', 'new_profile', 'source_manifest', 'reviewed_installation',
                 'owner_acceptance', 'installation_readback'):
        inst[name] = _binding(inst[name])
    inst['code_files'] = tuple(_binding(v) for v in inst['code_files'])
    inst['output_parent_chain'] = tuple(tuple(v) for v in inst['output_parent_chain'])
    return _AssociationSource(_AssociationInstallation(**inst), *(_binding(value[k]) for k in ('proof', 'request', 'capture', 'operation')))


def _profile(raw):
    from .models import ServerProfile, resolve_server_profile
    # Installed profile files predate this owner and need not be canonical JSON.
    import json
    def pairs(items):
        out = {}
        for key, value in items:
            a.require(key not in out, 'duplicate installed profile key')
            out[key] = value
        return out
    value = json.loads(raw, object_pairs_hook=pairs)
    value['config_files'] = [(row['logical_name'], base64.b64decode(row['content_base64'], validate=True))
                             for row in value['config_files']]
    value['runtime_contents'] = {k: base64.b64decode(v, validate=True) for k, v in value['runtime_contents'].items()}
    value['jump_topology'] = [tuple(row) for row in value['jump_topology']]
    current = ServerProfile(**value)
    return current, resolve_server_profile(current)


@contextmanager
def _installation_read(installation, *, live_owner=False):
    """Pin all registration inputs. Historical replay never calls a driver."""
    from .project_provisioning import _ProductionProvisioningJournal
    a.require(type(installation) is _AssociationInstallation, 'fixed installation NOT_ACQUIRED')
    with ExitStack() as stack:
        pins = []
        def read(binding):
            pin = _PinnedPublisherFile(binding, 64 * 1024 * 1024)
            pins.append(pin); stack.callback(pin.close)
            return pin.raw
        old_current, old = _profile(read(installation.old_profile))
        current, new = _profile(read(installation.new_profile))
        delta = a.profile_delta(old, new)
        read(installation.journal)
        journal = stack.enter_context(_ProductionProvisioningJournal.open_existing_readonly(
            installation.journal.path, approved_root=Path(installation.journal.path).parent))
        creation = journal._association_creation_source(installation.project_id)
        original = a.decode_binding(creation['original_binding'])
        a.require(original.resolved_server_profile_id == old.resolved_server_profile_id,
                  'original profile differs')
        source = {**creation, 'journal': {**asdict(installation.journal), 'journal_identity': journal._identity}}
        def profile_row(target, file):
            runtime = a.runtime_identity(target)
            return {'profile_file': asdict(file), 'resolved_profile_payload': a.profile_payload(target),
                    'runtime_authority_id': runtime, 'provisioning_authority_id': semantic_id(
                        'project-provisioning-authority', {'journal_identity': journal._identity, 'runtime_identity': runtime})}
        old_row, new_row = profile_row(old, installation.old_profile), profile_row(new, installation.new_profile)
        a.require(original.provisioning_authority_id == old_row['provisioning_authority_id'], 'original runtime differs')
        import json
        manifest = json.loads(read(installation.source_manifest))
        a.require(manifest['commit'] == installation.source_commit and manifest['tree'] == installation.source_tree,
                  'installed source commit/tree differs')
        import re
        a.require(all(type(v) is str and re.fullmatch('[0-9a-f]{40}', v) for v in
                      (installation.source_commit, installation.source_tree)), 'invalid source identity')
        review = strict_canonical_json(read(installation.reviewed_installation), 'association installation review')
        expected = {'schema': 'project-profile-association-installation-review/1',
                    'source_commit': installation.source_commit, 'source_tree': installation.source_tree,
                    'new_profile_id': new.resolved_server_profile_id,
                    'qualification': new.runtime_identities[a.Q8],
                    'owner_acceptance': {'sha256': installation.owner_acceptance.sha256, 'size_bytes': installation.owner_acceptance.size_bytes},
                    'installation_readback': {'sha256': installation.installation_readback.sha256, 'size_bytes': installation.installation_readback.size_bytes}}
        a.require(_raw(review) == _raw(expected), 'reviewed exact Q/installation scope differs')
        read(installation.owner_acceptance); read(installation.installation_readback)
        required = {'auto_g16/execution/' + name + '.py' for name in (
            '_project_association', '_project_association_source', 'project_provisioning', 'program', 'models')}
        required |= {'auto_g16/transport/' + name + '.py' for name in ('_program_rtwin', '_driver', '_bridge', 'program')}
        code = {}
        for binding in installation.code_files:
            path = Path(binding.path)
            matches = [rel for rel in required if path.as_posix().endswith('/' + rel)]
            a.require(len(matches) == 1 and matches[0] not in code, 'installed association owner inventory differs')
            rel = matches[0]; code[rel] = binding
            read(binding)
            a.require(manifest['source_files'][rel] == {'sha256': binding.sha256, 'size_bytes': binding.size_bytes},
                      'installed owner manifest differs')
            if live_owner:
                import importlib
                module = importlib.import_module(rel[:-3].replace('/', '.'))
                a.require(Path(module.__file__).absolute() == path, 'actual loaded association owner differs')
        a.require(set(code) == required, 'association owner code closure incomplete')
        payload = {'project_id': installation.project_id, 'source': source, 'old_profile': old_row,
                   'new_profile': new_row, 'allowed_delta': delta,
                   'issuer': {'owner_schema': 'project-profile-association-owner/1',
                              'source_commit': installation.source_commit, 'source_tree': installation.source_tree,
                              'installed_source_manifest': asdict(installation.source_manifest),
                              'target_runtime_authority_id': a.runtime_identity(new)}}
        try:
            yield freeze_mapping(payload, 'association sources'), current, new, original
        finally:
            for pin in pins:
                pin._read_and_check()
            journal._attest()


def _replay_observation(request_raw, capture_raw, target, original):
    """Closed frame/token verification from retained bytes, with no effect driver."""
    from auto_g16.transport import _bridge
    from auto_g16.transport import _program_rtwin as rtwin
    request = strict_canonical_json(request_raw, 'association request')
    expected = {'protocol': _bridge._PROGRAM_BOOTSTRAP_PROTOCOL, 'operation': 'OBSERVE_PROJECT',
                'binding': rtwin._wire_binding(target, target.resolved_server_profile_id, original.remote_project_dir), 'payload': {}}
    a.require(request == expected, 'observation request differs')
    cap = a.closed(strict_canonical_json(capture_raw, 'association capture'), {
        'schema', 'trusted_creation_receipt', 'operation', 'request_sha256', 'stdout_base64', 'stderr_base64',
        'stdout_sha256', 'stderr_sha256', 'output_complete', 'stdout_capture_limit', 'stderr_capture_limit',
        'returncode', 'transport_state', 'eof_stdout', 'eof_stderr'})
    operation = rtwin._project_operation('OBSERVE_PROJECT')
    a.require(cap['schema'] == 'project-wire-diagnostic/1' and cap['trusted_creation_receipt'] is False
              and cap['operation'] == 'OBSERVE_PROJECT' and cap['request_sha256'] == sha256(request_raw).hexdigest()
              and cap['output_complete'] is True and type(cap['returncode']) is int and cap['returncode'] == 0
              and cap['transport_state'] == 'completed' and cap['eof_stdout'] is True and cap['eof_stderr'] is True
              and cap['stdout_capture_limit'] == operation.stdout_cap and cap['stderr_capture_limit'] == operation.stderr_cap,
              'incomplete observation capture')
    out, err = (base64.b64decode(cap[k + '_base64'], validate=True) for k in ('stdout', 'stderr'))
    a.require(not err and len(out) <= operation.stdout_cap and all(
        sha256(raw).hexdigest() == cap[k + '_sha256'] and base64.b64encode(raw).decode() == cap[k + '_base64']
        for k, raw in (('stdout', out), ('stderr', err))), 'observation output differs')
    response = _bridge._decode_frame(out, cap=operation.stdout_cap, field='association response')
    a.closed(response, {'protocol', 'operation', 'result', 'status'})
    a.require(response['protocol'] == request['protocol'] and response['operation'] == 'OBSERVE_PROJECT'
              and response['status'] == 'ok', 'observation frame differs')
    result = a.closed(response['result'], {'state', 'parent_physical_identity', 'project_physical_identity'})
    a.require(result == {'state': 'EXISTING', 'parent_physical_identity': original.parent_physical_identity,
                        'project_physical_identity': original.project_physical_identity}, 'Project physical identity changed')
    # Token decoding uses the existing pure canonical decoder only; no authority lookup.
    rtwin._directory_token(result['parent_physical_identity'], original.remote_project_dir.rsplit('/', 1)[0])
    rtwin._directory_token(result['project_physical_identity'], original.remote_project_dir)
    return result


@contextmanager
def replay(binding, source=None):
    source = _FIXED_ASSOCIATION_SOURCE if source is None else source
    a.require(type(source) is _AssociationSource, 'registered association source NOT_ACQUIRED')
    binding.assert_identity_closed()
    with _installation_read(source.installation) as (base, _, target, original), ExitStack() as stack:
        pins = []
        def read(file):
            pin = _PinnedPublisherFile(file, 16 * 1024 * 1024)
            pins.append(pin); stack.callback(pin.close)
            return pin.raw
        files = ((source.proof, 'association.json'), (source.request, 'request.json'),
                 (source.capture, 'capture.json'), (source.operation, 'operation.json'))
        for file, name in files:
            a.require(file.path == source.installation.output_directory + '/' + name
                      and file.parent_chain == source.proof.parent_chain
                      and file.parent_chain[:-1] == source.installation.output_parent_chain,
                      'registered publication location differs')
        a.require(read(source.operation) == _raw(base), 'registered operation differs')
        proof = strict_canonical_json(read(source.proof), 'association proof')
        a.validate(proof)
        a.require(_raw(proof) == _raw(binding.project_profile_association), 'registered proof differs from binding')
        obs = proof['payload']['observation']
        a.require(_raw({k: v for k, v in proof['payload'].items() if k != 'observation'}) == _raw(base), 'registered source differs')
        a.require(_raw(obs['request']) == _raw(asdict(source.request)) and _raw(obs['capture']) == _raw(asdict(source.capture)),
                  'registered observation locator differs')
        result = _replay_observation(read(source.request), read(source.capture), target, original)
        a.require(result == obs['decoded_result'], 'decoded observation changed')
        window = a.closed(obs['observed_window'], {'started_at', 'finished_at'})
        from ._program_completion import _q_window
        _q_window(window)
        times = [datetime.fromisoformat(window[k].replace('Z', '+00:00')) for k in ('started_at', 'finished_at')]
        a.require(all(t.utcoffset() is not None and t.utcoffset().total_seconds() == 0 for t in times)
                  and 0 <= (times[1] - times[0]).total_seconds() <= 3600, 'invalid observation window')
        try:
            yield original
        finally:
            for pin in pins:
                pin._read_and_check()


class _Publication:
    """An exclusive bundle is also the durable once-only observation marker."""
    def __init__(self, installation):
        self.fds = []
        self.path = installation.output_directory
        parts = self.path[1:].split('/')
        a.require(self.path.startswith('/') and all(p not in {'', '.', '..'} for p in parts)
                  and len(installation.output_parent_chain) == len(parts), 'invalid association output path')
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
        try:
            self.fds.append(os.open('/', flags))
            for part in parts[:-1]:
                self.fds.append(os.open(part, flags, dir_fd=self.fds[-1]))
            self.parent_chain = installation.output_parent_chain
            self._check_parents()
            try:
                os.mkdir(parts[-1], 0o700, dir_fd=self.fds[-1])
                self.fresh = True
                os.fsync(self.fds[-1])
            except FileExistsError:
                self.fresh = False
            self.fds.append(os.open(parts[-1], flags, dir_fd=self.fds[-1]))
            info = os.fstat(self.fds[-1]); self.node = (info.st_dev, info.st_ino)
            self.check()
        except BaseException:
            self.close(); raise

    def _check_parents(self):
        parts = self.path[1:].split('/')
        for i, (fd, identity) in enumerate(zip(self.fds, self.parent_chain)):
            opened = os.fstat(fd)
            named = os.stat('/', follow_symlinks=False) if i == 0 else os.stat(parts[i-1], dir_fd=self.fds[i-1], follow_symlinks=False)
            a.require(stat.S_ISDIR(named.st_mode) and (opened.st_dev, opened.st_ino) == identity
                      and (named.st_dev, named.st_ino) == identity, 'output parent replaced')

    def check(self):
        self._check_parents()
        node = os.stat(self.path.rsplit('/', 1)[1], dir_fd=self.fds[-2], follow_symlinks=False)
        a.require(stat.S_ISDIR(node.st_mode) and (node.st_dev, node.st_ino) == self.node, 'output bundle replaced')

    def write(self, name, raw):
        self.check()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fds[-1])
        try:
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                a.require(written > 0, 'short association publication')
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(self.fds[-1]); self.check()
        return self.read_binding(name)

    def read_binding(self, name):
        self.check()
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fds[-1])
        try:
            info = os.fstat(fd)
            a.require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 16 * 1024 * 1024, 'invalid publication object')
            chunks = []; count = 0
            while count <= info.st_size:
                block = os.read(fd, min(1048576, info.st_size + 1 - count))
                if not block:
                    break
                chunks.append(block); count += len(block)
            raw = b''.join(chunks)
            a.require(len(raw) == info.st_size, 'publication size changed')
            binding = _PublisherFileBinding(self.path + '/' + name, (*self.parent_chain, self.node),
                (info.st_dev, info.st_ino), sha256(raw).hexdigest(), len(raw))
        finally:
            os.close(fd)
        pin = _PinnedPublisherFile(binding, 16 * 1024 * 1024)
        try:
            a.require(pin.raw == raw, 'publication bytes changed')
        finally:
            pin.close()
        return binding

    def close(self):
        while self.fds:
            os.close(self.fds.pop())


def issue(service, project):
    """Called only by the provisioning owner against its fixed installation."""
    from auto_g16.transport._program_rtwin import _RTWinProjectAttestor
    from .project_provisioning import _ProductionProvisioningJournal
    installation = _FIXED_ASSOCIATION_INSTALLATION
    a.require(type(installation) is _AssociationInstallation and project.project_id == installation.project_id,
              'exact Project association installation required')
    a.require(type(service._attestor) is _RTWinProjectAttestor
              and type(service._journal) is _ProductionProvisioningJournal and service._journal._read_only,
              'production association owner with read-only journal required')
    with _installation_read(installation, live_owner=True) as (base, current, target, original):
        a.require(service._journal._path == installation.journal.path
                  and service._journal._identity == base['source']['journal']['journal_identity']
                  and service._authority_id == base['new_profile']['provisioning_authority_id']
                  and service._attestor._profile == current and service._attestor._target == target,
                  'owning service differs from fixed installation')
        registered = _FIXED_ASSOCIATION_SOURCE
        if registered is not None:
            a.require(type(registered) is _AssociationSource and registered.installation == installation,
                      'completed association registration differs')
            pin = _PinnedPublisherFile(registered.proof, 16 * 1024 * 1024)
            try:
                binding = a.make_binding(strict_canonical_json(pin.raw, 'registered association proof'))
                with replay(binding, registered):
                    pin._read_and_check()
                return binding, registered
            finally:
                pin.close()
        publication = _Publication(installation)
        try:
            a.require(publication.fresh, 'existing bundle has no completed registration; no recovery or retry')
            if publication.fresh:
                # Directory durability precedes the only possible native invocation.
                publication.write('operation.json', _raw(base))
                request, capture, result, window = service._attestor._observe_association(target, original.remote_project_dir)
                a.require(result == _replay_observation(request, capture, target, original), 'native observation differs')
                req = publication.write('request.json', request)
                cap = publication.write('capture.json', capture)
                payload = freeze_mapping({**base, 'observation': {'request': asdict(req), 'capture': asdict(cap),
                    'decoded_result': result, 'observed_window': window}}, 'association issuance')
                proof = {'schema': a.SCHEMA, 'association_id': semantic_id(a.SCHEMA, payload),
                         'payload_sha256': semantic_sha256(payload), 'payload': payload}
                a.validate(proof)
                publication.write('association.json', _raw(proof))
            # Incomplete/conflicting bundles fail here, never resume or re-observe.
            source = _AssociationSource(installation, publication.read_binding('association.json'),
                publication.read_binding('request.json'), publication.read_binding('capture.json'),
                publication.read_binding('operation.json'))
            pin = _PinnedPublisherFile(source.proof, 16 * 1024 * 1024)
            try:
                binding = a.make_binding(strict_canonical_json(pin.raw, 'association proof'))
                with replay(binding, source):
                    publication.check()
            finally:
                pin.close()
            return binding, source
        finally:
            publication.close()


__all__ = ()
