#!/usr/bin/env python3
"""Reuse one SSH master to verify, transfer, and visibly open a structure in GaussView."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

HOST = "100.76.152.81"
USER = "10261"
TARGET = f"{USER}@{HOST}"
SOCKET = "/tmp/codex-windows-gaussview.sock"
REMOTE_ROOT = r"C:\Users\10261\Desktop\GaussianProjects"
GVIEW = r"D:\gs\g16\G16W\gview.exe"
OPEN_SUFFIXES = {".gjf", ".com", ".mol", ".sdf", ".xyz"}
DIRECT_OPEN_SUFFIXES = {".gjf", ".com", ".mol", ".sdf"}
VISUAL_PREVIEW_SCHEMA = "gaussview-visual-preview/1"
VISUAL_BOND_FACTOR = 1.25
PROBE_SCRIPT = Path(__file__).with_name("gaussview_load_probe.ps1")

# Covalent radii in angstrom for the organic-chemistry scope of this Skill.
# Unsupported elements stop rather than silently receiving guessed topology.
COVALENT_RADII = {
    "H": 0.31,
    "B": 0.84,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "Si": 1.11,
    "P": 1.07,
    "S": 1.05,
    "Cl": 1.02,
    "Br": 1.20,
    "I": 1.39,
}
MAX_VISUAL_NEIGHBORS = {
    "H": 1,
    "B": 4,
    "C": 4,
    "N": 4,
    "O": 3,
    "F": 1,
    "Si": 6,
    "P": 6,
    "S": 6,
    "Cl": 1,
    "Br": 1,
    "I": 1,
}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    # Windows OpenSSH may emit localized OEM/GBK bytes. ASCII tokens used for
    # control checks remain intact; replacement avoids locale-dependent crashes.
    return subprocess.run(
        command, check=check, text=True, encoding="utf-8", errors="replace", capture_output=True
    )


def master_ready() -> bool:
    return run(["ssh", "-S", SOCKET, "-O", "check", TARGET], check=False).returncode == 0


def ssh(remote_command: str) -> str:
    return run(["ssh", "-S", SOCKET, TARGET, remote_command]).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_master() -> int:
    if master_ready():
        print(json.dumps({"master": "ready", "socket": SOCKET, "target": TARGET}))
        return 0
    command = f"ssh -M -S {shlex.quote(SOCKET)} -o ControlPersist=15m -N -f {TARGET}"
    apple = f'tell application "Terminal" to do script {json.dumps(command)}'
    subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate', "-e", apple], check=True)
    print(json.dumps({
        "master": "password_required",
        "terminal_command": command,
        "next": "Enter the Windows account password in Terminal, then rerun this command or use open.",
    }))
    return 0


def validate_open_source(source: Path) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in OPEN_SUFFIXES:
        allowed = ", ".join(sorted(OPEN_SUFFIXES))
        raise ValueError(f"Input must be an existing structure file with one of: {allowed}")
    return source


def _element_symbol(value: str) -> str:
    symbol = value[:1].upper() + value[1:].lower()
    if symbol not in COVALENT_RADII:
        raise ValueError(f"XYZ element is outside the audited organic preview set: {value}")
    return symbol


def parse_xyz(source: Path) -> tuple[list[dict[str, Any]], str]:
    lines = source.read_text(encoding="utf-8").splitlines()
    if len(lines) < 3:
        raise ValueError("XYZ must contain an atom count, comment, and coordinates")
    try:
        declared = int(lines[0].strip())
    except ValueError as exc:
        raise ValueError("XYZ atom count is not an integer") from exc
    if declared < 1 or declared > 999:
        raise ValueError("XYZ atom count must be between 1 and 999 for V2000 preview")
    coordinate_lines = [line for line in lines[2:] if line.strip()]
    if len(coordinate_lines) != declared:
        raise ValueError(
            f"XYZ atom-count mismatch: declared {declared}, found {len(coordinate_lines)}"
        )
    atoms: list[dict[str, Any]] = []
    for index, line in enumerate(coordinate_lines, 1):
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"XYZ atom {index} must have exactly element,x,y,z fields")
        symbol = _element_symbol(fields[0])
        try:
            coordinates = [float(value) for value in fields[1:]]
        except ValueError as exc:
            raise ValueError(f"XYZ atom {index} has a non-numeric coordinate") from exc
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError(f"XYZ atom {index} has a non-finite coordinate")
        atoms.append(
            {
                "index": index,
                "element": symbol,
                "x": coordinates[0],
                "y": coordinates[1],
                "z": coordinates[2],
            }
        )
    return atoms, lines[1]


def _distance(first: dict[str, Any], second: dict[str, Any]) -> float:
    return math.sqrt(
        (first["x"] - second["x"]) ** 2
        + (first["y"] - second["y"]) ** 2
        + (first["z"] - second["z"]) ** 2
    )


def infer_visual_bonds(atoms: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    bonds: list[dict[str, Any]] = []
    neighbors = {atom["index"]: 0 for atom in atoms}
    closest: float | None = None
    for offset, first in enumerate(atoms):
        for second in atoms[offset + 1 :]:
            distance = _distance(first, second)
            closest = distance if closest is None else min(closest, distance)
            if distance < 0.4:
                raise ValueError(
                    f"XYZ atoms {first['index']} and {second['index']} are only {distance:.4f} angstrom apart"
                )
            cutoff = VISUAL_BOND_FACTOR * (
                COVALENT_RADII[first["element"]] + COVALENT_RADII[second["element"]]
            )
            if distance <= cutoff:
                neighbors[first["index"]] += 1
                neighbors[second["index"]] += 1
                bonds.append(
                    {
                        "first": first["index"],
                        "second": second["index"],
                        "type": 1,
                        "distance_angstrom": round(distance, 8),
                    }
                )
    for atom in atoms:
        count = neighbors[atom["index"]]
        maximum = MAX_VISUAL_NEIGHBORS[atom["element"]]
        if count > maximum:
            raise ValueError(
                f"distance-inferred preview gives atom {atom['index']} ({atom['element']}) "
                f"{count} neighbors, above the audited limit {maximum}"
            )
    if len(bonds) > 999:
        raise ValueError("V2000 preview cannot contain more than 999 bonds")
    return bonds, closest


def mol_v2000_text(atoms: list[dict[str, Any]], bonds: list[dict[str, Any]], source_hash: str) -> str:
    lines = [
        "Codex GaussView visual preview",
        "gaussian-view-rt-win",
        f"Visualization only; source XYZ SHA256 {source_hash}",
        f"{len(atoms):>3}{len(bonds):>3}  0  0  0  0            999 V2000",
    ]
    for atom in atoms:
        lines.append(
            f"{atom['x']:10.4f}{atom['y']:10.4f}{atom['z']:10.4f} "
            f"{atom['element']:<3} 0  0  0  0  0  0  0  0  0  0  0  0"
        )
    for bond in bonds:
        lines.append(
            f"{bond['first']:>3}{bond['second']:>3}{bond['type']:>3}  0  0  0  0"
        )
    lines.append("M  END")
    return "\n".join(lines) + "\n"


def prepare_visual_source(source: Path) -> tuple[Path, Path | None, dict[str, Any] | None]:
    """Return the actual GaussView file plus an optional immutable audit manifest."""
    source = validate_open_source(source)
    if source.suffix.lower() in DIRECT_OPEN_SUFFIXES:
        return source, None, None

    atoms, comment = parse_xyz(source)
    bonds, closest = infer_visual_bonds(atoms)
    source_hash = sha256(source)
    preview = source.with_name(source.stem + ".gaussview.mol")
    manifest_path = source.with_name(source.stem + ".gaussview.json")
    preview_text = mol_v2000_text(atoms, bonds, source_hash)
    preview_hash = hashlib.sha256(preview_text.encode("utf-8")).hexdigest()
    manifest: dict[str, Any] = {
        "schema": VISUAL_PREVIEW_SCHEMA,
        "source_file": source.name,
        "source_sha256": source_hash,
        "source_comment": comment,
        "preview_file": preview.name,
        "preview_sha256": preview_hash,
        "preview_format": "MDL MOL V2000",
        "visualization_only": True,
        "gaussian_input": False,
        "calculation_ready": False,
        "atom_count": len(atoms),
        "atom_order": [
            {"index": atom["index"], "element": atom["element"]} for atom in atoms
        ],
        "closest_pair_angstrom": closest,
        "bond_count": len(bonds),
        "bonds": bonds,
        "connectivity_model": f"covalent_radii_x_{VISUAL_BOND_FACTOR:g}",
        "warnings": [
            "Bond orders are single-bond visualization aids inferred from distance; review connectivity in GaussView.",
            "This MOL preview is not a Gaussian input and must never be submitted as a calculation.",
        ],
    }

    if preview.exists() or manifest_path.exists():
        if not preview.is_file() or not manifest_path.is_file():
            raise ValueError("refusing a partial existing GaussView preview/manifest pair")
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("existing GaussView preview manifest is unreadable") from exc
        if (
            existing == manifest
            and sha256(preview) == preview_hash
        ):
            return preview, manifest_path, existing
        raise ValueError("refusing to overwrite a stale or hash-mismatched GaussView preview")

    preview.write_text(preview_text, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return preview, manifest_path, manifest


def validate_load_probe(probe: dict[str, Any]) -> None:
    if probe.get("loaded") is not True:
        errors = probe.get("errors") or []
        detail = "; ".join(str(item) for item in errors) or str(
            probe.get("reason", "file load was not confirmed")
        )
        raise ValueError(f"GaussView did not confirm the requested document: {detail}")
    if probe.get("errors"):
        raise ValueError("GaussView reported an error despite a matching document window")


def _vbs_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def open_structure(source: Path, project: str) -> int:
    if not master_ready():
        raise SystemExit("SSH master is not ready. Run the 'master' subcommand and enter the password once.")
    try:
        source = validate_open_source(source)
        open_file, manifest_path, manifest = prepare_visual_source(source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    project = re.sub(r"[^A-Za-z0-9_-]+", "_", project).strip("_")
    if not project:
        raise SystemExit("Project name becomes empty after sanitization")

    remote_dir = REMOTE_ROOT + "\\" + project
    remote_source = remote_dir + "\\" + source.name
    remote_file = remote_dir + "\\" + open_file.name
    launcher_name = "open_gaussview.cmd"
    remote_launcher = remote_dir + "\\" + launcher_name
    remote_probe = remote_dir + "\\gaussview_load_probe.ps1"
    remote_probe_launcher = remote_dir + "\\run_gaussview_load_probe.vbs"
    remote_probe_result = remote_dir + "\\gaussview_load_probe_result.json"
    task = "CodexGaussView_" + project[:40]
    probe_task = "CodexGaussViewProbe_" + project[:35]

    ssh(f'powershell -NoProfile -Command "$d=\'{remote_dir}\'; New-Item -ItemType Directory -Force -Path $d | Out-Null; if (-not (Test-Path -LiteralPath \'{GVIEW}\')) {{ exit 41 }}"')
    transfer_files = [source]
    if open_file != source:
        transfer_files.append(open_file)
    if manifest_path is not None:
        transfer_files.append(manifest_path)
    remote_hashes: dict[str, str] = {}
    for local_file in transfer_files:
        remote_scp_path = (
            f"{TARGET}:C:/Users/10261/Desktop/GaussianProjects/{project}/{local_file.name}"
        )
        run(["scp", "-o", f"ControlPath={SOCKET}", str(local_file), remote_scp_path])
        local_hash = sha256(local_file)
        remote_path = remote_dir + "\\" + local_file.name
        remote_hash = ssh(
            f'powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 -LiteralPath \'{remote_path}\').Hash"'
        ).strip().lower()
        if local_hash != remote_hash:
            raise SystemExit(
                f"SHA-256 mismatch for {local_file.name}: local={local_hash} remote={remote_hash}"
            )
        remote_hashes[local_file.name] = remote_hash

    launcher = source.parent / f".{project}_{launcher_name}"
    launcher.write_text(f'@echo off\r\nstart "" "{GVIEW}" "{remote_file}"\r\n', encoding="utf-8", newline="")
    try:
        launcher_remote_scp = f"{TARGET}:C:/Users/10261/Desktop/GaussianProjects/{project}/{launcher_name}"
        run(["scp", "-o", f"ControlPath={SOCKET}", str(launcher), launcher_remote_scp])
        ssh(f"schtasks /Create /TN {task} /TR {remote_launcher} /SC ONCE /ST 23:59 /RU INTERACTIVE /F")
        try:
            ssh(f"schtasks /Run /TN {task}")
        finally:
            ssh(f"schtasks /Delete /TN {task} /F")
    finally:
        launcher.unlink(missing_ok=True)

    processes = ssh('tasklist /FI "IMAGENAME eq gview.exe"')
    if "gview.exe" not in processes or "Console" not in processes:
        raise SystemExit("GaussView was not confirmed in the visible Console session")
    if not PROBE_SCRIPT.is_file():
        raise SystemExit(f"GaussView load probe is missing: {PROBE_SCRIPT}")
    probe_remote_scp = (
        f"{TARGET}:C:/Users/10261/Desktop/GaussianProjects/{project}/gaussview_load_probe.ps1"
    )
    run(["scp", "-o", f"ControlPath={SOCKET}", str(PROBE_SCRIPT), probe_remote_scp])
    probe_powershell = (
        f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{remote_probe}" -ExpectedPath "{remote_file}" '
        f'-OutputPath "{remote_probe_result}" -TimeoutSeconds 15'
    )
    probe_vbs = source.parent / f".{project}_run_gaussview_load_probe.vbs"
    probe_vbs.write_text(
        "Set shell = CreateObject(\"WScript.Shell\")\r\n"
        f"command = {_vbs_string(probe_powershell)}\r\n"
        "shell.Run command, 0, True\r\n",
        encoding="utf-8",
        newline="",
    )
    try:
        probe_launcher_scp = (
            f"{TARGET}:C:/Users/10261/Desktop/GaussianProjects/{project}/run_gaussview_load_probe.vbs"
        )
        run(["scp", "-o", f"ControlPath={SOCKET}", str(probe_vbs), probe_launcher_scp])
        stale_result_cleanup = (
            f'powershell -NoProfile -Command "Remove-Item -LiteralPath \'{remote_probe_result}\' '
            f'-Force -ErrorAction SilentlyContinue; exit 0"'
        )
        run(
            ["ssh", "-S", SOCKET, TARGET, stale_result_cleanup],
            check=False,
        )
        ssh(
            f'schtasks /Create /TN {probe_task} /TR "wscript.exe {remote_probe_launcher}" '
            f'/SC ONCE /ST 23:59 /RU INTERACTIVE /F'
        )
        ssh(f"schtasks /Run /TN {probe_task}")
        result_command = (
            'powershell -NoProfile -Command "'
            f'$deadline=(Get-Date).AddSeconds(25); while ((Get-Date) -lt $deadline) '
            f'{{ if (Test-Path -LiteralPath \'{remote_probe_result}\') '
            f'{{ Get-Content -Raw -LiteralPath \'{remote_probe_result}\'; exit 0 }}; '
            'Start-Sleep -Milliseconds 250 }; exit 54"'
        )
        probe_process = run(["ssh", "-S", SOCKET, TARGET, result_command], check=False)
        payload = probe_process.stdout.strip()
        if not payload:
            raise ValueError(
                probe_process.stderr.strip() or "GaussView load probe returned no structured result"
            )
        probe = json.loads(payload)
        validate_load_probe(probe)
    except (ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        probe_vbs.unlink(missing_ok=True)
        run(
            ["ssh", "-S", SOCKET, TARGET, f"schtasks /Delete /TN {probe_task} /F"],
            check=False,
        )
        cleanup_command = (
            f'powershell -NoProfile -Command "Remove-Item -LiteralPath '
            f'\'{remote_probe}\',\'{remote_probe_launcher}\',\'{remote_probe_result}\' '
            f'-Force -ErrorAction SilentlyContinue"'
        )
        run(
            ["ssh", "-S", SOCKET, TARGET, cleanup_command],
            check=False,
        )

    source_hash = sha256(source)
    preview_hash = sha256(open_file)
    print(json.dumps({
        "opened": True,
        "file_loaded": True,
        "calculation_started": False,
        "local_source": str(source),
        "local_preview": str(open_file),
        "remote_source": remote_source,
        "remote_preview": remote_file,
        "source_sha256": source_hash,
        "preview_sha256": preview_hash,
        "audit_manifest": str(manifest_path) if manifest_path else None,
        "audit_manifest_sha256": sha256(manifest_path) if manifest_path else None,
        "visualization_only": bool(manifest),
        "load_probe": probe,
        "transferred_sha256": remote_hashes,
        "gaussview": GVIEW,
        "session": "Console",
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("master", help="Open or check the reusable SSH master connection")
    sub.add_parser("status", help="Report whether the reusable SSH master is ready")
    open_parser = sub.add_parser("open", help="Transfer, hash-check, and open a Gaussian input")
    open_parser.add_argument("input")
    open_parser.add_argument("--project", required=True)
    args = parser.parse_args()
    if args.command == "master":
        return open_master()
    if args.command == "status":
        print(json.dumps({"master_ready": master_ready(), "socket": SOCKET, "target": TARGET}))
        return 0
    return open_structure(Path(args.input), args.project)


if __name__ == "__main__":
    raise SystemExit(main())
