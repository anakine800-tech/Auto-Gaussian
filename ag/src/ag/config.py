"""Machine-local configuration. Never copy this configuration into a study."""
from pathlib import Path, PurePosixPath
import re
import math
import subprocess
from datetime import date
import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RESOURCE_TIERS = ('mini', 'simple', 'general', 'complex', 'max', 'ultra')


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


def multiwfn_executable(programs):
    """Optional until selected; reject shell syntax while permitting quoted spaces."""
    value = programs.get('multiwfn')
    if isinstance(value, dict) and set(value) == {'root'} and isinstance(value['root'], str):
        value = value['root'].rstrip('/') + '/Multiwfn'
    if (not isinstance(value, str) or not re.fullmatch(r'(?:/|~/)[A-Za-z0-9_./ -]+', value)
            or any(part in ('.', '..', '') for part in value.removeprefix('~/').lstrip('/').split('/'))):
        raise ConfigError('programs.multiwfn requires an absolute or ~/ executable path (or root table)')
    return value


def crest_executable(programs):
    """Resolve the optional independent CREST install; legacy layouts stay valid."""
    if 'crest' not in programs:
        return programs['xtb']['root'] + '/bin/crest'
    value = programs['crest']
    if not isinstance(value, dict) or set(value) != {'executable'}:
        raise ConfigError('programs.crest requires an executable path')
    return absolute(value['executable'], 'programs.crest.executable', remote=True)


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
        cfg['_config_path'] = str(path.absolute())
        validate_approval(cfg)
        validate_routing(cfg)
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
                for key in ('allowed_templates', 'display_name', 'display_order', 'scheduler_timezone', 'monitor_interval_seconds'):
                    if key in cfg:
                        cfg['clusters']['default'][key] = cfg[key]
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


def validate_routing(cfg):
    """Catch misspelled entries before advice can silently skip a destination."""
    if 'routing' not in cfg:
        return
    from ag.study import identifier
    names = set(cfg.get('clusters', {'default': cfg}))
    if cfg.get('ssh', {}).get('host'):
        names.add('default')

    def orders(value):
        if not isinstance(value, dict) or set(value) - {'gaussian', 'crest'}:
            raise ConfigError('routing orders only accept gaussian and crest')
        for order in value.values():
            if (not isinstance(order, list) or any(not isinstance(n, str) for n in order)
                    or len(order) != len(set(order)) or set(order) - names):
                raise ConfigError('routing order requires unique configured cluster names')

    section = cfg['routing']
    if not isinstance(section, dict):
        raise ConfigError('routing must be a table')
    orders({k: v for k, v in section.items() if k != 'studies'})
    studies = section.get('studies', {})
    if not isinstance(studies, dict):
        raise ConfigError('routing.studies must be a table')
    for name, value in studies.items():
        try:
            identifier(name)
        except ValueError as exc:
            raise ConfigError('Invalid routing study name') from exc
        orders(value)


def validate_approval(cfg):
    """Reject misspelled/unbounded policies before they can authorize a job."""
    if 'approval' not in cfg:
        return
    from ag.approval import timestamp, walltime_seconds
    from ag.render import declaration
    from ag.study import identifier
    try:
        section = cfg['approval']
        if not isinstance(section, dict) or set(section) != {'policies'}:
            raise ValueError('Expected approval.policies table')
        policies = section['policies']
        if not isinstance(policies, dict):
            raise ValueError('Expected approval.policies table')
        for name, policy in policies.items():
            cluster_name(name)
            if not isinstance(policy, dict) or set(policy) != {
                    'studies', 'templates', 'clusters', 'max_cores_per_job',
                    'max_walltime', 'quote', 'set_at'}:
                raise ValueError('Invalid approval policy fields')
            for key, validate in (('studies', identifier), ('templates', declaration), ('clusters', cluster_name)):
                values = policy[key]
                if (not isinstance(values, list) or not values
                        or any(not isinstance(v, str) for v in values) or len(values) != len(set(values))):
                    raise ValueError('Policy lists must be nonempty unique names')
                for value in values:
                    validate(value)  # Exact names only; no glob/regex patterns.
            if type(policy['max_cores_per_job']) is not int or policy['max_cores_per_job'] < 1:
                raise ValueError('Policy max_cores_per_job must be a positive integer')
            walltime_seconds(policy['max_walltime'])
            if not isinstance(policy['quote'], str) or not policy['quote'].strip():
                raise ValueError('Policy quote must not be empty')
            timestamp(policy['set_at'])
    except (ValueError, TypeError, KeyError) as exc:
        raise ConfigError(f'Invalid approval configuration: {exc}') from exc


