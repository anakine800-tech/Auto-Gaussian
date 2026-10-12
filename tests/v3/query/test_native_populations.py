"""Closed saved-population query, source isolation and zero-compute projection."""
from dataclasses import replace
from pathlib import Path
import json
import unittest
from unittest.mock import patch

from auto_g16.query import NativeSource, NativeQueryService, QueryError
from auto_g16.conformer import populations_readonly as saved
from auto_g16.thermochemistry import native_populations as builder
from tests.v31.conformer import test_native_populations as population_fixture
from tests.v31.conformer import test_successor_freq as native_fixture
from tests.v31.conformer import test_thermochemistry_readonly as pair_fixture


class PopulationQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = population_fixture.NativePopulationTests()
        cls.harness.setUpClass()
        cls.addClassCleanup(cls.harness.doClassCleanups)
        cls.harness.setUp()
        cls.addClassCleanup(cls.harness.doCleanups)
        cls.artifact=cls.harness.build()
        binding=cls.harness.save(cls.artifact)
        cls.reader=saved.NativePopulationReadout(thermodynamic_readout=cls.harness.reader,artifact=binding)

    def source(self, index=0, **changes):
        thermo=self.reader.thermodynamic_readout
        selected=thermo.readout.frequency_sources[index]
        values=dict(source_id='member-'+str(index),database=Path(selected.revision.path),
            snapshots=(selected.snapshot,),freq_readout=thermo.readout,thermodynamic_readout=thermo,
            population_readout=self.reader)
        return NativeSource(**{**values,**changes})

    def test_saved_projection_zero_compute_and_detached_whitelist(self):
        sources=(self.source(),self.source(1));query=NativeQueryService(sources)
        with native_fixture.inert_thermo_owners(),pair_fixture.no_computation(), \
                patch.object(builder,'build_native_populations',side_effect=AssertionError('builder called')), \
                patch.object(builder,'_scheme',side_effect=AssertionError('math called')), \
                patch.object(saved,'save_native_populations',side_effect=AssertionError('save called')):
            values=[query.get_populations(s.source_id,s.snapshots[0].attempt_id) for s in sources]
        for index,value in enumerate(values):
            self.assertEqual(set(value),{'schema','kind','data'})
            self.assertEqual(value['schema'],'auto-g16-native-populations-query/1')
            self.assertEqual(value['kind'],'populations')
            data=value['data'];self.assertEqual(data['availability'],'available')
            self.assertEqual(data['selected_member_id'],('anti','gauche')[index])
            result=data['result'];self.assertEqual([r['is_selected'] for r in result['members']],[index==0,index==1])
            self.assertEqual(result['scientific_acceptance'],'unavailable')
            for member,expected in zip(result['members'],self.artifact['payload']['members']):
                for scheme in ('rrho','qrrho'):self.assertEqual(member[scheme],expected[scheme])
                self.assertEqual(set(member['source']),{'optimization_attempt_id','frequency_attempt_id',
                    'two_stage_minimum_authority_id','optimization_parsed_result','optimization_result_source',
                    'frequency_parsed_result','frequency_result_source'})
            encoded=json.dumps(value)
            for private in ('source_provenance','parent_chain','file_identity','transport_root',str(self.harness.root)):
                self.assertNotIn(private,encoded)
        values[0]['data']['result']['members'][0]['rrho']['normalized_population']=0
        self.assertNotEqual(values[1]['data']['result']['members'][0]['rrho']['normalized_population'],0)

    def test_registration_foreign_attempt_and_unregistered_zero_read(self):
        source=self.source();query=NativeQueryService((source,))
        with self.assertRaisesRegex(QueryError,'invalid-population-registration'):
            self.source(thermodynamic_readout=None)
        wrong=replace(self.reader,thermodynamic_readout=replace(self.reader.thermodynamic_readout,
            artifact=replace(self.reader.thermodynamic_readout.artifact,sha256='0'*64)))
        with self.assertRaisesRegex(QueryError,'invalid-population-registration'):self.source(population_readout=wrong)
        with patch.object(saved.NativePopulationReadout,'read',side_effect=AssertionError('read called')):
            for sid,aid in [('absent',source.snapshots[0].attempt_id),(source.source_id,'foreign')]:
                with self.assertRaisesRegex(QueryError,'not-found'):query.get_populations(sid,aid)
            absent=NativeQueryService((replace(source,population_readout=None),))
            value=absent.get_populations(source.source_id,source.snapshots[0].attempt_id)
            self.assertEqual(value['data']['reason'],'not-registered');self.assertIsNone(value['data']['result'])

    def test_old_thermodynamics_and_inventory_remain_unchanged(self):
        source=self.source();new=NativeQueryService((source,));old=NativeQueryService((replace(source,population_readout=None),))
        with native_fixture.inert_thermo_owners(),pair_fixture.no_computation(), \
                patch.object(saved.NativePopulationReadout,'read',side_effect=AssertionError('old route read population')):
            self.assertEqual(new.list_sources(),old.list_sources())
            self.assertEqual(new.list_projects(),old.list_projects())
            self.assertEqual(new.get_thermodynamics(source.source_id,source.snapshots[0].attempt_id),
                             old.get_thermodynamics(source.source_id,source.snapshots[0].attempt_id))
