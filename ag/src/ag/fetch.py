"""Verified output collection with no-overwrite hard-link publication."""
from hashlib import sha256
import os
from pathlib import Path
import tempfile
from ag import attempt, journal, render, state, study
from ag.submit import metadata


def fetch(cfg, path, transport):
    if hasattr(transport, 'record_to'):
        transport.record_to([path])
    m = attempt.read_manifest(path)
    journal.append(path.parent.parent, 'fetch', path.name, 'requested')
    if state.read(path)['state'] != 'finished':
        raise ValueError('Only a finished Attempt can be fetched')
    stem = next(Path(r['name']).stem for r in m['inputs'] if r['name'] != 'job.pbs')
    names = [n.format(stem=stem) for n in render.declaration(m['template'])['outputs']]
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
    return dict(attempt_id=path.name, files=names, **result)