def scheduler_kind(cfg):
    value = cfg.get('scheduler', {})
    return 'pbs' if isinstance(value, dict) else value


def _max_walltime_seconds(value):
    from ag.approval import walltime_seconds
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{2,4}:[0-5][0-9]:[0-5][0-9]', value):
        raise ConfigError('resources.max_walltime must be positive HH:MM:SS')
    try:
        return walltime_seconds(value)
    except ValueError as exc:
        raise ConfigError('resources.max_walltime must be positive HH:MM:SS') from exc


def validate_walltime(cfg, value):
    """Apply the entry's optional hard limit without creating any artifacts."""
    from ag.approval import walltime_seconds
    requested = walltime_seconds(value)
    if 'max_walltime' in cfg['resources']:
        maximum = _max_walltime_seconds(cfg['resources']['max_walltime'])
        if requested > maximum:
            raise ConfigError('walltime exceeds resources.max_walltime')


def validate_cluster(cfg):
    if 'connect_timeout_seconds' in cfg.get('ssh', {}):
        value = cfg['ssh']['connect_timeout_seconds']
        if type(value) is not int or not 15 <= value <= 60:
            raise ConfigError('ssh.connect_timeout_seconds must be an integer from 15 to 60')
    if 'monitor_interval_seconds' in cfg:
        value = cfg['monitor_interval_seconds']
        if type(value) is not int or not 30 <= value <= 600:
            raise ConfigError('monitor_interval_seconds must be an integer from 30 to 600')
    if 'display_order' in cfg and type(cfg['display_order']) is not int:
        raise ConfigError('display_order must be an integer')
    if 'display_name' in cfg:
        value = cfg['display_name']
        if not isinstance(value, str) or not 1 <= len(value) <= 32 or not value.isprintable():
            raise ConfigError('display_name must contain 1–32 printable characters')
    scheduler = scheduler_kind(cfg)
    if scheduler not in ('pbs', 'slurm'):
        raise ConfigError('scheduler must be pbs or slurm')
    if 'scheduler_timezone' in cfg:
        if scheduler != 'pbs':
            raise ConfigError('scheduler_timezone is only supported for PBS')
        value = cfg['scheduler_timezone']
        if not isinstance(value, str):
            raise ConfigError('scheduler_timezone must be an IANA timezone name')
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ConfigError('scheduler_timezone must be a valid IANA timezone name') from exc
    # Named PBS configs use scheduler="pbs" plus queue; legacy retains its table.
    if scheduler == 'pbs' and cfg.get('scheduler') == 'pbs':
        cfg['scheduler'] = {'queue': cfg['queue']}
    allowed = cfg.get('allowed_templates')
    gaussian_only = (isinstance(allowed, list) and bool(allowed)
                     and all(t in ('gaussian', 'gaussian-cp') for t in allowed))
    has_xtb = 'xtb' in cfg['programs']
    if not has_xtb and not gaussian_only:
        raise ConfigError('programs.xtb.root is required unless allowed_templates contains only Gaussian templates')
    if not has_xtb and 'crest' in cfg['programs']:
        raise ConfigError('programs.crest requires programs.xtb.root')
    paths = [
        ('ssh', 'config_file', False), ('remote', 'allowed_root', True),
        ('remote', 'ag_root', True), ('programs.gaussian', 'g16root', True),
    ]
    if has_xtb:
        paths.append(('programs.xtb', 'root', True))
    for section, key, remote in paths:
        target = cfg
        for part in section.split('.'):
            target = target[part]
        target[key] = absolute(target[key], f'{section}.{key}', remote=remote)
    for section, key in [('ssh', 'host')] + ([('scheduler', 'queue')] if scheduler == 'pbs' else []):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg[section][key]):
            raise ConfigError(f'Invalid configuration: {section}.{key}')
    if cfg['remote']['ag_root'] != cfg['remote']['allowed_root'] + '/ag':
        raise ConfigError('remote.ag_root must equal remote.allowed_root/ag')
    if has_xtb:
        crest_executable(cfg['programs'])
    limit = cfg['resources']['max_cores']
    if type(limit) is not int or limit < 1:
        raise ConfigError('max_cores must be a positive integer')
    committed = cfg['resources'].get('max_committed_cores', limit)
    if type(committed) is not int or committed < limit:
        raise ConfigError('max_committed_cores must be an integer >= max_cores')
    cfg['resources']['max_committed_cores'] = committed
    for key in ('max_queued_cores', 'scheduler_max_running_cores'):
        if key in cfg['resources']:
            value = cfg['resources'][key]
            if type(value) is not int or value < 1:
                raise ConfigError(f'{key} must be a positive integer')
    memory_limit = cfg['resources'].get('pbs_max_mem_gb', 120)
    if 'pbs_max_mem_gb' in cfg['resources']:
        if scheduler != 'pbs':
            raise ConfigError('resources.pbs_max_mem_gb is only supported for PBS')
        if type(memory_limit) is not int or not 120 <= memory_limit <= 200:
            raise ConfigError('resources.pbs_max_mem_gb must be an integer from 120 to 200')
    if 'max_walltime' in cfg['resources']:
        _max_walltime_seconds(cfg['resources']['max_walltime'])
    tiers = cfg['resources']['tiers']
    if not isinstance(tiers, dict) or not all(name in tiers for name in RESOURCE_TIERS[:4]):
        raise ConfigError('Resource tiers require mini, simple, general and complex')
    for name in RESOURCE_TIERS:
        if name not in tiers:
            continue
        tier = tiers[name]
        if not isinstance(tier, dict):
            raise ConfigError(f'Invalid resource tier: {name}')
        if (type(tier['cores']) is not int or not 1 <= tier['cores'] <= limit
                or type(tier['mem_gb']) is not int or tier['mem_gb'] < 1
                or (scheduler == 'pbs' and tier['mem_gb'] > memory_limit)):
            raise ConfigError(f'Invalid resource tier: {name}')
    if not Path(cfg['ssh']['config_file']).is_file():
        raise ConfigError('SSH configuration file does not exist')
    if 'allowed_templates' in cfg:
        from ag.render import declaration
        allowed_templates = cfg['allowed_templates']
        if not isinstance(allowed_templates, list) or any(not isinstance(t, str) for t in allowed_templates):
            raise ConfigError('allowed_templates must be a list of reviewed template names')
        for template in allowed_templates:
            try:
                declaration(template)
            except ValueError as exc:
                raise ConfigError('allowed_templates contains an unknown template') from exc

    if scheduler == 'slurm':
        for key in ('partition', 'account', 'qos'):
            if key in cfg and (not isinstance(cfg[key], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg[key])):
                raise ConfigError(f'Invalid Slurm {key}')
        allowed = {'scheduler', 'ssh', 'remote', 'programs', 'resources', 'partition', 'account', 'qos', 'expires', 'allowed_templates', 'display_name', 'display_order', 'monitor_interval_seconds'}
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
    if 'multiwfn' in cfg['programs']:
        multiwfn_executable(cfg['programs'])
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
        if '_config_path' in cfg:
            selected['_config_path'] = cfg['_config_path']
        if 'approval' in cfg:
            selected['approval'] = cfg['approval']
        selected['_cluster_entries'] = cfg['clusters']
    else:
        if name != 'default':
            raise ConfigError(f'Cluster is not configured: {name}')
        selected = dict(cfg)
    selected['_cluster'] = name
    return selected


