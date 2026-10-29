"""T16 offline coverage: scheduler outcomes, cluster binding and committed capacity."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import shlex

import pytest
from ag import budget, attempt, cancel, cli, config, doctor, fetch, monitor, remote, render, slurm, state, status, study, submission, submit
from ag.transport import Result, SSHConnectionError, SSHTransport
from test_core import cfg, Fake, INPUT, allow, write_config


# Synthetic 26.05.5 --details --oneliner output, following SchedMD's
# src/scontrol/info_job.c field order. No live cluster or research data.
EVIDENCE_CONFIG = 'ClusterName = fixture\nSLURM_VERSION = 26.05.5\n'
EVIDENCE_SLUID = 's0123456789ABC'
EVIDENCE_DB_INDEX = 38390726480144748
EVIDENCE_JOB = (
    'JobId=123 JobName=water-001-sp SLUID=s0123456789ABC '
    'UserId=fixture(1001) GroupId=fixture(1001) MCS_label=N/A '
    'Priority=100 Nice=0 Account=fixture QOS=normal '
    'JobState=PENDING Reason=Resources Dependency=(null) '
    'Requeue=0 Restarts=0 BatchFlag=1 Reboot=0 ExitCode=0:0 DerivedExitCode=0:0 '
    'RunTime=00:00:00 TimeLimit=01:30:00 TimeMin=N/A '
    'SubmitTime=2026-01-01T00:00:00 EligibleTime=2026-01-01T00:00:00 '
    'AccrueTime=2026-01-01T00:00:00 StartTime=Unknown EndTime=Unknown Deadline=N/A '
    'SuspendTime=None SecsPreSuspend=0 LastSchedEval=2026-01-01T06:00:00 Scheduler=Main '
    'Partition=fixture AllocNode:Sid=fixture:100 ReqNodeList=(null) ExcNodeList=(null) '
    'NodeList= NumNodes=1 NumCPUs=8 NumTasks=1 CPUs/Task=8 ReqB:S:C:T=0:0:*:* '
    'ReqTRES=cpu=8,mem=12G,node=1,billing=8 AllocTRES=(null) '
    'Socks/Node=* NtasksPerN:B:S:C=0:0:*:* CoreSpec=* '
    'MinCPUsNode=8 MinMemoryNode=12G MinTmpDiskNode=0 Features=(null) DelayBoot=00:00:00 '
    'OverSubscribe=OK Exclusive=NONE Contiguous=0 Licenses=(null) LicensesAlloc=(null) Network=(null) '
    'Command=job.slurm SubmitLine=sbatch --parsable job.slurm WorkDir=synthetic '
    'StdErr=synthetic/job.slurm.err StdIn=synthetic/input StdOut=synthetic/job.slurm.out\n'
)
EVIDENCE_HISTORY = (
    'fixture|123|water-001-sp|1001|38390726480144748|2026-01-01T00:00:00|Unknown|Unknown|PENDING|0|'
    's0123456789ABC|s0123456789ABC\n'
)
EVIDENCE_IDENTITY = dict(job_id='123', cluster='fixture', name='water-001-sp')


@pytest.fixture
def multi(cfg):
    pbs = {k: deepcopy(v) for k, v in cfg.items() if k not in ('local', '_config_dir')}
    batch = deepcopy(pbs)
    batch.update(scheduler='slurm', partition='fixture', account='fixture', qos='fixture')
    batch['ssh']['host'] = 'batch-fixture'
    batch['remote'] = {k: v.replace('cluster', 'batch') for k, v in batch['remote'].items()}
    return dict(local=cfg['local'], _config_dir=cfg['_config_dir'], clusters={'default': pbs, 'batch': batch})


def prepare(cfg, tmp_path, cluster='batch', label='sp'):
    if not (Path(cfg['local']['studies_root']) / 'water').exists():
        study.init(cfg, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='water', template='gaussian', input_path=source,
                        tier='simple', walltime='01:30:00', label=label, cluster=cluster)
    return attempt.find(cfg, m['attempt_id']), m


class SlurmFake(Fake):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.qsub = Result(stdout='123;fixture\n')
        self.queue = Result()
        self.exact = Result()
        self.accounting = Result(stdout='123|water-001-sp|fixture|COMPLETED|0:0|00:01:00|8\n')
        self.find = Result()
        self.history = Result(stdout='123|water-001-sp|fixture|COMPLETED|0:0|00:01:00|8\n')
        self.partitions = Result(stdout='fixture*\n')

    def run(self, command):
        if command == remote.slurm_partition_jobs(self.cfg.get('partition', 'fixture')):
            self.calls.append(command)
            # Project the synthetic own rows into anonymous partition totals.
            rows = slurm.parse_queue(self.queue.stdout)
            return Result(stdout=''.join(f"{j['state']}|{j['cores']}\n" for j in rows
                                         if j['partition'] == self.cfg.get('partition')))
        if command == remote.slurm_partition_hardware(self.cfg.get('partition', 'fixture')):
            self.calls.append(command)
            return Result(stdout='8/24/0/32|65536|1\n')
        if command == remote.slurm_partition_allocmem(self.cfg.get('partition', 'fixture')):
            self.calls.append(command)
            return Result(stdout='8192                \n')
        if command == remote.slurm_partition_nodes(self.cfg.get('partition', 'fixture')):
            self.calls.append(command)
            return Result(stdout='node-a|fixture|8/24/0/32|65536|8192|mixed|up\n')
        replies = dict(storage_usage=Result(stdout='1024\t' + self.cfg['remote']['ag_root'] + '\n'), slurm_jobs=self.exact if ' -j ' in command.text else self.queue,
                       slurm_accounting=self.accounting, slurm_find=self.find,
                       slurm_history=self.history, slurm_partitions=self.partitions)
        if command.operation in replies:
            self.calls.append(command)
            return replies[command.operation]
        return super().run(command)


def submitted(multi, tmp_path, monkeypatch, cluster='batch', label='sp'):
    p, m = prepare(multi, tmp_path, cluster, label)
    fake = SlurmFake(config.select_cluster(multi, cluster))
    if m['scheduler'] == 'pbs':
        fake.qsub = Result(stdout='123\n')
    allow(monkeypatch)
    submit.submit(multi, [p.name], fake)
    fake.calls.clear()
    return p, m, fake


@pytest.mark.parametrize('text,expected', [('123\n', ('123', None)), ('123;fixture\n', ('123', 'fixture'))])
def test_sbatch_parsable(text, expected):
    assert slurm.parse_submission(text) == expected


@pytest.mark.parametrize('text', ['Submitted batch job 123', '123;', '123;a;b', '0', '123_1', '123;bad name', '123\n456', '123;$(evil)'])
def test_bad_sbatch_response(text):
    with pytest.raises(ValueError): slurm.parse_submission(text)


def test_evidence_config_and_client_versions_are_separate_observations():
    text = 'Configuration data as of 2026-01-01T00:00:00\n' + EVIDENCE_CONFIG + 'Other = synthetic\n'
    assert slurm.parse_evidence_config(text) == dict(cluster='fixture', server_version='26.05.5')
    assert slurm.parse_evidence_version('slurm 26.05.5\n') == '26.05.5'
    # Parsing an older version does not certify its support or authorize actions.
    assert slurm.parse_evidence_version('slurm 24.05.0') == '24.05.0'
    assert slurm.parse_evidence_config(EVIDENCE_CONFIG.replace('26.05.5', '24.05.0'))['server_version'] == '24.05.0'


@pytest.mark.parametrize('text', [
    '', 'Other = ClusterName=fixture SLURM_VERSION=26.05.5\n',
    'ClusterName = fixture\n', EVIDENCE_CONFIG + 'ClusterName = fixture\n',
    EVIDENCE_CONFIG + 'SLURM_VERSION = 26.05.5\n',
    EVIDENCE_CONFIG.replace('fixture', 'all'), EVIDENCE_CONFIG.replace('fixture', 'ALL'),
    EVIDENCE_CONFIG.replace('fixture', 'fixture,other'),
    EVIDENCE_CONFIG.replace('26.05.5', '26.05.5rc1'),
    EVIDENCE_CONFIG.replace('fixture', 'fixture\x00'), None,
])
def test_evidence_config_rejects_missing_ambiguous_or_nonlocal_identity(text):
    with pytest.raises(ValueError):
        slurm.parse_evidence_config(text)


@pytest.mark.parametrize('text', ['26.05.5', 'slurm 26.05', 'slurm 26.05.5-extra',
                                  'slurm 26.05.5\nslurm 26.05.5\n',
                                  ' slurm 26.05.5', 'slurm 26.05.5\r\n', None])
def test_evidence_client_version_rejects_nonexact_response(text):
    with pytest.raises(ValueError):
        slurm.parse_evidence_version(text)


def test_evidence_job_preserves_restarts_and_unknown_or_estimated_times():
    row = slurm.parse_evidence_job(EVIDENCE_JOB, **EVIDENCE_IDENTITY)
    assert row == dict(**EVIDENCE_IDENTITY, owner='fixture', uid=1001, state='PENDING',
                       submit='2026-01-01T00:00:00+00:00', start=None, end=None,
                       restarts=0, sluid=EVIDENCE_SLUID)
    changed = EVIDENCE_JOB.replace('Restarts=0', 'Restarts=2').replace(
        'StartTime=Unknown', 'StartTime=2026-01-02T00:00:00')
    row = slurm.parse_evidence_job(changed, **EVIDENCE_IDENTITY)
    assert row['restarts'] == 2 and row['start'] == '2026-01-02T00:00:00+00:00'
    assert not {'eligible', 'never_started', 'terminated', 'authorized'} & row.keys()


def test_evidence_job_horizontal_padding_keeps_fixed_field_order():
    padded = EVIDENCE_JOB.replace(' ', '  \t')
    assert slurm.parse_evidence_job(padded, **EVIDENCE_IDENTITY) == slurm.parse_evidence_job(
        EVIDENCE_JOB, **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('replacement', [
    ('JobId=123', 'JobId=124'), ('JobName=water-001-sp', 'JobName=other'),
    ('JobId=123', 'JobId=123 ArrayJobId=123 ArrayTaskId=1'),
    ('JobId=123', 'JobId=123 HetJobId=123 HetJobOffset=0'),
    ('Command=', 'FedOrigin=fixture FedViableSiblings=fixture FedActiveSiblings=fixture Command='),
    ('SLUID=' + EVIDENCE_SLUID + ' ', ''),
    ('SLUID=' + EVIDENCE_SLUID, 'SLUID=s0123456789AB+'),
    ('SLUID=' + EVIDENCE_SLUID, 'SLUID=sG123456789ABC'),
    ('SLUID=' + EVIDENCE_SLUID, 'SLUID=s0000000000000'),
    ('Restarts=0', 'Restarts=65536'), ('Restarts=0', 'Restarts='),
    ('UserId=fixture(1001)', 'UserId=fixture(4294967296)'),
    ('JobState=PENDING', 'JobState=PENDING+'), ('JobState=PENDING', 'JobState=REQUEUE_FED'),
    ('SubmitTime=2026-01-01T00:00:00', 'SubmitTime=Unknown'),
    ('StartTime=Unknown', 'StartTime=2026-02-30T00:00:00'),
    ('EndTime=Unknown', 'EndTime=2026-01-01T00:00:00+01:00'),
    ('DerivedExitCode=0:0 ', ''), ('StdOut=synthetic/job.slurm.out', ''),
])
def test_evidence_job_rejects_bad_identity_missing_fields_and_unsupported_shapes(replacement):
    with pytest.raises(ValueError):
        slurm.parse_evidence_job(EVIDENCE_JOB.replace(*replacement), **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('field', ['JobId=123', 'JobName=water-001-sp', 'SLUID=' + EVIDENCE_SLUID,
                                  'UserId=fixture(1001)', 'JobState=PENDING', 'Restarts=0',
                                  'SubmitTime=2026-01-01T00:00:00', 'StartTime=Unknown', 'EndTime=Unknown'])
def test_evidence_job_never_recovers_fields_from_paths_or_names(field):
    # A real key plus a path-embedded imitation is ambiguous, not last-wins.
    forged = EVIDENCE_JOB.replace('WorkDir=synthetic', 'WorkDir=synthetic ' + field)
    with pytest.raises(ValueError):
        slurm.parse_evidence_job(forged, **EVIDENCE_IDENTITY)
    # A missing prefix key cannot be supplied by free text in the suffix.
    moved = EVIDENCE_JOB.replace(field + ' ', '', 1).replace('WorkDir=synthetic', 'WorkDir=synthetic ' + field)
    with pytest.raises(ValueError):
        slurm.parse_evidence_job(moved, **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('text', ['', 'slurm_load_jobs error: Invalid job id specified\n',
                                  EVIDENCE_JOB * 2, EVIDENCE_JOB.rstrip('\n'),
                                  EVIDENCE_JOB.replace(' Command=', '\nCommand='),
                                  EVIDENCE_JOB.replace('UserId=', '\x00UserId=')])
def test_evidence_job_rejects_missing_multiple_or_incomplete_records(text):
    with pytest.raises(ValueError):
        slurm.parse_evidence_job(text, **EVIDENCE_IDENTITY)


def test_evidence_history_keeps_distinct_runs_without_positive_tags():
    # Real execution followed by requeue must survive in the parsed history.
    previous = EVIDENCE_HISTORY.replace('|Unknown|Unknown|PENDING|0|',
        '|2026-01-01T00:01:00|2026-01-01T00:02:00|REQUEUED|0|')
    current = EVIDENCE_HISTORY.replace(str(EVIDENCE_DB_INDEX), str(EVIDENCE_DB_INDEX + 1)).replace('T00:00:00', 'T00:03:00').replace(
        '|PENDING|0|', '|PENDING|1|').replace(EVIDENCE_SLUID, 's0123456789ABD')
    rows = slurm.parse_evidence_history(previous + current + current, **EVIDENCE_IDENTITY)
    assert len(rows) == 2
    assert rows[0]['start'] == '2026-01-01T00:01:00+00:00'
    assert rows[1]['restarts'] == 1 and rows[1]['start'] is None
    assert [row['db_index'] for row in rows] == [EVIDENCE_DB_INDEX, EVIDENCE_DB_INDEX + 1]
    assert all(row['uid'] == 1001 and not {'eligible', 'never_started', 'terminated'} & row.keys() for row in rows)
    cancelled = EVIDENCE_HISTORY.replace('|PENDING|', '|CANCELLED by 1001|')
    row = slurm.parse_evidence_history(cancelled, **EVIDENCE_IDENTITY)[0]
    assert row['state'] == 'CANCELLED' and row['state_raw'] == 'CANCELLED by 1001'


def test_evidence_history_does_not_invent_missing_original_sluid():
    fields = EVIDENCE_HISTORY.rstrip('\n').split('|')
    fields[-1] = 's0000000000000'
    row = slurm.parse_evidence_history('|'.join(fields) + '\n', **EVIDENCE_IDENTITY)[0]
    assert row['original_sluid'] is None
    assert row['original_sluid_raw'] == 's0000000000000'
    assert row['sluid'] == EVIDENCE_SLUID


@pytest.mark.parametrize('index,value', [
    (0, 'other'), (1, '124'), (1, '123_1'), (1, '123+0'), (2, 'other'),
    (3, ''), (3, '-1'), (3, '1.0'), (3, '4294967296'),
    (4, '0'), (4, str(2 ** 64)), (5, 'Unknown'), (5, '2026-13-01T00:00:00'),
    (6, ''), (6, 'None'), (7, '2026-01-01T00:00:00Z'),
    (8, 'CANCELLED+'), (8, 'REVOKED'), (8, 'never_started=true'),
    (9, ''), (9, '-1'), (9, '65536'), (9, '00'),
    (10, ''), (10, 's0123456789ABI'), (11, 'Unknown'),
    (0, 'f' * 256), (2, 'n' * 200),
])
def test_evidence_history_rejects_ambiguous_fields(index, value):
    fields = EVIDENCE_HISTORY.rstrip('\n').split('|')
    fields[index] = value
    with pytest.raises(ValueError):
        slurm.parse_evidence_history('|'.join(fields) + '\n', **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('text', ['', '\n', EVIDENCE_HISTORY + '\n', EVIDENCE_HISTORY.replace('|1001|', '|1001||'),
                                  EVIDENCE_HISTORY.rstrip('\n') + '|\n', 'never_started=true\n'])
def test_evidence_history_rejects_missing_or_wrong_column_count(text):
    with pytest.raises(ValueError):
        slurm.parse_evidence_history(text, **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('changed', [
    EVIDENCE_HISTORY.replace('|PENDING|', '|RUNNING|'),
    EVIDENCE_HISTORY.replace(str(EVIDENCE_DB_INDEX), str(EVIDENCE_DB_INDEX + 1)),
    EVIDENCE_HISTORY.replace(EVIDENCE_SLUID, 's0123456789ABD'),
    EVIDENCE_HISTORY.replace('|1001|', '|1002|'),
])
def test_evidence_history_rejects_conflicting_db_index_or_sluid(changed):
    with pytest.raises(ValueError):
        slurm.parse_evidence_history(EVIDENCE_HISTORY + changed, **EVIDENCE_IDENTITY)


@pytest.mark.parametrize('key,value', [('cluster', 'all'), ('cluster', 'ALL'), ('cluster', 'a,b'),
                                      ('job_id', '123_1'), ('name', 'name JobState=PENDING')])
def test_evidence_parsers_reject_unsafe_expected_identity(key, value):
    identity = dict(EVIDENCE_IDENTITY, **{key: value})
    for parser, text in ((slurm.parse_evidence_job, EVIDENCE_JOB),
                         (slurm.parse_evidence_history, EVIDENCE_HISTORY)):
        with pytest.raises(ValueError):
            parser(text, **identity)


def test_config_legacy_named_and_strict(multi, cfg):
    legacy = config.load_config(write_config(cfg))
    assert config.scheduler_kind(config.select_cluster(legacy)) == 'pbs'
    loaded = config.load_config(write_config(multi))
    assert config.select_cluster(loaded, 'batch')['resources']['max_committed_cores'] == 44
    multi['clusters']['batch']['resources']['max_committed_cores'] = 176
    assert config.load_config(write_config(multi))['clusters']['batch']['resources']['max_committed_cores'] == 176


@pytest.mark.parametrize('key,value', [('exclusive', True), ('partition', '--exclusive'), ('account', 'a;evil'), ('qos', 'a\nb')])
def test_config_rejects_unreviewed_slurm_fields(multi, key, value):
    multi['clusters']['batch'][key] = value
    with pytest.raises(ValueError): config.load_config(write_config(multi))


def test_slurm_template_and_summary(multi, tmp_path):
    p, m = prepare(multi, tmp_path)
    files = attempt.verified_files(multi, p, m)
    script = files['job.slurm'].decode()
    for token in ('--nodes=1', '--ntasks=1', '--cpus-per-task=8', '--mem=12G', '--time=01:30:00',
                  '--no-requeue', '--partition=fixture', '--account=fixture', '--qos=fixture',
                  'SLURM_JOB_ID', 'SLURM_SUBMIT_DIR', 'job.slurm.out', 'job.slurm.err'):
        assert token in script
    assert '--exclusive' not in script and '#PBS' not in script
    assert '--job-name=' + m['attempt_id'] in script
    assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0
    assert 'Cluster: batch' in attempt.summary(multi, m) and '12 核时' in attempt.summary(multi, m)
    with pytest.raises(ValueError): render.parameters('gaussian', {'--exclusive': ''})


@pytest.mark.parametrize('outcome', [Result(255), Result(1, stderr='sbatch: error: Socket timed out'), SSHConnectionError('timeout'), Result(stdout='unparseable')])
def test_sbatch_lost_never_retries(multi, tmp_path, monkeypatch, outcome):
    p, m = prepare(multi, tmp_path)
    fake = SlurmFake(config.select_cluster(multi, 'batch')); fake.qsub = outcome
    allow(monkeypatch)
    with pytest.raises(submit.UnknownSubmission): submit.submit(multi, [p.name], fake)
    assert state.read(p)['state'] == 'unknown' and (p / '.submit-claim').exists()
    with pytest.raises(ValueError): submit.submit(multi, [p.name], fake)
    assert fake.operations().count('submit') == 1
    fake.calls.clear(); fake.find = Result(stdout=f"123|{m['attempt_id']}|fixture|COMPLETED|0:0|00:01:00|8\n")
    assert status.check(multi, p, fake)['state'] == 'finished'
    assert state.read(p)['job_id'] == 'batch:123'
    assert set(fake.operations()) <= {'identity', 'slurm_jobs', 'slurm_find', 'slurm_accounting'}


@pytest.mark.parametrize('terminal', ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL'])
def test_terminal_from_accounting(multi, tmp_path, monkeypatch, terminal):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    fake.accounting = Result(stdout=f'123|water-001-sp|fixture|{terminal}|1:9|00:05:00|8\n')
    result = status.check(multi, p, fake)
    assert result['state'] == 'finished' and result['scheduler_state'] == terminal
    assert result['exit_code'] == 1 and result['exit_signal'] == 9 and result['exit_status'] == 1
    assert result['completion_source'] == 'sacct'
    assert fake.operations() == ['identity', 'slurm_jobs', 'slurm_accounting']


def test_no_queue_or_accounting_is_unknown(multi, tmp_path, monkeypatch):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    fake.accounting = Result()
    assert status.check(multi, p, fake)['state'] == 'unknown'
    assert state.read(p)['job_id'] == 'batch:123'
    with pytest.raises(ValueError): submit.submit(multi, [p.name], fake)
    fake.accounting = Result(stdout='123|water-001-sp|fixture|COMPLETED|0:0|00:01:00|8\n')
    assert status.check(multi, p, fake)['state'] == 'finished'


def test_running_and_all_user_cores(multi, tmp_path, monkeypatch):
    p, m, fake = submitted(multi, tmp_path, monkeypatch)
    fake.exact = Result(stdout=f"123|{m['attempt_id']}|fixture|RUNNING|8|00:00|fixture\n")
    assert status.check(multi, p, fake)['state'] == 'running'
    assert 'slurm_accounting' not in fake.operations()
    fake.queue = Result(stdout='456|web-job|fixture|PENDING|40|00:00|fixture\n789_1|array|fixture|RUNNING|4|00:00|fixture\n')
    assert status.inventory(fake, fake.cfg)[2] == 44
    assert submit.capacity(fake.cfg) == 44
    p2, _ = prepare(multi, tmp_path, label='more')
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: pytest.fail('over cap must refuse before dialog'))
    with pytest.raises(ValueError, match='Core limit'): submit.submit(multi, [p2.name], fake)
    assert 'nodes' not in fake.operations()


def test_binding_same_number_and_cancel(multi, tmp_path, monkeypatch):
    p, m, fake = submitted(multi, tmp_path, monkeypatch)
    q, _, pbs = submitted(multi, tmp_path, monkeypatch, 'default', 'pbs')
    assert state.read(p)['job_id'] == 'batch:123' and state.read(q)['job_id'] == 'default:123'
    # A changed default endpoint does not affect the manifest-bound batch target.
    multi['clusters']['default']['ssh']['host'] = 'different-fixture'
    fake.exact = Result(stdout=f"123|{m['attempt_id']}|fixture|RUNNING|8|00:00|fixture\n")
    class Router:
        def for_cluster(self, cfg):
            assert cfg['_cluster'] == 'batch' and cfg['ssh']['host'] == 'batch-fixture'
            return fake
    assert status.check(multi, p, Router())['state'] == 'running'
    seen = []
    monkeypatch.setattr('ag.confirm.confirm', lambda text, *a: seen.append(text) or True)
    assert cancel.cancel(multi, p, Router())['state'] == 'cancelled'
    assert fake.calls[-1].text == 'scancel 123' and 'Cluster: batch' in seen[0]
    assert not pbs.calls


def test_binding_tamper_refuses_before_cancel(multi, tmp_path, monkeypatch):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    value = state.read(p); value['job_id'] = 'default:123'; (p / 'status.json').write_text(json.dumps(value))
    with pytest.raises(ValueError): cancel.cancel(multi, p, fake)
    assert not fake.calls


def test_submission_manifest_immutable(multi, tmp_path, monkeypatch):
    p, m = prepare(multi, tmp_path)
    before = (p / 'manifest.json').read_bytes()
    fake = SlurmFake(config.select_cluster(multi, 'batch')); allow(monkeypatch)
    submit.submit(multi, [p.name], fake)
    assert (p / 'manifest.json').read_bytes() == before
    record = json.loads((p / 'submission.json').read_text())
    assert record['job_id'] == 'batch:123' and record['manifest_sha256'] == sha256(before).hexdigest()
    with pytest.raises(ValueError): submission.record(p, m, '124')
    assert json.loads((p / 'submission.json').read_text()) == record


def test_doctor_read_only(multi):
    cfg = config.select_cluster(multi, 'batch'); fake = SlurmFake(cfg)
    result = doctor.doctor(cfg, fake)
    assert result['ok'] and result['accounting_history']
    assert set(fake.operations()) <= {'identity', 'slurm_jobs', 'slurm_history', 'slurm_tools', 'slurm_partitions', 'root_check', 'executable', 'storage_usage', 'parent_chk_environment'}
    assert 'test -w' in next(c.text for c in fake.calls if c.operation == 'root_check')
    fake.history = Result()
    assert doctor.doctor(cfg, fake)['ok'] is False
    fake.partitions = Result()
    with pytest.raises(ValueError): doctor.doctor(cfg, fake)


def test_monitor_distinguishes_clusters(multi, tmp_path, monkeypatch):
    p, m, fake = submitted(multi, tmp_path, monkeypatch)
    submitted(multi, tmp_path, monkeypatch, 'default', 'pbs')
    fake.queue = Result(stdout=f"123|{m['attempt_id']}|fixture|RUNNING|8|00:00|fixture\n")
    result = monitor.observation(fake.cfg, fake, 'fixture')
    assert result['own']['jobs'][0]['job_id'] == 'batch:123'
    assert result['own']['jobs'][0]['attempt'] == p.name
    assert result['warnings'] == []


def test_slurm_fixed_commands(multi, tmp_path):
    _, m = prepare(multi, tmp_path); cfg = config.select_cluster(multi, 'batch')
    commands = [remote.slurm_submit(cfg, m), remote.slurm_jobs('123'), remote.slurm_jobs(user='fixture'),
                remote.slurm_accounting('123'), remote.slurm_find('fixture', m['attempt_id'], '2026-01-01'),
                remote.slurm_cancel('123'), remote.slurm_tools(), remote.slurm_partitions('fixture'), remote.slurm_history('fixture')]
    for c in commands:
        assert subprocess.run(['sh', '-n'], input=c.text, text=True).returncode == 0
        assert not set(shlex.split(c.text)) & {'--exclusive', 'rm', 'rmdir', 'mv', '>', '>>'}
    for bad in ('123;evil', '123_1', 'a:123', '-1'):
        with pytest.raises(ValueError): remote.slurm_cancel(bad)
    for c in commands:
        if c.operation not in ('submit', 'cancel'):
            from ag.transport import READ_OPERATIONS
            assert c.operation in READ_OPERATIONS


def test_slurm_output_widths_and_history_window():
    for command in (remote.slurm_jobs('123'), remote.slurm_jobs(user='fixture')):
        assert shlex.split(command.text)[-1] == '%i|%.200j|%.64u|%T|%C|%M|%P'
    for command in (remote.slurm_accounting('123'),
                    remote.slurm_find('fixture', 'water-001-optfreq', '2026-01-01'),
                    remote.slurm_history('fixture')):
        assert shlex.split(command.text)[-1] == (
            '--format=JobID%64,JobName%200,User%64,State%64,ExitCode%32,Elapsed%32,AllocCPUS%20')
    history = shlex.split(remote.slurm_history('fixture').text)
    assert '--starttime=now-30days' in history and '--endtime=now' in history
    assert '--starttime=2026-01-01' in remote.slurm_find('fixture', 'water-001-optfreq', '2026-01-01').text


def test_identified_node_query_and_selector_validation():
    command = remote.slurm_partition_nodes('synthetic')
    assert shlex.split(command.text) == [
        'sinfo', '-h', '--local', '-N', '-e', '-p', 'synthetic', '-O',
        'NodeList:256|,PartitionName:256|,CPUsState:64|,Memory:64|,AllocMem:64|,StateLong:64|,Available:32']
    from ag.transport import READ_OPERATIONS
    assert command.operation in READ_OPERATIONS
    assert subprocess.run(['sh', '-n'], input=command.text, text=True).returncode == 0
    for bad in ('--all', 'x;evil', '$(evil)', 'x\ny', '../path', '/path', 'a,b', 'a|b'):
        with pytest.raises(ValueError):
            remote.slurm_partition_nodes(bad)


def test_identified_nodes_duplicates_heterogeneity_and_precision():
    a = 'node-a|fixture|0/32/0/32|65535|0|idle|up\n'
    b = 'node-b|fixture|8/56/0/64|131072|8192|mixed|up\n'
    rows = slurm.parse_nodes(a + a + b, 'fixture')
    assert len(rows) == 2
    assert rows[0]['mem_total_gb'] == 65535 / 1024  # Do not round up to 64 GB.
    assert rows[1]['cores_total'] == 64
    rows = slurm.parse_nodes(a + a.replace('0/32/0/32', '8/24/0/32') + a, 'fixture')
    assert rows[0]['capacity_error']


@pytest.mark.parametrize('row', ['', 'node-a|fixture',
    'node-a|different|0/32/0/32|65536|0|idle|up',
    'node[1-2]|fixture|0/32/0/32|65536|0|idle|up',
    ('n' * 256) + '|fixture|0/32/0/32|65536|0|idle|up'])
def test_identified_node_bad_rows(row):
    with pytest.raises(ValueError):
        slurm.parse_nodes(row, 'fixture')


@pytest.mark.parametrize('value,field', [('N/A', 'mem_assigned_gb'), ('65537', 'mem_assigned_gb')])
def test_identified_node_unknown_memory(value, field):
    row = slurm.parse_nodes(f'node-a|fixture|0/32/0/32|65536|{value}|idle|up', 'fixture')[0]
    assert row[field] is None


def test_identified_node_unknown_counts_and_memory():
    row = slurm.parse_nodes('node-a|fixture|2/32/0/32|65536+|0|idle|up', 'fixture')[0]
    assert row['cores_total'] is None and row['mem_total_gb'] is None


def test_squeue_synthetic_diagnostic_shape():
    # Synthetic values only. Observed shape: 14-character truncated name,
    # 10-character user + 4 right spaces, 8-character partition + 6 right spaces.
    raw = '123|water-001-optf|sampleuser    |RUNNING|8|0:16|sampleqp      \n'
    fields = raw.rstrip('\n').split('|')
    assert len(fields[1]) == 14
    assert len(fields[2]) == 14 and len(fields[2].strip()) == 10
    assert fields[2].endswith(' ' * 4) and fields[6].endswith(' ' * 6)
    row = slurm.parse_queue(raw)[0]
    assert row['owner'] == 'sampleuser' and row['partition'] == 'sampleqp'
    assert slurm.core_breakdown([row], 'sampleuser') == (8, 0)
    with pytest.raises(ValueError, match='different owner'):
        slurm.core_breakdown([row], 'sampleuser2')


@pytest.mark.parametrize('source', ['queue', 'accounting', 'find'])
@pytest.mark.parametrize('identity', ['exact', 'truncated', 'suffix', 'wrong_owner'])
def test_padded_slurm_identity_is_exact(multi, tmp_path, monkeypatch, source, identity):
    p, m, fake = submitted(multi, tmp_path, monkeypatch, label='optfreq-long-label')
    assert len(m['attempt_id']) > 14
    name = m['attempt_id']
    owner = 'fixture'
    if identity == 'truncated':
        name = name[:14]
    elif identity == 'suffix':
        name += '-other'
    elif identity == 'wrong_owner':
        owner += '2'
    if source == 'queue':
        fake.exact = Result(stdout=f' 123 | {name:>200} | {owner:<64} | RUNNING | 8 | 0:16 | sampleqp \n')
    else:
        row = f' 123 | {name:>200} | {owner:<64} | COMPLETED | 0:0 | 00:01:00 | 8 \n'
        fake.accounting = Result(stdout=row)
        if source == 'find':
            state.write(p, 'unknown', job_id=None)
            fake.find = Result(stdout=row)
    if identity == 'exact':
        assert status.check(multi, p, fake)['state'] == ('running' if source == 'queue' else 'finished')
    else:
        with pytest.raises(ValueError, match='identity mismatch'):
            status.check(multi, p, fake)
        assert budget.totals(fake.cfg)[1] == 12 * 3600
    assert 'submit' not in fake.operations()


def test_doctor_padded_history_checks_owner(multi):
    cfg = config.select_cluster(multi, 'batch')
    fake = SlurmFake(cfg)
    fake.history = Result(stdout=' 123_1 | web-job-longer-than-fourteen | fixture   | CANCELLED by 42 | 0:15 | 00:01:00 | 8 \n')
    assert doctor.doctor(cfg, fake)['ok']
    fake.history.stdout = fake.history.stdout.replace('fixture   ', 'fixture2  ')
    with pytest.raises(ValueError, match='name/owner identity mismatch'):
        doctor.doctor(cfg, fake)


def test_budget_reserves_settles_without_balance_rejection(multi, tmp_path, monkeypatch):
    multi['clusters']['batch']['resources']['budget_core_hours'] = 1
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    assert budget.totals(fake.cfg) == (0, 12 * 3600)
    p2, _ = prepare(multi, tmp_path, label='next')
    seen = []
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: seen.append(a) or True)
    fake.accounting = Result(stdout='123|water-001-sp|fixture|COMPLETED|0:0|00:30:00|8\n')
    status.check(multi, p, fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 0)
    status.check(multi, p, fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 0)
    fake.qsub = Result(stdout='124\n')
    submit.submit(multi, [p2.name], fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 12 * 3600)
    assert '本次最多消耗 12 核时（核数 × walltime；实际以平台计费为准）' in seen[0][0]
    assert '预算' not in seen[0][0] and '累计已用' not in seen[0][0]


def test_budget_unknown_keeps_reservation_and_cancel_settles(multi, tmp_path, monkeypatch):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    cancel.cancel(multi, p, fake)
    assert budget.totals(fake.cfg) == (0, 12 * 3600)
    fake.accounting = Result(stdout='123|water-001-sp|fixture|CANCELLED by 42|0:15|00:10:00|8\n')
    assert status.check(multi, p, fake)['state'] == 'finished'
    assert budget.totals(fake.cfg) == (4800, 0)


def test_budget_presubmit_failure_releases(multi, tmp_path, monkeypatch):
    p, _ = prepare(multi, tmp_path)
    fake = SlurmFake(config.select_cluster(multi, 'batch')); fake.upload_corrupt = True
    allow(monkeypatch)
    with pytest.raises(ValueError): submit.submit(multi, [p.name], fake)
    assert state.read(p)['state'] == 'failed_presubmit'
    assert budget.totals(fake.cfg) == (0, 0)


def test_missing_ledger_does_not_reset_credit(multi, tmp_path, monkeypatch):
    _, _, fake = submitted(multi, tmp_path, monkeypatch)
    budget.ledger_path(fake.cfg).unlink()
    with pytest.raises(ValueError, match='missing from budget ledger'): budget.totals(fake.cfg)


def test_elapsed_and_expiry(multi):
    from datetime import date
    assert budget.seconds('2-03:04:05') == 183845
    cfg = config.select_cluster(multi, 'batch'); cfg['expires'] = '2026-06-30'
    assert budget.expiry_warning(cfg, date(2026, 6, 15)) is None
    assert budget.expiry_warning(cfg, date(2026, 6, 16)) == '资源即将到期，请先 fetch 全部结果'
    assert budget.expiry_warning(cfg, date(2026, 7, 1)) == '资源已到期，请先 fetch 全部结果'
    fake = SlurmFake(cfg)
    assert doctor.doctor(cfg, fake)['storage_kib'] == 1024
    assert monitor.observation(cfg, fake, 'fixture')['cluster']['storage_kib'] == 1024
    assert 'du -s -k --' in remote.storage_usage(cfg).text


@pytest.mark.parametrize('value', [True, -1, 0, float('inf'), '5000'])
def test_invalid_budget(multi, value):
    multi['clusters']['batch']['resources']['budget_core_hours'] = value
    with pytest.raises(ValueError): config.load_config(write_config(multi))


def test_ssh_key_hint(multi, monkeypatch):
    cfg = config.select_cluster(multi, 'batch'); t = SSHTransport(cfg)
    monkeypatch.setattr(t, '_execute', lambda *a: Result(255, stderr='Connection failed'))
    assert '密钥可能已过期，请到网页重新下载' in t.run(remote.identity()).stderr


def test_gaussian_versions_from_log():
    from ag._parse_outputs import gaussian_version
    assert gaussian_version(' Gaussian 16: ES64L-G16RevA.03 25-Dec-2016')['program_version'] == 'Gaussian 16 Rev A.03'
    assert gaussian_version(' Gaussian 16, Revision C.01,')['program_version'] == 'Gaussian 16 Rev C.01'
    assert gaussian_version('no header')['program_version'] is None
    mixed = gaussian_version('Gaussian 16, Revision A.03,\nGaussian 16, Revision C.01,')
    assert mixed['program_version'] is None and len(mixed['program_versions']) == 2


def test_legacy_config_plus_new_cluster(cfg, multi):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    loaded = config.load_config(write_config(cfg))
    assert config.select_cluster(loaded, 'default')['ssh']['host'] == 'fixture'
    assert config.select_cluster(loaded, 'batch')['scheduler'] == 'slurm'


def test_batch_estimate_includes_whole_confirmation_without_budget_gate(multi, tmp_path, monkeypatch, capsys):
    multi['clusters']['batch']['resources']['budget_core_hours'] = 20
    p, _ = prepare(multi, tmp_path)
    q, _ = prepare(multi, tmp_path, label='next')
    fake = SlurmFake(config.select_cluster(multi, 'batch'))
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: False)
    with pytest.raises(submit.UserCancelled): submit.submit(multi, [p.name, q.name], fake)
    text = capsys.readouterr().err
    assert '本次最多消耗 24 核时' in text and '预算' not in text
    assert not (p / '.submit-claim').exists() and not (q / '.submit-claim').exists()


def test_unknown_budget_is_not_released(multi, tmp_path, monkeypatch):
    p, _ = prepare(multi, tmp_path)
    fake = SlurmFake(config.select_cluster(multi, 'batch')); fake.qsub = Result(255)
    allow(monkeypatch)
    with pytest.raises(submit.UnknownSubmission): submit.submit(multi, [p.name], fake)
    assert budget.totals(fake.cfg) == (0, 12 * 3600)
    assert status.check(multi, p, fake)['state'] == 'unknown'
    assert budget.totals(fake.cfg) == (0, 12 * 3600)


def test_cli_transport_uses_manifest_after_default_change(multi, tmp_path, monkeypatch, capsys):
    p, m = prepare(multi, tmp_path)
    multi['clusters']['default']['ssh']['host'] = 'changed-fixture'
    seen = []
    def transport(cfg, **kwargs):
        seen.append((cfg['_cluster'], cfg['ssh']['host']))
        return SlurmFake(cfg)
    monkeypatch.setattr(cli, 'load_config', lambda: multi)
    monkeypatch.setattr('ag.transport.SSHTransport', transport)
    assert cli.main(['status', p.name, '--json']) == 0
    assert json.loads(capsys.readouterr().out)[0]['state'] == 'prepared'
    assert seen == [('batch', 'batch-fixture')]


def test_fetch_slurm_outputs_on_bound_cluster(multi, tmp_path, monkeypatch):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    status.check(multi, p, fake)
    fake.files.update({'water.log': b'synthetic log', 'job.slurm.out': b'stdout', 'job.slurm.err': b'stderr'})
    multi['clusters']['default']['ssh']['host'] = 'changed-fixture'
    result = fetch.fetch(multi, p, fake)
    assert result['files'] == ['water.log', 'job.slurm.out', 'job.slurm.err']
    assert (p / 'outputs/job.slurm.err').read_bytes() == b'stderr'


@pytest.mark.parametrize('environment', [None, 'scnet-a03'])
def test_slurm_local_guard_runs_once(multi, tmp_path, environment):
    # Execute the reviewed script only against a disposable local fake program.
    batch = multi['clusters']['batch']
    root = (tmp_path / 'remote').resolve(); root.mkdir()
    batch['remote'] = {'allowed_root': str(root), 'ag_root': str(root / 'ag')}
    binary = (tmp_path / 'bin').resolve(); binary.mkdir()
    batch['programs']['gaussian']['g16root'] = str(binary)
    if environment:
        batch['programs']['gaussian']['environment'] = environment
    if sys.platform != 'linux':
        realpath = binary / 'realpath'
        realpath.write_text(f'#!{sys.executable}\nimport pathlib, sys\nprint(pathlib.Path(sys.argv[-1]).resolve(strict=True))\n')
        realpath.chmod(0o700)
    program = binary / 'g16'
    program.write_text(f'#!{sys.executable}\nimport json, pathlib, os\n'
                       "assert json.loads(pathlib.Path('ag-start.json').read_text())['job_id'] == '123'\n"
                       "assert pathlib.Path(os.environ['GAUSS_SCRDIR']) == pathlib.Path.cwd() / 'scratch'\n"
                       + (f"assert os.environ['g16root'] == {str(binary.parent)!r}\n"
                          f"assert os.environ['GAUSS_EXEDIR'] == {str(binary / 'bsd') + ':' + str(binary)!r}\n"
                          "assert os.environ['PGI_FASTMATH_CPU'] == 'sandybridge'\n"
                          "assert os.environ['OMP_THREAD_LIMIT'] == '8'\n" if environment else '') +
                       "pathlib.Path('program-ran').write_text('once')\n")
    program.chmod(0o700)
    p, m = prepare(multi, tmp_path)
    work = Path(remote.attempt_dir(config.select_cluster(multi, 'batch'), m)); work.mkdir(parents=True)
    env = dict(os.environ, SLURM_JOB_ID='123', SLURM_SUBMIT_DIR=str(work), PATH=str(binary) + os.pathsep + os.environ['PATH'])
    script = (p / 'inputs/job.slurm').read_text()
    first = subprocess.run(['sh'], input=script, text=True, cwd=work, env=env, capture_output=True)
    assert first.returncode == 0, first.stderr
    before = {f.name: f.read_bytes() for f in work.glob('ag-*.json')}
    second = subprocess.run(['sh'], input=script, text=True, cwd=work, env=env, capture_output=True)
    assert second.returncode != 0
    assert before == {f.name: f.read_bytes() for f in work.glob('ag-*.json')}
    assert json.loads((work / 'ag-exit.json').read_text())['returncode'] == 0


def test_padded_squeue_long_names_and_all_user_cores(multi, tmp_path, monkeypatch):
    p, m, fake = submitted(multi, tmp_path, monkeypatch, label='long-name-smoke')
    owner = 'fixture'
    def row(job, name, state_name, cores):
        return f'{job:<128}|{name:<256}|{owner:<128}|{state_name:<64}|{cores:<32}|{"00:01":<32}|{"fixture":<128}\n'
    fake.exact = Result(stdout=row('123', m['attempt_id'], 'RUNNING', 8))
    assert status.check(multi, p, fake)['state'] == 'running'
    fake.queue = Result(stdout=fake.exact.stdout + row('456_1', 'external array', 'PENDING', 4)
                        + row('456_2', 'external array', 'PENDING', 4))
    username, jobs, used = status.inventory(fake, fake.cfg)
    assert username == owner and used == 16
    assert jobs[0]['name'] == m['attempt_id']
    assert slurm.core_breakdown(jobs, owner) == (8, 8)
    with pytest.raises(ValueError):
        slurm.parse_queue(row('123', m['attempt_id'], 'UNKNOWN_NEW_STATE', 8))
    with pytest.raises(ValueError):
        slurm.parse_queue(fake.queue.stdout.replace('456_2', '456_1'))


@pytest.mark.parametrize('extra', [
    {'environment': 'anything'},
    {'environment': 'scnet-a03', 'modules': ['fixture']},
    {'environment': 'scnet-a03', 'module_init': '/fixture/env.sh'},
])
def test_scnet_environment_rejects_unreviewed_or_vendor_setup(multi, extra):
    multi['clusters']['batch']['programs']['gaussian'].update(extra)
    with pytest.raises(ValueError):
        config.load_config(write_config(multi))


def test_scnet_environment_preserves_pbs_script(multi, tmp_path):
    _, m = prepare(multi, tmp_path, cluster='default')
    before = render.render(multi, m, 'water.gjf')
    multi['clusters']['default']['programs']['gaussian']['environment'] = 'scnet-a03'
    assert render.render(multi, m, 'water.gjf') == before
    multi['clusters']['batch']['programs']['gaussian']['environment'] = 'scnet-a03'
    config.load_config(write_config(multi))


def test_legacy_pbs_status_and_cancel_without_submission_manifest(cfg, tmp_path, monkeypatch):
    from test_core import job_text
    p, m = prepare(cfg, tmp_path, 'default')
    m.pop('cluster'); m.pop('scheduler')
    (p / 'manifest.json').write_text(json.dumps(m))
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg); fake.job = Result(stdout=job_text(m))
    assert status.check(cfg, p, fake)['state'] == 'running'
    allow(monkeypatch)
    assert cancel.cancel(cfg, p, fake)['state'] == 'cancelled'
    assert fake.calls[-1].text == 'qdel 123.fixture'
    assert not (p / 'submission.json').exists()


def test_squeue_malformed_cannot_free_cores():
    for text in ('123|web|fixture|PENDING|0|0:00|fixture',
                 '123|web|fixture|NEW_STATE|8|0:00|fixture',
                 '123_[1-9]|web|fixture|PENDING|8|0:00|fixture'):
        with pytest.raises(ValueError): slurm.parse_queue(text)


def test_sacct_wrong_id_and_ambiguous_name_refuse(multi, tmp_path, monkeypatch):
    p, m, fake = submitted(multi, tmp_path, monkeypatch)
    fake.accounting = Result(stdout='124|water-001-sp|fixture|COMPLETED|0:0|00:01:00|8\n')
    with pytest.raises(ValueError): status.check(multi, p, fake)
    assert budget.totals(fake.cfg)[1] == 12 * 3600


def test_ambiguous_unknown_name_stays_unknown(multi, tmp_path, monkeypatch):
    p, m = prepare(multi, tmp_path)
    fake = SlurmFake(config.select_cluster(multi, 'batch')); fake.qsub = Result(255)
    allow(monkeypatch)
    with pytest.raises(submit.UnknownSubmission): submit.submit(multi, [p.name], fake)
    fake.find = Result(stdout=''.join(f"{job}|{m['attempt_id']}|fixture|COMPLETED|0:0|00:01:00|8\n" for job in ('123', '124')))
    assert status.check(multi, p, fake)['state'] == 'unknown'
    assert not (p / 'submission.json').exists()
    assert budget.totals(fake.cfg) == (0, 12 * 3600)


def test_budget_batch_lock_serializes_core_reservations(multi, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    multi['clusters']['batch']['resources']['budget_core_hours'] = 20
    multi['clusters']['batch']['resources']['max_cores'] = 8
    paths = [prepare(multi, tmp_path, label=label)[0] for label in ('one', 'two')]
    allow(monkeypatch)
    def one(path):
        fake = SlurmFake(config.select_cluster(multi, 'batch'))
        try:
            submit.submit(multi, [path.name], fake)
            return 'submitted'
        except ValueError as exc:
            assert 'Core limit exceeded' in str(exc)
            assert 'submit' not in fake.operations()
            return 'refused'
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(one, paths)) == ['refused', 'submitted']
    assert budget.totals(config.select_cluster(multi, 'batch')) == (0, 12 * 3600)


def test_gaussian_facts_persist_revision(tmp_path):
    from ag.facts import build_facts
    directory = tmp_path / 'attempt'; (directory / 'outputs').mkdir(parents=True)
    (directory / 'manifest.json').write_text(json.dumps(dict(template='gaussian', inputs=[{'name': 'water.gjf'}])))
    (directory / 'outputs/water.log').write_bytes((Path(__file__).parent / 'fixtures/water_opt_freq.log').read_bytes())
    assert build_facts(directory)['program_version'] == 'Gaussian 16 Rev A.03'
    assert json.loads((directory / 'facts.json').read_text())['program_version'] == 'Gaussian 16 Rev A.03'


def test_separate_submits_reserve_unobserved_cores(multi, tmp_path, monkeypatch):
    multi['clusters']['batch']['resources']['max_cores'] = 8
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    q, _ = prepare(multi, tmp_path, label='next')
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: pytest.fail('readback lag must not exceed cap'))
    with pytest.raises(ValueError, match='Core limit exceeded'): submit.submit(multi, [q.name], fake)
    assert not (q / '.submit-claim').exists()
    assert state.read(p)['state'] == 'submitted'


def test_pbs_unused_program_fields_remain_compatible(cfg):
    cfg['programs']['gaussian']['legacy_note'] = 'unused fixture metadata'
    loaded = config.load_config(write_config(cfg))
    assert loaded['programs']['gaussian']['legacy_note'] == 'unused fixture metadata'


@pytest.mark.parametrize('terminal', ['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL'])
def test_status_purged_exact_job_uses_accounting(multi, tmp_path, monkeypatch, terminal):
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    fake.exact = Result(1, stderr='squeue: error: Invalid job id specified\n')
    fake.accounting = Result(stdout=f'123|water-001-sp|fixture|{terminal}|1:9|00:05:00|8\n')
    result = status.check(multi, p, fake)
    assert result['state'] == 'finished' and result['completion_source'] == 'sacct'
    assert result['scheduler_state'] == terminal
    assert fake.operations() == ['identity', 'slurm_jobs', 'slurm_accounting']
    assert all(' -j 123 ' in c.text for c in fake.calls if c.operation.startswith('slurm_'))


@pytest.mark.parametrize('queue', [
    Result(1, stderr='squeue: controller unavailable'),
    Result(1, stdout='Invalid job id specified'),
    Result(1, stderr='squeue: Invalid job id'),
    Result(255, stderr='synthetic SSH failure'),
    Result(255, stderr='Invalid job id specified'),
    Result(stdout='invalid queue output', stderr='Invalid job id specified'),
])
def test_status_other_queue_errors_stop(multi, tmp_path, monkeypatch, queue):
    from ag.transport import TransportError
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    fake.exact = queue
    before = (p / 'status.json').read_bytes()
    with pytest.raises((ValueError, TransportError)):
        status.check(multi, p, fake)
    assert (p / 'status.json').read_bytes() == before
    assert fake.operations() == ['identity', 'slurm_jobs']
