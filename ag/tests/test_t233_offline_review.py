"""Local mode exports must not enter the machine's PBS writer inventory."""
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from ag import _offline_mode_review as offline, cli, config, mode_review, node_targeting, submit
from test_autonomy import env, running
from test_core import Fake, allow, cfg, prepared
from test_local_review_writes import evidence
from test_mode_review import study, synthetic_log
from test_t216_reservation_audit import snapshot


def export(root, aid, *options):
    return cli.main(['mode-review', aid, '--study', str(root), '--pair', '1-2', '--json', *options])


def reviews():
    return Path.home() / '.local/state/ag-offline/mode-reviews'


@pytest.mark.parametrize('destination', ['study', 'offline'])
def test_seven_exports_and_unobserved_pbs_job(cfg, prepared, tmp_path, monkeypatch, capsys, destination):
    path, manifest = prepared
    source = tmp_path / 'acceptance-studies' / path.parent.parent.name
    shutil.copytree(path.parent.parent, source)
    (source / 'attempts' / path.name / 'outputs' / 'water.log').write_text(synthetic_log())
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    allow(monkeypatch)
    assert submit.submit(cfg, [path.name], Fake(cfg))[0]['state'] == 'submitted'
    entry = config.select_cluster(cfg, 'default')

    def unobserved():
        return node_targeting._unobserved_cores(entry, {}, 'fixture', None, set())

    assert unobserved() == manifest['cores']
    machine = Path.home() / '.config/ag'
    writer_registry = machine / 'manual-writers'
    baseline = snapshot(machine)
    production = snapshot(path.parent.parent)
    source_before = snapshot(source)
    old_groups = set(writer_registry.iterdir())
    receipts = set()
    for i in range(7):
        options = ['--out', f'analyses/review-{i}.json'] if destination == 'study' else ['--offline']
        assert export(source, path.name, *options) == 0
        result = json.loads(capsys.readouterr().out)
        if destination == 'offline':
            directory = Path(result['offline_review'])
            assert directory.parent == reviews() and directory not in receipts
            receipts.add(directory)
    assert snapshot(path.parent.parent) == production
    if destination == 'offline':
        assert len(receipts) == 7 and snapshot(source) == source_before and snapshot(machine) == baseline
    else:
        new_group, = set(writer_registry.iterdir()) - old_groups
        assert len(list(new_group.glob('*.claim.json'))) == len(list(new_group.glob('*.complete.json'))) == 7
    source.parent.rename(source.parent.with_name('moved-studies'))
    if destination == 'offline':
        assert unobserved() == manifest['cores']
        for directory in receipts:
            assert json.loads((directory / 'registration.json').read_bytes())['source_study'] == str(source)
    else:
        with pytest.raises((ValueError, OSError)):
            unobserved()


def test_same_science_and_self_contained_registration(study, capsys, monkeypatch):
    root, attempt = study
    assert export(root, attempt.name, '--out', 'analyses/report.json') == 0
    formal = json.loads(capsys.readouterr().out)
    before = snapshot(root)
    machine = snapshot(Path.home() / '.config')
    monkeypatch.setattr(cli, 'load_config', lambda **kw: pytest.fail('offline review loaded config'))
    assert export(root, attempt.name, '--offline') == 0
    output = json.loads(capsys.readouterr().out)
    directory = Path(output.pop('offline_review'))
    assert output == formal
    record = json.loads((directory / 'registration.json').read_bytes())
    assert record['source_study'] == str(root) and record['attempt'] == attempt.name
    assert record['review_id'] == directory.name and record['schema'] == 'ag-offline-mode-review/1'
    assert record['manifest_sha256'] == sha256((attempt / 'manifest.json').read_bytes()).hexdigest()
    assert set(record['artifacts']) == {'report.json', 'report.plus.xyz', 'report.minus.xyz'}
    for name, digest in record['artifacts'].items():
        payload = (directory / name).read_bytes()
        assert sha256(payload).hexdigest() == digest
        assert payload == (root / 'analyses' / name).read_bytes()
    assert set(p.name for p in directory.iterdir()) == set(record['artifacts']) | {'registration.json'}
    assert snapshot(root) == before and snapshot(Path.home() / '.config') == machine


