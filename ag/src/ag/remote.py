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
