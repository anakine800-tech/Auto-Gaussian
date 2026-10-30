"""Offline lifecycle tests. All remote effects use the recording fake below."""
from hashlib import sha256
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from ag import attempt, cancel, cli, config, confirm, doctor, fetch, gaussian_input, remote, render, state, status, study, submit
from ag import submission
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
            'resources': {'max_cores': 44, 'tiers': {'mini': {'cores': 4, 'mem_gb': 10}, 'simple': {'cores': 8, 'mem_gb': 12},
                          'general': {'cores': 22, 'mem_gb': 50}, 'complex': {'cores': 44, 'mem_gb': 120}}},
            'programs': {'gaussian': {'g16root': str(tmp_path / 'g16')}, 'xtb': {'root': str(tmp_path / 'chem')}},
            'local': {'studies_root': str(local)}, '_config_dir': str(conf)}


@pytest.fixture
def prepared(cfg, tmp_path):
    study.init(cfg, 'smoke')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
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
        if command.operation == 'parent_chk_environment':
            return Result(stdout='Python 3.6.8\nproc_fd=yes\n')
        if command.operation == 'identity':
            return Result(stdout='fixture\n')
        if command.operation == 'jobs':
            return self.qstat if command.text == 'qstat -f' else self.job
        if command.operation == 'receipt':
            return Result(stdout='absent\n')
        if command.operation == 'output_observation':
            return Result(stdout='water.log absent\njob.pbs.out absent\n')
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
        return attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
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
    m2 = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
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
    assert state.read(p)['job_id'] == 'default:123.fixture'


def test_status_absent_awaits_second_observation_without_receipt(cfg, prepared):
    p, m = prepared
    state.write(p, 'submitting'); seed_submission(p)
    fake = Fake(cfg)
    assert status.check(cfg, p, fake)['state'] == 'awaiting_second_observation'
    fake.files['job.pbs.out'] = b'output'
    assert status.check(cfg, p, fake)['state'] == 'awaiting_second_observation'


def test_status_error_does_not_infer_completion(cfg, prepared):
    p, _ = prepared
    state.write(p, 'submitting'); seed_submission(p)
    fake = Fake(cfg); fake.job = Result(255, '', 'connection error')
    with pytest.raises(TransportError): status.check(cfg, p, fake)
    assert state.read(p)['state'] == 'submitted'


def finish(p):
    state.write(p, 'submitting'); seed_submission(p); state.write(p, 'finished', exit_status=0)


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
    state.write(p, 'submitting'); seed_submission(p)
    fake = Fake(cfg); allow(monkeypatch)
    assert cancel.cancel(cfg, p, fake)['state'] == 'cancelled'
    assert [c.text for c in fake.calls] == ['qdel 123.fixture']
    with pytest.raises(ValueError): cancel.cancel(cfg, p, fake)
    assert len(fake.calls) == 1


def test_cancel_declined_zero_remote_calls(cfg, prepared, monkeypatch):
    p, _ = prepared
    state.write(p, 'submitting'); seed_submission(p)
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
    assert 'buttons {"不提交", actionText} default button "不提交" cancel button "不提交"' in confirm.SCRIPT
    assert 'buttons {"保留作业", actionText} default button "保留作业" cancel button "保留作业" with icon caution' in confirm.SCRIPT
    assert 'set actionText to "终止作业"' in confirm.SCRIPT
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
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template=template, input_path=source, tier='simple',
                        walltime='00:30:00', label=template, params=params)
    script = attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)['job.pbs'].decode()
    assert subprocess.run(['sh', '-n'], input=script, text=True).returncode == 0
    assert 'XTBPATH=' in script and 'OMP_NUM_THREADS=8' in script


def test_doctor_is_read_only(cfg):
    fake = Fake(cfg)
    assert doctor.doctor(cfg, fake)['ok']
    assert set(fake.operations()) == {'identity', 'jobs', 'queues', 'root_check', 'executable', 'parent_chk_environment'}


def test_remote_allowlist_and_paths(cfg, prepared):
    _, m = prepared
    commands = [remote.identity(), remote.queues(), remote.nodes(), remote.jobs(), remote.jobs('123.fixture'), remote.root_check(cfg),
                remote.executable(cfg['programs']['gaussian']['g16root'] + '/g16'), remote.create_attempt(cfg, m),
                remote.metadata(cfg, m, 'water.gjf'), remote.upload_check(cfg, m, 'water.gjf'),
                remote.output_exists(cfg, m, 'job.pbs.out'), remote.listing(cfg, m), remote.submit(cfg, m), remote.cancel('123.fixture'),
                remote.incomplete_output_observation(cfg, m, 'water.log')]
    import shlex
    allowed = {'id', 'qstat', 'pbsnodes', 'test', 'mkdir', 'stat', 'sha256sum', 'ls', 'cd', 'qsub', 'qdel', 'printf'}
    for c in commands:
        assert not any(token in shlex.split(c.text) for token in ('rm', 'rmdir', 'mv', 'cp', '>', '>>'))
        assert subprocess.run(['sh', '-n'], input=c.text, text=True).returncode == 0
        tokens = shlex.shlex(c.text, posix=True, punctuation_chars=True)
        expect_command = True
        for token in tokens:
            if token in ('&&', ';'):
                expect_command = True
            elif token in ('if', 'then', 'else', 'fi'):
                continue
            elif expect_command:
                assert token in allowed
                expect_command = False
    for bad in ('../escape', 'file;evil', '/absolute'):
        with pytest.raises(ValueError): remote.metadata(cfg, m, bad)
        with pytest.raises(ValueError): remote.incomplete_output_observation(cfg, m, bad)
    with pytest.raises(ValueError): remote.incomplete_output_observation(cfg, m, 'undeclared.log')
    with pytest.raises(ValueError): remote.incomplete_output_observation(cfg, {**m, 'remote_dir': '../escape'}, 'water.log')
    directory = remote.attempt_dir(cfg, m)
    p = directory + '/water.log'
    q, parent = shlex.quote(p), shlex.quote(directory)
    checks = ' && '.join('test ! -L ' + shlex.quote(str(part))
                         for part in reversed((Path(p), *Path(p).parents[:-1])))
    command = remote.incomplete_output_observation(cfg, m, 'water.log')
    assert command.text == (f'{checks} && test -d {parent} && test -x {parent} && '
                            f'if test -e {q}; then test -f {q} && test -r {q} && '
                            f"stat -c '%s %y' -- {q}; else "
                            f'test ! -L {q} && test -d {parent} && test -x {parent} && '
                            "printf 'absent\\n'; fi")
    from ag.transport import READ_OPERATIONS
    assert command.operation == 'output_observation' and command.operation in READ_OPERATIONS
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
    assert config.load_config(write_config(cfg)) == {
        **cfg, '_config_path': str(Path(cfg['_config_dir']) / 'config.toml'),
        'resources': {**cfg['resources'], 'max_committed_cores': 44}}
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


def test_scheduler_completion_alone_is_not_program_receipt(cfg, prepared):
    p, m = prepared
    state.write(p, 'submitting'); seed_submission(p)
    fake = Fake(cfg); fake.job = Result(stdout=job_text(m, state_='C').replace('exit_status = 0', 'exit_status = 9'))
    result = status.check(cfg, p, fake)
    assert result['state'] == 'interrupted' and result['exit_status'] is None


def test_cancel_failure_records_no_retry(cfg, prepared, monkeypatch):
    p, _ = prepared
    state.write(p, 'submitting'); seed_submission(p)
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
    other = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                            tier='simple', walltime='00:30:00', label='other')
    seen = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: seen.append(text) or True)
    fake = Fake(cfg)
    assert len(submit.submit(cfg, [p.name, other['attempt_id']], fake)) == 2
    assert len(seen) == 1 and '16 / 上限 44 核' in seen[0]
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


@pytest.mark.parametrize('operation', [remote.identity, remote.queues, remote.jobs, remote.nodes])
def test_read_connection_retry_once_after_15_seconds(cfg, monkeypatch, operation):
    events = []
    replies = iter([Result(255, '', 'connection closed'), Result(stdout='ok')])
    def execute(*args):
        events.append('execute')
        return next(replies)
    monkeypatch.setattr('ag.transport.time.sleep', lambda seconds: events.append(seconds))
    transport = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(transport, '_execute', execute)
    assert transport.run(operation()).stdout == 'ok'
    assert events == ['execute', 15, 'execute']


