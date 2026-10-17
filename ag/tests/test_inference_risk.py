"""T68 synthetic inference audit: explicit-graph oracles, no research inputs.

Fixtures are frozen XYZs. Regenerate into an EMPTY directory with:
  PYTHONPATH=ag/src python ag/tests/test_inference_risk.py --generate-fixtures DIR
Generation uses explicit SMILES, ETKDGv3(seed=6801), UFF(maxIters=2000),
then documented coordinate transforms. It never calls infer_molecule.
"""
from dataclasses import replace
import json
import math
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdDetermineBonds

from ag import geometry as geo, irc_compare as irc, topology
from ag.cli import main

FIXTURES = Path(__file__).parent / 'fixtures' / 'inference'
# Atom order is the SMILES parser's order, followed by Chem.AddHs order.
SMILES = {
    'nbpin': 'CC1(C)OB(N2C=CCC=C2)OC1(C)C',
    'acetone_bf3': 'CC(=[O+][B-](F)(F)F)C',
    'ester_bh3': 'COC(C)=[O+][BH3-]',
    # Nitro O initially carries -1; donation neutralizes it (NOT O+).
    'nitro_bh3': 'C[N+](=O)O[BH3-]',
    'nitronate': '[CH2-][N+](=O)[O-]',
    'nitromethane': 'C[N+](=O)[O-]',
    'enolate': 'C=C([O-])C',
    'ketone': 'CC(=O)C',
    'zw_open': '[NH2+]=CCC([O-])=C',
    'zw_closed': 'NC1CC(=O)C1',
    'boron_adjacent': '[BH2][C@H](F)C',
    'borate': '[B@-](F)(Cl)(Br)I',
}
ADDUCTS = ('acetone_bf3', 'ester_bh3', 'nitro_bh3')
CHIRAL = ('boron_adjacent', 'borate')
PROTONATIONS = {'nitronate': 'nitromethane', 'enolate': 'ketone'}


def explicit(name):
    return Chem.AddHs(Chem.MolFromSmiles(SMILES[name]))


def separated_oracle(name):
    mol = Chem.RWMol(explicit(name))
    boron = next(a for a in mol.GetAtoms() if a.GetSymbol() == 'B')
    oxygen = next(a for a in boron.GetNeighbors() if a.GetSymbol() == 'O')
    mol.RemoveBond(boron.GetIdx(), oxygen.GetIdx())
    boron.SetFormalCharge(0)
    oxygen.SetFormalCharge(oxygen.GetFormalCharge() - 1)
    Chem.SanitizeMol(mol)
    return mol.GetMol()


def protonated_oracle(name):
    """Keep anion atoms in place in the index map; append F and transferred H."""
    base, acid = explicit(name), explicit(PROTONATIONS[name])
    mapping = []
    for atom in base.GetAtoms():
        if atom.GetAtomicNum() != 1:
            mapping.append(atom.GetIdx())
            continue
        owner = atom.GetNeighbors()[0].GetIdx()
        old_h = [a.GetIdx() for a in base.GetAtomWithIdx(owner).GetNeighbors() if a.GetAtomicNum() == 1]
        new_h = [a.GetIdx() for a in acid.GetAtomWithIdx(owner).GetNeighbors() if a.GetAtomicNum() == 1]
        mapping.append(new_h[old_h.index(atom.GetIdx())])
    extra = sorted(set(range(acid.GetNumAtoms())) - set(mapping))
    assert len(extra) == 1
    combined = Chem.CombineMols(acid, Chem.MolFromSmiles('[F-]'))
    return Chem.RenumberAtoms(combined, mapping + [acid.GetNumAtoms()] + extra)


def oracle(name):
    if name in SMILES:
        return explicit(name)
    if name == 'nbpin_perturbed':
        return explicit('nbpin')
    if name.endswith('_mirror'):
        mol = explicit(name.removesuffix('_mirror'))
        for atom in mol.GetAtoms():
            atom.InvertChirality()
        return mol
    if name.endswith('_separated'):
        return separated_oracle(name.removesuffix('_separated'))
    if name.endswith('_hf'):
        return Chem.CombineMols(explicit(name.removesuffix('_hf')), Chem.AddHs(Chem.MolFromSmiles('F')))
    if name.endswith('_protonated_f'):
        return protonated_oracle(name.removesuffix('_protonated_f'))
    raise ValueError(name)


