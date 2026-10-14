"""Energy-window filtering and symmetry-aware heavy-atom deduplication."""

import hashlib
import json
import re
from pathlib import Path
import sys

from . import geometry as geo


def deduplicate(frames, charge, rmsd, de, window, chem, bonds, align, routes=None):
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
    # Route energies can be different Hamiltonians/units; never rank them together.
    relative = ([None] * len(frames) if routes is not None else
                geo.relative_energies(frames, min(frames[i].energy for i in molecules)))
    kept = []
    order = list(molecules) if routes is not None else sorted(molecules, key=lambda i: (frames[i].energy, i))
    for index in order:
        item = geo.record(frames[index], index, relative[index])
        if routes is None and relative[index] > window:
            rejected.append({**item, "reason": "energy_window"})
            continue
        duplicate = None
        for previous in kept:
            if routes is not None or abs(relative[index] - relative[previous]) < de:
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
    if routes is not None:
        for record in records:
            members = [record["index"]] + [r["index"] for r in rejected
                       if r.get("representative") == record["index"]]
            record["sources"] = sorted({routes[i - 1] for i in members})
            record["members"] = [{**geo.record(frames[i - 1], i - 1, None),
                                  "route": routes[i - 1]} for i in members]
        for record in rejected:
            record["sources"] = [routes[record["index"] - 1]]
    return records, rejected, [frames[index] for index in kept]


def run(args):
    try:
        from rdkit import Chem
        from rdkit.Chem import rdDetermineBonds, rdMolAlign
    except ImportError:
        print("dedup requires RDKit in the selected Python environment", file=sys.stderr)
        return 2
    try:
        routes = None
        if args.source:
            if args.inputs or args.energies or args.energy_unit or args.de is not None or args.window is not None:
                raise ValueError("--source is geometry-only; do not combine with positional inputs or energy filters")
            frames, routes = [], []
            for value in args.source:
                name, separator, path = value.partition("=")
                if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name) or not path:
                    raise ValueError("--source requires ROUTE=XYZ")
                group = geo.read_xyz(path)
                frames.extend(group)
                routes.extend([name] * len(group))
        else:
            if not args.inputs:
                raise ValueError("Provide inputs or --source ROUTE=XYZ")
            frames = geo.load_frames(args.inputs, args.energies, args.energy_unit)
        de = 0.05 if args.de is None else args.de
        window = 3.0 if args.window is None else args.window
        kept, rejected, selected = deduplicate(frames, args.charge, args.rmsd, de,
                                              window, Chem, rdDetermineBonds, rdMolAlign, routes)
        stem = geo.output_stem(args.out, "dedup")
        xyz_path, json_path = stem.with_suffix(".xyz"), stem.with_suffix(".json")
        result = {"charge": args.charge, "rmsd_threshold": args.rmsd, "de_kcal": None if routes is not None else de,
                  "window_kcal": None if routes is not None else window, "xyz_file": xyz_path.name,
                  "kept": kept, "excluded": rejected}
        if routes is not None:
            result.update(energy_basis="per_source_not_comparable", routes=sorted(set(routes)))
        geo.write_xyz(xyz_path, selected)
        if routes is not None:
            # Replaced coordinates must not inherit provenance from a stale JSON sidecar.
            result["xyz_sha256"] = hashlib.sha256(xyz_path.read_bytes()).hexdigest()
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
    parser.add_argument("inputs", nargs="*", help="XYZ files or Attempt directories containing final.xyz")
    parser.add_argument("--source", action="append", default=[], metavar="ROUTE=XYZ",
                        help="Repeat for geometry-only merging; retains all route labels and source energies")
    parser.add_argument("--charge", type=int, required=True)
    parser.add_argument("--energies", help="One energy per row, optionally preceded by a 1-based index")
    parser.add_argument("--energy-unit", choices=("hartree", "kcal/mol"),
                        help="Override units; two-column crest.energies defaults to kcal/mol, otherwise Hartree")
    parser.add_argument("--rmsd", type=float, default=0.125, help="Heavy-atom RMSD in angstrom")
    parser.add_argument("--de", type=float, help="Duplicate energy tolerance in kcal/mol (default 0.05; positional inputs only)")
    parser.add_argument("--window", type=float, help="Energy window in kcal/mol (default 3; positional inputs only)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory: point to the study's analyses/ outside the repository")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
