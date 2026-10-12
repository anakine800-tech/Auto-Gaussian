"""Explicit local human direction confirmations, separate from scientific acceptance.

GET never creates files. POST only appends an atomic immutable JSON record in an
operator-selected directory. No Core, Result, ReviewBundle or authority writes.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import uuid
from datetime import datetime, timezone

from auto_g16.query import QueryError
from .archive import _object
from .vibrations import validate_modes

SCHEMA = 'auto-g16-intended-mode-review/1'
TARGET_SCHEMA = 'auto-g16-intended-mode-target/1'
DECISION = 'intended-reaction-coordinate'
MAX_RECORDS = 1000


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def vector_digest(rows):
    return hashlib.sha256(b''.join(struct.pack('>5d',*(row[k] for k in ('center','atomic_number','dx','dy','dz'))) for row in rows)).hexdigest()


def command(value):
    if not isinstance(value, dict) or set(value) != {'schema','request_id','target_sha256','reviewer','note','decision'}:
        raise QueryError('invalid-review-request')
    if (value['schema'] != SCHEMA or value['decision'] != DECISION
            or not isinstance(value['request_id'], str)
            or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', value['request_id'])
            or not isinstance(value['target_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['target_sha256'])):
        raise QueryError('invalid-review-request')
    for key, limit in [('reviewer', 120), ('note', 2000)]:
        text = value[key]
        if not isinstance(text, str) or len(text) > limit or text != text.strip() or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise QueryError('invalid-review-request')
    if not value['reviewer']:
        raise QueryError('invalid-review-request')
    return value


class ModeReviewStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        if (not self.directory.is_absolute() or self.directory.resolve() != self.directory
                or not self.directory.is_dir()):
            raise ValueError('review directory must be an existing canonical absolute directory')
        info = self.directory.stat()
        self.identity = (info.st_dev, info.st_ino)

    def _open(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != self.identity:
            os.close(fd)
            raise QueryError('review-store-unavailable')
        return fd

    @staticmethod
    def _read(fd, name):
        file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise QueryError('review-store-invalid')
            record = json.loads(stream.read(65537), object_pairs_hook=_object)
        if not isinstance(record, dict) or set(record) != {'schema','record_id','recorded_at_utc','reviewer_identity','command','target','record_sha256'}:
            raise QueryError('review-store-invalid')
        payload = {k:v for k,v in record.items() if k != 'record_sha256'}
        cmd = command(record['command'])
        if (record['schema'] != SCHEMA or record['record_id'] != 'mode-review-'+cmd['request_id']
                or name != cmd['request_id']+'.json' or record['reviewer_identity'] != 'self-declared-local-user'
                or record['record_sha256'] != digest(payload) or digest(record['target']) != cmd['target_sha256']
                or record['target'].get('schema') != TARGET_SCHEMA):
            raise QueryError('review-store-invalid')
        datetime.strptime(record['recorded_at_utc'], '%Y-%m-%dT%H:%M:%S.%fZ')
        return record

    def records(self, attempt_id):
        fd = self._open()
        try:
            names = [n for n in os.listdir(fd) if n.endswith('.json')]
            if len(names) > MAX_RECORDS:
                raise QueryError('review-store-limit')
            records = [self._read(fd,n) for n in sorted(names)]
            return [r for r in records if r['target'].get('attempt_id') == attempt_id]
        finally:
            os.close(fd)

    def append(self, cmd, target):
        fd = self._open()
        name, temporary = cmd['request_id']+'.json', '.pending-'+str(uuid.uuid4())
        try:
            # Lock the configured directory inode across threads/processes.
            # Count and atomic publication must be one critical section, or
            # successful distinct requests can exceed the readable capacity.
            fcntl.flock(fd, fcntl.LOCK_EX)
            # Same request and same content replay the original server timestamp.
            try:
                existing = self._read(fd,name)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if existing['command'] != cmd or existing['target'] != target:
                    raise QueryError('review-request-conflict')
                return existing
            if sum(n.endswith('.json') for n in os.listdir(fd)) >= MAX_RECORDS:
                raise QueryError('review-store-limit')
            payload = dict(schema=SCHEMA,record_id='mode-review-'+cmd['request_id'],
                           recorded_at_utc=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                           reviewer_identity='self-declared-local-user',command=cmd,target=target)
            record = {**payload,'record_sha256':digest(payload)}
            tmp = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(tmp, 'wb') as stream:
                    stream.write(canonical(record));stream.flush();os.fsync(stream.fileno())
                try:
                    os.link(temporary,name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
                except FileExistsError:
                    existing = self._read(fd,name)
                    if existing['command'] != cmd or existing['target'] != target:
                        raise QueryError('review-request-conflict')
                    record = existing
            finally:
                os.unlink(temporary,dir_fd=fd)
            os.fsync(fd)
            return record
        finally:
            os.close(fd)


class ModeReviewService:
    def __init__(self, details, directory=None):
        self.details = details
        self.store = ModeReviewStore(directory) if directory is not None else None

    def target(self, attempt_id):
        detail = self.details.get_details('attempt',attempt_id)
        result = detail['result']
        if result['availability'] != 'available':
            return None,'qualified-result-required'
        data,source = result['data'],result['source']
        f = data['scientific_facts']
        if (f['program_status'] != 'normal-termination' or f['error_termination_count'] != 0
                or not f['optimization_completed_marker'] or not f['stationary_point_marker']
                or not f['frequency_parse_complete'] or f['imaginary_frequency_count'] != 1):
            return None,'single-imaginary-candidate-required'
        dto = self.details.get_vibrations('attempt',attempt_id)
        if dto['vibrations']['availability'] != 'available':
            return None,'bound-displacements-required'
        packet = validate_modes(dto['vibrations']['data'],detail)
        modes = [m for m in packet['modes'] if m['frequency_cm1'] < 0]
        if len(modes) != 1:
            return None,'single-imaginary-candidate-required'
        mode = modes[0]
        return dict(schema=TARGET_SCHEMA,attempt_id=attempt_id,result_source=source,
                    frequency_cm1=mode['frequency_cm1'],mode_number=mode['mode_number'],frequency_index=mode['frequency_index'],
                    geometry_sha256=digest(packet['reference_geometry']),displacements_sha256=vector_digest(mode['displacements']),
                    vector_digest_format='ieee754-be-f64-center-atomic-number-dxyz/1',
                    mode_source_span=mode['source_span'],frequency_source_span=mode['frequency_source_span'],
                    mode_evidence_sha256=dto['vibrations']['source']['sha256'],scientific_facts_sha256=digest(f),
                    scope='human-intended-mode-only-not-ts-acceptance'),None

    def _invoke(self, operation):
        try:
            return operation()
        except QueryError:
            raise
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            raise QueryError('review-store-unavailable') from None

    def get(self, attempt_id):
        def read():
            target,reason = self.target(attempt_id) if self.store else (None,'review-writing-disabled')
            records = self.store.records(attempt_id) if self.store else []
            key = digest(target) if target else None
            current = [r for r in records if r['command']['target_sha256'] == key]
            return dict(schema=SCHEMA,attempt_id=attempt_id,enabled=self.store is not None,
                        target=target,target_sha256=key,reason=reason,records=current,other_target_count=len(records)-len(current))
        return self._invoke(read)

    def confirm(self, attempt_id, value):
        def write():
            if not self.store:
                raise QueryError('review-writing-disabled')
            cmd = command(value)
            target,reason = self.target(attempt_id)
            if target is None or digest(target) != cmd['target_sha256']:
                raise QueryError('review-target-changed')
            record = self.store.append(cmd,target)
            return dict(schema=SCHEMA,attempt_id=attempt_id,record=record)
        return self._invoke(write)
