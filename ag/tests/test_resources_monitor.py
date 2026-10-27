"""T112: synthetic resources, local histories, config reloads and timeout recovery."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest

from ag import attempt, config, gaussian_input, monitor, study
from ag.transport import Result, SSHConnectionError
from test_core import cfg, INPUT, write_config
from test_slurm import multi, SlurmFake
from test_monitor import Fake as PBSFake


def prepare(cfg, tmp_path, *, tier='general', text=None, template='gaussian', **kwargs):
    if not (Path(cfg['local']['studies_root']) / 'water').exists():
        study.init(cfg, 'water')
    source = tmp_path / 'water.gjf'
    cores = cfg['resources']['tiers'][tier]['cores']
    source.write_bytes(text if text is not None else INPUT.replace('%mem=10GB\n', '').replace(
        'nprocshared=8', f'nprocshared={cores}').encode())
    manifest = attempt.prepare(cfg, study_name='water', template=template, input_path=source,
                               tier=tier, walltime='00:10:00', label='sp',
                               method_basis='兜底方法：合成测试', **kwargs)
    return attempt.find(cfg, manifest['attempt_id']), manifest


@pytest.mark.parametrize('cores,mem,expected', [
    (4, 10, 8), (8, 12, 10), (22, 50, 42), (44, 120, 88),
    (8, 16, 13), (16, 32, 27), (24, 48, 40), (36, 72, 61),
])
@pytest.mark.parametrize('missing_cores', [False, True])
def test_memory_tiers_and_bundle(cfg, tmp_path, cores, mem, expected, missing_cores):
    cfg['resources']['tiers']['general'] = dict(cores=cores, mem_gb=mem)
    text = INPUT.replace('%mem=10GB\n', '').replace('nprocshared=8', f'nprocshared={cores}')
    if missing_cores:
        text = text.replace(f'%nprocshared={cores}\n', '')
    path, m = prepare(cfg, tmp_path, text=text.encode())
    data = (path / 'inputs/water.gjf').read_bytes()
    assert data.startswith(f'%nprocshared={cores}\n%mem={expected}GB\n'.encode())
    assert b'%mem' not in (tmp_path / 'water.gjf').read_bytes()
    assert m['auto_mem_gb'] == expected
    assert m.get('auto_nprocshared') == (cores if missing_cores else None)
    assert f'%mem 由 ag 自动填写：{expected} GB（规则 R1）' in attempt.summary(cfg, m)
    assert attempt.verified_files(cfg, path, m)['water.gjf'] == data
    assert 'resource_references' not in json.loads((path / 'manifest.json').read_text())


def test_existing_bytes_and_old_bundle(cfg, tmp_path, monkeypatch):
    data = INPUT.replace('nprocshared=8', 'nprocshared=22').replace('10GB', '30GB').replace(
        '\n', '\r\n').encode()
    path, m = prepare(cfg, tmp_path, text=data)
    assert 'auto_mem_gb' not in m
    assert 'auto_nprocshared' not in m
    assert (path / 'inputs/water.gjf').read_bytes() == data
    # Verification must never invoke either fill step or rewrite an old bundle.
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.rglob('*') if p.is_file()}
    with monkeypatch.context() as guard:
        def no_fill(*args, **kwargs):
            pytest.fail('saved bundles must not be filled again')
        guard.setattr(gaussian_input, 'fill_nprocshared', no_fill)
        guard.setattr(gaussian_input, 'fill_memory', no_fill)
        assert attempt.verified_files(cfg, path, attempt.read_manifest(path))['water.gjf'] == data
        assert '由 ag 自动填写' not in attempt.summary(cfg, m)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    with pytest.raises(ValueError, match='85%'):
        prepare(cfg, tmp_path, text=data.replace(b'30GB', b'43GB'))
    (path / 'inputs/water.gjf').write_bytes(data.replace(b'%nprocshared=22\r\n', b''))
    with pytest.raises(ValueError, match='Input bundle differs'):
        attempt.verified_files(cfg, path, m)


@pytest.mark.parametrize('cluster,cores', [('default', 8), ('batch', 16)])
@pytest.mark.parametrize('ending', ['\n', '\r\n'])
@pytest.mark.parametrize('missing_cores,missing_memory', [(True, True), (True, False),
                                                       (False, True), (False, False)])
def test_resource_fill_selected_entry_bytes_and_hashes(multi, tmp_path, cluster, cores,
                                                       ending, missing_cores, missing_memory):
    multi['clusters']['batch']['resources']['tiers']['simple'] = dict(cores=16, mem_gb=32)
    study.init(multi, 'fill-test')
    core_line = f'%NpRoCsHaReD \t= {cores} \t{ending}'.encode()
    memory_line = f'%MeM \t= 8000MB \t{ending}'.encode()
    body = INPUT.split('#', 1)[1]
    source_data = ((b'' if missing_cores else core_line) + (b'' if missing_memory else memory_line)
                   + ('%chk=water.chk\n#' + body).replace('\n', ending).encode())
    source = tmp_path / 'water.gjf'
    source.write_bytes(source_data)
    source_hash = sha256(source_data).hexdigest()
    m = attempt.prepare(multi, study_name='fill-test', template='gaussian', input_path=source,
                        tier='simple', cluster=cluster, walltime='00:10:00', label='sp',
                        method_basis='Synthetic fallback')
    path = attempt.find(multi, m['attempt_id'])
    filled_core = f'%nprocshared={cores}{ending}'.encode() if missing_cores else core_line
    expected_memory = 10 if cluster == 'default' else 27
    filled_memory = f'%mem={expected_memory}GB{ending}'.encode() if missing_memory else memory_line
    expected = filled_core + filled_memory + ('%chk=water.chk\n#' + body).replace('\n', ending).encode()
    assert (path / 'inputs/water.gjf').read_bytes() == expected
    assert source.read_bytes() == source_data and sha256(source.read_bytes()).hexdigest() == source_hash
    assert m.get('auto_nprocshared') == (cores if missing_cores else None)
    assert m.get('auto_mem_gb') == (expected_memory if missing_memory else None)
    assert ('auto_nprocshared' in m) is missing_cores
    assert ('auto_mem_gb' in m) is missing_memory
    summary = attempt.summary(multi, m)
    assert (f'%nprocshared 由 ag 自动填写：{cores}' in summary) is missing_cores
    assert ('%mem 由 ag 自动填写' in summary) is missing_memory
    assert sha256(expected).hexdigest() in summary
    files = attempt.verified_files(multi, path, attempt.read_manifest(path))
    assert files['water.gjf'] == expected
    records = [dict(name=name, size=len(data), sha256=sha256(data).hexdigest())
               for name, data in sorted(files.items())]
    digest = sha256(''.join(f"{r['name']}\0{r['sha256']}\n" for r in records).encode()).hexdigest()
    assert m['inputs'] == records and m['bundle_sha256'] == digest


def test_link0_only_and_line_endings():
    data = INPUT.replace('%mem=10GB\n', '').replace('Water smoke', 'Title %mem=99GB').replace(
        '\n', '\r\n').encode()
    actual, memory = gaussian_input.fill_memory(data, 8, 12)
    assert actual == data.replace(b'%nprocshared=8\r\n', b'%nprocshared=8\r\n%mem=10GB\r\n')
    assert memory == 10
    assert gaussian_input.fill_memory(actual, 8, 12) == (actual, None)
    with pytest.raises(ValueError, match='integer GB'):
        gaussian_input.fill_memory(data, 8, 1)


def test_cp_auto_memory(cfg, tmp_path):
    from test_counterpoise import WATER, CSV
    source = ('%nprocshared=22\n%chk=water.chk\n# B3LYP/6-31G(d) Counterpoise=2 SP\n\n'
              'water dimer\n\n0 1\n' + WATER + '\n\n').encode()
    fragments = tmp_path / 'fragments.csv'
    fragments.write_text(CSV)
    path, m = prepare(cfg, tmp_path, text=source, template='gaussian-cp', fragments=fragments)
    assert m['auto_mem_gb'] == 42
    assert b'%mem=42GB\n' in attempt.verified_files(cfg, path, m)['water.gjf']


def historical(cfg, name, atoms=10, route='# RB3LYP/6-31G(d) Freq', *, state='fetched',
               template='gaussian', receipts=True):
    path = Path(cfg['local']['studies_root']) / 'past' / 'attempts' / name
    path.mkdir(parents=True)
    manifest = dict(attempt_id=name, study_id='past', template=template, tier='simple', cores=8)
    current = dict(state=state, job_id='123.fixture')
    if receipts:
        current['receipts'] = dict(
            start=dict(PBS_JOBID='123.fixture', started_at='2026-01-01T00:00:00Z'),
            exit=dict(PBS_JOBID='123.fixture', finished_at='2026-01-01T00:02:03Z'))
    (path / 'manifest.json').write_text(json.dumps(manifest))
    (path / 'status.json').write_text(json.dumps(current))
    (path / 'facts.json').write_text(json.dumps(
        dict(n_atoms=atoms, route=route, multiplicity=1, termination='normal')))
    return path


def test_history_filters_sort_limit_and_missing_receipts(cfg):
    target = dict(template='gaussian', science=dict(n_atoms=10, route='# B3LYP/6-31G(d) SP',
                                                   multiplicity=1))
    assert '无参考' in attempt.resource_references(cfg, target)
    historical(cfg, 'a', 12)
    historical(cfg, 'b', 8)
    historical(cfg, 'c', 9)
    historical(cfg, 'd', 11)
    historical(cfg, 'e', 10, receipts=False)
    historical(cfg, 'f', 10, state='finished')
    historical(cfg, 'outside', 13)
    historical(cfg, 'pending', state='running')
    historical(cfg, 'wrong-basis', route='# B3LYP/STO-3G')
    historical(cfg, 'wrong-spin', route='# UB3LYP/6-31G(d)')
    historical(cfg, 'wrong-template', template='gaussian-cp')
    historical(cfg, 'no-facts').joinpath('facts.json').unlink()
    historical(cfg, 'bad-facts').joinpath('facts.json').write_text('{')
    result = attempt.resource_references(cfg, target)
    rows = [line for line in result.splitlines() if line.startswith('- ')]
    assert [line.split(' / ')[1].split(' | ')[0] for line in rows] == ['e', 'f', 'c', 'd', 'a']
    assert '实际耗时 未知' in rows[0] and '实际耗时 123 秒' in rows[1]
    assert '集群 default | 档位 simple / 8 核' in rows[0]
    assert 'termination: normal' in rows[0]
    assert cfg['local']['studies_root'] not in result


@pytest.mark.parametrize('damage', ['missing', 'naive', 'reversed', 'job'])
def test_receipt_time_never_guessed(cfg, damage):
    path = historical(cfg, 'water')
    current = json.loads((path / 'status.json').read_text())
    if damage == 'missing':
        current['receipts']['exit'] = None
    elif damage == 'naive':
        current['receipts']['start']['started_at'] = '2026-01-01T00:00:00'
    elif damage == 'reversed':
        current['receipts']['start']['started_at'] = '2026-01-02T00:00:00Z'
    else:
        current['receipts']['start']['PBS_JOBID'] = '999.fixture'
    assert attempt.receipt_elapsed(current, {}, '123.fixture') == '未知'


def test_reload_add_remove_invalid_and_recover(multi, monkeypatch, capsys):
    file = write_config(multi)
    loaded = config.load_config(file)
    calls, rounds = [], []
    tick = [0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    def transport(entry, **kwargs):
        calls.append(entry['_cluster'])
        return SlurmFake(entry) if config.scheduler_kind(entry) == 'slurm' else PBSFake()
    monkeypatch.setattr(monitor, 'MonitorTransport', transport)
    def sleep(_):
        tick[0] += 60
        rounds.append(1)
        if len(rounds) == 1:
            multi['clusters']['added'] = deepcopy(multi['clusters']['default'])
            multi['clusters']['added']['resources']['max_cores'] = 48
            write_config(multi)
        elif len(rounds) == 2:
            del multi['clusters']['added']
            write_config(multi)
        elif len(rounds) == 3:
            file.write_text('[broken')
        elif len(rounds) == 4:
            multi['clusters']['default']['resources']['tiers']['mini']['mem_gb'] = 11
            write_config(multi)
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run_clusters(loaded, 60, json_output=True) == 0
    snapshots = [json.loads(line)['clusters'] for line in capsys.readouterr().out.splitlines()]
    assert ['added' in s for s in snapshots] == [False, True, False, False, False]
    assert all(s['config_warning'] for s in snapshots[3].values())
    assert all(s['config_warning'] is None for s in snapshots[4].values())
    assert snapshots[4]['default']['own']['tiers']['mini']['mem_gb'] == 11
    removed = json.loads((Path(multi['local']['studies_root']) /
                          '.ag-monitor/added/latest.json').read_text())
    assert removed['config_removed'] and removed['config_note'] == '配置已移除'
    assert removed['sampled_at'] == snapshots[1]['added']['sampled_at']
    assert removed['own'] == snapshots[1]['added']['own']
    assert calls.count('added') == 1


def test_single_reload_custom_file_and_timeout_then_recovery(cfg, tmp_path, monkeypatch, capsys):
    file = tmp_path / 'custom.toml'
    file.write_bytes(write_config(cfg).read_bytes())
    loaded = config.load_config(file)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    fake = PBSFake()
    fake.replies['jobs'] = subprocess.TimeoutExpired('ssh fixture', 60)
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    rounds = []
    tick = [0.0]
    monkeypatch.setattr(monitor.time, 'monotonic', lambda: tick[0])
    def sleep(_):
        tick[0] += 60
        rounds.append(1)
        if len(rounds) == 1:
            cfg['resources']['max_cores'] = 48
            file.write_bytes(write_config(cfg).read_bytes())
            fake.replies = PBSFake().replies
        else:
            raise KeyboardInterrupt
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    assert monitor.run(loaded, 60, json_output=True) == 0
    failed, recovered = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not failed['ok'] and 'fixture' not in failed['error']
    assert failed['own']['max_cores'] == 44
    assert failed['own']['tiers'] == cfg['resources']['tiers']
    assert recovered['ok'] and recovered['own']['max_cores'] == 48


def test_timeout_isolated_between_clusters(multi, monkeypatch, capsys):
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    def transport(entry, **kwargs):
        if entry['_cluster'] == 'default':
            fake = PBSFake()
            fake.replies['jobs'] = SSHConnectionError('synthetic timeout')
            return fake
        return SlurmFake(entry)
    monkeypatch.setattr(monitor, 'MonitorTransport', transport)
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert monitor.run_clusters(multi, 60, json_output=True) == 0
    snapshots = json.loads(capsys.readouterr().out)['clusters']
    assert not snapshots['default']['ok'] and snapshots['batch']['ok']
    for name, row in snapshots.items():
        assert row['own']['max_cores'] == multi['clusters'][name]['resources']['max_cores']
        assert row['own']['tiers'] == multi['clusters'][name]['resources']['tiers']


def test_storage_hourly_timeout_cache_and_recovery(multi, monkeypatch):
    entry = config.select_cluster(multi, 'batch')
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    class Clock(datetime):
        instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls.instant
    monkeypatch.setattr(monitor, 'datetime', Clock)
    fake = SlurmFake(entry)
    first = monitor.sample(entry, fake)
    assert first['ok'] and first['cluster']['storage_kib'] == 1024
    for offset in (60, 120, 3599):
        Clock.instant = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
        assert monitor.sample(entry, fake)['ok']
    assert len([c for c in fake.calls if c.operation == 'storage_usage']) == 1
    original = fake.run
    def fail(command):
        if command.operation == 'storage_usage':
            fake.calls.append(command)
            assert command.timeout == monitor.STORAGE_TIMEOUT == 30
            raise SSHConnectionError(f"storage {entry['ssh']['host']} timeout")
        return original(command)
    fake.run = fail
    Clock.instant += timedelta(seconds=1)
    failed = monitor.sample(entry, fake)
    assert failed['ok'] and failed['cluster']['storage_kib'] == 1024
    assert failed['cluster']['storage_sampled_at'] == first['cluster']['storage_sampled_at']
    assert failed['cluster']['storage_error'] and 'fixture' not in failed['cluster']['storage_error']
    Clock.instant += timedelta(seconds=60)
    cached = monitor.sample(entry, fake)
    assert cached['ok'] and cached['cluster']['storage_error']
    assert len([c for c in fake.calls if c.operation == 'storage_usage']) == 2
    fake.run = original
    Clock.instant += timedelta(seconds=3540)
    recovered = monitor.sample(entry, fake)
    assert recovered['ok'] and recovered['cluster']['storage_error'] is None
    assert recovered['cluster']['storage_sampled_at'] != first['cluster']['storage_sampled_at']
    assert len([c for c in fake.calls if c.operation == 'storage_usage']) == 3


def test_monitor_transport_timeout_no_retry_and_still_readonly(cfg, monkeypatch):
    calls = []
    def execute(self, *args):
        calls.append(args)
        raise SSHConnectionError('synthetic timeout')
    monkeypatch.setattr(monitor.MonitorTransport, '_execute', execute)
    monkeypatch.setattr(monitor.time, 'sleep', lambda _: pytest.fail('No transport retries'))
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    transport = monitor.MonitorTransport(cfg, read_only=True)
    assert not monitor.sample(cfg, transport)['ok']
    assert len(calls) == 1
    with pytest.raises(ValueError, match='refuses uploads'):
        transport.upload(None, None, None)


@pytest.mark.parametrize('changed,expected', [
    (None, ['other']), ('hostname', []), ('port', []), ('user', []),
    ('scheduler', []), ('failure', []), ('timeout', []), ('incomplete', []),
])
def test_doctor_alias_identity(multi, monkeypatch, changed, expected):
    multi['clusters']['other'] = deepcopy(multi['clusters']['default'])
    multi['clusters']['other']['ssh']['host'] = 'other'
    if changed == 'scheduler':
        multi['clusters']['other']['scheduler'] = 'slurm'
    def run(argv, **kwargs):
        assert argv[:2] == ['ssh', '-G'] and kwargs['timeout'] == 15
        values = dict(hostname='synthetic.invalid', port='22', user='fixture')
        if argv[-1] == 'other':
            if changed == 'failure':
                return Result(1)
            if changed == 'timeout':
                raise subprocess.TimeoutExpired(argv, 15)
            if changed == 'incomplete':
                return Result(stdout='user fixture\n')
            if changed in values:
                values[changed] = '23' if changed == 'port' else 'different'
        elif argv[-1] == 'batch-fixture':
            pytest.fail('Different schedulers must not be compared')
        return Result(stdout='\n'.join(f'{key} {value}' for key, value in values.items()))
    monkeypatch.setattr(config.subprocess, 'run', run)
    assert config.unmerged_clusters(config.select_cluster(multi, 'default')) == expected


# Match T110 MonitorFieldsTests at frontend commit 113230d: accepted labels
# must survive the frontend validator, including Unicode/control boundaries.
@pytest.mark.parametrize('name', ['default', 'batch'])
@pytest.mark.parametrize('value', [
    None, 3, [], '', '筛' * 33, 'line\nbreak', 'tab\tname', 'bad\x00name', '\u200bhidden',
    '\x1b[31m', True,
])
def test_display_name_rejects_invalid_values(multi, name, value):
    multi['clusters'][name]['display_name'] = value
    with pytest.raises(config.ConfigError, match='display_name'):
        config.validate_cluster(multi['clusters'][name])
    if value is not None:
        with pytest.raises(config.ConfigError):
            config.load_config(write_config(multi))


@pytest.mark.parametrize('value', ['scnet-初筛', '筛' * 32])
def test_display_name_discovery_cli_is_local_and_preserves_identity(multi, tmp_path, monkeypatch, capsys, value):
    from test_clusters import query
    multi['clusters']['batch']['display_name'] = value
    code, result = query(multi, tmp_path, monkeypatch, capsys)
    assert code == 0
    row = next(row for row in result['clusters'] if row['name'] == 'batch')
    assert row['display_name'] == value
    assert row['name'] == 'batch'
    assert 'display_name' not in next(row for row in result['clusters'] if row['name'] == 'default')


@pytest.mark.parametrize('name', ['default', 'batch'])
def test_display_name_success_failure_old_cache_and_removal(multi, monkeypatch, name):
    entry = config.select_cluster(multi, name)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    fake = SlurmFake(entry) if name == 'batch' else PBSFake()
    previous = monitor.sample(entry, fake)
    entry['display_name'] = '初筛入口'
    if name == 'batch':
        fake.queue = Result(255)
    else:
        fake.replies['jobs'] = Result(255)
    failed = monitor.sample(entry, fake)
    assert not failed['ok'] and failed['cluster']['display_name'] == '初筛入口'
    assert failed['last_ok_at'] == previous['last_ok_at']
    entry['display_name'] = '新的显示名'
    assert monitor.sample(entry, fake)['cluster']['display_name'] == '新的显示名'
    del entry['display_name']
    assert 'display_name' not in monitor.sample(entry, fake)['cluster']
    entry['display_name'] = '恢复后的显示名'
    good = SlurmFake(entry) if name == 'batch' else PBSFake()
    assert monitor.sample(entry, good)['cluster']['display_name'] == '恢复后的显示名'


def test_display_name_prepared_and_submit_summary_only(cfg, tmp_path, monkeypatch):
    from ag import submit
    from test_core import Fake, allow
    cfg['display_name'] = '合成入口'
    path, m = prepare(cfg, tmp_path)
    before = (path / 'manifest.json').read_bytes()
    assert 'Cluster: 合成入口（default）' in attempt.summary(cfg, m)
    assert 'display_name' not in before.decode()
    cfg['display_name'] = '更新后的显示名'
    assert attempt.verified_files(cfg, path, m)
    summaries = []
    allow(monkeypatch)
    monkeypatch.setattr('ag.confirm.confirm', lambda text: summaries.append(text) or True)
    submit.submit(cfg, [path.name], Fake(cfg))
    assert len(summaries) == 1
    assert 'Cluster: 更新后的显示名（default）' in summaries[0]
    assert '%mem 由 ag 自动填写：42 GB（规则 R1）' in summaries[0]
    assert '资源参考' in summaries[0] and '无参考' in summaries[0]
    assert (path / 'manifest.json').read_bytes() == before
    record = json.loads((path / 'submission.json').read_text())
    assert record['cluster'] == 'default' and 'display_name' not in record
    assert record['job_id'].startswith('default:')


def test_display_name_legacy_mixed_default(cfg, multi):
    cfg['clusters'] = {'batch': multi['clusters']['batch']}
    file = write_config(cfg)
    file.write_text('display_name = "默认入口"\n' + file.read_text())
    loaded = config.load_config(file)
    assert config.select_cluster(loaded, 'default')['display_name'] == '默认入口'


# T149 configuration cache: real local files, no sleeping or remote commands.
def test_reload_cache_wakeup_count_and_thirty_second_fallback(cfg, monkeypatch):
    from test_monitor_resilience import Clock
    clock = Clock(monkeypatch)
    file = write_config(cfg)
    loaded = config.load_config(file)
    calls, original = [], monitor.load_config
    def load(path):
        calls.append(clock.tick)
        return original(path)
    monkeypatch.setattr(monitor, 'load_config', load)
    cache = monitor.ConfigReload()
    for _ in range(31):
        loaded, warning = cache.read(loaded)
        assert warning is None
        clock.advance(2)
    assert calls == [0, 30, 60]
    # Separate monitor lifetimes never share the cache.
    assert monitor.ConfigReload().read(loaded)[1] is None
    assert calls == [0, 30, 60, 62]


@pytest.mark.parametrize('change', ['inplace', 'same-size', 'replace', 'touch'])
def test_reload_cache_detects_file_identity_and_metadata(cfg, monkeypatch, change):
    import os
    from test_monitor_resilience import Clock
    clock = Clock(monkeypatch)
    file = write_config(cfg)
    loaded = config.load_config(file)
    cache = monitor.ConfigReload()
    loaded, warning = cache.read(loaded)
    before = monitor.config_signature(file)
    original, calls = monitor.load_config, []
    def load(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(monitor, 'load_config', load)
    raw = file.read_bytes()
    if change == 'replace':
        replacement = file.with_suffix('.replacement')
        replacement.write_bytes(raw)
        replacement.replace(file)
    elif change == 'touch':
        os.utime(file, ns=(file.stat().st_atime_ns, file.stat().st_mtime_ns + 1000000))
    elif change == 'same-size':
        file.write_bytes(raw.replace(b'max_cores = 44', b'max_cores = 48'))
    else:
        file.write_bytes(raw + b'\n# synthetic edit\n')
    assert monitor.config_signature(file) != before
    clock.advance(2)
    loaded, warning = cache.read(loaded)
    assert len(calls) == 1 and warning is None
    assert loaded['resources']['max_cores'] == (48 if change == 'same-size' else 44)


@pytest.mark.parametrize('field', range(5))
def test_reload_cache_checks_each_signature_field(cfg, monkeypatch, field):
    file = write_config(cfg)
    loaded = config.load_config(file)
    signature = [1, 2, 3, 4, 5]
    monkeypatch.setattr(monitor, 'config_signature', lambda _: tuple(signature))
    calls = []
    monkeypatch.setattr(monitor, 'load_config', lambda _: calls.append(1) or loaded)
    cache = monitor.ConfigReload()
    cache.read(loaded)
    signature[field] += 1
    cache.read(loaded)
    assert len(calls) == 2


def test_reload_cache_fallback_catches_metadata_preserving_change(cfg, monkeypatch):
    from test_monitor_resilience import Clock
    clock = Clock(monkeypatch)
    file = write_config(cfg)
    loaded = config.load_config(file)
    signature = monitor.config_signature(file)
    monkeypatch.setattr(monitor, 'config_signature', lambda _: signature)
    cache = monitor.ConfigReload()
    loaded, _ = cache.read(loaded)
    cfg['resources']['max_cores'] = 48
    write_config(cfg)
    clock.advance(29.9)
    assert cache.read(loaded)[0]['resources']['max_cores'] == 44
    clock.advance(.1)
    loaded, warning = cache.read(loaded)
    assert loaded['resources']['max_cores'] == 48 and warning is None


@pytest.mark.parametrize('failure', ['stat', 'parse', 'read', 'unstable'])
def test_reload_failure_retains_config_and_recovers_without_metadata_change(cfg, monkeypatch, failure):
    from test_monitor_resilience import Clock
    clock = Clock(monkeypatch)
    file = write_config(cfg)
    loaded = config.load_config(file)
    stable = monitor.config_signature(file)
    cache = monitor.ConfigReload()
    loaded, _ = cache.read(loaded)
    clock.advance(30)
    original, calls = monitor.load_config, []
    broken = [True]
    def signature(_):
        if broken[0] and failure == 'stat':
            raise OSError('synthetic stat failure')
        return (*stable[:-1], stable[-1] + len(calls)) if broken[0] and failure == 'unstable' else stable
    def load(path):
        calls.append(path)
        if broken[0] and failure in ('parse', 'read'):
            raise ValueError('synthetic parse failure') if failure == 'parse' else OSError('synthetic read failure')
        fresh = original(path)
        fresh['resources']['max_cores'] = 48
        return fresh
    monkeypatch.setattr(monitor, 'config_signature', signature)
    monkeypatch.setattr(monitor, 'load_config', load)
    retained, warning = cache.read(loaded)
    assert retained is loaded and retained['resources']['max_cores'] == 44 and warning
    assert cache.signature is None
    broken[0] = False
    clock.advance(2)
    fresh, warning = cache.read(retained)
    assert fresh['resources']['max_cores'] == 48 and warning is None
    assert cache.signature == (loaded['_config_path'], stable)


def test_in_memory_reload_never_reads_file(cfg, monkeypatch):
    monkeypatch.setattr(monitor, 'load_config', lambda _: pytest.fail('In-memory config parsed a file'))
    monkeypatch.setattr(monitor, 'config_signature', lambda _: pytest.fail('In-memory config statted a file'))
    cache = monitor.ConfigReload()
    for _ in range(20):
        assert cache.read(cfg) == (cfg, None)


def test_selected_custom_config_preserves_binding_on_reload(multi, tmp_path, monkeypatch):
    custom = tmp_path / 'custom-monitor.toml'
    custom.write_bytes(write_config(multi).read_bytes())
    loaded = config.select_cluster(config.load_config(custom), 'batch')
    value, warning = monitor.ConfigReload().read(loaded)
    assert value['_cluster'] == 'batch' and value['_config_path'] == str(custom)
    assert warning is None and config.scheduler_kind(value) == 'slurm'


def test_changed_control_root_stops_before_migration_or_second_sample(cfg, monkeypatch, capsys):
    from test_monitor_resilience import Clock
    clock = Clock(monkeypatch)
    loaded = config.load_config(write_config(cfg))
    original_root = Path(cfg['local']['studies_root'])
    new_root = original_root.with_name('other-studies')
    fake = PBSFake()
    monkeypatch.setattr(monitor, 'MonitorTransport', lambda *a, **k: fake)
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    def sleep(seconds):
        clock.advance(seconds)
        cfg['local']['studies_root'] = str(new_root)
        write_config(cfg)
    monkeypatch.setattr(monitor.time, 'sleep', sleep)
    with pytest.raises(ValueError, match='control root changed'):
        monitor.run(loaded, 60)
    assert len(fake.calls) == 3 and not new_root.exists()
    assert (original_root / '.ag-monitor/latest.json').exists()


def test_removed_marker_never_appends_sampling_history(cfg, monkeypatch):
    monkeypatch.setattr(monitor, 'login_user', lambda _: 'fixture')
    snapshot = monitor.sample(cfg, PBSFake())
    root = monitor.cache_dir(cfg)
    before = (root / 'history.jsonl').read_bytes()
    monitor.mark_removed(cfg)
    removed = json.loads((root / 'latest.json').read_text())
    assert {key: removed[key] for key in ('sampled_at', 'last_ok_at', 'ok')} == {
        key: snapshot[key] for key in ('sampled_at', 'last_ok_at', 'ok')}
    assert (root / 'history.jsonl').read_bytes() == before
