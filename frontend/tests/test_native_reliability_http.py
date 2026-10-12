"""Disposable stores only. Optional projections do not install or compute results."""
import hashlib
import unittest
from unittest.mock import patch
from auto_g16.query import NativeQueryService, QueryError
from tests import test_native_http as fixture

class NativeReliabilityHTTPTests(unittest.TestCase):
    setUp = fixture.NativeHTTPTests.setUp

    def test_owner_projection_and_old_dto_unchanged(self):
        base='/api/v1/native/sources/one/attempts/attempt'
        before=self.client.get(base).content
        digest=hashlib.sha256(self.path.read_bytes()).hexdigest()
        for kind in ('lifecycle','populations'):
            data=dict(source_id='one',attempt_id='attempt',availability='unavailable',reason='not-registered',result=None)
            if kind=='populations':data['selected_member_id']=None
            dto=dict(schema=f'auto-g16-native-{kind}-query/1',kind=kind,data=data)
            with patch.object(NativeQueryService,'get_'+kind,return_value=dto,create=True) as owner, \
                 patch.object(NativeQueryService,'get_attempt',side_effect=AssertionError('unexpected nested read')):
                response=self.client.get(base+'/'+kind)
                self.assertEqual(response.status_code,200);self.assertEqual(response.json(),dto)
                owner.assert_called_once_with('one','attempt')
        self.assertEqual(self.client.get(base).content,before)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),digest)

    def test_absent_owner_confirms_membership_and_reports_unavailable(self):
        for kind in ('lifecycle','populations'):
            with patch.object(NativeQueryService,'get_'+kind,None,create=True):
                result=self.client.get('/api/v1/native/sources/one/attempts/attempt/'+kind)
                self.assertEqual(result.status_code,200)
                self.assertEqual(result.json()['data']['reason'],'backend-unavailable')
                self.assertIsNone(result.json()['data']['result'])
                self.assertEqual(self.client.get('/api/v1/native/sources/other/attempts/attempt/'+kind).status_code,404)
                self.assertEqual(self.client.get('/api/v1/native/sources/one/attempts/foreign/'+kind).status_code,404)

    def test_method_origin_auth_and_payload_guards_precede_owner(self):
        for kind in ('lifecycle','populations'):
            url='/api/v1/native/sources/one/attempts/attempt/'+kind
            with patch.object(NativeQueryService,'get_'+kind,side_effect=AssertionError('must not read'),create=True) as owner:
                for response in (self.client.post(url,json={}),self.client.get(url+'?path=secret'),
                                 self.client.request('GET',url,content=b'{}'),
                                 self.client.get(url,headers={'authorization':'Bearer wrong'}),
                                 self.client.get(url,headers={'origin':'https://foreign.example'})):
                    self.assertGreaterEqual(response.status_code,400)
                owner.assert_not_called()

    def test_safe_errors_no_internal_paths(self):
        for kind in ('lifecycle','populations'):
            url='/api/v1/native/sources/one/attempts/attempt/'+kind
            for error,status in [(QueryError('invalid-evidence'),409),(RuntimeError('/private/raw.log'),500)]:
                with patch.object(NativeQueryService,'get_'+kind,side_effect=error,create=True):
                    r=self.client.get(url);self.assertEqual(r.status_code,status);self.assertNotIn('/private',r.text)

    def test_unregistered_reads_with_effect_tripwires(self):
        from auto_g16.core import SQLiteRuntimeStore
        import socket
        import subprocess
        with patch.object(SQLiteRuntimeStore, '_transaction', side_effect=AssertionError('write forbidden')), \
             patch.object(subprocess, 'Popen', side_effect=AssertionError('process forbidden')), \
             patch.object(socket, 'create_connection', side_effect=AssertionError('remote forbidden')):
            for kind in ('lifecycle', 'populations'):
                response=self.client.get('/api/v1/native/sources/one/attempts/attempt/'+kind)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json()['data']['availability'],'unavailable')
                self.assertIn(response.json()['data']['reason'],('not-registered','backend-unavailable'))
