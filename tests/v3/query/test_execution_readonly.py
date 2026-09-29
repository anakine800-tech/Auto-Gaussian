"""Detached reader checks against owning synthetic completion fixture."""
import copy
from dataclasses import replace
from hashlib import sha256
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from auto_g16.execution import program, program_runtime
from auto_g16.execution.readonly import ProgramReadSnapshot, ProgramReadQuery
from auto_g16.execution._identity import canonical_bytes
from tests.v31.transport import test_program_completion as fixture


def registration(snapshot):
    content = fixture.completion._receipt_json(snapshot._approval_semantics())
    return ProgramReadSnapshot(content=content, sha256=sha256(content).hexdigest())


class ExecutionReadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.CompletionTests('test_success_durable_bundle_and_zero_read_replay')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.execute(); self.fixture.publish(); self.fixture.collect()
        self.registration = registration(self.fixture.snapshot)

    def test_opt_read_slot_timeout_is_unavailable_not_invalid_evidence(self):
        from auto_g16.conformer.readonly import OptReadBusy
        from auto_g16.query import NativeQueryService, QueryError
        # Inject only the read-owner outcome; actual Core and detached Execution
        # facts still come from the existing qualified completion fixture.
        query = object.__new__(NativeQueryService)
        reader = SimpleNamespace(read=lambda *_: (_ for _ in ()).throw(OptReadBusy('occupied')))
        query._sources = {'native': SimpleNamespace(snapshots=(self.registration,), opt_readout=reader, freq_readout=None)}
        with self.assertRaises(QueryError) as error:
            query._attempt(self.fixture.store, 'native', 'attempt-1')
        self.assertEqual(error.exception.code, 'store-unavailable')

    def test_detached_reader_does_not_render_parse_or_claim(self):
        with patch.object(program, '_render_scheduler_artifact', side_effect=AssertionError('render')), patch.object(program_runtime, '_assert_effect_intent_replay', side_effect=AssertionError('claim')), patch.object(fixture.completion, '_output_closure', side_effect=AssertionError('parse')), patch('builtins.open', side_effect=AssertionError('open')):
            value = ProgramReadQuery(self.fixture.store).get_summary(self.registration)
        self.assertEqual(value['program'], 'xtb')
        self.assertEqual(value['bound_plan'], {'id':'plan-1', 'revision':1})
        self.assertIsNotNone(value['capture'])
        self.assertEqual(value['capture']['job_id'], '123.server')
        self.assertNotIn('content_base64', json.dumps(value))
        self.assertNotIn('/home/', json.dumps(value))
        self.assertEqual(value['scientific_facts'], 'not-recorded')

    def test_registration_digest_rejects_change(self):
        with self.assertRaises(ValueError):
            replace(self.registration, content=self.registration.content + b' ')

    def test_unknown_adapter_rejected(self):
        raw = json.loads(self.registration.content)
        raw['program_execution_spec']['adapter_contract_version'] = 900
        content = json.dumps(raw).encode()
        with self.assertRaises(ValueError):
            ProgramReadSnapshot(content=content, sha256=sha256(content).hexdigest())

    def test_content_edit_without_snapshot_rebinding_rejected(self):
        raw = json.loads(self.registration.content)
        artifact = raw['scheduler_artifacts'][0]
        artifact['content_utf8'] += '# historical difference\n'
        artifact['size_bytes'] = len(artifact['content_utf8'].encode())
        artifact['sha256'] = sha256(artifact['content_utf8'].encode()).hexdigest()
        content = json.dumps(raw).encode()
        with self.assertRaises(ValueError):
            ProgramReadSnapshot(content=content, sha256=sha256(content).hexdigest())

    def test_core_intent_mismatch_rejected(self):
        with patch.object(self.fixture.store, 'load_submission_intent', return_value='wrong'):
            with self.assertRaises(ValueError):
                ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_duplicate_completion_rejected(self):
        records = self.fixture.store.results_for_attempt('attempt-1')
        with patch.object(self.fixture.store, 'results_for_attempt', return_value=records + records):
            with self.assertRaises(ValueError):
                ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_orphan_assessment_rejected(self):
        with patch.object(self.fixture.store, 'results_for_attempt', return_value=()):
            with self.assertRaises(ValueError):
                ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_wrong_core_plan_rejected(self):
        value = self.fixture.store.load_calculation_plan('plan-1')
        with patch.object(self.fixture.store, 'load_calculation_plan', return_value=replace(value, revision=2)):
            with self.assertRaises(ValueError):
                ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_rehashed_foreign_request_binding_rejected(self):
        records = self.fixture.store.observations_for_attempt('attempt-1')
        target = next(r for r in records if r.observation_type == fixture.transport._RECEIPT_TYPE)
        data = json.loads(fixture.completion._receipt_json(target.data))
        data['request']['binding']['workspace_binding_id'] = 'wrong-workspace'
        data['request_sha256'] = fixture.transport._digest(data['request'])
        changed = replace(target, observation_id=fixture.transport._identity('effect-receipt', data), data=data)
        with patch.object(self.fixture.store, 'observations_for_attempt', return_value=tuple(changed if r == target else r for r in records)):
            with self.assertRaises(ValueError):
                ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_historical_script_change_does_not_relax_execution_decoder(self):
        from auto_g16.execution._identity import semantic_id
        raw = json.loads(self.registration.content)
        artifact = raw['scheduler_artifacts'][0]
        artifact['content_utf8'] += '# historical revision\n'
        artifact['size_bytes'] = len(artifact['content_utf8'].encode())
        artifact['sha256'] = sha256(artifact['content_utf8'].encode()).hexdigest()
        payload = {k:raw[k] for k in program._SNAPSHOT_PAYLOAD_FIELDS}
        raw['effect_intent_id'] = semantic_id('program-effect-intent', payload)
        raw['program_execution_snapshot_id'] = semantic_id('program-execution-snapshot', {'effect_intent_id':raw['effect_intent_id'], **payload})
        content = json.dumps(raw).encode()
        registered = ProgramReadSnapshot(content=content, sha256=sha256(content).hexdigest())
        self.assertEqual(registered.attempt_id, 'attempt-1')
        with self.assertRaises(ValueError):
            program._decode_program_review_semantics(raw)

    def test_unknown_result_is_unavailable_not_absent(self):
        from auto_g16.core import Result
        values = self.fixture.store.results_for_attempt('attempt-1')
        extra = Result(result_id='future',attempt_id='attempt-1',result_type='future-native-facts/2',data={})
        with patch.object(self.fixture.store, 'results_for_attempt', return_value=(*values, extra)):
            value = ProgramReadQuery(self.fixture.store).get_summary(self.registration)
        self.assertEqual(value['scientific_facts'], 'unsupported-native-result-contract')

    def _read_with(self, observations, results=None):
        values = self.fixture.store.results_for_attempt('attempt-1') if results is None else results
        with patch.object(self.fixture.store, 'observations_for_attempt', return_value=tuple(observations)), patch.object(self.fixture.store, 'results_for_attempt', return_value=tuple(values)):
            return ProgramReadQuery(self.fixture.store).get_summary(self.registration)

    def test_later_stat_and_fetch_drift_reach_specific_rejection(self):
        from auto_g16.core import Observation
        records = self.fixture.store.observations_for_attempt('attempt-1')
        receipts = [r for r in records if r.observation_type == fixture.transport._RECEIPT_TYPE]
        for operation in ('STAT_EXACT_FILE', 'FETCH_EXACT_FILE'):
            with self.subTest(operation=operation):
                target = next(r for r in reversed(receipts) if r.data['operation'] == operation and r.data['response'].get('presence', 'present') == 'present')
                data = json.loads(fixture.completion._receipt_json(target.data))
                data['effect_sequence'] = len(receipts) + 1
                if operation == 'STAT_EXACT_FILE':
                    data['response']['file_physical_token'] = 'different-token'
                else:
                    data['response']['sha256'] = '0' * 64
                changed = Observation(observation_id=fixture.transport._identity('effect-receipt', data),attempt_id='attempt-1',observation_type=target.observation_type,data=data)
                with self.assertRaisesRegex(ValueError, 'late-capture-evidence-drift'):
                    self._read_with((*records, changed))

    def test_terminal_assessment_digest_and_capture_mismatch_reach_rejection(self):
        from auto_g16.execution._identity import semantic_id
        records = self.fixture.store.observations_for_attempt('attempt-1')
        target = records[-1]
        self.assertEqual(target.observation_type, program_runtime._COMPLETION_ASSESSMENT)
        self.assertIsNotNone(self._read_with(records)['capture'])
        for key, value in (('receipt_sha256', '0' * 64), ('capture_authority_id', 'foreign-capture')):
            with self.subTest(key=key):
                data = dict(target.data);data[key] = value
                changed = replace(target, observation_id=semantic_id('program-completion-assessment',data),data=data)
                with self.assertRaisesRegex(ValueError, 'terminal-assessment-capture-mismatch'):
                    self._read_with((*records[:-1],changed))

    def test_metadata_mismatch_with_reclosed_outer_evidence_reaches_rejection(self):
        import base64
        from auto_g16.execution._identity import semantic_id
        records = self.fixture.store.observations_for_attempt('attempt-1')
        original = self.fixture.store.results_for_attempt('attempt-1')[0]
        result_data = json.loads(fixture.completion._receipt_json(original.data))
        member = result_data['captured_files'][0]
        metadata = json.loads(base64.b64decode(member['content_base64']))
        metadata['program_execution_spec_payload_sha256'] = '0' * 64
        content = fixture.completion._receipt_json(metadata)
        self.assertEqual(len(content), member['size_bytes'])
        member['content_base64'] = base64.b64encode(content).decode()
        member['sha256'] = sha256(content).hexdigest()
        changed_fetch_id = member['fetch_observation_id']
        remap, revised = {}, []
        def mapped(value):
            if isinstance(value, dict):return {k:mapped(v) for k,v in value.items()}
            if isinstance(value, list):return [mapped(v) for v in value]
            return remap.get(value,value) if isinstance(value,str) else value
        for record in records:
            data = mapped(json.loads(fixture.completion._receipt_json(record.data)))
            if record.observation_type == fixture.transport._RECEIPT_TYPE:
                if record.observation_id == changed_fetch_id:data['response']['sha256'] = member['sha256']
                data['request_sha256'] = fixture.transport._digest(data['request'])
                identity = fixture.transport._identity('effect-receipt', data)
            elif record.observation_type == program_runtime._COMPLETION_ASSESSMENT:
                # The completion Result is persisted before the terminal assessment.
                revised_data = mapped(result_data)
                result = replace(original, result_id=semantic_id('program-completion-evidence',revised_data), data=revised_data)
                data['evidence_result_id'] = result.result_id
                data['observation_prefix_sha256'] = program_runtime._observation_prefix(tuple(revised))
                data['receipt_sha256'] = member['sha256']
                identity = semantic_id('program-completion-assessment',data)
            else:
                identity = record.observation_id
            remap[record.observation_id] = identity
            revised.append(replace(record, observation_id=identity, data=data))
        with self.assertRaisesRegex(ValueError, 'completion-metadata-binding-mismatch'):
            self._read_with(revised,(result,))

    def test_optimized_assessment_validator_matches_owner_accept_and_reject(self):
        from auto_g16.execution.readonly import _verify_read_assessments
        from auto_g16.execution._identity import semantic_id
        records = self.fixture.store.observations_for_attempt('attempt-1')
        target = records[-1]
        job = {'job_authority_id':target.data['job_authority_id']}
        variants = [('valid', records)]
        changes = {
            'schema':'future/1', 'completion_mode':'wrong-mode',
            'attempt_id':'foreign', 'program_execution_snapshot_id':'foreign',
            'effect_intent_id':'foreign', 'job_authority_id':'foreign',
            'observation_prefix_sha256':'0'*64, 'evidence_observation_ids':(),
            'diagnostic':'future-diagnostic', 'verdict':'UNKNOWN',
            'epoch_id':None, 'evidence_result_id':None,
            'capture_authority_id':None, 'receipt_sha256':None,
        }
        for key, value in changes.items():
            data = dict(target.data);data[key] = value
            altered = replace(target, observation_id=semantic_id('program-completion-assessment',data),data=data)
            variants.append((key,(*records[:-1],altered)))
        for label, history in variants:
            with self.subTest(label=label):
                outcomes = []
                for validate in (program_runtime._verify_completion_assessments,_verify_read_assessments):
                    try:
                        validate(history,self.fixture.snapshot,job)
                        outcomes.append('accepted')
                    except ValueError:
                        outcomes.append('rejected')
                self.assertEqual(outcomes[0],outcomes[1])
                self.assertEqual(outcomes[0],'accepted' if label == 'valid' else 'rejected')

    def test_optimized_validator_does_not_encode_unused_tail(self):
        from auto_g16.core import Observation
        from auto_g16.execution.readonly import _verify_read_assessments
        records = self.fixture.store.observations_for_attempt('attempt-1')
        job = {'job_authority_id':records[-1].data['job_authority_id']}
        tail = Observation(observation_id='tail',attempt_id='attempt-1',observation_type='foreign',data={'core_float':1.5})
        for history in ((tail,),(*records,tail)):
            for validate in (program_runtime._verify_completion_assessments,_verify_read_assessments):
                self.assertIsNone(validate(history,self.fixture.snapshot,job))


