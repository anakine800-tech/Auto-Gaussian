"""Synthetic ordinary-reactant geometries: no TS scientific evidence or jobs."""
import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem
from rdkit.Chem import rdDistGeom, rdMolDescriptors

from ag import attempt, catalog, catalog_v2, crest_input, geometry, study
from ag.transport import SSHTransport
from test_core import cfg

MODULE = Path(__file__).parents[1] / 'benchmarks/template_transfer/prototype.py'
spec = importlib.util.spec_from_file_location('t191_prototype', MODULE)
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


@pytest.fixture
def template(tmp_path):
    mol = p.molecule(p.DATA['template']['reactant'])
    params = rdDistGeom.ETKDGv3()
    params.randomSeed = 191
    assert rdDistGeom.EmbedMolecule(mol, params) == 0
    frame = geometry.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
                           tuple(map(tuple, mol.GetConformer().GetPositions())),
                           'Synthetic ordinary reactant; NOT a TS')
    path = tmp_path / 'synthetic-template.xyz'
    geometry.write_xyz(path, [frame])
    description = dict(template_id='B-trans-outward', reactant=p.DATA['template']['reactant'],
                       sha256=sha256(path.read_bytes()).hexdigest(),
                       row_by_atom=list(range(1, mol.GetNumAtoms() + 1)),
                       source=dict(status='synthetic-test-only',
                                   location='ETKDGv3 seed 191, ordinary reactant; no TS evidence'))
    return path, description


def generate(template, out, pair='B-C'):
    path, description = template
    return p.generate(pair, template_xyz=path, description=description,
                      output_dir=out, force_constant=0.5)


@pytest.mark.parametrize('pair,formula,count', [
    ('B-C', 'C7H8O2', 17), ('B-D', 'C11H10O2', 23),
    ('B-E', 'C5H5N3O2', 15), ('B-F', 'C6H8O3', 17)])
def test_fixed_pairs_maps_stereo_and_generation(template, tmp_path, pair, formula, count):
    record = next(row for row in p.DATA['pairs'] if row['id'] == pair)
    left, right = [p.molecule(record[side]) for side in ('reactant', 'product')]
    assert rdMolDescriptors.CalcMolFormula(left) == rdMolDescriptors.CalcMolFormula(right) == formula
    assert left.GetNumAtoms() == right.GetNumAtoms() == count
    assert set(p.map_indices(left)) == set(p.map_indices(right))
    assert sorted(dict(Chem.FindMolChiralCenters(left)).values()) == ['S', 'S']
    assert [str(b.GetStereo()) for b in right.GetBonds() if b.GetStereo() != Chem.BondStereo.STEREONONE] == ['STEREOE', 'STEREOE']
    bonds = lambda mol: {tuple(sorted((b.GetBeginAtom().GetAtomMapNum(), b.GetEndAtom().GetAtomMapNum()))):
                         b.GetBondTypeAsDouble() for b in mol.GetBonds()
                         if b.GetBeginAtom().GetAtomMapNum() and b.GetEndAtom().GetAtomMapNum()}
    before, after = bonds(left), bonds(right)
    assert {k: (before.get(k), after.get(k)) for k in before.keys() | after.keys()
            if before.get(k) != after.get(k)} == {(1, 2): (1.0, None), (2, 3): (1.0, 2.0),
                                                  (3, 4): (2.0, 1.0), (1, 4): (1.0, 2.0)}
    out = tmp_path / pair
    report = generate(template, out, pair)
    assert catalog_v2.xyz((out / 'guess.xyz').read_bytes()) == (count, formula)
    crest_input.validate((out / 'constraints.inp').read_text(), count)
    assert report['template']['source']['status'] == 'synthetic-test-only'
    assert report['core_max_error_angstrom'] < 0.02
    frame = geometry.read_xyz(out / 'guess.xyz')[0]
    p.check_geometry(left, frame.coordinates)
    # Constraints use actual output row indices, not the mapped SMILES numbers.
    source = geometry.read_xyz(template[0])[0]
    source_map = p.map_indices(p.molecule(p.DATA['template']['reactant']))
    target_map = p.map_indices(left)
    for m in p.CORE:
        assert np.linalg.norm(np.array(frame.coordinates[target_map[m]]) - source.coordinates[source_map[m]]) < 0.02
    for line in (out / 'constraints.inp').read_text().splitlines():
        if 'distance:' in line:
            i, j, value = line.split(':')[1].split(',')
            actual = np.linalg.norm(np.array(frame.coordinates[int(i)-1]) - frame.coordinates[int(j)-1])
            assert actual == pytest.approx(float(value), abs=0.04)
    frozen = {f.name: f.read_bytes() for f in out.iterdir()}
    with pytest.raises(FileExistsError):
        generate(template, out, pair)
    assert frozen == {f.name: f.read_bytes() for f in out.iterdir()}


@pytest.mark.parametrize('damage,match', [
    ('cis', 'stereochemistry'), ('other-template', 'Inapplicable'),
    ('duplicate-row', 'mapping'), ('missing-row', 'mapping'),
    ('source-missing', 'source'), ('hash', 'hash'), ('element', 'element')])
