"""Offline lifecycle tests. All remote effects use the recording fake below."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from ag import attempt, cancel, cli, config, confirm, doctor, fetch, gaussian_input, remote, render, state, status, study, submit
from ag.locks import claim
from ag.transport import Result, SSHTransport, TransportError

INPUT = '%nprocshared=8\n%mem=10GB\n%chk=water.chk\n# B3LYP/6-31G(d) SP\n\nWater smoke\n\n0 1\nO 0 0 0\nH 0 0 1\nH 0 1 0\n\n'


@pytest.fixture
def cfg(tmp_path):
    # Test-only paths are ephemeral and contain no actual machine identifiers.
    root = tmp_path / 'cluster'
    local = tmp_path / 'studies'
    conf = tmp_path / 'config'
    conf.mkdir()
    ssh = conf / 'ssh_config'
    ssh.touch()
    return {'ssh': {'config_file': str(ssh), 'host': 'fixture'},
            'remote': {'allowed_root': str(root), 'ag_root': str(root / 'ag')},
            'scheduler': {'queue': 'batch'},
            'resources': {'max_cores': 44, 'tiers': {'simple': {'cores': 8, 'mem_gb': 12},
                          'general': {'cores': 22, 'mem_gb': 50}, 'complex': {'cores': 44, 'mem_gb': 120}}},
            'programs': {'gaussian': {'g16root': str(tmp_path / 'g16')}, 'xtb': {'root': str(tmp_path / 'chem')}},
            'local': {'studies_root': str(local)}, '_config_dir': str(conf)}


@pytest.fixture
def prepared(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    m = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=source,
                        tier='simple', walltime='00:30:00', label='sp')
    return attempt.find(cfg, m['attempt_id']), m


class Fake:
    def __init__(self, cfg):
        self.cfg, self.calls, self.files = cfg, [], {}
        self.qsub = Result(0, '123.fixture\n')
        self.qstat = Result()
        self.job = Result(153, '', 'qstat: Unknown Job Id')
        self.fail = None
        self.upload_corrupt = False
        self.download_corrupt = False

    def run(self, command):
        assert isinstance(command, remote.Command)
        self.calls.append(command)
        if command.operation == self.fail:
            raise TransportError('Synthetic interrupted connection')
        if command.operation == 'identity':
            return Result(stdout='fixture\n')
        if command.operation == 'jobs':
            return self.qstat if command.text == 'qstat -f' else self.job
        if command.operation == 'metadata':
            import shlex
            name = Path(shlex.split(command.text)[-1]).name
            data = self.files[name]
            path = shlex.split(command.text)[-1]
            return Result(stdout=f'{len(data)}\n{sha256(data).hexdigest()}  {path}\n')
        if command.operation == 'submit':
            if isinstance(self.qsub, Exception):
                raise self.qsub
            return self.qsub
        if command.operation == 'output_exists':
            return Result(0 if 'job.pbs.out' in self.files else 1)
        return Result()

    def upload(self, local, manifest, name):
        self.calls.append(remote.Command('upload', name))
        self.files[name] = local.read_bytes() + (b'corruption' if self.upload_corrupt else b'')

    def download(self, manifest, name, local):
        self.calls.append(remote.Command('download', name))
        local.write_bytes(self.files[name] + (b'corruption' if self.download_corrupt else b''))

    def operations(self):
        return [c.operation for c in self.calls]


def allow(monkeypatch):
    monkeypatch.setattr(confirm, 'confirm', lambda *args: True)


def test_prepare_and_bundle(cfg, prepared):
    p, m = prepared
    assert m['attempt_id'] == 'smoke-001-sp'
    assert m['remote_dir'] == 'smoke/smoke-001-sp'
    assert len(m['pbs_job_name']) == 14
    assert state.read(p)['state'] == 'prepared'
    assert attempt.bundle(attempt.verified_files(cfg, p, m))[1] == m['bundle_sha256']
    assert 'Geometry' not in m
    assert m['science']['n_atoms'] == 3
    assert 'Route:' in attempt.summary(cfg, m)
    assert m['bundle_sha256'] in attempt.summary(cfg, m)
    script = (p / 'inputs/job.pbs').read_text()
    assert '#PBS -V' not in script and '#PBS -r n' in script
    assert 'set -C' in script and 'GAUSS_SCRDIR="$scratch"' in script
    assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0


def test_parallel_prepare_unique_sequences(cfg, prepared, tmp_path):
    def prepare(n):
        return attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                               tier='simple', walltime='00:01:00', label=f'sp{n}')['attempt_id']
    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(prepare, range(8)))
    assert len({i.split('-')[1] for i in ids}) == 8


def test_atomic_claim(tmp_path):
    def reserve(_):
        try:
            claim(tmp_path / 'claim')
            return True
        except FileExistsError:
            return False
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(reserve, range(24))) == 1


@pytest.mark.parametrize('key,value', [('nprocshared', '9'), ('mem', '11GB'), ('chk', '../escape.chk'), ('chk', 'bad name.chk')])
def test_invalid_gaussian(key, value):
    import re
    text = re.sub(rf'%{key}=.*', f'%{key}={value}', INPUT)
    with pytest.raises(ValueError):
        gaussian_input.validate(text, 8, 12)


@pytest.mark.parametrize('text', [INPUT.replace('# B3LYP', 'B3LYP'), INPUT.replace('0 1', '0 0'),
    INPUT.replace('O 0 0 0', 'O nan 0 0'), INPUT + '--Link1--\n', INPUT.replace(' SP', ' External=evil'),
    '%oldchk=parent.chk\n' + INPUT, INPUT + '@file\n'])
def test_unsafe_gaussian(text):
    with pytest.raises(ValueError):
        gaussian_input.validate(text, 8, 12)


def test_submit_once(cfg, prepared, monkeypatch):
    p, m = prepared
    fake = Fake(cfg)
    allow(monkeypatch)
    manifest_bytes = (p / 'manifest.json').read_bytes()
    result = submit.submit(cfg, [p.name], fake)
    assert result[0]['state'] == 'submitted'
    assert (p / '.submit-claim').exists()
    assert fake.operations().count('submit') == 1
    assert (p / 'manifest.json').read_bytes() == manifest_bytes
    fake.calls.clear()
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake)
    assert fake.calls == []


def test_cancel_submission(cfg, prepared, monkeypatch):
    p, m = prepared
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: False)
    with pytest.raises(submit.UserCancelled):
        submit.submit(cfg, [p.name], fake)
    assert fake.operations() == ['identity', 'jobs']
    assert not (p / '.submit-claim').exists()
    assert state.read(p)['state'] == 'prepared'


@pytest.mark.parametrize('response', [Result(0, 'not a job'), Result(255, '', 'disconnect'), TransportError('timeout')])
def test_unknown_stops_batch(cfg, prepared, tmp_path, monkeypatch, response):
    p, m = prepared
    m2 = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                         tier='simple', walltime='00:30:00', label='second')
    p2 = attempt.find(cfg, m2['attempt_id'])
    fake = Fake(cfg)
    fake.qsub = response
    allow(monkeypatch)
    with pytest.raises(submit.UnknownSubmission):
        submit.submit(cfg, [p.name, p2.name], fake)
    assert state.read(p)['state'] == 'unknown'
    assert state.read(p2)['state'] == 'prepared'
    assert fake.operations()[-1] == 'submit'
    assert fake.operations().count('submit') == 1
    fake.calls.clear()
    with pytest.raises(ValueError):
        submit.submit(cfg, [p.name], fake)
    assert fake.calls == []


@pytest.mark.parametrize('failure', ['create_attempt', 'hash', 'qsub_reject'])
def test_presubmit_failure_never_retries(cfg, prepared, monkeypatch, failure):
    p, m = prepared
    fake = Fake(cfg)
    if failure == 'create_attempt': fake.fail = failure
    if failure == 'hash': fake.upload_corrupt = True
    if failure == 'qsub_reject': fake.qsub = Result(1, '', 'qsub: invalid queue')
    allow(monkeypatch)
    with pytest.raises((ValueError, TransportError)):
        submit.submit(cfg, [p.name], fake)
    assert state.read(p)['state'] == 'failed_presubmit'
    if failure != 'qsub_reject': assert 'submit' not in fake.operations()
    fake.calls.clear()
    with pytest.raises(ValueError): submit.submit(cfg, [p.name], fake)
    assert fake.calls == []


def test_mutation_during_confirmation(cfg, prepared, monkeypatch):
    p, _ = prepared
    fake = Fake(cfg)
    def mutate(*args):
        (p / 'inputs/water.gjf').write_text(INPUT + 'changed')
        return True
    monkeypatch.setattr(confirm, 'confirm', mutate)
    with pytest.raises(ValueError): submit.submit(cfg, [p.name], fake)
    assert 'create_attempt' not in fake.operations()
    assert not (p / '.submit-claim').exists()


def test_input_snapshot_resists_later_mutation(cfg, prepared, monkeypatch):
    p, m = prepared
    fake = Fake(cfg)
    allow(monkeypatch)
    upload = fake.upload
    def mutate(local, manifest, name):
        (p / 'inputs/water.gjf').write_text('changed after snapshot')
        upload(local, manifest, name)
    fake.upload = mutate
    submit.submit(cfg, [p.name], fake)
    assert fake.files['water.gjf'] == INPUT.encode()


def job_text(m=None, *, cores=8, owner='fixture', state_='R'):
    return (f'Job Id: 123.fixture\n    Job_Name = {m["pbs_job_name"] if m else "unrelated"}\n'
            f'    Job_Owner = {owner}@fixture\n    job_state = {state_}\n'
            f'    Resource_List.nodes = 1:ppn={cores}\n    exit_status = 0\n')


def test_counts_non_ag_and_other_states():
    for state_ in ('Q', 'R', 'H', 'E', 'T', 'W', 'S'):
        assert status.occupied(status.parse_jobs(job_text(cores=22, state_=state_)), 'fixture') == 22
    assert status.occupied(status.parse_jobs(job_text(owner='different')), 'fixture') == 0
    assert status.occupied(status.parse_jobs(job_text(state_='C')), 'fixture') == 0
    with pytest.raises(ValueError): status.occupied(status.parse_jobs(job_text().replace('1:ppn=8', 'nonsense')), 'fixture')
    with pytest.raises(ValueError): status.parse_jobs('scheduler malfunction')


def test_limit_blocks_before_confirmation(cfg, prepared, monkeypatch):
    fake = Fake(cfg)
    fake.qstat = Result(stdout=job_text(cores=44))
    monkeypatch.setattr(confirm, 'confirm', lambda *args: pytest.fail('must not confirm'))
    with pytest.raises(ValueError): submit.submit(cfg, [prepared[0].name], fake)
    assert 'create_attempt' not in fake.operations()


def test_unknown_reconcile_read_only(cfg, prepared):
    p, m = prepared
    state.write(p, 'submitting'); state.write(p, 'unknown')
    fake = Fake(cfg)
    assert status.check(cfg, p, fake)['state'] == 'unknown'
    assert set(fake.operations()) <= {'identity', 'jobs', 'listing'}
    fake.qstat = Result(stdout=job_text(m))
    assert status.check(cfg, p, fake)['state'] == 'submitted'
    assert state.read(p)['job_id'] == '123.fixture'


def test_status_absent_retains_without_output(cfg, prepared):
    p, m = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg)
    assert status.check(cfg, p, fake)['state'] == 'submitted'
    fake.files['job.pbs.out'] = b'output'
    assert status.check(cfg, p, fake)['state'] == 'finished'


def test_status_error_does_not_infer_completion(cfg, prepared):
    p, _ = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg); fake.job = Result(255, '', 'connection error')
    with pytest.raises(TransportError): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'


def finish(p):
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture'); state.write(p, 'finished', exit_status=0)


def test_fetch_verified_no_overwrite(cfg, prepared):
    p, m = prepared
    finish(p)
    fake = Fake(cfg); fake.files = {'water.log': b'Normal termination', 'job.pbs.out': b'output'}
    assert fetch.fetch(cfg, p, fake)['state'] == 'fetched'
    assert (p / 'outputs/water.log').read_bytes() == fake.files['water.log']
    with pytest.raises(ValueError): fetch.fetch(cfg, p, fake)


def test_fetch_existing_is_local_refusal(cfg, prepared):
    p, m = prepared; finish(p)
    (p / 'outputs/water.log').write_bytes(b'preserve')
    fake = Fake(cfg)
    with pytest.raises(FileExistsError): fetch.fetch(cfg, p, fake)
    assert not fake.calls
    assert (p / 'outputs/water.log').read_bytes() == b'preserve'


def test_fetch_hash_failure_leaves_no_published_files(cfg, prepared):
    p, m = prepared; finish(p)
    fake = Fake(cfg); fake.files = {'water.log': b'normal', 'job.pbs.out': b'output'}
    fake.download_corrupt = True
    with pytest.raises(ValueError): fetch.fetch(cfg, p, fake)
    assert not (p / 'outputs/water.log').exists()
    assert state.read(p)['state'] == 'finished'
    assert list((p / 'outputs/.partial').glob('*/water.log'))


def test_cancel_exactly_once(cfg, prepared, monkeypatch):
    p, m = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg); allow(monkeypatch)
    assert cancel.cancel(cfg, p, fake)['state'] == 'cancelled'
    assert [c.text for c in fake.calls] == ['qdel 123.fixture']
    with pytest.raises(ValueError): cancel.cancel(cfg, p, fake)
    assert len(fake.calls) == 1


def test_cancel_declined_zero_remote_calls(cfg, prepared, monkeypatch):
    p, _ = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: False)
    with pytest.raises(submit.UserCancelled): cancel.cancel(cfg, p, fake)
    assert fake.calls == []


def test_dialog_non_mac_and_argument_injection(monkeypatch):
    monkeypatch.setattr(confirm.sys, 'platform', 'linux')
    monkeypatch.setattr(confirm.subprocess, 'run', lambda *args, **kw: pytest.fail('non-Mac must not launch'))
    assert confirm.confirm('test') is False
    monkeypatch.setattr(confirm.sys, 'platform', 'darwin')
    seen = []
    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return Result(stdout='confirmed\n')
    monkeypatch.setattr(confirm.subprocess, 'run', run)
    attack = '" & do shell script "touch injected"'
    assert confirm.confirm(attack)
    assert attack not in seen[0][0][2]
    assert seen[0][0][-2] == attack
    assert 'default button "取消"' in confirm.SCRIPT
    assert 'giving up after 300' in confirm.SCRIPT


@pytest.mark.parametrize('flag', ['--yes', '--force', '--no-confirm'])
def test_cli_has_no_confirmation_bypass(flag):
    with pytest.raises(SystemExit): cli.main(['submit', 'smoke-001-sp', flag])


@pytest.mark.parametrize('template,params', [('gaussian', {'--evil': ''}), ('xtb', {'--gfn': '1'}),
    ('xtb', {'--alpb': 'water; evil'}), ('crest', {'--ewin': 'nan'}), ('crest', {'--uhf': '-1'}),
    ('crest', {'--gfn2': '', '--gfnff': ''})])
def test_parameter_whitelist(template, params):
    with pytest.raises(ValueError): render.parameters(template, params)


@pytest.mark.parametrize('template,params', [('xtb', {'--gfn': '2', '--opt': ''}), ('crest', {'--gfn2': '', '--quick': ''})])
def test_other_templates(cfg, prepared, tmp_path, template, params):
    source = tmp_path / 'water.xyz'; source.write_text('3\nwater\nO 0 0 0\nH 0 0 1\nH 0 1 0\n')
    m = attempt.prepare(cfg, study_name='smoke', template=template, input_path=source, tier='simple',
                        walltime='00:30:00', label=template, params=params)
    script = attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)['job.pbs'].decode()
    assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0
    assert 'XTBPATH=' in script and 'OMP_NUM_THREADS=8' in script


def test_doctor_is_read_only(cfg):
    fake = Fake(cfg)
    assert doctor.doctor(cfg, fake)['ok']
    assert set(fake.operations()) == {'identity', 'jobs', 'queues', 'root_check', 'executable'}


def test_remote_allowlist_and_paths(cfg, prepared):
    _, m = prepared
    commands = [remote.identity(), remote.queues(), remote.jobs(), remote.jobs('123.fixture'), remote.root_check(cfg),
                remote.executable(cfg['programs']['gaussian']['g16root'] + '/g16'), remote.create_attempt(cfg, m),
                remote.metadata(cfg, m, 'water.gjf'), remote.upload_check(cfg, m, 'water.gjf'),
                remote.output_exists(cfg, m, 'job.pbs.out'), remote.listing(cfg, m), remote.submit(cfg, m), remote.cancel('123.fixture')]
    import shlex
    allowed = {'id', 'qstat', 'test', 'mkdir', 'stat', 'sha256sum', 'ls', 'cd', 'qsub', 'qdel'}
    for c in commands:
        assert not any(token in shlex.split(c.text) for token in ('rm', 'rmdir', 'mv', 'cp', '>', '>>'))
        assert subprocess.run(['sh', '-n'], input=c.text, text=True).returncode == 0
        tokens = shlex.shlex(c.text, posix=True, punctuation_chars=True)
        expect_command = True
        for token in tokens:
            if token in ('&&', ';'):
                expect_command = True
            elif token in ('if', 'then', 'fi'):
                continue
            elif expect_command:
                assert token in allowed
                expect_command = False
    for bad in ('../escape', 'file;evil', '/absolute'):
        with pytest.raises(ValueError): remote.metadata(cfg, m, bad)
    with pytest.raises(ValueError): remote.attempt_dir(cfg, {**m, 'remote_dir': '../escape'})
    with pytest.raises(ValueError): remote.cancel('123;evil')


def write_config(cfg):
    path = Path(cfg['_config_dir']) / 'config.toml'
    lines = []
    def section(name, data):
        lines.append(f'[{name}]')
        for key, value in data.items():
            if not isinstance(value, dict): lines.append(f'{key} = {json.dumps(value)}')
        for key, value in data.items():
            if isinstance(value, dict): section(f'{name}.{key}', value)
    for name, data in cfg.items():
        if not name.startswith('_'): section(name, data)
    path.write_text('\n'.join(lines))
    return path


def test_config_complete_and_private(cfg):
    assert config.load_config(write_config(cfg)) == cfg
    cfg['remote']['ag_root'] += '-wrong'
    with pytest.raises(ValueError): config.load_config(write_config(cfg))


@pytest.mark.parametrize('section,key', [('ssh', 'host'), ('ssh', 'config_file'), ('remote', 'allowed_root'),
    ('remote', 'ag_root'), ('local', 'studies_root'), ('resources', 'tiers'), ('scheduler', 'queue')])
def test_config_missing_keys(cfg, section, key):
    del cfg[section][key]
    with pytest.raises(ValueError): config.load_config(write_config(cfg))


@pytest.mark.parametrize('value', ['relative', '/', '../escape', '<placeholder>', '/bad\npath', '/safe/../escape', '/bad path'])
def test_invalid_remote_config_path(value):
    with pytest.raises(ValueError): config.absolute(value, 'test', remote=True)


def test_config_rejects_studies_inside_git(cfg):
    root = Path(cfg['local']['studies_root'])
    root.mkdir(parents=True); (root / '.git').mkdir()
    with pytest.raises(ValueError): config.load_config(write_config(cfg))


def test_study_symlink_rejected(cfg, tmp_path):
    root = Path(cfg['local']['studies_root']); root.mkdir()
    target = tmp_path / 'outside'; target.mkdir()
    (root / 'linked').symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError): study.init(cfg, 'linked')


def test_forbidden_state_rewind(prepared):
    p, _ = prepared
    state.write(p, 'submitting'); state.write(p, 'unknown')
    with pytest.raises(ValueError): state.write(p, 'prepared')


def test_crash_in_submitting_reconciles_only_read_only(cfg, prepared):
    p, m = prepared
    claim(p / '.submit-claim'); state.write(p, 'submitting')
    fake = Fake(cfg)
    assert status.check(cfg, p, fake)['state'] == 'unknown'
    assert set(fake.operations()) <= {'identity', 'jobs', 'listing'}


def test_completed_scheduler_records_exit(cfg, prepared):
    p, m = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg); fake.job = Result(stdout=job_text(m, state_='C').replace('exit_status = 0', 'exit_status = 9'))
    result = status.check(cfg, p, fake)
    assert result['state'] == 'finished' and result['exit_status'] == 9


def test_cancel_failure_records_no_retry(cfg, prepared, monkeypatch):
    p, _ = prepared
    state.write(p, 'submitting'); state.write(p, 'submitted', job_id='123.fixture')
    fake = Fake(cfg); fake.fail = 'cancel'; allow(monkeypatch)
    with pytest.raises(TransportError): cancel.cancel(cfg, p, fake)
    assert fake.operations() == ['cancel']
    assert state.read(p)['state'] == 'submitted'
    assert 'failed_or_unknown' in (p.parent.parent / 'journal.jsonl').read_text()


def test_transport_argv_and_timeout(cfg, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(subprocess, 'run', lambda args, **kw: seen.append((args, kw)) or Result())
    t = SSHTransport(cfg)
    t.run(remote.identity())
    assert seen[0][0] == ['ssh', *t.options, 'fixture', '--', 'id -un']
    assert seen[0][1]['timeout'] == 60
    with pytest.raises(ValueError): t.run('arbitrary command')


def test_remote_create_existing_and_symlink_rejected(cfg, prepared, tmp_path):
    p, m = prepared
    # Run fixed generated shell commands only against disposable local fixture dirs.
    root = tmp_path.resolve() / 'remote-root'; root.mkdir()
    cfg['remote'] = {'allowed_root': str(root), 'ag_root': str(root / 'ag')}
    command = remote.create_attempt(cfg, m).text
    assert subprocess.run(['sh', '-c', command], capture_output=True).returncode == 0
    target = Path(remote.attempt_dir(cfg, m)); keep = target / 'keep'; keep.write_bytes(b'unchanged')
    assert subprocess.run(['sh', '-c', command], capture_output=True).returncode != 0
    assert keep.read_bytes() == b'unchanged'
    other = {**m, 'study_id': 'linked', 'remote_dir': 'linked/' + m['attempt_id']}
    (root / 'ag/linked').symlink_to(target, target_is_directory=True)
    assert subprocess.run(['sh', '-c', remote.create_attempt(cfg, other).text], capture_output=True).returncode != 0


def test_batch_one_confirmation(cfg, prepared, tmp_path, monkeypatch):
    p, m = prepared
    other = attempt.prepare(cfg, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                            tier='simple', walltime='00:30:00', label='other')
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or True)
    fake = Fake(cfg)
    assert len(submit.submit(cfg, [p.name, other['attempt_id']], fake)) == 2
    assert len(seen) == 1 and '16 / 44' in seen[0]
    assert p.name in seen[0] and other['attempt_id'] in seen[0]


def test_cli_config_error_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'load_config', lambda: (_ for _ in ()).throw(config.ConfigError('missing config')))
    assert cli.main(['doctor', '--json']) == 1
    assert json.loads(capsys.readouterr().out)['exit_code'] == 1


def test_dialog_timeouts_and_errors(monkeypatch):
    monkeypatch.setattr(confirm.sys, 'platform', 'darwin')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(stdout='cancelled\n'))
    assert confirm.confirm('test') is False
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(1, '', 'execution error: User canceled. (-128)'))
    assert confirm.confirm('test') is False
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Result(1, '', 'dialog failed'))
    with pytest.raises(OSError): confirm.confirm('test')
