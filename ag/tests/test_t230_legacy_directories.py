"""Exercise a genuine old writer/Attempt against synthetic per-device history."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

import pytest

from ag import _pbs_legacy_directories as legacy, autonomy, autonomy_submission as accounting, config, study
from ag import _autonomy_store as disk
from ag import attempt, pbs_legacy_index, snapshot, state
from test_core import cfg, INPUT, seed_submission
from test_snapshot import Fake as SnapshotTransport


@pytest.fixture
def historical(cfg, monkeypatch, tmp_path):
    root = Path(cfg['local']['studies_root']) / 'water'
    source = tmp_path / 'water.gjf'
    source.write_text(INPUT)
    old = accounting.study_identity
    remounted = [False]

    def identity(path, *, apfs=False):
        obj = old(path)
        if remounted[0]:
            obj['study_device'] += 1
            if apfs:
                obj['apfs_directory_sha256'] = 'f' * 64
        return obj
    monkeypatch.setattr(accounting, 'study_identity', identity)
    study.init(cfg, root.name)
    data = attempt.prepare(cfg, method_basis='Synthetic test', study_name=root.name, template='gaussian',
                           input_path=source, tier='simple', walltime='00:30:00', label='sp')
    aid = data['attempt_id']
    target = attempt.find(cfg, aid)
    state.write(target, 'submitting')
    seed_submission(target)
    state.write(target, 'running')
    folders = []
    for _ in range(2):
        with autonomy.manual_write_guard(cfg, root.name, action='snapshot', attempt_ids=[aid]):
            receipt = snapshot.capture(cfg, target, SnapshotTransport(b'synthetic output'))
            folders.append(target / receipt['snapshot'])
    folder, later = folders
    state.write(target, 'finished')
    claims = sorted((Path.home() / '.config/ag/manual-writers').rglob('*.claim.json'),
                    key=lambda p: json.loads(p.read_bytes())['started_at'])
    bucket = claims[0].parent
    events = {root.parent: [(10, 0x100)], root: [(20, 0x100)], folder: [(42, 0x800)],
              folder / 'snapshot.json': [(43, 0x1000)], later: [(52, 0x800)],
              later / 'snapshot.json': [(53, 0x1000)]}
    for pos, claim in enumerate(claims):
        events[claim] = [(30 + 10 * pos, 0x100)]
        events[claim.with_name(claim.name.replace('.claim.', '.complete.'))] = [(35 + 10 * pos, 0x100)]
    ids = {p.stat().st_ino: p for p in (*events, bucket)}
    monkeypatch.setattr(legacy, 'volume_path', lambda fd: (str(ids[os.fstat(fd).st_ino]).lstrip('/'),
                                                          os.fstat(fd).st_dev))
    monkeypatch.setattr(legacy._study_directory, 'apfs_object_digest', lambda fd, ino: f'{ino:064x}')
    monkeypatch.setattr(legacy._study_directory, '_attributes', lambda fd, *args:
                        ((b'v' * 16,) if args[-1] == '16s'
                         else (1, 2, ids[os.fstat(fd).st_ino].parent.stat().st_ino, 1, 2)))
    monkeypatch.setattr(config, 'ssh_identity', lambda _: ('fixture', 22, 'fixture'))

    class Kernel:
        def read_ids(self, scope, dev, lo, hi, files, *, targets):
            return [(str(path).lstrip('/'), i, flags) for path, rows in events.items()
                    if files.get(str(path).lstrip('/')) == path.stat().st_ino
                    for i, flags in rows if lo <= i <= hi]

        def read(self, scope, dev, start, end, files, *, first_birth):
            return self.read_ids(scope, dev, 0, 100, files, targets=())

        def get_id(self, dev, seconds):
            import time
            return 1 if seconds < time.time() else 100

    monkeypatch.setattr(legacy, '_DarwinEvents', Kernel)
    remounted[0] = True
    index = Path.home() / '.config/ag/pbs-legacy-event-index.json'
    hints = {sha256(os.fsencode(p)).hexdigest(): [i for i, _ in rows] for p, rows in events.items()}
    return root, index, events, hints, folder


@pytest.mark.parametrize('case', ['valid', 'absent', 'foreign-event', 'lost-snapshot', 'conflicting-bytes', 'foreign-volume',
                                  'changed-parent-entry', 'hand-entered-device', 'split-window', 'overlap',
                                  'cropped-bad-original', 'post-close-metadata'])
def test_index_never_supplies_directory_identity(cfg, historical, monkeypatch, case):
    root, index, observed, hints, folder = historical
    value = dict(schema='ag-pbs-directory-event-index/1', events=hints)
    if case == 'foreign-event':
        hints[sha256(os.fsencode(root.parent)).hexdigest()] = [99]
    elif case == 'lost-snapshot':
        observed.pop(folder / 'snapshot.json')
    elif case == 'split-window':
        target = max(folder.parent.iterdir()) / 'snapshot.json'
        observed[target] = [(44, 0x1000)]
        hints[sha256(os.fsencode(target)).hexdigest()] = [44]
    elif case == 'overlap':
        source, = [p for p, rows in observed.items() if rows == [(50, 0x100)]]
        observed[source] = [(41, 0x100)]
        hints[sha256(os.fsencode(source)).hexdigest()] = [41]
    elif case == 'conflicting-bytes':
        (folder / json.loads((folder / 'snapshot.json').read_bytes())['file']).write_bytes(b'changed')
    elif case == 'cropped-bad-original':
        (folder / json.loads((folder / 'snapshot.json').read_bytes())['file']).write_bytes(b'changed')
        hints.pop(sha256(os.fsencode(folder / 'snapshot.json')).hexdigest())
    elif case == 'post-close-metadata':
        meta = folder / 'snapshot.json'
        meta.write_bytes(meta.read_bytes())
    elif case == 'changed-parent-entry':
        monkeypatch.setattr(legacy._study_directory, '_attributes', lambda *a: (1, 2, 9, 4, 5))
    elif case == 'hand-entered-device':
        value['device_map'] = {'42': 43}
    elif case == 'foreign-volume':
        bucket = next((Path.home() / '.config/ag/manual-writers').iterdir())
        foreign = {bucket.stat().st_ino, *(p.stat().st_ino for p in bucket.iterdir())}
        volume = legacy.LegacyDirectories._volume
        def actual_volume(self, fd):
            if os.fstat(fd).st_ino in foreign:
                return os.fstat(fd).st_dev, b'x' * 16
            return volume(self, fd)
        monkeypatch.setattr(legacy.LegacyDirectories, '_volume', actual_volume)
    if case != 'absent':
        index.write_bytes(disk.encode(value))
    if case == 'valid':
        assert accounting.read_pbs_reservations(cfg)['placements'] == []
        with pytest.raises(ValueError, match='binding changed'):
            with autonomy.manual_write_guard(cfg, root.name, action='prepare'):
                pytest.fail('A recovered PBS read granted write permission')
    else:
        with pytest.raises(ValueError):
            accounting.read_pbs_reservations(cfg)


@pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin exclusive-rename publication')
def test_index_is_derived_and_installed_only_for_the_verified_bytes(cfg, historical):
    root, index, events, hints, folder = historical
    initial = pbs_legacy_index.derive(cfg)
    assert not index.exists() and not initial['installed']
    with pytest.raises(ValueError, match='reviewed digest'):
        pbs_legacy_index.derive(cfg, install='0' * 64)
    assert not index.exists()
    assert pbs_legacy_index.derive(cfg, install=initial['sha256'])['installed']
    inode = index.stat().st_ino
    assert pbs_legacy_index.derive(cfg, install=initial['sha256'])['installed']
    assert index.stat().st_ino == inode
    assert json.loads(index.read_bytes())['events'] == hints
    index.write_bytes(b'local original')
    with pytest.raises(ValueError, match='Different existing'):
        pbs_legacy_index.derive(cfg, install=initial['sha256'])
    assert index.read_bytes() == b'local original'


@pytest.mark.parametrize('active', [False, True])
def test_current_writer_is_audited_independently_of_the_historical_group(cfg, historical, active):
    import fcntl
    import time
    root, index, _, hints, _ = historical
    index.write_bytes(disk.encode({'schema': 'ag-pbs-directory-event-index/1', 'events': hints}))
    identity = accounting.study_identity(root)
    bucket = Path.home() / '.config/ag/manual-writers' / identity['study_key']
    writer = uuid4().hex
    raw = disk.encode(dict(schema='ag-manual-writer/2', writer_id=writer, started_at=time.time(),
                           study_path=str(root), action='status', attempt_ids=[], **identity))
    file = bucket / (writer + '.claim.json')
    file.write_bytes(raw)
    with file.open('rb') as handle:
        if active:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:
            completion = dict(schema='ag-manual-writer-complete/1', writer_id=writer,
                              claim_sha256=sha256(raw).hexdigest(), finished_at=time.time())
            (bucket / (writer + '.complete.json')).write_bytes(disk.encode(completion))
        assert accounting.read_pbs_reservations(cfg)['placements'] == []


def test_index_reads_more_files_than_descriptor_limit(tmp_path, monkeypatch):
    import resource
    files = [tmp_path / str(i) for i in range(260)]
    for p in files:
        p.write_bytes(b'synthetic')
    by_inode = {p.stat().st_ino: p for p in [tmp_path, *files]}
    device = tmp_path.stat().st_dev
    def location(fd):
        return str(by_inode[os.fstat(fd).st_ino]).lstrip('/'), device
    monkeypatch.setattr(legacy, 'volume_path', location)
    class Kernel:
        def read_ids(self, scope, device, lo, hi, files, *, targets):
            return [(name, i, 0x100) for name, i in targets]
    with accounting._capture_reads() as reads:
        verifier = legacy.LegacyDirectories.__new__(legacy.LegacyDirectories)
        verifier.lookup = {sha256(os.fsencode(p)).hexdigest(): [i + 10] for i, p in enumerate(files)}
        verifier.collect, verifier.reads, verifier.system = False, reads, Kernel()
        verifier.stream_volume = (device, bytes([1]) * 16)
        monkeypatch.setattr(verifier, '_volume', lambda fd: verifier.stream_volume)
        original = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(original[0], 256), original[1]))
        try:
            result = verifier._events(tmp_path, files)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, original)
    assert len(result) == len(files)
