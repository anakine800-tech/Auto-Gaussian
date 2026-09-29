"""Freq resource tuple offline qualification, explicitly not target evidence."""
from hashlib import sha256
import json
import unittest
from unittest.mock import patch
from auto_g16 import execution
from auto_g16.execution import program, _program_completion as completion
from auto_g16.execution import _gaussian_freq_resources as owner
from auto_g16.transport import _gaussian_freq_submit as submit
from auto_g16.execution._program_artifacts import _stage_material
from auto_g16.execution.readonly import ProgramReadSnapshot
from tests.v31.transport import test_gaussian_successor as fixture

INPUT=('%chk=gaussian.chk\n%mem=12GB\n%nprocshared=8\n'+owner.ROUTE+'\n\nsynthetic\n\n0 1\nC 0 0 0\n\n').encode()

class FrequencyResourcesTests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.GaussianSuccessorTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
    def case(self,**changes):
        return self.f.qualified_case(**dict(startup='freq-resource',input_raw=INPUT,headroom_mib=4096,resource_memory_mb=16384,**changes))
    def test_complete_tuple_restore_stage_loader_and_installation(self):
        current,target,q,evidence,spec,service,binding,material,snapshot=self.case()
        self.assertEqual(spec.adapter_contract_version,7)
        self.assertEqual(spec.program_data['stage'],'freq')
        self.assertEqual(program._decode_program_review_semantics(snapshot._approval_semantics()),snapshot)
        raw=completion._receipt_json(snapshot._approval_semantics())
        self.assertEqual(ProgramReadSnapshot(content=raw,sha256=sha256(raw).hexdigest()).attempt_id,snapshot.attempt_id)
        stage=_stage_material(snapshot,input_bytes={'flow.gjf':INPUT},scheduler_artifact_bytes={a['portable_name']:a['content_utf8'].encode() for a in snapshot.scheduler_artifacts})
        self.assertEqual(stage[0][1],INPUT)
        self.f.installed_case(current,target,q,evidence,snapshot)
        compile(owner._DECODED_LOADER_SOURCE,'freq-loader','exec');compile(submit.source_bytes(),'freq-bootstrap','exec')
        submit.assert_submit_timeout_contract()
    def test_closed_route_resource_and_old_tuple_rejection(self):
        def validate(raw):return program._validate_gaussian_input('freq.gjf',raw,{'stage':'freq'},resource_link0=True,freq_resource=True)
        self.assertEqual(validate(INPUT)['cores'],8)
        for token in (b'Freq Opt',b'Freq=ReadFC',b'Freq Geom=AllCheck',b'Freq Guess=Read',b'Freq SCRF=Water'):
            with self.subTest(token=token),self.assertRaises(ValueError):validate(INPUT.replace(b'Freq',token))
        for raw in (INPUT.replace(b'%mem=12GB\n',b''),INPUT+b'--Link1--\n',INPUT.replace(b'%nprocshared=8',b'%nprocshared=0'),INPUT.replace(b'Def2SVP',b'STO-3G')):
            with self.assertRaises(ValueError):validate(raw)
        with self.assertRaises(ValueError):program._validate_gaussian_input('freq.gjf',INPUT,{'stage':'freq'},resource_link0=True)
        with self.assertRaises(ValueError):program._validate_gaussian_input('freq.gjf',INPUT,{'stage':'freq'})
    def test_old_owners_do_not_route_to_freq(self):
        with patch.object(completion,'_freq_owner',side_effect=AssertionError('historical tuple selected Freq')):
            for startup in (None,True,'file','resource'):
                kwargs={} if startup!='resource' else dict(input_raw=INPUT.replace(b'Freq',b'Opt'),headroom_mib=4096,resource_memory_mb=16384)
                kwargs['startup']=startup
                snapshot=self.f.qualified_case(**kwargs)[-1]
                snapshot.assert_identity_closed()
    def test_resource_and_q_mismatch_reject(self):
        _,_,q,_,spec,_,_,_,snapshot=self.case()
        request=execution.ResolvedResourceRequest(resource_spec=self.f.store.load_resource_spec('resource-1'),cores=8,memory_mb=12288,walltime_seconds=3600,queue='simple')
        with self.assertRaises(ValueError):program._validate_gaussian_resource_binding(spec,request)
        for field,value in (('adapter_contract_version',6),('stage','opt')):
            candidate=json.loads(json.dumps(q))
            # Scope is owned by qualification; an otherwise self-consistent payload is insufficient.
            if field=='stage':candidate['scope']['operations']=['opt']
            else:candidate['scope']['adapter_contract_version']=value
            with self.assertRaises(ValueError):completion._decode_publisher_qualification(completion._receipt_json({'payload':candidate,'payload_sha256':completion.semantic_sha256(candidate)}))

    def test_rendered_freq_wrapper_real_inert_child_and_rejection_gates(self):
        import subprocess,sys
        from pathlib import Path
        # Reuse the six original wrapper scenarios in a dedicated process, with
        # the exact new wrapper bytes and a stdin-echo child. No Gaussian/PBS.
        script='''
import unittest
from tests.v31.transport import test_gaussian_opt_resources as old
from tests.v31.transport.test_gaussian_freq_resources import INPUT,owner
class FreqWrapper(old.GaussianOptResourceBindingTests):
    def case(self,**kwargs):
        return self.qualified_case(startup='freq-resource',input_raw=INPUT,headroom_mib=4096,resource_memory_mb=16384,**kwargs)
old.INPUT=INPUT
old.resources=owner
result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite([FreqWrapper('_check_rendered_wrapper_real_inert_child')]))
raise SystemExit(not result.wasSuccessful())
'''
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=Path(__file__).resolve().parents[3],capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_installed_freq_driver_wire_single_intent_and_no_replay(self):
        from tests.v31.transport import test_gaussian_short_entry as delivery
        from auto_g16.transport.program import _ProgramTransportStore
        f=self.f;root=f.root/'freq-installed-effects';root.mkdir()
        f.program_transport_store=_ProgramTransportStore._create_completion_store(root/'transport.sqlite3',approved_root=root)
        self.addCleanup(f.program_transport_store.close)
        f.execute=lambda:delivery.ShortEntryCompositionTests.execute(f)
        delivery.ShortEntryCompositionTests._check_installed_gaussian_delivery(f,startup_mode='freq-resource',input_raw=INPUT,
            resource_kwargs={'headroom_mib':4096,'resource_memory_mb':16384})
