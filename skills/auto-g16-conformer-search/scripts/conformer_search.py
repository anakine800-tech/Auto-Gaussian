#!/usr/bin/env python3
"""CLI for offline dual-route conformer planning and candidate auditing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import conformer_core as core


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def command_diagnose(args: argparse.Namespace) -> None:
    request_path = Path(args.request).expanduser().resolve()
    result = core.dependency_diagnostic(core.load_json(request_path), request_path)
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_analyze(args: argparse.Namespace) -> None:
    request_path = Path(args.request).expanduser().resolve()
    result = core.analyze_freedom(core.load_json(request_path), request_path)
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_plan(args: argparse.Namespace) -> None:
    request_path = Path(args.request).expanduser().resolve()
    result = core.build_plan(core.load_json(request_path), request_path)
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_audit(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).expanduser().resolve()
    candidates_path = Path(args.candidates).expanduser().resolve()
    result = core.audit_candidates(
        core.load_json(plan_path), plan_path,
        core.load_json(candidates_path), candidates_path,
    )
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_crosscheck(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).expanduser().resolve()
    candidates_path = Path(args.candidates).expanduser().resolve()
    ledger_path = Path(args.ledger).expanduser().resolve()
    result = core.crosscheck(
        core.load_json(plan_path), plan_path,
        core.load_json(candidates_path), candidates_path,
        core.load_json(ledger_path), ledger_path,
    )
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_handoff(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest).expanduser().resolve()
    review_path = Path(args.review).expanduser().resolve()
    result = core.build_handoff(
        core.load_json(manifest_path), manifest_path,
        core.load_json(review_path), review_path,
    )
    core.write_new_json(Path(args.output), result)
    emit(result)


def command_validate_handoff(args: argparse.Namespace) -> None:
    result = core.validate_handoff(args.handoff)
    emit({
        "schema": "gaussian-conformer-candidate-handoff-validation/1",
        "artifact_schema": result["schema"],
        "handoff_id": result["handoff_id"],
        "payload_sha256": result["payload_sha256"],
        "live_actions": False,
    })


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, handler in (
        ("diagnose", "record dependency discovery without executing or installing software", command_diagnose),
        ("analyze", "write the reviewed-input freedom analysis", command_analyze),
        ("plan", "write a non-executable preregistered search plan", command_plan),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("request")
        command.add_argument("--output", required=True)
        command.set_defaults(func=handler)
    audit = sub.add_parser("audit", help="audit supplied candidate observations and preserve negative evidence")
    audit.add_argument("plan")
    audit.add_argument("candidates")
    audit.add_argument("--output", required=True)
    audit.set_defaults(func=command_audit)
    check = sub.add_parser("crosscheck", help="deduplicate, cross-match, cluster, and choose medoids offline")
    check.add_argument("plan")
    check.add_argument("candidates")
    check.add_argument("ledger")
    check.add_argument("--output", required=True)
    check.set_defaults(func=command_crosscheck)
    handoff = sub.add_parser("handoff", help="write a reviewed candidate-only downstream handoff")
    handoff.add_argument("manifest")
    handoff.add_argument("--review", required=True)
    handoff.add_argument("--output", required=True)
    handoff.set_defaults(func=command_handoff)
    validate_handoff = sub.add_parser("validate-handoff", help="replay one exact candidate handoff through its complete owner chain")
    validate_handoff.add_argument("handoff")
    validate_handoff.set_defaults(func=command_validate_handoff)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except core.ContractError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        raise SystemExit(130)
