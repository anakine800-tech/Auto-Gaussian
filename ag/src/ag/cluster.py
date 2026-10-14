"""Greedy conformer selection with optional mirror degeneracy counting."""

from dataclasses import replace
import json
from pathlib import Path
import sys

from . import geometry as geo


def select(frames, records, charge, maximum, rmsd, mirror, chem, bonds, align, representative="lowest"):
    if representative not in {"lowest", "medoid"}:
        raise ValueError("Unknown representative method")
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
    selected, representatives, excluded, groups = [], [], [], []
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
                        groups[position].append(index)
                        merged = True
                        break
        if not merged:
            for position, distance in enumerate(direct):
                if distance <= rmsd:
                    representatives[position]["members"].append({**item, "reason": "rmsd", "rmsd": distance})
                    groups[position].append(index)
                    merged = True
                    break
        if merged:
            continue
        if len(selected) >= maximum:
            excluded.append({**item, "reason": "max_representatives"})
        else:
            selected.append(index)
            groups.append([index])
            representatives.append({**item, "degeneracy": 1,
                                    "members": [{**item, "reason": "representative"}]})
        # Continue after the cap so later mirror partners still contribute.
    if representative == "medoid":
        for position, group in enumerate(groups):
            sums = {i: 0.0 for i in group}
            for offset, i in enumerate(group):
                for j in group[offset + 1:]:
                    distance = geo.best_rms(molecules[i], molecules[j], chem, align)
                    if mirror and abs(relative[i] - relative[j]) < 0.05:
                        distance = min(distance, geo.best_rms(molecules[i], molecules[j], chem, align, mirror=True))
                    sums[i] += distance
                    sums[j] += distance
            chosen = min(group, key=lambda i: (sums[i], frames[i].energy, i))
            old = representatives[position]
            representatives[position] = {**records[chosen], "degeneracy": old["degeneracy"],
                "members": old["members"], "cluster_seed_index": records[selected[position]]["index"],
                "medoid_rmsd_sum": sums[chosen]}
            selected[position] = chosen
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
        source_merge = payload.get("energy_basis") == "per_source_not_comparable"
        frames = (geo.read_xyz(args.input.parent / payload["xyz_file"]) if source_merge else
                  geo.load_frames([args.input.parent / payload["xyz_file"]]))
        if source_merge and (args.representative == "lowest" or args.mirror):
            raise ValueError("Source energies are not comparable; use --representative medoid without --mirror")
        records = payload["kept"]
        # A stale/replaced XYZ would otherwise pair an energy with the wrong structure.
        if len(records) != len(frames) or any(
            row["xyz_frame"] != index + 1 or row["energy_unit"] != frame.energy_unit
            or (row["energy"] != frame.energy and (row["energy"] is None or frame.energy is None
                or abs(row["energy"] - frame.energy) > 1e-9))
            for index, (row, frame) in enumerate(zip(records, frames))
        ):
            raise ValueError("Dedup JSON and XYZ energies/frame ordering do not agree")
        # Zero is an internal sort key only, never a reported energy for mixed routes.
        working = [replace(f, energy=0.0, energy_unit="hartree") for f in frames] if source_merge else frames
        reps, excluded, selected = select(working, records, payload["charge"], args.maximum,
                                          args.rmsd, args.mirror, Chem, rdDetermineBonds, rdMolAlign,
                                          args.representative)
        if source_merge:
            selected = [frames[rep["xyz_frame"] - 1] for rep in reps]
        stem = geo.output_stem(args.out or args.input.parent, "cluster")
        for index, (rep, frame) in enumerate(zip(reps, selected), 1):
            path = stem.with_name(f"{stem.name}-c{index:03d}.xyz")
            geo.write_xyz(path, [frame])
            rep["xyz_file"] = path.name
        result = {"charge": payload["charge"], "rmsd_threshold": args.rmsd,
                  "representative_method": args.representative, "mirror": args.mirror, "max_representatives": args.maximum,
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
    parser.add_argument("--representative", choices=("lowest", "medoid"), default="lowest")
    parser.add_argument("--mirror", action="store_true")
    parser.add_argument("--out", type=Path, help="Defaults to the dedup output directory")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
