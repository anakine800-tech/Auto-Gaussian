"""Energy-window filtering and symmetry-aware heavy-atom deduplication."""

import json
from pathlib import Path
import sys

from . import geometry as geo


def deduplicate(frames, charge, rmsd, de, window, chem, bonds, align):
    rmsd, de, window = map(geo.nonnegative, (rmsd, de, window))
    molecules, rejected = {}, []
    first = geo.infer_molecule(frames[0], charge, chem, bonds)
    key = geo.graph_key(first, chem)
    stereo = geo.stereo_key(first, chem)
    for index, frame in enumerate(frames):
        try:
            mol = first if index == 0 else geo.infer_molecule(frame, charge, chem, bonds)
        except (ValueError, RuntimeError):
            rejected.append({**geo.record(frame, index, None), "reason": "bond_inference_failed"})
            continue
        if geo.graph_key(mol, chem) != key:
            rejected.append({**geo.record(frame, index, None), "reason": "graph_changed"})
        elif geo.stereo_key(mol, chem) != stereo:
            rejected.append({**geo.record(frame, index, None), "reason": "stereo_changed"})
        else:
            molecules[index] = geo.heavy_molecule(mol, chem)
    minimum = min(frames[index].energy for index in molecules)
    relative = geo.relative_energies(frames, minimum)
    kept = []
    for index in sorted(molecules, key=lambda i: (frames[i].energy, i)):
        item = geo.record(frames[index], index, relative[index])
        if relative[index] > window:
            rejected.append({**item, "reason": "energy_window"})
            continue
        duplicate = None
        for previous in kept:
            if abs(relative[index] - relative[previous]) < de:
                distance = geo.best_rms(molecules[index], molecules[previous], chem, align)
                if distance < rmsd:
                    duplicate = (previous, distance)
                    break
        if duplicate is None:
            kept.append(index)
        else:
            rejected.append({**item, "reason": "duplicate", "representative": duplicate[0] + 1,
                             "rmsd": duplicate[1]})
    records = [{**geo.record(frames[index], index, relative[index]), "xyz_frame": position + 1}
               for position, index in enumerate(kept)]
    return records, rejected, [frames[index] for index in kept]


def run(args):
    try:
        from rdkit import Chem
        from rdkit.Chem import rdDetermineBonds, rdMolAlign
    except ImportError:
        print("dedup requires RDKit in the selected Python environment", file=sys.stderr)
        return 2
    try:
        frames = geo.load_frames(args.inputs, args.energies, args.energy_unit)
        kept, rejected, selected = deduplicate(frames, args.charge, args.rmsd, args.de,
                                              args.window, Chem, rdDetermineBonds, rdMolAlign)
        stem = geo.output_stem(args.out, "dedup")
        xyz_path, json_path = stem.with_suffix(".xyz"), stem.with_suffix(".json")
        result = {"charge": args.charge, "rmsd_threshold": args.rmsd, "de_kcal": args.de,
                  "window_kcal": args.window, "xyz_file": xyz_path.name,
                  "kept": kept, "excluded": rejected}
        geo.write_xyz(xyz_path, selected)
        geo.write_json(json_path, result)
        if args.json:
            print(json.dumps({"output": str(json_path), **result}, allow_nan=False))
        else:
            print(f"Kept {len(kept)} / {len(frames)}; excluded {len(rejected)}. {json_path}")
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"dedup: {exc}", file=sys.stderr)
        return 1


def register(subparsers):
    parser = subparsers.add_parser("dedup", description=__doc__)
    parser.add_argument("inputs", nargs="+", help="XYZ files or Attempt directories containing final.xyz")
    parser.add_argument("--charge", type=int, required=True)
    parser.add_argument("--energies", help="One energy per row, optionally preceded by a 1-based index")
    parser.add_argument("--energy-unit", choices=("hartree", "kcal/mol"),
                        help="Override units; two-column crest.energies defaults to kcal/mol, otherwise Hartree")
    parser.add_argument("--rmsd", type=float, default=0.125, help="Heavy-atom RMSD in angstrom")
    parser.add_argument("--de", type=float, default=0.05, help="Duplicate energy tolerance in kcal/mol")
    parser.add_argument("--window", type=float, default=3.0, help="Energy window in kcal/mol")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory: point to the study's analyses/ outside the repository")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