@pytest.mark.parametrize('operation', [
    remote.slurm_evidence_config, lambda: remote.slurm_evidence_version('scontrol'),
    lambda: remote.slurm_evidence_version('sacct'),
    lambda: remote.slurm_evidence_version('sbatch'), lambda: remote.slurm_evidence_version('scancel'),
    lambda: remote.slurm_evidence_job('123', 'Synthetic_Cluster'),
    lambda: remote.slurm_evidence_history('123', 'Synthetic_Cluster'),
])
@pytest.mark.parametrize('failure', ['exit_255', 'connection_exception'])
def test_slurm_evidence_records_first_connection_failure_without_retry(cfg, monkeypatch, operation, failure):
    from ag.transport import SSHConnectionError
    calls, failures = [], []
    transport = SSHTransport(cfg, read_only=True)
    command = operation()

    def execute(*args):
        calls.append('execute')
        if failure == 'connection_exception':
            raise SSHConnectionError('Synthetic connection timeout')
        return Result(255, '', 'connection closed')

    monkeypatch.setattr(transport, '_execute', execute)
    monkeypatch.setattr(transport, '_record_failure', failures.append)
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: pytest.fail('formal evidence must not retry'))
    if failure == 'connection_exception':
        with pytest.raises(SSHConnectionError, match='Synthetic connection timeout'):
            transport.run(command)
    else:
        assert transport.run(command).returncode == 255
    assert calls == ['execute'] and len(failures) == 1
    rows = [json.loads(line) for path in (Path(cfg['_config_dir']) / 'ssh-log').glob('*.jsonl')
            for line in path.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]['operation'] == command.operation and rows[0]['attempt'] == 1
    assert rows[0]['outcome'] == ('timeout' if failure == 'connection_exception' else 'exit')


def test_second_connection_failure_stops(cfg, monkeypatch):
    calls = []
    transport = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(transport, '_execute', lambda *a: calls.append('execute') or Result(255))
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: calls.append(s))
    result = transport.run(remote.jobs())
    assert result.returncode == 255
    assert calls == ['execute', 15, 'execute']


@pytest.mark.parametrize('read_only,expected', [(False, ['execute']), (True, ['execute', 15, 'execute'])])
def test_connection_timeout_retry_policy(cfg, monkeypatch, read_only, expected):
    from ag.transport import SSHConnectionError
    calls = []
    def timeout(*args, **kwargs):
        calls.append('execute')
        raise subprocess.TimeoutExpired('ssh', 60)
    monkeypatch.setattr(subprocess, 'run', timeout)
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: calls.append(s))
    with pytest.raises(SSHConnectionError): SSHTransport(cfg, read_only=read_only).run(remote.jobs())
    assert calls == expected


def test_missing_ssh_executable_is_not_a_retryable_connection_error(cfg, monkeypatch):
    calls = []
    def missing(*args, **kwargs):
        calls.append('execute')
        raise FileNotFoundError('ssh')
    monkeypatch.setattr(subprocess, 'run', missing)
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: pytest.fail('must not retry local failures'))
    with pytest.raises(TransportError): SSHTransport(cfg, read_only=True).run(remote.jobs())
    assert calls == ['execute']


@pytest.mark.parametrize('code', [1, 2, 153])
def test_read_command_errors_are_not_retried(cfg, monkeypatch, code):
    calls = []
    t = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(t, '_execute', lambda *a: calls.append('execute') or Result(code))
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: pytest.fail('must not retry command errors'))
    assert t.run(remote.jobs()).returncode == code
    assert calls == ['execute']


@pytest.mark.parametrize('operation', ['identity', 'mkdir', 'qsub', 'qdel', 'scancel', 'bound_sbatch',
                                        'instance_scancel', 'reroute_scancel'])
def test_submit_cancel_transport_never_retries_even_reads(cfg, prepared, monkeypatch, operation):
    _, m = prepared
    command = {'identity': remote.identity(), 'mkdir': remote.create_attempt(cfg, m),
               'qsub': remote.submit(cfg, m), 'qdel': remote.cancel('123.fixture'),
               'scancel': remote.slurm_cancel('123'),
               'bound_sbatch': remote.slurm_submit_bound(dict(cfg, scheduler='slurm'), dict(m, scheduler='slurm'),
                                                        scheduler_cluster='synthetic'),
               'instance_scancel': remote.slurm_cancel_instance(scheduler_cluster='synthetic', uid=1001,
                                                                 job_name=m['attempt_id'], sluid='s0123456789ABC'),
               'reroute_scancel': remote.slurm_cancel_instance(scheduler_cluster='synthetic', uid=1001,
                                                               job_name=m['attempt_id'], sluid='s0123456789ABC',
                                                               purpose='reroute')}[operation]
    calls = []
    t = SSHTransport(cfg)
    monkeypatch.setattr(t, '_execute', lambda *a: calls.append('execute') or Result(255))
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: pytest.fail('write CLI must never retry'))
    assert t.run(command).returncode == 255
    assert calls == ['execute']


def test_upload_never_retries(cfg, prepared, monkeypatch):
    p, m = prepared
    calls = []
    t = SSHTransport(cfg)
    monkeypatch.setattr(t, 'run', lambda *a: Result())
    monkeypatch.setattr(t, '_execute', lambda *a: calls.append('upload') or Result(255))
    monkeypatch.setattr('ag.transport.time.sleep', lambda s: pytest.fail('must not retry upload'))
    with pytest.raises(TransportError): t.upload(p / 'inputs/water.gjf', m, 'water.gjf')
    assert calls == ['upload']


def test_read_only_transport_refuses_writes(cfg, prepared, monkeypatch):
    p, m = prepared
    t = SSHTransport(cfg, read_only=True)
    monkeypatch.setattr(t, '_execute', lambda *a: pytest.fail('must not launch'))
    for command in (remote.submit(cfg, m), remote.cancel('123.fixture'),
                    remote.slurm_cancel('123'), remote.create_attempt(cfg, m),
                    remote.slurm_submit_bound(dict(cfg, scheduler='slurm'), dict(m, scheduler='slurm'),
                                              scheduler_cluster='synthetic'),
                    remote.slurm_cancel_instance(scheduler_cluster='synthetic', uid=1001,
                                                 job_name=m['attempt_id'], sluid='s0123456789ABC'),
                    remote.slurm_cancel_instance(scheduler_cluster='synthetic', uid=1001,
                                                 job_name=m['attempt_id'], sluid='s0123456789ABC', purpose='reroute')):
        with pytest.raises(ValueError): t.run(command)
    with pytest.raises(ValueError): t.upload(p / 'inputs/water.gjf', m, 'water.gjf')


def test_fetch_retry_preserves_failed_partial_and_never_overwrites(cfg, prepared, monkeypatch, tmp_path):
    from test_fetch import fake_scp
    _, m = prepared
    t = SSHTransport(cfg, read_only=True)
    target = tmp_path / 'downloaded.log'
    clock = fake_scp(monkeypatch, [dict(duration=1, writes=[(1, b'partial')], returncode=255),
                                   dict(duration=1, writes=[(1, b'complete')])])
    t.download(m, 'water.log', target)
    calls = [p.target for p in clock.processes]
    assert target.read_bytes() == b'complete'
    assert calls[0] != calls[1] and calls[0].read_bytes() == b'partial'
    assert clock.sleeps == [15]
    with pytest.raises(ValueError): t.download(m, 'water.log', target)
    assert len(clock.processes) == 2


def test_second_failed_download_is_not_published(cfg, prepared, monkeypatch, tmp_path):
    from test_fetch import fake_scp
    _, m = prepared
    t = SSHTransport(cfg, read_only=True)
    clock = fake_scp(monkeypatch, [dict(duration=1, writes=[(1, b'partial')], returncode=255)] * 2)
    target = tmp_path / 'unpublished.log'
    with pytest.raises(TransportError): t.download(m, 'water.log', target)
    calls = [p.target for p in clock.processes]
    assert len(calls) == 2 and not target.exists()
    assert all(p.read_bytes() == b'partial' for p in calls)


def test_mini_prepare_and_memory_limit(cfg, prepared, tmp_path):
    source = tmp_path / 'mini.gjf'
    source.write_text(INPUT.replace('nprocshared=8', 'nprocshared=4').replace('mem=10GB', 'mem=8GB'))
    m = attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                        tier='mini', walltime='00:30:00', label='mini')
    assert (m['tier'], m['cores'], m['mem_gb']) == ('mini', 4, 10)
    script = attempt.verified_files(cfg, attempt.find(cfg, m['attempt_id']), m)['job.pbs'].decode()
    assert 'nodes=1:ppn=4' in script and 'mem=10gb' in script
    source.write_text(source.read_text().replace('mem=8GB', 'mem=10GB'))
    with pytest.raises(ValueError):
        attempt.prepare(cfg, method_basis='兜底方法：合成测试', study_name='smoke', template='gaussian', input_path=source,
                        tier='mini', walltime='00:30:00', label='too-much-memory')
    assert cfg['resources']['tiers']['simple'] == {'cores': 8, 'mem_gb': 12}


