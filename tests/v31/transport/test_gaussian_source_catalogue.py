import asyncio
from contextvars import Context
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auto_g16.execution import _receipt_source as owner
from auto_g16.transport._canonical import TransportBoundaryError


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        self.one = owner._FixedReceiptSource('one', None, None, '0'*64, 1)
        self.two = replace(self.one, snapshot_id='two')

    def test_registration_and_exception_cleanup(self):
        for values in ((), [], (None,), (self.one, self.one)):
            with self.assertRaises(TransportBoundaryError):
                with owner._gaussian_receipt_sources(values):
                    self.fail('invalid registration entered')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            with owner._gaussian_receipt_sources((self.one,)):
                with self.assertRaises(TransportBoundaryError):
                    with owner._gaussian_receipt_sources((self.two,)): pass
                self.assertEqual(owner._GAUSSIAN_SOURCES.get(), (self.one,))
                raise RuntimeError('interrupted')
        self.assertIsNone(owner._GAUSSIAN_SOURCES.get())

    def test_active_catalogue_never_falls_back(self):
        snapshot = SimpleNamespace(program_execution_snapshot_id='one',
            project_physical_binding=SimpleNamespace(provisioning_contract_version='remote-project-physical-binding/2'),
            program_execution_spec=SimpleNamespace(program_kind='gaussian',
                invocation={'executable_identity': {'absolute_path': '/production/g16'}}))
        with patch.object(owner, '_FIXED_GAUSSIAN_RECEIPT_SOURCE', self.one), \
             owner._gaussian_receipt_sources((self.two,)), \
             self.assertRaisesRegex(TransportBoundaryError, 'NOT_ACQUIRED'):
            with owner._source_qualification(None, snapshot, None, None): pass

    def test_changed_catalogue_is_rejected_and_restored(self):
        with self.assertRaisesRegex(TransportBoundaryError, 'changed'):
            with owner._gaussian_receipt_sources((self.one,)):
                owner._GAUSSIAN_SOURCES.set((self.two,))
        self.assertIsNone(owner._GAUSSIAN_SOURCES.get())

    def test_independent_contexts_and_interleaved_tasks(self):
        with owner._gaussian_receipt_sources((self.one,)):
            self.assertIsNone(Context().run(owner._GAUSSIAN_SOURCES.get))
        async def run():
            ready = [asyncio.Event(), asyncio.Event()]
            async def read(index, source):
                with owner._gaussian_receipt_sources((source,)):
                    ready[index].set()
                    await ready[1-index].wait()
                    self.assertEqual(owner._GAUSSIAN_SOURCES.get(), (source,))
            await asyncio.gather(read(0, self.one), read(1, self.two))
        asyncio.run(run())
        self.assertIsNone(owner._GAUSSIAN_SOURCES.get())
