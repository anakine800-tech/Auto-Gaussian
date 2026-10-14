"""Verified output collection and exclusive supplemental fetches."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from ag import attempt, journal, state, study, remote
from ag.config import for_manifest
from ag.transport import TransportError, bound_transport
from ag.submit import metadata


def fetch(cfg, path, transport, *, add_missing=False):
    cfg = for_manifest(cfg, attempt.read_manifest(path))
    transport = bound_transport(transport, cfg)
    if add_missing:
        # Supplement records must not rewrite status or the original journal,
        # including the transport's usual SSH failure annotations.
        if hasattr(transport, 'record_to'):
            transport.record_to([])
        return _add_missing(cfg, path, transport)
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    m = attempt.read_manifest(path)
    journal.append(path.parent.parent, 'fetch', path.name, 'requested')
    if state.read(path)['state'] != 'finished':
        raise ValueError('Only a finished Attempt can be fetched')
    names = remote.output_names(m)
    output = study.local_path(Path(cfg['local']['studies_root']), path / 'outputs')
    for name in names:
        if (output / name).exists() or (output / name).is_symlink():
            raise FileExistsError('Output already exists; fetch will not overwrite')
    partial = study.local_path(Path(cfg['local']['studies_root']), output / '.partial')
    partial.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='fetch-', dir=partial))
    # Retain partial evidence on error. Do not publish any file until all verify.
    for name in names:
        before = metadata(transport, cfg, m, name)
        transport.download(m, name, stage / name)
        data = (stage / name).read_bytes()
        if before != (len(data), sha256(data).hexdigest()) or before != metadata(transport, cfg, m, name):
            raise ValueError('Downloaded file hash/size mismatch or remote output changed; stop')
    for name in names:
        os.link(stage / name, output / name)
    result = state.write(path, 'fetched', exit_status=state.read(path).get('exit_status'))
    journal.append(path.parent.parent, 'fetch', path.name, detail={'files': names})
    reminder = None
    if result.get('scheduler_residue'):
        reminder = (f'结果已取回；最近状态观察仍有 PBS 调度器残留。先用 ag status {path.name} 核查；'
                    f'若仍残留，可以用 ag cancel {path.name} 清理。'
                    '需人明确授权并亲手点击 Mac 系统对话框，只取消 status.json 中记录的确切作业号；不会自动取消。')
    return dict(attempt_id=path.name, files=names, cleanup_hint=reminder, **result)


def _remote_metadata(transport, cfg, manifest, name):
    try:
        return metadata(transport, cfg, manifest, name)
    except (TransportError, ValueError) as exc:
        # A failed test/stat cannot distinguish absence, permissions or a
        # rejected symlink; do not report an SSH failure as an absent file.
        raise type(exc)(f'Cannot verify declared remote output {name} '
                        f'(missing, unreadable or failed verification): {exc}') from exc


def _local_matches(root, output, name, expected):
    target = study.local_path(root, output / name)
    data = target.read_bytes()
    actual = len(data), sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f'Existing output mismatch: {name}; '
                         f'local size={actual[0]} sha256={actual[1]}; '
                         f'remote size={expected[0]} sha256={expected[1]}')


def _add_missing(cfg, path, transport):
    current = state.read(path)
    if current['state'] != 'fetched':
        raise ValueError('--add-missing requires a fetched Attempt')
    manifest = attempt.read_manifest(path)
    names = remote.output_names(manifest)
    root = Path(cfg['local']['studies_root'])
    output = study.local_path(root, path / 'outputs')
    # Preflight every remote file and every existing local file before download.
    expected = {name: _remote_metadata(transport, cfg, manifest, name) for name in names}
    missing, existing = [], []
    for name in names:
        target = study.local_path(root, output / name)
        if target.exists():
            _local_matches(root, output, name, expected[name])
            existing.append(name)
        else:
            missing.append(name)
    if not missing:
        return dict(attempt_id=path.name, files=[], message='没有可补取的文件', **current)

    partial = study.local_path(root, output / '.partial')
    partial.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='fetch-add-missing-', dir=partial))
    for name in missing:
        transport.download(manifest, name, stage / name)
        data = (stage / name).read_bytes()
        if (len(data), sha256(data).hexdigest()) != expected[name]:
            raise ValueError(f'Downloaded file hash/size mismatch: {name}; stop')
    # Do not publish a supplement against evidence changed during download.
    for name in names:
        if _remote_metadata(transport, cfg, manifest, name) != expected[name]:
            raise ValueError(f'Remote output changed during fetch: {name}; stop')
    for name in existing:
        _local_matches(root, output, name, expected[name])

    now = datetime.now(timezone.utc)
    record_name = 'fetch-add-missing-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.json'
    record = dict(attempt_id=path.name, created_at=now.isoformat(), files=missing,
                  outputs={name: dict(size=size, sha256=digest)
                           for name, (size, digest) in expected.items()})
    # xb uses O_CREAT | O_EXCL, for both results and the separate record.
    # Reserve the record before publishing: a collision cannot alter old data.
    # On I/O failure retain all evidence; an empty record is not a success.
    with study.local_path(root, path / record_name).open('xb') as handle:
        for name in missing:
            target = study.local_path(root, output / name)
            with target.open('xb') as destination:
                destination.write((stage / name).read_bytes())
                destination.flush()
                os.fsync(destination.fileno())
            _local_matches(root, output, name, expected[name])
        handle.write((json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode())
        handle.flush()
        os.fsync(handle.fileno())
    return dict(attempt_id=path.name, files=missing, record=record_name, **current)