@pytest.mark.parametrize('name', ['doctor', 'status', 'fetch', 'submit', 'cancel'])
def test_cli_selects_retry_only_for_read_only_commands(cfg, prepared, monkeypatch, name):
    from types import SimpleNamespace
    p, _ = prepared
    selected = []
    monkeypatch.setattr('ag.transport.SSHTransport', lambda conf, **kwargs: selected.append(kwargs['read_only']))
    monkeypatch.setattr(doctor, 'doctor', lambda *a: {})
    monkeypatch.setattr(status, 'check', lambda *a: {'state': 'prepared'})
    monkeypatch.setattr(fetch, 'fetch', lambda *a, **kw: {})
    monkeypatch.setattr(submit, 'submit', lambda *a, **kw: {})
    monkeypatch.setattr(cancel, 'cancel', lambda *a: {})
    args = SimpleNamespace(config=cfg, command=name, id=p.name, ids=[p.name], study=None, json=True,
                           add_missing=False, approval=None, policy=None)
    assert cli.core_command(args) == 0
    assert selected == [name in ('doctor', 'status', 'fetch')]


def test_list_has_no_ssh_operations(cfg, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('list is local-only'))
    assert cli.core_command(SimpleNamespace(config=cfg, command='list', study=None, json=True)) == 0


def seed_submission(path):
    m = attempt.read_manifest(path)
    submission.record(path, m, '123.fixture')
    return state.write(path, 'submitted', job_id=submission.qualified(m, '123.fixture'))


def test_slurm_evidence_fixed_commands():
    from ag.transport import READ_OPERATIONS
    environment = ['env', '-u', 'SLURM_CLUSTERS']
    locale = ['LC_ALL=C', 'TZ=UTC', 'SLURM_TIME_FORMAT=standard']
    scontrol = environment + ['-u', 'SCONTROL_SIB', '-u', 'SCONTROL_SIBLING'] + locale
    sacct = environment + locale
    commands = [
        (remote.slurm_evidence_config(), 'slurm_evidence_config',
         scontrol + ['scontrol', '--local', 'show', 'config']),
        (remote.slurm_evidence_version('scontrol'), 'slurm_evidence_version',
         scontrol + ['scontrol', '--version']),
        (remote.slurm_evidence_version('sacct'), 'slurm_evidence_version',
         sacct + ['sacct', '--version']),
        (remote.slurm_evidence_job('123', 'Synthetic_Cluster'), 'slurm_evidence_job',
         scontrol + ['scontrol', '--local', '--clusters=Synthetic_Cluster',
                     '--oneliner', '--details', 'show', 'job', '123']),
        (remote.slurm_evidence_history('123', 'Synthetic_Cluster'), 'slurm_evidence_history',
         sacct + ['sacct', '--local', '--clusters=Synthetic_Cluster', '-X', '--duplicates', '-n', '-P',
                  '--jobs=123', '--format=Cluster%256,JobIDRaw%64,JobName%200,UID%20,DBIndex%32,'
                  'Submit%32,Start%32,End%32,State%64,Restarts%20,SLUID%64,OriginalSLUID%64']),
    ]
    for command, operation, expected in commands:
        assert command.operation == operation and operation in READ_OPERATIONS
        assert shlex.split(command.text) == expected
    assert 'cancel' not in READ_OPERATIONS


@pytest.mark.parametrize('job', ['', '0', '01', '1,2', '123.batch', '123_1', '123+1',
                                 '1;true', '1\n', '$(true)', '１２３', None, 123, True])
def test_slurm_evidence_refuses_nonexact_job_ids(job):
    for command in (remote.slurm_evidence_job, remote.slurm_evidence_history):
        with pytest.raises(ValueError):
            command(job, 'synthetic')


@pytest.mark.parametrize('cluster', ['', 'all', 'ALL', 'All', '-1', 'a,b', 'a b', 'a\n',
                                     'a;true', '$(true)', 'a/b', '*', None, 123, True])
def test_slurm_evidence_refuses_multiple_or_unsafe_clusters(cluster):
    for command in (remote.slurm_evidence_job, remote.slurm_evidence_history):
        with pytest.raises(ValueError):
            command('123', cluster)


@pytest.mark.parametrize('program', ['sbatch --wrap=true', 'squeue', 'scontrol --local', 'sacct;true',
                                     '/usr/bin/sacct', 'sacct\n', None, 123, [], {}])
def test_slurm_evidence_version_refuses_other_programs(program):
    with pytest.raises(ValueError):
        remote.slurm_evidence_version(program)


@pytest.mark.parametrize('command,program', [
    (remote.slurm_evidence_config(), 'scontrol'),
    (remote.slurm_evidence_version('scontrol'), 'scontrol'),
    (remote.slurm_evidence_version('sacct'), 'sacct'),
    (remote.slurm_evidence_job('123', 'synthetic'), 'scontrol'),
    (remote.slurm_evidence_history('123', 'synthetic'), 'sacct'),
])
def test_slurm_evidence_environment_is_fixed(tmp_path, command, program):
    # Only this inert local executable runs; there is no Slurm or SSH process.
    executable = tmp_path / program
    executable.write_text('#!/bin/sh\n'
                          'printf "%s\\n" "${SLURM_CLUSTERS-unset}" '
                          '"${SCONTROL_SIB-unset}" "${SCONTROL_SIBLING-unset}" '
                          '"$LC_ALL" "$TZ" "$SLURM_TIME_FORMAT" "$@"\n')
    executable.chmod(0o700)
    environment = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ['PATH'],
                       SLURM_CLUSTERS='other,all', SCONTROL_SIB='1', SCONTROL_SIBLING='1',
                       LC_ALL='C', TZ='Etc/GMT+8', SLURM_TIME_FORMAT='relative', SACCT_FORMAT='JobID')
    result = subprocess.run(shlex.split(command.text), env=environment, capture_output=True,
                            text=True, check=True)
    sibling = 'unset' if program == 'scontrol' else '1'
    lines = result.stdout.splitlines()
    assert lines[:6] == ['unset', sibling, sibling, 'C', 'UTC', 'standard']
    argv = shlex.split(command.text)
    assert lines[6:] == argv[argv.index(program) + 1:]


# Independent approved 26.05.5 option lists, exercised against inert local
# executables below so omission or misspelling leaves visible environment data.
BOUND_SBATCH_UNSET = '''SLURM_CLUSTERS SLURM_HINT SLURM_HOSTFILE SBATCH_IGNORE_PBS SBATCH_DEBUG
SBATCH_ACCOUNT SBATCH_ARRAY_INX SBATCH_ACCTG_FREQ SBATCH_BATCH SBATCH_BURST_BUFFER
SBATCH_CLUSTER_CONSTRAINT SBATCH_CLUSTERS SBATCH_CONSOLIDATE_SEGMENTS SBATCH_CONTAINER
SBATCH_CONTAINER_ID SBATCH_CONTAINER_TYPE SBATCH_CONSTRAINT SBATCH_CORE_SPEC
SBATCH_CPU_FREQ_REQ SBATCH_CPUS_PER_GPU SBATCH_DELAY_BOOT SBATCH_DISTRIBUTION
SBATCH_EXCLUSIVE SBATCH_EXPORT SBATCH_GET_USER_ENV SBATCH_GRES SBATCH_GRES_FLAGS
SBATCH_GPUS SBATCH_GPU_BIND SBATCH_GPU_FREQ SBATCH_GPUS_PER_NODE SBATCH_GPUS_PER_SOCKET
SBATCH_GPUS_PER_TASK SBATCH_HINT SBATCH_JOB_NAME SBATCH_MEM_BIND SBATCH_MEM_PER_CPU
SBATCH_MEM_PER_GPU SBATCH_MEM_PER_NODE SBATCH_NETWORK SBATCH_NO_KILL SBATCH_NO_REQUEUE
SBATCH_OPEN_MODE SBATCH_OVERCOMMIT SBATCH_PARTITION SBATCH_POWER SBATCH_PROFILE
SBATCH_QOS SBATCH_REQ_SWITCH SBATCH_REQUEUE SBATCH_RESERVATION SBATCH_SEGMENT_SIZE
SBATCH_SIGNAL SBATCH_SPREAD_JOB SBATCH_SPREAD_SEGMENTS SBATCH_THREAD_SPEC
SBATCH_THREADS_PER_CORE SBATCH_TIMELIMIT SBATCH_TRES_BIND SBATCH_TRES_PER_TASK
SBATCH_USE_MIN_NODES SBATCH_WAIT SBATCH_WAIT_ALL_NODES SBATCH_WAIT4SWITCH SBATCH_WCKEY
SBATCH_ERROR SBATCH_INPUT SBATCH_OUTPUT'''.split()
INSTANCE_SCANCEL_UNSET = '''SLURM_CLUSTERS SCANCEL_ACCOUNT SCANCEL_BATCH SCANCEL_CTLD
SCANCEL_CRON SCANCEL_FULL SCANCEL_HURRY SCANCEL_INTERACTIVE SCANCEL_NAME SCANCEL_PARTITION
SCANCEL_QOS SCANCEL_STATE SCANCEL_USER SCANCEL_VERBOSE SCANCEL_WCKEY'''.split()


