"""T162 declarations use synthetic local evidence; no chemical matching."""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from ag import g0_mapping as mapping


ELEMENTS = ['O', 'H', 'H']
TARGET = dict(kind='reference', attempt='synthetic-input', source=dict(
    file='attempts/synthetic-input/manifest.json', sha256='b' * 64,
    json_pointer='/science/geometry'))


def entry():
    return dict(object='water', candidate='guess', candidate_sha256='a' * 64,
                target=deepcopy(TARGET), candidate_to_target=[1, 3, 2])


def resolve(entries, elements=ELEMENTS, target_elements=ELEMENTS):
    return mapping.resolve(dict(entries=entries, sha256='c' * 64), 'water',
                           dict(id='guess', sha256='a' * 64), elements,
                           dict(reference=(TARGET, target_elements), frequency=(None, None)))


def test_runtime_byte_hash_and_complete_permutation(tmp_path):
    path = tmp_path / 'mapping.json'
    raw = json.dumps(dict(mappings=[entry()]), indent=2).encode() + b'\n'
    path.write_bytes(raw)
    data = mapping.read(path)
    assert data['sha256'] == sha256(raw).hexdigest()
    result = resolve(data['entries'])
    assert result['reference']['status'] == 'declared_verified'
    assert result['reference']['candidate_to_target'] == [1, 3, 2]
    assert result['reference']['json_pointer'] == '/mappings/0'
    assert result['frequency']['status'] == 'unverified'
    assert '不证明化学身份' in result['reference']['limitation']
    assert path.read_bytes() == raw


@pytest.mark.parametrize('permutation', [None, [], [1, 2], [1, 2, 2], [0, 2, 3],
                                      [1, 2, 4], [1, 2, True], [1, 2, 3.0], ['1', 2, 3],
                                      [1, 2, 3, 4], {'1': 1, '2': 2, '3': 3}, [2, 1, 3]])
def test_invalid_bijection_is_typed(permutation):
    value = entry()
    value['candidate_to_target'] = permutation
    with pytest.raises(mapping.AtomMappingError) as error:
        resolve([value])
    assert error.value.category == 'invalid_atom_mapping'


@pytest.mark.parametrize('change,category,reason', [
    ('missing', 'invalid_atom_mapping', 'missing'),
    ('self_hash', 'invalid_atom_mapping', 'unknown'),
    ('candidate_hash', 'atom_mapping_binding_mismatch', 'candidate SHA-256'),
    ('attempt', 'atom_mapping_binding_mismatch', 'attempt'),
    ('source_hash', 'atom_mapping_binding_mismatch', 'source.sha256'),
    ('pointer', 'atom_mapping_binding_mismatch', 'source.json_pointer'),
    ('path', 'atom_mapping_binding_mismatch', 'source.file'),
    ('source_type', 'invalid_atom_mapping', 'source must'),
    ('kind_type', 'invalid_atom_mapping', 'target requires'),
    ('duplicate', 'invalid_atom_mapping', 'not unique'),
    ('count', 'invalid_atom_mapping', 'atom counts')])
def test_invalid_declaration_and_target_bindings(change, category, reason):
    value = entry()
    entries, target_elements = [value], ELEMENTS
    if change == 'missing':
        value.pop('candidate_to_target')
    elif change == 'self_hash':
        value['sha256'] = 'd' * 64
    elif change == 'candidate_hash':
        value['candidate_sha256'] = 'd' * 64
    elif change == 'attempt':
        value['target']['attempt'] = 'another-input'
    elif change == 'source_hash':
        value['target']['source']['sha256'] = 'd' * 64
    elif change == 'pointer':
        value['target']['source']['json_pointer'] = '/science/structures/0/geometry'
    elif change == 'path':
        value['target']['source']['file'] = '../other.json'
    elif change == 'source_type':
        value['target']['source'] = []
    elif change == 'kind_type':
        value['target']['kind'] = []
    elif change == 'duplicate':
        entries.append(deepcopy(value))
    else:
        target_elements = ELEMENTS[:2]
    with pytest.raises(mapping.AtomMappingError, match=reason) as error:
        resolve(entries, target_elements=target_elements)
    assert error.value.category == category
    assert error.value.source['mapping_sha256'] == 'c' * 64
    assert '../other' not in str(error.value)  # never emit an untrusted path


def test_entries_match_object_candidate_and_exact_target_not_position():
    unrelated = dict(entry(), object='other-object', candidate_to_target=[])
    result = resolve([unrelated, entry()])
    assert result['reference']['json_pointer'] == '/mappings/1'
    assert resolve([dict(entry(), candidate='other-candidate')])['reference']['status'] == 'unverified'
    wrong_kind = entry()
    wrong_kind['target']['kind'] = 'frequency'
    with pytest.raises(mapping.AtomMappingError, match='unavailable'):
        resolve([wrong_kind])


@pytest.mark.parametrize('content', ['{}', '{', '{"mappings":[null]}',
                                    '{"mappings":[{"object":"water"}]}',
                                    '{"mappings":[],"sha256":"self"}'])
def test_unlocatable_file_errors_are_global(tmp_path, content):
    path = tmp_path / 'bad.json'
    path.write_text(content)
    with pytest.raises(ValueError) as error:
        mapping.read(path)
    assert not isinstance(error.value, mapping.AtomMappingError)


def test_mapping_symlink_is_global(tmp_path):
    path = tmp_path / 'map.json'
    path.write_text('{"mappings":[]}')
    link = tmp_path / 'link.json'
    link.symlink_to(path)
    with pytest.raises(ValueError, match='Symbolic') as error:
        mapping.read(link)
    assert not isinstance(error.value, mapping.AtomMappingError)
