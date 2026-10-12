"""Pinned startup registration only; HTTP never supplies filesystem paths."""
import json
from pathlib import Path

from auto_g16.execution.readonly import ProgramReadSnapshot
from auto_g16.query import NativeQueryService, NativeSource
from auto_g16.conformer.readonly import load_opt_readout
from auto_g16.conformer.frequency_readonly import load_freq_readout
from .archive import read_pinned


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate registration key')
        value[key] = item
    return value


def load_native_sources(path: Path, digest: str) -> tuple[NativeSource, ...]:
    """Reuse the existing bounded no-follow reader; never open a business store."""
    data = json.loads(read_pinned(path, digest, limit=256 * 1024), object_pairs_hook=_object)
    if (type(data) is not dict or set(data) != {'schema', 'sources'}
            or data['schema'] not in {'autog-native-source-registration/1', 'autog-native-source-registration/2', 'autog-native-source-registration/3', 'autog-native-source-registration/4', 'autog-native-source-registration/5'}
            or type(data['sources']) is not list or not 1 <= len(data['sources']) <= 32):
        raise ValueError('invalid native registry')
    sources = []
    for entry in data['sources']:
        keys = {'source_id', 'database', 'snapshots'}
        if data['schema'] != 'autog-native-source-registration/1':
            keys.add('opt_readout')
        if data['schema'] in {'autog-native-source-registration/3', 'autog-native-source-registration/4', 'autog-native-source-registration/5'}:
            keys.add('freq_readout')
        if data['schema'] in {'autog-native-source-registration/4', 'autog-native-source-registration/5'}:
            keys.add('thermodynamic_readout')
        if data['schema'] == 'autog-native-source-registration/5':
            keys.add('population_readout')
        if (type(entry) is not dict or set(entry) != keys
                or type(entry['database']) is not str or type(entry['snapshots']) is not list
                or len(entry['snapshots']) > 64):
            raise ValueError('invalid native source')
        snapshots = []
        for snapshot in entry['snapshots']:
            if (type(snapshot) is not dict or set(snapshot) != {'path', 'sha256'}
                    or type(snapshot['path']) is not str or type(snapshot['sha256']) is not str):
                raise ValueError('invalid snapshot registration')
            content = read_pinned(Path(snapshot['path']), snapshot['sha256'], limit=16 * 1024 * 1024)
            snapshots.append(ProgramReadSnapshot(content=content, sha256=snapshot['sha256']))
        opt_readout = None
        descriptor = entry.get('opt_readout')
        if descriptor is not None:
            if (type(descriptor) is not dict or set(descriptor) != {'path', 'sha256'}
                    or type(descriptor['path']) is not str or type(descriptor['sha256']) is not str):
                raise ValueError('invalid Opt readout descriptor')
            content = read_pinned(Path(descriptor['path']), descriptor['sha256'], limit=1024 * 1024)
            opt_readout = load_opt_readout(content, descriptor['sha256'])
        freq_readout = None
        descriptor = entry.get('freq_readout')
        if descriptor is not None:
            if (type(descriptor) is not dict or set(descriptor) != {'path', 'sha256'}
                    or type(descriptor['path']) is not str or type(descriptor['sha256']) is not str):
                raise ValueError('invalid Freq readout descriptor')
            content = read_pinned(Path(descriptor['path']), descriptor['sha256'], limit=2 * 1024 * 1024)
            freq_readout = load_freq_readout(content, descriptor['sha256'])
        extra = {}
        if data['schema'] in {'autog-native-source-registration/4', 'autog-native-source-registration/5'}:
            thermodynamic_readout = None
            descriptor = entry['thermodynamic_readout']
            if descriptor is not None:
                if (type(descriptor) is not dict or set(descriptor) != {'path', 'sha256'}
                        or type(descriptor['path']) is not str or type(descriptor['sha256']) is not str):
                    raise ValueError('invalid thermodynamic readout descriptor')
                from auto_g16.conformer.thermochemistry_readonly import load_native_thermodynamic_readout
                content = read_pinned(Path(descriptor['path']), descriptor['sha256'], limit=1024 * 1024)
                thermodynamic_readout = load_native_thermodynamic_readout(content, descriptor['sha256'])
            extra['thermodynamic_readout'] = thermodynamic_readout
        if data['schema'] == 'autog-native-source-registration/5':
            descriptor = entry['population_readout']
            if descriptor is not None:
                if (type(descriptor) is not dict or set(descriptor) != {'path', 'sha256'}
                        or type(descriptor['path']) is not str or type(descriptor['sha256']) is not str):
                    raise ValueError('invalid population readout descriptor')
                if extra['thermodynamic_readout'] is None or freq_readout is None:
                    raise ValueError('population registration requires thermodynamic and Freq readouts')
                from auto_g16.conformer.populations_readonly import load_native_population_readout
                content = read_pinned(Path(descriptor['path']), descriptor['sha256'], limit=1024 * 1024)
                extra['population_readout'] = load_native_population_readout(content, descriptor['sha256'])
        sources.append(NativeSource(source_id=entry['source_id'], database=Path(entry['database']),
                                    snapshots=tuple(snapshots), opt_readout=opt_readout,
                                    freq_readout=freq_readout, **extra))
    result = tuple(sources)
    NativeQueryService(result)  # Owning validation rejects duplicate aliases and database paths.
    return result
