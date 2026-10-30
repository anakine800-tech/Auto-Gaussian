"""Local publication races on synthetic evidence and real autonomy guards."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from ag import autonomy, cli, facts, mode_review, review
from ag import _review_manifest as inventory
from test_autonomy import env, ready, running, change, image_tree
from test_mode_review import synthetic_log
from test_review import CARD
from test_core import cfg, prepared


@pytest.fixture
def evidence(env):
    cfg, root, clock = env
    (root / 'analyses').mkdir()
    path = root / 'attempts/water-001-ts'
    (path / 'outputs').mkdir(parents=True)
    (path / 'inputs').mkdir()
    (path / 'inputs/water.gjf').write_text('Synthetic input\n')
    (path / 'outputs/water.log').write_text(synthetic_log())
    (path / 'manifest.json').write_text(json.dumps(dict(template='gaussian', attempt_id=path.name, study_id=root.name,
        inputs=[dict(name='water.gjf')], science=dict(route='# freq', charge=0, multiplicity=1),
        card=dict(name='test', git_commit='a' * 40, dirty=False, content=CARD))))
    (path / 'status.json').write_text('{"state":"fetched"}')
    return cfg, root, path, clock


def invoke(kind, root, path, owner=None):
    owner = owner or {}
    if kind == 'facts':
        return facts.write_facts(path, **owner)
    if kind == 'init':
        return review.init(path, **owner)
    if kind == 'manifest':
        return inventory.create(root, **owner)
    return mode_review.create(path.name, root, [(1, 2)], 'analyses/mode.json', **owner)


def context(env):
    plan, run = running(env)
    return plan, run, dict(run_id=run['run_id'], token=run['token'], plan_sha256=plan['sha256'])


def hook(monkeypatch, kind, callback):
    module, name = {'facts': (facts, 'parse_facts'), 'init': (review, 'facts_snapshot'),
                    'manifest': (inventory, '_references'), 'mode': (mode_review, 'read_modes')}[kind]
    original = getattr(module, name)
    called = []
    def analyze(*a, **kw):
        result = original(*a, **kw)
        if not called:
            called.append(True)
            callback()
        return result
    monkeypatch.setattr(module, name, analyze)
    return called


def no_publication(root, path):
    assert not (path / 'facts.json').exists()
    assert not (path / 'review.md').exists()
    assert not [p for p in (root / 'analyses').iterdir() if not p.name.startswith('.')]
    assert not (path / 'final.xyz').exists()


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
@pytest.mark.parametrize('paused', [False, True])
def test_current_owner_and_paused_organizing(evidence, env, kind, paused):
    cfg, root, path, clock = evidence
    plan, run, owner = context(env)
    if paused:
        autonomy.pause(cfg, root.name, 'Synthetic pause')
    invoke(kind, root, path, owner)
    if kind == 'init':
        assert '待人确认' in (path / 'review.md').read_text()
    assert autonomy.status(cfg, root.name)['state']['lease']['run_id'] == run['run_id']


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
@pytest.mark.parametrize('loss', ['timeout', 'takeover', 'finish', 'version'])
def test_analysis_loses_owner_before_publication(evidence, env, monkeypatch, kind, loss):
    cfg, root, path, clock = evidence
    plan, run, owner = context(env)
    def lose():
        if loss in ('timeout', 'takeover'):
            clock[0] += 3600 if loss == 'timeout' else 5400
        if loss == 'takeover':
            autonomy.start(cfg, root.name, plan['plan_id'], 'successor', takeover_reason='Synthetic expired lease')
        if loss == 'finish':
            change(env, run, 'finish', reason='Synthetic finished wake')
        if loss == 'version':
            original = autonomy.versions()
            monkeypatch.setattr(autonomy, 'versions', lambda: dict(original, git_commit='b' * 40))
    called = hook(monkeypatch, kind, lose)
    with pytest.raises(autonomy.PublicationRefused):
        invoke(kind, root, path, owner)
    assert called
    no_publication(root, path)


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
@pytest.mark.parametrize('source', ['manifest.json', 'facts.json', 'inputs/water.gjf', 'outputs/water.log'])
def test_sources_changed_after_analysis_are_not_published(evidence, env, monkeypatch, kind, source):
    cfg, root, path, clock = evidence
    plan, run, owner = context(env)
    # Inventory collects only referenced evidence; explicitly include these inputs.
    (root / 'study.md').write_text('Synthetic study\n')
    if kind == 'manifest' and source not in ('facts.json',):
        source = 'facts.json'
    original = autonomy.observation_publication_guard
    calls = []
    @contextmanager
    def guard(*a, **kw):
        calls.append(True)
        if len(calls) == 2:
            target = path / source
            target.write_text('{"changed": true}')
        with original(*a, **kw) as value:
            yield value
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    with pytest.raises((ValueError, OSError)):
        invoke(kind, root, path, owner)
    assert not (path / 'review.md').exists()
    assert not [p for p in (root / 'analyses').iterdir() if not p.name.startswith('.')]
    if source != 'facts.json':
        assert not (path / 'facts.json').exists()
    else:
        assert (path / 'facts.json').read_text() == '{"changed": true}'


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
@pytest.mark.parametrize('damage', ['replace', 'restore_mtime', 'directory', 'symlink'])
def test_file_and_directory_identity_are_rechecked(evidence, env, monkeypatch, kind, damage):
    cfg, root, path, clock = evidence
    plan, run, owner = context(env)
    target = root / 'study.md' if kind == 'manifest' else path / 'manifest.json'
    before = target.read_bytes()
    stamp = target.stat()
    def mutate():
        if damage == 'restore_mtime':
            target.write_bytes(before + b' ')
            os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        elif damage == 'replace':
            replacement = target.with_name('replacement')
            replacement.write_bytes(before)
            os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            os.replace(replacement, target)
        elif damage == 'directory':
            folder = root / 'analyses' if kind == 'manifest' else path / 'inputs'
            folder.rename(folder.with_name(folder.name + '-old'))
            folder.mkdir()
        else:
            target.rename(target.with_name(target.name + '-old'))
            target.symlink_to(target.with_name(target.name + '-old'))
    hook(monkeypatch, kind, mutate)
    with pytest.raises((ValueError, OSError)):
        invoke(kind, root, path, owner)
    no_publication(root, path)


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_manual_write_rejects_active_and_live_paused_lease(evidence, env, kind):
    cfg, root, path, clock = evidence
    context(env)
    with pytest.raises(ValueError, match='Pause'):
        invoke(kind, root, path)
    autonomy.pause(cfg, root.name, 'Synthetic pause')
    with pytest.raises(ValueError, match='live autonomous lease'):
        invoke(kind, root, path)
    no_publication(root, path)


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_manual_analysis_registration_excludes_lease_acquisition(evidence, env, monkeypatch, kind):
    cfg, root, path, clock = evidence
    plan = ready(env)
    autonomy.pause(cfg, root.name, 'Synthetic pause without lease')
    def acquire():
        with pytest.raises(ValueError, match='manual writer'):
            autonomy.start(cfg, root.name, plan['plan_id'], 'competing-owner')
    assert hook(monkeypatch, kind, acquire) == []
    invoke(kind, root, path)
    run = autonomy.start(cfg, root.name, plan['plan_id'], 'after-writer')
    assert run['run_id']


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_analysis_and_hashing_do_not_hold_publication_locks(evidence, env, monkeypatch, kind):
    cfg, root, path, clock = evidence
    plan, run, owner = context(env)
    original = autonomy.observation_publication_guard
    held = [False]
    @contextmanager
    def guard(*a, **kw):
        with original(*a, **kw) as value:
            held[0] = True
            try:
                yield value
            finally:
                held[0] = False
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    def check_unlocked():
        assert not held[0]
        autonomy.pause(cfg, root.name, 'Pause is not blocked by analysis')
    hook(monkeypatch, kind, check_unlocked)
    # Inventory deliberately notices its own evidence tree's changed membership.
    if kind == 'manifest':
        with pytest.raises(ValueError, match='变化'):
            invoke(kind, root, path, owner)
    else:
        invoke(kind, root, path, owner)


@pytest.mark.parametrize('options', [dict(refresh=True), dict(reparse=True), dict(reparse=True, dry_run=True)])
def test_owner_cannot_refresh_or_reparse(evidence, env, options):
    cfg, root, path, clock = evidence
    _, _, owner = context(env)
    before = image_tree(root)
    with pytest.raises(ValueError, match='cannot refresh or reparse'):
        facts.write_facts(path, **owner, **options)
    assert image_tree(root) == before


def test_conflicting_facts_remain_unchanged(evidence, env):
    cfg, root, path, clock = evidence
    (path / 'facts.json').write_text('{"schema":"ag-facts/1","old":true}')
    _, _, owner = context(env)
    old = (path / 'facts.json').read_bytes()
    with pytest.raises(facts.FactsConflictError):
        facts.write_facts(path, **owner)
    assert (path / 'facts.json').read_bytes() == old
    assert not list(path.glob('facts.*.json'))


def test_readonly_review_check_and_reparse_preview_do_not_register_writer(evidence, env, tmp_path):
    cfg, root, path, clock = evidence
    facts.write_facts(path)
    review.init(path)
    context(env)
    before = image_tree(root)
    registry = image_tree(Path.home())
    assert review.check(path)['complete'] is False
    facts.write_facts(path, reparse=True, dry_run=True, out=tmp_path / 'preview.json')
    assert image_tree(root) == before
    assert image_tree(Path.home()) == registry


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_partial_owner_parameters_do_not_fall_back_to_manual(evidence, kind):
    cfg, root, path, clock = evidence
    with pytest.raises(ValueError, match='together'):
        invoke(kind, root, path, {'run_id': 'missing-context'})
    no_publication(root, path)


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_deadline_crossed_during_final_source_check(evidence, env, monkeypatch, kind):
    cfg, root, path, clock = evidence
    _, _, owner = context(env)
    original_guard = autonomy.observation_publication_guard
    held = [False]
    @contextmanager
    def guard(*a, **kw):
        with original_guard(*a, **kw) as value:
            held[0] = True
            try:
                yield value
            finally:
                held[0] = False
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    original_check = facts._publication_unchanged
    crossed = []
    def checked(proof):
        original_check(proof)
        if held[0] and not crossed:
            crossed.append(True)
            clock[0] += 3600
    for module in (facts, inventory, mode_review):
        monkeypatch.setattr(module, '_publication_unchanged', checked)
    with pytest.raises(autonomy.PublicationRefused, match='60 minute'):
        invoke(kind, root, path, owner)
    assert crossed
    no_publication(root, path)


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
def test_payload_io_and_fsync_are_outside_shared_lock(evidence, env, monkeypatch, kind):
    cfg, root, path, clock = evidence
    _, _, owner = context(env)
    original_guard = autonomy.observation_publication_guard
    held = [False]
    @contextmanager
    def guard(*a, **kw):
        with original_guard(*a, **kw) as value:
            held[0] = True
            try:
                yield value
            finally:
                held[0] = False
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    fsync, link = os.fsync, os.link
    synced, linked = [], []
    def sync(fd):
        assert not held[0], 'Payload durability must precede the shared publication guard'
        synced.append(fd)
        return fsync(fd)
    def publish(source, destination, **kw):
        assert held[0]
        linked.append(destination)
        return link(source, destination, **kw)
    monkeypatch.setattr(os, 'fsync', sync)
    monkeypatch.setattr(os, 'link', publish)
    invoke(kind, root, path, owner)
    assert synced and len(linked) == {'facts': 2, 'init': 1, 'manifest': 1, 'mode': 3}[kind]
    assert not list((root / 'analyses').glob('.*stage-*'))


def test_owner_cannot_claim_human_acceptance_of_unresolved_references(evidence, env):
    cfg, root, path, clock = evidence
    _, _, owner = context(env)
    with pytest.raises(ValueError, match='requires manual review'):
        inventory.create(root, accept_unresolved=True, **owner)
    no_publication(root, path)


def cli_arguments(kind, root, path):
    return {
        'facts': ['facts', path.name, '--study', str(root)],
        'init': ['review', 'init', path.name],
        'manifest': ['review', 'manifest', '--study', str(root)],
        'mode': ['mode-review', path.name, '--study', str(root), '--pair', '1-2',
                 '--out', 'analyses/mode.json'],
    }[kind]


@pytest.mark.parametrize('kind', ['facts', 'init', 'manifest', 'mode'])
@pytest.mark.parametrize('authorization', ['owner', 'partial', 'manual'])
def test_actual_cli_owner_wiring(evidence, env, monkeypatch, capsys, kind, authorization):
    cfg, root, path, clock = evidence
    _, _, owner = context(env)
    def local_config(**options):
        assert kind == 'init' and options == {'local_only': True}
        return cfg
    monkeypatch.setattr(cli, 'load_config', local_config)
    monkeypatch.setattr('ag.transport.SSHTransport', lambda *a, **kw: pytest.fail('No remote transport'))
    args = cli_arguments(kind, root, path) + ['--json']
    if authorization != 'manual':
        args += ['--run', owner['run_id'], '--plan-sha256', owner['plan_sha256']]
        if authorization == 'owner':
            args += ['--token', owner['token']]
    assert cli.main(args) == (0 if authorization == 'owner' else 1)
    response = capsys.readouterr()
    assert owner['token'] not in response.out + response.err
    if authorization != 'owner':
        no_publication(root, path)


def test_readonly_check_has_no_owner_cli_flags(evidence, env):
    cfg, root, path, clock = evidence
    before = image_tree(root)
    with pytest.raises(SystemExit) as error:
        cli.main(['review', 'check', path.name, '--run', 'unused-owner'])
    assert error.value.code == 2
    assert image_tree(root) == before


@pytest.mark.parametrize('expire', [False, True])
def test_cli_fetch_automatic_facts_rechecks_native_guard_state(
        env, cfg, prepared, monkeypatch, capsys, expire):
    from ag import state, transport
    from test_core import finish
    from test_fetch import ReadOnlyFake
    from test_autonomy import _publication_context
    path, _ = prepared
    finish(path)
    ctx, plan, run, _ = _publication_context(env, cfg, path)
    fake = ReadOnlyFake({'water.log': synthetic_log().encode(), 'job.pbs.out': b''})
    monkeypatch.setattr(cli, 'load_config', lambda: cfg)
    monkeypatch.setattr(transport, 'SSHTransport', lambda *a, **kw: fake)
    original_guard = autonomy.observation_publication_guard
    held = [False]
    @contextmanager
    def guard(*a, **kw):
        with original_guard(*a, **kw) as current:
            assert isinstance(current, dict) and not callable(current)
            held[0] = True
            try:
                yield current  # Preserve the original public guard result.
            finally:
                held[0] = False
    monkeypatch.setattr(autonomy, 'observation_publication_guard', guard)
    original_check = facts._publication_unchanged
    crossed = []
    def checked(proof):
        original_check(proof)
        if held[0] and not crossed:
            crossed.append(True)
            if expire:
                ctx[2][0] += autonomy.RUN_SECONDS
    monkeypatch.setattr(facts, '_publication_unchanged', checked)
    code = cli.main(['fetch', path.name, '--json', '--run', run['run_id'],
                     '--token', run['token'], '--plan-sha256', plan['sha256']])
    output = capsys.readouterr()
    assert crossed and code == (1 if expire else 0)
    assert state.read(path)['state'] == 'fetched'
    assert (path / 'outputs/water.log').read_bytes() == synthetic_log().encode()
    if expire:
        assert '60 minute' in json.loads(output.out)['error']
        assert not (path / 'facts.json').exists()
        assert not (path / 'final.xyz').exists()
        journal = [json.loads(line) for line in (path.parent.parent / 'journal.jsonl').read_text().splitlines()]
        assert not any(row['action'] == 'facts' for row in journal)
    else:
        assert json.loads(output.out)['facts']['status'] == 'written'
        assert (path / 'facts.json').is_file()
