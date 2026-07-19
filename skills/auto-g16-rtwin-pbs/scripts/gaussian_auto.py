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


def prepare_source(args, *, maturity_action: str = "ts_input") -> dict[str, Any]:
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
    audit = transport.parse_gaussian(gjf)
    maturity = transport.audit_scientific_maturity(args, audit, maturity_action)
    detail = {
        "schema": "gaussian-auto-preflight/1",
        "source": str(source_path.resolve()) if source_path.is_file() else args.source,
        "local_dir": str(local_dir),
        "gaussian_input": str(gjf),
        "atom_count": audit["atom_count"],
        "elements": audit["elements"],
        "warnings": [] if report is None else report.get("warnings", []),
        "automatic_retry_policy": "disabled; diagnose and require explicit approval",
    }
    input_approval_record = getattr(args, "input_approval_record", None)
    requested_work_kind = getattr(args, "work_kind", None)
    compatibility = transport.input_approval_compatibility(audit, requested_work_kind)
    if input_approval_record:
        assert requested_work_kind is not None
        input_approval = transport.validate_input_approval(
            Path(input_approval_record), gjf, audit, requested_work_kind
        )
    elif compatibility["status"] != "supported_generic_v1":
        input_approval = {**compatibility, "no_submission_authorization": True}
    else:
        input_approval = {
            "status": "missing_required_for_live_submission",
            "required_schema": compatibility.get("required_schema", transport.INPUT_APPROVAL_SCHEMA),
            "work_kind": requested_work_kind,
            "no_submission_authorization": True,
        }
    # Reuse the direct submitter's canonical authority summary instead of
    # reconstructing a legacy wrapper-only approval scope.
    summary = transport.live_approval_summary(
        project, audit, maturity, requested_work_kind, input_approval
    )
    if input_approval["status"] == "validated_exact_input_approval":
        summary["live_approval_requirement"] = transport.live_approval_scope_proposal(summary)
    summary = {**summary, **detail}
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
    args._prospective_live = not args.dry_run
    summary = prepare_source(args, maturity_action="ts_submission")
    execution_values = (
        args.execution_batch_ledger, args.scientific_task_id, args.idempotency_key,
        args.estimated_core_hours, args.estimated_core_hours_evidence_source,
        args.estimated_core_hours_evidence_sha256,
        args.resource_policy, args.resource_gate, args.scheduler_resource_snapshot,
        args.resource_tier, args.resource_cores, args.resource_memory_gb, args.walltime_seconds,
    )
    if not args.dry_run and any(value is None for value in execution_values):
        fail("live auto submission requires the complete execution-batch reservation binding")
    if all(value is not None for value in execution_values):
        try:
            ledger = transport.resource_efficiency.validate_ledger(
                transport.resource_efficiency.load(Path(args.execution_batch_ledger).expanduser().resolve())
            )
            policy = transport.resource_efficiency.validate_policy(transport.resource_efficiency.load(Path(args.resource_policy).expanduser().resolve()))
            gate = transport.resource_efficiency._validate_gate_binding(transport.resource_efficiency.load(Path(args.resource_gate).expanduser().resolve()), allow_historical=False)
            scheduler = transport.resource_efficiency.validate_scheduler_snapshot(transport.resource_efficiency.load(Path(args.scheduler_resource_snapshot).expanduser().resolve()))
        except (transport.execution_batch.BatchError, transport.resource_efficiency.ResourceError) as exc:
            fail(f"execution-batch gate blocked auto submit: {exc}")
        task = next(
            (item for item in ledger["tasks"] if item["scientific_task_id"] == args.scientific_task_id),
            None,
        )
        if task is None or task["identity"]["relevant_input_sha256"] != summary["input_sha256"]:
            fail("auto execution binding does not match the exact reviewed input task")
        summary["execution"] = {
            "batch_id": ledger["batch"]["batch_id"],
            "review_sha256": ledger["batch"]["review_sha256"],
            "scientific_task_id": args.scientific_task_id,
            "attempt_id": transport.execution_batch.attempt_id_for(
                ledger["batch"]["batch_id"], args.idempotency_key
            ),
            "idempotency_key": args.idempotency_key,
            "estimated_core_hours": float(args.estimated_core_hours),
            "estimated_core_hours_evidence": {
                "source": args.estimated_core_hours_evidence_source,
                "sha256": args.estimated_core_hours_evidence_sha256,
            },
            "resource_binding": {
                "policy_id": policy["policy_id"], "policy_sha256": policy["payload_sha256"],
                "gate_id": gate["gate_id"], "gate_sha256": gate["gate_sha256"],
                "resource_tier": args.resource_tier, "cores": args.resource_cores,
                "memory_gb": args.resource_memory_gb, "walltime_seconds": args.walltime_seconds,
            },
        }
        if gate["policy_sha256"] != policy["payload_sha256"] or gate["scheduler_snapshot"]["payload_sha256"] != scheduler["payload_sha256"]:
            fail("auto resource policy/gate/scheduler binding mismatch")
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
    for option in (
        "execution_batch_ledger", "scientific_task_id", "idempotency_key",
        "estimated_core_hours", "estimated_core_hours_evidence_source",
        "estimated_core_hours_evidence_sha256",
        "resource_policy", "resource_gate", "scheduler_resource_snapshot", "resource_tier",
        "resource_cores", "resource_memory_gb", "walltime_seconds",
    ):
        value = getattr(args, option, None)
        if value is not None:
            submit_command.extend(["--" + option.replace("_", "-"), str(value)])
    if args.dry_run:
        submit_command.append("--dry-run")
    # The transport owns finite timeouts for each local/SSH/scp phase.  Do not
    # kill the multi-phase transaction with a shorter wrapper timeout: once a
    # phase has begun, an outer timeout cannot prove the physical outcome.
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
        "--execution-batch-ledger", args.execution_batch_ledger,
        "--attempt-id", summary["execution"]["attempt_id"],
        *connection_arguments(args),
    ]
    try:
        watched = subprocess.run(watch_command, timeout=args.timeout_seconds + 60)
    except subprocess.TimeoutExpired:
        fail("watch subprocess exceeded its explicit timeout", code=4)
    raise SystemExit(watched.returncode)


def add_prepare_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="existing reviewed .gjf/.com input")
    parser.add_argument("--project", required=True)
    parser.add_argument("--local-dir", required=True)
    parser.add_argument(
        "--input-approval-record",
        help=(
            f"owner-validated {transport.INPUT_APPROVAL_SCHEMA} for ordinary/closed-shell minimum, "
            f"or fully replayed {transport.OPEN_SHELL_INPUT_APPROVAL_SCHEMA} for legacy open-shell minimum, "
            f"or {transport.OPEN_SHELL_FAMILY_INPUT_APPROVAL_SCHEMA} for one two-stage family member"
        ),
    )
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
    auto.add_argument(
        "--approval-record",
        help="resource-bound one-time live approval /9, /10, or /11 for protected submit",
    )
    auto.add_argument("--execution-batch-ledger")
    auto.add_argument("--scientific-task-id")
    auto.add_argument("--idempotency-key")
    auto.add_argument("--estimated-core-hours", type=float)
    auto.add_argument("--estimated-core-hours-evidence-source")
    auto.add_argument("--estimated-core-hours-evidence-sha256")
    auto.add_argument("--resource-policy")
    auto.add_argument("--resource-gate")
    auto.add_argument("--scheduler-resource-snapshot")
    auto.add_argument("--resource-tier")
    auto.add_argument("--resource-cores", type=int)
    auto.add_argument("--resource-memory-gb", type=int)
    auto.add_argument("--walltime-seconds", type=int)
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