def test_bound_slurm_commands_are_exact_and_old_commands_are_unchanged(cfg, prepared):
    _, manifest = prepared
    cfg, manifest = dict(cfg, scheduler='slurm'), dict(manifest, scheduler='slurm')
    directory = remote.attempt_dir(cfg, manifest)
    old = remote.slurm_submit(cfg, manifest)
    assert old.text == remote.path_checks(directory + '/job.slurm') + ' && cd ' + shlex.quote(directory) + ' && sbatch --parsable job.slurm'
    assert remote.slurm_cancel('123').text == 'scancel 123'
    submit_command = remote.slurm_submit_bound(cfg, manifest, scheduler_cluster='Actual_Cluster')
    cancel_command = remote.slurm_cancel_instance(scheduler_cluster='Actual_Cluster', uid=1001,
                                                 job_name=manifest['attempt_id'], sluid='s0123456789ABC')
    assert submit_command.text.startswith(remote.path_checks(directory + '/job.slurm') + ' && cd ' + shlex.quote(directory) + ' && ')
    expected_submit = ['env'] + [part for name in BOUND_SBATCH_UNSET for part in ('-u', name)]
    expected_cancel = ['env'] + [part for name in INSTANCE_SCANCEL_UNSET for part in ('-u', name)]
    assert shlex.split(submit_command.text.split(' && ')[-1]) == expected_submit + [
        'LC_ALL=C', 'TZ=UTC', 'sbatch', '--parsable', '--clusters=Actual_Cluster', '--no-requeue', 'job.slurm']
    assert shlex.split(cancel_command.text) == expected_cancel + [
        'LC_ALL=C', 'TZ=UTC', 'scancel', '--ctld', '--clusters=Actual_Cluster', '--user=1001',
        '--name=' + manifest['attempt_id'], 's0123456789ABC']
    assert (submit_command.operation, submit_command.timeout) == ('submit', 120)
    assert (cancel_command.operation, cancel_command.timeout) == ('cancel', 60)
    for program, prefix in [('sbatch', expected_submit), ('scancel', expected_cancel)]:
        version = remote.slurm_evidence_version(program)
        assert version.operation == 'slurm_evidence_version'
        assert shlex.split(version.text) == prefix + ['LC_ALL=C', 'TZ=UTC', program, '--version']


@pytest.mark.parametrize('program,version,purpose', [('sbatch', False, 'no_progress'), ('scancel', False, 'no_progress'),
                                                    ('sbatch', True, 'no_progress'), ('scancel', True, 'no_progress'),
                                                    ('scancel', False, 'reroute')])
def test_bound_slurm_commands_clear_only_fixed_overrides_in_local_fake(cfg, prepared, tmp_path, program, version, purpose):
    _, manifest = prepared
    cfg, manifest = dict(cfg, scheduler='slurm'), dict(manifest, scheduler='slurm')
    root = tmp_path.resolve() / 'remote-directory'
    cfg['remote'] = dict(allowed_root=str(root), ag_root=str(root / 'ag'))
    directory = Path(remote.attempt_dir(cfg, manifest))
    directory.mkdir(parents=True)
    script = directory / 'job.slurm'
    script.write_bytes(b'# synthetic frozen script; not executed\n')
    names = BOUND_SBATCH_UNSET if program == 'sbatch' else INSTANCE_SCANCEL_UNSET
    executable = tmp_path / program
    # -S avoids loading the borrowed environment's unrelated .pth files under
    # LC_ALL=C; this inert fixture only needs the standard library.
    executable.write_text('#!' + sys.executable + ' -S\nimport json, os, sys\n'
                          'print(json.dumps(dict(argv=sys.argv[1:], cwd=os.getcwd(), '
                          'values={k:os.environ.get(k) for k in ' + repr(names + ['LC_ALL', 'TZ', 'SLURM_CONF', 'AG_TEST_KEEP']) + '})))\n')
    executable.chmod(0o700)
    environment = {name: 'synthetic-override' for name in names}
    environment.update(PATH=str(tmp_path) + os.pathsep + os.defpath, LC_ALL='C', TZ='Etc/GMT+8',
                       SLURM_CONF='site-config-fixture', AG_TEST_KEEP='preserved')
    if version:
        command = remote.slurm_evidence_version(program)
        expected = ['--version']
    elif program == 'sbatch':
        command = remote.slurm_submit_bound(cfg, manifest, scheduler_cluster='actual')
        expected = ['--parsable', '--clusters=actual', '--no-requeue', 'job.slurm']
    else:
        command = remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001,
                                              job_name=manifest['attempt_id'], sluid='s0123456789ABC', purpose=purpose)
        expected = ['--ctld', '--clusters=actual', '--user=1001', '--name=' + manifest['attempt_id']]
        expected += ['--state=PENDING'] if purpose == 'reroute' else []
        expected += ['s0123456789ABC']
    run = subprocess.run(['sh', '-c', command.text], env=environment, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    observed = json.loads(run.stdout)
    assert observed['argv'] == expected
    assert all(observed['values'][name] is None for name in names)
    assert {key: observed['values'][key] for key in ('LC_ALL', 'TZ', 'SLURM_CONF', 'AG_TEST_KEEP')} == dict(
        LC_ALL='C', TZ='UTC', SLURM_CONF='site-config-fixture', AG_TEST_KEEP='preserved')
    if program == 'sbatch' and not version:
        assert observed['cwd'] == str(directory)
    assert script.read_bytes() == b'# synthetic frozen script; not executed\n'


@pytest.mark.parametrize('cluster', ['', 'all', 'ALL', 'All', '-1', 'a,b', 'a b', 'a\n',
                                     'a;true', '$(true)', 'a/b', '*', None, 123, True])
def test_bound_slurm_writes_refuse_nonexact_cluster(cfg, prepared, cluster):
    _, manifest = prepared
    with pytest.raises(ValueError):
        remote.slurm_submit_bound(dict(cfg, scheduler='slurm'), dict(manifest, scheduler='slurm'),
                                  scheduler_cluster=cluster)
    with pytest.raises(ValueError):
        remote.slurm_cancel_instance(scheduler_cluster=cluster, uid=1001,
                                     job_name=manifest['attempt_id'], sluid='s0123456789ABC')


@pytest.mark.parametrize('uid', [True, False, -1, 2 ** 32, 1.0, '1001', None])
def test_slurm_instance_cancel_rejects_invalid_uid(uid):
    with pytest.raises(ValueError):
        remote.slurm_cancel_instance(scheduler_cluster='actual', uid=uid, job_name='water-001-sp', sluid='s0123456789ABC')


@pytest.mark.parametrize('name', ['', 'a b', 'a;b', 'a\n', 'a/b', '-a', 'ALL', 'a' * 81, None, 123, True])
def test_slurm_instance_cancel_rejects_non_attempt_name(name):
    with pytest.raises(ValueError):
        remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001, job_name=name, sluid='s0123456789ABC')


@pytest.mark.parametrize('sluid', ['', '123', 123, None, True, 's0000000000000', 'sG123456789ABC',
                                  's0123456789abc', 's0123456789ABI', 's0123456789ABC.0',
                                  's0123456789ABC_1', 's0123456789ABC+1', 's0123456789ABC,s0123456789ABD',
                                  's0123456789ABC 123', 's0123456789ABC\n', 's0123456789ABC;true'])
def test_slurm_instance_cancel_rejects_noncanonical_or_multiple_targets(sluid):
    with pytest.raises(ValueError):
        remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001, job_name='water-001-sp', sluid=sluid)


def test_slurm_instance_cancel_purpose_only_adds_fixed_pending_filter():
    fields = dict(scheduler_cluster='actual', uid=1001, job_name='water-001-sp', sluid='s0123456789ABC')
    default = remote.slurm_cancel_instance(**fields)
    assert remote.slurm_cancel_instance(**fields, purpose='no_progress') == default
    reroute = remote.slurm_cancel_instance(**fields, purpose='reroute')
    assert reroute.text == default.text.removesuffix(' s0123456789ABC') + ' --state=PENDING s0123456789ABC'
    assert (reroute.operation, reroute.timeout) == (default.operation, default.timeout)


@pytest.mark.parametrize('purpose', ['', 'PENDING', 'RUNNING', 'reroute --state=RUNNING', 'reroute;true',
                                    'no_progress\n', 'all', None, True, 1, [], {}])
def test_slurm_instance_cancel_refuses_arbitrary_purpose_or_state(purpose):
    with pytest.raises(ValueError):
        remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001, job_name='water-001-sp',
                                     sluid='s0123456789ABC', purpose=purpose)


def test_bound_slurm_submit_keeps_path_and_scheduler_checks(cfg, prepared):
    _, manifest = prepared
    with pytest.raises(ValueError):
        remote.slurm_submit_bound(cfg, manifest, scheduler_cluster='actual')
    cfg, manifest = dict(cfg, scheduler='slurm'), dict(manifest, scheduler='slurm')
    with pytest.raises(ValueError):
        remote.slurm_submit_bound(cfg, dict(manifest, remote_dir='../escape'), scheduler_cluster='actual')
    with pytest.raises(ValueError):
        remote.slurm_submit_bound(cfg, dict(manifest, attempt_id='a;true'), scheduler_cluster='actual')


