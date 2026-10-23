"""Energy-window filtering and symmetry-aware conformer deduplication."""

import hashlib
import json
import re
from pathlib import Path
import sys

from . import geometry as geo


def _atoms(value, count=None):
    fields = value.split(",")
    if (any(not re.fullmatch(r"[1-9][0-9]*", field.strip()) for field in fields)
            or (count is not None and len(fields) != count)):
        raise ValueError(f"expected {count or 'one or more'} positive 1-based atom indices")
    atoms = [int(field) for field in fields]
    if len(set(atoms)) != len(atoms):
        raise ValueError("atom indices must not repeat")
    return atoms


def descriptor_definitions(dihedral_bins=(), report_distance=(), contact_atoms=(), contact_cutoff=None):
    """Parse opt-in descriptors; None preserves the legacy output exactly."""
    if not (dihedral_bins or report_distance or contact_atoms or contact_cutoff is not None):
        return None
    result = {"dihedral_bins": [], "distance_pairs": [], "contact_atoms": [],
              "contact_cutoff": 3.0 if contact_cutoff is None else geo.nonnegative(contact_cutoff)}
    if contact_cutoff is not None and not contact_atoms:
        raise ValueError("--contact-cutoff requires --contact-atoms")
    for value in dihedral_bins:
        try:
            indices, spec = value.split(":")
            angles, named, labels = spec.partition("@")
            atoms = _atoms(indices, 4)
            boundaries = [geo.finite_number(x) for x in angles.split(",")]
            if (any(x < -180 or x > 180 for x in boundaries)
                    or any(a >= b for a, b in zip(boundaries, boundaries[1:]))
                    or boundaries[-1] - boundaries[0] >= 360):
                raise ValueError("boundaries must increase in [-180, 180] and be distinct modulo 360")
            names = ([x.strip() for x in labels.split(",")] if named else
                     [f"bin{i + 1}" for i in range(len(boundaries))])
            if (len(names) != len(boundaries) or any(not x or "@" in x for x in names)
                    or len(set(names)) != len(names)):
                raise ValueError("provide one nonempty, unique name per bin")
            result["dihedral_bins"].append({"atoms": atoms, "boundaries": boundaries, "names": names})
        except ValueError as exc:
            raise ValueError(f"--dihedral-bins {value!r}: {exc}") from exc
    for value in report_distance:
        try:
            result["distance_pairs"].append(_atoms(value, 2))
        except ValueError as exc:
            raise ValueError(f"--report-distance {value!r}: {exc}") from exc
    selected = set()
    for value in contact_atoms:
        try:
            selected.update(_atoms(value))
        except ValueError as exc:
            raise ValueError(f"--contact-atoms {value!r}: {exc}") from exc
    result["contact_atoms"] = sorted(selected)
    return result


def frame_descriptors(frame, definitions, index):
    """Validate every requested index before inference or energy filtering."""
    def check(atoms, label):
        if any(i > len(frame.coordinates) for i in atoms):
            raise ValueError(f"frame {index + 1}, {label} {atoms}: atom index out of range")

    angles, bins = [], []
    near_boundary = False
    for definition in definitions["dihedral_bins"]:
        atoms, boundaries = definition["atoms"], definition["boundaries"]
        check(atoms, "dihedral")
        try:
            angle = geo.dihedral(frame.coordinates, atoms)
        except ValueError as exc:
            raise ValueError(f"frame {index + 1}, dihedral {atoms}: {exc}") from exc
        angles.append(angle)
        bins.append(geo.dihedral_bin(angle, boundaries))
        near_boundary |= any(geo.periodic_difference(angle, edge) < 5 for edge in boundaries)
    distances = []
    for pair in definitions["distance_pairs"]:
        check(pair, "distance")
        distances.append(geo.atom_distance(frame.coordinates, pair))
    check(definitions["contact_atoms"], "contact atoms")
    return {"dihedrals": angles, "bins": bins, "near_boundary": near_boundary,
            "distances": distances,
            "contacts": geo.contact_fingerprint(frame.coordinates, definitions["contact_atoms"],
                                                definitions["contact_cutoff"])}


