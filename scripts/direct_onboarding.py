#!/usr/bin/env python3
"""Offline-only onboarding for the non-production direct SSH/PBS candidate.

This command never opens a path or connection and never performs SSH, PBS,
Gaussian, qsub, qdel, delete, cleanup, deployment, or any other external
effect.  Direct profile documents are accepted only as bounded JSON on stdin.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from typing import Any

import direct_root_owner_contract as ROOT_OWNER
import direct_ssh_pbs_offline as DIRECT_OFFLINE


TEMPLATE_SCHEMA = "auto-g16-direct-onboarding-template/1"
RESULT_SCHEMA = "auto-g16-direct-onboarding-result/1"
DIRECT_STATUSES = (
    "offline_synthetic",
    "production_blocked",
    "live_not_ready",
)
HASH_PREFIX_LENGTH = 12

# Independent literal compatibility snapshots.  Do not derive these from the
# mutable reporting values that they verify.
EXPECTED_DIRECT_STATUSES = (
    "offline_synthetic",
    "production_blocked",
    "live_not_ready",
)

EXPECTED_PRODUCTION_GAPS = (
    "physical_descriptor_relative_helper",
    "durable_cross_process_consumption",
    "direct_resource_effect_time_replay_ingress",
    "direct_live_approval_effect_time_replay_ingress",
    "direct_transport",
    "real_qsub",
    "real_inspect",
    "real_fetch",
    "separately_authorized_live_smoke_evidence",
)

EXPECTED_SUPPORT_MATRIX = {
    "legacy_rtwin_pbs": {
        "status": "existing_production_path_not_authorized_by_this_command",
        "onboarding_owner": "platform_contracts",
        "root_policy": "fixed_legacy_root",
        "direct_cli_allowed": False,
    },
    "direct_ssh_pbs": {
        "statuses": [
            "offline_synthetic",
            "production_blocked",
            "live_not_ready",
        ],
        "backend_supported": False,
        "live_ready": False,
        "production_gaps": [
            "physical_descriptor_relative_helper",
            "durable_cross_process_consumption",
            "direct_resource_effect_time_replay_ingress",
            "direct_live_approval_effect_time_replay_ingress",
            "direct_transport",
            "real_qsub",
            "real_inspect",
            "real_fetch",
            "separately_authorized_live_smoke_evidence",
        ],
    },
    "local_gaussian": {"status": "unsupported"},
    "slurm": {"status": "unsupported"},
    "mcp": {"status": "unsupported"},
    "multihop": {"status": "unsupported"},
    "arbitrary_shell": {"status": "unsupported"},
    "unknown": {"status": "fail_closed"},
}

EXPECTED_PR6_AUTHORITY = {
    "synthetic_only": True,
    "schema_valid_is_capability": False,
    "backend_supported": False,
    "live_ready": False,
    "remote_effect_performed": False,
    "transport_authorized": False,
    "qsub_authorized": False,
    "qsub_invoked": False,
    "qdel_capability": False,
    "qdel_requires_separate_exact_authorization": True,
    "delete_capability": False,
    "cleanup_capability": False,
    "automatic_retry": False,
}

EXPECTED_PR6_OWNER_GAPS = (
    {
        "port": "resource_effect_time_replay",
        "exact_owner": "resource_effect_time_replay_owner",
        "expected_type": "ResourceEffectTimeReplayCapability",
        "status": "required_exact_direct_ingress_unavailable",
        "fallback_allowed": False,
        "synthetic_substitute_allowed": False,
    },
    {
        "port": "live_approval_effect_time_replay",
        "exact_owner": "live_approval_effect_time_replay",
        "expected_type": "PreQsubLiveApprovalReplayCapability",
        "status": "required_exact_direct_ingress_unavailable",
        "fallback_allowed": False,
        "synthetic_substitute_allowed": False,
    },
)

OWNER_GAP_SUPPORT_TOKENS = {
    "resource_effect_time_replay": "direct_resource_effect_time_replay_ingress",
    "live_approval_effect_time_replay": "direct_live_approval_effect_time_replay_ingress",
}

PRODUCTION_GAPS = (
    "physical_descriptor_relative_helper",
    "durable_cross_process_consumption",
    "direct_resource_effect_time_replay_ingress",
    "direct_live_approval_effect_time_replay_ingress",
    "direct_transport",
    "real_qsub",
    "real_inspect",
    "real_fetch",
    "separately_authorized_live_smoke_evidence",
)

SUPPORT_MATRIX = {
    "legacy_rtwin_pbs": {
        "status": "existing_production_path_not_authorized_by_this_command",
        "onboarding_owner": "platform_contracts",
        "root_policy": "fixed_legacy_root",
        "direct_cli_allowed": False,
    },
    "direct_ssh_pbs": {
        "statuses": list(DIRECT_STATUSES),
        "backend_supported": False,
        "live_ready": False,
        "production_gaps": list(PRODUCTION_GAPS),
    },
    "local_gaussian": {"status": "unsupported"},
    "slurm": {"status": "unsupported"},
    "mcp": {"status": "unsupported"},
    "multihop": {"status": "unsupported"},
    "arbitrary_shell": {"status": "unsupported"},
    "unknown": {"status": "fail_closed"},
}


class DirectOnboardingError(ValueError):
    """One sanitized direct-onboarding error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject_float(_token: str) -> Any:
    raise DirectOnboardingError(
        "invalid_json_type",
        "direct onboarding JSON does not accept floating-point values",
    )


