"""Machine-local configuration. Never copy this configuration into a study."""
from pathlib import Path, PurePosixPath
import re
import math
from datetime import date
import tomllib


class ConfigError(ValueError):
    pass


def absolute(value, key, *, remote=False):
    if not isinstance(value, str) or not value or any(c in value for c in '\n\r\x00<>'):
        raise ConfigError(f'Invalid configuration: {key}')
    path = PurePosixPath(value) if remote else Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise ConfigError(f'Expected absolute non-root path: {key}')
    if remote and not re.fullmatch(r'/[A-Za-z0-9_./-]+', str(path)):
        raise ConfigError(f'Path cannot be represented safely in PBS directives: {key}')
    return str(path)


def load_config(path=None, *, local_only=False):
    path = Path(path) if path else Path.home() / '.config/ag/config.toml'
    try:
        with path.open('rb') as handle:
            cfg = tomllib.load(handle)
        cfg['local']['studies_root'] = absolute(cfg['local']['studies_root'], 'local.studies_root')
        studies = Path(cfg['local']['studies_root'])
        # Prevent accidentally committing studies into this or another Git checkout.
        if any((p / '.git').exists() for p in (studies, *studies.parents)):
            raise ConfigError('studies_root must be outside a Git checkout')
        cfg['_config_dir'] = str(path.parent)
        if local_only:
            # review is local: cluster credentials and scheduler settings are not prerequisites.
            return dict(local=cfg['local'], _config_dir=cfg['_config_dir'])
        if 'clusters' in cfg:
            if not isinstance(cfg['clusters'], dict) or not cfg['clusters']:
                raise ConfigError('Expected nonempty clusters table')
            if cfg.get('ssh', {}).get('host'):
                if 'default' in cfg['clusters']:
                    raise ConfigError('Legacy configuration and clusters.default are ambiguous')
                cfg['clusters']['default'] = {key: cfg[key] for key in ('ssh', 'remote', 'scheduler', 'programs', 'resources')}
            for name, cluster in cfg['clusters'].items():
                cluster_name(name)
                validate_cluster(cluster)
        else:
            validate_cluster(cfg)
        return cfg
    except (KeyError, TypeError, OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError('Missing or invalid local configuration') from exc


def cluster_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ConfigError('Invalid cluster name')
    return value


def scheduler_kind(cfg):
    value = cfg.get('scheduler', {})
    return 'pbs' if isinstance(value, dict) else value


def validate_cluster(cfg):
    scheduler = scheduler_kind(cfg)
    if scheduler not in ('pbs', 'slurm'):
        raise ConfigError('scheduler must be pbs or slurm')
    # Named PBS configs use scheduler="pbs" plus queue; legacy retains its table.
    if scheduler == 'pbs' and cfg.get('scheduler') == 'pbs':
        cfg['scheduler'] = {'queue': cfg['queue']}
    for section, key, remote in (
        ('ssh', 'config_file', False), ('remote', 'allowed_root', True),
        ('remote', 'ag_root', True), ('programs.gaussian', 'g16root', True),
        ('programs.xtb', 'root', True),
    ):
        target = cfg
        for part in section.split('.'):
            target = target[part]
        target[key] = absolute(target[key], f'{section}.{key}', remote=remote)
    for section, key in [('ssh', 'host')] + ([('scheduler', 'queue')] if scheduler == 'pbs' else []):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg[section][key]):
            raise ConfigError(f'Invalid configuration: {section}.{key}')
    if cfg['remote']['ag_root'] != cfg['remote']['allowed_root'] + '/ag':
        raise ConfigError('remote.ag_root must equal remote.allowed_root/ag')
    limit = cfg['resources']['max_cores']
    if type(limit) is not int or limit < 1 or (scheduler == 'pbs' and limit > 44):
        raise ConfigError('max_cores must be positive (PBS maximum: 44)')
    committed = cfg['resources'].get('max_committed_cores', limit)
    if type(committed) is not int or not limit <= committed <= 4 * limit:
        raise ConfigError('max_committed_cores must be an integer: max_cores..4*max_cores')
    cfg['resources']['max_committed_cores'] = committed
    for name in ('mini', 'simple', 'general', 'complex'):
        tier = cfg['resources']['tiers'][name]
        if (type(tier['cores']) is not int or not 1 <= tier['cores'] <= limit
                or type(tier['mem_gb']) is not int or tier['mem_gb'] < 1
                or (scheduler == 'pbs' and tier['mem_gb'] > 120)):
            raise ConfigError(f'Invalid resource tier: {name}')
    if not Path(cfg['ssh']['config_file']).is_file():
        raise ConfigError('SSH configuration file does not exist')

    if scheduler == 'slurm':
        for key in ('partition', 'account', 'qos'):
            if key in cfg and (not isinstance(cfg[key], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg[key])):
                raise ConfigError(f'Invalid Slurm {key}')
        allowed = {'scheduler', 'ssh', 'remote', 'programs', 'resources', 'partition', 'account', 'qos', 'expires'}
        if set(cfg) - allowed:
            raise ConfigError('Unsupported Slurm configuration field')
    if 'expires' in cfg:
        value = cfg['expires']
        if isinstance(value, date):
            value = value.isoformat()
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ConfigError('expires must be YYYY-MM-DD')
        date.fromisoformat(value)
        cfg['expires'] = value
    budget = cfg['resources'].get('budget_core_hours')
    if budget is not None and (type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0):
        raise ConfigError('budget_core_hours must be a positive finite number')
    if scheduler == 'pbs':
        return  # Preserve legacy PBS handling of unused program config fields.
    gaussian = cfg['programs']['gaussian']
    if set(gaussian) - {'g16root', 'modules', 'module_init', 'environment'}:
        raise ConfigError('Unsupported Gaussian environment field')
    if 'environment' in gaussian:
        if gaussian['environment'] != 'scnet-a03':
            raise ConfigError('Unsupported Gaussian environment')
        # The platform env.sh writes outside ag_root and resets scratch.
        # This fixed template must not source it via module initialization.
        if gaussian.get('module_init') or gaussian.get('modules'):
            raise ConfigError('scnet-a03 uses its fixed environment without module setup')
    modules = gaussian.get('modules', [])
    if not isinstance(modules, list) or any(not isinstance(m, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./+-]*', m) or '..' in m for m in modules):
        raise ConfigError('Invalid Gaussian module name')
    if 'module_init' in gaussian:
        gaussian['module_init'] = absolute(gaussian['module_init'], 'programs.gaussian.module_init', remote=True)


def select_cluster(cfg, name='default'):
    cluster_name(name)
    if '_cluster' in cfg:
        if cfg['_cluster'] != name:
            raise ConfigError('Transport/configuration cluster mismatch')
        return cfg
    if 'clusters' in cfg:
        if name not in cfg['clusters']:
            raise ConfigError(f'Cluster is not configured: {name}')
        selected = dict(cfg['clusters'][name])
        selected.update(local=cfg['local'], _config_dir=cfg['_config_dir'])
    else:
        if name != 'default':
            raise ConfigError(f'Cluster is not configured: {name}')
        selected = dict(cfg)
    selected['_cluster'] = name
    return selected


def for_manifest(cfg, manifest):
    try:
        selected = select_cluster(cfg, manifest.get('cluster', 'default'))
        if scheduler_kind(selected) != manifest.get('scheduler', 'pbs'):
            raise ConfigError('Scheduler changed since preparation')
        return selected
    except ValueError as exc:
        raise ConfigError(f'Attempt {manifest.get("attempt_id", "<unknown>")}: {exc}') from exc
