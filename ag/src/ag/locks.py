"""Local process serialization and permanent single-submission claims."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def submission_lock(cfg):
    path = Path(cfg['_config_dir']) / 'submit.lock'
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def claim(path):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write('Claimed permanently; never resubmit this Attempt.\n')
        handle.flush()
        os.fsync(handle.fileno())

    # A power loss must not erase the claim directory entry after qsub started.
    directory_fd = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
