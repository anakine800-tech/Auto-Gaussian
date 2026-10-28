"""The complete remote command allowlist. No caller-supplied shell programs."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from shlex import quote
from ag.study import identifier


@dataclass(frozen=True)
class Command:
    operation: str
    text: str
    timeout: int = 60


def path_checks(path):
    p = PurePosixPath(path)
    return ' && '.join(f'test ! -L {quote(str(part))}' for part in reversed((p, *p.parents[:-1])))


def contained(cfg, path):
    p, root = PurePosixPath(path), PurePosixPath(cfg['remote']['ag_root'])
    if not p.is_absolute() or '..' in p.parts or not p.is_relative_to(root):
        raise ValueError('Remote path escapes ag_root')
    return str(p)


def attempt_dir(cfg, manifest):
    study, attempt = identifier(manifest['study_id']), identifier(manifest['attempt_id'])
    if manifest['remote_dir'] != f'{study}/{attempt}':
        raise ValueError('Invalid relative remote directory')
    return contained(cfg, cfg['remote']['ag_root'] + '/' + manifest['remote_dir'])


def filename(name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or name in ('.', '..'):
        raise ValueError('Expected a plain filename')
    return name


def job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.[A-Za-z0-9][A-Za-z0-9_.-]*)?', value):
        raise ValueError('Invalid exact PBS job ID')
    return value


def identity():
    return Command('identity', 'id -un')


def queues():
    return Command('queues', 'qstat -Q')


def nodes():
    return Command('nodes', 'pbsnodes -a')


def jobs(job=None):
    return Command('jobs', 'qstat -f' + (' ' + quote(job_id(job)) if job else ''))


def root_check(cfg):
    root = cfg['remote']['allowed_root']
    ag = cfg['remote']['ag_root']
    text = f'{path_checks(root)} && test -d {quote(root)} && test -w {quote(root)} && test -x {quote(root)} && test ! -L {quote(ag)}'
    if cfg.get('scheduler') == 'slurm':
        text += f' && test -d {quote(ag)} && test -w {quote(ag)} && test -x {quote(ag)}'
    return Command('root_check', text)


def executable(path):
    return Command('executable', f'test -x {quote(path)} && test -f {quote(path)}')


def create_attempt(cfg, manifest):
    path = attempt_dir(cfg, manifest)
    root, study = cfg['remote']['ag_root'], str(PurePosixPath(path).parent)
    checks = path_checks(path)
    # All directories are created individually. The Attempt MUST be new.
    text = (f'{checks} && test -d {quote(cfg["remote"]["allowed_root"])} && '
            f'if test ! -e {quote(root)}; then mkdir -- {quote(root)}; fi && '
            f'if test ! -e {quote(study)}; then mkdir -- {quote(study)}; fi && '
            f'mkdir -- {quote(path)}')
    return Command('create_attempt', text)


def upload_check(cfg, manifest, name):
    p = attempt_dir(cfg, manifest) + '/' + filename(name)
    return Command('upload_check', f'{path_checks(p)} && test -d {quote(str(PurePosixPath(p).parent))} && test ! -e {quote(p)}')


def metadata(cfg, manifest, name):
    p = attempt_dir(cfg, manifest) + '/' + filename(name)
    return Command('metadata', f"{path_checks(p)} && test -f {quote(p)} && stat -c %s -- {quote(p)} && sha256sum -- {quote(p)}")


def parent_chk_environment():
    # Diagnose unsupported Python/proc before any checkpoint declaration is used.
    return Command('parent_chk_environment',
                   "python3 --version && if test -d /proc/self/fd && "
                   "test -r /proc/self/fd/0; then printf 'proc_fd=yes\\n'; "
                   "else printf 'proc_fd=no\\n'; fi")


def parent_chk_metadata(cfg, manifest, name):
    from ag.parent_chk_remote import SCRIPT
    if not filename(name).endswith('.chk'):
        raise ValueError('Expected a chk filename')
    source = attempt_dir(cfg, manifest) + '/' + name
    return Command('parent_chk_metadata',
                   f'{path_checks(source)} && python3 -c {quote(SCRIPT)} metadata {quote(source)} -')


def copy_parent_chk(cfg, parent, child):
    from ag.parent_chk_remote import SCRIPT
    attachment = child['parent_chk']
    if (attachment['attempt_id'] != parent['attempt_id'] or
            attachment['target_name'] != 'parent.chk' or
            parent['attempt_id'] == child['attempt_id'] or
            parent['study_id'] != child['study_id'] or
            parent.get('cluster', 'default') != child.get('cluster', 'default') or
            attachment['cluster'] != child.get('cluster', 'default')):
        raise ValueError('Invalid parent chk copy declaration')
    name = filename(attachment['source_name'])
    if not name.endswith('.chk'):
        raise ValueError('Expected a chk filename')
    source = attempt_dir(cfg, parent) + '/' + name
    target = attempt_dir(cfg, child)
    return Command('copy_parent_chk',
                   f'{path_checks(source)} && test -f {quote(source)} && '
                   f'{path_checks(target)} && set -C && '
                   f'python3 -c {quote(SCRIPT)} copy {quote(source)} {quote(target)}')


def output_exists(cfg, manifest, name):
    p = attempt_dir(cfg, manifest) + '/' + filename(name)
    return Command('output_exists', f'{path_checks(p)} && test -f {quote(p)}')


def listing(cfg, manifest):
    p = attempt_dir(cfg, manifest)
    return Command('listing', f'{path_checks(p)} && ls -la -- {quote(p)}')


def submit(cfg, manifest):
    p = attempt_dir(cfg, manifest)
    return Command('submit', f'{path_checks(p + "/job.pbs")} && cd {quote(p)} && qsub job.pbs', 120)


def cancel(job):
    return Command('cancel', 'qdel ' + quote(job_id(job)))


def _observation(cfg, manifest, mode, names):
    from ag.observation_remote import SCRIPT
    directory = attempt_dir(cfg, manifest)
    arguments = ' '.join(quote(filename(name)) for name in names)
    # No installation, arbitrary shell input, procfs or weaker fallback.
    text = (f'if ag_python=$(command -v python3); then python3 -I -S -B -c {quote(SCRIPT)} '
            f'{mode} {quote(directory)} {arguments}; else '
            "printf 'observation runtime PYTHON_MISSING\\n' >&2; exit 1; fi")
    if len(text.encode()) >= 64 * 1024:
        raise ValueError('Observation command exceeds 64 KiB; shorten configured path')
    return text


def receipt(cfg, manifest, name):
    """Read only the two receipts from a pinned file, buffering at most 4097 bytes."""
    if name not in ('ag-start.json', 'ag-exit.json'):
        raise ValueError('Only start/exit receipts may be read')
    return Command('receipt', _observation(cfg, manifest, 'receipt', [name]))


def output_names(manifest):
    from ag.render import declaration
    if manifest['template'] == 'multiwfn':
        from ag.nci_report import layout
        frames, pairs = layout(manifest)
        declared = declaration('multiwfn')
        names = list(declared['outputs'])
        for frame in range(1, frames + 1):
            names.extend(n.format(frame=frame) for n in declared['frame_outputs'])
            for left, right in pairs:
                names.extend(n.format(frame=frame, left=left, right=right)
                             for n in declared['pair_outputs'])
        return [filename(name) for name in names]
    stem = PurePosixPath(next(r['name'] for r in manifest['inputs'] if r['name'] not in ('job.pbs', 'job.slurm', 'constraints.inp'))).stem
    declared = declaration(manifest['template'])
    # Scan output selection only; keep existing commands and non-scan files unchanged.
    key = 'scan_outputs' if manifest['template'] == 'xtb' and manifest.get('science', {}).get('scan') else 'outputs'
    if manifest['template'] == 'crest' and '--mdopt' in manifest.get('template_params', {}):
        key = 'mdopt_outputs'
    names = [filename(n.format(stem=stem)) for n in declared[key]]
    # Freeze old receipts' outputs union missing; only new CREST Attempts opt in.
    if manifest['template'] == 'crest' and 'crest_output_set' in manifest:
        if manifest['crest_output_set'] != 'diagnostics-v1':
            raise ValueError('Unsupported CREST output set')
        names += [filename(n) for n in declared['diagnostic_outputs']]
    if manifest.get('scheduler') == 'slurm':
        names = [n.replace('job.pbs.out', 'job.slurm.out') for n in names] + ['job.slurm.err']
    return names


def output_observation(cfg, manifest):
    # The same bounded command/declared list handles ordinary and Multiwfn
    # outputs. The remote helper buffers all rows; no partial observation.
    return Command('output_observation',
                   _observation(cfg, manifest, 'output', output_names(manifest)))


def incomplete_output_observation(cfg, manifest, name):
    """Strict, read-only presence check for one declared output.

    T47: test ! -e alone mistakes an inaccessible parent for a missing file.
    Keep the existing status observer unchanged; reuse its read-only operation
    category, not its weaker absence test. Nonzero means unverifiable.
    """
    filename(name)
    if name not in output_names(manifest):
        raise ValueError('Expected a declared output filename')
    directory = attempt_dir(cfg, manifest)
    p = directory + '/' + name
    q, parent = quote(p), quote(directory)
    return Command('output_observation',
                   f'{path_checks(p)} && test -d {parent} && test -x {parent} && '
                   f'if test -e {q}; then test -f {q} && test -r {q} && '
                   f"stat -c '%s %y' -- {q}; else "
                   f"test ! -L {q} && test -d {parent} && test -x {parent} && "
                   "printf 'absent\\n'; fi")


def log_snapshot(cfg, manifest, max_bytes):
    """Observe only the declared primary log, with no remote temporary file.

    The descriptor identity checks prevent a replaced path/link from selecting
    another file. Bound the initial-size window so an appending writer cannot
    exceed the byte limit. Base64 preserves bytes through the text transport.
    Reuse output_observation's read-only category, as T47 does above.
    """
    # Shell/utility byte offsets use signed 64-bit integers; reject overflow.
    if type(max_bytes) is not int or not 1 <= max_bytes <= 2**63 - 1:
        raise ValueError('max-bytes must be a positive signed 64-bit integer')
    p = attempt_dir(cfg, manifest) + '/' + output_names(manifest)[0]
    q = quote(p)
    checks = path_checks(p)
    return Command('output_observation',
                   f'{checks} && test -f {q} && test -r {q} && '
                   f"ag_meta=$(stat -c '%s %Y %d:%i' -- {q}) && "
                   'set -- $ag_meta && test "$#" -eq 3 && '
                   'ag_size=$1 && ag_mtime=$2 && ag_file=$3 && '
                   f'if test "$ag_size" -gt {max_bytes}; then '
                   f'ag_start=$((ag_size - {max_bytes} + 1)); ag_count={max_bytes}; '
                   'else ag_start=1; ag_count=$ag_size; fi && '
                   f'( {checks} && test -f /proc/self/fd/3 && '
                   'test "$(stat -Lc %d:%i -- /proc/self/fd/3)" = "$ag_file" && '
                   "printf '%s\\n' \"$ag_size\" \"$ag_mtime\" && "
                   '{ tail -c +"$ag_start" -- /proc/self/fd/3 | head -c "$ag_count" | base64; } && '
                   f'{checks} && test "$(stat -c %d:%i -- {q})" = "$ag_file" && '
                   'test "$(stat -Lc %s -- /proc/self/fd/3)" -ge "$ag_size" '
                   f') 3< {q}')


def completion_marker(cfg, manifest):
    from ag.render import declaration
    name = output_names(manifest)[0]
    marker = declaration(manifest['template'])['completion']
    p = attempt_dir(cfg, manifest) + '/' + name
    # grep's no-match code is distinct from command/SSH failure. Never execute
    # a caller-supplied pattern or inspect an undeclared program output.
    return Command('completion_marker', f'{path_checks(p)} && if test ! -e {quote(p)}; then '
                   "printf 'absent\\n'; else "
                   f'test -f {quote(p)} && {{ if grep -F -q -- {quote(marker)} {quote(p)}; '
                   "then printf 'present\\n'; else ag_rc=$?; test \"$ag_rc\" -eq 1 && "
                   "printf 'absent\\n'; fi; }; fi")


def session_processes(session):
    # Only a positive PBS session ID, never a command/selector supplied by a log.
    if not isinstance(session, str) or not re.fullmatch(r'[1-9][0-9]{0,9}', session):
        raise ValueError('Invalid PBS session ID')
    return Command('session_processes', f'ps -s {session} -o pid=,sid=,stat=,comm=')


# These fixed constructions prevent job IDs, account names or scheduler output
# from becoming remote commands; callers cannot supply formats or shell flags.
def slurm_job_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value):
        raise ValueError('Invalid exact Slurm job ID')
    return value


def slurm_token(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value):
        raise ValueError('Invalid Slurm selector')
    return value


def slurm_jobs(job=None, *, user=None):
    if (job is None) == (user is None):
        raise ValueError('Expected one exact job or user selector')
    selector = '-j ' + slurm_job_id(job) if job is not None else '-u ' + quote(slurm_token(user))
    return Command('slurm_jobs', f"squeue -h {selector} -r --local -o '%i|%.200j|%.64u|%T|%C|%M|%P'")


def slurm_accounting(job):
    return Command('slurm_accounting', 'sacct -X -n -P -j ' + slurm_job_id(job)
                   + ' --format=JobID%64,JobName%200,User%64,State%64,ExitCode%32,Elapsed%32,AllocCPUS%20')


def slurm_find(user, name, since):
    identifier(name)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', since):
        raise ValueError('Invalid accounting start date')
    return Command('slurm_find', f'sacct -X -n -P -u {quote(slurm_token(user))} '
                   f'--name={quote(name)} --starttime={since} '
                   '--format=JobID%64,JobName%200,User%64,State%64,ExitCode%32,Elapsed%32,AllocCPUS%20')


def slurm_history(user):
    return Command('slurm_history', f'sacct -X -n -P -u {quote(slurm_token(user))} '
                   '--starttime=now-30days --endtime=now --state=CD,F,CA,TO,OOM,NF '
                   '--format=JobID%64,JobName%200,User%64,State%64,ExitCode%32,Elapsed%32,AllocCPUS%20')


def slurm_partitions(partition=None):
    return Command('slurm_partitions', "sinfo -h -o '%P'" +
                   (' -p ' + quote(slurm_token(partition)) if partition else ''))


def slurm_tools():
    return Command('slurm_tools', 'command -v sbatch && command -v squeue && command -v sacct && command -v scancel && command -v sinfo')


def slurm_partition_jobs(partition):
    # Reuse the read-only squeue operation; never fetch other users' identities.
    return Command('slurm_jobs', f"squeue -h -p {quote(slurm_token(partition))} -r --local -o '%T|%C'")


def slurm_partition_hardware(partition):
    return Command('slurm_partitions', f"sinfo -h -p {quote(slurm_token(partition))} -o '%C|%m|%D'")


def slurm_partition_allocmem(partition):
    # Node rows contain only AllocMem, not node names; aggregate locally.
    return Command('slurm_partitions', f'sinfo -h -p {quote(slurm_token(partition))} -N -O AllocMem:20')


def slurm_partition_nodes(partition):
    # One identified row per node/partition; never join anonymous CPU/memory rows.
    fields = ('NodeList:256|,PartitionName:256|,CPUsState:64|,Memory:64|,'
              'AllocMem:64|,StateLong:64|,Available:32')
    return Command('slurm_partitions', f'sinfo -h --local -N -e -p {quote(slurm_token(partition))} '
                   f'-O {quote(fields)}')


def slurm_submit(cfg, manifest):
    p = attempt_dir(cfg, manifest)
    return Command('submit', f'{path_checks(p + "/job.slurm")} && cd {quote(p)} && sbatch --parsable job.slurm', 120)


def slurm_cancel(job):
    return Command('cancel', 'scancel ' + slurm_job_id(job))


def storage_usage(cfg):
    root = contained(cfg, cfg['remote']['ag_root'])
    # du's default does not follow encountered symlinks; reject root symlinks.
    return Command('storage_usage', f'{path_checks(root)} && test -d {quote(root)} && du -s -k -- {quote(root)}')
