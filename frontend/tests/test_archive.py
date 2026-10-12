import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from auto_g16.query import QueryError
from autog_frontend.archive import ArchiveQuery, SCHEMA, validate_index
from autog_frontend.archive_import import build_record
from autog_frontend.api import create_app
from .archive_fixture import archive_capture
from .test_api import TestClient, TOKEN


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.capture = archive_capture(self.root)
        self.record = build_record(self.capture)
        self.index = self.root / 'index.json'
        self.raw = json.dumps({'schema': SCHEMA, 'records': [self.record]}).encode()
        self.index.write_bytes(self.raw)
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.query = ArchiveQuery(self.index, self.digest)

    def test_parser_facts_and_missing_frequency_have_distinct_meanings(self):
        self.assertEqual(self.record['summary']['energy_hartree'], -75.0)
        self.assertIsNone(self.record['summary']['frequency_count'])
        self.assertIsNone(self.record['summary']['imaginary_count'])
        record = build_record(archive_capture(self.root, frequency=True))
        self.assertEqual(record['summary']['frequency_count'], 3)
        self.assertEqual(record['summary']['imaginary_count'], 1)
        self.assertTrue(all(v == 'unavailable' for v in record['authority'].values()))

    def test_unparseable_preserves_references_without_summary(self):
        record = build_record(archive_capture(self.root, invalid=True))
        self.assertNotEqual(record['parser']['status'], 'parsed')
        self.assertIsNone(record['summary'])
        self.assertEqual(len(record['artifacts']), 3)

    def test_capture_tamper_and_sidecar_mismatch_fail(self):
        mixed = copy.deepcopy(self.capture)
        mixed['files'][0]['path'] = 'C:\\OtherProject\\synthetic.log'
        with self.assertRaises(ValueError):
            build_record(mixed)
        Path(self.capture['files'][0]['local_file']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            build_record(self.capture)
        capture = archive_capture(self.root)
        f = capture['files'][2]
        raw = Path(f['local_file']).read_bytes().replace(b'"synthetic.log"', b'"different.log"')
        Path(f['local_file']).write_bytes(raw)
        f.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), sha256_after=hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            build_record(capture)

    def test_pinned_index_changes_and_symlinks_fail(self):
        self.index.write_bytes(self.raw + b' ')
        with self.assertRaises(QueryError):
            self.query.list_archives()
        self.index.write_bytes(self.raw)
        alias = self.root / 'alias.json'
        alias.symlink_to(self.index)
        with self.assertRaises(QueryError):
            ArchiveQuery(alias, self.digest).list_archives()

    def test_invalid_authority_duplicates_and_frequency_fail(self):
        for change in ('authority', 'frequency', 'identity'):
            r = copy.deepcopy(self.record)
            if change == 'authority': r['authority']['core_attempt'] = 'succeeded'
            if change == 'frequency': r['summary']['imaginary_count'] = 0
            if change == 'identity': r['archive_id'] = 'archive-' + '0' * 64
            with self.assertRaises(ValueError): validate_index({'schema': SCHEMA, 'records': [r]})
        with self.assertRaises(ValueError):
            validate_index({'schema': SCHEMA, 'records': [self.record, self.record]})

    def test_query_never_parses_or_launches_process_and_keeps_index_unchanged(self):
        before = self.index.stat()
        with patch('autog_frontend.archive_import.GaussianJobParser.parse', side_effect=AssertionError('parse on GET')), patch('subprocess.Popen', side_effect=AssertionError('process on GET')):
            self.assertEqual(len(self.query.list_archives()['items']), 1)
            self.assertEqual(self.query.get_archive(self.record['archive_id'])['data'], self.record)
        after = self.index.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ctime_ns), (after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        self.assertEqual(self.index.read_bytes(), self.raw)

    def test_http_authorization_get_only_missing_and_no_source_paths(self):
        app = create_app(self.root / 'absent-core.db', token=TOKEN, archive_index=self.index, archive_sha256=self.digest)
        client = TestClient(app, base_url='http://localhost', headers={'Authorization': 'Bearer ' + TOKEN})
        response = client.get('/api/archives')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(self.root), response.text)
        self.assertNotIn('C:\\Archive', response.text)
        self.assertEqual(client.get('/api/archives/' + self.record['archive_id']).json()['data'], self.record)
        self.assertEqual(client.post('/api/archives').status_code, 405)
        self.assertEqual(client.get('/api/archives?path=elsewhere').status_code, 400)
        self.assertEqual(client.get('/api/archives/missing').status_code, 404)
        self.assertEqual(TestClient(app, base_url='http://localhost').get('/api/archives').status_code, 401)
        self.assertFalse((self.root / 'absent-core.db').exists())

    def test_optional_source_and_configuration_pair(self):
        self.assertEqual(ArchiveQuery(None, None).list_archives()['items'], [])
        self.assertFalse(ArchiveQuery(None, None).list_archives()['configured'])
        with self.assertRaises(ValueError): ArchiveQuery(self.index, None)
        with self.assertRaises(ValueError): ArchiveQuery(None, self.digest)
