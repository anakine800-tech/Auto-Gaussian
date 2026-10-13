"""Read-only environment checks; never create remote probe files."""
import time
from ag import remote, status
from ag.transport import require_ok


def doctor(cfg, transport):
    start = time.monotonic()
    _, _, used = status.inventory(transport)
    latency = time.monotonic() - start
    require_ok(transport.run(remote.queues()), 'scheduler queues')
    require_ok(transport.run(remote.root_check(cfg)), 'allowed root')
    paths = {'gaussian': cfg['programs']['gaussian']['g16root'] + '/g16',
             'xtb': cfg['programs']['xtb']['root'] + '/bin/xtb',
             'crest': cfg['programs']['xtb']['root'] + '/bin/crest'}
    for name, path in paths.items():
        require_ok(transport.run(remote.executable(path)), f'{name} executable')
    return dict(ok=True, ssh=True, identity=True, scheduler=True, allowed_root=True,
                programs=list(paths), occupied_cores=used,
                max_cores=cfg['resources']['max_cores'], inventory_seconds=round(latency, 3))