MODELS = (tuple(SMILES) + ('nbpin_perturbed',)
          + tuple(n + '_separated' for n in ADDUCTS)
          + tuple(n + '_mirror' for n in CHIRAL)
          + tuple(n + suffix for n in PROTONATIONS for suffix in ('_hf', '_protonated_f')))
PAIRS = [('nbpin', 'nbpin_perturbed', 'unchanged', None)] + [
    (n, n + '_separated', 'changed', 'fragment') for n in ADDUCTS] + [
    (n + '_hf', n + '_protonated_f', 'changed', 'proton') for n in PROTONATIONS] + [
    ('zw_open', 'zw_closed', 'changed', 'ring')] + [
    (n, n + '_mirror', 'changed', 'stereo') for n in CHIRAL]


def frame(name):
    return geo.read_xyz(FIXTURES / (name + '.xyz'))[0]


def infer(value, charge):
    return geo.infer_molecule(value, charge, Chem, rdDetermineBonds)


def bonds(mol):
    return {tuple(sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx()))): b.GetBondTypeAsDouble()
            for b in mol.GetBonds()}


def charges(mol):
    return tuple(a.GetFormalCharge() for a in mol.GetAtoms())


def signature(mol):
    return bonds(mol), charges(mol)


def acceptable_oracles(name):
    result = [oracle(name)]
    # Same nuclei/protons/electrons, alternate resonance form, not a tautomer.
    if name in ('nitronate', 'nitronate_hf'):
        alternative = Chem.AddHs(Chem.MolFromSmiles('C=[N+]([O-])[O-]'))
        if name.endswith('_hf'):
            alternative = Chem.CombineMols(alternative, Chem.AddHs(Chem.MolFromSmiles('F')))
        result.append(alternative)
    return result


def perturb(value):
    return replace(value, coordinates=tuple(
        tuple(x + (1 if (i + j) % 2 else -1) * 0.0001 for j, x in enumerate(row))
        for i, row in enumerate(value.coordinates)))


def source(value, charge):
    return dict(frame=value, facts=dict(charge=charge, multiplicity=1))


def write_attempt(root, name, before, after, charge, *, endpoint=False):
    path = root / 'attempts' / name
    path.mkdir(parents=True)
    rows = '\n'.join(geo.xyz_text([before]).splitlines()[2:])
    (path / 'manifest.json').write_text(json.dumps(dict(
        attempt_id=name, template='gaussian', science=dict(
            charge=charge, multiplicity=1, route='# hf/sto-3g opt freq', geometry=rows))))
    facts = dict(charge=charge, multiplicity=1, n_imag=0,
                 final_geometry='final_input.xyz', opt_converged=False)
    if endpoint:
        facts['irc'] = dict(end_geometry='final_input.xyz')
    (path / 'facts.json').write_text(json.dumps(facts))
    (path / 'final_input.xyz').write_text(geo.xyz_text([after]))
    return path


def snapshot(root):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('name', MODELS)
def test_inferred_identity_against_explicit_graph(name):
    expected = oracle(name)
    value = frame(name)
    assert value.symbols == tuple(a.GetSymbol() for a in expected.GetAtoms())
    charge = Chem.GetFormalCharge(expected)
    actual = infer(value, charge)
    # An unchanged report alone is never the identity oracle.
    assert Chem.GetFormalCharge(actual) == charge
    assert signature(actual) in [signature(m) for m in acceptable_oracles(name)]
    assert geo.graph_key(actual, Chem) in [geo.graph_key(m, Chem) for m in acceptable_oracles(name)]
    assert Chem.GetMolFrags(actual) == Chem.GetMolFrags(expected)
    if name.removesuffix('_mirror') in CHIRAL:
        assert geo.stereo_key(actual, Chem) == geo.stereo_key(expected, Chem)


@pytest.mark.parametrize('name', MODELS)
def test_microperturbation_preserves_identity_and_stereo(name):
    value = frame(name)
    charge = Chem.GetFormalCharge(oracle(name))
    before, after = infer(value, charge), infer(perturb(value), charge)
    assert signature(before) == signature(after)
    assert geo.graph_key(before, Chem) == geo.graph_key(after, Chem)
    assert geo.stereo_key(before, Chem) == geo.stereo_key(after, Chem)
    report = topology.compare_minimum(value, perturb(value), charge)
    assert report['status'] == 'unchanged', report
    assert report['bond_order_and_stereo_assessment']['status'] == 'evaluated'
    assert irc.compare_endpoint(source(perturb(value), charge), source(value, charge), charge)['status'] == irc.MATCH


