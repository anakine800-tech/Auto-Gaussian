"""Read-only, byte-preserving log observations, never result collection."""
import base64
import binascii
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from ag import attempt, remote, study
from ag.config import for_manifest
from ag.transport import bound_transport, require_ok


DEFAULT_MAX_BYTES = 20_000_000
NOTICE = '运行中快照，不是结果，不能用于签字或分析。'


def find(cfg, value, study_name=None):
    """Resolve an ID (optionally within a study) without accepting remote paths."""
    if study_name is None:
        return attempt.find(cfg, value)
    directory = study.locate(cfg, study_name)
    path = study.local_path(directory, directory / 'attempts' / study.identifier(value))
    attempt.read_manifest(path)
    return path


def progress(data, template, *, truncated=False):
    """Text statistics over this fragment only; no facts/scientific acceptance."""
    result = dict(program=template, scope='captured_fragment', truncated=truncated)
    if template != 'gaussian':
        return dict(result, message='已保存主程序日志；Gaussian 进度统计不适用。')
    text = data.decode('utf-8', errors='replace')
    # A tail can begin in the middle of a line; do not count that partial line.
    if truncated:
        text = text.partition('\n')[2]
    scf = re.findall(r'^\s*SCF Done:.*?=\s*([-+]?\d+\.\d+(?:[DEde][-+]?\d+)?)', text, re.M)
    steps = re.findall(r'^\s*Step number\s+(\d+)\b', text, re.M)
    tables = list(re.finditer(r'^[ \t]*Item[ \t]+Value[ \t]+Threshold[ \t]+Converged\?[^\n]*\n', text, re.M))
    rows = []
    if tables:
        for line in text[tables[-1].end():].splitlines()[:4]:
            if re.match(r'^\s*(?:Maximum|RMS)\s+(?:Force|Displacement)\s+', line):
                rows.append(line)
            else:
                break
    endings = re.findall(r'^[ \t]*(?:Normal termination|Error termination)[^\n]*', text, re.M)
    frequency = bool(re.search(r'^\s*(?:Harmonic frequencies|Frequencies\s+--)', text, re.M))
    return dict(result, scf_done_count=len(scf), last_scf_energy_hartree=scf[-1] if scf else None,
                optimization_step_count=len(steps), last_step_number=int(steps[-1]) if steps else None,
                last_convergence_table=rows, convergence_table_complete=len(rows) == 4,
                last_termination=endings[-1] if endings else None, freq_started=frequency,
                freq_note='仅表示片段中是否看见频率输出标记；未见不代表未开始。')


def _decode(value, max_bytes):
    try:
        size, mtime, encoded = value.split('\n', 2)
        if not re.fullmatch(r'\d+', size) or not re.fullmatch(r'-?\d+', mtime):
            raise ValueError
        size, mtime = int(size), int(mtime)
        # ASCII armour preserves CRLF, non-UTF-8 bytes and a partial final line
        # through the existing text-mode Transport, without changing it.
        data = base64.b64decode(''.join(encoded.split()), validate=True)
        if len(data) != min(size, max_bytes):
            raise ValueError
    except (ValueError, binascii.Error) as exc:
        raise ValueError('Invalid or incomplete log snapshot response; no snapshot published') from exc
    return size, mtime, data


