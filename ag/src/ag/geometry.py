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


def stereo_key(mol, chem):
    return chem.MolToSmiles(chem.RemoveHs(mol), isomericSmiles=True)


def heavy_molecule(mol, chem):
    result = chem.RemoveAllHs(mol)
    if not result.GetNumAtoms():
        raise ValueError("Heavy-atom RMSD requires at least one heavy atom")
    return result


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
