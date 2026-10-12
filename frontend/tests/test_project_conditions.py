import json
from hashlib import sha256
from pathlib import Path
import unittest
from unittest.mock import patch
from autog_frontend.conditions import extract,validate
from autog_frontend.project_catalog import ProjectLibrary
from autog_frontend.library import capture_completed
from auto_g16.query import QueryService
from . import test_library_upgrade as fixture

LOG=b''' Entering Gaussian System, Link 0=g16
 -------------------------------
 #p B3LYP/6-31G(d) Opt SCRF
 =(SMD,Solvent=Toluene)
 -------------------------------
 Symbolic Z-matrix:
 Charge = 0 Multiplicity = 1
 H 0 0 0
 Standard basis: 6-31G(d) (6D, 7F)
 Error termination via Lnk1e in l9999
 (Enter /g16/l1.exe)
 Link1:  Proceeding to internal job step number  2.
 -------------------------------
 #p M06L/def2SVP Freq Geom=AllCheck
 -------------------------------
 Temperature   298.150 Kelvin.  Pressure   1.00000 Atm.
'''
INPUT=b'''#p B3LYP/GenECP Opt

Two elements

0 1
C 0 0 0
Cu 0 0 1

C H 0
6-31G(d)
****
Cu 0
LANL2DZ
****

Cu 0
LANL2DZ

--Link1--
#p M06L/def2SVP Freq Geom=AllCheck

'''
class ConditionTests(unittest.TestCase):
 def test_failure_does_not_hide_conditions_and_no_cross_step_inheritance(self):
  p=extract(LOG,'test.log');self.assertEqual(len(p['steps']),2)
  a,b=p['steps'];self.assertEqual(a['fields']['method'][0]['value'],'B3LYP');self.assertEqual(a['fields']['environment'][0]['value'],'(SMD,Solvent=Toluene)')
  self.assertEqual(b['fields']['charge'],[]);self.assertEqual(b['fields']['environment'],[]);self.assertEqual(b['fields']['temperature_k'][0]['value'],298.15)
  for s in p['steps']:
   for e in [s['route'],*sum(s['fields'].values(),[])]:
    span=e['source_span'];self.assertIn(str(e['value']).encode().split(b' ')[0],LOG[span['start']:span['end']]) if e['evidence_kind']=='printed-standard-basis' else None
  validate(p,dict(sha256=sha256(LOG).hexdigest(),size_bytes=len(LOG)),'test.log')
 def test_input_mixed_basis_ecp_preserved_by_element_separate_steps(self):
  p=extract(INPUT,'test.gjf',input_file=True);self.assertEqual(len(p['steps']),2);s=p['steps'][0]
  self.assertEqual([b['selectors'] for b in s['basis_blocks']],[['C','H'],['Cu']]);self.assertEqual(s['ecp_blocks'][0]['selectors'],['Cu']);self.assertEqual(s['fields']['basis'][0]['value'],'GenECP');self.assertEqual(p['steps'][1]['basis_blocks'],[])
  self.assertEqual(s['fields']['charge'][0]['value'],0)
 def test_route_in_body_cannot_create_extra_step_and_spans_tamper_rejected(self):
  p=extract(LOG+b' ---------\n #p fake/fake\n ---------\n','t.log');self.assertEqual(len(p['steps']),2)
  p['steps'][0]['route']['source_span']['sha256']='0'*64
  with self.assertRaises(ValueError):validate(p,dict(sha256=sha256(LOG).hexdigest(),size_bytes=len(LOG)))
 def test_crlf_unicode_byte_offsets_and_partial_route(self):
  raw=b' Entering Gaussian System, Link 0=g16\r\n'+ ' 中文标题\r\n'.encode()+b' --------\r\n #p HF/STO-3G\r\n --------\r\n Charge = -1 Multiplicity = 2\r\n'
  p=extract(raw,'test.log');e=p['steps'][0]['fields']['charge'][0];self.assertEqual(raw[e['source_span']['start']:e['source_span']['end']],b' Charge = -1 Multiplicity = 2\r\n')
  self.assertEqual(extract(b' Entering Gaussian System, Link 0=g16\n ------\n #p HF/STO-3G','x.log')['steps'],[])
 def test_printed_general_basis_and_ecp_keep_center_tables(self):
  raw=LOG.split(b' Error termination')[0]+b' General basis read from cards: (5D, 7F)\n C H 0\n 6-31G(d)\n ****\n Cu 0\n LANL2DZ\n ****\n Leave Link  301\n Pseudopotential Parameters\n Center Atomic Valence\n 2 29 19\n Leave Link  301\n'
  p=extract(raw,'mixed.log');self.assertIn('Cu 0',p['steps'][0]['basis_blocks'][0]['value']);self.assertIn('2 29 19',p['steps'][0]['ecp_blocks'][0]['value'])

