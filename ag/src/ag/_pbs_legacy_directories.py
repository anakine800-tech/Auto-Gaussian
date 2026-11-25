"""Recover only PBS directory reads from original producer bytes and native file events.

The optional local index contains event numbers as lookup hints. No facts, device
translations, resource totals or approval decisions can be supplied by it.
"""
from contextlib import ExitStack
from hashlib import sha256
import os
from pathlib import Path
import stat

from ag import _autonomy_store as disk, _study_directory, approval, study
from ag._pbs_legacy_events import _DarwinEvents, volume_path


def _require(value):
    if not value:
        raise ValueError('Original PBS directory evidence is missing or inconsistent')


def _hash(raw):
    return sha256(raw).hexdigest()


class LegacyDirectories:
    def __init__(self, reads, *, collect=False):
        from ag.autonomy_submission import _json, _read_file
        self.reads = reads
        self.by_study = {}
        self.kernel_bounds = {}
        self.stream_volume = None
        self.lookup = None
        self.system = None
        self.collect = collect
        if collect:
            self.lookup = {}
            self.system = _DarwinEvents()
            return
        index = Path.home() / '.config/ag/pbs-legacy-event-index.json'
        try:
            raw = _read_file(index)
        except FileNotFoundError:
            return
        data = _json(raw)
        _require(isinstance(data, dict) and set(data) == {'schema', 'events'}
                 and data['schema'] == 'ag-pbs-directory-event-index/1' and isinstance(data['events'], dict))
        for key, ids in data['events'].items():
            _require(isinstance(key, str) and len(key) == 64 and isinstance(ids, list)
                     and ids and all(type(i) is int and 1 < i < 2**64 - 1 for i in ids)
                     and ids == sorted(set(ids)))
        self.lookup = data['events']
        self.system = _DarwinEvents()

    def matches(self, path, record, raw, source, live):
        if self.lookup is None or 'apfs_directory_sha256' not in live:
            return False
        group = (path, record['study_device'])
        if group not in self.by_study:
            try:
                self.by_study[group] = self._originals(path, live, record['study_device'])
            except (KeyError, IndexError, TypeError, UnicodeError) as exc:
                raise ValueError('Malformed historical PBS evidence') from exc
        accepted = self.by_study[group]
        return accepted.get(source) == (_hash(raw), record['study_device'])

    def _has(self, path):
        if self.collect:
            return os.path.lexists(path)
        return _hash(os.fsencode(path)) in self.lookup

    def _historical_time(self, path, event, stamp):
        # FSEvents dates bound archive segments; event order is always the
        # actual per-device ID. A recently rewritten artifact cannot date its
        # old kernel event by editing application timestamps or its birth time.
        device = path.stat().st_dev
        day = int(stamp // 86400)
        key = (device, day)
        if key not in self.kernel_bounds:
            self.kernel_bounds[key] = (self.system.get_id(device, (day - 1) * 86400),
                                       self.system.get_id(device, (day + 2) * 86400))
        lo, hi = self.kernel_bounds[key]
        _require(0 < lo < event <= hi)

    def _volume(self, fd):
        _require(not os.fstatvfs(fd).f_flag & os.ST_RDONLY)
        values = _study_directory._attributes(fd, 0, _study_directory._VOL_INFO | _study_directory._VOLUME_UUID, '16s')
        _require(values and len(values) == 1 and isinstance(values[0], bytes) and values[0] != bytes(16))
        return os.fstat(fd).st_dev, values[0]

    def _same_volume(self, fd):
        _require(self._volume(fd) == self.stream_volume)

    def _read_original(self, path):
        from ag.autonomy_submission import _fingerprint
        parent = disk.directory(path.parent)
        try:
            with os.fdopen(disk.Store(parent).open(path.name, os.O_RDONLY), 'rb') as handle:
                self._same_volume(handle.fileno())
                before = _fingerprint(os.fstat(handle.fileno()))
                raw = handle.read()
                self.reads.remember(path, before, _fingerprint(os.fstat(handle.fileno())), raw)
                return raw
        finally:
            os.close(parent)

    def _events(self, scope, paths):
        """Look up only exact current objects. Keep their fd observations in the T229 receipt."""
        result = {}
        native = {}
        ids_by_path = {}
        times = []
        with ExitStack() as stack:
            watch = disk.directory(scope)
            stack.callback(os.close, watch)
            self._same_volume(watch)
            watch_name, dev = volume_path(watch)
            _require(dev == self.stream_volume[0])
            for path in set(paths):
                ids = self.lookup.get(_hash(os.fsencode(path)))
                if ids is None and not self.collect:
                    continue
                with ExitStack() as opened:
                    if path == scope:
                        fd = watch
                    else:
                        parent = disk.directory(path.parent)
                        opened.callback(os.close, parent)
                        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                        opened.callback(os.close, fd)
                    self._same_volume(fd)
                    info = os.fstat(fd)
                    _require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    if self.collect:
                        times.extend((info.st_birthtime, info.st_ctime))
                    name, device = volume_path(fd)
                    _require(device == dev and (name == watch_name or name.startswith(watch_name + '/')))
                    if stat.S_ISDIR(info.st_mode):
                        self.reads.directory(path, fd)
                    else:
                        from ag.autonomy_submission import _fingerprint
                        stamp = _fingerprint(info)
                        self.reads.remember(path, stamp, stamp)
                native[name] = info.st_ino
                ids_by_path[name] = (path, ids)
            if not ids_by_path:
                return result
            if self.collect:
                one_birth = set(paths) == {scope}
                events = self.system.read(watch_name, dev, min(times) - 86400, max(times) + 86400,
                                          native, first_birth=one_birth)
            else:
                targets = {(name, i) for name, (_, ids) in ids_by_path.items() for i in ids}
                hints = [i for _, i in targets]
                events = self.system.read_ids(watch_name, dev, min(hints) - 1, max(hints), native, targets=targets)
        for name, event, flags in events:
            path, ids = ids_by_path[name]
            if self.collect or event in ids:
                result.setdefault(path, []).append((event, flags))
        # Positive events only. The index cannot turn missing history into evidence.
        for path, ids in ids_by_path.values():
            observed = {i for i, _ in result.get(path, ())}
            if self.collect:
                if observed:
                    self.lookup[_hash(os.fsencode(path))] = sorted(observed)
            else:
                if set(ids) != observed:
                    raise ValueError(f'Original PBS history did not return {len(set(ids) - observed)} indexed events')
        return result

    @staticmethod
    def _one(events, path, flag):
        ids = [i for i, f in events.get(path, ()) if f & flag]
        _require(len(ids) == 1)
        return ids[0]

    def _directory_entry(self, path, *, root=False):
        with ExitStack() as stack:
            parent = disk.directory(path.parent)
            stack.callback(os.close, parent)
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            stack.callback(os.close, fd)
            if root:
                self.stream_volume = self._volume(fd)
            self._same_volume(fd)
            self.reads.directory(path, fd)
            stamp = os.fstat(fd)
            _require(_study_directory.apfs_object_digest(fd, stamp.st_ino) is not None)
            # Darwin ATTR_CMN_CRTIME | PARENTID | ADDEDTIME. A normal cross-parent
            # rename updates date-added. It is settable, so the independent original
            # operation must also bound the kernel ctime, which cannot be backdated.
            fields = _study_directory._attributes(fd, 0x200 | 0x04000000 | 0x10000000, 0, 'qqQqq')
            _require(fields and fields[:2] == fields[3:] and fields[2] == os.fstat(parent).st_ino)
            return stamp

    def _needs_recovery(self, source, record, raw, live, old_device):
        if record['study_device'] != old_device:
            return False
        with ExitStack() as stack:
            directory = disk.directory(source.parent)
            stack.callback(os.close, directory)
            fd = disk.Store(directory).open(source.name, os.O_RDONLY)
            stack.callback(os.close, fd)
            seal = _study_directory.matches_binding(fd, raw, live['apfs_directory_sha256'])
            _require(seal is not False)
            return seal is None

    def _originals(self, path, live, old_device):
        from ag.autonomy_submission import _json, _read_file
        root = path.parent
        self._directory_entry(root, root=True)
        leaf = self._directory_entry(path)
        parent_birth = self._one(self._events(root, [root]), root, 0x100)
        machine = Path.home() / '.config/ag'
        bucket = machine / 'manual-writers' / live['study_key']
        bucket_fd = disk.directory(bucket)
        try:
            self.reads.directory(bucket, bucket_fd)
            names = os.listdir(bucket_fd)
        finally:
            os.close(bucket_fd)
        claims = sorted(bucket / n for n in names if n.endswith('.claim.json'))
        machine_files, objects, original = [], [path], {}
        pairs = []
        for source in claims:
            raw = _read_file(source)
            claim = _json(raw)
            if not self._needs_recovery(source, claim, raw, live, old_device):
                continue
            _require(raw == self._read_original(source))
            writer = claim['writer_id']
            _require(isinstance(writer, str) and len(writer) == 32 and source.name == writer + '.claim.json'
                     and claim['study_path'] == str(path) and claim['study_key'] == live['study_key']
                     and claim['study_inode'] == live['study_inode'] and type(claim['study_device']) is int)
            complete = bucket / (writer + '.complete.json')
            completion = _json(self._read_original(complete))
            _require(completion['writer_id'] == writer and completion['claim_sha256'] == _hash(raw)
                     and completion['finished_at'] >= claim['started_at'])
            machine_files.extend([source, complete])
            original[source] = (_hash(raw), claim['study_device'])
            targets = []
            if claim.get('action') == 'submit':
                for aid in claim['attempt_ids']:
                    sub = path / 'attempts' / study.identifier(aid) / 'submission.json'
                    if self._has(sub):
                        submission = _json(self._read_original(sub))
                        auth = submission['authorization']
                        if auth.get('method') == 'approval':
                            approval_id = study.identifier(auth['approval_id'])
                            used = path / 'approvals' / (approval_id + '.used')
                            if self._has(used):
                                targets.append((sub, used, aid))
                                objects.extend([sub, used])
            if claim.get('action') == 'snapshot':
                for aid in claim['attempt_ids']:
                    snapshots = path / 'attempts' / study.identifier(aid) / 'snapshots'
                    fd = disk.directory(snapshots)
                    try:
                        self.reads.directory(snapshots, fd)
                        names = os.listdir(fd)
                    finally:
                        os.close(fd)
                    for name in names:
                        folder = snapshots / name
                        meta = folder / 'snapshot.json'
                        if self._has(folder) and self._has(meta):
                            targets.append((folder, meta, aid))
                            objects.extend([folder, meta])
            pairs.append((source, complete, claim, targets))
        owned = path / 'autonomy/state.json'
        if self._has(owned):
            objects.extend([path / 'journal.jsonl', path / 'study.md', path / 'autonomy/journal.jsonl', owned])
        evidence = self._events(path, objects)
        birth = self._one(evidence, path, 0x100)
        _require(parent_birth < birth)
        writes = self._events(bucket, machine_files)
        deadlines, status_tied, attributed = [], False, set()
        for source, complete, claim, targets in pairs:
            lo, hi = self._one(writes, source, 0x100), self._one(writes, complete, 0x100)
            _require(birth < lo < hi)
            self._historical_time(source, lo, source.stat().st_ctime)
            self._historical_time(complete, hi, complete.stat().st_ctime)
            if claim.get('action') == 'status':
                status_tied |= any(lo < i < hi and f & 0x1000 for i, f in evidence.get(path / 'journal.jsonl', ()))
            members = set()
            for first, second, aid in targets:
                if claim['action'] == 'submit':
                    left, right = self._one(evidence, second, 0x100), self._one(evidence, first, 0x100)
                else:
                    left, right = self._one(evidence, first, 0x800), self._one(evidence, second, 0x1000)
                # The same Attempt can have successive snapshots. A writer may
                # also finish before dispatch, leaving no in-window product.
                if not (lo < left < hi or lo < right < hi):
                    continue
                _require(lo < left < right < hi and aid not in members and first not in attributed)
                members.add(aid)
                attributed.add(first)
                if claim['action'] == 'submit':
                    self._submission(path, first, second, aid)
                else:
                    self._snapshot(first, second, aid)
                _require(claim['started_at'] <= source.stat().st_ctime <= _json(self._read_original(complete))['finished_at'])
                deadlines.append(int(claim['started_at'] * 10**9))
        globals_here = self._globals(machine, live, old_device, birth)
        if self._has(owned):
            _require(status_tied and globals_here)
            deadlines.append(self._published(path, evidence, globals_here))
        _require(deadlines and leaf.st_ctime_ns <= max(deadlines))
        original.update(globals_here)
        return original

    def _submission(self, path, submission, used, aid):
        from ag.autonomy_submission import _json
        record = _json(self._read_original(submission))
        manifest = self._read_original(submission.parent / 'manifest.json')
        m, consumed = _json(manifest), _json(self._read_original(used))
        auth = record['authorization']
        permitted = _json(self._read_original(used.with_suffix('.json')))
        _require(record['attempt_id'] == m['attempt_id'] == aid and m['study_id'] == path.name
                 and record['manifest_sha256'] == _hash(manifest)
                 and permitted['id'] == consumed['id'] == auth['approval_id']
                 and permitted['study_id'] == path.name and aid in consumed['attempts']
                 and consumed['record_sha256'] == auth['record_sha256'] == approval.digest(permitted)
                 and any(row['attempt_id'] == aid and row['bundle_sha256'] == m['bundle_sha256']
                         for row in permitted['attempts']))

    def _snapshot(self, folder, metadata, aid):
        from ag.autonomy_submission import _json
        meta = _json(self._read_original(metadata))
        filename = meta['file']
        _require(isinstance(filename, str) and Path(filename).name == filename
                 and filename not in ('', '.', '..') and meta['attempt_id'] == aid
                 and meta['sha256'] == _hash(self._read_original(folder / filename)))

    def _globals(self, machine, live, old_device, birth):
        from ag.autonomy_submission import _json, _read_file
        result = {}
        for name in ('autonomy-studies', 'autonomy-reservations'):
            scope = machine / name
            try:
                fd = disk.directory(scope)
            except FileNotFoundError:
                continue
            try:
                self.reads.directory(scope, fd)
                files = [scope / n for n in os.listdir(fd)]
            finally:
                os.close(fd)
            members = []
            for source in files:
                raw = _read_file(source)
                item = _json(raw)
                if item['study_key'] != live['study_key']:
                    continue
                if not self._needs_recovery(source, item, raw, live, old_device):
                    continue
                _require(raw == self._read_original(source))
                _require(item['study_inode'] == live['study_inode'])
                members.append(source)
                result[source] = (_hash(raw), item['study_device'])
            events = self._events(scope, members)
            for source in members:
                event = self._one(events, source, 0x100)
                _require(birth < event)
                self._historical_time(source, event, source.stat().st_ctime)
        return result

    def _published(self, path, evidence, globals_here):
        from ag import autonomy
        from ag.autonomy_submission import _json, _load_state
        current = _load_state(path, {}, readonly=True)
        _require(current['phase'] == 'ended' and current['lease'] is None)
        consumed = {item['ownership_sha256'] for item in current['submissions'].values()}
        reservations = {sha for p, (sha, _) in globals_here.items() if p.parent.name == 'autonomy-reservations'}
        _require(reservations and reservations <= consumed)
        journal = path / 'autonomy/journal.jsonl'
        raw_events = self._read_original(journal).splitlines(keepends=True)
        events = [_json(line) for line in raw_events]
        _require([e['op'] for e in events[-3:]] == ['update', 'finish', 'end'])
        prefix = None
        for event in events[:-2]:
            prefix = autonomy.apply(prefix, event)
        previous = dict(state=prefix, seq=events[-3]['seq'], journal_sha256=_hash(raw_events[-3]))
        document = path / 'study.md'
        raw = self._read_original(document)
        _require(study._summary_render(raw, previous) == raw)
        state = path / 'autonomy/state.json'
        publication = self._one(evidence, document, 0x800)
        self._historical_time(document, publication, document.stat().st_ctime)
        self._historical_time(state, self._one(evidence, state, 0x800), state.stat().st_ctime)
        _require(any(publication < i < self._one(evidence, state, 0x800)
                     for i, f in evidence[journal] if f & 0x1000))
        leaf_ns, published_ns = path.stat().st_ctime_ns, document.stat().st_ctime_ns
        finish_ns = int(events[-2]['at'] * 10**9)
        end_ns = int(events[-1]['at'] * 10**9)
        _require(int(events[-3]['at'] * 10**9) <= published_ns <= leaf_ns <= finish_ns <= end_ns
                 <= journal.stat().st_ctime_ns <= state.stat().st_ctime_ns)
        return finish_ns
