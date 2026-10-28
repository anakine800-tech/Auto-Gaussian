"""Explicit, source-bound G0 atom declarations; never chemical matching."""
from copy import deepcopy
from hashlib import sha256
import json
import re

from ag import catalog_v2 as v2, study


LIMITATION = ('仅校验声明映射的格式、完整双射、元素和来源绑定；'
              '不证明化学身份对应，重复元素仍可能由人填错，须人工审阅。')
DIRECTION = 'candidate_to_target: candidate 1-based index -> target 1-based index'


class AtomMappingError(ValueError):
    """Only declaration errors are recoverable; source I/O stays outside."""

    def __init__(self, reason, *, category, attempt=None, source=None):
        super().__init__(reason)
        self.category = category
        self.attempt = attempt
        self.source = source


def read(filename):
    if filename is None:
        return None
    # Use the same regular-file/no-symlink reader as candidate archives.
    raw = v2.read_bytes(filename, 1024 * 1024)
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'mappings'} or not isinstance(data['mappings'], list):
        raise ValueError('Atom mapping file requires only a mappings list')
    for entry in data['mappings']:
        # An unlocatable entry cannot safely be assigned to a candidate.
        if not isinstance(entry, dict):
            raise ValueError('Atom mapping entry requires object and candidate IDs')
        for key in ('object', 'candidate'):
            study.identifier(entry.get(key))
    return dict(entries=data['mappings'], sha256=sha256(raw).hexdigest())


def reference_target(source):
    if source is None:
        return None
    identity = source['attempt']
    if 'input_sha256' in source:
        binding = dict(file=source['input_file'], sha256=source['input_sha256'],
                       frame=source['geometry_frame'], manifest_sha256=source['manifest_sha256'])
    elif 'json_pointer' in source:
        binding = dict(file=f'attempts/{identity}/manifest.json', sha256=source['manifest_sha256'],
                       json_pointer=source['json_pointer'])
    else:
        return None
    return dict(kind='reference', attempt=identity, source=binding)


def frequency_target(frequency):
    if frequency is None:
        return None
    source = frequency['source']
    return dict(kind='frequency', attempt=frequency['attempt'], source=dict(
        file=source['log'], sha256=source['log_sha256'],
        start_line=source['section']['start_line'], end_line=source['section']['end_line'],
        section_sha256=source['section_sha256']))


def unverified(kind, target=None):
    return dict(status='unverified', target=target, direction=DIRECTION, limitation=LIMITATION,
                reason=f'身份对应未核实：缺少绑定当前 {kind} 来源的 --atom-mapping 声明')


def resolve(config, object_id, candidate, elements, targets):
    """Validate this candidate after all requested source evidence was read.

    targets maps each kind to (actual target descriptor, target elements).
    No declaration is ever used as a file path or as an Attempt selector.
    """
    reports = {kind: unverified(kind, target) for kind, (target, _) in targets.items()}
    if config is None:
        return reports
    for report in reports.values():
        report['mapping_sha256'] = config['sha256']
    seen = set()
    for index, entry in enumerate(config['entries']):
        if (entry['object'], entry['candidate']) != (object_id, candidate['id']):
            continue
        provenance = dict(mapping_sha256=config['sha256'], json_pointer=f'/mappings/{index}',
                          candidate_sha256=candidate['sha256'])
        target = entry.get('target')
        kind = target.get('kind') if isinstance(target, dict) else None
        actual, target_elements = targets.get(kind, (None, None)) if isinstance(kind, str) else (None, None)
        provenance['target'] = actual

        def fail(reason, *, binding=False):
            raise AtomMappingError(reason, category=('atom_mapping_binding_mismatch' if binding else
                                                     'invalid_atom_mapping'),
                                   attempt=actual['attempt'] if actual else None, source=provenance)

        if set(entry) != {'object', 'candidate', 'candidate_sha256', 'target', 'candidate_to_target'}:
            fail('Atom mapping entry has missing or unknown fields')
        if (not isinstance(target, dict) or set(target) != {'kind', 'attempt', 'source'} or
                not isinstance(kind, str) or kind not in targets):
            fail('Atom mapping target requires kind reference/frequency, attempt and source')
        if kind in seen:
            fail('Atom mapping target is not unique for this candidate and target kind')
        seen.add(kind)
        if not isinstance(target['source'], dict) or not isinstance(target['attempt'], str):
            fail('Atom mapping target source must be an object and attempt must be an ID')
        digest = entry['candidate_sha256']
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            fail('Atom mapping candidate_sha256 must be a SHA-256 digest')
        if digest != candidate['sha256']:
            fail('Atom mapping candidate SHA-256 binding mismatch', binding=True)
        if actual is None or target_elements is None:
            fail('Atom mapping target is unavailable or not selected for this diagnosis', binding=True)
        if json.dumps(target, sort_keys=True) != json.dumps(actual, sort_keys=True):
            different = [key for key in ('kind', 'attempt') if target[key] != actual[key]]
            if set(target['source']) != set(actual['source']):
                different.append('source fields')
            different.extend('source.' + key for key, value in actual['source'].items()
                             if json.dumps(target['source'].get(key)) != json.dumps(value))
            fail(f'Atom mapping {kind} target binding mismatch: ' + ', '.join(different), binding=True)
        permutation = entry['candidate_to_target']
        count = len(elements)
        if (not isinstance(permutation, list) or len(permutation) != count or len(target_elements) != count or
                any(type(i) is not int or i < 1 or i > count for i in permutation) or
                len(set(permutation)) != count):
            fail('Atom mapping requires a complete 1-based integer bijection with matching atom counts')
        if any(symbol != target_elements[i - 1] for symbol, i in zip(elements, permutation)):
            fail('Atom mapping elements disagree at the declared corresponding indices')
        reports[kind] = dict(status='declared_verified', direction=DIRECTION, limitation=LIMITATION,
                             reason='声明映射的格式与来源绑定已校验；化学对应仍须人审',
                             candidate_to_target=list(permutation), **deepcopy(provenance))
    return reports
