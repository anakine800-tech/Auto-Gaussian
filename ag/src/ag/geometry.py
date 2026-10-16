"""Local XYZ helpers. Energies are explicit; coordinates are in angstrom.

RDKit objects are supplied by the command handlers to keep CLI startup light.
No legacy implementation is imported or copied.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

HARTREE_TO_KCAL = 627.5094740631
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][-+]?\d+)?"


@dataclass(frozen=True)
class Frame:
    symbols: tuple
    coordinates: tuple
    comment: str = ""
    energy: float | None = None
    energy_unit: str = "hartree"
    source: str = ""
    source_frame: int = 1


def finite_number(value):
    number = float(str(value).replace("D", "E").replace("d", "e"))
    if not math.isfinite(number):
        raise ValueError("Coordinates and energies must be finite")
    return number


def comment_energy(comment):
    """Accept a leading CREST energy or an explicitly named energy, not an ID."""
    match = re.search(rf"(?:^\s*|\b(?:energy|E)\s*[=:]\s*)({NUMBER})(?=\s|$)", comment)
    unit = "kcal/mol" if "kcal/mol" in comment.lower() else "hartree"
    return (finite_number(match[1]) if match else None), unit


def read_xyz(path):
    path = Path(path)
    lines = path.read_text().splitlines()
    frames, cursor = [], 0
    while cursor < len(lines):
        if not lines[cursor].strip():
            cursor += 1
            continue
        try:
            count = int(lines[cursor])
        except ValueError as exc:
            raise ValueError(f"Invalid XYZ atom count at line {cursor + 1}") from exc
        if count < 1 or cursor + count + 2 > len(lines):
            raise ValueError("Empty or truncated XYZ frame")
        comment = lines[cursor + 1]
        symbols, coordinates = [], []
        for line in lines[cursor + 2:cursor + count + 2]:
            fields = line.split()
            if len(fields) != 4 or not re.fullmatch(r"[A-Z][a-z]?", fields[0]):
                raise ValueError("XYZ atom rows require an element and three coordinates")
            symbols.append(fields[0])
            coordinates.append(tuple(finite_number(x) for x in fields[1:]))
        energy, unit = comment_energy(comment)
        frames.append(Frame(tuple(symbols), tuple(coordinates), comment, energy,
                            unit, str(path), len(frames) + 1))
        cursor += count + 2
    if not frames:
        raise ValueError("XYZ contains no frames")
    return frames


def xyz_text(frames):
    blocks = []
    for frame in frames:
        comment = frame.comment if frame.energy is None else f"energy={frame.energy:.14g} {frame.energy_unit}"
        blocks.append(f"{len(frame.symbols)}\n{comment}\n" + "".join(
            f"{symbol} {x:.10f} {y:.10f} {z:.10f}\n"
            for symbol, (x, y, z) in zip(frame.symbols, frame.coordinates)))
    return "".join(blocks)


def write_xyz(path, frames):
    with Path(path).open("x") as handle:
        handle.write(xyz_text(frames))


def infer_molecule(frame, charge, chem, determine_bonds):
    mol = chem.MolFromXYZBlock(xyz_text([frame]))
    if mol is None:
        raise ValueError("RDKit could not read the XYZ geometry")
    determine_bonds.DetermineBonds(mol, charge=charge, embedChiral=False)
    # CREST/MTD frames can invert a stereocenter or change double-bond geometry.
    chem.AssignStereochemistryFrom3D(mol, replaceExistingTags=True)
    return mol


def graph_key(mol, chem):
    # Preserve bond order, hydrogen counts and formal charge, ignore stereo.
    return chem.MolToSmiles(chem.RemoveHs(mol), isomericSmiles=False)


# A truncated enumeration cannot establish that two localized graphs agree.
RESONANCE_MAX_STRUCTURES = 1000


def resonance_equivalence(left, right, chem):
    """Compare localized graphs at fixed atom indices, including every H.

    This is an electronic-representation check only; callers must still check
    geometry connectivity, electronic-state metadata and stereochemistry.
    UNCONSTRAINED_ANIONS includes the less favored C-local nitronate forms.
    Inputs are copied: inference, graph keys, conformers and stereo stay intact.
    """
    result = dict(executed=False, status='not_needed', reason='编号键级和形式电荷一致。',
                  enumerated={'endpoint': 0, 'reference': 0},
                  limit=RESONANCE_MAX_STRUCTURES, limit_reached=False,
                  atoms=[], bonds=[], formal_charge_differences=[], fragment_charges=[])

    def signature(mol):
        return ({tuple(sorted((b.GetBeginAtomIdx() + 1, b.GetEndAtomIdx() + 1))):
                 b.GetBondTypeAsDouble() for b in mol.GetBonds()},
                tuple(a.GetFormalCharge() for a in mol.GetAtoms()))

    bonds_a, charges_a = signature(left)
    bonds_b, charges_b = signature(right)
    if (tuple(a.GetAtomicNum() for a in left.GetAtoms()) !=
            tuple(a.GetAtomicNum() for a in right.GetAtoms()) or bonds_a.keys() != bonds_b.keys()):
        result.update(status='not_equivalent', reason='含全部 H 的编号元素或连接不同。')
        return result
    result['bonds'] = [list(pair) for pair in sorted(bonds_a) if bonds_a[pair] != bonds_b[pair]]
    result['formal_charge_differences'] = [dict(atom=i + 1, endpoint=a, reference=b)
        for i, (a, b) in enumerate(zip(charges_a, charges_b)) if a != b]
    result['atoms'] = sorted({i for pair in result['bonds'] for i in pair} |
                             {row['atom'] for row in result['formal_charge_differences']})
    for component in chem.GetMolFrags(left):
        result['fragment_charges'].append(dict(atoms=[i + 1 for i in component],
            endpoint=sum(charges_a[i] for i in component), reference=sum(charges_b[i] for i in component)))
    if any(row['endpoint'] != row['reference'] for row in result['fragment_charges']):
        result.update(status='not_equivalent', reason='按原子归属核对的片段总电荷不同。')
        return result
    if not result['atoms']:
        return result
    result['executed'] = True
    matches = []
    try:
        for name, mol, target in (('endpoint', left, (bonds_b, charges_b)),
                                  ('reference', right, (bonds_a, charges_a))):
            supplier = chem.ResonanceMolSupplier(chem.Mol(mol),
                flags=chem.ResonanceFlags.UNCONSTRAINED_ANIONS,
                maxStructs=RESONANCE_MAX_STRUCTURES)
            count = len(supplier)
            result['enumerated'][name] = count
            # RDKit does not expose whether maxStructs cut off another form.
            # Even a match in the capped prefix is conservatively unknown.
            result['limit_reached'] |= count >= RESONANCE_MAX_STRUCTURES
            if supplier.WasCanceled() or count == 0:
                raise ValueError('incomplete resonance enumeration')
            matches.append(any(signature(form) == target for form in supplier))
    except Exception as exc:
        # RDKit may raise several C++/Python exception types; never accept on
        # failure and do not expose molecule contents from exception messages.
        result.update(status='unknown', reason=f'共振枚举失败（{type(exc).__name__}）；不能确认等价。')
        return result
    if result['limit_reached']:
        result.update(status='unknown', reason='共振枚举达到上限；不能确认等价。')
    elif any(matches):
        result.update(status='equivalent', reason='键级 / 电荷位置差异经判断为共振等价。')
    else:
        result.update(status='not_equivalent', reason='双向枚举未找到对应的编号键级与形式电荷。')
    return result


def stereo_key(mol, chem):
    return chem.MolToSmiles(chem.RemoveHs(mol), isomericSmiles=True)


def heavy_molecule(mol, chem):
    result = chem.RemoveAllHs(mol)
    if not result.GetNumAtoms():
        raise ValueError("Heavy-atom RMSD requires at least one heavy atom")
    return result


def atom_indices(mol, hydrogens):
    """Select original atom indices; polar H is bonded to N, O, S or P."""
    if hydrogens not in {"heavy", "polar", "all"}:
        raise ValueError("Unknown hydrogen mode: expected heavy, polar or all")
    return tuple(atom.GetIdx() for atom in mol.GetAtoms()
                 if atom.GetAtomicNum() != 1 or hydrogens == "all" or
                 (hydrogens == "polar" and any(neighbor.GetAtomicNum() in {7, 8, 15, 16}
                                               for neighbor in atom.GetNeighbors())))


def rms_molecule(mol, chem, hydrogens):
    """Filter a comparison copy only; never reorder or change the input/output atoms."""
    indices = set(atom_indices(mol, hydrogens))
    if not indices:
        raise ValueError("RMSD requires at least one selected atom")
    # Retain original order in this temporary projection. The original molecule
    # and Frame remain untouched, including every hydrogen and its coordinates.
    result = chem.RWMol(mol)
    for index in reversed(range(mol.GetNumAtoms())):
        if index not in indices:
            result.RemoveAtom(index)
    return result.GetMol()


def best_rms(probe, reference, chem, align, mirror=False):
    # GetBestRMS modifies probe coordinates: copy to preserve output geometries.
    copy = chem.Mol(probe)
    if mirror:
        conformer = copy.GetConformer()
        for index in range(copy.GetNumAtoms()):
            point = conformer.GetAtomPosition(index)
            conformer.SetAtomPosition(index, (-point.x, -point.y, -point.z))
    return float(align.GetBestRMS(copy, reference))


def load_frames(inputs, energy_file=None, energy_unit=None):
    """Read XYZs or Attempt directories; facts energies are SCF Hartree.

    External tables contain one energy per line or 1-based index + energy.
    Two-column crest.energies from conformer screening defaults to relative
    kcal/mol; one-column CREST singlepoint energies and other tables default
    to Hartree. --energy-unit overrides either default.
    """
    frames = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            path /= "final.xyz"
        group = read_xyz(path)
        facts_path = path.with_name("facts.json")
        if not energy_file and facts_path.exists():
            if len(group) != 1:
                raise ValueError("An Attempt facts.json must describe exactly one XYZ frame")
            facts = json.loads(facts_path.read_text())
            energies = facts.get("energies") or {}
            value = energies.get("scf")
            if value is None:
                value = facts.get("total_energy")
            if value is None:
                raise ValueError("facts.json has no SCF or total energy in Hartree")
            group = [replace(group[0], energy=finite_number(value), energy_unit="hartree")]
        frames.extend(group)
    if energy_file:
        rows = [line.split() for line in Path(energy_file).read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        if len(rows) != len(frames):
            raise ValueError("Energy table and XYZ frame counts differ")
        if len({len(row) for row in rows}) != 1:
            raise ValueError("Energy table rows must have a consistent column count")
        unit = energy_unit or ("kcal/mol" if Path(energy_file).name == "crest.energies"
                               and len(rows[0]) == 2 else "hartree")
        for index, row in enumerate(rows):
            if len(row) not in (1, 2) or (len(row) == 2 and row[0] != str(index + 1)):
                raise ValueError("Energy table requires ordered 1-based indices and one energy")
            frames[index] = replace(frames[index], energy=finite_number(row[-1]), energy_unit=unit)
    elif energy_unit:
        frames = [replace(frame, energy_unit=energy_unit) for frame in frames]
    if any(frame.energy is None for frame in frames):
        raise ValueError("Missing energy: provide XYZ energy comments, facts.json or --energies")
    if len({frame.energy_unit for frame in frames}) != 1:
        raise ValueError("Cannot mix absolute Hartree and relative kcal/mol energies")
    return frames


def relative_energies(frames, minimum):
    factor = HARTREE_TO_KCAL if frames[0].energy_unit == "hartree" else 1.0
    return [(frame.energy - minimum) * factor for frame in frames]


def record(frame, index, relative):
    return {"index": index + 1, "energy": frame.energy, "energy_unit": frame.energy_unit,
            "relative_energy_kcal": relative, "source": frame.source,
            "source_frame": frame.source_frame}


def output_stem(directory, prefix):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}"


def write_json(path, result):
    with Path(path).open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")


def nonnegative(value):
    number = finite_number(value)
    if number < 0:
        raise ValueError("Thresholds must be nonnegative")
    return number


def periodic_difference(left, right):
    """Smallest unsigned angular difference in degrees, in [0, 180].

    Algorithm adapted from archive/skills/auto-g16-conformer-search/scripts/
    conformer_core.py; no legacy command or contract is used.
    """
    return abs((left - right + 180.0) % 360.0 - 180.0)


def dihedral(coordinates, atoms):
    """Signed A-B-C-D torsion in [-180, 180), using 1-based XYZ indices.

    Reject degenerate planes instead of assigning collinear atoms a family.
    """
    a, b, c, d = (coordinates[i - 1] for i in atoms)

    def unit(vector):
        length = math.hypot(*vector)
        if length == 0:
            raise ValueError("undefined dihedral: coincident atoms")
        return tuple(x / length for x in vector)

    def dot(u, v):
        return sum(x * y for x, y in zip(u, v))

    axis = unit(tuple(z - y for y, z in zip(b, c)))
    left = unit(tuple(x - y for x, y in zip(a, b)))
    right = unit(tuple(w - z for z, w in zip(c, d)))
    v = tuple(x - dot(left, axis) * y for x, y in zip(left, axis))
    w = tuple(x - dot(right, axis) * y for x, y in zip(right, axis))
    if min(math.hypot(*v), math.hypot(*w)) < 1e-12:
        raise ValueError("undefined dihedral: collinear atoms")
    cross = (axis[1] * v[2] - axis[2] * v[1],
             axis[2] * v[0] - axis[0] * v[2],
             axis[0] * v[1] - axis[1] * v[0])
    return (math.degrees(math.atan2(dot(cross, w), dot(v, w))) + 180) % 360 - 180


def dihedral_bin(angle, boundaries):
    """1-based half-open bins; last bin wraps from last to first boundary.

    Boundaries are validated by the caller, ascending and unique modulo 360.
    An exact boundary belongs to the bin starting at that boundary.
    """
    offset = (angle - boundaries[0]) % 360
    for i, edge in enumerate(boundaries[1:], 1):
        if offset < edge - boundaries[0]:
            return i
    return len(boundaries)


def atom_distance(coordinates, atoms):
    """Euclidean distance in angstrom for a 1-based pair."""
    return math.dist(*(coordinates[i - 1] for i in atoms))


def contact_fingerprint(coordinates, atoms, cutoff):
    """Sorted unique 1-based pairs touching selected atoms and closer than cutoff.

    Includes bonded pairs and hydrogens; excludes self-pairs. No bond inference.
    """
    pairs = {tuple(sorted((i, j))) for i in atoms
             for j in range(1, len(coordinates) + 1) if i != j
             and atom_distance(coordinates, (i, j)) < cutoff}
    return [list(pair) for pair in sorted(pairs)]
