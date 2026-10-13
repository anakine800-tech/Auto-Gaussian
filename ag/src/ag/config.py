"""Machine-local configuration. Never copy this configuration into a study."""
from pathlib import Path, PurePosixPath
import re
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


def load_config(path=None):
    path = Path(path) if path else Path.home() / '.config/ag/config.toml'
    try:
        with path.open('rb') as handle:
            cfg = tomllib.load(handle)
        for section, key, remote in (
            ('ssh', 'config_file', False), ('remote', 'allowed_root', True),
            ('remote', 'ag_root', True), ('programs.gaussian', 'g16root', True),
            ('programs.xtb', 'root', True), ('local', 'studies_root', False),
        ):
            target = cfg
            for part in section.split('.'):
                target = target[part]
            target[key] = absolute(target[key], f'{section}.{key}', remote=remote)
        for section, key in (('ssh', 'host'), ('scheduler', 'queue')):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', cfg[section][key]):
                raise ConfigError(f'Invalid configuration: {section}.{key}')
        if cfg['remote']['ag_root'] != cfg['remote']['allowed_root'] + '/ag':
            raise ConfigError('remote.ag_root must equal remote.allowed_root/ag')
        limit = cfg['resources']['max_cores']
        if type(limit) is not int or not 1 <= limit <= 44:
            raise ConfigError('max_cores must be between 1 and 44')
        for name in ('mini', 'simple', 'general', 'complex'):
            tier = cfg['resources']['tiers'][name]
            if (type(tier['cores']) is not int or not 1 <= tier['cores'] <= 44
                    or type(tier['mem_gb']) is not int or not 1 <= tier['mem_gb'] <= 120):
                raise ConfigError(f'Invalid resource tier: {name}')
        if not Path(cfg['ssh']['config_file']).is_file():
            raise ConfigError('SSH configuration file does not exist')
        studies = Path(cfg['local']['studies_root'])
        # Prevent accidentally committing studies into this or another Git checkout.
        if any((p / '.git').exists() for p in (studies, *studies.parents)):
            raise ConfigError('studies_root must be outside a Git checkout')
        cfg['_config_dir'] = str(path.parent)
        return cfg
    except (KeyError, TypeError, OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError('Missing or invalid local configuration') from exc
