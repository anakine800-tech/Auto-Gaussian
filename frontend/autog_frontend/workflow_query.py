"""Workflow display queries. Public Core records + independent telemetry only.

Historical receipt binding is distinct from the current incarnation of a PBS
job. Job names, PID coincidence, directory labels and job-number prefixes never
establish a live binding. No domain mutation or remote command occurs here.
"""
from collections import Counter
from datetime import datetime, timezone
import re
import sqlite3

from auto_g16.core import SQLiteRuntimeStore, RecordNotFoundError, RuntimeStoreError
from auto_g16.execution import RemoteEffectReceipt
from auto_g16.observe import project_attempt_observations
from auto_g16.query import QueryError
from auto_g16.result import ResultProvenanceService, GaussianResultQuery
from .archive_import import plain

SCHEMA = 'autog-workflow-overview/1'
JOB = re.compile(r'[0-9]+(?:\[[0-9]*\])?\.[A-Za-z0-9_.-]+\Z')


def scheduler_jobs(monitor):
    sample = monitor.get('sample') or {}
    sources = sample.get('sources', {})
    source = sources.get('queue_details')
    rows = []
    if not source or source['exit_code'] != 0:
        return [], 'unavailable'
    current = None
    allowed = {'Job_Name','Job_Owner','job_state','queue','server','ctime','qtime','start_time',
               'exec_host','init_work_dir','Output_Path','Error_Path','resources_used.cput',
               'resources_used.mem','resources_used.vmem','resources_used.walltime',
               'Resource_List.nodes','Resource_List.mem','Resource_List.walltime'}
    for line in source['text'].splitlines():
        if line.startswith('Job Id: '):
            identity = line[len('Job Id: '):].strip()
            if not JOB.fullmatch(identity): return [], 'invalid'
            current = {'job_id': identity, 'fields': {}}
            rows.append(current)
        elif line.strip():
            match = re.fullmatch(r'    ([A-Za-z0-9_.]+) = (.*)', line)
            if not current or not match or match[1] not in allowed or match[1] in current['fields']:
                return [], 'invalid'
            current['fields'][match[1]] = match[2]
    if len({r['job_id'] for r in rows}) != len(rows): return [], 'invalid'
    user = sample.get('user')
    rows = [r for r in rows if r['fields'].get('Job_Owner','').split('@')[0] == user]
    for row in rows:
        row.update(sampled_at=sample.get('sampled_at'), sample_sha256=sample.get('raw_sha256'),
                   freshness=monitor.get('state'), association='unlinked', attempt_id=None)
    return rows, 'available'


def receipt_binding(observations, attempt_id):
    receipts = []
    for observation in observations:
        if observation.observation_type != 'v3.remote-effect-receipt': continue
        receipt = RemoteEffectReceipt.from_payload(observation.data)
        if receipt.attempt_id != attempt_id or observation.attempt_id != attempt_id or receipt.remote_effect_receipt_id != observation.observation_id:
            raise ValueError('receipt identity mismatch')
        receipts.append(receipt)
    receipts.sort(key=lambda r:r.effect_sequence)
    if receipts and ([r.effect_sequence for r in receipts] != list(range(1,len(receipts)+1))
                     or len({(r.execution_snapshot_id,r.submission_intent_id) for r in receipts}) != 1):
        raise ValueError('conflicting receipt chain')
    effects = [r for r in receipts if r.effect_kind.value in ('submission','submission-reconciliation')]
    confirmed = [r for r in effects if r.effect_state.value == 'confirmed_effect' and r.job_id]
    if len({(r.job_id,r.remote_workspace) for r in confirmed}) > 1:
        raise ValueError('conflicting job identities')
    if confirmed and any(r.effect_sequence>confirmed[0].effect_sequence and r.effect_state.value=='confirmed_no_effect' for r in effects):
        raise ValueError('contradictory submission evidence')
    binding = dict(status='unavailable',reason='no-confirmed-submission-receipt',job_id=None,
                   receipt_id=None,execution_snapshot_id=None,server=None,workspace=None,
                   incarnation=None,source=None)
    if confirmed:
        r=confirmed[-1]
        binding.update(status='historical-confirmed',reason=None,job_id=r.job_id,
                       receipt_id=r.remote_effect_receipt_id,execution_snapshot_id=r.execution_snapshot_id,
                       workspace=r.remote_workspace,source='Core/v3.remote-effect-receipt')
        # Optional explicit birth identity, never synthesized from a live queue.
        identity=plain(r.details).get('scheduler_identity')
        if identity is not None:
            if (not isinstance(identity,dict) or set(identity)!={'schema','host','port','user','job_id','ctime','qtime','workspace'}
                    or identity['schema']!='pbs-job-incarnation/1' or identity['job_id']!=r.job_id
                    or identity['workspace']!=r.remote_workspace or type(identity['port']) is not int
                    or not 1<=identity['port']<=65535
                    or any(not isinstance(identity[k],str) or not identity[k] for k in ('host','user','ctime','qtime','workspace'))):
                raise ValueError('invalid job incarnation')
            binding['incarnation']=identity
            binding['server']={k:identity[k] for k in ('host','port','user')}
    return receipts,binding