def cluster_identity(cfg):
    """Only explicit SSH configuration identity may share an admission cap."""
    return (scheduler_kind(cfg), Path(cfg['ssh']['config_file']).expanduser().resolve(),
            cfg['ssh']['host'])


def shared_clusters(cfg):
    """Selected entry plus peers on the same scheduler and SSH login alias.

    Keep ledgers separate; the selected entry carries the other configuration
    entries so for_manifest() cannot accidentally discard the shared cap.
    """
    name = cfg.get('_cluster', 'default')
    entries = dict(cfg.get('_cluster_entries', {name: cfg}))
    entries[name] = cfg
    identity = cluster_identity(cfg)
    return {other: dict(entry, local=cfg['local'], _config_dir=cfg['_config_dir'], _cluster=other)
            for other, entry in sorted(entries.items()) if cluster_identity(entry) == identity}


def committed_cap(cfg):
    return min(entry['resources'].get('max_committed_cores', entry['resources']['max_cores'])
               for entry in shared_clusters(cfg).values())


def optional_resource_caps(cfg):
    """Peer entries cannot bypass an explicitly configured queue allowance.

    The scheduler running limit is advisory metadata, never an ag guarantee.
    """
    entries = shared_clusters(cfg).values()
    result = {}
    for key in ('max_queued_cores', 'scheduler_max_running_cores'):
        values = [entry['resources'][key] for entry in entries if key in entry['resources']]
        if values:
            result[key] = min(values)
    return result


