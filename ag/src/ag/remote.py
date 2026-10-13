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


def jobs(job=None):
    return Command('jobs', 'qstat -f' + (' ' + quote(job_id(job)) if job else ''))


def root_check(cfg):
    root = cfg['remote']['allowed_root']
    ag = cfg['remote']['ag_root']
    return Command('root_check', f'{path_checks(root)} && test -d {quote(root)} && test -w {quote(root)} && test -x {quote(root)} && test ! -L {quote(ag)}')


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


def receipt(cfg, manifest, name):
    """Read only the two small receipts; an oversized/racing file is rejected."""
    if name not in ('ag-start.json', 'ag-exit.json'):
        raise ValueError('Only start/exit receipts may be read')
    p = attempt_dir(cfg, manifest) + '/' + name
    q = quote(p)
    return Command('receipt', f'{path_checks(p)} && if test ! -e {q}; then '
                   f"printf 'absent\\n'; else test -f {q} && "
                   f'test "$(stat -c %s -- {q})" -le 4096 && head -c 4096 -- {q} && test "$(stat -c %s -- {q})" -le 4096; fi')


def output_names(manifest):
    from ag.render import declaration
    stem = PurePosixPath(next(r['name'] for r in manifest['inputs'] if r['name'] != 'job.pbs')).stem
    return [filename(n.format(stem=stem)) for n in declaration(manifest['template'])['outputs']]


def output_observation(cfg, manifest):
    # Query exactly the declared files, including absent ones. Nanosecond mtime
    # detects writes within the same second; no directory traversal or globbing.
    commands = []
    for name in output_names(manifest):
        p = attempt_dir(cfg, manifest) + '/' + name
        q = quote(p)
        commands.append(f'{path_checks(p)} && if test ! -e {q}; then '
                        f"printf '%s absent\\n' {quote(name)}; else test -f {q} && "
                        f"printf '%s ' {quote(name)} && stat -c '%s %y' -- {q}; fi")
    return Command('output_observation', ' && '.join(f'{{ {c}; }}' for c in commands))


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
