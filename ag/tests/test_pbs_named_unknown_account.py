"""A live PBS owner observation may invalidate a resolved UNKNOWN at either named check."""
import pytest

from ag import attempt, autonomy, autonomy_submission, confirm, node_targeting, remote, route, state, study, submit
from ag.transport import Result
from test_autonomy_submission import actual_unknown_resolution, selector, unknown_monitor_sample
from test_core import cfg, prepared
from test_node_targeting import TargetFake, nodes, policy, queue_site, snapshot


class ConfirmedOwnerFake(TargetFake):
    def __init__(self, config, phase, name):
        super().__init__(config)
        self.phase = phase
        self.appeared = False
        self.name = name
        self.owner = 'synthetic-user'
        self.live_owner_checks = []
        self.node_text = nodes()

    def run(self, command):
        if command == remote.identity():
            self.calls.append(command)
            return Result(stdout=self.owner + '\n')
        if command == remote.pbs_own_jobs():
            self.calls.append(command)
            self.live_owner_checks.append(self.appeared)
            ids = '77.fixture\n' if self.appeared else ''
            return Result(stdout=f'AG_OWNER {self.owner}\n{ids}AG_END\n')
        if command == remote.jobs():
            self.calls.append(command)
            text = (f'Job Id: 77.fixture\n    Job_Name = {self.name}\n    '
                    f'Job_Owner = {self.owner}@fixture\n    job_state = Q\n    '
                    'queue = batch\n    Resource_List.nodes = 1:ppn=8\n') if self.appeared else ''
            return Result(stdout=text)
        return super().run(command)

    def upload(self, *args):
        super().upload(*args)
        if self.phase == 'upload':
            self.appeared = True


@pytest.mark.parametrize('start_delta', [1, 601])
@pytest.mark.parametrize('phase', ['confirmation', 'upload'])
@pytest.mark.parametrize('form', ['exact', 'truncated', 'unrelated'])
def test_live_unknown_against_named_pbs_fresh_check(actual_unknown_resolution, monkeypatch, tmp_path, phase, form, start_delta):
    cfg, source, old, saved, clock, negative = actual_unknown_resolution
    source_id = old['attempt_id']
    autonomy.resolve_attempt(cfg, 'smoke', source_id, 'Synthetic explicit manual resolution')
    name = old['pbs_job_name']
    live_name = {'exact':name, 'truncated':name[:-3] + '+', 'unrelated':'independent-job'}[form]

    cfg['resources'].update(max_cores=32, max_committed_cores=32, max_queued_cores=32)
    cfg['resources']['tiers']['general'] = dict(cores=24, mem_gb=48)
    # Prepare the normal named 24-core candidate; install the queue policy before
    # both fresh checks. The source identity and monitored account remain fixed.
    cfg['node_targeting'] = policy()
    study.init(cfg, 'candidate')
    snapshot(cfg, node_targeting.strict_nodes(nodes(), []))
    candidate_input = tmp_path / 'candidate.gjf'
    candidate_input.write_text('%nprocshared=24\n%mem=40GB\n# HF/STO-3G SP\n\nSynthetic water\n\n0 1\nO 0.0 0.0 0.0\nH 0.0 0.0 1.0\nH 0.0 1.0 0.0\n\n')
    m = attempt.prepare(cfg, study_name='candidate', template='gaussian', input_path=candidate_input,
        target_node='compute-a', tier='general', label='named', walltime='00:10:00', method_basis='Synthetic')
    queue_site(cfg)

    # Replace the prepare helper's wall-clock cache, then publish adjacent fixture-time generations.
    for delta in (start_delta, 60, 60):
        clock[0] += delta
        unknown_monitor_sample(cfg, saved, clock[0])
    placements = autonomy_submission.read_reservations(cfg)['placements']
    assert len(placements) == 1 and placements[0]['state'] == 'finished'
    assert placements[0]['job_id'] is None and 'unknown_release' in placements[0]
    accounting = route.retain_live_unknowns(placements, {'default'}, [live_name])
    expected_hold = 0 if form == 'unrelated' else 8
    assert sum(p['cores'] for p in accounting if p['state'] == 'unknown') == expected_hold

    fake = ConfirmedOwnerFake(cfg, phase, live_name)
    fake.job = Result(stdout=f"Job Id: 123.fixture\n    Job_Name = {m['pbs_job_name']}\n    job_state = Q\n")
    def click(_):
        if phase == 'confirmation':
            fake.appeared = True
        return True
    monkeypatch.setattr(confirm, 'confirm', click)
    path = attempt.find(cfg, m['attempt_id'])
    if expected_hold:
        stage = 'after confirmation' if phase == 'confirmation' else 'after upload, before qsub'
        with pytest.raises(ValueError, match=stage + '.*limit exceeded'):
            submit.submit(cfg, [m['attempt_id']], fake)
        assert fake.operations().count('submit') == 0
        assert fake.live_owner_checks == ([True] if phase == 'confirmation' else [False, True])
        assert (path / '.submit-claim').exists() is (phase == 'upload')
        assert state.read(path)['state'] == ('failed_presubmit' if phase == 'upload' else 'prepared')
    else:
        submit.submit(cfg, [m['attempt_id']], fake)
        assert fake.operations().count('submit') == 1 and len(fake.live_owner_checks) == 2
        assert state.read(path)['state'] == 'submitted'
    assert state.read(source)['state'] == 'unknown'


@pytest.mark.parametrize('label,expected', [('sp', 'unknown'), ('different', 'finished')])
def test_unmapped_foreign_entry_cannot_disambiguate_unknown_name(
        actual_unknown_resolution, monkeypatch, tmp_path, label, expected):
    from test_core import Fake
    cfg, source, old, saved, clock, _ = actual_unknown_resolution
    autonomy.resolve_attempt(cfg, 'smoke', source.name, 'Synthetic resolution')
    other = dict(clusters={'foreign': cfg}, local={'studies_root': str(tmp_path / 'other-studies')},
                 _config_dir=str(tmp_path / 'other-config'))
    (tmp_path / 'other-config').mkdir()
    study.init(other, 'smoke')
    foreign = attempt.prepare(other, study_name='smoke', template='gaussian', input_path=tmp_path / 'water.gjf',
                              cluster='foreign', tier='simple', walltime='00:30:00',
                              label=label, method_basis='Synthetic method')
    monkeypatch.setattr(confirm, 'confirm', lambda _: True)
    submit.submit(other, [foreign['attempt_id']], Fake(other))
    assert (old['pbs_job_name'] == foreign['pbs_job_name']) is (label == 'sp')
    for delta in (601, 60, 60):
        clock[0] += delta
        unknown_monitor_sample(cfg, saved, clock[0])
    with autonomy_submission.machine_lock(create=False):
        placements = autonomy_submission.read_pbs_reservations(cfg)['placements']
    local, peer = sorted(placements, key=lambda p: p['cluster'])
    assert local['state'] == expected and local['job_id'] is None
    assert peer['unmapped_manual_account'] and peer['cores'] == 8
