#!/usr/bin/env python3
"""Prepare and audit one Cartesian Gaussian input for GaussView preview."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

PIPELINE = Path.home() / ".codex/skills/auto-g16-chemdraw-pipeline/scripts"
INSPECT = PIPELINE / "inspect_chemdraw.py"
MAKE = PIPELINE / "make_gaussian_input.py"
AUDIT = PIPELINE / "audit_cartesian_input.py"


def run_json(command: list[str]) -> dict:
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise SystemExit(detail) from None
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="CDX/CDXML/MOL/SDF path or unambiguous SMILES")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--project", default=None)
    parser.add_argument("--route", default="#p b3lyp/6-31g(d)")
    parser.add_argument("--charge", type=int)
    parser.add_argument("--multiplicity", type=int)
    parser.add_argument("--mem", default="1200MB")
    parser.add_argument("--nproc", type=int, default=3)
    parser.add_argument("--allow-ambiguous-stereo", action="store_true")
    args = parser.parse_args()

    for dependency in (MAKE, AUDIT):
        if not dependency.exists():
            raise SystemExit(f"Missing dependency: {dependency}")

    source_path = Path(args.source).expanduser()
    source_exists = source_path.exists()
    out = Path(args.output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    project = args.project or (source_path.stem if source_exists else "structure")
    project = "".join(c if c.isalnum() or c in "-_" else "_" for c in project).strip("_")
    if not project:
        raise SystemExit("Project name becomes empty after sanitization")

    conversion_source = args.source
    import_manifest = None
    preview = None
    if source_exists and source_path.suffix.lower() in {".cdx", ".cdxml"}:
        if not INSPECT.exists():
            raise SystemExit(f"Missing dependency: {INSPECT}")
        review = out / "review"
        subprocess.run([sys.executable, str(INSPECT), str(source_path.resolve()), str(review)], check=True)
        import_manifest_path = review / f"{source_path.stem}_imported.json"
        import_manifest = json.loads(import_manifest_path.read_text(encoding="utf-8"))
        preview = review / f"{source_path.stem}_imported.png"
        # Convert directly from CDX/CDXML.  The shared parser preserves explicit
        # wedge hydrogens and avoids a potentially lossy MOL/SDF round trip.
        conversion_source = str(source_path.resolve())
        if import_manifest.get("warnings") and not args.allow_ambiguous_stereo:
            raise SystemExit("ChemDraw import has warnings; review them or use --allow-ambiguous-stereo for preview only")

    gjf = out / f"{project}_cartesian.gjf"
    command = [
        sys.executable, str(MAKE), conversion_source,
        "--output", str(gjf), "--route", args.route,
        "--mem", args.mem, "--nproc", str(args.nproc),
        "--title", f"{project} GaussView preview",
    ]
    if args.charge is not None:
        command += ["--charge", str(args.charge)]
    if args.multiplicity is not None:
        command += ["--multiplicity", str(args.multiplicity)]
    if args.allow_ambiguous_stereo:
        command.append("--allow-ambiguous-stereo")
    conversion = run_json(command)
    audit = run_json([sys.executable, str(AUDIT), str(gjf)])
    manifest_path = Path(conversion["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if audit["atom_count"] != manifest["atom_count_in_gaussian_input"]:
        raise SystemExit("Audit atom count does not match conversion manifest")
    if audit["charge_multiplicity"] != {
        "charge": manifest["charge_used"], "multiplicity": manifest["multiplicity_used"]
    }:
        raise SystemExit("Audit charge/multiplicity does not match conversion manifest")

    source_hash = sha256(source_path.resolve()) if source_exists else None
    report = {
        "schema": "gaussian-view-rt-win/1",
        "project": project,
        "source": str(source_path.resolve()) if source_exists else args.source,
        "source_sha256": source_hash,
        "gaussian_input": str(gjf),
        "gaussian_input_sha256": sha256(gjf),
        "xyz": conversion["xyz"],
        "manifest": str(manifest_path),
        "preview": str(preview) if preview else None,
        "identity": {
            "smiles": manifest["canonical_isomeric_smiles"],
            "formula": manifest["formula"],
            "molecular_weight": manifest["molecular_weight"],
        },
        "charge": manifest["charge_used"],
        "multiplicity": manifest["multiplicity_used"],
        "chiral_centers": manifest["chiral_centers"],
        "component_count": manifest["component_count"],
        "geometry": manifest["geometry"],
        "route": manifest["route"],
        "audit": audit,
        "warnings": (import_manifest or {}).get("warnings", []) + manifest.get("warnings", []),
        "review_artifact_warnings": (import_manifest or {}).get("review_artifact_warnings", []),
        "calculation_started": False,
    }
    report_path = out / f"{project}_preview_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
