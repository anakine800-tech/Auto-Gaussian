"""Startup-only registration: exact snapshot bytes, no business-store open."""
from dataclasses import asdict
from hashlib import sha256
import json
from unittest import TestCase
from unittest.mock import patch

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.conformer.readonly import load_opt_readout
from auto_g16.result._successor import _plain
from tests.v31.transport import test_gaussian_successor as gaussian_fixture
from tests.v31.transport.test_publisher_pilot_orchestration import file_binding


class OptRegistrationTests(TestCase):
    def setUp(self):
        fixture = gaussian_fixture.GaussianSuccessorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        snapshot = fixture.qualified_case()[-1]
        self.snapshot_path = fixture.root / 'read-snapshot.json'
        self.snapshot_path.write_text(json.dumps(_plain(snapshot._approval_semantics())))
        opaque = fixture.root / 'not-opened-at-registration'
        opaque.write_bytes(b'not a database')
        binding = asdict(file_binding(opaque))
        self.data = {'schema': 'auto-g16-opt-readout-registration/1', 'material': binding,
            'sources': [{'member_id': 'member', 'original': {
                'snapshot_id': snapshot.program_execution_snapshot_id,
                'core': binding, 'transport': binding, 'bootstrap_source_sha256': '0'*64,
                'bootstrap_source_size_bytes': 1},
                'snapshot': asdict(file_binding(self.snapshot_path)), 'transport_root': str(fixture.root),
                'revision': binding, 'parser_version': '1.2.0'}]}

    def load(self, data=None):
        content = json.dumps(self.data if data is None else data).encode()
        return load_opt_readout(content, sha256(content).hexdigest())

    def test_snapshot_loaded_without_opening_business_stores(self):
        with patch.object(SQLiteRuntimeStore, '__init__', side_effect=AssertionError('write constructor')), \
             patch.object(SQLiteRuntimeStore, '_open_readonly_existing', side_effect=AssertionError('Core read')):
            value = self.load()
        self.assertEqual(value.sources[0].parser_version, '1.2.0')
        self.assertEqual(value.source_for(value.sources[0].snapshot.attempt_id).member_id, 'member')

    def test_digest_closed_fields_duplicates_and_identity_reject(self):
        content = json.dumps(self.data).encode()
        with self.assertRaises(ValueError): load_opt_readout(content, '0'*64)
        duplicated = content.replace(b'"member_id": "member"', b'"member_id": "member", "member_id": "other"')
        with self.assertRaises(ValueError): load_opt_readout(duplicated, sha256(duplicated).hexdigest())
        for change in ('extra', 'source-extra', 'snapshot-id', 'parser', 'duplicate'):
            data = json.loads(content)
            if change == 'extra': data['unowned'] = True
            elif change == 'source-extra': data['sources'][0]['unowned'] = True
            elif change == 'snapshot-id': data['sources'][0]['original']['snapshot_id'] = 'other'
            elif change == 'parser': data['sources'][0]['parser_version'] = 'latest'
            else: data['sources'].append(data['sources'][0])
            with self.subTest(change=change), self.assertRaises(ValueError): self.load(data)

    def test_replaced_same_bytes_snapshot_is_not_accepted(self):
        raw = self.snapshot_path.read_bytes()
        self.snapshot_path.rename(self.snapshot_path.with_suffix('.retained'))
        self.snapshot_path.write_bytes(raw)
        with self.assertRaises(ValueError): self.load()
