"""T16 offline coverage: scheduler outcomes, cluster binding and strict capacity."""
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
    m = attempt.prepare(cfg, study_name='water', template='gaussian', input_path=source,
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


def test_config_legacy_named_and_strict(multi, cfg):
    legacy = config.load_config(write_config(cfg))
    assert config.scheduler_kind(config.select_cluster(legacy)) == 'pbs'
    loaded = config.load_config(write_config(multi))
    assert config.select_cluster(loaded, 'batch')['resources']['max_committed_cores'] == 44
    multi['clusters']['batch']['resources']['max_committed_cores'] = 45
    with pytest.raises(ValueError): config.load_config(write_config(multi))


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
    assert submit.capacity(fake.cfg, fake, []) == (44, 'Slurm 无硬件保证；运行加排队按 max_cores 严格统计')
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


def test_budget_reserves_settles_and_refuses(multi, tmp_path, monkeypatch):
    multi['clusters']['batch']['resources']['budget_core_hours'] = 20
    p, _, fake = submitted(multi, tmp_path, monkeypatch)
    assert budget.totals(fake.cfg) == (0, 12 * 3600)
    p2, _ = prepare(multi, tmp_path, label='next')
    seen = []
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: seen.append(a) or True)
    with pytest.raises(ValueError, match='budget exceeded'): submit.submit(multi, [p2.name], fake)
    assert not seen and not (p2 / '.submit-claim').exists()
    fake.accounting = Result(stdout='123|water-001-sp|fixture|COMPLETED|0:0|00:30:00|8\n')
    status.check(multi, p, fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 0)
    status.check(multi, p, fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 0)
    fake.qsub = Result(stdout='124\n')
    submit.submit(multi, [p2.name], fake)
    assert budget.totals(fake.cfg) == (4 * 3600, 12 * 3600)
    assert '本次最多 12 核时；累计已用 4、预留 0、预算 20' in seen[0][0]


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


def test_batch_budget_includes_whole_confirmation(multi, tmp_path, monkeypatch):
    multi['clusters']['batch']['resources']['budget_core_hours'] = 20
    p, _ = prepare(multi, tmp_path)
    q, _ = prepare(multi, tmp_path, label='next')
    fake = SlurmFake(config.select_cluster(multi, 'batch'))
    monkeypatch.setattr('ag.confirm.confirm', lambda *a: pytest.fail('must refuse entire batch'))
    with pytest.raises(ValueError, match='budget exceeded'): submit.submit(multi, [p.name, q.name], fake)
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


def test_slurm_local_guard_runs_once(multi, tmp_path):
    # Execute the reviewed script only against a disposable local fake program.
    batch = multi['clusters']['batch']
    root = (tmp_path / 'remote').resolve(); root.mkdir()
    batch['remote'] = {'allowed_root': str(root), 'ag_root': str(root / 'ag')}
    binary = (tmp_path / 'bin').resolve(); binary.mkdir()
    batch['programs']['gaussian']['g16root'] = str(binary)
    if sys.platform != 'linux':
        realpath = binary / 'realpath'
        realpath.write_text(f'#!{sys.executable}\nimport pathlib, sys\nprint(pathlib.Path(sys.argv[-1]).resolve(strict=True))\n')
        realpath.chmod(0o700)
    program = binary / 'g16'
    program.write_text(f'#!{sys.executable}\nimport json, pathlib\n'
                       "assert json.loads(pathlib.Path('ag-start.json').read_text())['job_id'] == '123'\n"
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


def test_budget_batch_lock_serializes_available_credit(multi, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    multi['clusters']['batch']['resources']['budget_core_hours'] = 20
    paths = [prepare(multi, tmp_path, label=label)[0] for label in ('one', 'two')]
    allow(monkeypatch)
    def one(path):
        fake = SlurmFake(config.select_cluster(multi, 'batch'))
        try:
            submit.submit(multi, [path.name], fake)
            return 'submitted'
        except ValueError as exc:
            assert 'budget exceeded' in str(exc)
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