def test_bound_slurm_submit_rejects_symlink_before_invoking_local_fake(cfg, prepared, tmp_path):
    _, manifest = prepared
    cfg, manifest = dict(cfg, scheduler='slurm'), dict(manifest, scheduler='slurm')
    root = tmp_path.resolve() / 'remote-directory'
    cfg['remote'] = dict(allowed_root=str(root), ag_root=str(root / 'ag'))
    directory = Path(remote.attempt_dir(cfg, manifest))
    directory.mkdir(parents=True)
    target = tmp_path / 'unrelated-script'
    target.write_text('unchanged')
    (directory / 'job.slurm').symlink_to(target)
    executable = tmp_path / 'sbatch'
    executable.write_text('#!/bin/sh\nprintf "must-not-run\\n"\n')
    executable.chmod(0o700)
    command = remote.slurm_submit_bound(cfg, manifest, scheduler_cluster='actual')
    result = subprocess.run(['sh', '-c', command.text], capture_output=True, text=True,
                            env=dict(PATH=str(tmp_path) + os.pathsep + os.defpath))
    assert result.returncode != 0 and result.stdout == '' and target.read_text() == 'unchanged'


@pytest.fixture
def autonomous_cancel_case(cfg, tmp_path, monkeypatch):
    """Exercise the executor against explicit upstream contracts, never SSH.

    Upstream reservation and observation implementations have separate tests;
    this fixture exposes boundary changes and asserts every lock/IO ordering.
    """
    from contextlib import contextmanager
    from contextvars import ContextVar
    from copy import deepcopy
    from types import SimpleNamespace
    import ag
    from ag import autonomy, autonomy_cancel
    cfg = deepcopy(cfg)
    cfg.update(scheduler='slurm', partition='fixture')
    study.init(cfg, 'water')
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    manifest = attempt.prepare(cfg, study_name='water', template='gaussian', input_path=source,
        tier='simple', walltime='00:30:00', label='sp', method_basis='Synthetic fixture')
    path = attempt.find(cfg, manifest['attempt_id'])
    owner_hash, rule_hash, plan_hash = 'a' * 64, 'b' * 64, 'c' * 64
    record = dict(round_id='round', run_id='older-wake', study_id='water', attempt_id=path.name,
                  plan_sha256=plan_hash, rule_sha256=rule_hash, policy_name='bounded',
                  manifest_sha256=sha256((path / 'manifest.json').read_bytes()).hexdigest())
    authorization = dict(method='autonomy-policy', ownership_sha256=owner_hash, **record)
    def unit_authorization(candidate, value, *, verified_state=None):
        # This fixture isolates executor boundaries with an explicit ownership
        # double. Actual authorization/consumption is covered by the real API
        # integration fixture, including in a combined T186 checkout.
        assert candidate == path and value == authorization
        return deepcopy(authorization)
    integrated = sys.modules.get('ag.autonomy_submission')
    if integrated is not None and hasattr(integrated, 'verified_authorization'):
        monkeypatch.setattr(integrated, 'verified_authorization', unit_authorization)
    submission.record(path, manifest, '123', scheduler_cluster='actual', authorization=authorization)
    state.write(path, 'submitting')
    state.write(path, 'submitted', job_id='default:123')
    state.write(path, 'running')
    dispatch = dict(ownership_sha256=owner_hash, round_id='round', run_id='older-wake',
                    plan_sha256=plan_hash, dispatch_started={'at': 10.0})
    runtime = dict(current_round='round', updated_at=90.0, submissions={path.name: deepcopy(dispatch)})
    case = SimpleNamespace(cfg=cfg, path=path, manifest=manifest, record=record, authorization=authorization,
        runtime=runtime, owner_hash=owner_hash, rule_hash=rule_hash, locks=[], calls=[], records=[],
        consumed=[], captured=[], cfg_current=deepcopy(cfg), now=100.0, publication_refused=False,
        claim_failure=False, result=Result(), after_capture=lambda: None, during_command=lambda: None,
        on_consume=lambda: None, review_error=None, instance_error=None, reservation_error=None,
        state_label='RUNNING', ledger_error=None, lock_exit=None, lock_exit_early=False,
        capture_error=None, proof_error=None, proof_calls=[], pauses=[], paused=False,
        after_proof=lambda: None, run_until=200.0, receipt_hook=lambda: None)
    case.context = dict(run_id='current-wake', token='test-token', plan_sha256=plan_hash,
                        policy_name='bounded', kind='no_progress', reason='Reviewed scientific stall',
                        reviews=[dict(snapshot='first'), dict(snapshot='second')])
    case.observation = dict(observation='scheduler-observations/fresh', observation_sha256='d' * 64)

    @contextmanager
    def locked(name):
        expected = {'config': [], 'machine': ['config'], 'guard': ['config', 'machine']}
        assert case.locks == expected[name], 'No nested or out-of-order local locks'
        case.locks.append(name)
        try:
            yield
        finally:
            assert case.locks.pop() == name
            if case.lock_exit == name and (case.consumed or case.lock_exit_early):
                raise OSError('Synthetic mutex changed before unlock')

    class Guard:
        @property
        def snapshot(self):
            return deepcopy(case.runtime)

        @property
        def current(self):
            return dict(state=self.snapshot, seq=9, journal_sha256='e' * 64)

        def recheck(self):
            assert case.locks == ['config', 'machine', 'guard']
            if case.consumed:
                raise ValueError('No recheck or new action after pending cancellation consumption')

        def consume(self, **fields):
            self.recheck()
            case.on_consume()
            case.consumed.append(fields)
            from ag import _autonomy_store as disk
            consumed = dict(fields, run_id=case.context['run_id'], round_id='round',
                plan_sha256=plan_hash, token_sha256=sha256(case.context['token'].encode()).hexdigest(),
                versions={}, at=case.now, seq=10, lineage_sha256=None)
            consumed['consumption_sha256'] = sha256(disk.encode(consumed)).hexdigest()
            case.runtime.setdefault('cancellations', {})[path.name] = deepcopy(consumed)
            return dict(record=consumed)

    @contextmanager
    def guard(*args, **kwargs):
        with locked('guard'):
            current = Guard()
            current.recheck()
            yield current

    @contextmanager
    def machine(*, create=True):
        assert create is False
        with locked('machine'):
            yield

    @contextmanager
    def publication(*args, **kwargs):
        assert kwargs['action'] == 'observe' and case.locks == ['config']
        if case.publication_refused:
            raise ValueError('Original lease is no longer the current owner')
        with locked('machine'), locked('guard'):
            yield deepcopy(case.runtime)

    def reservation(path, *, verified_state):
        assert case.locks == ['config', 'machine', 'guard']
        assert verified_state == case.runtime
        if case.reservation_error:
            raise ValueError(case.reservation_error)
        return dict(record=deepcopy(case.record), sha256=case.owner_hash)

    def review(path, *, current, **kwargs):
        assert not case.locks and current['seq'] == 9
        if case.review_error:
            raise ValueError(case.review_error)
        return dict(binding=autonomy_cancel.bound_attempt(path), evidence=deepcopy(kwargs['reviews']))

    def instance(path, *, ownership_sha256, observation):
        assert not case.locks and observation == case.observation
        assert ownership_sha256 == owner_hash
        if case.instance_error:
            raise ValueError(case.instance_error)
        return dict(binding=autonomy_cancel.bound_attempt(path), origin_dispatch=deepcopy(dispatch),
                    current_instance=dict(cluster='actual', uid=1001, name=path.name,
                                          sluid='s0123456789ABC', state=case.state_label))

    def capture(cfg, path, transport, *, publication, include_cancel_version):
        assert not case.locks and include_cancel_version is True
        case.captured.append(True)
        with publication():
            pass
        if case.capture_error:
            raise ValueError(case.capture_error)
        case.after_capture()
        return deepcopy(case.observation)

    def record_result(*args, **fields):
        assert not case.locks
        case.records.append(fields)
        if case.ledger_error:
            raise ValueError(case.ledger_error)
        case.runtime.setdefault('cancellation_results', {})[path.name] = dict(fields, run_id=case.context['run_id'])
        return dict(record=fields)

    def pause(*args):
        assert not case.locks, 'Pause must not reenter a held observation lock'
        case.pauses.append(args)
        if not case.publication_refused:
            case.paused = True

    def stopped(path, *, ownership_sha256, observation, cancel_response):
        assert not case.locks, 'Full stopping proof parsing and hashing must stay outside locks'
        assert observation == case.observation and ownership_sha256 == case.owner_hash
        case.proof_calls.append(cancel_response)
        if case.proof_error:
            raise ValueError(case.proof_error)
        case.after_proof()
        return dict(stopped=True, binding=autonomy_cancel.bound_attempt(path),
                    ownership_sha256=ownership_sha256, **cancel_response,
                    reroute_authorized=False, live_validated=False)

    class CancelTransport:
        cfg = case.cfg

        def record_to(self, paths):
            assert paths == []

        def run(self, command):
            assert not case.locks, 'Cancellation must never hold a local mutex over IO'
            assert (path / '.cancel-claim').exists() and len(case.consumed) == 1
            case.calls.append(command)
            case.during_command()
            if isinstance(case.result, BaseException):
                raise case.result
            return case.result

    isolated_home = tmp_path / 'isolated-home'
    for name in ('autonomy-reservations', 'autonomy-studies'):
        (isolated_home / '.config/ag' / name).mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: isolated_home))
    active_reads = ContextVar('test_cancel_reads', default=None)

    class ReadReceipt:
        def __init__(self):
            self.identities, self.directories, self.files = {}, {}, {}

        def directory(self, directory):
            directory = Path(directory)
            value = directory.stat()
            fingerprint = (value.st_dev, value.st_ino, value.st_mtime_ns, value.st_ctime_ns)
            if self.directories.setdefault(directory, fingerprint) != fingerprint:
                raise ValueError('Directory changed during evidence reading')

        def verify(self):
            for directory, expected in self.identities.items():
                value = directory.stat()
                if (value.st_dev, value.st_ino) != expected:
                    raise ValueError('Registry identity changed')
            for directory in self.directories:
                self.directory(directory)
            for target, expected in self.files.items():
                value = target.stat()
                if (value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns) != expected:
                    raise ValueError('File changed after evidence parsing')
            case.receipt_hook()

    @contextmanager
    def capture_reads():
        assert not case.locks
        receipt = ReadReceipt()
        token = active_reads.set(receipt)
        try:
            yield receipt
            receipt.verify()
        finally:
            active_reads.reset(token)

    def read_file(target):
        assert not case.locks, 'Full file reads must stay outside publication locks'
        raw = target.read_bytes()
        value = target.stat()
        active_reads.get().files[target] = (value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        return raw

    def scientific_reservation(path):
        assert not case.locks
        if case.reservation_error:
            raise ValueError(case.reservation_error)
        return deepcopy(case.record), case.owner_hash

    def owned_audit(path, record, digest):
        assert not case.locks and record == case.record and digest == case.owner_hash
        for item in (path / 'inputs').iterdir():
            read_file(item)

    def check_consumption(record, digest, current):
        assert case.locks == ['config', 'machine', 'guard']
        assert record == case.record and digest == case.owner_hash
        if current['submissions'][path.name]['ownership_sha256'] != digest:
            raise ValueError('Original submission consumption changed')

    def eligible(current, *args):
        assert case.locks == ['config', 'machine', 'guard']
        if case.now >= case.run_until:
            raise ValueError('Wake expired during stopping proof parsing')

    ownership = SimpleNamespace(machine_lock=machine, verified_reservation=reservation,
        verified_authorization=unit_authorization,
        authorization=lambda *args: deepcopy(case.authorization), _capture_reads=capture_reads,
        _CAPTURE_READS=active_reads, _read_file=read_file, _scientific_reservation=scientific_reservation,
        _owned_audit=owned_audit, _check_consumption=check_consumption)
    monkeypatch.setitem(sys.modules, 'ag.autonomy_submission', ownership)
    monkeypatch.setattr(ag, 'autonomy_submission', ownership, raising=False)
    monkeypatch.setattr(submit, 'autonomous_configuration', lambda cfg: deepcopy(case.cfg_current), raising=False)
    monkeypatch.setattr(submit, 'bound_policy', lambda *args: ({}, case.rule_hash), raising=False)
    monkeypatch.setattr(cancel, 'submission_lock', lambda cfg: locked('config'))
    monkeypatch.setattr(autonomy, '_cancellation_guard', guard)
    monkeypatch.setattr(autonomy, 'observation_publication_guard', publication, raising=False)
    monkeypatch.setattr(autonomy, '_record_cancellation_result', record_result)
    monkeypatch.setattr(autonomy, 'pause_if_current_owner', pause, raising=False)
    monkeypatch.setattr(autonomy, 'now', lambda: case.now)
    monkeypatch.setattr(autonomy, 'eligible', eligible)
    monkeypatch.setattr(autonomy, 'versions', lambda: {})
    monkeypatch.setattr(autonomy_cancel, '_review_no_progress_locked', review)
    monkeypatch.setattr(autonomy_cancel, 'verify_slurm_instance', instance)
    monkeypatch.setattr(autonomy_cancel, 'verify_slurm_stopped', stopped)
    monkeypatch.setattr(status, 'capture_slurm_evidence', capture)
    monkeypatch.setattr(confirm, 'confirm', lambda *a: pytest.fail('Autonomous cancellation never falls back to confirmation'))
    case.transport = CancelTransport()
    return case


def run_autonomous_cancel(case, **changes):
    return cancel.autonomous_cancel(case.cfg, case.path, case.transport, **dict(case.context, **changes))


def test_autonomous_cancel_publishes_when_local_status_lags_controller(autonomous_cancel_case):
    case = autonomous_cancel_case
    current = json.loads((case.path / 'status.json').read_text())
    current['state'] = 'submitted'
    (case.path / 'status.json').write_text(json.dumps(current))
    answer = run_autonomous_cancel(case)
    assert case.state_label == 'RUNNING'
    assert answer['outcome'] == 'accepted' and answer['status_published'] is True
    assert state.read(case.path)['state'] == 'cancelled'
    assert len(case.calls) == 1


def test_autonomous_cancel_exact_instance_once_and_canonical_evidence(autonomous_cancel_case):
    from ag import _autonomy_store as disk
    case = autonomous_cancel_case
    result = run_autonomous_cancel(case)
    assert result['outcome'] == 'accepted' and result['stopped'] is False and result['status_published'] is True
    assert state.read(case.path)['state'] == 'cancelled'
    assert len(case.calls) == len(case.consumed) == len(case.records) == 1
    assert case.calls[0] == remote.slurm_cancel_instance(scheduler_cluster='actual', uid=1001,
                           job_name=case.path.name, sluid='s0123456789ABC')
    for key in ('request', 'response'):
        raw = (case.path / result[key]).read_bytes()
        assert raw == disk.encode(disk.decode(raw))
        assert sha256(raw).hexdigest() == result[key + '_sha256']
    request = disk.decode((case.path / result['request']).read_bytes())
    response = disk.decode((case.path / result['response']).read_bytes())
    assert request['run_id'] == 'current-wake'
    assert request['slurm_instance']['origin_dispatch']['run_id'] == 'older-wake'
    assert request['command'] == case.calls[0].text and request['target']['scheduler_cluster'] == 'actual'
    assert response['dispatched'] is True and response['returncode'] == 0
    assert response['request_sha256'] == result['request_sha256']
    assert response['consumption_sha256'] == result['consumption_sha256']
    assert case.consumed[0]['evidence_sha256'] == result['request_sha256']
    assert case.records[0]['evidence_sha256'] == result['response_sha256']
    with pytest.raises(ValueError):
        run_autonomous_cancel(case)
    assert len(case.calls) == len(case.captured) == 1


@pytest.mark.parametrize('response', [Result(255, '', 'synthetic disconnect'), Result(0, '', 'unexpected diagnostic'),
                                      TransportError('synthetic interruption'), KeyboardInterrupt()])
def test_autonomous_cancel_uncertain_response_retains_claim_and_pauses_once(autonomous_cancel_case, response):
    case = autonomous_cancel_case
    case.result = response
    with pytest.raises(cancel.AutonomousCancellationUnknown) as caught:
        run_autonomous_cancel(case)
    assert caught.value.evidence['outcome'] == 'unknown'
    assert (case.path / '.cancel-claim').exists() and len(case.calls) == 1
    assert state.read(case.path)['state'] == 'running'
    assert case.records[0]['outcome'] == 'unknown'
    with pytest.raises(ValueError):
        run_autonomous_cancel(case)
    assert len(case.calls) == 1


def test_autonomous_cancel_late_acceptance_keeps_response_without_status_publication(autonomous_cancel_case):
    case = autonomous_cancel_case
    case.during_command = lambda: setattr(case, 'publication_refused', True)
    result = run_autonomous_cancel(case)
    assert result['outcome'] == 'accepted' and result['status_published'] is False
    assert (case.path / result['response']).exists()
    assert case.records[0]['outcome'] == 'accepted'
    assert state.read(case.path)['state'] == 'running'


@pytest.mark.parametrize('change', ['configuration', 'rule', 'round', 'plan', 'dispatch', 'authorization',
                                  'review', 'instance', 'claim', 'directory', 'state'])
def test_autonomous_cancel_rechecks_all_sources_after_query_before_consumption(autonomous_cancel_case, change):
    case = autonomous_cancel_case
    def mutate():
        if change == 'configuration':
            case.cfg_current['ssh']['host'] = 'changed-fixture'
        elif change == 'rule':
            case.rule_hash = '0' * 64
        elif change == 'round':
            case.runtime['current_round'] = 'next-round'
        elif change == 'plan':
            case.record['plan_sha256'] = '0' * 64
        elif change == 'dispatch':
            case.runtime['submissions'][case.path.name]['dispatch_started'] = {'at': 11.0}
        elif change == 'authorization':
            value = json.loads((case.path / 'submission.json').read_text())
            value['authorization']['method'] = 'policy'
            (case.path / 'submission.json').write_text(json.dumps(value))
        elif change == 'review':
            case.review_error = 'snapshot mutated'
        elif change == 'instance':
            case.instance_error = 'SLUID was replaced'
        elif change == 'claim':
            claim(case.path / '.cancel-claim')
        elif change == 'directory':
            case.path.rename(case.path.with_name('replaced'))
            case.path.mkdir()
        elif change == 'state':
            case.state_label = 'COMPLETING'
    case.after_capture = mutate
    with pytest.raises((ValueError, OSError)):
        run_autonomous_cancel(case)
    assert case.calls == case.consumed == case.records == []


@pytest.mark.parametrize('state_label', ['PENDING', 'COMPLETING', 'CANCELLED', 'FAILED', 'UNKNOWN'])
def test_autonomous_cancel_rejects_nonrunning_current_instance(autonomous_cancel_case, state_label):
    case = autonomous_cancel_case
    case.state_label = state_label
    with pytest.raises(ValueError, match='currently running'):
        run_autonomous_cancel(case)
    assert case.calls == case.consumed == []


def test_autonomous_cancel_suspended_still_requires_both_explicit_reviews(autonomous_cancel_case):
    case = autonomous_cancel_case
    case.state_label = 'SUSPENDED'
    case.review_error = 'Missing second explicit scientific review'
    with pytest.raises(ValueError, match='second explicit'):
        run_autonomous_cancel(case)
    assert case.calls == case.captured == case.consumed == []


@pytest.mark.parametrize('stage', ['consume', 'claim', 'response', 'ledger'])
def test_autonomous_cancel_local_failures_never_reissue(autonomous_cancel_case, monkeypatch, stage):
    from ag import _autonomy_store as disk
    case = autonomous_cancel_case
    if stage == 'consume':
        def refuse():
            raise ValueError('Lease expired during final evidence reads')
        case.on_consume = refuse
    elif stage == 'ledger':
        case.ledger_error = 'Durable ledger unavailable'
    else:
        original = disk.Store.exclusive
        def refuse(store, name, data):
            if name == ('.cancel-claim' if stage == 'claim' else 'autonomy-cancel-response.json'):
                raise OSError('Synthetic local publication interruption')
            return original(store, name, data)
        monkeypatch.setattr(disk.Store, 'exclusive', refuse)
    with pytest.raises(ValueError) as caught:
        run_autonomous_cancel(case)
    assert len(case.calls) == int(stage in ('response', 'ledger'))
    assert len(case.consumed) == int(stage != 'consume')
    if stage != 'consume':
        assert isinstance(caught.value, cancel.AutonomousCancellationUnknown)
        assert case.records[0]['outcome'] == ('accepted' if stage == 'ledger' else 'unknown')
        if stage == 'claim':
            assert caught.value.evidence['response_record']['dispatched'] is False
    with pytest.raises(ValueError):
        run_autonomous_cancel(case)
    assert len(case.calls) == int(stage in ('response', 'ledger'))


def test_autonomous_cancel_reroute_missing_t185_never_queries_or_consumes(autonomous_cancel_case, monkeypatch):
    from ag import route
    monkeypatch.delattr(route, 'autonomous_selection', raising=False)
    case = autonomous_cancel_case
    with pytest.raises(ValueError, match='T185'):
        run_autonomous_cancel(case, kind='reroute', reviews=None)
    assert case.calls == case.captured == case.consumed == []


@pytest.mark.parametrize('lock', ['config', 'machine', 'guard'])
def test_autonomous_cancel_lock_exit_after_consume_records_unknown_without_dispatch(autonomous_cancel_case, lock):
    case = autonomous_cancel_case
    case.lock_exit = lock
    with pytest.raises(cancel.AutonomousCancellationUnknown) as caught:
        run_autonomous_cancel(case)
    assert case.calls == [] and len(case.consumed) == len(case.records) == 1
    assert case.records[0]['outcome'] == 'unknown'
    assert caught.value.evidence['response_record']['dispatched'] is False
    assert (case.path / '.cancel-claim').exists()


def test_autonomous_cancel_lock_exit_before_consume_does_not_invent_consumption(autonomous_cancel_case):
    case = autonomous_cancel_case
    case.lock_exit, case.lock_exit_early = 'machine', True
    with pytest.raises(OSError, match='mutex changed'):
        run_autonomous_cancel(case)
    assert case.calls == case.consumed == case.records == case.captured == []
    assert not (case.path / '.cancel-claim').exists()


def test_autonomous_cancel_missing_t186_is_explicit_before_transport(cfg, prepared, monkeypatch):
    import ag
    monkeypatch.delattr(ag, 'autonomy_submission', raising=False)
    monkeypatch.setitem(sys.modules, 'ag.autonomy_submission', None)
    with pytest.raises(ValueError, match='T186'):
        cancel.autonomous_cancel(cfg, prepared[0], Fake(cfg), run_id='wake', token='token',
            plan_sha256='a' * 64, policy_name='bounded', kind='no_progress', reason='stalled', reviews=[{}, {}])


def test_manual_cancel_rejects_initialized_autonomy_without_upstream_guard(cfg, prepared, monkeypatch):
    from ag import autonomy
    path, _ = prepared
    (path.parent.parent / 'autonomy').mkdir()
    monkeypatch.delattr(autonomy, 'manual_write_guard', raising=False)
    fake = Fake(cfg)
    with pytest.raises(ValueError, match='manual write guard'):
        cancel.cancel(cfg, path, fake)
    assert fake.calls == [] and not (path / '.cancel-claim').exists()


def test_manual_cancel_uses_upstream_guard_and_still_requires_confirmation(cfg, prepared, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import ag
    from ag import autonomy
    path, _ = prepared
    state.write(path, 'submitting')
    seed_submission(path)
    calls = []
    @contextmanager
    def guard(value, name, **kwargs):
        calls.append((name, kwargs))
        yield
    monkeypatch.setattr(autonomy, 'manual_write_guard', guard, raising=False)
    monkeypatch.setattr(ag, 'autonomy_submission', SimpleNamespace(), raising=False)
    monkeypatch.setattr(confirm, 'confirm', lambda *args: False)
    fake = Fake(cfg)
    with pytest.raises(submit.UserCancelled):
        cancel.cancel(cfg, path, fake)
    assert calls == [('smoke', dict(action='cancel', attempt_ids=[path.name]))] and fake.calls == []


@pytest.mark.parametrize('missing', ['run', 'token', 'plan_sha256', 'autonomous_policy', 'kind', 'reason', 'reviews'])
def test_cli_autonomous_cancel_missing_context_creates_no_transport(cfg, prepared, monkeypatch, missing):
    from types import SimpleNamespace
    args = dict(config=cfg, command='cancel', id=prepared[0].name, json=True, run='wake', token='token',
                plan_sha256='a' * 64, autonomous_policy='bounded', kind='no_progress', reason='stalled', reviews='unused')
    args[missing] = None
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('Incomplete context must precede transport'))
    with pytest.raises(ValueError):
        cli.core_command(SimpleNamespace(**args))


def test_cli_autonomous_cancel_failure_does_not_fall_back_to_manual(cfg, prepared, monkeypatch, tmp_path):
    from types import SimpleNamespace
    reviews = tmp_path / 'reviews.json'
    reviews.write_text('[{}, {}]')
    called = []
    def refuse(*args, **kwargs):
        called.append(kwargs)
        raise ValueError('Invalid instance evidence')
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: Fake(cfg))
    monkeypatch.setattr(cancel, 'autonomous_cancel', refuse)
    monkeypatch.setattr(cancel, 'cancel', lambda *a: pytest.fail('No manual fallback'))
    with pytest.raises(ValueError, match='instance'):
        cli.core_command(SimpleNamespace(config=cfg, command='cancel', id=prepared[0].name, json=True,
            run='wake', token='token', plan_sha256='a' * 64, autonomous_policy='bounded', kind='no_progress',
            reason='stalled', reviews=str(reviews)))
    assert called[0]['reviews'] == [{}, {}] and called[0]['policy_name'] == 'bounded'


