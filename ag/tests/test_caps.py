"""T51 admission boundaries, using synthetic queues and no live transport."""
import pytest

from ag import attempt, budget, config, confirm, doctor, monitor, state, submit
from ag.transport import Result
from test_core import cfg, prepared, job_text, write_config
from test_queue import QueueFake
from test_slurm import multi, prepare, SlurmFake


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('extra', [0, 1])
def test_total_boundary_includes_external_and_held(multi, tmp_path, monkeypatch, capsys, scheduler, extra):
    name = 'default' if scheduler == 'pbs' else 'batch'
    multi['clusters'][name]['resources'].update(max_cores=44, max_committed_cores=132)
    path, _ = prepare(multi, tmp_path, cluster=name)
    selected = config.select_cluster(multi, name)
    if scheduler == 'pbs':
        fake = QueueFake(selected, occupied=0)
        fake.qstat = Result(stdout=job_text(cores=40) + job_text(cores=40, state_='Q').replace('123.fixture', '124.fixture')
                           + job_text(cores=44 + extra, state_='H').replace('123.fixture', '125.fixture'))
    else:
        fake = SlurmFake(selected)
        # squeue %T reports PENDING for PD, including held jobs; reasons are not queried.
        fake.queue = Result(stdout=f'101|external|fixture|RUNNING|40|0:00|fixture\n'
                            f'102|manual|fixture|PENDING|40|0:00|fixture\n'
                            f'103|held|fixture|PENDING|{44 + extra}|0:00|fixture\n')
    dialogs = []
    monkeypatch.setattr(confirm, 'confirm', lambda text: dialogs.append(text) or True)
    if extra:
        with pytest.raises(ValueError, match='Core limit exceeded'):
            submit.submit(multi, [path.name], fake)
        assert not dialogs and not (path / '.submit-claim').exists()
    else:
        assert submit.submit(multi, [path.name], fake)[0]['state'] == 'submitted'
        text = dialogs[0]
        for expected in ('当前占用 124', '运行 40、排队 84', '其他电脑和非 ag',
                         '提交后合计 132 / 上限 132', 'ag 不限制运行中的核数', '最多 132 核'):
            assert expected in text
        assert text in capsys.readouterr().err
        if scheduler == 'slurm':
            assert '本次最多消耗 12 核时' in text
            assert budget.totals(selected)[1] > 0
    assert 'nodes' not in fake.operations()


@pytest.mark.parametrize('scheduler', ['pbs', 'slurm'])
@pytest.mark.parametrize('limit', [8, 7])
def test_single_job_boundary(multi, tmp_path, monkeypatch, scheduler, limit):
    name = 'default' if scheduler == 'pbs' else 'batch'
    path, _ = prepare(multi, tmp_path, cluster=name)
    multi['clusters'][name]['resources'].update(max_cores=limit, max_committed_cores=4 * limit)
    selected = config.select_cluster(multi, name)
    fake = QueueFake(selected, occupied=0) if scheduler == 'pbs' else SlurmFake(selected)
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    if limit == 8:
        assert submit.submit(multi, [path.name], fake)[0]['state'] == 'submitted'
    else:
        with pytest.raises(ValueError, match='Single job'):
            submit.submit(multi, [path.name], fake)
        assert not fake.calls


def test_slurm_unobserved_reservation_and_fresh_recheck(multi, tmp_path, monkeypatch):
    multi['clusters']['batch']['resources']['max_committed_cores'] = 132
    paths = [prepare(multi, tmp_path, label=label)[0] for label in ('prior', 'next')]
    selected = config.select_cluster(multi, 'batch')
    fake = SlurmFake(selected)
    monkeypatch.setattr(confirm, 'confirm', lambda text: True)
    submit.submit(multi, [paths[0].name], fake)
    fake.queue = Result(stdout='456|manual|fixture|RUNNING|117|0:00|fixture\n')
    with pytest.raises(ValueError, match='125 occupied.*8 requested / 132'):
        submit.submit(multi, [paths[1].name], fake)
    fake.queue = Result(stdout='456|manual|fixture|RUNNING|116|0:00|fixture\n')
    def accept(text):
        assert '当前占用 124 核（运行 116、排队 8；' in text
        fake.queue = Result(stdout='456|manual|fixture|RUNNING|117|0:00|fixture\n')
        return True
    monkeypatch.setattr(confirm, 'confirm', accept)
    with pytest.raises(ValueError, match='Core limit changed'):
        submit.submit(multi, [paths[1].name], fake)
    assert state.read(paths[1])['state'] == 'failed_presubmit'
    assert fake.operations().count('submit') == 1


@pytest.mark.parametrize('name', ['default', 'batch'])
@pytest.mark.parametrize('committed', [43, 177])
def test_config_committed_bounds(multi, name, committed):
    multi['clusters'][name]['resources']['max_committed_cores'] = committed
    with pytest.raises(ValueError, match='max_committed_cores'):
        config.load_config(write_config(multi))


def test_config_slurm_64_256_and_pbs_maximum(multi):
    multi['clusters']['batch']['resources'].update(max_cores=64, max_committed_cores=256)
    loaded = config.load_config(write_config(multi))
    assert loaded['clusters']['batch']['resources']['max_committed_cores'] == 256
    multi['clusters']['default']['resources']['max_cores'] = 45
    with pytest.raises(ValueError, match='max_cores'):
        config.load_config(write_config(multi))


@pytest.mark.parametrize('name', ['default', 'batch'])
def test_tier_must_fit_single_job_cap(multi, name):
    multi['clusters'][name]['resources']['max_cores'] = 43
    with pytest.raises(ValueError, match='Invalid resource tier'):
        config.load_config(write_config(multi))


@pytest.mark.parametrize('cores', [64, 256, 257])
def test_slurm_monitor_uses_committed_cap_and_doctor(multi, cores):
    multi['clusters']['batch']['resources'].update(max_cores=64, max_committed_cores=256)
    selected = config.select_cluster(multi, 'batch')
    fake = SlurmFake(selected)
    fake.queue = Result(stdout=f'101|external|fixture|PENDING|{cores}|0:00|fixture\n')
    result = monitor.observation(selected, fake, 'fixture')
    assert result['own']['core_cap'] == 64 and result['own']['committed_cap'] == 256
    assert bool(result['warnings']) == (cores > 256)
    if result['warnings']:
        assert '超过上限 256' in result['warnings'][0]['detail']
    assert doctor.doctor(selected, fake)['max_committed_cores'] == 256


def test_pbs_doctor_reports_both_caps(cfg):
    cfg['resources']['max_committed_cores'] = 132
    result = doctor.doctor(cfg, QueueFake(cfg, occupied=0))
    assert (result['max_cores'], result['max_committed_cores']) == (44, 132)
