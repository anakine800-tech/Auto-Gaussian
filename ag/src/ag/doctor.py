"""Read-only environment checks; never create remote probe files."""
import re
import time
import sys
from ag import remote, status, slurm, budget
from ag.config import scheduler_kind
from ag.transport import require_ok


def doctor(cfg, transport):
    warning = budget.expiry_warning(cfg)
    if warning:
        print(warning, file=sys.stderr, flush=True)
    start = time.monotonic()
    username, _, used = status.inventory(transport, cfg)
    latency = time.monotonic() - start
    history_available = None
    storage_kib = None
    if scheduler_kind(cfg) == 'slurm':
        require_ok(transport.run(remote.slurm_tools()), 'Slurm commands')
        partitions = require_ok(transport.run(remote.slurm_partitions(cfg.get('partition'))), 'Slurm partitions')
        visible = [line.strip().rstrip('*') for line in partitions.splitlines() if line.strip()]
        if not visible or (cfg.get('partition') and cfg['partition'] not in visible):
            raise ValueError('Configured Slurm partition is not visible')
        history = require_ok(transport.run(remote.slurm_history(username)), 'Slurm accounting history')
        history_available = bool(slurm.parse_accounting(history, allow_arrays=True))
        storage_kib = storage(cfg, transport)
    else:
        require_ok(transport.run(remote.queues()), 'scheduler queues')
    require_ok(transport.run(remote.root_check(cfg)), 'allowed root')
    paths = {'gaussian': cfg['programs']['gaussian']['g16root'] + '/g16',
             'xtb': cfg['programs']['xtb']['root'] + '/bin/xtb',
             'crest': cfg['programs']['xtb']['root'] + '/bin/crest'}
    for name, path in paths.items():
        require_ok(transport.run(remote.executable(path)), f'{name} executable')
    checkpoint = parent_chk_environment(transport)
    return dict(ok=history_available is not False and checkpoint['ok'], parent_chk=checkpoint, storage_kib=storage_kib, expiry_warning=budget.expiry_warning(cfg), accounting_history=history_available,
                accounting_note=('No historical jobs visible; accounting availability remains unverified' if history_available is False else None),
                cluster=cfg.get('_cluster', 'default'), ssh=True, identity=True, scheduler=True, allowed_root=True,
                programs=list(paths), occupied_cores=used,
                max_cores=cfg['resources']['max_cores'], inventory_seconds=round(latency, 3))


def storage(cfg, transport):
    value = require_ok(transport.run(remote.storage_usage(cfg)), 'ag_root storage usage')
    fields = value.strip().split()
    if len(fields) != 2 or not fields[0].isdigit() or fields[1] != cfg['remote']['ag_root']:
        raise ValueError('Invalid du usage response')
    return int(fields[0])


def parent_chk_environment(transport):
    value = require_ok(transport.run(remote.parent_chk_environment()), 'parent chk Python/proc environment')
    match = re.fullmatch(r'Python (\d+)\.(\d+)\.(\d+)\nproc_fd=(yes|no)\n?', value.strip())
    if match is None:
        raise ValueError('Invalid parent chk Python/proc environment response')
    version = tuple(int(match[i]) for i in (1, 2, 3))
    proc_fd = match[4] == 'yes'
    supported = version >= (3, 6, 0)
    return dict(ok=supported and proc_fd, python_version='.'.join(str(n) for n in version),
                proc_fd=proc_fd, note=None if supported and proc_fd else
                'Parent chk requires Python >= 3.6 and readable /proc/self/fd')
