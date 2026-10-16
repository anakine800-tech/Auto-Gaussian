#!/usr/bin/env python3
"""Compare mapped TS local chirality with a signed reference product; draft only."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import re

import numpy as np
from rdkit import Chem, rdBase
from rdkit.Chem import rdCIPLabeler

from check_species import csv_rows, input_bytes, safe_path, study_root
from make_gaussian_input import read_molecule, validate_scope

TETRAHEDRAL = {Chem.ChiralType.CHI_TETRAHEDRAL_CCW: 1,
               Chem.ChiralType.CHI_TETRAHEDRAL_CW: -1}
VOLUME_SCALE = 16 / (3 * math.sqrt(3))  # Maximum determinant for four unit vectors.
NOTICE = '仅为产物构型及通道建议；须人工确认，不证明 TS、反应方向或 IRC 已验证。'


def cip_labels(mol):
    # Use the accurate labeler on the REFERENCE graph, never on TS coordinates.
    for atom in mol.GetAtoms():
        if atom.HasProp('_CIPCode'):
            atom.ClearProp('_CIPCode')
    rdCIPLabeler.AssignCIPLabels(mol)
    return {a.GetIdx(): a.GetProp('_CIPCode') for a in mol.GetAtoms() if a.HasProp('_CIPCode')}


def reference_centers(mol):
    labels = cip_labels(mol)
    relative = {a.GetIdx() for group in mol.GetStereoGroups()
                if group.GetGroupType() != Chem.StereoGroupType.STEREO_ABSOLUTE
                for a in group.GetAtoms()}
    centers = []
    for atom in mol.GetAtoms():
        tag = atom.GetChiralTag()
        if tag == Chem.ChiralType.CHI_UNSPECIFIED:
            continue
        if tag not in TETRAHEDRAL:
            raise ValueError('only specified tetrahedral reference centers are supported')
        index = atom.GetIdx()
        neighbors = [str(a.GetIdx() + 1) for a in atom.GetNeighbors()]
        # Bracket H counts and implicit H both have no source atom row. RDKit
        # places this fourth neighbor last in its internal tetrahedral ordering.
        if len(neighbors) == 3 and atom.GetTotalNumHs() == 1:
            neighbors.append(f'H@{index + 1}')
        if len(neighbors) != 4:
            raise ValueError(f'reference atom {index + 1}: needs four neighbors including mapped H')
        cip = labels.get(index)
        reasons = []
        if cip in {'r', 's'}:
            reasons.append('pseudoasymmetric r/s center')
        elif cip not in {'R', 'S'}:
            reasons.append('reference has no supported absolute CIP label')
        else:
            # If constitution alone cannot rank the ligands, R/S can change when
            # another center changes even though this center does not invert.
            # Remove ALL other stereo (also bond stereo), not just one center at
            # a time: simultaneous changes must not evade the dependency check.
            isolated = Chem.Mol(mol)
            Chem.RemoveStereochemistry(isolated)
            isolated.GetAtomWithIdx(index).SetChiralTag(tag)
            if cip_labels(isolated).get(index) != cip:
                reasons.append('CIP depends on other stereochemistry; local inversion is insufficient')
        if index in relative:
            reasons.append('relative/mixture stereo group does not specify an absolute reference')
        centers.append({'reference_atom': index + 1, 'element': atom.GetSymbol(),
                        'reference_cip': cip, 'reference_chiral_tag': str(tag),
                        'reference_sign': TETRAHEDRAL[tag], 'neighbors': neighbors,
                        'review_reasons': reasons})
    if not centers:
        raise ValueError('reference must contain at least one specified tetrahedral center')
    return centers


def read_reference(root, relative, mapping_file, inputs):
    if Path(relative).suffix.lower() not in {'.mol', '.sdf', '.cdxml'}:
        raise ValueError('reference must be a .mol, .sdf or .cdxml file inside the study')
    path = safe_path(root, relative)
    input_bytes(root, relative, inputs)
    try:
        mol, _, diagnostics = read_molecule(str(path), Chem, preserve_explicit_h=True)
        validate_scope(mol, Chem, diagnostics)
    except SystemExit as exc:
        raise ValueError(str(exc).removeprefix('ERROR: ')) from exc
    input_bytes(root, relative, inputs)
    centers = reference_centers(mol)
    rows = csv_rows(input_bytes(root, mapping_file, inputs), {'reference_atom', 'ts_atom'})
    mapping, elements, used = {}, {}, set()
    hidden_h = {n for center in centers for n in center['neighbors'] if n.startswith('H@')}
    for row in rows:
        key, target = row['reference_atom'], row['ts_atom']
        if not re.fullmatch(r'[1-9]\d*', target):
            raise ValueError('ts_atom must be a positive 1-based integer')
        target = int(target)
        if key in mapping or target in used:
            raise ValueError('mapping must be one-to-one; duplicate reference_atom or ts_atom')
        if key in hidden_h:
            element = 'H'
        elif re.fullmatch(r'[1-9]\d*', key) and int(key) <= mol.GetNumAtoms():
            element = mol.GetAtomWithIdx(int(key) - 1).GetSymbol()
        else:
            raise ValueError(f'invalid reference_atom: {key}; use a source atom or H@<center>')
        mapping[key], elements[key] = target, element
        used.add(target)
    required = {str(c['reference_atom']) for c in centers} | {n for c in centers for n in c['neighbors']}
    missing = sorted(required - mapping.keys())
    if missing:
        raise ValueError('mapping missing center or neighbor atoms: ' + ', '.join(missing))
    return {'source': relative, 'map': mapping_file, 'centers': centers,
            'mapping': mapping, 'elements': elements}


def cartesian_rows(lines):
    symbols, points = [], []
    table = Chem.GetPeriodicTable()
    elements = {table.GetElementSymbol(n) for n in range(1, 119)}
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError('geometry needs element and three Cartesian coordinates per row')
        symbol = fields[0]
        if symbol.isdigit() and 1 <= int(symbol) <= 118:
            symbol = table.GetElementSymbol(int(symbol))
        if symbol not in elements:
            raise ValueError('geometry contains an invalid element')
        xyz = [float(value.replace('D', 'E').replace('d', 'e')) for value in fields[1:]]
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError('geometry coordinates must be finite')
        symbols.append(symbol)
        points.append(xyz)
    if not points:
        raise ValueError('geometry is empty')
    return symbols, np.asarray(points)


def read_geometry(root, attempt, geometry, inputs):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', attempt):
        raise ValueError('--ts needs comma-separated Attempt directory names, not paths')
    base = f'attempts/{attempt}'
    if geometry == 'final':
        relative = f'{base}/final_input.xyz'
        lines = input_bytes(root, relative, inputs).decode('utf-8').splitlines()
        if not lines or not re.fullmatch(r'[1-9]\d*', lines[0].strip()):
            raise ValueError('final_input.xyz needs a positive atom count')
        count = int(lines[0])
        if len(lines) < count + 2 or any(line.strip() for line in lines[count + 2:]):
            raise ValueError('final_input.xyz must contain exactly one complete XYZ frame')
        frame = cartesian_rows(lines[2:count + 2])
        pointer = None
    else:
        relative = f'{base}/manifest.json'
        manifest = json.loads(input_bytes(root, relative, inputs))
        science = manifest.get('science') if isinstance(manifest, dict) else None
        if not isinstance(science, dict):
            raise ValueError('manifest needs science.geometry for --geometry input')
        groups = science.get('structures')
        if groups is not None:
            if not isinstance(groups, list) or len(groups) != 3 or not isinstance(groups[2], dict):
                raise ValueError('QST input needs an explicit third (TS guess) geometry; QST2 has none')
            text = groups[2].get('geometry')
            pointer = '/science/structures/2/geometry'
        else:
            text = science.get('geometry')
            pointer = '/science/geometry'
        if not isinstance(text, str):
            raise ValueError('manifest input geometry must be Cartesian text')
        frame = cartesian_rows(text.splitlines())
    return *frame, {'path': relative, 'sha256': inputs[relative]['sha256'], 'json_pointer': pointer}


def signed_volume(center, neighbors):
    """Ordered tetrahedron of four center-relative unit vectors, in [-1, 1]."""
    vectors = np.asarray(neighbors, dtype=float) - center
    lengths = np.linalg.norm(vectors, axis=1)
    if not np.isfinite(lengths).all() or np.any(lengths < 1e-12):
        raise ValueError('mapped neighbor coincides with center or has invalid distance')
    unit = vectors / lengths[:, None]
    return float(np.linalg.det(unit[:3] - unit[3]) / VOLUME_SCALE)


def compare(reference, symbols, points, minimum):
    mapping = reference['mapping']
    for key, target in mapping.items():
        if target > len(symbols):
            raise ValueError(f'mapped ts_atom {target} exceeds geometry atom count')
        if symbols[target - 1] != reference['elements'][key]:
            raise ValueError(f'element mismatch: reference atom {key} -> TS atom {target}')
    results = []
    for center in reference['centers']:
        target = mapping[str(center['reference_atom'])]
        neighbors = [mapping[n] for n in center['neighbors']]
        volume = signed_volume(points[target - 1], points[np.asarray(neighbors) - 1])
        reasons = list(center['review_reasons'])
        if abs(volume) < minimum:
            relation, label = 'unknown', 'unknown'
            reasons.append('absolute signed volume below min_chirality')
        else:
            relation = 'same' if volume * center['reference_sign'] > 0 else 'opposite'
            label = ('needs_review' if reasons else center['reference_cip'] if relation == 'same'
                     else {'R': 'S', 'S': 'R'}[center['reference_cip']])
        results.append({**center, 'ts_atom': target, 'ts_neighbors': neighbors,
                        'signed_volume': volume, 'relation': relation, 'label': label, 'reasons': reasons})
    return results


def configuration(centers):
    return ';'.join(f"{c['element']}{c['reference_atom']}:{c['label']}" for c in centers)


def read_channels(root, relative, inputs):
    rows = csv_rows(input_bytes(root, relative, inputs), {'channel_id', 'product_branch'})
    ids = set()
    for row in rows:
        if not row['channel_id'] or row['channel_id'] in ids or not row['product_branch']:
            raise ValueError('channels need unique nonempty channel_id and nonempty product_branch')
        ids.add(row['channel_id'])
    return rows


def suggestion(item, channels):
    matches = [c['channel_id'] for c in channels if c['product_branch'] == item['product_configuration']]
    notes = []
    if any(c['label'] in {'unknown', 'needs_review'} for c in item['product_centers']):
        notes.append('product contains unknown/needs_review centers')
    if item['catalyst_check']['status'] in {'changed', 'needs_review'}:
        notes.append('catalyst self-check requires review')
    if not matches:
        notes.append('no exact product_branch match')
    elif len(matches) > 1:
        notes.append('multiple product_branch matches: ' + ';'.join(matches))
    return {'attempt': item['attempt'], 'product_configuration': item['product_configuration'],
            'suggested_channel_id': matches[0] if len(matches) == 1 and not notes else '',
            'status': 'pending_confirmation', 'note': '; '.join(notes) or 'unique match; human confirmation required'}


def markdown(report):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# TS 立体标签（草稿）', '', NOTICE, '',
             '编号从 1 开始；构型标签使用参照产物原子序号。',
             f"几何来源：`{report['geometry']}`；阈值：`{report['min_chirality']}`；RDKit：`{report['rdkit_version']}`。",
             '参照符号来自四面体手性标记及邻居顺序（隐含 H 最后），不使用二维绘图的平面坐标。',
             '体积为 det(u1−u4,u2−u4,u3−u4)/(16/(3√3))，ui 是中心指向邻居的单位向量。']
    for item in report['attempts']:
        lines += ['', f"## {item['attempt']}", '', f"产物构型：`{item['product_configuration']}`",
                  f"催化剂自检：**{item['catalyst_check']['status']}**"]
        lines += [f'**警告：{cell(warning)}**' for warning in item['warnings']]
        lines += ['', '| 参照 | 中心 | TS 原子 | 参照 CIP | 带符号体积 | 与参照关系 | 标签 | 说明 |',
                  '|---|---|---|---|---|---|---|---|']
        for kind, centers in [('product', item['product_centers']), ('catalyst', item['catalyst_centers'])]:
            for c in centers:
                lines.append('| ' + ' | '.join(map(cell, [kind, c['reference_atom'], c['ts_atom'],
                    c['reference_cip'], f"{c['signed_volume']:.8f}", c['relation'], c['label'], '; '.join(c['reasons'])])) + ' |')
    if report['channel_suggestions'] is not None:
        lines += ['', '## 通道建议（pending_confirmation）', '',
                  '| Attempt | 产物构型 | 建议通道 | 状态 | 说明 |', '|---|---|---|---|---|']
        for row in report['channel_suggestions']:
            lines.append('| ' + ' | '.join(cell(v) for v in row.values()) + ' |')
    lines += ['', '## 输入文件 SHA-256', '']
    lines += [f"- `{entry['path']}`：`{entry['sha256']}`" for entry in report['inputs']]
    return '\n'.join(lines) + '\n'


def run(study, name, ts, product, product_map, *, geometry='final', catalyst=None,
        catalyst_map=None, channels=None, min_chirality=0.05):
    root = study_root(study)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
        raise ValueError('name must contain only letters, digits, underscores or hyphens (max 80)')
    if geometry not in {'final', 'input'}:
        raise ValueError('geometry must be final or input')
    if not math.isfinite(min_chirality) or not 0 < min_chirality <= 1:
        raise ValueError('min_chirality must be finite and in (0, 1]')
    if bool(catalyst) != bool(catalyst_map):
        raise ValueError('--catalyst and --catalyst-map must be supplied together')
    attempts = [a.strip() for a in ts.split(',')]
    if len(set(attempts)) != len(attempts):
        raise ValueError('--ts contains duplicate Attempts')
    output_dir = f'analyses/ts-labels/{name}'
    if safe_path(root, output_dir).exists():
        raise ValueError('output directory already exists; choose a new name')
    inputs = {}
    reference = read_reference(root, product, product_map, inputs)
    catalyst_ref = read_reference(root, catalyst, catalyst_map, inputs) if catalyst else None
    channel_rows = read_channels(root, channels, inputs) if channels else None
    items = []
    for attempt in attempts:
        symbols, points, source = read_geometry(root, attempt, geometry, inputs)
        product_centers = compare(reference, symbols, points, min_chirality)
        catalyst_centers = compare(catalyst_ref, symbols, points, min_chirality) if catalyst_ref else []
        changed = [c['reference_atom'] for c in catalyst_centers if c['relation'] == 'opposite']
        unresolved = [c['reference_atom'] for c in catalyst_centers if c['label'] in {'unknown', 'needs_review'}]
        status = ('not_requested' if not catalyst_ref else 'changed' if changed else
                  'needs_review' if unresolved else 'unchanged')
        warnings = []
        if changed:
            warnings.append('催化剂局部构型与参照相反：' + ', '.join(map(str, changed)) + '；检查结构与映射。')
        if unresolved:
            warnings.append('催化剂自检无法确认：' + ', '.join(map(str, unresolved)))
        items.append({'attempt': attempt, 'geometry_source': source, 'product_centers': product_centers,
                      'product_configuration': configuration(product_centers), 'catalyst_centers': catalyst_centers,
                      'catalyst_check': {'status': status, 'changed_centers': changed, 'unresolved_centers': unresolved},
                      'warnings': warnings})
    suggestions = [suggestion(item, channel_rows) for item in items] if channel_rows is not None else None
    report = {'rdkit_version': rdBase.rdkitVersion, 'atom_index_base': 1, 'geometry': geometry,
              'min_chirality': min_chirality, 'volume_definition': 'det(u1-u4,u2-u4,u3-u4)/(16/(3*sqrt(3)))',
              'reference_sign_basis': 'RDKit bond/neighbor order; virtual H last; CCW +1, CW -1',
              'product': {'path': product, 'map': product_map},
              'catalyst': {'path': catalyst, 'map': catalyst_map} if catalyst else None,
              'attempts': items, 'channel_suggestions': suggestions, 'inputs': list(inputs.values()),
              'notice': NOTICE,
              'limitations': ['Reference intake verification and human signature are prerequisites, not inferred by this script.',
                              'Mapping must be human-reviewed; element checks cannot detect same-element permutations.',
                              'Only mapped tetrahedral local geometry is compared; bond orders and reaction direction are not inferred.',
                              'XYZ does not encode isotopes; isotope identity must be checked against the reference mapping.']}
    payloads = {'labels.json': json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
                'labels.md': markdown(report)}
    if suggestions is not None:
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=['attempt', 'product_configuration', 'suggested_channel_id', 'status', 'note'])
        writer.writeheader()
        writer.writerows(suggestions)
        payloads['channel-suggestions.csv'] = stream.getvalue()
    # Refuse mixed revisions before any report is published. Each run claims a
    # fresh directory; partial failures are retained and never reused.
    for entry in report['inputs']:
        input_bytes(root, entry['path'], inputs)
    safe_path(root, 'analyses/ts-labels').mkdir(parents=True, exist_ok=True)
    safe_path(root, output_dir).mkdir()
    for filename, text in payloads.items():
        with safe_path(root, f'{output_dir}/{filename}').open('x', encoding='utf-8', newline='') as handle:
            handle.write(text)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('study', 'name', 'ts', 'product', 'product-map'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--geometry', choices=['final', 'input'], default='final')
    parser.add_argument('--catalyst')
    parser.add_argument('--catalyst-map')
    parser.add_argument('--channels')
    parser.add_argument('--min-chirality', type=float, default=0.05)
    args = parser.parse_args(argv)
    try:
        report = run(**vars(args))
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f'ERROR: {exc}\n')
    print(json.dumps({'report': f'analyses/ts-labels/{args.name}/labels.json',
                      'configurations': {a['attempt']: a['product_configuration'] for a in report['attempts']},
                      'status': 'pending_confirmation'}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