def attach_live(binding, jobs, monitor):
    result=dict(status='unavailable',reason='historical-binding-required',job=None)
    if binding['status']!='historical-confirmed':return result
    identity=binding['incarnation']
    if identity is None:return dict(result,reason='submission-birth-identity-not-recorded')
    server=monitor.get('server_identity') or {}
    if any(server.get(k)!=identity[k] for k in ('host','port','user')):
        return dict(result,reason='different-server-or-account')
    if monitor.get('state') not in ('fresh','partial'):
        return dict(result,status='stale',reason='telemetry-not-fresh')
    candidates=[j for j in jobs if j['job_id']==binding['job_id']]
    if not candidates:return dict(result,reason='not-observed-does-not-imply-completion')
    job=candidates[0];f=job['fields']
    if any(f.get(k)!=identity[k] for k in ('ctime','qtime')):
        return dict(result,status='conflict',reason='job-id-reused-or-birth-identity-conflicts')
    if f.get('init_work_dir')!=identity['workspace']:
        return dict(result,reason='exact-workspace-not-observed')
    if f.get('Job_Owner','').split('@')[0]!=identity['user']:
        return dict(result,status='conflict',reason='different-owner')
    return dict(status='verified',reason=None,job=job)


class WorkflowQuery:
    def __init__(self,database,details,monitor=None,mode_reviews=None):
        self.database,self.details,self.monitor,self.mode_reviews=database,details,monitor,mode_reviews

    def _attempt(self,store,attempt,project_id,run,*,events=False):
        identity=attempt.attempt_id
        row=dict(attempt_id=identity,ordinal=attempt.ordinal,parent_attempt_id=store.parent_attempt_id(identity),
                 task_id=attempt.task_id,project_id=project_id,workflow_run_id=run.workflow_run_id,
                 core_state=store.attempt_state(identity).value,issues=[],timeline=[],input=None,
                 requested_resources=None,scientific_review='not-projected',program='unknown')
        observations=store.observations_for_attempt(identity)
        try:
            receipts,binding=receipt_binding(observations,identity)
            row['binding']=binding
            if events:
                row['timeline'] += [dict(kind='effect',id=r.remote_effect_receipt_id,time=None,
                    sequence=r.effect_sequence,label=r.effect_kind.value,status=r.effect_state.value,
                    source='Core/v3.remote-effect-receipt',data={'job_id':r.job_id,'workspace':r.remote_workspace}) for r in receipts]
        except (ValueError,TypeError,KeyError):
            receipts=[];row['binding']=dict(status='conflict',reason='invalid-or-conflicting-receipts',job_id=None)
            row['issues'].append('receipt-conflict')
        summary=GaussianResultQuery(store).get_summary(identity)
        row['result']={k:summary[k] for k in ('availability','summary','source','reasons')}
        packet=None
        packet_requested=False
        try:
            view=ResultProvenanceService(store).current_view(identity)
            input_binding=view.input_binding
            if input_binding:
                plan=store.load_calculation_plan(input_binding.calculation_plan_id)
                if plan.task_id!=attempt.task_id:raise ValueError('plan task mismatch')
                row['input']={k:plain(input_binding.payload())[k] for k in ('logical_name','sha256','size_bytes','execution_snapshot_id')}
                row['program']=plain(plan.intent).get('program','unknown')
                if not isinstance(row['program'],str):row['program']='unknown'
                if receipts and any(r.execution_snapshot_id!=input_binding.execution_snapshot_id for r in receipts):
                    row['binding']=dict(status='conflict',reason='receipt-input-snapshot-conflict',job_id=None)
                    row['issues'].append('receipt-input-snapshot-conflict')
                if events:row['timeline'].append(dict(kind='input',id=input_binding.observation_id,time=None,label='input-binding',status='recorded',source='Result.InputBinding',data=row['input']))
            if events:
                for e in view.envelopes:
                    row['timeline'].append(dict(kind='capture',id=e.observation_id,time=e.captured_at_utc,label='output-capture',status=e.capture_status.value,source='Result.OutputEnvelope',data={'completeness':e.capture_completeness.value,'sequence':e.capture_sequence}))
                for r in view.results:
                    row['timeline'].append(dict(kind='result',id=r.result_id,time=None,label='parse-result',status=r.parse_status.value,source='Result.ParseOutcome',data={'parser':r.parser_name,'version':r.parser_version,'selected':r.result_id==(summary.get('source') or {}).get('result_id')}))
            packet_requested=True
            packet=self.details.execution_source(identity)
            if packet and receipts:
                s=packet['packet']['execution_snapshot'];workspace=s['workspace_binding']
                if (s['attempt_id']!=identity or any(s['execution_snapshot_id']!=r.execution_snapshot_id or s['submission_intent_id']!=r.submission_intent_id for r in receipts)
                        or workspace['attempt_id']!=identity or workspace['project_id']!=project_id
                        or any(r.remote_workspace and r.remote_workspace!=workspace['remote_attempt_dir'] for r in receipts)):
                    raise ValueError('snapshot receipt mismatch')
                if input_binding:
                    expected={k:plain(input_binding.payload())[k] for k in ('attempt_id','calculation_plan_id','calculation_plan_revision','input_format','logical_name','prepared_input_binding_id','sha256','size_bytes')}
                    if s['prepared_input_binding']!=expected:raise ValueError('input binding mismatch')
                target=s['resolved_server_profile'];t=target['target_identity']
                server=dict(host=t['destination_host'],port=t['destination_port'],user=target['remote_user'])
                if row['binding'].get('server') and row['binding']['server']!=server:raise ValueError('receipt server conflict')
                if row['binding']['status']=='historical-confirmed':row['binding'].update(server=server,packet_source=packet['source'])
                # Validate task ownership and the public resource contract independently.
                from auto_g16.execution import ResolvedResourceRequest
                request=s['resolved_resource_request'];spec=store.load_resource_spec(request['resource_spec_id'])
                if spec.task_id!=attempt.task_id:raise ValueError('resource task mismatch')
                resolved=ResolvedResourceRequest(resource_spec=spec,**{k:request[k] for k in ('cores','memory_mb','walltime_seconds','queue')})
                if plain(resolved.semantic_payload())!=request:raise ValueError('resource request mismatch')
                row['requested_resources']={k:request[k] for k in ('cores','memory_mb','walltime_seconds','queue')}
        except (OSError,ValueError,TypeError,KeyError,AttributeError,QueryError,RecordNotFoundError):
            row['issues'].append('input-or-execution-source-unavailable')
            if packet_requested:
                row['binding']=dict(status='conflict',reason='execution-packet-conflict',job_id=None)
                row['requested_resources']=None
        if events:
            try:
                projection=project_attempt_observations(store,attempt_id=identity)
                for axis in ('scheduler','process','gaussian'):
                    o=getattr(projection,axis)
                    if o:row['timeline'].append(dict(kind='observation',id=o.observation_id,time=o.observed_at_utc,label=axis,status=o.state,source='Observe.persisted-projection',data={'freshness_at_recording':o.freshness,'scope':'historical-not-live'}))
            except (ValueError,TypeError,KeyError):row['issues'].append('observation-unavailable')
        return row

    def _read(self,selected=None):
        try:
            monitor=self.monitor.snapshot() if self.monitor else {'enabled':False,'state':'unavailable'}
            jobs,queue_status=scheduler_jobs(monitor)
            tasks=[];count=0
            with SQLiteRuntimeStore.read_snapshot(self.database) as store:
                if selected:store.load_attempt(selected)
                for project in store.list_projects():
                    for run in store.list_workflow_runs(project.project_id):
                        for task in store.list_tasks(run.workflow_run_id):
                            attempts=[]
                            for attempt in store.list_attempts(task.task_id):
                                count+=1
                                if count>2000:raise QueryError('response-too-large')
                                row=self._attempt(store,attempt,project.project_id,run,events=selected==attempt.attempt_id)
                                row['live']=attach_live(row['binding'],jobs,monitor)
                                if queue_status!='available' and row['live']['status']!='verified':row['live']['reason']='scheduler-detail-unavailable'
                                attempts.append(row)
                            tasks.append(dict(task_id=task.task_id,task_kind=task.task_kind,project_id=project.project_id,
                                workflow_run_id=run.workflow_run_id,workflow_name=run.workflow_name,
                                attempts=attempts,dependency_status='not-projected',current_attempt_id=None))
            # Multiple receipts claiming the same live identity are an ambiguity,
            # never resolved by choosing the newest Attempt.
            claims=Counter(a['live']['job']['job_id'] for t in tasks for a in t['attempts'] if a['live']['status']=='verified')
            for t in tasks:
                for a in t['attempts']:
                    if a['live']['status']=='verified' and claims[a['live']['job']['job_id']]>1:
                        a['live']=dict(status='conflict',reason='multiple-attempts-claim-job',job=None)
                    if a['live']['status']=='verified':
                        for job in jobs:
                            if job['job_id']==a['binding']['job_id']:job.update(association='verified',attempt_id=a['attempt_id'])
            if selected:
                row=next(a for t in tasks for a in t['attempts'] if a['attempt_id']==selected)
                if row['live']['status']=='verified':
                    job=row['live']['job']
                    row['timeline'].append(dict(kind='live',id=job['sample_sha256'],time=job['sampled_at'],label='scheduler',
                        status=job['fields'].get('job_state','unknown'),source='ReadOnlyTelemetry',data={'job_id':job['job_id'],'scope':'sample-not-scientific-completion'}))
                self._review(row)
                return dict(schema=SCHEMA,attempt=row,monitor_state=monitor.get('state'),queue_status=queue_status)
            return dict(schema=SCHEMA,read_at=datetime.now(timezone.utc).isoformat(),tasks=tasks,
                        server_jobs=jobs,queue_status=queue_status,monitor_state=monitor.get('state'),
                        scope='all-persisted-attempts; no-current-winner-inferred',
                        layout=dict(schema='autog-workflow-layout/1',availability='unavailable',
                                    reason='v31-workflow-source-not-connected',nodes=[],edges=[]))
        except QueryError:raise
        except RecordNotFoundError:raise QueryError('not-found') from None
        except (OSError,sqlite3.Error,RuntimeStoreError):raise QueryError('store-unavailable') from None
        except (ValueError,KeyError,TypeError,AttributeError):raise QueryError('invalid-evidence') from None

    def _review(self,row):
        row['review']={'historical':None,'human_mode':None}
        try:
            detail=self.details.get_details('attempt',row['attempt_id'])
            selected=(row['result']['source'] or {}).get('result_id')
            if detail['result']['availability']=='available' and detail['result']['source']['result_id']==selected:
                row['review']['historical']=detail['review']
                if self.mode_reviews:
                    mode=self.mode_reviews.get(row['attempt_id'])
                    target=mode['target']
                    if target is not None and target['result_source']!=detail['result']['source']:raise ValueError('review target changed')
                    row['review']['human_mode']=mode
                    for r in mode['records']:
                        row['timeline'].append(dict(kind='review',id=r['command']['request_id'],time=r['recorded_at_utc'],label='human-intended-mode',status='recorded',source='IndependentModeReview',data={'reviewer':r['command']['reviewer'],'scope':'intended-mode-only-not-ts-acceptance'}))
        except (QueryError,ValueError,KeyError,TypeError):row['issues'].append('review-unavailable')

    def overview(self):return self._read()
    def attempt(self,identity):
        return self._read(identity)
