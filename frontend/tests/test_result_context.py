import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from auto_g16 import core
from auto_g16.result import ResultProvenanceService
from autog_frontend.archive import ArchiveQuery
from autog_frontend.details import DetailQuery, full_result
from autog_frontend.result_context import PLAN_SCHEMA, bind_result, native_context
from .mode_review_fixture import ID, add_mode_review_fixture
from .result_fixture import add_result_fixtures

INTENT={'schema':PLAN_SCHEMA,'method':{'electronic_structure_method':'B3LYP','basis':'STO-3G','environment':'gas_phase','dispersion':'none'},'molecule':{'charge':0,'multiplicity':1}}


class ResultContextTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name).resolve();self.db=self.root/'core.sqlite3'
        with core.SQLiteRuntimeStore(self.db) as store:
            add_result_fixtures(store);add_mode_review_fixture(store,self.root,intent=INTENT)
            store.store_calculation_plan(core.CalculationPlan(calculation_plan_id='unbound-later-plan',task_id=ID,revision=2,intent={**INTENT,'method':{'electronic_structure_method':'DO-NOT-SELECT'}}))
        self.query=DetailQuery(self.db,ArchiveQuery(None,None))

    def project(self, intent):
        with core.SQLiteRuntimeStore.read_snapshot(self.db) as store:
            a=store.load_attempt(ID);v=ResultProvenanceService(store).current_view(ID);p=replace(store.load_calculation_plan(ID),intent=intent);o=v.selected_results[-1];e=next(e for e in v.envelopes if e.observation_id==v.selected_envelope_id)
            return bind_result(native_context(store,a),p,v.input_binding,o,full_result(o)['source'],e)

    def test_exact_snapshot_chain_and_bound_plan_not_latest_no_effects(self):
        before={p:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        with patch('subprocess.Popen',side_effect=AssertionError('process')),patch('autog_frontend.archive_import.GaussianJobParser.parse',side_effect=AssertionError('parse')):
            d=self.query.get_details('attempt',ID);c=d['context']
        self.assertEqual(c['lineage']['project_id'],'gaussian-demo');self.assertEqual(c['lineage']['task_id'],ID)
        self.assertEqual(c['lineage']['result_source'],d['result']['source']);self.assertEqual(c['plan']['calculation_plan_id'],ID)
        f=c['conditions']['declared'];self.assertEqual(f['method']['value'],'B3LYP');self.assertEqual(f['charge']['value'],0)
        self.assertEqual(f['environment']['source']['field_path'],'intent.method.environment')
        self.assertEqual(c['conditions']['observed']['method']['availability'],'unavailable');self.assertEqual(c['comparison_status'],'not-assessed')
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertNotIn(str(self.root),json.dumps(c));self.assertEqual(c,self.query.get_details('attempt',ID)['context'])

    def test_missing_environment_is_unknown_not_gas_or_default_temperature(self):
        intent=copy.deepcopy(INTENT);del intent['method']['environment'];c=self.project(intent)
        self.assertEqual(c['conditions']['declared']['environment']['availability'],'missing')
        self.assertIsNone(c['conditions']['declared']['environment']['value'])
        self.assertEqual(c['conditions']['declared']['temperature_k']['availability'],'unavailable')
        self.assertTrue(all(f['availability']=='unavailable' for f in c['conditions']['observed'].values()))

    def test_unsupported_schema_and_bad_scalars_do_not_gain_condition_authority(self):
        for intent in ({**INTENT,'schema':'future/2'},{'method':'B3LYP','basis':'STO-3G'}):
            c=self.project(intent);self.assertTrue(all(f['availability']=='unavailable' for f in c['conditions']['declared'].values()))
        intent=copy.deepcopy(INTENT);intent['molecule']['charge']=False;intent['molecule']['multiplicity']=0;intent['method']['basis']={'name':'STO-3G'}
        c=self.project(intent)
        for k in ('charge','multiplicity','basis'):self.assertEqual(c['conditions']['declared'][k]['reason'],'invalid-declared-condition')

    def test_chain_mismatches_are_refused_and_plan_digest_tracks_content(self):
        with core.SQLiteRuntimeStore.read_snapshot(self.db) as store:
            a=store.load_attempt(ID);v=ResultProvenanceService(store).current_view(ID);p=store.load_calculation_plan(ID);o=v.selected_results[-1];e=next(e for e in v.envelopes if e.observation_id==v.selected_envelope_id)
            for bad_plan,bad_envelope in ((replace(p,task_id='other-task'),e),(replace(p,revision=2),e),(p,replace(e,input_binding_observation_id='other-input'))):
                with self.assertRaises(ValueError):bind_result(native_context(store,a),bad_plan,v.input_binding,o,full_result(o)['source'],bad_envelope)
        changed=copy.deepcopy(INTENT);changed['method']['basis']='another-basis'
        self.assertNotEqual(self.project(INTENT)['plan']['plan_sha256'],self.project(changed)['plan']['plan_sha256'])

    def test_unsupported_result_keeps_real_parents_but_no_result_or_plan_guess(self):
        c=self.query.get_details('attempt','gaussian-v31')['context']
        self.assertEqual(c['lineage']['project_id'],'gaussian-demo');self.assertIsNone(c['lineage']['result_source']);self.assertIsNone(c['plan']);self.assertIsNone(c['input'])
        self.assertTrue(all(f['availability']=='unavailable' for f in c['conditions']['declared'].values()))

    def test_older_supported_summary_with_unavailable_full_result_preserves_details_and_log(self):
        from auto_g16.result import GaussianJobParser, GaussianResultQuery
        from autog_frontend.archive_import import plain
        from .result_fixture import PREFIX, FREQUENCY
        from .mode_review_fixture import reference
        db=self.root/'older.sqlite3';original=GaussianJobParser.parse
        def old_parse(parser,*args,**kwargs):
            outcome=original(parser,*args,**kwargs)
            if outcome.parse_status.value!='parsed':return outcome
            facts=plain(outcome.facts);facts['grammar_id']='auto-g16-v3-gaussian-job-grammar/1'
            return replace(outcome,parser_version='1.0.0',facts=facts)
        with core.SQLiteRuntimeStore(db) as store,patch.object(GaussianJobParser,'parse',old_parse):add_result_fixtures(store)
        log=self.root/'synthetic.log';raw=PREFIX+FREQUENCY+b' Normal termination of Gaussian 16\n';log.write_bytes(raw)
        catalog=self.root/'old-catalog.json';catalog.write_text(json.dumps({'schema':'auto-g16-local-evidence-catalog/1','entries':[{'kind':'attempt','id':'gaussian-normal','log':reference(log)}]}))
        q=DetailQuery(db,ArchiveQuery(None,None),catalog,reference(catalog)['sha256'])
        with core.SQLiteRuntimeStore.read_snapshot(db) as store:self.assertEqual(GaussianResultQuery(store).get_summary('gaussian-normal')['availability'],'available')
        d=q.get_details('attempt','gaussian-normal');self.assertEqual(d['result']['availability'],'unavailable')
        self.assertEqual(d['context']['lineage']['project_id'],'gaussian-demo');self.assertIsNone(d['context']['plan'])
        self.assertEqual(q.get_log('attempt','gaussian-normal')['log']['data']['text'],raw.decode())
