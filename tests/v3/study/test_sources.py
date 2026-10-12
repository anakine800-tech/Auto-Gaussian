"""Historical source ownership and saved handoff decoding boundaries."""
from dataclasses import replace
from hashlib import sha256
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from auto_g16.execution import _receipt_source as source, program_runtime as runtime
from auto_g16.execution._crest_seed_handoff import _restore_receipt_seed_handoff
from auto_g16.transport._canonical import TransportBoundaryError
from auto_g16.transport._program_rtwin import _PublisherFileBinding
from tests.v31.transport import test_publisher_collection_recovery as recovery
from tests.v31.transport import test_publisher_pilot_orchestration as pilot
from auto_g16.transport import _bridge


class HistoricalSourceTests(recovery._RecoveryFixture):
    def setUp(self):
        super().setUp()
        self.resume()
        self.fixed = source._FixedReceiptSource(self.snapshot.program_execution_snapshot_id,
            pilot.file_binding(Path(self.database)), pilot.file_binding(Path(self.program_transport_store._path)),
            sha256(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(), len(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))

    def test_exact_context_original_read_and_no_global_fallback(self):
        catalogue = {'xtb': self.fixed, 'crest': replace(self.fixed, snapshot_id='crest-other')}
        with patch.object(source, '_FIXED_RECEIPT_SOURCE', None):
            with source._historical_receipt_sources(catalogue):
                proof, capture = runtime._read_program_receipt_success_authority(self.store,
                    snapshot=self.snapshot, program_transport_store=self.program_transport_store)
                self.assertEqual(proof['capture_authority_id'], capture.capture_authority_id)
            self.assertIsNone(source._HISTORICAL_SOURCES.get())
        with patch.object(source, '_FIXED_RECEIPT_SOURCE', self.fixed):
            catalogue['xtb'] = replace(self.fixed, snapshot_id='foreign')
            with source._historical_receipt_sources(catalogue), self.assertRaises(TransportBoundaryError):
                runtime._read_program_receipt_success_authority(self.store,
                    snapshot=self.snapshot, program_transport_store=self.program_transport_store)


class ContextAndLoaderTests(unittest.TestCase):
    def test_native_busy_is_not_evidence_corruption_or_unsupported_lock(self):
        import errno
        from auto_g16.study._catalog import _availability_error
        from auto_g16.query.models import QueryError
        lock = TransportBoundaryError('completion physical owner is busy or unsupported')
        lock.__cause__ = BlockingIOError(errno.EAGAIN, 'locked')
        wrapper = ValueError('native consumer rejected'); wrapper.__cause__ = lock
        self.assertEqual(_availability_error(wrapper), 'busy')
        lock.__cause__ = OSError(errno.ENOTSUP, 'unsupported')
        self.assertIsNone(_availability_error(wrapper))
        self.assertEqual(_availability_error(QueryError('store-unavailable')), 'source-unavailable')
        self.assertIsNone(_availability_error(QueryError('invalid-evidence')))
    def test_catalog_gaussian_core_snapshot_and_member_edges_reject_swaps(self):
        from auto_g16.study._catalog import _gaussian_stage_links
        from auto_g16.study._model import StudyError
        databases = {s: 'core-' + s for s in ('anti_opt', 'anti_freq', 'gauche_opt', 'gauche_freq')}
        snapshots = {s: 'snapshot-' + s for s in databases}
        def item(stage):
            return SimpleNamespace(member_id=stage.split('_')[0],
                original=SimpleNamespace(core=databases[stage]), snapshot=snapshots[stage])
        freq = SimpleNamespace(optimization_sources=(item('anti_opt'), item('gauche_opt')),
                               frequency_sources=(item('anti_freq'), item('gauche_freq')))
        _gaussian_stage_links(freq, databases, snapshots)
        for changed in ('core', 'snapshot', 'member'):
            with self.subTest(changed=changed):
                wrong = item('anti_freq')
                if changed == 'core': wrong.original.core = databases['gauche_freq']
                if changed == 'snapshot': wrong.snapshot = snapshots['gauche_freq']
                if changed == 'member': wrong.member_id = 'gauche'
                swapped = SimpleNamespace(optimization_sources=freq.optimization_sources,
                    frequency_sources=(wrong, item('gauche_freq')))
                with self.assertRaises(StudyError): _gaussian_stage_links(swapped, databases, snapshots)

    def test_owner_exit_mutation_is_checked_before_source_pins_close(self):
        from auto_g16.study._catalog import _pinned_sources
        with tempfile.TemporaryDirectory() as root:
            path = Path(root).resolve() / 'source.json'; path.write_bytes(b'original')
            node = path.stat()
            bound = _PublisherFileBinding(str(path), tuple((p.stat().st_dev, p.stat().st_ino)
                for p in reversed(path.parents)), (node.st_dev, node.st_ino), sha256(b'original').hexdigest(), 8)
            @contextmanager
            def owner():
                yield
                path.write_bytes(b'modified')
            with self.assertRaises(TransportBoundaryError):
                with _pinned_sources() as (stack, pin, _):
                    self.assertEqual(pin(bound), b'original')
                    stack.enter_context(owner())
            self.assertEqual(path.read_bytes(), b'modified')

    def test_closed_context_nested_and_exception_reset(self):
        binding = _PublisherFileBinding('/fixture', ((1, 1),), (1, 2), 'a' * 64, 1)
        item = source._FixedReceiptSource('xtb-id', binding, binding, 'a' * 64, 1)
        catalogue = {'xtb': item, 'crest': replace(item, snapshot_id='crest-id')}
        for bad in ({}, {'xtb': item, 'crest': item}, {**catalogue, 'gaussian': item},
                    {**catalogue, 'xtb': replace(item, project_association=object())}):
            with self.assertRaises(TransportBoundaryError), source._historical_receipt_sources(bad):
                pass
        with self.assertRaisesRegex(RuntimeError, 'sentinel'):
            with source._historical_receipt_sources(catalogue):
                with self.assertRaises(TransportBoundaryError), source._historical_receipt_sources(catalogue):
                    pass
                raise RuntimeError('sentinel')
        self.assertIsNone(source._HISTORICAL_SOURCES.get())

    def test_saved_handoff_closed_decode(self):
        from auto_g16.execution._identity import ExecutionValueError
        keys = ('xtb_snapshot_id', 'xtb_effect_intent_id', 'xtb_project_id',
            'xtb_project_physical_binding_id', 'xtb_project_physical_binding',
            'xtb_terminal_success_authority', 'optimized_geometry_sha256',
            'optimized_geometry_size_bytes', 'crest_spec_id', 'crest_spec_payload_sha256',
            'sampling_profile_id', 'sampling_profile_payload_sha256')
        value = {k: 'fixture' for k in keys}
        value['schema'] = 'v31-xtb-crest-seed-handoff/2'
        raw = json.dumps(value).encode()
        restored = _restore_receipt_seed_handoff(raw, sha256(raw).hexdigest())
        restored.assert_identity_closed()  # Nested proof is the native consumer's responsibility.
        for invalid in (b'{"a":1,"a":2}', b'{"a":NaN}', b'{}',
                        json.dumps({**value, 'extra': 1}).encode()):
            with self.assertRaises((ValueError, ExecutionValueError)):
                _restore_receipt_seed_handoff(invalid, sha256(invalid).hexdigest())
        with self.assertRaises(ExecutionValueError): _restore_receipt_seed_handoff(raw, '0' * 64)
