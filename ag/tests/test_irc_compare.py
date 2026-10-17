"""T89 synthetic fixed-index resonance graphs; no private investigation files."""
from dataclasses import replace
import math

import pytest

from ag import geometry as geo, irc_compare as irc, topology

Chem = pytest.importorskip('rdkit.Chem')
from rdkit.Chem import AllChem, rdDetermineBonds


FORMS = {
    'nitronate': ('[CH2-][N+](=O)[O-]', 'C=[N+]([O-])[O-]'),
    'acetate': ('CC(=O)[O-]', 'CC([O-])=O'),
    'enolate': ('[CH2-]C=O', 'C=C[O-]'),
}


def molecule(smiles):
    return Chem.AddHs(Chem.MolFromSmiles(smiles))


def geometry(name, t=0.):
    # Hand-built interpolation of typical localized bond lengths. Coordinates
    # are geometric test data, not optimized structures or energy evidence.
    s = math.sqrt(3) / 2
    if name == 'nitronate':
        cn, no3, no4 = 1.46 - .14*t, 1.22 + .12*t, 1.34
        symbols = ('C', 'N', 'O', 'O', 'H', 'H')
        points = [(0, 0, 0), (cn, 0, 0), (cn+no3/2, no3*s, 0),
                  (cn+no4/2, -no4*s, 0), (-.545, 1.09*s, 0), (-.545, -1.09*s, 0)]
    elif name == 'acetate':
        co3, co4 = 1.23+.10*t, 1.33-.10*t
        r, a = 1.09*math.sqrt(8/9), 1.09/3
        symbols = ('C', 'C', 'O', 'O', 'H', 'H', 'H')
        points = [(0, 0, 0), (1.5, 0, 0), (1.5+co3/2, co3*s, 0), (1.5+co4/2, -co4*s, 0),
                  (-a, r, 0), (-a, -r/2, r*s), (-a, -r/2, -r*s)]
    else:
        cc, co = 1.48-.14*t, 1.23+.12*t
        symbols = ('C', 'C', 'O', 'H', 'H', 'H')
        points = [(0, 0, 0), (cc, 0, 0), (cc+co/2, co*s, 0),
                  (-.545, 1.09*s, 0), (-.545, -1.09*s, 0), (cc+.545, -1.09*s, 0)]
    return geo.Frame(symbols, tuple(tuple(p) for p in points))


def with_geometry(mol, frame):
    result = Chem.Mol(mol)
    assert tuple(a.GetSymbol() for a in result.GetAtoms()) == frame.symbols
    result.RemoveAllConformers()
    conf = Chem.Conformer(result.GetNumAtoms())
    for i, row in enumerate(frame.coordinates):
        conf.SetAtomPosition(i, row)
    result.AddConformer(conf)
    Chem.AssignStereochemistryFrom3D(result, replaceExistingTags=True)
    return result


def source(frame, charge=-1):
    return dict(frame=frame, facts=dict(charge=charge, multiplicity=1))


def compare_graphs(monkeypatch, left, right, a, b):
    # A geometry-only inference chooses one localized form. Inject the two
    # explicit oracles AFTER inference to test the comparator's actual risk.
    left, right = with_geometry(left, a), with_geometry(right, b)
    before = [Chem.MolToMolBlock(mol) for mol in (left, right)]
    monkeypatch.setattr(geo, 'infer_molecule', lambda frame, *args: left if frame is a else right)
    charge = Chem.GetFormalCharge(left)
    endpoint = irc.compare_endpoint(source(a, charge), source(b, charge), charge)
    minimum = topology.compare_minimum(b, a, charge)
    assert before == [Chem.MolToMolBlock(mol) for mol in (left, right)]
    return endpoint, minimum


