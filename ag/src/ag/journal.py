"""Append-only local action journal."""
from datetime import datetime, timezone
import json
import os


def now():
    return datetime.now(timezone.utc).isoformat()


def append(study, action, attempt_id=None, result='ok', detail=None):
    record = dict(ts=now(), action=action, attempt_id=attempt_id, result=result, detail=detail)
    data = (json.dumps(record, ensure_ascii=False) + '\n').encode()
    fd = os.open(study / 'journal.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        if os.write(fd, data) != len(data):
            raise OSError('Incomplete journal append')
        os.fsync(fd)
    finally:
        os.close(fd)
