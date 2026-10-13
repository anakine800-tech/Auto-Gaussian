"""Greedy conformer selection with optional mirror degeneracy counting."""

import json
from pathlib import Path
import sys

from . import geometry as geo


def select(frames, records, charge, maximum, rmsd, mirror, chem, bonds, align):
    rmsd = geo.nonnegative(rmsd)
    if maximum < 1:
        raise ValueError("--max must be positive")
    if not frames or len(frames) != len(records):
        raise ValueError("Dedup records and XYZ frames differ or are empty")
    molecules = [geo.infer_molecule(frame, charge, chem, bonds) for frame in frames]
    if len({geo.graph_key(mol, chem) for mol in molecules}) != 1:
        raise ValueError("Dedup XYZ contains different molecular graphs")
    # An enantiomer of a molecule with a specified stereocenter is not a
    # degenerate conformer of the same stereoisomer.
    if mirror and any(chem.FindMolChiralCenters(mol, includeUnassigned=False,
                                               useLegacyImplementation=False)
                      for mol in molecules):
        raise ValueError("镜像简并只适用于非手性分子 (--mirror found a specified chiral center)")
    molecules = [geo.heavy_molecule(mol, chem) for mol in molecules]
    minimum = min(frame.energy for frame in frames)
    relative = geo.relative_energies(frames, minimum)
    selected, representatives, excluded = [], [], []
    for index in sorted(range(len(frames)), key=lambda i: (frames[i].energy, i)):
        item = dict(records[index])
        merged = False
        # Gauche partners also fit the default direct threshold (about 0.46 A).
        # Prefer a better mirror fit so their degeneracy is not lost to that merge.
        direct = [geo.best_rms(molecules[index], molecules[previous], chem, align)
                  for previous in selected]
        if mirror:
            for position, previous in enumerate(selected):
                if abs(relative[index] - relative[previous]) < 0.05:
                    distance = geo.best_rms(molecules[index], molecules[previous], chem, align, mirror=True)
                    if distance < rmsd and distance + 1e-7 < direct[position]:
                        representatives[position]["degeneracy"] += 1
                        representatives[position]["members"].append({**item, "reason": "mirror", "rmsd": distance})
                        merged = True
                        break
        if not merged:
            for position, distance in enumerate(direct):
                if distance <= rmsd:
                    representatives[position]["members"].append({**item, "reason": "rmsd", "rmsd": distance})
                    merged = True
                    break
        if merged:
            continue
        if len(selected) >= maximum:
            excluded.append({**item, "reason": "max_representatives"})
        else:
            selected.append(index)
            representatives.append({**item, "degeneracy": 1,
                                    "members": [{**item, "reason": "representative"}]})
        # Continue after the cap so later mirror partners still contribute.
    return representatives, excluded, [frames[index] for index in selected]


def run(args):
    try:
        from rdkit import Chem
        from rdkit.Chem import rdDetermineBonds, rdMolAlign
    except ImportError:
        print("cluster requires RDKit in the selected Python environment", file=sys.stderr)
        return 2
    try:
        payload = json.loads(args.input.read_text())
        frames = geo.load_frames([args.input.parent / payload["xyz_file"]])
        records = payload["kept"]
        # A stale/replaced XYZ would otherwise pair an energy with the wrong structure.
        if len(records) != len(frames) or any(
            row["xyz_frame"] != index + 1 or row["energy_unit"] != frame.energy_unit
            or abs(row["energy"] - frame.energy) > 1e-9
            for index, (row, frame) in enumerate(zip(records, frames))
        ):
            raise ValueError("Dedup JSON and XYZ energies/frame ordering do not agree")
        reps, excluded, selected = select(frames, records, payload["charge"], args.maximum,
                                          args.rmsd, args.mirror, Chem, rdDetermineBonds, rdMolAlign)
        stem = geo.output_stem(args.out or args.input.parent, "cluster")
        for index, (rep, frame) in enumerate(zip(reps, selected), 1):
            path = stem.with_name(f"{stem.name}-c{index:03d}.xyz")
            geo.write_xyz(path, [frame])
            rep["xyz_file"] = path.name
        result = {"charge": payload["charge"], "rmsd_threshold": args.rmsd,
                  "mirror": args.mirror, "max_representatives": args.maximum,
                  "representatives": reps, "excluded": excluded}
        output = stem.with_suffix(".json")
        geo.write_json(output, result)
        print(json.dumps({"output": str(output), **result}, allow_nan=False) if args.json
              else f"Selected {len(reps)} representatives. {output}")
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"cluster: {exc}", file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser("cluster", description=__doc__)
    parser.add_argument("input", type=Path, help="dedup-*.json")
    parser.add_argument("--max", dest="maximum", type=int, default=20)
    parser.add_argument("--rmsd", type=float, default=0.5, help="Heavy-atom RMSD in angstrom")
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--out", type=Path, help="Defaults to the dedup output directory")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
