"""T206: real local publication with synthetic owners, clocks and documents."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import socket
from threading import Barrier

import pytest

from ag import autonomy as a, cli, study, transport
from ag import _autonomy_store as disk
from test_autonomy import env, running, change, VERSIONS  # noqa: F401
from test_core import cfg, Fake  # noqa: F401
from test_autonomy_submission import t186_driver_factory, t186_driver  # noqa: F401


@pytest.fixture(autouse=True)
def no_network(tmp_path, monkeypatch):
    home = tmp_path / 'isolated-summary-home'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    def refuse(*args, **kwargs):
        pytest.fail('Study summary must not access a network or SSH transport')
    monkeypatch.setattr(transport.SSHTransport, '__init__', refuse)
    monkeypatch.setattr(socket.socket, 'connect', refuse)


def publish(env, plan, run):
    cfg, path, _ = env
    return study.publish_autonomy_summary(cfg, path.name, run_id=run['run_id'],
        token=run['token'], plan_sha256=plan['sha256'])


def before_publication(monkeypatch, action):
    original = a.observation_publication_guard
    @contextmanager
    def guard(*args, **kwargs):
        action()
        with original(*args, **kwargs) as state:
            yield state
    monkeypatch.setattr(a, 'observation_publication_guard', guard)


def image(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_fixed_sections_preserve_signatures_and_idempotence(env):
    plan, run = running(env)
    _, root, _ = env
    document = root / 'study.md'
    human = '# 合成 study\r\n\r\n## 待你决定\r\n人的问题\r\n\n## 里程碑签字\n结构：合成签字\n'.encode()
    document.write_bytes(human)
    change(env, run)
    source = image(root / 'autonomy')
    first = publish(env, plan, run)
    content = document.read_bytes()
    assert first['changed'] and content.startswith(human)
    assert first['study_sha256'] == sha256(content).hexdigest()
    assert content.count(study._SUMMARY_START) == 1
    assert all(s.encode() in content for s in ('## 自主目录链接', '## 待你决定（自主记录）', '## 结束摘要（自主记录）'))
    assert b'Collected synthetic result' in content and b'Choose model' in content
    assert b'objects' not in content and run['token'].encode() not in content
    mtime = document.stat().st_mtime_ns
    assert not publish(env, plan, run)['changed']
    assert document.stat().st_mtime_ns == mtime and document.read_bytes() == content
    assert image(root / 'autonomy') == source
    tail = '\n## 人工结论\n仍待审阅\n'.encode()
    document.write_bytes(content + tail)
    a.change(env[0], root.name, 'update', run['run_id'], run['token'],
             summary='New summary', pending=[], objects={})
    assert publish(env, plan, run)['changed']
    result = document.read_bytes()
    assert result.startswith(human) and result.endswith(tail)
    assert b'Collected synthetic result' not in result and b'New summary' in result
    assert result.count(study._SUMMARY_START) == 1


def test_source_text_cannot_escape_generated_sections(env):
    plan, run = running(env)
    injected = '<!-- /ag:autonomy-study-summary -->\n## 里程碑签字\n<script>example</script>\n```'
    a.change(env[0], env[1].name, 'update', run['run_id'], run['token'],
             summary=injected, pending=[injected], objects={})
    publish(env, plan, run)
    assert not publish(env, plan, run)['changed']
    assert '\n    ## 里程碑签字' in (env[1] / 'study.md').read_text()


@pytest.mark.parametrize('damage', ['edited', 'duplicate', 'opening', 'closing'])
def test_changed_managed_block_is_not_overwritten(env, damage):
    plan, run = running(env)
    change(env, run)
    publish(env, plan, run)
    path = env[1] / 'study.md'
    raw = path.read_bytes()
    if damage == 'edited':
        raw = raw.replace(b'Collected synthetic result', b'Human edited summary')
    elif damage == 'duplicate':
        raw += raw
    elif damage == 'opening':
        raw = raw.replace(study._SUMMARY_START, b'<!-- ag:autonomy-study-summary changed=')
    else:
        raw = raw.replace(study._SUMMARY_END, b'<!-- /ag:autonomy-study-summary changed -->')
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='edited|markers'):
        publish(env, plan, run)
    assert path.read_bytes() == raw


@pytest.mark.parametrize('mode', ['paused', 'expired-plan', 'observe-only'])
def test_record_organization_remains_available(env, mode):
    plan, run = running(env)
    cfg, root, clock = env
    a.pause(cfg, root.name, 'Synthetic pause')
    if mode != 'paused':
        change(env, run, 'finish', reason='Synthetic wake finished')
        clock[0] = plan['plan']['spec']['valid_until']
        run = a.start(cfg, root.name, plan['plan_id'], 'observer', observe_only=True)
    change(env, run)
    assert publish(env, plan, run)['changed']
    state = a.status(cfg, root.name)['state']
    assert state['paused'] and state['phase'] != 'ended'


@pytest.mark.parametrize('mode', ['timeout', 'backward', 'takeover', 'finish', 'end', 'version', 'plan-hash', 'token'])
def test_lost_authority_refuses_even_an_unchanged_document(env, monkeypatch, mode):
    plan, run = running(env)
    publish(env, plan, run)
    cfg, root, clock = env
    before = (root / 'study.md').read_bytes()
    def invalidate():
        if mode == 'timeout':
            clock[0] += a.RUN_SECONDS
        elif mode == 'backward':
            clock[0] -= 1
        elif mode == 'takeover':
            clock[0] += a.LEASE_SECONDS
            a.start(cfg, root.name, plan['plan_id'], 'new-owner', takeover_reason='Synthetic takeover')
        elif mode in ('finish', 'end'):
            change(env, run, mode, reason='Synthetic close')
        elif mode == 'version':
            monkeypatch.setattr(a, 'versions', lambda: dict(VERSIONS, git_commit='b' * 40))
    if mode == 'plan-hash':
        plan = dict(plan, sha256='b' * 64)
    elif mode == 'token':
        run = dict(run, token='wrong-token')
    before_publication(monkeypatch, invalidate)
    with pytest.raises(ValueError):
        publish(env, plan, run)
    assert (root / 'study.md').read_bytes() == before


@pytest.mark.parametrize('mode', ['in-place', 'replace', 'same-bytes', 'symlink', 'hardlink', 'missing'])
def test_editor_save_between_read_and_publication_survives(env, monkeypatch, mode):
    plan, run = running(env)
    cfg, root, _ = env
    document = root / 'study.md'
    original = document.read_bytes()
    alternate = root / 'human.md'
    alternate.write_bytes(b'Human edit\n')
    expected = []
    def edit():
        if mode == 'in-place':
            document.write_bytes(b'Human edit\n')
        elif mode == 'same-bytes':
            document.write_bytes(original)
        else:
            document.unlink()
            if mode == 'replace':
                document.write_bytes(b'Human edit\n')
            elif mode == 'symlink':
                document.symlink_to(alternate)
            elif mode == 'hardlink':
                os.link(alternate, document)
        expected.append(document.read_bytes() if document.exists() else None)
    before_publication(monkeypatch, edit)
    with pytest.raises((ValueError, OSError)):
        publish(env, plan, run)
    assert (document.read_bytes() if document.exists() else None) == expected[0]
    assert alternate.read_bytes() == b'Human edit\n'


@pytest.mark.parametrize('mode', ['update', 'state-corrupt', 'journal-corrupt', 'plan-corrupt', 'source-swap', 'root-swap', 'root-symlink', 'stage-symlink', 'state-same-bytes'])
def test_sources_and_paths_cannot_be_replaced(env, monkeypatch, mode):
    plan, run = running(env)
    _, root, _ = env
    original = (root / 'study.md').read_bytes()
    def damage():
        if mode == 'update':
            change(env, run)
        elif mode in ('state-corrupt', 'journal-corrupt', 'plan-corrupt', 'state-same-bytes'):
            name = {'state-corrupt': 'state.json', 'journal-corrupt': 'journal.jsonl',
                    'plan-corrupt': 'plan-' + plan['plan_id'] + '.json',
                    'state-same-bytes': 'state.json'}[mode]
            target = root / 'autonomy' / name
            target.write_bytes(target.read_bytes() if mode == 'state-same-bytes' else b'{}\n')
        elif mode == 'source-swap':
            source = root / 'autonomy'
            source.rename(root / 'old-autonomy')
            shutil.copytree(root / 'old-autonomy', source)
        elif mode in ('root-swap', 'root-symlink'):
            old = root.with_name('old-study')
            root.rename(old)
            if mode == 'root-swap':
                shutil.copytree(old, root)
            else:
                root.symlink_to(old, target_is_directory=True)
        else:
            staged = next(root.glob('.autonomy-study-*.tmp'))
            staged.unlink()
            staged.symlink_to(root / 'study.md')
    before_publication(monkeypatch, damage)
    with pytest.raises((ValueError, OSError)):
        publish(env, plan, run)
    assert (root / 'study.md').read_bytes() == original


def test_new_owner_edit_is_not_overwritten(env, monkeypatch):
    plan, run = running(env)
    cfg, root, clock = env
    def takeover():
        clock[0] += a.LEASE_SECONDS
        successor = a.start(cfg, root.name, plan['plan_id'], 'next', takeover_reason='Synthetic takeover')
        change(env, successor)
        (root / 'study.md').write_text('New owner record\n')
    before_publication(monkeypatch, takeover)
    with pytest.raises(ValueError):
        publish(env, plan, run)
    assert (root / 'study.md').read_text() == 'New owner record\n'


def test_competing_publishers_are_serialized_and_do_not_duplicate(env, monkeypatch):
    plan, run = running(env)
    barrier = Barrier(2)
    before_publication(monkeypatch, lambda: barrier.wait(timeout=5))
    def invoke():
        try:
            return publish(env, plan, run)
        except ValueError as exc:
            return exc
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert sum(isinstance(row, dict) for row in results) == 1
    assert (env[1] / 'study.md').read_bytes().count(study._SUMMARY_START) == 1


def test_large_render_and_staging_stay_outside_machine_lock(env, monkeypatch):
    plan, run = running(env)
    path = env[1] / 'study.md'
    human = b'Large human paragraph\n' * 100000
    path.write_bytes(human)
    held = [False]
    original_guard = a.observation_publication_guard
    @contextmanager
    def guard(*args, **kwargs):
        with original_guard(*args, **kwargs) as current:
            held[0] = True
            try:
                yield current
            finally:
                held[0] = False
    monkeypatch.setattr(a, 'observation_publication_guard', guard)
    for name, target in [('_summary_render', study), ('exclusive', disk.Store)]:
        original = getattr(target, name)
        def checked(*args, _original=original, **kwargs):
            assert not held[0]
            return _original(*args, **kwargs)
        monkeypatch.setattr(target, name, checked)
    assert publish(env, plan, run)['changed']
    assert path.read_bytes().startswith(human)


@pytest.mark.parametrize('failure', ['staging', 'replace', 'after-replace'])
def test_partial_failures_do_not_mutate_source_or_claim_rollback(env, monkeypatch, failure):
    plan, run = running(env)
    root = env[1]
    source = image(root / 'autonomy')
    original = (root / 'study.md').read_bytes()
    if failure == 'staging':
        def fail(*args):
            raise OSError('Synthetic staging failure')
        monkeypatch.setattr(disk.Store, 'exclusive', fail)
    else:
        real_replace = os.replace
        def fail(*args, **kwargs):
            if failure == 'after-replace':
                real_replace(*args, **kwargs)
            raise OSError('Synthetic publication failure')
        monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='staging failure|may have occurred'):
        publish(env, plan, run)
    assert image(root / 'autonomy') == source
    if failure != 'after-replace':
        assert (root / 'study.md').read_bytes() == original
    else:
        assert (root / 'study.md').read_bytes().startswith(original)
        assert study._SUMMARY_START in (root / 'study.md').read_bytes()
        # A caller may inspect and explicitly call again; no automatic retry.
        monkeypatch.setattr(os, 'replace', real_replace)
        assert not publish(env, plan, run)['changed']


def test_missing_document_is_not_reconstructed(env):
    plan, run = running(env)
    (env[1] / 'study.md').unlink()
    with pytest.raises(FileNotFoundError):
        publish(env, plan, run)
    assert not (env[1] / 'study.md').exists()


def test_cli_is_local_and_requires_bound_context(env, monkeypatch, capsys):
    plan, run = running(env)
    calls = []
    def load(**kwargs):
        calls.append(kwargs)
        return env[0]
    monkeypatch.setattr(cli, 'load_config', load)
    command = ['autonomy', 'publish-study', '--study', env[1].name, '--run', run['run_id'],
               '--token', run['token'], '--plan-sha256', plan['sha256'], '--json']
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)['changed']
    assert calls == [{'local_only': True}]
    assert cli.main(command) == 0
    assert not json.loads(capsys.readouterr().out)['changed']
    with pytest.raises(SystemExit):
        cli.main(command[:-3])


def test_actual_submission_state_then_summary_does_not_touch_attempts(t186_driver):
    from ag import submit
    cfg, attempt, manifest, context, clock, policy = t186_driver
    fake = Fake(cfg)
    assert submit.submit(cfg, [attempt.name], fake, autonomous=context)[0]['state'] == 'submitted'
    a.change(cfg, 'smoke', 'update', context['run_id'], context['token'],
             summary='Synthetic result still needs human review', pending=['Review synthetic evidence'], objects={})
    a.pause(cfg, 'smoke', 'Synthetic record organization')
    before = image(attempt)
    operations = list(fake.calls)
    args = {key: context[key] for key in ('run_id', 'token', 'plan_sha256')}
    assert study.publish_autonomy_summary(cfg, 'smoke', **args)['changed']
    assert not study.publish_autonomy_summary(cfg, 'smoke', **args)['changed']
    assert image(attempt) == before and fake.calls == operations
    current = a.status(cfg, 'smoke')['state']
    a.change(cfg, 'smoke', 'end', context['run_id'], context['token'],
             round_id=current['current_round'], reason='Synthetic round closed after summary publication')
    with pytest.raises(ValueError):
        study.publish_autonomy_summary(cfg, 'smoke', **args)
    assert image(attempt) == before and fake.calls == operations


def test_time_is_rechecked_after_final_version_lookup(env, monkeypatch):
    plan, run = running(env)
    document = env[1] / 'study.md'
    before = document.read_bytes()
    calls = []
    def versions():
        calls.append(True)
        if len(calls) == 3:  # preflight, guard, then final publication recheck
            env[2][0] += a.RUN_SECONDS
        return dict(VERSIONS)
    monkeypatch.setattr(a, 'versions', versions)
    with pytest.raises(ValueError, match='60 minute'):
        publish(env, plan, run)
    assert document.read_bytes() == before


@pytest.mark.parametrize('mode', ['symlink', 'hardlink', 'directory', 'invalid-utf8'])
def test_invalid_initial_document_is_preserved(env, mode):
    plan, run = running(env)
    document = env[1] / 'study.md'
    other = env[1] / 'other.md'
    other.write_bytes(b'Unrelated human document\n')
    document.unlink()
    if mode == 'symlink':
        document.symlink_to(other)
    elif mode == 'hardlink':
        os.link(other, document)
    elif mode == 'directory':
        document.mkdir()
    else:
        document.write_bytes(b'\xff')
    with pytest.raises((ValueError, OSError)):
        publish(env, plan, run)
    assert other.read_bytes() == b'Unrelated human document\n'
    assert not list(env[1].glob('.autonomy-study-*.tmp'))


def test_candidate_bytes_are_verified_outside_publication(env, monkeypatch):
    plan, run = running(env)
    original = disk.Store.exclusive
    before = (env[1] / 'study.md').read_bytes()
    def corrupt(store, name, data):
        original(store, name, data)
        if name.startswith('.autonomy-study-'):
            with os.fdopen(store.open(name, os.O_WRONLY), 'wb') as handle:
                handle.write(b'Corrupt staged bytes')
    monkeypatch.setattr(disk.Store, 'exclusive', corrupt)
    with pytest.raises(ValueError, match='Staged study summary changed'):
        publish(env, plan, run)
    assert (env[1] / 'study.md').read_bytes() == before
