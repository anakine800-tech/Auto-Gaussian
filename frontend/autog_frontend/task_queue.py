"""Durable local command queue. The domain execute_once remains effect owner.

Browser input can select a prepared identity, never code, paths or chemistry.
SUBMITTING is persisted before the effect. Lost replies become UNKNOWN with no
automatic retry, including after restart. GET only reads local snapshots.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid
import fcntl

from auto_g16.query import QueryError

SCHEMA = 'autog-task-center/1'
TERMINAL = {'SUCCEEDED', 'FAILED', 'NOT_SUBMITTED'}


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass
class PreparedExecution:
    """Created by a trusted local backend factory, never deserialized from HTTP.

    readiness must check current approval, structure/stereochemistry and declared
    prerequisites, raising on drift. It must perform no effects itself.
    """
    database: Path
    snapshot: object
    profile: object
    input_bytes: bytes
    template_bytes: bytes
    port: object
    title: str
    structure_review: str
    readiness: object


class RuntimeGateway:
    """Concrete adapter to public Auto-G16 execute_once; no SSH/qsub shortcut."""
    def __init__(self, bundles):
        from auto_g16.execution import ExecutionSnapshot
        self.bundles = dict(bundles)
        for identity,b in self.bundles.items():
            if (not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}',identity)
                    or not isinstance(b,PreparedExecution) or type(b.snapshot) is not ExecutionSnapshot
                    or not callable(b.readiness) or not b.structure_review or not b.title):
                raise ValueError('qualified V30 ExecutionSnapshot bundle required; V31 provider not yet qualified')

    def review(self, identity):
        b = self.bundles[identity]
        b.readiness()
        s = b.snapshot
        from auto_g16.execution import assert_execution_snapshot_identity
        assert_execution_snapshot_identity(s)
        s.prepared_input_binding.verify_bytes(b.input_bytes)
        s.pbs_template_binding.verify_bytes(b.template_bytes)
        from auto_g16.execution import resolve_server_profile
        if resolve_server_profile(b.profile) != s.resolved_server_profile:
            raise ValueError('profile drift')
        snapshot_id = getattr(s, 'program_execution_snapshot_id', None) or s.execution_snapshot_id
        from .archive_import import plain
        return dict(id=identity, title=b.title, attempt_id=s.attempt_id, snapshot_id=snapshot_id,
                    input_sha256=sha256(b.input_bytes).hexdigest(), input_text=b.input_bytes.decode('utf-8'),
                    template_sha256=sha256(b.template_bytes).hexdigest(), structure_review=b.structure_review,
                    resources=plain(s.resolved_resource_request.semantic_payload()),
                    remote_directory=s.workspace_binding.remote_attempt_dir,
                    profile_sha256=s.resolved_server_profile.effective_config_sha256)

    def list_prepared(self):
        items = []
        for identity in self.bundles:
            try:
                review = self.review(identity)
                items.append(dict(review=review, review_sha256=digest(review), available=True))
            except Exception:
                items.append(dict(id=identity, available=False, reason='preparation-or-approval-unavailable'))
        return items

    def submit(self, identity, expected):
        review = self.review(identity)
        if digest(review) != expected:
            raise ValueError('review changed')
        from auto_g16.core import SQLiteRuntimeStore
        from auto_g16.execution import execute_once
        b = self.bundles[identity]
        with SQLiteRuntimeStore(b.database) as store:
            result = execute_once(store, snapshot=b.snapshot, current_profile=b.profile,
                prepared_input_bytes=b.input_bytes, pbs_template_bytes=b.template_bytes,
                confirmed_execution_snapshot_id=review['snapshot_id'], port=b.port)
        return dict(state=result.attempt_state.value, attempt_id=review['attempt_id'])

    def status(self, identity):
        from auto_g16.query import QueryService
        b = self.bundles[identity]
        return QueryService(b.database).get_attempt(b.snapshot.attempt_id)['data']['execution_state']


class TaskQueue:
    def __init__(self, directory, gateway=None, max_active=1):
        directory = Path(directory)
        if not directory.is_absolute() or directory.resolve() != directory or not directory.is_dir():
            raise ValueError('existing canonical task queue directory required')
        if type(max_active) is not int or not 1 <= max_active <= 16:
            raise ValueError('max_active must be 1..16')
        self.path = directory / 'queue.sqlite3'
        if self.path.is_symlink():
            raise ValueError('queue cannot be a symlink')
        self.gateway, self.max_active = gateway, max_active
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        # One owner per queue directory, including separate local app processes.
        import os
        fd = os.open(directory / 'owner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self.owner = os.fdopen(fd, 'a')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise ValueError('task queue already owned') from None
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, request_id TEXT UNIQUE, request_hash TEXT, prepared_id TEXT, review_hash TEXT, payload TEXT, state TEXT, reason TEXT, created REAL, updated REAL)')
            db.execute("UPDATE commands SET state='UNKNOWN',reason='interrupted-before-receipt' WHERE state='SUBMITTING'")

    @contextmanager
    def db(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()

    def snapshot(self):
        with self.db() as db:
            rows = db.execute('SELECT * FROM commands ORDER BY created,id').fetchall()
        return dict(schema=SCHEMA, enabled=True, execution_enabled=self.gateway is not None,
                    max_active=self.max_active, items=[self.row(r) for r in rows],
                    prepared=self.gateway.list_prepared() if self.gateway else [])

    @staticmethod
    def row(r):
        return dict(id=r['id'], prepared_id=r['prepared_id'], state=r['state'], reason=r['reason'],
                    payload=json.loads(r['payload']), created_at=r['created'], updated_at=r['updated'])

    def action(self, action, body):
        if not isinstance(body, dict):
            raise QueryError('invalid-task-request')
        if action == 'reconcile':
            if self.gateway is None: raise QueryError('execution-unavailable')
            if set(body) != {'id'} or not isinstance(body['id'],str): raise QueryError('invalid-task-request')
            with self.db() as db:
                row=db.execute("SELECT * FROM commands WHERE id=? AND state='UNKNOWN'",(body['id'],)).fetchone()
                if row is None: raise QueryError('task-conflict')
                try: state=self.gateway.status(row['prepared_id'])
                except Exception: state='UNKNOWN'
                if state in TERMINAL | {'SUBMITTED','RUNNING'}:
                    db.execute('UPDATE commands SET state=?,reason=NULL,updated=? WHERE id=?',(state,time.time(),row['id']))
            return self.snapshot()
        if action == 'withdraw':
            if set(body) != {'id'} or not isinstance(body['id'], str):
                raise QueryError('invalid-task-request')
            with self.db() as db:
                changed = db.execute("UPDATE commands SET state='WITHDRAWN',reason=NULL,updated=? WHERE id=? AND state IN ('DRAFT','QUEUED','BLOCKED')", (time.time(),body['id'])).rowcount
                if not changed: raise QueryError('task-conflict')
            return self.snapshot()
        required = {'request_id', 'source', 'stage', 'title'} if action == 'draft' else {'request_id','prepared_id','review_sha256'}
        if action not in ('draft','enqueue','submit') or set(body) != required or not isinstance(body['request_id'], str) or not re.fullmatch(r'[A-Za-z0-9-]{8,80}', body['request_id']):
            raise QueryError('invalid-task-request')
        with self.db() as db:
            previous = db.execute('SELECT request_hash FROM commands WHERE request_id=?',(body['request_id'],)).fetchone()
            if previous:
                if previous['request_hash'] != digest(body): raise QueryError('task-conflict')
                return self.snapshot()
        prepared_id = review_hash = None
        if action == 'draft':
            src = body['source']
            if not isinstance(src,dict) or set(src) != {'kind','id','sha256'} or src['kind'] not in ('attempt','archive') or not isinstance(src['id'],str) or not 1 <= len(src['id']) <= 256 or not re.fullmatch('[a-f0-9]{64}',str(src['sha256'])):
                raise QueryError('invalid-task-request')
            if body['stage'] not in ('optimization','frequency','single-point','review') or not isinstance(body['title'],str) or not 1 <= len(body['title']) <= 160:
                raise QueryError('invalid-task-request')
            payload, state = body, 'DRAFT'
        else:
            if self.gateway is None: raise QueryError('execution-unavailable')
            prepared_id, review_hash = body['prepared_id'], body['review_sha256']
            if not isinstance(prepared_id,str) or not re.fullmatch('[a-f0-9]{64}',str(review_hash)):
                raise QueryError('invalid-task-request')
            try:
                payload = self.gateway.review(prepared_id)
            except Exception: raise QueryError('task-review-changed') from None
            if digest(payload) != review_hash: raise QueryError('task-review-changed')
            state = 'QUEUED'
        with self.db() as db:
            # Repeat under the mutation lock for concurrent/replayed HTTP calls.
            previous = db.execute('SELECT request_hash FROM commands WHERE request_id=?',(body['request_id'],)).fetchone()
            if previous:
                if previous['request_hash'] != digest(body): raise QueryError('task-conflict')
                return self.snapshot()
            if db.execute('SELECT count(*) FROM commands').fetchone()[0] >= 2000:
                raise QueryError('task-queue-full')
            if prepared_id and db.execute("SELECT 1 FROM commands WHERE prepared_id=? AND state!='WITHDRAWN'",(prepared_id,)).fetchone():
                raise QueryError('task-conflict')
            if action == 'submit' and db.execute("SELECT 1 FROM commands WHERE state IN ('QUEUED','SUBMITTING','SUBMITTED','RUNNING','UNKNOWN')").fetchone():
                raise QueryError('task-capacity-busy')
            now = time.time()
            db.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,?,?,?,?)',
                (str(uuid.uuid4()),body['request_id'],digest(body),prepared_id,review_hash,json.dumps(payload),state,None,now,now))
        self.wake.set()
        return self.snapshot()

    def tick(self):
        if self.gateway is None: return
        with self.db() as db:
            rows = db.execute("SELECT * FROM commands WHERE state IN ('SUBMITTED','RUNNING','UNKNOWN','SUBMITTING')").fetchall()
        active = 0
        for row in rows:
            if row['state'] in ('UNKNOWN','SUBMITTING'):
                active += 1
                continue
            try:
                state = self.gateway.status(row['prepared_id'])
                if state not in TERMINAL | {'SUBMITTED','RUNNING'}: state = 'UNKNOWN'
            except Exception: state = 'UNKNOWN'
            with self.db() as db:
                db.execute('UPDATE commands SET state=?,updated=? WHERE id=?',(state,time.time(),row['id']))
            if state not in TERMINAL: active += 1
        if active >= self.max_active: return
        with self.db() as db:
            row = db.execute("SELECT * FROM commands WHERE state='QUEUED' ORDER BY created,id LIMIT 1").fetchone()
            if row is None: return
            try:
                review = self.gateway.review(row['prepared_id'])
                if digest(review) != row['review_hash']: raise ValueError()
            except Exception:
                db.execute("UPDATE commands SET state='BLOCKED',reason='review-or-prerequisite-changed',updated=? WHERE id=?",(time.time(),row['id']))
                return
            db.execute("UPDATE commands SET state='SUBMITTING',updated=? WHERE id=?",(time.time(),row['id']))
        try:
            result = self.gateway.submit(row['prepared_id'],row['review_hash'])
            state = result['state']
            if state not in TERMINAL | {'SUBMITTED','RUNNING','UNKNOWN'}: state = 'UNKNOWN'
        except Exception:
            state = 'UNKNOWN'
        with self.db() as db:
            db.execute('UPDATE commands SET state=?,reason=?,updated=? WHERE id=?',
                (state,'receipt-unavailable-no-retry' if state=='UNKNOWN' else None,time.time(),row['id']))

    def start(self):
        if self.thread is not None: return
        def work():
            while not self.stop.is_set():
                try: self.tick()
                except Exception: pass  # Durable state is preserved; no remote replay.
                self.wake.wait(5)
                self.wake.clear()
        self.thread = threading.Thread(target=work, daemon=True, name='autog-local-submit-queue')
        self.thread.start()

    def close(self):
        self.stop.set(); self.wake.set()
        if self.thread: self.thread.join(timeout=2)
        if not self.thread or not self.thread.is_alive(): self.owner.close()
