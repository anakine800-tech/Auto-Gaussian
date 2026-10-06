"""Detached Opt readout composed from exact original proof and retained revisions.

Registrations belong to trusted local startup, never to HTTP request arguments.
Every read replays native parsing, validation, member audit and joint deduplication.
"""
from contextlib import ExitStack
from dataclasses import dataclass
from inspect import signature
from hashlib import sha256
import json
from threading import Lock

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution._receipt_source import _FixedReceiptSource, _gaussian_receipt_sources
from auto_g16.execution.readonly import ProgramReadSnapshot
from auto_g16.execution.program import _decode_program_review_semantics
from auto_g16.execution._gaussian_result_source import gaussian_result_source
from auto_g16.transport._program_rtwin import _PublisherFileBinding, _PinnedPublisherFile
from auto_g16.transport.program import _ProgramTransportStore
from auto_g16.result._successor import parse_source, require_pair, _plain, project_opt_facts
from .models import SamplingProfile, ConformerEnsemble
from ._successor_opt import refine_opt_ensemble
from .refinement_authority import _require


_OPT_READ_LOCK = Lock()
_OPT_READ_WAIT_SECONDS = 30


class OptReadBusy(ValueError):
    """The consumer's bounded read slot is occupied; no proof was replayed."""


def load_opt_readout(content: bytes, digest: str):
    return _load_readout(content, digest, associated=False)


def _load_readout(content: bytes, digest: str, *, associated: bool):
    """Decode a hash-bound startup document; open only its pinned Snapshot files.

    Core/Transport/material databases are validated by the read owner at query
    time. The document is never an execution or installation authorization.
    """
    _require(type(content) is bytes and len(content) <= 1024 * 1024
             and type(digest) is str and sha256(content).hexdigest() == digest,
             "invalid Opt registry digest")
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate Opt registry key")
            result[key] = value
        return result
    def closed(value, keys):
        _require(type(value) is dict and set(value) == set(keys), "Opt registry fields differ")
        return value
    def binding(value):
        closed(value, ('path', 'parent_chain', 'file_identity', 'sha256', 'size_bytes'))
        _require(type(value['parent_chain']) is list and type(value['file_identity']) is list,
                 "invalid Opt registry physical identity")
        return _PublisherFileBinding(value['path'], tuple(tuple(node) for node in value['parent_chain']),
                                     tuple(value['file_identity']), value['sha256'], value['size_bytes'])
    data = closed(json.loads(content, object_pairs_hook=pairs), ('schema', 'material', 'sources'))
    _require(data['schema'] == 'auto-g16-opt-readout-registration/1'
             and type(data['sources']) is list and 1 <= len(data['sources']) <= 32,
             "unsupported Opt registry")
    sources = []
    for row in data['sources']:
        closed(row, ('member_id', 'original', 'snapshot', 'transport_root', 'revision', 'parser_version'))
        original = closed(row['original'], ('snapshot_id', 'core', 'transport',
                                           'bootstrap_source_sha256', 'bootstrap_source_size_bytes') +
                          (('project_association',) if associated else ()))
        association = None
        if associated:
            from auto_g16.execution._project_association_source import decode_source
            association = decode_source(original['project_association'])
        snapshot_binding = binding(row['snapshot'])
        pin = _PinnedPublisherFile(snapshot_binding, 16 * 1024 * 1024)
        try:
            snapshot = ProgramReadSnapshot(content=pin.raw, sha256=snapshot_binding.sha256)
            pin._read_and_check()
        finally:
            pin.close()
        sources.append(OptMemberSource(member_id=row['member_id'], snapshot=snapshot,
            original=_FixedReceiptSource(original['snapshot_id'], binding(original['core']),
                binding(original['transport']), original['bootstrap_source_sha256'],
                original['bootstrap_source_size_bytes'], project_association=association),
            transport_root=row['transport_root'], revision=binding(row['revision']),
            parser_version=row['parser_version']))
    return OptReadout(material=binding(data['material']), sources=tuple(sources))


@dataclass(frozen=True, kw_only=True)
class OptMemberSource:
    member_id: str
    original: _FixedReceiptSource
    snapshot: ProgramReadSnapshot
    transport_root: str
    revision: _PublisherFileBinding
    parser_version: str = "1.2.0"

    def __post_init__(self):
        _require(type(self.original) is _FixedReceiptSource
                 and type(self.snapshot) is ProgramReadSnapshot
                 and type(self.revision) is _PublisherFileBinding
                 and self.parser_version in {"1.1.0", "1.2.0"}, "invalid Opt source registration")
        snapshot = _decode_program_review_semantics(json.loads(self.snapshot.content))
        _require(snapshot.program_execution_snapshot_id == self.original.snapshot_id,
                 "Opt source Snapshot differs")


