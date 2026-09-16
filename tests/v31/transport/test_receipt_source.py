"""Original production-shaped SQLite authority, with an inert wire only in setup."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import os
from unittest.mock import patch

from auto_g16 import core
from auto_g16.execution import _receipt_source as source, program_runtime as runtime
from auto_g16.transport import _program_rtwin as rtwin, _bridge, program as transport
from auto_g16.transport._canonical import TransportBoundaryError
from tests.v31.transport import test_publisher_collection_recovery as recovery
from tests.v31.transport import test_publisher_pilot_orchestration as pilot


class ReceiptSourceTests(recovery._RecoveryFixture):
    def setUp(self):
        super().setUp()
        self.resume()
        self.fixed = source._FixedReceiptSource(self.snapshot.program_execution_snapshot_id,
            pilot.file_binding(Path(self.database)), pilot.file_binding(Path(self.program_transport_store._path)),
            sha256(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES).hexdigest(), len(_bridge._PROGRAM_BOOTSTRAP_SOURCE_BYTES))

    def read(self, fixed=None, store=None):
        before = tuple(Path(b.path).read_bytes() for b in (self.fixed.core, self.fixed.transport))
        calls = len(self.wire.calls)
        try:
            with patch.object(source, '_FIXED_RECEIPT_SOURCE', fixed or self.fixed), \
                 patch.object(rtwin, '_FIXED_PUBLISHER_INSTALLATION', None), \
                 patch.object(rtwin, '_FIXED_COLLECTION_INSTALLATION', None), \
                 patch.object(rtwin, '_RTWinProgramEffectDriver', side_effect=AssertionError('no live driver')), \
                 patch.object(core.SQLiteRuntimeStore, 'append_observation', side_effect=AssertionError('no write')), \
                 patch.object(core.SQLiteRuntimeStore, 'append_result', side_effect=AssertionError('no write')), \
                 patch.object(transport._ProgramTransportStore, 'attest_runtime', side_effect=AssertionError('no attestation write')):
                return runtime._read_program_receipt_success_authority(store or self.store,
                    snapshot=self.snapshot, program_transport_store=self.program_transport_store)
        finally:
            self.assertEqual(before, tuple(Path(b.path).read_bytes() for b in (self.fixed.core, self.fixed.transport)))
            self.assertEqual(calls, len(self.wire.calls))

    def test_original_success_without_any_live_installation(self):
        proof, capture = self.read()
        self.assertEqual(proof['capture_authority_id'], capture.capture_authority_id)
        self.assertEqual(proof['schema'], 'program-terminal-success-authority/2')

    def test_missing_or_drifted_source_rejects(self):
        for fixed in (replace(self.fixed, snapshot_id='other'), replace(self.fixed, bootstrap_source_sha256='0'*64),
                      replace(self.fixed, core=replace(self.fixed.core, sha256='0'*64))):
            with self.subTest(fixed=fixed), self.assertRaises(TransportBoundaryError): self.read(fixed)
        with patch.object(source, '_FIXED_RECEIPT_SOURCE', None), self.assertRaises(TransportBoundaryError):
            runtime._read_program_receipt_success_authority(self.store, snapshot=self.snapshot, program_transport_store=self.program_transport_store)

    def test_copied_database_cannot_supply_original_proof(self):
        path = self.root / 'copied.sqlite3';path.write_bytes(Path(self.database).read_bytes())
        copied = core.SQLiteRuntimeStore(path);self.addCleanup(copied.close)
        with self.assertRaises(TransportBoundaryError): self.read(store=copied)

    def test_existing_transaction_and_attachment_reject(self):
        self.store._connection.execute('BEGIN')
        try:
            with self.assertRaises(TransportBoundaryError): self.read()
        finally: self.store._connection.execute('ROLLBACK')
        self.store._connection.execute("ATTACH DATABASE ':memory:' AS unrelated")
        try:
            with self.assertRaises(TransportBoundaryError): self.read()
        finally: self.store._connection.execute('DETACH DATABASE unrelated')

    def test_journal_sidecar_rejects(self):
        Path(str(self.database)+'-wal').write_bytes(b'inert sidecar')
        with self.assertRaises(TransportBoundaryError): self.read()

    def test_same_path_stale_connection_cannot_hide_current_failure(self):
        path = Path(self.database)
        retained = self.root / 'original-retained.sqlite3'
        stale_path = self.root / 'stale-retained.sqlite3'
        os.rename(path, retained)
        path.write_bytes(retained.read_bytes())
        stale = core.SQLiteRuntimeStore(path);self.addCleanup(stale.close)
        os.rename(path, stale_path)
        os.rename(retained, path)
        # Deliberately corrupted synthetic Core state; the old connection still
        # sees SUCCEEDED while the fixed original bytes say FAILED.
        self.store._connection.execute("UPDATE attempts SET state='FAILED' WHERE attempt_id='attempt-1'")
        self.fixed = replace(self.fixed, core=pilot.file_binding(path))
        self.assertEqual(stale.attempt_state('attempt-1'), core.AttemptState.SUCCEEDED)
        with self.assertRaises(TransportBoundaryError): self.read(store=stale)
