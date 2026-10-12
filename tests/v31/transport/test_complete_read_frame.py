"""Closed complete-read frame recognition, including hostile epoch boundaries."""
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest
from auto_g16.execution import program_runtime as r


class CompleteReadFrameTests(unittest.TestCase):
    def setUp(self):
        required = dict(logical_role='output', portable_name='gaussian.log', format='text', max_size_bytes=100)
        optional = dict(logical_role='checkpoint', portable_name='gaussian.chk', format='binary', max_size_bytes=100)
        self.snapshot = NS(program_execution_spec=NS(required_outputs=(required,), optional_outputs=(optional,)))
        rows = []
        def add(op, payload, response):
            row = NS(observation_id=str(len(rows)), observation_type=r._transport._RECEIPT_TYPE,
                data=dict(operation=op, outcome='SUCCEEDED', request=dict(operation=op,
                    binding={'job_authority_id':'job'}, payload=payload), response=response))
            rows.append(row)
            return row
        add('QUERY_SCHEDULER', {'job_id':'1.server'}, {'job_id':'1.server','state':'absent'})
        stats = []
        for i, declaration in enumerate((r._completion._METADATA_DECLARATION, required, optional)):
            payload = {key:declaration[key] for key in ('logical_role','portable_name','format')}
            response = {'portable_name':declaration['portable_name'], 'presence':'absent'}
            if i < 2: response.update(presence='present', size_bytes=3, file_physical_token='token')
            stat = add('STAT_EXACT_FILE',payload,response); stats.append(stat)
            if i < 2:
                add('FETCH_EXACT_FILE',{**payload,'expected_size_bytes':3,'expected_file_physical_token':'token',
                    'stat_receipt_id':stat.observation_id}, {'portable_name':declaration['portable_name'],
                    'size_bytes':3,'file_physical_token':'token','sha256':'a'*64})
        for stat in stats: add('STAT_EXACT_FILE',deepcopy(stat.data['request']['payload']),deepcopy(stat.data['response']))
        add('QUERY_SCHEDULER', {'job_id':'1.server'}, {'job_id':'1.server','state':'absent'})
        self.frame = rows

    def evaluate(self, frame, *, split=None):
        old = NS(observation_id='old', observation_type=r._COLLECTION_START)
        new = NS(observation_id='new', observation_type=r._COLLECTION_START)
        observations = [old, *frame, new]
        if split is not None: observations.insert(split + 1, NS(observation_id='interleaved', observation_type=r._COLLECTION_START))
        return r._complete_abandoned_read_frame(self.snapshot, observations, frame, 'job')

    def test_complete_and_optional_absence(self):
        self.assertTrue(self.evaluate(self.frame))

    def test_damaged_or_cross_epoch_frames_never_match(self):
        for kind in ('truncated','duplicate','reorder','foreign-job','failed-fetch','required-absent',
                     'restat-drift','wrong-predecessor','extra-assessment','extra-query','invalid-digest'):
            with self.subTest(kind=kind):
                rows = deepcopy(self.frame)
                if kind == 'truncated': rows.pop()
                elif kind == 'duplicate': rows.insert(2, deepcopy(rows[1]))
                elif kind == 'reorder': rows[1],rows[2] = rows[2],rows[1]
                elif kind == 'foreign-job': rows[2].data['request']['binding']['job_authority_id'] = 'other'
                elif kind == 'failed-fetch': rows[2].data['outcome'] = 'UNKNOWN'
                elif kind == 'required-absent':
                    rows[3].data['response'] = {'portable_name':'gaussian.log','presence':'absent'}
                    rows.pop(4)
                elif kind == 'restat-drift': rows[-2].data['response']['presence'] = 'present'
                elif kind == 'wrong-predecessor': rows[2].data['request']['payload']['stat_receipt_id'] = 'other'
                elif kind == 'extra-assessment': rows.insert(3, NS(observation_id='assessed', observation_type=r._COMPLETION_ASSESSMENT))
                elif kind == 'extra-query': rows.append(deepcopy(rows[-1]))
                elif kind == 'invalid-digest': rows[2].data['response']['sha256'] = 'not-a-digest'
                self.assertFalse(self.evaluate(rows))
        for cut in range(1,len(self.frame)):
            with self.subTest(cross_epoch=cut): self.assertFalse(self.evaluate(self.frame,split=cut))

    def test_requires_later_continuation_and_verified_receipts(self):
        old = NS(observation_id='old', observation_type=r._COLLECTION_START)
        new = NS(observation_id='new', observation_type=r._COLLECTION_START)
        fn = r._complete_abandoned_read_frame
        self.assertFalse(fn(self.snapshot,[old,*self.frame],self.frame,'job'))
        self.assertFalse(fn(self.snapshot,[old,*self.frame,new],self.frame[:-1],'job'))
        self.assertFalse(fn(self.snapshot,[old,*self.frame,new],self.frame,None))


if __name__ == '__main__': unittest.main()
