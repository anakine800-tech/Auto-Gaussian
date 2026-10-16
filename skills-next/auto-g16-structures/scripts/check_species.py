#!/usr/bin/env python3
"""Check an intake species CSV locally; report evidence without signing a study."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import re

from cdx_stereo import structure_stereo_invariants
from make_gaussian_input import load_rdkit, read_molecule, validate_scope, validate_multiplicity

REQUIRED = {'species_id', 'role', 'source_file', 'expected_formula', 'expected_charge', 'multiplicity'}
ROLES = {'reactant', 'product', 'catalyst', 'reagent', 'byproduct', 'additive'}
EXTENSIONS = {'.cdxml', '.cdx', '.mol', '.sdf', '.smi'}


def safe_path(root, relative):
    """Prevent following links or escaping the study with an input/output path."""
    path = Path(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in str(relative):
        raise ValueError('paths must be relative and stay inside the study')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f'symlink refused: {relative}')
    return current


def study_root(study):
    root = Path(study).expanduser().absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('study path must not contain symlinks')
    if not root.is_dir():
        raise ValueError('study directory must already exist')
    return root


def digest(data):
    return hashlib.sha256(data).hexdigest()


def input_bytes(root, relative, inputs):
    data = safe_path(root, relative).read_bytes()
    entry = {'path': Path(relative).as_posix(), 'sha256': digest(data)}
    previous = inputs.setdefault(entry['path'], entry)
    if previous != entry:
        raise ValueError(f'input changed during check: {relative}')
    return data


def csv_rows(data, required):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    fields = reader.fieldnames or []
    if len(set(fields)) != len(fields) or not required.issubset(fields):
        raise ValueError('CSV needs unique headers including: ' + ', '.join(sorted(required)))
    rows = []
    for number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'CSV row {number} has the wrong number of fields')
        rows.append({key: value.strip() for key, value in row.items()})
    if not rows:
        raise ValueError('CSV must contain at least one row')
    return rows


def integer(value, name, positive=False):
    if not value:
        return None
    if not re.fullmatch(r'[+-]?\d+', value):
        raise ValueError(f'{name} must be an integer or blank (unknown)')
    result = int(value)
    if positive and result < 1:
        raise ValueError(f'{name} must be positive')
    return result


def expected_centers(text):
    if not text:
        return None
    if text == 'none':
        return {}
    result = {}
    for item in text.split(';'):
        match = re.fullmatch(r'([1-9]\d*):([RSrs])', item.strip())
        if not match or int(match[1]) in result:
            raise ValueError('expected_cip needs unique 1-based atom numbers, e.g. 2:R;4:S, or none')
        result[int(match[1])] = match[2]
    return result


def comparison(expected, actual):
    return {'status': 'unknown' if expected is None or actual is None else
            ('match' if expected == actual else 'mismatch'), 'expected': expected, 'actual': actual}


def one_based(value):
    """Convert imported atom/bond indices for the report, without changing the molecule."""
    if isinstance(value, list):
        return [one_based(v) for v in value]
    if isinstance(value, dict):
        return {k: (v + 1 if k in {'atom_index', 'bond_index', 'begin_atom', 'end_atom'} else
                    [i + 1 for i in v] if k == 'explicit_hydrogen_atom_indices' else one_based(v))
                for k, v in value.items()}
    return value


def inspect_molecule(mol, diagnostics, Chem, descriptors):
    identity = one_based(structure_stereo_invariants(mol, Chem, descriptors,
                         diagnostics[0] if diagnostics else None))
    expanded = Chem.AddHs(mol)
    elements = dict(sorted(Counter(a.GetSymbol() for a in expanded.GetAtoms()).items()))
    # RDKit appends the charge to CalcMolFormula; intake records it separately.
    identity['formula'] = re.sub(r'[+-]\d*$', '', identity['formula'])
    identity.update(charge=int(Chem.GetFormalCharge(mol)), component_count=len(Chem.GetMolFrags(mol)),
                    explicit_h_atom_count=len(identity['explicit_hydrogen_atom_indices']),
                    atom_count_with_h=expanded.GetNumAtoms(), element_counts=elements,
                    unassigned_centers=[c['atom_index'] for c in identity['chiral_centers'] if c['cip'] == '?'],
                    import_diagnostics=one_based(diagnostics))
    return identity


def cip_comparison(expected, actual):
    declared = None if expected is None else [{'atom_index': i, 'cip': c} for i, c in expected.items()]
    if actual is None:
        return {'status': 'unknown', 'expected': declared, 'centers': [], 'unlisted_centers': []}
    observed = {c['atom_index']: c['cip'] for c in actual['chiral_centers']}
    if expected is None:
        return {'status': 'unknown', 'expected': None, 'centers': [], 'unlisted_centers': list(observed)}
    items = [{'atom_index': index, **comparison(cip, observed.get(index))} for index, cip in expected.items()]
    for item in items:
        if item['atom_index'] not in observed:
            item['status'] = 'mismatch'
        elif item['actual'] == '?':
            item['status'] = 'unknown'
    extra = sorted(set(observed) - set(expected))
    status = ('mismatch' if extra or any(i['status'] == 'mismatch' for i in items) else
              'unknown' if any(i['status'] == 'unknown' for i in items) else 'match')
    return {'status': status, 'expected': declared, 'centers': items, 'unlisted_centers': extra}


def normalized(mol, Chem):
    result = Chem.RemoveHs(Chem.Mol(mol))
    for atom in result.GetAtoms():
        atom.SetAtomMapNum(0)
    return result


def graph_smiles(mol, Chem, *, strip_charge=False):
    result = Chem.Mol(mol)
    Chem.RemoveStereochemistry(result)
    if strip_charge:
        for atom in result.GetAtoms():
            atom.SetFormalCharge(0)
            atom.SetNumRadicalElectrons(0)
            atom.SetNumExplicitHs(0)
            atom.SetNoImplicit(True)
    return Chem.MolToSmiles(result, isomericSmiles=True)


def compare_sources(first, second, Chem):
    left, right = normalized(first, Chem), normalized(second, Chem)
    a, b = (Chem.MolToSmiles(m, isomericSmiles=True) for m in (left, right))
    constitution = graph_smiles(left, Chem, strip_charge=True) == graph_smiles(right, Chem, strip_charge=True)
    nonstereo = graph_smiles(left, Chem) == graph_smiles(right, Chem)
    charge_equal = Chem.GetFormalCharge(left) == Chem.GetFormalCharge(right)
    differences = []
    if not constitution:
        differences.append('constitution')
    if not charge_equal:
        differences.append('charge')
    if constitution and not nonstereo:
        differences.append('charge_or_hydrogen_placement')
    if nonstereo and a != b:
        differences.append('stereochemistry')
    return {'status': 'match' if a == b else 'mismatch',
            'source_canonical_smiles': a, 'second_canonical_smiles': b,
            'constitution': 'match' if constitution else 'mismatch',
            'charge': 'match' if charge_equal else 'mismatch',
            'stereochemistry': ('match' if a == b else 'mismatch') if nonstereo else 'unknown',
            'differences': differences}


def error_text(exc, root):
    return str(exc).replace(str(root) + os.sep, '').removeprefix('ERROR: ')


def read_structure(root, relative, inputs, Chem):
    if Path(relative).suffix.lower() not in EXTENSIONS:
        raise ValueError('structure files must be .cdxml, .cdx, .mol, .sdf or .smi')
    path = safe_path(root, relative)
    input_bytes(root, relative, inputs)
    # Use exactly the existing reader; only SMILES explicit-H removal is opted out.
    mol, _, diagnostics = read_molecule(str(path), Chem, preserve_explicit_h=True)
    input_bytes(root, relative, inputs)
    return mol, diagnostics


def check_one(row, root, inputs, Chem, descriptors):
    expected_formula = row['expected_formula'] or None
    charge = integer(row['expected_charge'], 'expected_charge')
    multiplicity = integer(row['multiplicity'], 'multiplicity', positive=True)
    cip = expected_centers(row.get('expected_cip', ''))
    result = {'species_id': row['species_id'], 'role': row['role'], 'source_file': row['source_file'],
              'second_source': row.get('second_source', ''), 'multiplicity': multiplicity,
              'stereo_basis': row.get('stereo_basis', ''), 'note': row.get('note', ''),
              'actual': None, 'scope_errors': [], 'read_errors': [],
              'warnings': ['Axial/atropisomeric chirality is not validated; inspect the source explicitly.']}
    mol = None
    try:
        mol, diagnostics = read_structure(root, row['source_file'], inputs, Chem)
        try:
            validate_scope(mol, Chem, diagnostics)
        except SystemExit as exc:
            result['scope_errors'].append(error_text(exc, root))
        result['actual'] = inspect_molecule(mol, diagnostics, Chem, descriptors)
    except (SystemExit, ValueError, RuntimeError, OSError) as exc:
        result['read_errors'].append(error_text(exc, root))
        if 'exactly one molecule' in str(exc):
            result['scope_errors'].append(error_text(exc, root))
    if multiplicity is not None:
        try:
            validate_multiplicity(multiplicity)
        except SystemExit as exc:
            result['scope_errors'].append(error_text(exc, root))
    actual = result['actual']
    checks = {'formula': comparison(expected_formula, actual['formula'] if actual else None),
              'charge': comparison(charge, actual['charge'] if actual else None),
              'cip': cip_comparison(cip, actual),
              'second_source': {'status': 'unknown', 'reason': 'second source not supplied'}}
    second = row.get('second_source', '')
    if second:
        try:
            if second.startswith('smiles:'):
                text = second[len('smiles:'):]
                # Inline SMILES must never be interpreted as a filesystem path by the shared reader.
                if not text or Path(text).expanduser().exists() or '/' == text[:1] or '\n' in text:
                    raise ValueError('second_source smiles: needs SMILES text, not a file path')
                other, _, diagnostics = read_molecule(text, Chem, preserve_explicit_h=True)
                result['second_source_sha256'] = digest(text.encode('utf-8'))
            else:
                other, diagnostics = read_structure(root, second, inputs, Chem)
            try:
                validate_scope(other, Chem, diagnostics)
            except SystemExit as exc:
                result['scope_errors'].append('second source: ' + error_text(exc, root))
            result['second_actual'] = inspect_molecule(other, diagnostics, Chem, descriptors)
            checks['second_source'] = compare_sources(mol, other, Chem) if actual else {
                'status': 'unknown', 'reason': 'primary structure unreadable'}
        except (SystemExit, ValueError, RuntimeError, OSError) as exc:
            checks['second_source'] = {'status': 'unknown', 'reason': error_text(exc, root)}
    statuses = [c['status'] for c in checks.values()]
    result['checks'] = checks
    result['status'] = ('out_of_scope' if result['scope_errors'] else
                        'has_mismatch' if 'mismatch' in statuses else
                        'incomplete' if 'unknown' in statuses or multiplicity is None or not actual else 'all_match')
    return result, mol


def reaction_check(rows, species):
    sides = {'left': Counter(), 'right': Counter()}
    charges = {'left': Fraction(0), 'right': Fraction(0)}
    seen = set()
    unavailable = []
    for row in rows:
        key, side = row['species_id'], row['side']
        if key not in species or side not in sides:
            raise ValueError('reaction needs known species_id and side left/right')
        seen.add((key, side))
        try:
            coefficient = Fraction(row['coefficient'])
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError('reaction coefficient must be a positive number or fraction') from exc
        if coefficient <= 0:
            raise ValueError('reaction coefficient must be positive')
        actual = species[key]['actual']
        if actual is None:
            unavailable.append(key)
            continue
        for element, count in actual['element_counts'].items():
            sides[side][element] += coefficient * count
        charges[side] += coefficient * actual['charge']
    if {side for _, side in seen} != {'left', 'right'}:
        raise ValueError('reaction must have both left and right sides')
    if unavailable:
        return {'status': 'unknown', 'unreadable_species': unavailable}
    delta = {e: sides['right'][e] - sides['left'][e] for e in sorted(set(sides['left']) | set(sides['right']))}
    delta = {e: d for e, d in delta.items() if d}
    charge_delta = charges['right'] - charges['left']
    messages = [f"右侧{'少' if d < 0 else '多'} {abs(d)} 个 {e}" for e, d in delta.items()]
    if charge_delta:
        messages.append(f'右侧减左侧总电荷差：{charge_delta}')
    return {'status': 'mismatch' if delta or charge_delta else 'match',
            'element_totals': {side: {e: str(n) for e, n in sorted(counts.items())} for side, counts in sides.items()},
            'charge_totals': {side: str(n) for side, n in charges.items()},
            'delta_right_minus_left': {e: str(d) for e, d in delta.items()},
            'charge_delta_right_minus_left': str(charge_delta), 'messages': messages,
            'note': '不自动补组分；差额可能来自缺失副产物或未画出的组分。'}


def markdown(report):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# 开题物种核验', '', '这是自动核验报告，不是结构签字。原子及键序号从 1 开始。',
             '第二来源一致不证明来源独立；未提供的可选反应式不属于本次核验范围。', '',
             '| 物种 | 汇总 | 分子式 | 电荷 | 源原子 / 显式氢 / 补氢后总数 | 组分 | CIP | 预览 |',
             '|---|---|---|---|---|---|---|---|']
    for item in report['species']:
        a = item['actual'] or {}
        lines.append('| ' + ' | '.join(map(cell, [item['species_id'], item['status'], a.get('formula', '未知'),
            a.get('charge', '未知'), f"{a.get('atom_count', '?')} / {a.get('explicit_h_atom_count', '?')} / {a.get('atom_count_with_h', '?')}",
            a.get('component_count', '?'), a.get('chiral_centers', '未知'),
            f"[{item['species_id']}]({item['species_id']}/preview.png)"])) + ' |')
    for item in report['species']:
        lines += ['', f"## {item['species_id']}", '', f"- 结构来源：`{item['source_file']}`",
                  f"- 规范同分异构 SMILES：`{(item['actual'] or {}).get('canonical_isomeric_smiles', '未知')}`",
                  f"- 研究者提供的多重度：{item['multiplicity']}",
                  f"- 立体依据：{cell(item['stereo_basis']) or '未给'}；人工备注：{cell(item['note']) or '无'}"]
        for name, check in item['checks'].items():
            lines.append(f"- {name}：{check['status']} — {cell(json.dumps(check, ensure_ascii=False))}")
        lines += [f'- {cell(message)}' for message in item['scope_errors'] + item['read_errors'] + item['warnings']]
        lines.append('- 读入诊断：' + cell(json.dumps((item['actual'] or {}).get('import_diagnostics'), ensure_ascii=False)))
    lines += ['', '## 反应式', '', '```json', json.dumps(report['reaction'], ensure_ascii=False, indent=2), '```',
              '', '## 输入文件 SHA-256', '']
    lines += [f"- `{entry['path']}`：`{entry['sha256']}`" for entry in report['inputs']]
    return '\n'.join(lines) + '\n'


def preview(mol, name):
    from rdkit.Chem.Draw import rdMolDraw2D
    if mol is None:
        from PIL import Image, ImageDraw
        picture = Image.new('RGB', (1000, 700), 'white')
        ImageDraw.Draw(picture).text((30, 30), name + ': structure unreadable; see report', fill='black')
        buffer = io.BytesIO()
        picture.save(buffer, format='PNG')
        return buffer.getvalue()
    drawing = rdMolDraw2D.MolDraw2DCairo(1200, 800)
    from rdkit import Chem
    annotated = Chem.Mol(mol)
    for atom in annotated.GetAtoms():
        atom.SetProp('atomNote', str(atom.GetIdx() + 1))
    rdMolDraw2D.PrepareAndDrawMolecule(drawing, annotated, legend=name)
    drawing.FinishDrawing()
    return drawing.GetDrawingText()


def run(study, species_file='analyses/intake/species.csv', reaction_file=None, output_dir='analyses/intake'):
    root = study_root(study)
    output = safe_path(root, output_dir)
    if len(Path(output_dir).parts) < 2 or Path(output_dir).parts[0] != 'analyses':
        raise ValueError('output directory must be below analyses/')
    inputs = {}
    rows = csv_rows(input_bytes(root, species_file, inputs), REQUIRED)
    ids = set()
    for row in rows:
        name = row['species_id']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name) or name in ids:
            raise ValueError('species_id must be unique and contain only letters, digits, underscores or hyphens')
        if row['role'] not in ROLES:
            raise ValueError('unsupported species role')
        ids.add(name)
        # Do safety preflight outside per-species chemistry error handling.
        safe_path(root, row['source_file'])
        if row.get('second_source') and not row['second_source'].startswith('smiles:'):
            safe_path(root, row['second_source'])
    targets = [output / 'species-check.json', output / 'species-check.md', *(output / name for name in ids)]
    for path in targets:
        safe_path(root, path.relative_to(root).as_posix())
        if path.exists():
            raise ValueError('output already exists; choose a new --output-dir and retain old reports')
    if reaction_file is None:
        default = safe_path(root, 'analyses/intake/reaction.csv')
        reaction_file = 'analyses/intake/reaction.csv' if default.exists() else None
    reaction_rows = csv_rows(input_bytes(root, reaction_file, inputs), {'species_id', 'side', 'coefficient'}) if reaction_file else None
    Chem, _, _, descriptors = load_rdkit()
    from rdkit import rdBase
    species, images = [], {}
    for row in rows:
        item, mol = check_one(row, root, inputs, Chem, descriptors)
        item['preview'] = (Path(output_dir) / row['species_id'] / 'preview.png').as_posix()
        images[item['preview']] = preview(mol, row['species_id'])
        species.append(item)
    reaction = reaction_check(reaction_rows, {s['species_id']: s for s in species}) if reaction_rows else {'status': 'unknown', 'reason': 'reaction CSV not supplied'}
    report = {'rdkit_version': rdBase.rdkitVersion, 'atom_index_base': 1,
              'atom_numbering': 'source atom order, explicit H retained; bracket H counts are not separate atoms',
              'species': species, 'reaction': reaction, 'inputs': list(inputs.values()),
              'warnings': ['Second-source agreement does not establish independence of its provenance.',
                           'No structure is signed or corrected by this report.']}
    # Detect edits while the shared readers were working, before publishing evidence.
    for entry in report['inputs']:
        input_bytes(root, entry['path'], inputs)
    payloads = {(Path(output_dir) / 'species-check.json').as_posix(): (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode(),
                (Path(output_dir) / 'species-check.md').as_posix(): markdown(report).encode(), **images}
    safe_path(root, output_dir).mkdir(parents=True, exist_ok=True)
    for name in sorted(ids):
        safe_path(root, (Path(output_dir) / name).as_posix()).mkdir()
    for relative, data in payloads.items():
        path = safe_path(root, relative)
        # Exclusive creation keeps previous reports intact, including partial failed runs.
        with path.open('xb') as stream:
            stream.write(data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--species', default='analyses/intake/species.csv', help='study-relative CSV path')
    parser.add_argument('--reaction', help='study-relative CSV; otherwise use default if present')
    parser.add_argument('--output-dir', default='analyses/intake', help='study-relative analyses directory; choose a new name for reruns')
    args = parser.parse_args()
    try:
        report = run(args.study, args.species, args.reaction, args.output_dir)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(2, f'ERROR: {exc}\n')
    print(json.dumps({'species': {s['species_id']: s['status'] for s in report['species']},
                      'reaction': report['reaction']['status'],
                      'report': str(Path(args.output_dir) / 'species-check.json')}, ensure_ascii=False))
    return 0  # Successful report generation is not scientific acceptance.


if __name__ == '__main__':
    raise SystemExit(main())