def test_active_study_is_read_only_and_owner_options_never_select_offline(evidence, env, capsys):
    _, root, attempt, _ = evidence
    plan, owner = running(env)
    assert export(root, attempt.name, '--out', 'analyses/locked.json') != 0
    capsys.readouterr()
    before = snapshot(root)
    machine = snapshot(Path.home() / '.config')
    with pytest.raises(SystemExit):
        export(root, attempt.name, '--offline', '--out', 'analyses/locked.json')
    for flags in (['--run', owner['run_id']], ['--token', owner['token']], ['--plan-sha256', plan['sha256']]):
        assert export(root, attempt.name, '--offline', *flags) != 0
    assert not reviews().exists()
    assert export(root, attempt.name, '--offline') == 0
    assert len(list(reviews().glob('*/registration.json'))) == 1
    assert snapshot(root) == before and snapshot(Path.home() / '.config') == machine


@pytest.mark.parametrize('damage', ['link', 'source-overlap', 'other-study', 'ledger', 'id-collision'])
def test_unsafe_destination_rejected_before_publication(study, tmp_path, monkeypatch, damage):
    root, attempt = study
    if damage == 'link':
        reviews().parent.mkdir(parents=True)
        reviews().symlink_to(root / 'analyses', target_is_directory=True)
    elif damage == 'source-overlap':
        monkeypatch.setenv('HOME', str(root))
    elif damage == 'other-study':
        (Path.home() / '.local' / 'attempts').mkdir(parents=True)
    elif damage == 'ledger':
        home = tmp_path / 'other' / '.config' / 'ag'
        home.mkdir(parents=True)
        monkeypatch.setenv('HOME', str(home))
    else:
        previous = offline.uuid4()
        monkeypatch.setattr(offline, 'uuid4', lambda: previous)
        directory = reviews() / previous.hex
        directory.mkdir(parents=True)
        (directory / 'registration.json').write_bytes(b'prior')
    before = snapshot(root)
    assert export(root, attempt.name, '--offline') != 0
    assert snapshot(root) == before
    if damage == 'id-collision':
        assert list(directory.iterdir()) == [directory / 'registration.json']
        assert (directory / 'registration.json').read_bytes() == b'prior'


@pytest.mark.parametrize('damage', ['source-before-render-end', 'source-after-staging', 'output-changed',
                                    'output-replaced', 'output-collision', 'directory-swap'])
def test_changes_leave_no_offline_registration(study, monkeypatch, damage):
    root, attempt = study
    source = attempt / 'outputs/job.log'
    original = offline.disk.Store.exclusive
    parse = mode_review.read_modes
    if damage == 'source-before-render-end':
        def replace_source(*args):
            result = parse(*args)
            source.rename(source.with_suffix('.old'))
            source.write_bytes(source.with_suffix('.old').read_bytes())
            return result
        monkeypatch.setattr(mode_review, 'read_modes', replace_source)
    else:
        def change(store, name, content, **kwargs):
            directory, = reviews().iterdir()
            target = directory / 'report.plus.xyz'
            if damage == 'output-collision' and name == target.name:
                target.write_bytes(b'concurrent member')
            original(store, name, content, **kwargs)
            if name != '.registration-stage':
                return
            if damage == 'source-after-staging':
                source.write_bytes(source.read_bytes() + b' ')
            elif damage == 'output-changed':
                target.write_bytes(b'wrong bytes')
            elif damage == 'output-replaced':
                moved = target.with_name('old-geometry')
                target.rename(moved)
                target.write_bytes(moved.read_bytes())
            elif damage == 'directory-swap':
                directory.rename(directory.with_name('original'))
                directory.symlink_to(root / 'analyses', target_is_directory=True)
        monkeypatch.setattr(offline.disk.Store, 'exclusive', change)
    assert export(root, attempt.name, '--offline') != 0
    assert not list(reviews().glob('*/registration.json')) and not list((root / 'analyses').iterdir())
    if damage == 'output-collision':
        held, = reviews().glob('*/report.plus.xyz')
        assert held.read_bytes() == b'concurrent member'


def test_existing_private_directory_replaced_with_a_study_before_creation(study, tmp_path, monkeypatch):
    root, attempt = study
    private = reviews().parent
    private.mkdir(parents=True)
    other = tmp_path / 'active-study'
    (other / 'attempts').mkdir(parents=True)
    previous = snapshot(other)
    directory = offline.disk.directory

    def replace_at_open(path):
        fd = directory(path)
        if path == Path.home() and other.exists():
            private.rename(private.with_name('original'))
            other.rename(private)
        return fd

    monkeypatch.setattr(offline.disk, 'directory', replace_at_open)
    assert export(root, attempt.name, '--offline') != 0
    assert snapshot(private) == previous