def test_cli_cancel_rejects_old_submission_policy_flag(monkeypatch):
    monkeypatch.setattr(cli, 'load_config', lambda: pytest.fail('Unsupported flag must not load config'))
    with pytest.raises(SystemExit) as error:
        cli.main(['cancel', 'water-001-sp', '--policy', 'ordinary'])
    assert error.value.code == 2


def run_verify_stopped(case):
    return cancel.verify_stopped(case.cfg, case.path, case.transport,
        **{key: case.context[key] for key in ('run_id', 'token', 'plan_sha256')})


def test_verify_stopped_binds_actual_ledger_and_writes_once_without_recancelling(autonomous_cancel_case):
    from ag import _autonomy_store as disk
    case = autonomous_cancel_case
    accepted = run_autonomous_cancel(case)
    before = (case.path / 'status.json').read_bytes()
    result = run_verify_stopped(case)
    assert result['stopped'] is True and result['reroute_authorized'] is False
    raw = (case.path / 'autonomy-cancel-stopped.json').read_bytes()
    assert raw == disk.encode(disk.decode(raw)) and sha256(raw).hexdigest() == result['evidence_sha256']
    assert result['response_sha256'] == accepted['response_sha256']
    assert len(case.calls) == len(case.consumed) == 1 and len(case.captured) == 2
    assert len(case.proof_calls) == 1 and not case.paused
    assert (case.path / 'status.json').read_bytes() == before
    with pytest.raises(ValueError, match='already published'):
        run_verify_stopped(case)
    assert len(case.captured) == 2 and not case.paused


