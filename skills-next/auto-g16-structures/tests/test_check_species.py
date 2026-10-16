"""Synthetic intake regressions; no private study data or remote operations."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

pytest.importorskip('rdkit')
from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import check_species as check
from make_gaussian_input import read_molecule

FIELDS = ['species_id', 'role', 'source_file', 'second_source', 'expected_formula',
          'expected_charge', 'multiplicity', 'expected_cip', 'stereo_basis', 'note']


def write_csv(path, rows, fields=FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def species(root, name='butane', smiles='CCCC', **changes):
    (root / f'{name}.smi').write_text(smiles + '\n')
    row = dict(species_id=name, role='reactant', source_file=f'{name}.smi',
               second_source='smiles:' + smiles, expected_formula='C4H10',
               expected_charge='0', multiplicity='1', expected_cip='none')
    row.update(changes)
    return row


def run(root, rows, **kwargs):
    write_csv(root / 'analyses/intake/species.csv', rows)
    return check.run(root, **kwargs)


def test_batch_mismatches_and_scope_continue(tmp_path):
    chiral = 'C[C@H](O)[C@@H](O)C'
    rows = [species(tmp_path),
            species(tmp_path, 'diol', chiral, expected_formula='C4H10O2', expected_cip='2:S;4:S'),
            species(tmp_path, 'wrong_cip', chiral, expected_formula='C4H10O2', expected_cip='2:R;4:S'),
            species(tmp_path, 'wrong_formula', expected_formula='C5H12'),
            species(tmp_path, 'wrong_charge', expected_charge='1'),
            species(tmp_path, 'second_stereo', chiral, expected_formula='C4H10O2', expected_cip='2:S;4:S',
                    second_source='smiles:C[C@@H](O)[C@@H](O)C'),
            species(tmp_path, 'radical', '[CH3]', expected_formula='CH3'),
            species(tmp_path, 'metal', '[Na+]', expected_formula='Na', expected_charge='1'),
            species(tmp_path, 'disconnected', 'C.C', expected_formula='C2H8'),
            species(tmp_path, 'unknown', expected_cip='', second_source='')]
    report = run(tmp_path, rows)
    assert [s['status'] for s in report['species']] == ['all_match', 'all_match', *['has_mismatch'] * 4,
                                                       *['out_of_scope'] * 3, 'incomplete']
    assert report['species'][5]['checks']['second_source']['differences'] == ['stereochemistry']
    assert report['species'][2]['checks']['cip']['centers'][0]['status'] == 'mismatch'
    for item in report['species']:
        assert (tmp_path / item['preview']).read_bytes().startswith(b'\x89PNG')
    for entry in report['inputs']:
        assert not Path(entry['path']).is_absolute()
        assert entry['sha256'] == hashlib.sha256((tmp_path / entry['path']).read_bytes()).hexdigest()
    saved = json.loads((tmp_path / 'analyses/intake/species-check.json').read_text())
    assert saved == report
    assert str(tmp_path) not in json.dumps(report)
    assert 'has_mismatch' in (tmp_path / 'analyses/intake/species-check.md').read_text()


@pytest.mark.parametrize('source_kind', ['argument', 'file'])
def test_preserve_h_only_changes_indices(source_kind, tmp_path):
    text = '[H][C@](F)(Cl)Br'
    source = text
    if source_kind == 'file':
        path = tmp_path / 'h.smi'; path.write_text(text + '\n'); source = str(path)
    default, _, _ = read_molecule(source, Chem)
    off, _, _ = read_molecule(source, Chem, preserve_explicit_h=False)
    preserved, _, _ = read_molecule(source, Chem, preserve_explicit_h=True)
    assert default.ToBinary() == off.ToBinary()
    assert Chem.FindMolChiralCenters(default) == [(0, 'S')]
    assert Chem.FindMolChiralCenters(preserved) == [(1, 'S')]
    assert rdMolDescriptors.CalcMolFormula(default) == rdMolDescriptors.CalcMolFormula(preserved) == 'CHBrClF'
    assert Chem.GetFormalCharge(default) == Chem.GetFormalCharge(preserved) == 0
    assert Chem.MolToSmiles(default) == Chem.MolToSmiles(Chem.RemoveHs(preserved))


def test_h_numbering_and_second_source_equivalence(tmp_path):
    row = species(tmp_path, 'explicit', '[H][C@](F)(Cl)Br', expected_formula='CHBrClF',
                  expected_cip='2:S', second_source='smiles:F[C@@H](Cl)Br')
    report = run(tmp_path, [row])['species'][0]
    assert report['status'] == 'all_match'
    assert report['actual']['explicit_h_atom_count'] == 1
    assert report['actual']['explicit_hydrogen_atom_indices'] == [1]
    assert report['actual']['chiral_centers'] == [{'atom_index': 2, 'cip': 'S'}]


@pytest.mark.skipif(not getattr(Chem, 'HasChemDrawCDXSupport', lambda: False)(), reason='RDKit lacks ChemDraw CDX support')
def test_cdxml_direct_read_preserves_source_numbering(tmp_path):
    source = Path(__file__).parent / 'fixtures/chiral_explicit_h.cdxml'
    shutil.copyfile(source, tmp_path / 'source.cdxml')
    row = species(tmp_path, source_file='source.cdxml', expected_formula='C4H10O',
                  expected_cip='1:S', second_source='smiles:C[C@H](O)CC')
    item = run(tmp_path, [row])['species'][0]
    assert item['status'] == 'all_match'
    assert item['actual']['atom_count'] == 6
    assert item['actual']['atom_count_with_h'] == 15
    assert item['actual']['explicit_hydrogen_atom_indices'] == [6]
    assert item['actual']['chiral_centers'] == [{'atom_index': 1, 'cip': 'S'}]
    diagnostic = item['actual']['import_diagnostics'][0]
    assert diagnostic['explicit_hydrogen_atom_indices'] == [6]
    assert diagnostic['restored_bond_cfg'][0]['begin_atom'] == 1


@pytest.mark.parametrize('suffix', ['.mol', '.sdf'])
def test_mol_sdf_source_indices_and_file_hash(tmp_path, suffix):
    params = Chem.SmilesParserParams(); params.removeHs = False
    mol = Chem.MolFromSmiles('[H][C@](F)(Cl)Br', params)
    file = tmp_path / ('source' + suffix)
    if suffix == '.mol':
        Chem.MolToMolFile(mol, str(file))
    else:
        with Chem.SDWriter(str(file)) as writer: writer.write(mol)
    row = species(tmp_path, source_file=file.name, expected_formula='CHBrClF', expected_cip='2:S',
                  second_source='smiles:F[C@@H](Cl)Br')
    result = run(tmp_path, [row])
    assert result['species'][0]['status'] == 'all_match'
    assert file.name in {f['path'] for f in result['inputs']}


@pytest.mark.parametrize('first,second,difference', [('CCO', 'COC', 'constitution'),
                                                   ('N', '[NH4+]', 'charge'),
                                                   ('F/C=C/F', 'F/C=C\\F', 'stereochemistry')])
def test_second_source_difference_categories(first, second, difference):
    result = check.compare_sources(Chem.MolFromSmiles(first), Chem.MolFromSmiles(second), Chem)
    assert result['status'] == 'mismatch'
    assert difference in result['differences']


def test_charge_separate_from_formula_and_map_numbers_ignored(tmp_path):
    row = species(tmp_path, 'ammonium', '[NH4+:7]', expected_formula='H4N', expected_charge='1',
                  second_source='smiles:[NH4+]')
    item = run(tmp_path, [row])['species'][0]
    assert item['status'] == 'all_match'
    assert item['actual']['formula'] == 'H4N'
    assert item['actual']['charge'] == 1


@pytest.mark.parametrize('cip,expected', [('2:S', 'mismatch'), ('none', 'mismatch'), ('2:S;4:S', 'match')])
def test_unlisted_centers(tmp_path, cip, expected):
    item = run(tmp_path, [species(tmp_path, smiles='C[C@H](O)[C@@H](O)C',
                                 expected_formula='C4H10O2', expected_cip=cip)])['species'][0]
    assert item['checks']['cip']['status'] == expected


def test_unassigned_and_bad_input_do_not_abort_batch(tmp_path):
    rows = [species(tmp_path, 'unassigned', 'CC(O)CC', expected_formula='C4H10O', expected_cip='2:R'),
            species(tmp_path, 'bad', 'not_a_smiles'), species(tmp_path)]
    items = run(tmp_path, rows)['species']
    assert items[0]['status'] == 'out_of_scope'
    assert items[0]['actual']['unassigned_centers'] == [2]
    assert items[0]['checks']['cip']['status'] == 'unknown'
    assert items[1]['status'] == 'incomplete' and items[1]['actual'] is None
    assert items[2]['status'] == 'all_match'


@pytest.mark.parametrize('field', ['expected_formula', 'expected_charge', 'multiplicity', 'expected_cip', 'second_source'])
def test_missing_expectations_not_inferred(tmp_path, field):
    item = run(tmp_path, [species(tmp_path, **{field: ''})])['species'][0]
    assert item['status'] == 'incomplete'
    if field == 'multiplicity': assert item['multiplicity'] is None


@pytest.mark.parametrize('balanced', [True, False])
def test_reaction_balance_and_missing_byproduct(tmp_path, balanced):
    rows = [species(tmp_path, 'peroxide', 'OO', expected_formula='H2O2'),
            species(tmp_path, 'water', 'O', expected_formula='H2O'),
            species(tmp_path, 'oxygen', 'O=O', expected_formula='O2')]
    rxn = [dict(species_id='peroxide', side='left', coefficient='2'),
           dict(species_id='water', side='right', coefficient='2')]
    if balanced: rxn.append(dict(species_id='oxygen', side='right', coefficient='1'))
    write_csv(tmp_path / 'analyses/intake/reaction.csv', rxn, ['species_id', 'side', 'coefficient'])
    reaction = run(tmp_path, rows)['reaction']
    assert reaction['status'] == ('match' if balanced else 'mismatch')
    assert reaction['delta_right_minus_left'] == ({} if balanced else {'O': '-2'})
    if not balanced: assert '右侧少 2 个 O' in reaction['messages']


def test_fractional_coefficients_and_charge_difference(tmp_path):
    rows = [species(tmp_path, 'left', '[CH3+]', expected_formula='CH3', expected_charge='1'),
            species(tmp_path, 'right', '[CH3]', expected_formula='CH3')]
    write_csv(tmp_path / 'analyses/intake/reaction.csv', [dict(species_id=s, side=s, coefficient='1/2') for s in ['left', 'right']],
              ['species_id', 'side', 'coefficient'])
    reaction = run(tmp_path, rows)['reaction']
    assert reaction['delta_right_minus_left'] == {}
    assert reaction['charge_delta_right_minus_left'] == '-1/2'


def test_no_overwrite_and_revision_output(tmp_path):
    run(tmp_path, [species(tmp_path)])
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='already exists'): check.run(tmp_path)
    assert all(p.read_bytes() == data for p, data in before.items())
    check.run(tmp_path, output_dir='analyses/intake-v2')
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('target', ['source', 'second', 'species', 'reaction', 'output', 'preview', 'root'])
def test_symlinks_refused(tmp_path, target):
    root = tmp_path / 'study'; root.mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    row = species(root)
    write_csv(root / 'analyses/intake/species.csv', [row])
    if target == 'source':
        (root / 'butane.smi').unlink(); (root / 'butane.smi').symlink_to(outside / 'missing.smi')
    elif target == 'second':
        row['second_source'] = 'second.smi'; (root / 'second.smi').symlink_to(root / 'butane.smi')
        write_csv(root / 'analyses/intake/species.csv', [row])
    elif target == 'species':
        (root / 'analyses/intake/species.csv').unlink(); (root / 'analyses/intake/species.csv').symlink_to(outside / 'missing.csv')
    elif target == 'reaction': (root / 'analyses/intake/reaction.csv').symlink_to(outside / 'missing.csv')
    elif target == 'output': (root / 'analyses/intake/species-check.json').symlink_to(outside / 'missing.json')
    elif target == 'preview': (root / 'analyses/intake/butane').symlink_to(outside)
    elif target == 'root':
        alias = tmp_path / 'alias'; alias.symlink_to(root); root = alias
    with pytest.raises(ValueError, match='symlink'): check.run(root)
    assert not list(outside.iterdir())


@pytest.mark.parametrize('field,value', [('source_file', '../outside.smi'), ('source_file', '/outside.smi'),
                                        ('second_source', '../outside.smi'), ('species_id', '../escape')])
def test_escape_refused(tmp_path, field, value):
    with pytest.raises(ValueError): run(tmp_path, [species(tmp_path, **{field: value})])
    assert not (tmp_path / 'analyses/intake/species-check.json').exists()


def test_output_escape_refused(tmp_path):
    with pytest.raises(ValueError): run(tmp_path, [species(tmp_path)], output_dir='../outside')


def test_changed_input_not_published(tmp_path, monkeypatch):
    original = check.preview
    def changing(mol, name):
        (tmp_path / 'butane.smi').write_text('CC\n')
        return original(mol, name)
    monkeypatch.setattr(check, 'preview', changing)
    with pytest.raises(ValueError, match='input changed'): run(tmp_path, [species(tmp_path)])
    assert not (tmp_path / 'analyses/intake/species-check.json').exists()


def test_cli_and_original_study_untouched(tmp_path):
    (tmp_path / 'study.md').write_text('Existing signature; do not change.\n')
    row = species(tmp_path)
    write_csv(tmp_path / 'analyses/intake/species.csv', [row])
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = subprocess.run([sys.executable, str(SCRIPTS / 'check_species.py'), '--study', str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['species'] == {'butane': 'all_match'}
    assert all(p.read_bytes() == data for p, data in before.items())