def deduplicate(frames, charge, rmsd, de, window, chem, bonds, align, routes=None, representative=None,
                hydrogens="polar", descriptors=None, kept_by_bins=None, *, mirror="off", report=None):
    if mirror not in {"off", "report"}:
        raise ValueError("--mirror must be off or report; mirror merging is not supported")
    rmsd, de, window = map(geo.nonnegative, (rmsd, de, window))
    local = ([frame_descriptors(frame, descriptors, i) for i, frame in enumerate(frames)]
             if descriptors is not None else [{} for frame in frames])
    molecules, heavy, rejected = {}, {}, []
    chiral = False
    first = geo.infer_molecule(frames[0], charge, chem, bonds)
    key = geo.graph_key(first, chem)
    stereo = geo.stereo_key(first, chem)
    for index, frame in enumerate(frames):
        try:
            mol = first if index == 0 else geo.infer_molecule(frame, charge, chem, bonds)
        except (ValueError, RuntimeError):
            rejected.append({**geo.record(frame, index, None), **local[index], "reason": "bond_inference_failed"})
            continue
        if geo.graph_key(mol, chem) != key:
            rejected.append({**geo.record(frame, index, None), **local[index], "reason": "graph_changed"})
        elif geo.stereo_key(mol, chem) != stereo:
            rejected.append({**geo.record(frame, index, None), **local[index], "reason": "stereo_changed"})
        else:
            molecules[index] = geo.rms_molecule(mol, chem, hydrogens)
            heavy[index] = geo.heavy_molecule(mol, chem)
            if mirror == "report":
                chiral |= bool(chem.FindMolChiralCenters(mol, includeUnassigned=False,
                                                       useLegacyImplementation=False))
    # Only an explicit lowest request asserts a shared energy method across routes.
    comparable = routes is None or representative == "lowest"
    if routes is not None and comparable and any(f.energy is None or f.energy_unit != "hartree" for f in frames):
        raise ValueError("lowest source merging requires finite Hartree energies from the same method")
    # Route energies can otherwise be different Hamiltonians/units.
    relative = ([None] * len(frames) if not comparable else
                geo.relative_energies(frames, min(frames[i].energy for i in molecules)))
    comparisons = {}

    def compare(index, previous):
        pair = (index, previous)
        if pair not in comparisons:
            comparisons[pair] = geo.best_rms(molecules[index], molecules[previous], chem, align,
                                              return_mapping=True)
        return comparisons[pair]

    def pair_record(index, previous, distance, mapping):
        return {"indices": [previous + 1, index + 1], "rmsd": distance, "mapping": mapping,
                "delta_energy_kcal": abs(relative[index] - relative[previous]) if comparable else None}

    kept = []
    order = list(molecules) if not comparable else sorted(molecules, key=lambda i: (frames[i].energy, i))
    for index in order:
        item = {**geo.record(frames[index], index, relative[index]), **local[index]}
        if routes is None and relative[index] > window:
            rejected.append({**item, "reason": "energy_window"})
            continue
        duplicate = None
        for previous in kept:
            if descriptors is not None and local[index]["bins"] != local[previous]["bins"]:
                continue
            if not comparable or abs(relative[index] - relative[previous]) < de:
                distance, mapping = compare(index, previous)
                if distance < rmsd:
                    heavy_distance = (distance if hydrogens == "heavy" else
                                      geo.best_rms(heavy[index], heavy[previous], chem, align))
                    duplicate = (previous, distance, heavy_distance, mapping)
                    break
        if duplicate is None:
            if comparable and relative[index] > window:
                rejected.append({**item, "reason": "energy_window"})
            else:
                kept.append(index)
        else:
            if descriptors is not None:
                item["max_periodic_dihedral_difference"] = max(
                    (geo.periodic_difference(a, b) for a, b in
                     zip(local[index]["dihedrals"], local[duplicate[0]]["dihedrals"])), default=None)
            rejected.append({**item, "reason": "duplicate", "representative": duplicate[0] + 1,
                             "rmsd": duplicate[1], "heavy_rmsd": duplicate[2], "mapping": duplicate[3]})
    records = [{**geo.record(frames[index], index, relative[index]), **local[index], "xyz_frame": position + 1}
               for position, index in enumerate(kept)]
    if report is not None:
        report.update(algorithm={
            "name": "greedy_first_match", "order_dependent": True,
            "ordering": "energy_ascending_then_input_order" if comparable else "input_order",
            "description": ("Sort by increasing energy, breaking ties by input order. " if comparable else
                            "Source energies are not comparable; process in input order. ") +
                           "Compare only with retained representatives; merge into the first satisfying "
                           "the RMSD, energy (when comparable) and optional bin criteria. "
                           "The result depends on processing order; this is not transitive clustering."},
            boundary_pairs=[])
        for row in rejected:
            if row["reason"] == "duplicate" and row["rmsd"] > rmsd / 2:
                report["boundary_pairs"].append({"kind": "merged", **pair_record(
                    row["index"] - 1, row["representative"] - 1, row["rmsd"], row["mapping"])})
        if mirror == "report":
            report.update(mirror="report", mirror_pairs=[], mirror_note=(
                "手性体系，镜像对不是同一构象，仅供识别对映构象。" if chiral else
                "镜像 RMSD 仅供报告，不合并代表；非手性镜像简并由 ag cluster --mirror 处理。") +
                "仅比较已保留的代表；graph_changed / stereo_changed 排除规则不变。")
    if report is not None or (descriptors is not None and kept_by_bins is not None):
        # Diagnostics inspect final representatives regardless of energy/bins,
        # and never alter selection, source provenance or degeneracy.
        for position, index in enumerate(kept):
            for previous in kept[:position]:
                distance, mapping = compare(index, previous)
                if (descriptors is not None and kept_by_bins is not None and
                        local[index]["bins"] != local[previous]["bins"] and distance < rmsd):
                    kept_by_bins.append({"indices": [previous + 1, index + 1], "rmsd": distance,
                                         "bins": [local[previous]["bins"], local[index]["bins"]]})
                if report is not None:
                    pair = pair_record(index, previous, distance, mapping)
                    if distance < 2 * rmsd:
                        report["boundary_pairs"].append({"kind": "representatives", **pair})
                    if mirror == "report":
                        mirrored, mirror_mapping = geo.best_rms(
                            molecules[index], molecules[previous], chem, align, mirror=True,
                            return_mapping=True)
                        if mirrored < rmsd:
                            report["mirror_pairs"].append({**pair, "mirror_rmsd": mirrored,
                                                           "mirror_mapping": mirror_mapping})
    if routes is not None:
        duplicates = {r["index"]: r for r in rejected if r.get("reason") == "duplicate"}
        for record in records:
            members = [record["index"]] + [r["index"] for r in rejected
                       if r.get("representative") == record["index"]]
            record["sources"] = sorted({routes[i - 1] for i in members})
            record["members"] = [{**geo.record(frames[i - 1], i - 1, relative[i - 1]), **local[i - 1],
                                  **({"max_periodic_dihedral_difference":
                                      duplicates[i]["max_periodic_dihedral_difference"]}
                                     if descriptors is not None and i in duplicates else {}),
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
            if args.inputs or args.energies or args.energy_unit:
                raise ValueError("--source cannot combine with positional inputs, --energies or --energy-unit")
            if args.representative != "lowest" and (args.de is not None or args.window is not None):
                raise ValueError("--source is geometry-only without --representative lowest; do not use --de or --window")
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
        descriptors = descriptor_definitions(args.dihedral_bins, args.report_distance,
                                             args.contact_atoms, args.contact_cutoff)
        kept_by_bins = []
        report = {}
        kept, rejected, selected = deduplicate(frames, args.charge, args.rmsd, de,
                                              window, Chem, rdDetermineBonds, rdMolAlign, routes, args.representative,
                                              args.hydrogens, descriptors, kept_by_bins,
                                              mirror=args.mirror, report=report)
        stem = geo.output_stem(args.out, "dedup")
        xyz_path, json_path = stem.with_suffix(".xyz"), stem.with_suffix(".json")
        result = {"charge": args.charge, "rmsd_threshold": args.rmsd, "hydrogens": args.hydrogens,
                  "de_kcal": None if routes is not None and args.representative != "lowest" else de,
                  "window_kcal": None if routes is not None and args.representative != "lowest" else window, "xyz_file": xyz_path.name,
                  "kept": kept, "excluded": rejected, **report}
        if descriptors is not None:
            result.update(descriptors=descriptors, kept_by_bins=kept_by_bins)
        if routes is not None:
            result.update(energy_basis=("shared_hartree" if args.representative == "lowest" else "per_source_not_comparable"),
                          representative_method=args.representative or "first", routes=sorted(set(routes)))
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
                        help="Merge route-labelled XYZs geometrically; lowest opts in to comparable-energy ranking and --de")
    parser.add_argument("--representative", choices=("lowest",),
                        help="With --source, assert same-method Hartree energies and select the lowest-energy member")
    parser.add_argument("--charge", type=int, required=True)
    parser.add_argument("--energies", help="One energy per row, optionally preceded by a 1-based index")
    parser.add_argument("--energy-unit", choices=("hartree", "kcal/mol"),
                        help="Override units; two-column crest.energies defaults to kcal/mol, otherwise Hartree")
    parser.add_argument("--hydrogens", choices=("heavy", "polar", "all"), default="polar",
                        help="RMSD atoms: heavy only, plus N/O/S/P-bound H (default polar), or all atoms")
    parser.add_argument("--rmsd", type=float, default=0.125, help="Selected-atom RMSD in angstrom")
    parser.add_argument("--mirror", choices=("off", "report"), default="off",
                        help="Report mirror RMSD between retained representatives without merging (default off)")
    parser.add_argument("--de", type=float, help="Duplicate energy tolerance in kcal/mol (default 0.05; positional inputs or --source --representative lowest)")
    parser.add_argument("--window", type=float, help="Energy window in kcal/mol (default 3; positional inputs or --source --representative lowest)")
    parser.add_argument("--dihedral-bins", action="append", default=[], metavar="A,B,C,D:b1,b2[@names]",
                        help="Periodic boundaries in degrees; different bin tuples never merge (repeatable)")
    parser.add_argument("--report-distance", action="append", default=[], metavar="I,J",
                        help="Report a 1-based XYZ atom-pair distance without changing merging (repeatable)")
    parser.add_argument("--contact-atoms", action="append", default=[], metavar="I,J,K",
                        help="Report contacts touching these 1-based atoms; repeated sets are united")
    parser.add_argument("--contact-cutoff", type=float, metavar="ANGSTROM",
                        help="Strict contact distance cutoff (default 3.0; requires --contact-atoms)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output directory: point to the study's analyses/ outside the repository")
    parser.add_argument("--json", action="store_true")
    parser.set_defaults(func=run)