def _reject_constant(_token: str) -> Any:
    raise DirectOnboardingError(
        "invalid_json_constant",
        "direct onboarding JSON does not accept non-finite constants",
    )


def _closed_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise DirectOnboardingError(
                "duplicate_json_key",
                "direct onboarding JSON contains a duplicate key",
            )
        value[key] = item
    return value


def parse_stdin_document(raw: bytes) -> dict[str, Any]:
    """Parse one bounded exact JSON object without interpreting its schema."""
    if type(raw) is not bytes or not raw or len(raw) > ROOT_OWNER.MAX_DOCUMENT_BYTES:
        raise DirectOnboardingError(
            "invalid_input_size",
            "direct onboarding input must be one bounded non-empty JSON document",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DirectOnboardingError(
            "invalid_utf8",
            "direct onboarding input must be exact UTF-8",
        ) from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_closed_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except DirectOnboardingError:
        raise
    except (ValueError, RecursionError) as exc:
        raise DirectOnboardingError(
            "invalid_json",
            "direct onboarding input is not one valid JSON document",
        ) from exc
    if type(value) is not dict:
        raise DirectOnboardingError(
            "invalid_document_shape",
            "direct onboarding input must be one exact JSON object",
        )
    return value


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _finalize(document: dict[str, Any], field: str) -> dict[str, Any]:
    result = copy.deepcopy(document)
    projection = copy.deepcopy(result)
    projection.pop(field, None)
    result[field] = hashlib.sha256(_canonical_bytes(projection)).hexdigest()
    return result


def _is_exact_value(value: Any, expected: Any) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return value.keys() == expected.keys() and all(
            _is_exact_value(value[field], expected_value)
            for field, expected_value in expected.items()
        )
    if type(expected) in {list, tuple}:
        return len(value) == len(expected) and all(
            _is_exact_value(item, expected_item)
            for item, expected_item in zip(value, expected, strict=True)
        )
    return value == expected


def _is_exact_closed_mapping(value: Any, expected: dict[str, Any]) -> bool:
    return _is_exact_value(value, expected)


def _assert_pr6_non_authority() -> None:
    if (
        not _is_exact_value(DIRECT_STATUSES, EXPECTED_DIRECT_STATUSES)
        or not _is_exact_value(PRODUCTION_GAPS, EXPECTED_PRODUCTION_GAPS)
        or not _is_exact_closed_mapping(SUPPORT_MATRIX, EXPECTED_SUPPORT_MATRIX)
    ):
        raise DirectOnboardingError(
            "pr6_support_snapshot_drift",
            "the offline direct-backend support snapshot changed",
        )

    authority = getattr(DIRECT_OFFLINE, "AUTHORITY", None)
    if not _is_exact_closed_mapping(authority, EXPECTED_PR6_AUTHORITY):
        raise DirectOnboardingError(
            "pr6_authority_drift",
            "the approved offline direct-backend non-authority markers changed",
        )

    owner_gaps = getattr(DIRECT_OFFLINE, "OWNER_GAPS", None)
    owner_gap_type = getattr(DIRECT_OFFLINE, "OwnerGap", None)
    if (
        type(owner_gaps) is not tuple
        or len(owner_gaps) != len(EXPECTED_PR6_OWNER_GAPS)
        or owner_gap_type is None
        or any(type(gap) is not owner_gap_type for gap in owner_gaps)
    ):
        raise DirectOnboardingError(
            "pr6_owner_gap_drift",
            "the approved offline direct-backend owner gaps changed",
        )
    try:
        owner_gap_documents = tuple(gap.document() for gap in owner_gaps)
    except (AttributeError, TypeError) as exc:
        raise DirectOnboardingError(
            "pr6_owner_gap_drift",
            "the approved offline direct-backend owner gaps changed",
        ) from exc
    if any(
        not _is_exact_closed_mapping(document, expected)
        for document, expected in zip(
            owner_gap_documents,
            EXPECTED_PR6_OWNER_GAPS,
            strict=True,
        )
    ):
        raise DirectOnboardingError(
            "pr6_owner_gap_drift",
            "the approved offline direct-backend owner gaps changed",
        )

    try:
        owner_gap_tokens = tuple(
            OWNER_GAP_SUPPORT_TOKENS[document["port"]]
            for document in owner_gap_documents
        )
        direct_support = SUPPORT_MATRIX["direct_ssh_pbs"]
    except (KeyError, TypeError) as exc:
        raise DirectOnboardingError(
            "pr6_support_gap_drift",
            "the offline direct-backend support summary changed",
        ) from exc
    if (
        owner_gap_tokens
        != (
            "direct_resource_effect_time_replay_ingress",
            "direct_live_approval_effect_time_replay_ingress",
        )
        or any(token not in PRODUCTION_GAPS for token in owner_gap_tokens)
        or not _is_exact_closed_mapping(
            direct_support,
            EXPECTED_SUPPORT_MATRIX["direct_ssh_pbs"],
        )
    ):
        raise DirectOnboardingError(
            "pr6_support_gap_drift",
            "the offline direct-backend support summary changed",
        )


def build_unreviewed_template(profile_id: str) -> dict[str, Any]:
    """Build a non-authorizing checklist, never an execution profile."""
    _assert_pr6_non_authority()
    if type(profile_id) is not str or ROOT_OWNER.ID_RE.fullmatch(profile_id) is None:
        raise DirectOnboardingError(
            "invalid_profile_id",
            "profile id is not a valid direct-profile identifier",
        )
    return _finalize(
        {
            "schema": TEMPLATE_SCHEMA,
            "profile_id": profile_id,
            "target_profile_schema": ROOT_OWNER.DIRECT_PROFILE_SCHEMA,
            "backend_kind": ROOT_OWNER.BACKEND_KIND,
            "status": "unreviewed_non_authorizing_template",
            "support_statuses": list(DIRECT_STATUSES),
            "required_owner_inputs": [
                ROOT_OWNER.PROFILE_POLICY_SCHEMA,
                ROOT_OWNER.STABLE_EVIDENCE_SCHEMA,
            ],
            "required_human_review": True,
            "root_must_be_backend_owned_profile_field": True,
            "root_must_be_profile_hash_bound": True,
            "root_override_allowed": False,
            "schema_valid_is_capability": False,
            "backend_supported": False,
            "live_ready": False,
            "template_payload_sha256": "",
        },
        "template_payload_sha256",
    )


def validate_direct_profile(document: Any) -> dict[str, Any]:
    """Validate only the exact direct execution-profile/3 owner contract."""
    _assert_pr6_non_authority()
    if type(document) is not dict:
        raise DirectOnboardingError(
            "invalid_document_shape",
            "direct profile input must be one exact JSON object",
        )
    schema = document.get("schema")
    if schema in {
        "auto-g16-execution-profile/1",
        "auto-g16-execution-profile/2",
    }:
        raise DirectOnboardingError(
            "legacy_profile_requires_legacy_owner",
            "legacy profiles must use their existing legacy command or owner; no direct fallback exists",
        )
    if schema != ROOT_OWNER.DIRECT_PROFILE_SCHEMA:
        raise DirectOnboardingError(
            "unsupported_profile_schema",
            "direct onboarding accepts only auto-g16-execution-profile/3",
        )
    try:
        profile = ROOT_OWNER.validate_direct_execution_profile(document)
    except (ROOT_OWNER.DirectRootOwnerError, TypeError, ValueError) as exc:
        raise DirectOnboardingError(
            "invalid_direct_profile",
            "direct execution-profile/3 failed its sole owner validator",
        ) from exc
    return profile


def validate_summary(document: Any) -> dict[str, Any]:
    profile = validate_direct_profile(document)
    return {
        "schema": RESULT_SCHEMA,
        "command": "validate",
        "profile_schema": ROOT_OWNER.DIRECT_PROFILE_SCHEMA,
        "profile_id": profile["profile_id"],
        "profile_payload_sha256": profile["profile_payload_sha256"],
        "statuses": list(DIRECT_STATUSES),
        "backend_supported": False,
        "live_ready": False,
        "offline_only": True,
        "capability_issued": False,
    }


def doctor_summary(document: Any) -> dict[str, Any]:
    profile = validate_direct_profile(document)
    return {
        "schema": RESULT_SCHEMA,
        "command": "doctor",
        "profile_hash_prefix": profile["profile_payload_sha256"][:HASH_PREFIX_LENGTH],
        "hash_prefix_requires_user_confirmation_before_sharing": True,
        "statuses": list(DIRECT_STATUSES),
        "backend_supported": False,
        "live_ready": False,
        "offline_only": True,
        "redacted": True,
        "production_gaps": list(PRODUCTION_GAPS),
        "support": copy.deepcopy(SUPPORT_MATRIX),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser(
        "init",
        help="emit one unreviewed non-authorizing direct onboarding template",
    )
    init.add_argument("profile_id", help="portable profile identifier only")

    commands.add_parser(
        "validate",
        help="validate exact execution-profile/3 JSON from stdin",
    )
    commands.add_parser(
        "doctor",
        help="emit a redacted offline diagnosis for profile/3 JSON from stdin",
    )
    return parser


def _write_json(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(_canonical_bytes(value))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _assert_pr6_non_authority()
        if args.command == "init":
            _write_json(build_unreviewed_template(args.profile_id))
        else:
            document = parse_stdin_document(
                sys.stdin.buffer.read(ROOT_OWNER.MAX_DOCUMENT_BYTES + 1)
            )
            if args.command == "validate":
                _write_json(validate_summary(document))
            elif args.command == "doctor":
                _write_json(doctor_summary(document))
            else:  # argparse owns the closed command enum.
                raise DirectOnboardingError(
                    "unsupported_command",
                    "direct onboarding command is unsupported",
                )
        return 0
    except DirectOnboardingError as exc:
        print(f"ERROR {exc.code}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
