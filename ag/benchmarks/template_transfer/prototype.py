"""T191's four-pair, local-only experiment; deliberately not an ag command.

Input is the explicit B reactant graph plus separately supplied geometry and
row mapping. No bond perception, quantum program, study, catalog or transport.
No upstream code copied. See SOURCES.md and docs/benchmarks/template-transfer.md.
"""
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from rdkit import Chem, DistanceGeometry, rdBase
from rdkit.Chem import rdDistGeom
from rdkit.Geometry import Point3D

from ag import catalog_v2, crest_input, geometry

DATA_PATH = Path(__file__).with_name('pairs.json')
DATA_BYTES = DATA_PATH.read_bytes()
DATA = json.loads(DATA_BYTES)
CORE = (1, 2, 3, 4, 5, 6, 7)  # ring plus unchanged COOH anchor; never R


def molecule(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError('Invalid reactant graph')
    maps = [a.GetAtomMapNum() for a in mol.GetAtoms()]
    if not all(maps) or len(set(maps)) != len(maps):
        raise ValueError('Ambiguous or missing atom maps')
    if (len(Chem.GetMolFrags(mol)) != 1 or Chem.GetFormalCharge(mol) != 0
            or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms())
            or any(a.GetSymbol() not in {'C', 'N', 'O'} for a in mol.GetAtoms())):
        raise ValueError('Outside these neutral closed-shell benchmark graphs')
    if any(cip == '?' for _, cip in Chem.FindMolChiralCenters(mol, includeUnassigned=True)):
        raise ValueError('Unspecified stereochemistry')
    return Chem.AddHs(mol)


def map_indices(mol):
    return {a.GetAtomMapNum(): a.GetIdx() for a in mol.GetAtoms() if a.GetAtomMapNum()}


def check_geometry(mol, coordinates):
    """Check obvious clashes and reactant handedness, without perceiving bonds.

    The reactant graph is only a reference for handedness/peripheral placement.
    Near-planar reactive centres are conservatively refused for manual review.
    This check cannot classify the TS or its inward/outward reaction mode.
    """
    xyz = np.asarray(coordinates, dtype=float)
    if xyz.shape != (mol.GetNumAtoms(), 3) or not np.isfinite(xyz).all():
        raise ValueError('Coordinates must be finite and cover all atoms')
    radii = Chem.GetPeriodicTable()
    for i, j in combinations(range(len(xyz)), 2):
        distance = float(np.linalg.norm(xyz[i] - xyz[j]))
        bonded = mol.GetBondBetweenAtoms(i, j) is not None
        cutoff = 0.4 if bonded else max(0.4, 0.65 * (
            radii.GetRcovalent(mol.GetAtomWithIdx(i).GetAtomicNum()) +
            radii.GetRcovalent(mol.GetAtomWithIdx(j).GetAtomicNum())))
        if distance < cutoff:
            raise ValueError(f'Collision between XYZ rows {i + 1} and {j + 1}')
    expected = dict(Chem.FindMolChiralCenters(mol, includeUnassigned=True))
    for i in expected:
        neighbors = [a.GetIdx() for a in mol.GetAtomWithIdx(i).GetNeighbors()]
        unit = xyz[neighbors] - xyz[i]
        unit /= np.linalg.norm(unit, axis=1)[:, None]
        volume = np.linalg.det(unit[:3] - unit[3])
        if abs(volume) < 0.05:
            raise ValueError(f'Near-planar stereochemistry at XYZ row {i + 1}; review required')
    observed = Chem.Mol(mol)
    observed.RemoveAllConformers()
    conformer = Chem.Conformer(len(xyz))
    for i, point in enumerate(xyz):
        conformer.SetAtomPosition(i, Point3D(*map(float, point)))
    observed.AddConformer(conformer)
    Chem.RemoveStereochemistry(observed)
    Chem.AssignStereochemistryFrom3D(observed)
    actual = dict(Chem.FindMolChiralCenters(observed, includeUnassigned=True))
    if actual != expected:
        raise ValueError('Geometry stereochemistry differs from explicit reactant graph')


def _read_template(template_xyz, description):
    if description.get('template_id') != DATA['template']['id']:
        raise ValueError('Inapplicable template: only B-trans-outward is in this benchmark')
    # This order is also the reference order for row_by_atom, including AddHs.
    if description.get('reactant') != DATA['template']['reactant']:
        raise ValueError('Inapplicable template graph, atom order or stereochemistry')
    source = description.get('source', {})
    if (source.get('status') not in {'synthetic-test-only', 'unvalidated-source-geometry'}
            or not isinstance(source.get('location'), str) or not source['location'].strip()):
        raise ValueError('Explicit source location and unvalidated evidence status required')
    if source['status'] == 'unvalidated-source-geometry' and source.get('doi') != DATA['doi']:
        raise ValueError('Source DOI does not match fixed benchmark')
    path = Path(template_xyz)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Template symlinks are not accepted')
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != description.get('sha256'):
        raise ValueError('Template hash mismatch')
    # Strict single-frame, element and finite-coordinate checks from current ag.
    catalog_v2.xyz(raw)
    lines = raw.decode('utf-8').splitlines()
    symbols = [line.split()[0] for line in lines[2:]]
    xyz = np.array([[float(x) for x in line.split()[1:]] for line in lines[2:]])
    mol = molecule(description['reactant'])
    rows = description.get('row_by_atom', [])
    if (len(rows) != mol.GetNumAtoms() or len(xyz) != len(rows)
            or any(type(row) is not int for row in rows)
            or sorted(rows) != list(range(1, len(rows) + 1))):
        raise ValueError('Ambiguous/incomplete template row mapping')
    if [symbols[row - 1] for row in rows] != [a.GetSymbol() for a in mol.GetAtoms()]:
        raise ValueError('Template row mapping element mismatch')
    ordered = xyz[np.array(rows) - 1]
    check_geometry(mol, ordered)
    return mol, ordered