def shared_cap_summary(cfg):
    entries = shared_clusters(cfg)
    if len(entries) == 1:
        return ''
    limits = ', '.join(f"{name}={entry['resources'].get('max_committed_cores', entry['resources']['max_cores'])}"
                       for name, entry in entries.items())
    return f'同集群入口共享总上限 {committed_cap(cfg)} 核（取最小值；{limits}）'


def unmerged_clusters(cfg):
    candidates = {name: entry for name, entry in cfg.get('_cluster_entries', {}).items()
                  if scheduler_kind(entry) == scheduler_kind(cfg)
                  and cluster_identity(entry) != cluster_identity(cfg)}
    if not candidates:
        return []
    identity = ssh_identity(cfg)
    if identity is None:
        return []
    return sorted(name for name, entry in candidates.items() if ssh_identity(entry) == identity)


def ssh_identity(cfg):
    """Compare local SSH expansion, never scheduler kind alone or remote probes."""
    try:
        result = subprocess.run(
            ['ssh', '-G', '-F', cfg['ssh']['config_file'], cfg['ssh']['host']],
            capture_output=True, text=True, timeout=15)
        if result.returncode:
            return None
        fields = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] in ('hostname', 'port', 'user'):
                if len(parts) != 2 or parts[0] in fields:
                    return None
                fields[parts[0]] = parts[1]
        if set(fields) != {'hostname', 'port', 'user'} or not fields['port'].isdigit():
            return None
        port = int(fields['port'])
        if not 1 <= port <= 65535:
            return None
        return fields['hostname'].lower(), port, fields['user']
    except (OSError, subprocess.TimeoutExpired, UnicodeError, KeyError, TypeError):
        return None


def for_manifest(cfg, manifest):
    try:
        selected = select_cluster(cfg, manifest.get('cluster', 'default'))
        if scheduler_kind(selected) != manifest.get('scheduler', 'pbs'):
            raise ConfigError('Scheduler changed since preparation')
        return selected
    except ValueError as exc:
        raise ConfigError(f'Attempt {manifest.get("attempt_id", "<unknown>")}: {exc}') from exc
