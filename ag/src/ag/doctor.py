"""Read-only environment checks; never create remote probe files."""
import re
import time
import sys
from dataclasses import replace
from ag import remote, status, slurm, budget
from ag.config import scheduler_kind, unmerged_clusters, crest_executable, optional_resource_caps
from ag.transport import require_ok


def doctor(cfg, transport):
    limits = optional_resource_caps(cfg)
    if "scheduler_max_running_cores" in limits:
        limits["scheduler_running_note"] = "由调度器执行，ag 未核实；此字段仅记录管理员应实施的运行上限"
        print(limits["scheduler_running_note"], file=sys.stderr, flush=True)
    if 'budget_core_hours' in cfg['resources']:
        print('budget_core_hours 已不参与提交检查，可删除', file=sys.stderr, flush=True)
    unmerged = unmerged_clusters(cfg)
    if unmerged:
        names = ', '.join(sorted([cfg.get('_cluster', 'default'), *unmerged]))
        print(f'疑似同集群入口未合并（SSH 配置文件或 host 别名不同）：{names}', file=sys.stderr, flush=True)
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
        history_available = bool(slurm.parse_accounting(history, username=username, allow_arrays=True))
        storage_kib = storage(cfg, transport)
    else:
        require_ok(transport.run(remote.queues()), 'scheduler queues')
    require_ok(transport.run(remote.root_check(cfg)), 'allowed root')
    paths = {'gaussian': cfg['programs']['gaussian']['g16root'] + '/g16',
             'xtb': cfg['programs']['xtb']['root'] + '/bin/xtb',
             'crest': crest_executable(cfg['programs'])}
    for name, path in paths.items():
        require_ok(transport.run(remote.executable(path)), f'{name} executable')
    checkpoint = parent_chk_environment(transport)
    if not checkpoint['ok']:
        print(checkpoint['note'], file=sys.stderr, flush=True)
    return dict(ok=history_available is not False, parent_chk=checkpoint, storage_kib=storage_kib, expiry_warning=budget.expiry_warning(cfg), accounting_history=history_available,
                accounting_note=('No historical jobs visible; accounting availability remains unverified' if history_available is False else None),
                cluster=cfg.get('_cluster', 'default'), ssh=True, identity=True, scheduler=True, allowed_root=True,
                programs=list(paths), occupied_cores=used,
                max_cores=cfg['resources']['max_cores'],
                max_committed_cores=cfg['resources'].get('max_committed_cores', cfg['resources']['max_cores']),
                inventory_seconds=round(latency, 3), **limits)


def storage(cfg, transport, *, timeout=None):
    command = remote.storage_usage(cfg)
    if timeout is not None:
        command = replace(command, timeout=timeout)
    value = require_ok(transport.run(command), 'ag_root storage usage')
    fields = value.strip().split()
    if len(fields) != 2 or not fields[0].isdigit() or fields[1] != cfg['remote']['ag_root']:
        raise ValueError('Invalid du usage response')
    return int(fields[0])


def parent_chk_environment(transport):
    result = transport.run(remote.parent_chk_environment())
    if result.returncode == 127:
        return dict(ok=False, python_version=None, proc_fd=None, note='父 chk 功能不可用：远端没有 python3')
    value = require_ok(result, 'parent chk Python/proc environment')
    match = re.fullmatch(r'Python (\d+)\.(\d+)\.(\d+)\nproc_fd=(yes|no)\n?', value.strip())
    if match is None:
        raise ValueError('Invalid parent chk Python/proc environment response')
    version = tuple(int(match[i]) for i in (1, 2, 3))
    proc_fd = match[4] == 'yes'
    supported = version >= (3, 6, 0)
    return dict(ok=supported and proc_fd, python_version='.'.join(str(n) for n in version),
                proc_fd=proc_fd, note=None if supported and proc_fd else
                '父 chk 功能不可用：需要 Python >= 3.6 和可读的 /proc/self/fd')