@pytest.mark.parametrize('name', CHIRAL)
def test_enantiomers_have_same_graph_and_distinct_stereo(name):
    charge = Chem.GetFormalCharge(oracle(name))
    before, after = (infer(frame(n), charge) for n in (name, name + '_mirror'))
    assert geo.graph_key(before, Chem) == geo.graph_key(after, Chem)
    assert geo.stereo_key(before, Chem) != geo.stereo_key(after, Chem)


@pytest.mark.parametrize('before_name,after_name,status,reason', PAIRS)
def test_topology_cli_pairs(tmp_path, capsys, before_name, after_name, status, reason):
    before, after = frame(before_name), frame(after_name)
    charge = Chem.GetFormalCharge(oracle(before_name))
    assert Chem.GetFormalCharge(oracle(after_name)) == charge
    path = write_attempt(tmp_path, 'synthetic', before, after, charge)
    baseline = snapshot(path)
    out = tmp_path / 'topology.json'
    assert main(['topology', str(path), '--out', str(out), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(out.read_text())
    assert report['mode'] == 'minimum' and report['status'] == status
    assert snapshot(path) == baseline
    assert topology.NOTICE in out.with_suffix('.md').read_text()
    if reason == 'fragment':
        assert [report['fragments'][side]['count'] for side in ('submitted', 'final')] == [1, 2]
        assert any('片段数变化：1 → 2' in r for r in report['reasons'])
        expected_removed = set(bonds(oracle(before_name))) - set(bonds(oracle(after_name)))
        assert {tuple(i - 1 for i in d['atoms']) for d in report['bond_differences']} == expected_removed
    elif reason == 'proton':
        hydrogen = len(before.symbols)
        fluorine = hydrogen - 1
        assert report['proton_differences'] == [dict(
            hydrogen=hydrogen, reference_owners=[fluorine], endpoint_owners=[1])]
        assert [report['fragments'][side]['count'] for side in ('submitted', 'final')] == [2, 2]
        assert any('质子归属' in r for r in report['reasons'])
    elif reason == 'ring':
        assert [d['atoms'] for d in report['bond_differences']] == [[2, 6]]
        assert report['bond_differences'][0]['reference_state'] == 'separated'
        assert report['bond_differences'][0]['endpoint_state'] == 'bonded'
        assert not report['proton_differences']
        assert [report['fragments'][side]['count'] for side in ('submitted', 'final')] == [1, 1]
        assert report['same_connectivity_graph'] is False
        # Early distance mismatch does not mean bond orders/stereo were reviewed.
        assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'
    elif reason == 'stereo':
        assert report['stereo_differences'] and not report['bond_differences']
        assert any('立体' in r for r in report['reasons'])
    else:
        assert all(not report[key] for key in topology.DIFFERENCES)


@pytest.mark.parametrize('before_name,after_name,status,reason', PAIRS)
def test_irc_cli_endpoints_and_references(tmp_path, capsys, before_name, after_name, status, reason):
    before, after = frame(before_name), frame(after_name)
    charge = Chem.GetFormalCharge(oracle(before_name))
    paths = {
        'ts': write_attempt(tmp_path, 'ts', before, before, charge),
        'forward': write_attempt(tmp_path, 'forward', before, perturb(before), charge, endpoint=True),
        'reverse': write_attempt(tmp_path, 'reverse', after, perturb(after), charge, endpoint=True),
        'reactant': write_attempt(tmp_path, 'reactant', before, before, charge),
        'product': write_attempt(tmp_path, 'product', after, after, charge),
    }
    baseline = snapshot(tmp_path / 'attempts')
    out = tmp_path / 'irc.json'
    args = ['irc-compare', '--out', str(out), '--json']
    for role, path in paths.items():
        args.extend(['--' + role, str(path)])
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(out.read_text()) and report['status'] == irc.MATCH
    assert snapshot(tmp_path / 'attempts') == baseline
    comparisons = report['comparisons']
    assert comparisons['forward']['reactant']['status'] == irc.MATCH
    assert comparisons['reverse']['product']['status'] == irc.MATCH
    if status == 'changed':
        assert report['assignment'] == dict(forward='reactant', reverse='product')
        assert comparisons['forward']['product']['status'] == irc.MISMATCH
        assert comparisons['reverse']['reactant']['status'] == irc.MISMATCH
    else:
        assert report['assignment'] is None  # Two identical targets cannot assign direction.
    if reason == 'ring':
        changes = report['reaction_changes']['reference_reactant_to_product']['bond_differences']
        assert [(d['atoms'], d['change']) for d in changes] == [([2, 6], 'formed')]
    if reason == 'stereo':
        assert comparisons['forward']['product']['stereo_differences']


@pytest.mark.parametrize('name', MODELS)
def test_irc_explicit_charge_disagreement_is_rejected(name):
    value = frame(name)
    charge = Chem.GetFormalCharge(oracle(name))
    report = irc.compare_endpoint(source(value, charge + 1), source(value, charge), charge)
    assert report['status'] == irc.MISMATCH
    assert 'charge 不同' in report['reasons'][0]


@pytest.mark.parametrize('name', PROTONATIONS)
def test_unbalanced_protonation_does_not_reuse_atom_mapping(name):
    before, after = frame(name), frame(PROTONATIONS[name])
    report = topology.compare_minimum(before, after, -1)
    assert report['status'] == 'unknown'
    assert '原子数不同' in report['reasons'][0]
    assert irc.compare_endpoint(source(after, 0), source(before, -1), -1)['status'] == irc.MISMATCH


@pytest.mark.parametrize('name', ('enolate', 'borate'))
def test_wrong_total_charge_errors_in_inference_and_is_unknown_in_comparison(name):
    value = frame(name)
    with pytest.raises(ValueError, match='charge'):
        infer(value, 0)
    report = topology.compare_minimum(value, value, 0)
    assert report['status'] == 'unknown'
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'
    assert irc.compare_endpoint(source(value, 0), source(value, 0), 0)['status'] == irc.UNKNOWN


@pytest.mark.parametrize('name', ('nitronate', 'nitronate_hf'))
def test_xyz_inference_selects_a_legal_resonance_form(name):
    # T89 removes the two strict R1 xfails: XYZ cannot encode which localized
    # electron drawing a human chose. This limitation remains, not a promise
    # that inference will reproduce the C-local representation in the oracle.
    actual = infer(frame(name), -1)
    assert signature(actual) in [signature(mol) for mol in acceptable_oracles(name)]
    assert Chem.GetFormalCharge(actual) == -1
    assert set(bonds(actual)) == set(bonds(oracle(name)))


@pytest.mark.parametrize('name', ('enolate', 'borate'))
def test_failed_inference_cli_is_unknown(tmp_path, capsys, name):
    value = frame(name)
    path = write_attempt(tmp_path, 'wrong-charge', value, value, 0)
    baseline = snapshot(path)
    out = tmp_path / 'topology.json'
    assert main(['topology', str(path), '--out', str(out), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'unknown'
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'
    out = tmp_path / 'irc.json'
    args = ['irc-compare', '--out', str(out), '--json']
    for role in ('ts', 'forward', 'reverse', 'reactant', 'product'):
        args.extend(['--' + role, str(path)])
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)['status'] == irc.UNKNOWN
    assert snapshot(path) == baseline


def test_ambiguous_boron_contact_retains_warning_and_irc_unknown(tmp_path, capsys):
    before, after = frame('acetone_bf3'), frame('acetone_bf3_stretched')
    path = write_attempt(tmp_path, 'ambiguous', before, after, 0)
    out = tmp_path / 'topology.json'
    assert main(['topology', str(path), '--out', str(out), '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert [d['atoms'] for d in report['ambiguous_bonds']] == [[3, 4]]
    assert report['ambiguous_bonds'][0]['endpoint_distance'] == pytest.approx(2.2)
    assert report['bond_order_and_stereo_assessment']['status'] == 'unknown'
    assert any('XYZ 距离不能确定成键' in r for r in report['reasons'])
    assert [report['fragments'][side]['count'] for side in ('submitted', 'final')] == [1, 2]
    assert irc.compare_endpoint(source(after, 0), source(before, 0), 0)['status'] == irc.UNKNOWN
    # RDKit makes a definite graph choice inside ag's uncertainty band.
    assert signature(infer(after, 0)) == signature(separated_oracle('acetone_bf3'))


def test_ambiguous_boron_fragment_change_should_remain_unknown():
    report = topology.compare_minimum(frame('acetone_bf3'), frame('acetone_bf3_stretched'), 0)
    assert report['status'] == 'unknown'
    assert report['fragments']['fragments_if_uncertain_bonded'] == {'submitted': 1, 'final': 1}
    assert report['fragments']['fragment_change_depends_on_uncertain_contacts'] is True
    assert any('3–4 (O–B)' in reason and '2.200000 Å' in reason and '1.466667' in reason
               for reason in report['reasons'])


def generate_fixtures(directory):
    """Explicit offline regeneration; no production inference used as an oracle."""
    directory.mkdir(parents=True, exist_ok=True)
    values = {}
    for name in SMILES:
        mol = explicit(name)
        params = AllChem.ETKDGv3()
        params.randomSeed = 6801
        assert AllChem.EmbedMolecule(mol, params) == 0
        assert AllChem.UFFOptimizeMolecule(mol, maxIters=2000) == 0
        values[name] = geo.Frame(tuple(a.GetSymbol() for a in mol.GetAtoms()),
            tuple(tuple(mol.GetConformer().GetAtomPosition(i)) for i in range(mol.GetNumAtoms())))
    values['nbpin_perturbed'] = perturb(values['nbpin'])
    for name in CHIRAL:
        original = values[name]
        values[name + '_mirror'] = replace(original, coordinates=tuple((-x, y, z) for x, y, z in original.coordinates))
    for name in ADDUCTS:
        original, mol = values[name], separated_oracle(name)
        fragment = next(indices for indices in Chem.GetMolFrags(mol)
                        if any(mol.GetAtomWithIdx(i).GetSymbol() == 'B' for i in indices))
        values[name + '_separated'] = replace(original, coordinates=tuple(
            (x + 10 if i in fragment else x, y, z) for i, (x, y, z) in enumerate(original.coordinates)))
    for name, acid_name in PROTONATIONS.items():
        base, acid = values[name], values[acid_name]
        values[name + '_hf'] = geo.Frame(base.symbols + ('F', 'H'), base.coordinates + ((10., 0., 0.), (10.92, 0., 0.)))
        # Keep the existing H indices; put the transferred proton last.
        mol = explicit(acid_name)
        base_mol = explicit(name)
        mapping = list(range(base_mol.GetNumHeavyAtoms()))
        for atom in base_mol.GetAtoms():
            if atom.GetAtomicNum() == 1:
                owner = atom.GetNeighbors()[0].GetIdx()
                old_h = [a.GetIdx() for a in base_mol.GetAtomWithIdx(owner).GetNeighbors() if a.GetAtomicNum() == 1]
                new_h = [a.GetIdx() for a in mol.GetAtomWithIdx(owner).GetNeighbors() if a.GetAtomicNum() == 1]
                mapping.append(new_h[old_h.index(atom.GetIdx())])
        extra, = set(range(mol.GetNumAtoms())) - set(mapping)
        values[name + '_protonated_f'] = geo.Frame(base.symbols + ('F', 'H'),
            tuple(acid.coordinates[i] for i in mapping) + ((10., 0., 0.), acid.coordinates[extra]))
    assert set(values) == set(MODELS)
    # Deliberately ambiguous B-O contact; no claim of a stable adduct at 2.2 A.
    original = values['acetone_bf3']
    vector = tuple(original.coordinates[3][j] - original.coordinates[2][j] for j in range(3))
    length = math.hypot(*vector)
    fragment = next(ids for ids in Chem.GetMolFrags(separated_oracle('acetone_bf3')) if 3 in ids)
    values['acetone_bf3_stretched'] = replace(original, coordinates=tuple(
        tuple(x + (2.2 - length) * vector[j] / length if i in fragment else x
              for j, x in enumerate(row)) for i, row in enumerate(original.coordinates)))
    for name, value in values.items():
        comment = f'T68 synthetic {name}; ETKDGv3 seed=6801 + UFF; see test_inference_risk.py'
        with (directory / (name + '.xyz')).open('x') as handle:
            handle.write(geo.xyz_text([replace(value, comment=comment)]))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate-fixtures', type=Path, required=True)
    generate_fixtures(parser.parse_args().generate_fixtures)