def capture(cfg, path, transport, *, max_bytes=DEFAULT_MAX_BYTES, publication=None):
    root = Path(cfg['local']['studies_root'])
    path = study.local_path(root, Path(path))
    manifest, current, job = attempt.local_record(path)
    if current['state'] == 'fetched' or list(path.glob('fetch-incomplete-*.json')):
        raise ValueError('Attempt already fetched; inspect outputs/ directly')
    if job is None or current['state'] in ('prepared', 'submitting', 'failed_presubmit'):
        raise ValueError('Snapshot requires a submitted Attempt with a recorded job ID')
    cfg = for_manifest(cfg, manifest)
    command = remote.log_snapshot(cfg, manifest, max_bytes)
    directory = study.local_path(root, path / 'snapshots')
    if directory.exists() and not directory.is_dir():
        raise ValueError('snapshots must be a directory')
    transport = bound_transport(transport, cfg)
    # An injected/reused transport may still have a status/journal error target.
    # Snapshot failures must not annotate any lifecycle or evidence record.
    if hasattr(transport, 'record_to'):
        transport.record_to([])
    response = require_ok(transport.run(command), 'log snapshot (missing, unreadable or changed file)')
    size, mtime, data = _decode(response, max_bytes)
    at = datetime.now(timezone.utc)
    name = remote.output_names(manifest)[0]
    destination = study.local_path(root, directory / at.strftime('%Y%m%dT%H%M%S%fZ'))
    result = dict(schema='ag-log-snapshot/1', created_at=at.isoformat(),
                  attempt_id=path.name, cluster=manifest.get('cluster', 'default'), job_id=job,
                  latest_status=dict(state=current['state'], updated_at=current.get('updated_at')),
                  file=name, remote_size=size, remote_mtime_epoch=mtime, read_bytes=len(data),
                  max_bytes=max_bytes, truncated=size > max_bytes, sha256=sha256(data).hexdigest(),
                  notice=NOTICE, progress=progress(data, manifest['template'], truncated=size > max_bytes),
                  snapshot=destination.relative_to(path).as_posix())
    with publication() if publication is not None else nullcontext():
        directory.mkdir(mode=0o700, exist_ok=True)
        destination.mkdir(mode=0o700)  # A timestamp collision fails, never overwrites.
        for filename, content in ((name, data), ('snapshot.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())):
            target = study.local_path(root, destination / filename)
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
                stream.write(content)
    return result


def capture_for_run(cfg, path, transport, *, run_id, token, plan_sha256,
                    max_bytes=DEFAULT_MAX_BYTES):
    """Bind a new formal capture to a wake; no lock spans network IO.

    An owner that expires in flight cannot publish the returned bytes. Paused
    owners may still observe; cancellation review requires an active run.
    """
    from ag import autonomy
    from ag import _autonomy_store as disk
    from ag.autonomy_cancel import bound_attempt, snapshot_evidence
    root = Path(cfg['local']['studies_root'])
    path = study.local_path(root, Path(path))
    name = path.parent.parent.name
    publication_guard = getattr(autonomy, 'observation_publication_guard', None)
    if publication_guard is not None:
        from ag.autonomy_submission import machine_lock
        def registry_lock():
            return machine_lock(create=False)
    else:
        # T184 supports local observation provenance independently. When T186
        # is integrated, its global registry lock and publication fence apply.
        registry_lock = nullcontext
    with registry_lock():
        with autonomy.action_guard(cfg, name, run_id, token,
                                   action='observe', plan_sha256=plan_sha256) as before:
            binding = bound_attempt(path)
            started = autonomy.now()
    @contextmanager
    def publication():
        guard = publication_guard or autonomy.action_guard
        with guard(cfg, name, run_id, token, action='observe', plan_sha256=plan_sha256):
            if bound_attempt(path) != binding:
                raise ValueError('Attempt binding changed before snapshot publication')
            yield
    result = capture(cfg, path, transport, max_bytes=max_bytes, publication=publication)
    with registry_lock(), disk.locked(cfg, name, write=True) as store:
        current, _ = autonomy.load(store)
        token_hash = sha256(token.encode()).hexdigest()
        evidence = snapshot_evidence(path, result['snapshot'], binding)
        if evidence['snapshot_sha256'] != sha256(
                (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest():
            raise ValueError('Captured snapshot changed before registration')
        versions = autonomy.versions()
        at = autonomy.now()
        autonomy.eligible(current['state'], run_id, token_hash, versions,
                          at, 'observe', plan_sha256)
        data = dict(binding=binding, run_id=run_id, token_sha256=token_hash,
                    round_id=before['state']['current_round'], plan_sha256=plan_sha256,
                    capture_started_seq=before['seq'],
                    versions=versions, capture_started_at=started, capture_finished_at=at,
                    **{k: evidence[k] for k in ('snapshot', 'snapshot_sha256', 'log_sha256', 'captured_at')})
        saved = store.commit(current, 'snapshot', at, data, autonomy.apply)
    return dict(result, autonomy=dict(run_id=run_id, round_id=data['round_id'],
                plan_sha256=plan_sha256, journal_seq=saved['seq'],
                snapshot_sha256=evidence['snapshot_sha256']))


def format_snapshot(result):
    p = result['progress']
    lines = [result['notice'], f"{result['snapshot']}/{result['file']}",
             f"读取 {result['read_bytes']} / {result['remote_size']} 字节；截断：{result['truncated']}",
             f"最近本地状态：{result['latest_status']['state']}（本命令不查询或刷新状态）"]
    if p['program'] == 'gaussian':
        lines += [f"片段中 SCF Done：{p['scf_done_count']}；末次能量（Hartree）：{p['last_scf_energy_hartree']}",
                  f"片段中优化步记录：{p['optimization_step_count']}；末次 Step number：{p['last_step_number']}",
                  f"末次收敛表（完整四项：{p['convergence_table_complete']}）：",
                  *p['last_convergence_table'], f"末次终止标记：{p['last_termination']}",
                  f"看到 Freq 输出标记：{p['freq_started']}；{p['freq_note']}"]
    else:
        lines.append(p['message'])
    return '\n'.join(lines)