@pytest.mark.parametrize('name', FORMS)
@pytest.mark.parametrize('t', [0., .25, .5, .75, 1.])
def test_resonance_forms_compare_unchanged(monkeypatch, name, t):
    a = geometry(name, t)
    b = replace(a)  # Identical coordinates, distinct source identity.
    left, right = map(molecule, FORMS[name])
    endpoint, minimum = compare_graphs(monkeypatch, left, right, a, b)
    assert endpoint['status'] == irc.MATCH, endpoint
    assert minimum['status'] == 'unchanged', minimum
    for report in (endpoint, minimum):
        assert report['resonance_equivalent'] is True
        assert report['bond_differences_resonance_equivalent'] is True
        assert report['bond_differences']  # Keep the original per-bond evidence.
        check = report['resonance_check']
        assert check['executed'] and check['status'] == 'equivalent'
        assert all(n > 0 for n in check['enumerated'].values())
        assert not check['limit_reached']
        assert check['atoms'] and check['bonds'] and check['formal_charge_differences']
        assert '键级 / 电荷位置差异经判断为共振等价。' in report['reasons']
        assert report['resonance_stereo_check']['status'] == 'evaluated'
    # Atom-indexed acetate bonds differ even though canonical graph keys match.
    if name == 'acetate':
        assert endpoint['graph_keys']['endpoint'] == endpoint['graph_keys']['reference']


@pytest.mark.parametrize('name', FORMS)
@pytest.mark.parametrize('t', [0., .25, .5, .75, 1.])
def test_real_inference_on_interpolated_geometries(name, t):
    a, b = geometry(name), geometry(name, t)
    inferred = geo.infer_molecule(b, -1, Chem, rdDetermineBonds)
    assert Chem.GetFormalCharge(inferred) == -1
    check = geo.resonance_equivalence(inferred, molecule(FORMS[name][0]), Chem)
    assert check['status'] in ('equivalent', 'not_needed')
    assert topology.compare_minimum(a, b, -1)['status'] == 'unchanged'
    assert irc.compare_endpoint(source(a), source(b), -1)['status'] == irc.MATCH


def test_keto_enol_keeps_all_hydrogen_owners():
    s, r, a = math.sqrt(3)/2, 1.09*math.sqrt(8/9), 1.09/3
    enol = geometry('enolate', 1.)
    enol = replace(enol, symbols=enol.symbols+('H',),
        coordinates=enol.coordinates+((2.015+.97, 1.35*s, 0.),))
    keto = geo.Frame(enol.symbols, ((0,0,0),(1.50,0,0),(2.115,1.23*s,0),
        (-a,-r/2,r*s),(-a,-r/2,-r*s),(2.045,-1.09*s,0),(-a,r,0)))
    report = topology.compare_minimum(keto, enol, 0)
    assert report['status'] == 'changed' and report['proton_differences']
    report = irc.compare_endpoint(source(keto, 0), source(enol, 0), 0)
    assert report['status'] == irc.MISMATCH
    assert report['resonance_check']['executed'] is False


def test_fragment_charge_is_by_membership_not_sorted_multiset():
    left = Chem.CombineMols(molecule('CC(=O)[O-]'), molecule('CC(=O)O'))
    # Use identical nuclei/bonds, moving one formal charge between components.
    right = Chem.Mol(left)
    right.GetAtomWithIdx(3).SetFormalCharge(0)
    right.GetAtomWithIdx(10).SetFormalCharge(-1)
    report = geo.resonance_equivalence(left, right, Chem)
    assert report['status'] == 'not_equivalent' and not report['executed']
    rows = report['fragment_charges']
    assert sorted(row['endpoint'] for row in rows) == sorted(row['reference'] for row in rows)
    assert any(row['endpoint'] != row['reference'] for row in rows)


def test_same_connections_and_fragment_charge_are_not_sufficient(monkeypatch):
    # Charge swaps across a saturated spacer cannot delocalize by resonance.
    # The canonical graph/SMILES is identical, so only fixed-index charges
    # reveal the different representation; all H and sigma bonds are retained.
    left, right = map(molecule, ('[CH2-]CC[CH2+]', '[CH2+]CC[CH2-]'))
    assert geo.graph_key(left, Chem) == geo.graph_key(right, Chem)
    check = geo.resonance_equivalence(left, right, Chem)
    assert check['status'] == 'not_equivalent'
    assert AllChem.EmbedMolecule(left, randomSeed=8901) == 0
    AllChem.UFFOptimizeMolecule(left)
    a = geo.Frame(tuple(atom.GetSymbol() for atom in left.GetAtoms()),
        tuple(tuple(left.GetConformer().GetAtomPosition(i)) for i in range(left.GetNumAtoms())))
    endpoint, minimum = compare_graphs(monkeypatch, left, right, a, replace(a))
    assert endpoint['status'] == irc.MISMATCH and minimum['status'] == 'changed'
    assert not endpoint['resonance_equivalent']