@dataclass(frozen=True, kw_only=True)
class OptReadout:
    material: _PublisherFileBinding
    sources: tuple[OptMemberSource, ...]

    def __post_init__(self):
        _require(type(self.material) is _PublisherFileBinding and type(self.sources) is tuple
                 and bool(self.sources) and all(type(s) is OptMemberSource for s in self.sources),
                 "invalid Opt readout registration")
        for keys in ((s.member_id for s in self.sources),
                     (s.snapshot.attempt_id for s in self.sources),
                     (s.original.snapshot_id for s in self.sources)):
            values = tuple(keys)
            _require(len(set(values)) == len(values), "duplicate Opt readout identity")

    def source_for(self, attempt_id):
        matches = tuple(s for s in self.sources if s.snapshot.attempt_id == attempt_id)
        _require(len(matches) == 1, "Opt readout Attempt not registered")
        return matches[0]

    def read(self, store, attempt_id):
        # The retained Transport owner intentionally rejects concurrent access.
        # Share one consumer slot across registrations without weakening that guard.
        if not _OPT_READ_LOCK.acquire(timeout=_OPT_READ_WAIT_SECONDS):
            raise OptReadBusy("Opt read slot is busy")
        try:
            return self._read_serial(store, attempt_id)
        finally:
            _OPT_READ_LOCK.release()

    def _read_serial(self, store, attempt_id):
        selected = self.source_for(attempt_id)
        with ExitStack() as stack:
            pins = []
            def pin(binding):
                value = _PinnedPublisherFile(binding, 64 * 1024 * 1024)
                stack.callback(value.close)
                pins.append(value)
                return value.raw
            def pairs(items):
                result = {}
                for key, value in items:
                    _require(key not in result, "duplicate Opt material key")
                    result[key] = value
                return result
            material = json.loads(pin(self.material), object_pairs_hook=pairs)
            _require(set(material) == {"profile", "prior", "refined"}, "Opt material fields differ")
            def restore(factory, payload, **extra):
                value = factory(**extra, **{k: payload[k] for k in signature(factory).parameters if k in payload})
                _require(_plain(value._identity_payload()) == payload, "Opt material identity differs")
                return value
            profile = restore(SamplingProfile._create, material['profile'])
            prior = restore(ConformerEnsemble._create, material['prior'], profile=profile)
            inputs = []
            for item in self.sources:
                pin(item.revision)
                source = SQLiteRuntimeStore._open_readonly_existing(item.original.core.path)
                stack.callback(source.close)
                transport = _ProgramTransportStore._open_readonly_existing(
                    item.original.transport.path, approved_root=item.transport_root)
                stack.callback(transport.close)
                destination = stack.enter_context(SQLiteRuntimeStore.read_snapshot(item.revision.path))
                if item is selected:
                    _require(store._connection.serialize() == destination._connection.serialize(),
                             "query view differs from registered parsed revision")
                inputs.append(dict(member_id=item.member_id, source_store=source, transport_store=transport,
                    snapshot=_decode_program_review_semantics(json.loads(item.snapshot.content)),
                    destination=destination, parser_version=item.parser_version))
            with _gaussian_receipt_sources(tuple(s.original for s in self.sources)):
                refined = refine_opt_ensemble(prior, profile, inputs=inputs)
                _require(_plain(refined._identity_payload()) == material['refined'],
                         "retained Opt refinement differs from original proof replay")
                args = inputs[self.sources.index(selected)]
                with gaussian_result_source(args['source_store'], snapshot=args['snapshot'],
                                            transport_store=args['transport_store']) as (_, payload, _, log):
                    observation, result, _, parsed = parse_source(payload, log, parser_version=selected.parser_version)
                    require_pair(store, observation, result)
                    projection = project_opt_facts(payload, result, parsed)
            member = next(m for m in refined.members if m['member_id'] == selected.member_id)
            authority = member['optimization_geometry_authority'] or member['negative_optimization_authority']
            projection['assessment'] = _plain(authority['assessment'])
            projection['optimization']['ensemble'] = {
                'conformer_ensemble_id': refined.conformer_ensemble_id,
                'payload_sha256': refined.payload_sha256, 'revision': refined.revision,
                'supersedes_conformer_ensemble_id': prior.conformer_ensemble_id,
                'sampling_project_id': prior.project_id,
                'member_id': selected.member_id, 'status': member['post_dft_status'],
                'member_ids': [m['member_id'] for m in refined.members],
                'audit': _plain(refined.audit_evidence[len(prior.audit_evidence):]),
                'dedup': _plain(refined.dedup_decisions[len(prior.dedup_decisions):]),
                'thermodynamic_eligible_members': _plain(refined.thermodynamic_eligible_members),
                'ts_seed_members': _plain(refined.ts_seed_members),
            }
            for value in pins:
                value._read_and_check()
        return projection
