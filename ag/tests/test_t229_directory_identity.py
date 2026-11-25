"""Exercise original records through the PBS reader, with synthetic mount facts."""
from pathlib import Path

import pytest

from ag import autonomy, autonomy_submission as records, config, study
from test_autonomy_submission import install_owned, selector
from test_core import cfg, prepared
from test_t216_reservation_audit import snapshot


@pytest.fixture
def mounts(monkeypatch):
    # Only the simulated kernel values vary. Record production, encoding,
    # ownership digests, validation and the directory walk remain real.
    devices = {}
    digests = {}
    original = records.study_identity

    def identity(path, *, apfs=False):
        result = original(path)
        result['study_device'] += devices.get(Path(path), 0)
        digest = digests.get(Path(path), 'a' * 64)
        if apfs and digest is not None:
            result['apfs_directory_sha256'] = digest
        return result

    monkeypatch.setattr(records, 'study_identity', identity)
    monkeypatch.setattr(records._study_directory, 'apfs_object_digest', lambda fd, ino: f'{ino:064x}')
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))
    return devices, digests


@pytest.mark.parametrize('failure', [None, 'legacy', 'mixed', 'different-volume', 'missing-volume',
                                     'different-inode', 'redirect', 'scan-race'])
def test_two_historical_devices_require_every_original_claim(cfg, mounts, tmp_path, monkeypatch, failure):
    devices, digests = mounts
    roots = []
    for n, name in enumerate(('first', 'second'), start=1):
        root = Path(cfg['local']['studies_root']) / name
        study.init(cfg, name)
        if n == 2 and failure in ('legacy', 'mixed'):
            digests[root] = None
        devices[root] = n
        with autonomy.manual_write_guard(cfg, name, action='prepare'):
            pass
        if failure == 'mixed' and n == 2:
            digests[root] = 'a' * 64
            with autonomy.manual_write_guard(cfg, name, action='prepare'):
                pass
        devices[root] = 0
        roots.append(root)
    root = roots[-1]
    if failure == 'different-volume':
        digests[root] = 'b' * 64
    elif failure == 'missing-volume':
        digests[root] = None
    elif failure in ('different-inode', 'redirect'):
        root.rename(root.with_name('original'))
        if failure == 'redirect':
            root.symlink_to(root.with_name('original'), target_is_directory=True)
        else:
            study.init(cfg, root.name)
    elif failure == 'scan-race':
        enumerate_roots = records._study_paths
        def change(*args, **kwargs):
            result = enumerate_roots(*args, **kwargs)
            devices[root] += 1
            return result
        monkeypatch.setattr(records, '_study_paths', change)
    before = snapshot(Path.home())
    if failure is None:
        assert records.read_pbs_reservations(cfg)['placements'] == []
        with pytest.raises(ValueError, match='binding changed'):
            with autonomy.manual_write_guard(cfg, root.name, action='cancel'):
                pytest.fail('Historical directory was allowed to acquire a writer')
    else:
        with pytest.raises((OSError, ValueError)):
            records.read_pbs_reservations(cfg)
    assert snapshot(Path.home()) == before


def test_remounted_owned_reservation_is_only_read_for_pbs(cfg, mounts, prepared, selector, monkeypatch):
    devices, digests = mounts
    path, _ = prepared
    root = path.parent.parent
    saved, current = install_owned(cfg, path, selector[0])
    # install_owned constructs the exact immutable evidence and consumption
    # state. Isolate the state loader just as the existing ownership tests do.
    monkeypatch.setattr(records, '_load_state', lambda *args, **kwargs: current)
    devices[root] = 1
    before = snapshot(Path.home())
    placement, = records.read_pbs_reservations(cfg)['placements']
    assert placement['record_sha256'] == saved['sha256'] and placement['cores'] == 8
    with pytest.raises(ValueError, match='moved, copied or replaced'):
        records.read_reservations(cfg)
    with pytest.raises(ValueError, match='moved, copied or replaced'):
        records.verified_authorization(path, saved['authorization'])
    assert snapshot(Path.home()) == before


@pytest.mark.parametrize('mutation', ['sibling', 'attempt', 'claim', 'status', 'writer-bytes'])
def test_pbs_rechecks_all_members_and_accounting_reads(cfg, prepared, selector, monkeypatch, mutation):
    path, _ = prepared
    scan = records._manual_accounting

    def classify(*args, **kwargs):
        result = scan(*args, **kwargs)
        if mutation == 'sibling':
            study.init(cfg, 'arriving')
        elif mutation == 'attempt':
            (path.parent / 'arriving').mkdir()
        elif mutation == 'claim':
            (path / '.submit-claim').write_bytes(b'Claimed permanently; never resubmit this Attempt.\n')
        elif mutation == 'status':
            status = path / 'status.json'
            status.write_bytes(status.read_bytes() + b'\n')
        else:
            source, = (Path.home() / '.config/ag/manual-writers').rglob('*.claim.json')
            source.write_bytes(source.read_bytes() + b' ')
        return result

    monkeypatch.setattr(records, '_manual_accounting', classify)
    with pytest.raises(ValueError, match='changed'):
        records.read_pbs_reservations(cfg)


def test_legacy_originals_are_not_endorsed_later(cfg, mounts):
    devices, digests = mounts
    root = Path(cfg['local']['studies_root']) / 'original'
    study.init(cfg, root.name)
    digests[root] = None
    records._register_study(root)
    with autonomy.manual_write_guard(cfg, root.name, action='prepare'):
        pass
    before = snapshot(Path.home())
    digests[root] = 'a' * 64
    records._register_study(root)
    records.read_pbs_reservations(cfg)
    assert snapshot(Path.home()) == before
    devices[root] = 1
    with pytest.raises(ValueError, match='binding changed'):
        records.read_pbs_reservations(cfg)


def test_rechecks_directory_used_for_registry_enumeration(cfg, prepared, selector, monkeypatch):
    registry = Path.home() / '.config/ag/manual-writers'
    complete = registry.with_name('original-registry')
    registry.rename(complete)
    registry.mkdir()
    read_directory = records._EvidenceReads.directory

    def replace(self, path, *args):
        if path == registry and complete.exists():
            registry.rename(registry.with_name('old-registry'))
            complete.rename(registry)
        return read_directory(self, path, *args)

    monkeypatch.setattr(records._EvidenceReads, 'directory', replace)
    with pytest.raises(ValueError, match='directory changed'):
        records.read_pbs_reservations(cfg)