@pytest.mark.parametrize('failure', ['limit', 'exception', 'cancelled', 'empty'])
def test_incomplete_enumeration_is_unknown(monkeypatch, failure):
    left, right = map(molecule, FORMS['acetate'])
    if failure == 'limit':
        monkeypatch.setattr(geo, 'RESONANCE_MAX_STRUCTURES', 1)
    else:
        class BrokenSupplier:
            def __init__(self, *args, **kwargs):
                if failure == 'exception':
                    raise RuntimeError('synthetic failure')
            def __len__(self):
                return 0 if failure == 'empty' else 1
            def WasCanceled(self):
                return failure == 'cancelled'
        monkeypatch.setattr(Chem, 'ResonanceMolSupplier', BrokenSupplier)
    a, b = geometry('acetate'), replace(geometry('acetate'))
    endpoint, minimum = compare_graphs(monkeypatch, left, right, a, b)
    assert endpoint['status'] == irc.UNKNOWN and minimum['status'] == 'unknown'
    assert minimum['bond_order_and_stereo_assessment']['status'] == 'unknown'
    assert endpoint['resonance_check']['status'] == 'unknown'
    assert not endpoint['resonance_equivalent']
    assert endpoint['resonance_check']['limit_reached'] is (failure == 'limit')


@pytest.mark.parametrize('smiles,changed', [
    ('[BH2][C@H](F)C', True), ('[BH2][C@H](F)C', False), ('F/C=C/Cl', True)])
def test_resonance_does_not_hide_stereochemistry(monkeypatch, smiles, changed):
    stereo = molecule(smiles)
    assert AllChem.EmbedMolecule(stereo, randomSeed=8901) == 0
    sf = geo.Frame(tuple(a.GetSymbol() for a in stereo.GetAtoms()),
        tuple(tuple(stereo.GetConformer().GetAtomPosition(i)) for i in range(stereo.GetNumAtoms())))
    if 'C=C' in smiles:
        other = molecule('F/C=C\\Cl')
        assert AllChem.EmbedMolecule(other, randomSeed=8901) == 0
        coords = tuple(tuple(other.GetConformer().GetAtomPosition(i)) for i in range(other.GetNumAtoms()))
    else:
        coords = tuple((-x if changed else x, y, z) for x,y,z in sf.coordinates)
    a = geometry('acetate')
    b = replace(a, symbols=a.symbols+sf.symbols,
        coordinates=a.coordinates+tuple((x+12,y,z) for x,y,z in coords))
    a = replace(a, symbols=a.symbols+sf.symbols,
        coordinates=a.coordinates+tuple((x+12,y,z) for x,y,z in sf.coordinates))
    left, right = (Chem.CombineMols(molecule(s), stereo) for s in FORMS['acetate'])
    endpoint, minimum = compare_graphs(monkeypatch, left, right, a, b)
    assert endpoint['resonance_equivalent']
    assert endpoint['status'] == (irc.MISMATCH if changed else irc.MATCH), endpoint
    assert minimum['status'] == ('changed' if changed else 'unchanged'), minimum
    if changed:
        assert any('立体' in reason for reason in endpoint['reasons'])


def test_eighty_to_hundred_atom_enumeration_and_real_cap():
    # 31-carbon carboxylate = 94 explicit atoms, only two resonance forms.
    left = molecule('C'*30+'C(=O)[O-]')
    right = molecule('C'*30+'C([O-])=O')
    assert 80 <= left.GetNumAtoms() <= 100
    assert geo.resonance_equivalence(left, right, Chem)['status'] == 'equivalent'
    # 10 independent acetates produce 2**10 forms and hit the real 1000 cap.
    left = molecule('.'.join(['CC(=O)[O-]']*10))
    right = molecule('.'.join(['CC([O-])=O']*10))
    result = geo.resonance_equivalence(left, right, Chem)
    assert result['status'] == 'unknown' and result['limit_reached']
    assert result['enumerated'] == dict(endpoint=1000, reference=1000)


