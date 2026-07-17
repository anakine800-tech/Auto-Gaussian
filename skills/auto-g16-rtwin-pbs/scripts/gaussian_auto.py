#!/usr/bin/env python3
"""Run an already reviewed Gaussian input after an exact live-approval gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import gaussian_rtwin_pbs as transport
TRANSPORT = Path(__file__).with_name("gaussian_rtwin_pbs.py")
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


def matching_resource_tier(mem: str, nproc: int) -> str:
    for name, tier in RESOURCE_TIERS.items():
        if transport.parse_memory(mem) == transport.parse_memory(tier["mem"]) and nproc == tier["nproc"]:
            return name
    return "custom"


def prepare_source(args) -> dict[str, Any]:
    project = transport.validate_project(args.project)
    local_dir = guarded_local_dir(Path(args.local_dir))
    source_path = Path(args.source).expanduser()
    if not source_path.is_file() or source_path.suffix.lower() not in {".gjf", ".com"}:
        fail(
            "gaussian_auto accepts only an existing reviewed .gjf/.com input; "
            "create a protocol-options artifact, record a hash-bound selection, "
            "and render the exact offline input before using this runner"
        )
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
    protocol = {
        "route": existing_audit["route"],
        "mem": existing_audit["mem"],
        "nproc": existing_audit["nprocshared"],
        "resource_tier": matching_resource_tier(existing_audit["mem"], existing_audit["nprocshared"]),
        "purpose": "Existing audited Gaussian input",
    }
    audit = transport.parse_gaussian(gjf)
    maturity = transport.audit_scientific_maturity(args, audit, "ts_input")
    if maturity is not None and args.scientific_action_authorization:
        owner = transport._load_scientific_maturity()
        tier = transport._resource_tier(audit["mem"], audit["nprocshared"])
        authorization_path = Path(args.scientific_action_authorization).expanduser().resolve()
        authorization = owner.validate_action_authorization(
            authorization_path,
            gate_path=Path(args.scientific_maturity).expanduser().resolve(),
            input_sha256=audit["input_sha256"], edge_id=args.edge_id, node_id=args.node_id,
            project=project, work_kind=args.work_kind, resource_tier=tier,
        )
        maturity["exact_action_authorization"] = {
            "sha256": transport.sha256(authorization_path),
            "payload_sha256": authorization["payload_sha256"],
            "node_id": authorization["scope"]["node_id"],
            "project": authorization["scope"]["project"],
            "input_sha256": authorization["input"]["sha256"],
            "no_submission_authorization": True,
        }
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
    if maturity is not None:
        # Approval material deliberately leads with scientific maturity,
        # evidence/endpoints/blockers before protocol/resources/input hash.
        summary = {"scientific_maturity": maturity, **summary}
    input_approval_record = getattr(args, "input_approval_record", None)
    requested_work_kind = getattr(args, "work_kind", None)
    summary["work_kind"] = requested_work_kind
    compatibility = transport.input_approval_compatibility(audit, requested_work_kind)
    if compatibility["status"] != "supported_generic_v1":
        summary["input_approval"] = {**compatibility, "no_submission_authorization": True}
    elif input_approval_record:
        assert requested_work_kind is not None
        summary["input_approval"] = transport.validate_input_approval(
            Path(input_approval_record), gjf, audit, requested_work_kind
        )
    else:
        summary["input_approval"] = {
            "status": "missing_required_for_live_submission",
            "required_schema": transport.INPUT_APPROVAL_SCHEMA,
            "work_kind": requested_work_kind,
            "no_submission_authorization": True,
        }
    if workflow is not None:
        summary["workflow"] = workflow
    transport.atomic_json(local_dir / "automation_preflight.json", summary)
    return summary


def validate_live_approval(path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return transport.validate_live_approval(path, summary)


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
        fail("auto requires --confirmed after exact live approval")
    if not args.dry_run and not args.work_kind:
        fail("live auto submission requires an explicit --work-kind; it must not default to ordinary")
    summary = prepare_source(args)
    if "scientific_maturity" in summary and "exact_action_authorization" not in summary["scientific_maturity"]:
        fail("protected auto submission requires an exact offline scientific action authorization before live approval")
    if not args.dry_run and summary["input_approval"]["status"] != "validated_exact_input_approval":
        if summary["input_approval"]["status"] == "blocked_missing_specialist_input_approval":
            fail("blocked_missing_specialist_input_approval: specialist owner approval is not integrated")
        fail("auto submission requires --input-approval-record before live approval")
    if not args.dry_run:
        if not args.approval_record:
            fail("a hash-bound --approval-record is required for live submission")
        validate_live_approval(Path(args.approval_record), summary)
    elif args.approval_record and summary["input_approval"]["status"] == "validated_exact_input_approval":
        validate_live_approval(Path(args.approval_record), summary)
    print(json.dumps({"approved_preflight": summary}, ensure_ascii=False, indent=2), flush=True)
    submit_command = [
        sys.executable, str(TRANSPORT), "submit", summary["gaussian_input"],
        "--project", args.project, "--local-dir", args.local_dir, "--confirmed",
        *connection_arguments(args),
    ]
    if args.scientific_maturity:
        submit_command.extend(["--scientific-maturity", args.scientific_maturity, "--edge-id", args.edge_id, "--node-id", args.node_id])
    if args.pilot:
        submit_command.append("--pilot")
    if args.work_kind:
        submit_command.extend(["--work-kind", args.work_kind])
    if args.scientific_action_authorization:
        submit_command.extend(["--scientific-action-authorization", args.scientific_action_authorization])
    if args.input_approval_record:
        submit_command.extend(["--input-approval-record", args.input_approval_record])
    if args.approval_record:
        submit_command.extend(["--approval-record", args.approval_record])
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
    parser.add_argument("source", help="existing reviewed .gjf/.com input")
    parser.add_argument("--project", required=True)
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--input-approval-record", help=f"owner-validated {transport.INPUT_APPROVAL_SCHEMA} required for live submission")
    transport.add_scientific_maturity_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="prepare and report without network submission")
    add_prepare_options(prepare)
    prepare.set_defaults(func=command_prepare)
    auto = sub.add_parser("auto", help="prepare, submit once, watch, fetch, and analyze")
    add_prepare_options(auto)
    auto.add_argument("--confirmed", action="store_true")
    auto.add_argument("--approval-record")
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