class PrefixDigestTests(unittest.TestCase):
    def test_every_prefix_matches_existing_owner_encoding(self):
        from auto_g16.core import Observation
        from auto_g16.execution.readonly import _ReadPrefixDigests
        records = tuple(Observation(observation_id=f'id-{i}',attempt_id='a',observation_type='data',data=value) for i,value in enumerate(({}, {'中文':'line\n"quoted"\\'}, {'a':(None,True,1,'1',()),'z':{'b':False}}, {'ordered':('third','first')})))
        digests = _ReadPrefixDigests(records)
        for i in range(len(records)+1):
            self.assertEqual(digests.before(i),program_runtime._observation_prefix(records[:i]))
            self.assertEqual(digests.before(i),program_runtime._observation_prefix(records[:i]))

    def test_encoding_occurs_once_per_prefix_member(self):
        from auto_g16.core import Observation
        from auto_g16.execution import readonly
        records = tuple(Observation(observation_id=f'id-{i}',attempt_id='a',observation_type='data',data={}) for i in range(20))
        with patch.object(readonly,'canonical_bytes',wraps=readonly.canonical_bytes) as encoder:
            digests = readonly._ReadPrefixDigests(records)
            for i in range(21):digests.before(i)
        self.assertEqual(encoder.call_count,20)
