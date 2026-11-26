"""Independent local mode-review bundles. Nothing here opens the submission registry."""
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
from uuid import uuid4

from ag import _autonomy_store as disk
from ag.facts import _publication_identity, _publication_unchanged
from ag.study import local_path


def _check_location(path, study):
    # The fixed destination may itself be under a study on a nonstandard HOME.
    # Use the same study markers as the PBS directory walk, without opening a ledger.
    local_path(path, path)
    if path.is_relative_to(study.parent) or study.is_relative_to(path):
        raise ValueError('Offline mode-review output overlaps the source studies root')
    for parent in (path, *path.parents):
        if (parent.name == 'ag' and parent.parent.name == '.config'
                or any(os.path.lexists(parent / marker) for marker in ('attempts', 'autonomy'))):
            raise ValueError('Offline mode-review output overlaps a study or the production registry')


def _verify_directory(path, fd):
    named = disk.directory(path)
    try:
        if not os.path.samestat(os.fstat(fd), os.fstat(named)):
            raise ValueError('Offline mode-review directory changed during publication')
    finally:
        os.close(named)


def publish(study, attempt, manifest_hash, payloads, verify):
    """Return a bundle directory only after the source and all three members agree."""
    home = Path.home().absolute()
    components = ('.local', 'state', 'ag-offline', 'mode-reviews')
    base = home.joinpath(*components)
    _check_location(base, study)
    verify()
    review_id = uuid4().hex
    path = base / review_id
    with ExitStack() as stack:
        fd = disk.directory(home)
        stack.callback(os.close, fd)
        directory = home
        for name in (*components, review_id):
            # Recheck before mkdir, including when an existing component was
            # substituted with another real directory after the initial check.
            _check_location(base, study)
            _verify_directory(directory, fd)
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
                os.fsync(fd)
            except FileExistsError:
                if name == review_id:
                    raise
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            stack.callback(os.close, fd)
            directory /= name
        _check_location(path, study)
        _verify_directory(path, fd)
        store = disk.Store(fd)
        proofs = []

        def write_new(name, data):
            def pin(opened):
                held = os.dup(opened)
                stack.callback(os.close, held)
                proofs.append((path / name, held, _publication_identity(os.fstat(held))))
            store.exclusive(name, data, before_sync=pin)

        for name, content in payloads.items():
            write_new(name, content)
        record = dict(schema='ag-offline-mode-review/1', review_id=review_id,
                      created_at=datetime.now(timezone.utc).isoformat(), source_study=str(study),
                      attempt=attempt, manifest_sha256=manifest_hash,
                      artifacts={name: sha256(raw).hexdigest() for name, raw in payloads.items()})
        # Only the final exclusive link publishes the registration. IO failure or
        # a changed source may leave inspectable artifacts without a registration.
        candidate = '.registration-stage'
        encoded = disk.encode(record)
        write_new(candidate, encoded)
        for name, expected in (*payloads.items(), (candidate, encoded)):
            if store.read(name) != expected:
                raise ValueError('Offline mode-review bytes changed before registration')
        _check_location(path, study)
        _verify_directory(path, fd)
        verify()
        for proof in proofs:
            _publication_unchanged(proof)
        os.link(candidate, 'registration.json', src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.unlink(candidate, dir_fd=fd)
        os.fsync(fd)
        _verify_directory(path, fd)
    return path