def test_resonance_markdown_and_reaction_changes(monkeypatch, tmp_path):
    from test_inference_risk import write_attempt
    a, b = geometry('nitronate'), replace(geometry('nitronate'))
    left, right = (with_geometry(molecule(s), a) for s in FORMS['nitronate'])
    # analyze reads final first, then the submitted geometry.
    copies = iter((left, right))
    monkeypatch.setattr(geo, 'infer_molecule', lambda *args: next(copies))
    path = write_attempt(tmp_path, 'synthetic', b, a, -1)
    report = topology.analyze(path)
    assert report['status'] == 'unchanged'
    text = topology.markdown(report)
    assert '键级 / 电荷位置差异经判断为共振等价' in text
    assert 'resonance_check' in text and 'bond_differences_resonance_equivalent' in text
    monkeypatch.setattr(geo, 'infer_molecule', lambda f, *args: left if f is a else right)
    report = irc.compare(source(a), source(a), source(b), source(a), source(b))
    assert report['status'] == irc.MATCH
    changes = report['reaction_changes']['reference_reactant_to_product']
    assert changes['resonance_equivalent'] and changes['bond_differences_resonance_equivalent']
    assert changes['bond_differences']


def test_connectivity_and_metadata_precede_resonance(monkeypatch):
    a = geometry('nitronate')
    b = replace(a, coordinates=a.coordinates[:-1]+((12.,0.,0.),))
    def forbidden(*args):
        pytest.fail('do not enumerate before connectivity and metadata checks pass')
    monkeypatch.setattr(geo, 'resonance_equivalence', forbidden)
    assert irc.compare_endpoint(source(a), source(b), -1)['status'] == irc.MISMATCH
    for field in ('charge', 'multiplicity'):
        changed = source(a)
        changed['facts'][field] += 1
        assert irc.compare_endpoint(changed, source(a), -1)['status'] == irc.MISMATCH


def test_resonance_requires_fixed_connectivity_even_if_distances_match():
    left, right = map(molecule, FORMS['nitronate'])
    edit = Chem.RWMol(right)
    edit.RemoveBond(0, 4)
    edit.AddBond(2, 4, Chem.BondType.SINGLE)
    assert geo.resonance_equivalence(left, edit.GetMol(), Chem)['status'] == 'not_equivalent'


def test_enumeration_checks_both_directions(monkeypatch):
    left, right = map(molecule, FORMS['nitronate'])
    # Mimic an asymmetric supplier: only B enumerates A. Both are required to
    # run (and complete) even if the first direction happens to find a match.
    calls = []
    class OneForm:
        def __init__(self, mol, **kwargs):
            calls.append(mol)
        def __len__(self):
            return 1
        def WasCanceled(self):
            return False
        def __iter__(self):
            return iter([left])
    monkeypatch.setattr(Chem, 'ResonanceMolSupplier', OneForm)
    for a,b in ((left,right),(right,left)):
        assert geo.resonance_equivalence(a,b,Chem)['status'] == 'equivalent'
    assert len(calls) == 4


def test_second_direction_failure_does_not_accept_first_match(monkeypatch):
    left, right = map(molecule, FORMS['acetate'])
    calls = []
    class Supplier:
        def __init__(self, mol, **kwargs):
            calls.append(mol)
            if len(calls) == 2:
                raise RuntimeError('second direction failed')
        def __len__(self):
            return 1
        def WasCanceled(self):
            return False
        def __iter__(self):
            return iter([right])
    monkeypatch.setattr(Chem, 'ResonanceMolSupplier', Supplier)
    result = geo.resonance_equivalence(left, right, Chem)
    assert result['status'] == 'unknown' and len(calls) == 2