@pytest.mark.parametrize('stage', ['missing-response', 'corrupt-response', 'ledger-unknown', 'wrong-consumption',
                                  'wrong-request-hash', 'wrong-result-hash', 'missing-claim'])
def test_verify_stopped_missing_consumed_evidence_pauses_without_query(autonomous_cancel_case, stage):
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    path = case.path
    if stage == 'missing-response':
        (path / 'autonomy-cancel-response.json').unlink()
    elif stage == 'corrupt-response':
        (path / 'autonomy-cancel-response.json').write_text('{}\n')
    elif stage == 'ledger-unknown':
        case.runtime['cancellation_results'][path.name]['outcome'] = 'unknown'
    elif stage == 'wrong-consumption':
        case.runtime['cancellations'][path.name]['consumption_sha256'] = '0' * 64
    elif stage == 'wrong-request-hash':
        case.runtime['cancellations'][path.name]['evidence_sha256'] = '0' * 64
    elif stage == 'wrong-result-hash':
        case.runtime['cancellation_results'][path.name]['evidence_sha256'] = '0' * 64
    elif stage == 'missing-claim':
        (path / '.cancel-claim').unlink()
    with pytest.raises((ValueError, OSError)):
        run_verify_stopped(case)
    assert len(case.calls) == len(case.captured) == 1
    assert not case.proof_calls and not (path / 'autonomy-cancel-stopped.json').exists()
    assert case.paused is True