class ProjectConditionIntegration(unittest.TestCase):
 setUp=fixture.LibraryUpgradeTests.setUp
 write=fixture.LibraryUpgradeTests.write
 ref=fixture.LibraryUpgradeTests.ref
 def test_import_conditions_groups_workflow_without_core_mutation_or_get_parse(self):
  folder=self.source/'study-A';folder.mkdir();(folder/'failed.log').write_bytes(LOG);(folder/'input.gjf').write_bytes(INPUT)
  (folder/'submission-intent.json').write_text(json.dumps(dict(schema='gaussian-submission-intent/1',project='declared-project',input_sha256=sha256(INPUT).hexdigest(),attempt_id='historic-attempt',reserved_at='2026-09-25T00:00:00Z')))
  capture_completed(self.source,self.manager.config);self.manager.run_once();self.assertEqual(self.manager.status()['jobs'][0]['state'],'archived')
  a,q=self.manager.queries();identity='archive-'+sha256(LOG).hexdigest()
  with patch('autog_frontend.conditions.extract',side_effect=AssertionError('GET parse')):
   d=q.get_conditions(identity);self.assertEqual(len(d['observed']['steps']),2);self.assertEqual(len(d['declarations']),1)
   workflow=q.get_workflow(identity);self.assertEqual(next(x for x in workflow['items'] if x['stage']=='submission-intent')['stage'],'submission-intent');self.assertEqual(next(x for x in workflow['items'] if x['stage']=='submission-intent')['input_binding'],'sha256-verified');self.assertEqual(next(x for x in workflow['items'] if x['stage']=='submission-intent')['log_binding'],'unknown')
   groups,rows=ProjectLibrary(None,q).snapshots();g=next(x for x in groups.values() if x['label']=='study-A');self.assertEqual(g['count'],1);self.assertEqual(g['state_counts']['unparseable'],1);self.assertEqual(g['issue_archive_ids'],[identity]);self.assertEqual(g['archive_ids'],[identity]);self.assertIn(identity,rows[g['id']]);self.assertEqual(a.get_archive(identity)['data']['parser']['status'],'unparseable')
  self.assertFalse((self.root/'nonexistent-Core.sqlite').exists())
  entry=q._entry('archive',identity);Path(entry['conditions']['path']).write_text('{}')
  with self.assertRaises(Exception):q.get_conditions(identity)

class ProjectIndexMetadata(unittest.TestCase):
 def test_content_fingerprint_changes_only_with_index_content(self):
  class Core:
   def list_projects(self):return {'data':{'items':[]}}
  q=ProjectLibrary(Core(),None)
  q.snapshots=lambda: ({'g':{'id':'g','label':'a'}},{'g':{'a':{'captured_at':'2026-09-26T12:00:00Z'}}})
  a=q.list_projects();b=q.list_projects()
  self.assertEqual(a['snapshot']['content_sha256'],b['snapshot']['content_sha256'])
  self.assertEqual(a['snapshot']['latest_archive_capture'],'2026-09-26T12:00:00Z')
  q.snapshots=lambda: ({'g':{'id':'g','label':'b'}},{})
  self.assertNotEqual(a['snapshot']['content_sha256'],q.list_projects()['snapshot']['content_sha256'])
