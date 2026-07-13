#!/usr/bin/env python3
"""One-command structure preparation, PBS submission, monitoring, and results."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import gaussian_rtwin_pbs as transport


RDKIT_PYTHON = Path("<MAC_HOME>/miniforge3/envs/chem/bin/python")
PREPARE_PREVIEW = Path.home() / ".codex/skills/gaussian-view-rt-win/scripts/prepare_preview.py"
TRANSPORT = Path(__file__).with_name("gaussian_rtwin_pbs.py")
PROTOCOLS = {
    "smoke-test": {
        "route": "#p b3lyp/sto-3g opt",
        "mem": "2GB",
        "nproc": 4,
        "purpose": "Fast workflow validation only; not a research recommendation.",
    },
    "organic-opt": {
        "route": "#p b3lyp/6-31g(d) opt",
        "mem": "50GB",
        "nproc": 22,
        "purpose": "Previously approved basic closed-shell organic optimization example.",
    },
}
RESOURCE_TIERS = {
    "simple": {"mem": "12GB", "nproc": 8},
    "general": {"mem": "50GB", "nproc": 22},
    "complex": {"mem": "120GB", "nproc": 44},
}
PROTECTED_STATES = {"submitted", "queued", "running", "completed", "failed", "interrupted", "submission_uncertain"}


def fail(message: str, code: int = 2) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def guarded_local_dir(path: Path) -> Path:
    path = path.expanduser().resolve()
    job_path = path / "job.json"
    if job_path.is_file():
        try:
            state = json.loads(job_path.read_text(encoding="utf-8")).get("status")
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"cannot read existing job.json: {exc}")
        if state in PROTECTED_STATES:
            fail(f"local directory already records {state!r}; choose a new project directory")
    path.mkdir(parents=True, exist_ok=True)
    return path


def selected_protocol(args) -> dict[str, Any]:
    protocol = dict(PROTOCOLS[args.protocol])
    tier = args.resource_tier
    if tier is None and args.protocol != "smoke-test":
        tier = "general"
    if tier:
        protocol.update(RESOURCE_TIERS[tier])
        protocol["resource_tier"] = tier
    else:
        protocol["resource_tier"] = "smoke-test"
    if args.route:
        protocol["route"] = args.route
    if args.mem:
        protocol["mem"] = args.mem
    if args.nproc:
        protocol["nproc"] = args.nproc
    if args.mem or args.nproc:
        protocol["resource_tier"] = "custom"
    return protocol


def matching_resource_tier(mem: str, nproc: int) -> str:
    for name, tier in RESOURCE_TIERS.items():
        if transport.parse_memory(mem) == transport.parse_memory(tier["mem"]) and nproc == tier["nproc"]:
            return name
    return "custom"


def prepare_source(args) -> dict[str, Any]:
    project = transport.validate_project(args.project)
    local_dir = guarded_local_dir(Path(args.local_dir))
    source_path = Path(args.source).expanduser()
    if source_path.is_file() and source_path.suffix.lower() in {".gjf", ".com"}:
        gjf = source_path.resolve()
        report = None
        workflow = None
        existing_audit = transport.parse_gaussian(gjf)
        manifest_path = gjf.with_suffix(".json")
        if manifest_path.is_file():
            manifest_value = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_value.get("schema") == "gaussian-opt-freq-sp/1":
                workflow = {
                    "species_id": manifest_value.get("species_id"),
                    "stages": manifest_value.get("stages"),
                    "temperature_k": manifest_value.get("temperature_k"),
                    "standard_state": manifest_value.get("standard_state"),
                    "quasi_harmonic_correction": manifest_value.get("quasi_harmonic_correction"),
                }
        if args.resource_tier or args.mem or args.nproc:
            requested = selected_protocol(args)
            if (
                transport.parse_memory(existing_audit["mem"]) != transport.parse_memory(requested["mem"])
                or existing_audit["nprocshared"] != requested["nproc"]
            ):
                fail(
                    "existing Gaussian input resources do not match the requested tier/overrides; "
                    "review and update the audited input before submission"
                )
        protocol = {
            "route": existing_audit["route"],
            "mem": existing_audit["mem"],
            "nproc": existing_audit["nprocshared"],
            "resource_tier": matching_resource_tier(existing_audit["mem"], existing_audit["nprocshared"]),
            "purpose": "Existing audited Gaussian input",
        }
    else:
        workflow = None
        protocol = selected_protocol(args)
        if not RDKIT_PYTHON.is_file() or not PREPARE_PREVIEW.is_file():
            fail("gaussian-view-rt-win preparation dependency is missing")
        command = [
            str(RDKIT_PYTHON), str(PREPARE_PREVIEW), args.source,
            "--output-dir", str(local_dir), "--project", project,
            "--route", protocol["route"], "--mem", protocol["mem"],
            "--nproc", str(protocol["nproc"]),
            "--charge", str(args.charge), "--multiplicity", str(args.multiplicity),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            fail((result.stderr or result.stdout).strip())
        gjf = local_dir / f"{project}_cartesian.gjf"
        report_path = local_dir / f"{project}_preview_report.json"
        if not gjf.is_file() or not report_path.is_file():
            fail("preparation did not produce the expected Gaussian input/report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("warnings"):
            fail("preparation report contains unresolved warnings: " + "; ".join(report["warnings"]))
    audit = transport.parse_gaussian(gjf)
    summary = {
        "schema": "gaussian-auto-preflight/1",
        "project": project,
        "source": str(source_path.resolve()) if source_path.is_file() else args.source,
        "local_dir": str(local_dir),
        "gaussian_input": str(gjf),
        "protocol": protocol,
        "charge": audit["charge"],
        "multiplicity": audit["multiplicity"],
        "atom_count": audit["atom_count"],
        "elements": audit["elements"],
        "input_sha256": audit["input_sha256"],
        "remote_workdir": transport.remote_project_dir(project),
        "warnings": [] if report is None else report.get("warnings", []),
        "automatic_retry_policy": "disabled; diagnose and require explicit approval",
    }
    if workflow is not None:
        summary["workflow"] = workflow
    transport.atomic_json(local_dir / "automation_preflight.json", summary)
    return summary


def connection_arguments(args) -> list[str]:
    values = []
    for option in ("mac_ssh_config", "rtwin_alias", "windows_root", "windows_server_config", "server_alias"):
        value = getattr(args, option, None)
        if value:
            values.extend(["--" + option.replace("_", "-"), str(value)])
    return values


def command_prepare(args) -> None:
    print(json.dumps(prepare_source(args), ensure_ascii=False, indent=2))


def command_auto(args) -> None:
    if not args.confirmed:
        fail("auto requires --confirmed after approval of source, protocol, charge, multiplicity, and resources")
    summary = prepare_source(args)
    print(json.dumps({"approved_preflight": summary}, ensure_ascii=False, indent=2), flush=True)
    submit_command = [
        sys.executable, str(TRANSPORT), "submit", summary["gaussian_input"],
        "--project", args.project, "--local-dir", args.local_dir, "--confirmed",
        *connection_arguments(args),
    ]
    if args.dry_run:
        submit_command.append("--dry-run")
    submitted = subprocess.run(submit_command)
    if submitted.returncode:
        raise SystemExit(submitted.returncode)
    if args.dry_run or not args.watch:
        return
    job = json.loads((Path(args.local_dir).expanduser().resolve() / "job.json").read_text(encoding="utf-8"))
    job_id = job.get("job_id")
    if not job_id:
        fail("submission succeeded without a recorded PBS job id", code=3)
    input_stem = Path(job["input"]).stem
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else Path(args.local_dir).expanduser().resolve() / "results"
    watch_command = [
        sys.executable, str(TRANSPORT), "watch",
        "--project", args.project, "--job-id", job_id,
        "--input-stem", input_stem, "--local-dir", args.local_dir,
        "--output-dir", str(output_dir), "--poll-seconds", str(args.poll_seconds),
        "--timeout-seconds", str(args.timeout_seconds), "--fetch",
        *connection_arguments(args),
    ]
    watched = subprocess.run(watch_command)
    raise SystemExit(watched.returncode)


def add_prepare_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="CDX/CDXML/MOL/SDF/SMILES, or an existing .gjf/.com")
    parser.add_argument("--project", required=True)
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--protocol", choices=sorted(PROTOCOLS), default="organic-opt")
    parser.add_argument("--resource-tier", choices=sorted(RESOURCE_TIERS))
    parser.add_argument("--route")
    parser.add_argument("--mem")
    parser.add_argument("--nproc", type=int)
    parser.add_argument("--charge", type=int, default=0)
    parser.add_argument("--multiplicity", type=int, default=1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="prepare and report without network submission")
    add_prepare_options(prepare)
    prepare.set_defaults(func=command_prepare)
    auto = sub.add_parser("auto", help="prepare, submit once, watch, fetch, and analyze")
    add_prepare_options(auto)
    auto.add_argument("--confirmed", action="store_true")
    auto.add_argument("--watch", action="store_true")
    auto.add_argument("--dry-run", action="store_true")
    auto.add_argument("--output-dir")
    auto.add_argument("--poll-seconds", type=int, default=30)
    auto.add_argument("--timeout-seconds", type=int, default=86400)
    transport.add_connection_options(auto)
    auto.set_defaults(func=command_auto)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        fail("interrupted", code=130)