def test_verify_stopped_without_cancellation_is_plain_rejection(autonomous_cancel_case):
    case = autonomous_cancel_case
    with pytest.raises((ValueError, OSError)):
        run_verify_stopped(case)
    assert case.calls == case.captured == case.pauses == []
    assert case.paused is False


@pytest.mark.parametrize('stage', ['query', 'proof', 'changed-config', 'changed-result', 'lost-owner', 'write'])
def test_verify_stopped_failure_keeps_consumption_and_never_recancels(autonomous_cancel_case, monkeypatch, stage):
    from ag import _autonomy_store as disk
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    if stage == 'query':
        case.capture_error = 'scheduler query failed'
    elif stage == 'proof':
        case.proof_error = 'controller remains COMPLETING'
    elif stage == 'changed-config':
        case.after_capture = lambda: case.cfg_current['ssh'].update(host='different-fixture')
    elif stage == 'changed-result':
        case.after_capture = lambda: case.runtime['cancellation_results'][case.path.name].update(outcome='unknown')
    elif stage == 'lost-owner':
        case.after_capture = lambda: setattr(case, 'publication_refused', True)
    elif stage == 'write':
        original = disk.Store.exclusive
        def refuse(store, name, data):
            if name == 'autonomy-cancel-stopped.json':
                raise OSError('synthetic full disk')
            return original(store, name, data)
        monkeypatch.setattr(disk.Store, 'exclusive', refuse)
    with pytest.raises(ValueError, match='no replacement'):
        run_verify_stopped(case)
    assert len(case.calls) == len(case.consumed) == 1
    assert not (case.path / 'autonomy-cancel-stopped.json').exists()
    assert case.paused is (stage != 'lost-owner')


def test_cli_verify_stopped_uses_readonly_transport_and_only_stop_entry(cfg, prepared, monkeypatch):
    from types import SimpleNamespace
    created, calls = [], []
    monkeypatch.setattr('ag.transport.SSHTransport', lambda cfg, **kwargs: created.append(kwargs) or Fake(cfg))
    monkeypatch.setattr(cancel, 'verify_stopped', lambda *args, **kwargs: calls.append(kwargs) or {'stopped': True})
    monkeypatch.setattr(cancel, 'autonomous_cancel', lambda *a, **k: pytest.fail('Must not cancel again'))
    monkeypatch.setattr(cancel, 'cancel', lambda *a, **k: pytest.fail('Must not request manual cancellation'))
    assert cli.core_command(SimpleNamespace(config=cfg, command='cancel', id=prepared[0].name, json=True,
        verify_stopped=True, run='wake', token='token', plan_sha256='a' * 64)) == 0
    assert created == [dict(read_only=True)] and calls == [dict(run_id='wake', token='token', plan_sha256='a' * 64)]


@pytest.mark.parametrize('bad', ['missing-run', 'missing-token', 'missing-plan', 'kind', 'reason', 'policy', 'reviews'])
def test_cli_verify_stopped_rejects_cancel_arguments_before_transport(cfg, prepared, monkeypatch, bad):
    from types import SimpleNamespace
    args = dict(config=cfg, command='cancel', id=prepared[0].name, json=True,
                verify_stopped=True, run='wake', token='token', plan_sha256='a' * 64)
    key = {'missing-run': 'run', 'missing-token': 'token', 'missing-plan': 'plan_sha256',
           'policy': 'autonomous_policy'}.get(bad, bad)
    args[key] = None if bad.startswith('missing') else 'unused'
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **k: pytest.fail('Invalid context must precede transport'))
    with pytest.raises(ValueError):
        cli.core_command(SimpleNamespace(**args))


@pytest.mark.parametrize('change', ['expired', 'changed'])
def test_autonomous_cancel_rechecks_rule_after_request_saved(autonomous_cancel_case, monkeypatch, change):
    from ag import _autonomy_store as disk
    case = autonomous_cancel_case
    original = disk.Store.exclusive
    saved = []
    def write(store, name, data):
        original(store, name, data)
        if name == 'autonomy-cancel-request.json':
            saved.append(True)
    def policy(*args):
        if saved:
            if change == 'expired':
                raise ValueError('Effective rule expired during evidence reads')
            return {}, '0' * 64
        return {}, case.rule_hash
    monkeypatch.setattr(disk.Store, 'exclusive', write)
    monkeypatch.setattr(submit, 'bound_policy', policy)
    with pytest.raises(ValueError):
        run_autonomous_cancel(case)
    assert saved and (case.path / 'autonomy-cancel-request.json').exists()
    assert case.consumed == case.calls == case.records == []
    assert not (case.path / '.cancel-claim').exists()


@pytest.mark.parametrize('stage', ['proof', 'final-receipt'])
def test_verify_stopped_rechecks_expiry_after_lockfree_work(autonomous_cancel_case, stage):
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    if stage == 'proof':
        case.after_proof = lambda: setattr(case, 'now', case.run_until)
    else:
        def advance():
            if case.proof_calls and case.locks:
                case.now = case.run_until
        case.receipt_hook = advance
    with pytest.raises(ValueError, match='no replacement'):
        run_verify_stopped(case)
    assert case.paused and len(case.calls) == 1 and len(case.proof_calls) == 1
    assert not (case.path / 'autonomy-cancel-stopped.json').exists()


def test_verify_stopped_read_receipt_rejects_file_mutation_after_parsing(autonomous_cancel_case):
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    source = case.path / 'inputs/water.gjf'
    case.after_proof = lambda: source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='no replacement'):
        run_verify_stopped(case)
    assert case.paused and len(case.calls) == 1
    assert not (case.path / 'autonomy-cancel-stopped.json').exists()


def test_verify_stopped_unrelated_registry_addition_does_not_invalidate_owner(autonomous_cancel_case):
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    registry = Path.home() / '.config/ag/autonomy-studies'
    case.after_proof = lambda: (registry / 'unrelated-study.json').write_text('{}\n')
    result = run_verify_stopped(case)
    assert result['stopped'] is True and not case.paused
    assert len(case.calls) == 1


def test_verify_stopped_registry_replacement_is_rejected(autonomous_cancel_case):
    case = autonomous_cancel_case
    run_autonomous_cancel(case)
    registry = Path.home() / '.config/ag/autonomy-studies'
    def replace():
        registry.rename(registry.with_name('old-studies'))
        registry.mkdir()
    case.after_proof = replace
    with pytest.raises(ValueError, match='no replacement'):
        run_verify_stopped(case)
    assert case.paused and not (case.path / 'autonomy-cancel-stopped.json').exists()