def generate(pair_id, *, template_xyz, description, output_dir, force_constant, seed=191):
    """Write a fresh guess/constraints/report, or refuse without replacing files.

    description: template_id, exact mapped reactant SMILES, sha256,
    row_by_atom (one-based XYZ rows in molecule(reactant) order), source dict.
    This API intentionally accepts only the four fixed pairs. Synthetic source
    status propagates to every artifact; no evidence status can mean validated.
    """
    pair = next((p for p in DATA['pairs'] if p['id'] == pair_id), None)
    if pair is None:
        raise ValueError('Pair is outside the fixed four-sample benchmark')
    force_constant = geometry.finite_number(force_constant)
    if force_constant <= 0:
        raise ValueError('Force constant must be positive (Eh/Bohr^2)')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Seed must be an explicit nonnegative 32-bit integer')
    out = Path(output_dir)
    if any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('Output symlinks are not accepted')
    if out.exists():
        raise FileExistsError('Output directory already exists; choose a new name')
    source_mol, source_xyz = _read_template(template_xyz, description)
    target = molecule(pair['reactant'])
    source_map, target_map = map_indices(source_mol), map_indices(target)
    positions = {target_map[m]: source_xyz[source_map[m]] for m in CORE}

    # Retain the ordinary reactant graph. Only its core-core distance bounds
    # are replaced by the supplied coordinates; no half-bond TS graph is built.
    bounds = rdDistGeom.GetMoleculeBoundsMatrix(target)
    for i, j in combinations(sorted(positions), 2):
        distance = float(np.linalg.norm(positions[i] - positions[j]))
        bounds[i, j], bounds[j, i] = distance + 0.005, distance - 0.005
    if not DistanceGeometry.DoTriangleSmoothing(bounds):
        raise ValueError('Core coordinates incompatible with reactant embedding bounds')
    params = rdDistGeom.ETKDGv3()
    params.randomSeed = seed
    params.numThreads = 1
    params.enforceChirality = True
    params.useRandomCoords = True
    params.SetBoundsMat(bounds)
    params.SetCoordMap({i: Point3D(*map(float, point)) for i, point in positions.items()})
    if rdDistGeom.EmbedMolecule(target, params) < 0:
        raise ValueError('Constrained embedding failed; no automatic repair')
    xyz = target.GetConformer().GetPositions()
    error = max(float(np.linalg.norm(xyz[i] - point)) for i, point in positions.items())
    if error > 0.02:
        raise ValueError('Core embedding drift exceeds 0.02 angstrom; no coordinate overwrite')
    check_geometry(target, xyz)
    status = description['source']['status']
    frame = geometry.Frame(tuple(a.GetSymbol() for a in target.GetAtoms()),
                           tuple(map(tuple, xyz)), f'{pair_id} {status}; unvalidated TS guess')
    xyz_text = geometry.xyz_text([frame])
    catalog_v2.xyz(xyz_text.encode())
    distances = [(target_map[a] + 1, target_map[b] + 1,
                  float(np.linalg.norm(positions[target_map[a]] - positions[target_map[b]])))
                 for a, b in combinations(CORE, 2)]
    constraints = '$constrain\n' + f'  force constant={force_constant:.12g}\n' + ''.join(
        f'  distance: {i}, {j}, {distance:.10f}\n' for i, j, distance in distances) + '$end\n'
    crest_input.validate(constraints, len(xyz))
    report = dict(pair=pair, template=description, core_maps=list(CORE),
                  atom_rows=[dict(row=a.GetIdx() + 1, element=a.GetSymbol(),
                                  map=a.GetAtomMapNum() or None,
                                  attached_to=[n.GetIdx() + 1 for n in a.GetNeighbors()])
                             for a in target.GetAtoms()],
                  core_max_error_angstrom=error, force_constant=force_constant,
                  force_constant_unit='Eh/Bohr^2', seed=seed, rdkit_version=rdBase.rdkitVersion,
                  pairs_sha256=sha256(DATA_BYTES).hexdigest(),
                  xyz_sha256=sha256(xyz_text.encode()).hexdigest(),
                  constraints_sha256=sha256(constraints.encode()).hexdigest(),
                  scientific_status='unvalidated; no quantum calculations or IRC',
                  method='ETKDGv3 reactant graph; explicit core distance/coordinate constraints')
    # Reserve a new directory only after validation; all files are exclusive.
    # Partial I/O failure leaves the directory in place, never retried/cleaned.
    out.mkdir()
    with (out / 'guess.xyz').open('x') as handle:
        handle.write(xyz_text)
    with (out / 'constraints.inp').open('x') as handle:
        handle.write(constraints)
    with (out / 'transform.json').open('x') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    return report