def test_bad_template_is_refused(template, tmp_path, damage, match):
    path, desc = template
    desc = copy.deepcopy(desc)
    if damage == 'cis':
        desc['reactant'] = desc['reactant'].replace('[C@H:2]', '[C@@H:2]')
    elif damage == 'other-template':
        desc['template_id'] = 'unrelated-reaction'
    elif damage == 'duplicate-row':
        desc['row_by_atom'][0] = desc['row_by_atom'][1]
    elif damage == 'missing-row':
        desc['row_by_atom'].pop()
    elif damage == 'source-missing':
        desc['source'] = {}
    elif damage == 'hash':
        desc['sha256'] = '0' * 64
    else:
        desc['row_by_atom'][0], desc['row_by_atom'][1] = desc['row_by_atom'][1], desc['row_by_atom'][0]
    with pytest.raises(ValueError, match=match):
        generate((path, desc), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


@pytest.mark.parametrize('damage,match', [('mirror', 'stereochemistry'), ('overlap', 'Collision')])
def test_template_coordinates_checked_independently_of_smiles(template, tmp_path, damage, match):
    path, desc = template
    mol = p.molecule(desc['reactant'])
    xyz = np.array(geometry.read_xyz(path)[0].coordinates)
    if damage == 'mirror':
        xyz[:, 0] *= -1
    else:
        xyz[-1] = xyz[0]
    mutated = tmp_path / 'mutated.xyz'
    geometry.write_xyz(mutated, [geometry.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()), tuple(map(tuple, xyz)))])
    desc = dict(desc, sha256=sha256(mutated.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match=match):
        generate((mutated, desc), tmp_path / 'bad')
    assert not (tmp_path / 'bad').exists()


def test_missing_maps_and_out_of_scope_pair(template, tmp_path):
    with pytest.raises(ValueError, match='maps'):
        p.molecule('[CH3:1][CH3:1]')
    with pytest.raises(ValueError, match='fixed four'):
        generate(template, tmp_path / 'bad', pair='new-case')
    path, desc = template
    for constant in (0, -1, float('nan'), float('inf')):
        with pytest.raises(ValueError):
            p.generate('B-C', template_xyz=path, description=desc, output_dir=tmp_path/'bad', force_constant=constant)


def test_sample_hash_binds_loaded_graph_snapshot(template, tmp_path, monkeypatch):
    changed = tmp_path / 'changed-pairs.json'
    changed.write_text('{}')
    monkeypatch.setattr(p, 'DATA_PATH', changed)
    report = generate(template, tmp_path / 'snapshot')
    assert report['pairs_sha256'] == sha256(p.DATA_BYTES).hexdigest()
    assert report['pairs_sha256'] != sha256(changed.read_bytes()).hexdigest()


def test_local_catalog_and_xtb_prepare_only(template, tmp_path, cfg, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline benchmark must not construct SSHTransport')
    monkeypatch.setattr(SSHTransport, '__init__', forbidden)
    out = tmp_path / 'guess'
    generate(template, out)
    study.init(cfg, 't191-synthetic')
    root = study.locate(cfg, 't191-synthetic')
    catalog.change(root, 'object', id='target', name='Synthetic benchmark target',
                   formula='C7H8O2', charge='0', multiplicity=1, upgrade_catalog=True)
    catalog.change(root, 'candidate', object='target', id='guess-01',
                   xyz=out/'guess.xyz', origin='template-transform',
                   parent_file=template[0], transform_json=out/'transform.json',
                   doi=p.DATA['doi'], si_location='Synthetic interface test; not an SI geometry')
    manifest = attempt.prepare(cfg, study_name='t191-synthetic', template='xtb',
                               input_path=out/'guess.xyz', constraints=out/'constraints.inp',
                               tier='mini', walltime='00:10:00', label='guess',
                               params={'--gfn': '2', '--opt': 'tight', '--chrg': '0', '--uhf': '0'},
                               method_basis='兜底方法：仅合成离线接口验证，未运行计算')
    path = attempt.find(cfg, manifest['attempt_id'])
    files = attempt.verified_files(cfg, path, manifest)
    assert files['constraints.inp'] == (out/'constraints.inp').read_bytes()
    assert manifest['template_params']['--input'] == 'constraints.inp'
    assert not (path/'.submit-claim').exists()
    assert not (path/'submission.json').exists()


@pytest.mark.parametrize('pair', ['B-C', 'B-D', 'B-E', 'B-F'])
def test_published_seed_preserves_checks_and_evidence_status(tmp_path, pair):
    # Public SI S17, not a live calculation. This is a known refusal, not success.
    root = MODULE.parent
    description = json.loads((root / 'B_TS_trans_1.source.json').read_text())
    try:
        result = p.generate(pair, template_xyz=root / 'B_TS_trans_1.xyz', description=description,
                            output_dir=tmp_path / pair, force_constant=0.5)
    except ValueError as exc:
        assert 'Constrained embedding failed' in str(exc)
        assert not (tmp_path / pair).exists()
    else:
        # Another RDKit version may embed it; scientific status must not change.
        assert result['template']['source']['status'] == 'unvalidated-source-geometry'
        assert result['core_max_error_angstrom'] < 0.02
        frame = geometry.read_xyz(tmp_path / pair / 'guess.xyz')[0]
        p.check_geometry(p.molecule(result['pair']['reactant']), frame.coordinates)
