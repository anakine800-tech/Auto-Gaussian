#!/usr/bin/env python3
"""Own the additive PR4 runtime/path binding and append-only state contract.

This module performs local, no-clobber state publication only.  It never
constructs a legacy effect plan or raw owner, invokes an adapter or runner,
opens a connection, transfers bytes, calls qsub/qstat/qdel, or obtains remote
reconciliation evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable


SCHEMA = "auto-g16-protected-runtime-state-contract/1"
RECEIPT_SCHEMA = "auto-g16-protected-runtime-state-receipt/1"
RECONCILIATION_SCHEMA = (
    "auto-g16-protected-read-only-reconciliation-handoff/1"
)
OWNER = "auto-g16-protected-runtime-state-owner"
HANDOFF_MODULE_NAME = "protected_legacy_effect_handoff"
HANDOFF_SCHEMA = "auto-g16-protected-legacy-effect-handoff/1"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
STATE_CONTAINER = ".auto-g16-protected-runtime-state-v1"
STATES = (
    "ready",
    "effect_not_started",
    "effect_started_outcome_uncertain",
    "accepted_terminal",
)
TRANSITIONS = (
    "runtime_bound_ready",
    "consume_after_final_assert_current",
    "enter_effect_boundary_outcome_uncertain",
    "accept_read_only_reconciliation_terminal",
)
RECEIPT_BASENAMES = (
    "000000-ready.json",
    "000001-effect-not-started.json",
    "000002-effect-started-outcome-uncertain.json",
    "000003-accepted-terminal.json",
)
TERMINAL_CLASSIFICATIONS = {
    "submitted_unique",
    "definitely_not_submitted",
    "terminal_completed",
    "terminal_failed",
}
RUNTIME_REQUIRED_KEYS = {
    "rtwin_ssh_config",
    "windows_target",
    "windows_project_root",
    "windows_server_config",
}
RUNTIME_ALLOWED_KEYS = {
    "core_python",
    "rdkit_python",
    "chemdraw_pipeline_scripts",
    "rtwin_ssh_config",
    "windows_target",
    "windows_control_socket",
    "windows_project_root",
    "windows_server_config",
    "gaussview_exe",
}
SCOPE = {
    "bind_exact_pr4n_handoff": True,
    "bind_runtime_config_identity": True,
    "bind_windows_work_root_identity": True,
    "publish_append_only_local_receipts": True,
    "issue_effect_capability": False,
    "create_effect_plan": False,
    "create_raw_effect_owner": False,
    "invoke_adapter": False,
    "invoke_runner": False,
    "transfer": False,
    "submit": False,
    "status": False,
    "fetch": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
}
POLICY = {
    "single_consumption": True,
    "last_assert_current_before_effect_boundary": True,
    "uncertain_before_external_effect": True,
    "read_only_reconciliation_only_after_uncertain": True,
    "automatic_retry": False,
    "automatic_cancel": False,
    "automatic_cleanup": False,
    "automatic_delete": False,
    "automatic_rollback": False,
    "historical_migration": False,
    "legacy_ledger_is_sole_authority": False,
    "remote_root_override_allowed": False,
}
VALIDATION_LAYERS = {
    "draft_schema_structural_only": True,
    "public_validator_semantic_projection": True,
    "owner_replay_required": True,
    "in_process_seal_required_for_transition": True,
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
JOB_RE = re.compile(r"^[0-9]+(?:\.[A-Za-z0-9._-]+)?$")
ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
WINDOWS_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,63}$")
CONTRACT_RE = re.compile(r"^protected-runtime-state-[a-f0-9]{64}$")
JOURNAL_RE = re.compile(r"^protected-runtime-journal-[a-f0-9]{64}$")
RECEIPT_RE = re.compile(r"^protected-runtime-receipt-[a-f0-9]{64}$")
RECONCILIATION_RE = re.compile(
    r"^protected-read-only-reconciliation-[a-f0-9]{64}$"
)
_MAX_PUBLIC_DEPTH = 64
_MAX_FILE_BYTES = 4 * 1024 * 1024
_CHUNK_SIZE = 64 * 1024
_ZERO_SHA = "0" * 64
_SEAL_TOKEN = object()
_OWNER_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_RECONCILIATION_TOKEN = object()


class ProtectedRuntimeStateError(ValueError):
    """The runtime/state successor cannot be proved safely."""


def canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProtectedRuntimeStateError(
            f"protected runtime/state value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _rebuild_public_json(
    value: object,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> object:
    if depth > _MAX_PUBLIC_DEPTH:
        raise ProtectedRuntimeStateError(
            "protected runtime/state value exceeds the nesting bound"
        )
    value_type = type(value)
    if value_type in {str, int, bool} or value is None:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ProtectedRuntimeStateError(
                "protected runtime/state value contains a non-finite number"
            )
        return value
    if value_type not in {dict, list}:
        raise ProtectedRuntimeStateError(
            "protected runtime/state public validators accept exact builtin JSON only"
        )
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ProtectedRuntimeStateError(
            "protected runtime/state value contains a cycle"
        )
    active.add(identity)
    try:
        if value_type is list:
            return [
                _rebuild_public_json(item, depth=depth + 1, active=active)
                for item in value
            ]
        rebuilt: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ProtectedRuntimeStateError(
                    "protected runtime/state object keys must be strings"
                )
            rebuilt[key] = _rebuild_public_json(
                item,
                depth=depth + 1,
                active=active,
            )
        return rebuilt
    except RuntimeError as exc:
        raise ProtectedRuntimeStateError(
            "protected runtime/state value changed during rebuild"
        ) from exc
    finally:
        active.remove(identity)


def _exact(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ProtectedRuntimeStateError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _sha(value: object, label: str, *, nonzero: bool = False) -> str:
    if (
        type(value) is not str
        or SHA_RE.fullmatch(value) is None
        or (nonzero and value == _ZERO_SHA)
    ):
        raise ProtectedRuntimeStateError(
            f"{label} must be a lowercase"
            f"{' nonzero' if nonzero else ''} SHA-256"
        )
    return value


def _text(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(ord(character) < 0x20 for character in value)
    ):
        raise ProtectedRuntimeStateError(
            f"{label} must be non-empty trimmed control-free text"
        )
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProtectedRuntimeStateError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _fixed_mapping(
    value: object,
    expected: dict[str, bool],
    label: str,
) -> dict[str, Any]:
    result = _exact(value, set(expected), label)
    for field, expected_value in expected.items():
        if (
            type(result[field]) is not bool
            or result[field] is not expected_value
        ):
            raise ProtectedRuntimeStateError(
                f"{label}.{field} must be exact boolean {expected_value!r}"
            )
    return result


def _utc_text(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ProtectedRuntimeStateError(
            f"{label} must be second-precision RFC3339 UTC"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != text:
        raise ProtectedRuntimeStateError(
            f"{label} must be canonical second-precision UTC"
        )
    return text


def _payload_sha256(
    document: dict[str, Any],
    *,
    id_field: str,
    payload_field: str,
) -> str:
    return digest(
        {
            key: value
            for key, value in document.items()
            if key not in {id_field, payload_field}
        }
    )


def _contract_payload_sha256(document: dict[str, Any]) -> str:
    projection = {
        key: value
        for key, value in document.items()
        if key not in {"contract_id", "contract_payload_sha256"}
    }
    projection = json.loads(canonical_bytes(projection))
    projection["journal"]["journal_id"] = (
        "protected-runtime-journal-" + _ZERO_SHA
    )
    return digest(projection)


def _state_status(state: str) -> dict[str, bool]:
    return {
        "ready": state == "ready",
        "consumed": state != "ready",
        "effect_not_started": state == "effect_not_started",
        "effect_outcome_uncertain": (
            state == "effect_started_outcome_uncertain"
        ),
        "accepted": state == "accepted_terminal",
        "terminal": state == "accepted_terminal",
    }


def validate_protected_runtime_state_contract(
    value: object,
) -> dict[str, Any]:
    rebuilt = _rebuild_public_json(value)
    canonical_bytes(rebuilt)
    document = _exact(
        rebuilt,
        {
            "schema",
            "owner",
            "contract_id",
            "handoff",
            "identity",
            "runtime_binding",
            "workspace",
            "journal",
            "state_protocol",
            "validation",
            "scope",
            "policy",
            "contract_payload_sha256",
        },
        "runtime/state contract",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedRuntimeStateError(
            "runtime/state contract schema or owner differs"
        )
    if (
        type(document["contract_id"]) is not str
        or CONTRACT_RE.fullmatch(document["contract_id"]) is None
    ):
        raise ProtectedRuntimeStateError("contract_id is malformed")
    handoff = _exact(
        document["handoff"],
        {
            "schema",
            "handoff_id",
            "handoff_payload_sha256",
            "materialization_id",
            "materialization_state_payload_sha256",
        },
        "contract handoff",
    )
    if handoff["schema"] != HANDOFF_SCHEMA:
        raise ProtectedRuntimeStateError("contract handoff schema differs")
    for field in (
        "handoff_payload_sha256",
        "materialization_state_payload_sha256",
    ):
        _sha(handoff[field], f"handoff.{field}", nonzero=True)
    _text(handoff["handoff_id"], "handoff.handoff_id")
    _text(handoff["materialization_id"], "handoff.materialization_id")

    identity = _exact(
        document["identity"],
        {
            "project",
            "attempt_id",
            "invocation_id",
            "invocation_payload_sha256",
            "input_sha256",
        },
        "contract identity",
    )
    if (
        type(identity["project"]) is not str
        or PROJECT_RE.fullmatch(identity["project"]) is None
        or type(identity["attempt_id"]) is not str
        or ATTEMPT_RE.fullmatch(identity["attempt_id"]) is None
    ):
        raise ProtectedRuntimeStateError("contract identity is malformed")
    _text(identity["invocation_id"], "identity.invocation_id")
    for field in ("invocation_payload_sha256", "input_sha256"):
        _sha(identity[field], f"identity.{field}", nonzero=True)

    runtime = _exact(
        document["runtime_binding"],
        {
            "runtime_config_path_sha256",
            "runtime_config_sha256",
            "runtime_config_size_bytes",
            "first_hop_config_path_sha256",
            "first_hop_config_sha256",
            "first_hop_config_size_bytes",
            "windows_target_sha256",
            "first_hop_ref_sha256",
            "second_hop_ref_sha256",
            "transport_config_bindings_sha256",
            "windows_root_identity_sha256",
            "windows_project_dir_identity_sha256",
            "binding_payload_sha256",
        },
        "runtime binding",
    )
    for field in set(runtime) - {
        "runtime_config_size_bytes",
        "first_hop_config_size_bytes",
    }:
        _sha(runtime[field], f"runtime_binding.{field}", nonzero=True)
    for field in (
        "runtime_config_size_bytes",
        "first_hop_config_size_bytes",
    ):
        _integer(runtime[field], f"runtime_binding.{field}", 1)
    expected_runtime_payload = digest(
        {
            key: item
            for key, item in runtime.items()
            if key != "binding_payload_sha256"
        }
    )
    if runtime["binding_payload_sha256"] != expected_runtime_payload:
        raise ProtectedRuntimeStateError("runtime binding payload differs")

    workspace = _exact(
        document["workspace"],
        {
            "windows_path_normalization",
            "remote_root",
            "remote_project_dir",
            "remote_root_override_allowed",
        },
        "contract workspace",
    )
    if (
        workspace["windows_path_normalization"]
        != "drive-absolute-backslash-casefold/1"
        or workspace["remote_root"] != FIXED_REMOTE_ROOT
        or workspace["remote_project_dir"]
        != f"{FIXED_REMOTE_ROOT}/{identity['project']}"
        or workspace["remote_root_override_allowed"] is not False
    ):
        raise ProtectedRuntimeStateError("contract workspace differs")

    journal = _exact(
        document["journal"],
        {
            "journal_id",
            "state_container",
            "journal_path_sha256",
            "receipt_schema",
            "receipt_basenames",
            "append_only",
            "no_clobber",
            "legacy_ledger_is_sole_authority",
        },
        "contract journal",
    )
    if (
        type(journal["journal_id"]) is not str
        or JOURNAL_RE.fullmatch(journal["journal_id"]) is None
        or journal["state_container"] != STATE_CONTAINER
        or journal["receipt_schema"] != RECEIPT_SCHEMA
        or journal["receipt_basenames"] != list(RECEIPT_BASENAMES)
        or journal["append_only"] is not True
        or journal["no_clobber"] is not True
        or journal["legacy_ledger_is_sole_authority"] is not False
    ):
        raise ProtectedRuntimeStateError("contract journal differs")
    _sha(journal["journal_path_sha256"], "journal path", nonzero=True)

    protocol = _exact(
        document["state_protocol"],
        {
            "states",
            "transitions",
            "initial_state",
            "terminal_state",
            "uncertain_recovery",
            "not_started_recovery",
        },
        "state protocol",
    )
    if protocol != {
        "states": list(STATES),
        "transitions": list(TRANSITIONS),
        "initial_state": "ready",
        "terminal_state": "accepted_terminal",
        "uncertain_recovery": "typed_read_only_reconciliation_only",
        "not_started_recovery": "resume_before_effect_boundary_without_reconsumption",
    }:
        raise ProtectedRuntimeStateError("state protocol differs")
    _fixed_mapping(document["validation"], VALIDATION_LAYERS, "validation")
    _fixed_mapping(document["scope"], SCOPE, "scope")
    _fixed_mapping(document["policy"], POLICY, "policy")
    _sha(
        document["contract_payload_sha256"],
        "contract_payload_sha256",
        nonzero=True,
    )
    expected_payload = _contract_payload_sha256(document)
    if document["contract_payload_sha256"] != expected_payload:
        raise ProtectedRuntimeStateError("contract payload differs")
    expected_id = "protected-runtime-state-" + digest(
        {
            "schema": "auto-g16-protected-runtime-state-id/1",
            "handoff_id": handoff["handoff_id"],
            "attempt_id": identity["attempt_id"],
            "runtime_binding_payload_sha256": runtime[
                "binding_payload_sha256"
            ],
            "journal_path_sha256": journal["journal_path_sha256"],
            "contract_payload_sha256": expected_payload,
        }
    )
    if document["contract_id"] != expected_id:
        raise ProtectedRuntimeStateError("contract_id differs")
    expected_journal = "protected-runtime-journal-" + digest(
        {
            "schema": "auto-g16-protected-runtime-journal-id/1",
            "contract_id": expected_id,
            "attempt_id": identity["attempt_id"],
        }
    )
    if journal["journal_id"] != expected_journal:
        raise ProtectedRuntimeStateError("journal_id differs")
    return document


def validate_protected_runtime_state_receipt(
    value: object,
) -> dict[str, Any]:
    rebuilt = _rebuild_public_json(value)
    canonical_bytes(rebuilt)
    document = _exact(
        rebuilt,
        {
            "schema",
            "owner",
            "receipt_id",
            "journal_id",
            "contract_id",
            "handoff_id",
            "materialization_id",
            "attempt_id",
            "runtime_binding_payload_sha256",
            "sequence",
            "state",
            "transition",
            "previous_receipt_sha256",
            "issued_at",
            "status",
            "reconciliation",
            "policy",
            "receipt_payload_sha256",
        },
        "runtime state receipt",
    )
    if document["schema"] != RECEIPT_SCHEMA or document["owner"] != OWNER:
        raise ProtectedRuntimeStateError(
            "runtime state receipt schema or owner differs"
        )
    if (
        type(document["receipt_id"]) is not str
        or RECEIPT_RE.fullmatch(document["receipt_id"]) is None
        or type(document["journal_id"]) is not str
        or JOURNAL_RE.fullmatch(document["journal_id"]) is None
        or type(document["contract_id"]) is not str
        or CONTRACT_RE.fullmatch(document["contract_id"]) is None
        or type(document["attempt_id"]) is not str
        or ATTEMPT_RE.fullmatch(document["attempt_id"]) is None
    ):
        raise ProtectedRuntimeStateError("runtime state receipt identity is malformed")
    _text(document["handoff_id"], "receipt.handoff_id")
    _text(document["materialization_id"], "receipt.materialization_id")
    _sha(
        document["runtime_binding_payload_sha256"],
        "receipt runtime binding",
        nonzero=True,
    )
    sequence = _integer(document["sequence"], "receipt.sequence", 0)
    if sequence >= len(STATES):
        raise ProtectedRuntimeStateError("receipt sequence is outside the protocol")
    if (
        document["state"] != STATES[sequence]
        or document["transition"] != TRANSITIONS[sequence]
    ):
        raise ProtectedRuntimeStateError("receipt state transition differs")
    _sha(document["previous_receipt_sha256"], "previous receipt")
    if (
        (sequence == 0 and document["previous_receipt_sha256"] != _ZERO_SHA)
        or (sequence > 0 and document["previous_receipt_sha256"] == _ZERO_SHA)
    ):
        raise ProtectedRuntimeStateError("previous receipt binding differs")
    _utc_text(document["issued_at"], "receipt.issued_at")
    _fixed_mapping(
        document["status"],
        _state_status(document["state"]),
        "receipt.status",
    )
    if sequence < 3:
        if document["reconciliation"] is not None:
            raise ProtectedRuntimeStateError(
                "nonterminal receipt must not contain reconciliation"
            )
    else:
        reconciliation = _exact(
            document["reconciliation"],
            {
                "schema",
                "handoff_id",
                "handoff_payload_sha256",
                "classification",
                "evidence_sha256",
            },
            "receipt reconciliation",
        )
        if (
            reconciliation["schema"] != RECONCILIATION_SCHEMA
            or reconciliation["classification"]
            not in TERMINAL_CLASSIFICATIONS
        ):
            raise ProtectedRuntimeStateError(
                "terminal receipt reconciliation differs"
            )
        _text(
            reconciliation["handoff_id"],
            "receipt reconciliation handoff_id",
        )
        for field in ("handoff_payload_sha256", "evidence_sha256"):
            _sha(
                reconciliation[field],
                f"receipt reconciliation {field}",
                nonzero=True,
            )
    _fixed_mapping(document["policy"], POLICY, "receipt.policy")
    _sha(
        document["receipt_payload_sha256"],
        "receipt payload",
        nonzero=True,
    )
    expected_payload = _payload_sha256(
        document,
        id_field="receipt_id",
        payload_field="receipt_payload_sha256",
    )
    if document["receipt_payload_sha256"] != expected_payload:
        raise ProtectedRuntimeStateError("receipt payload differs")
    expected_id = "protected-runtime-receipt-" + digest(
        {
            "schema": "auto-g16-protected-runtime-receipt-id/1",
            "journal_id": document["journal_id"],
            "sequence": sequence,
            "previous_receipt_sha256": document[
                "previous_receipt_sha256"
            ],
            "receipt_payload_sha256": expected_payload,
        }
    )
    if document["receipt_id"] != expected_id:
        raise ProtectedRuntimeStateError("receipt_id differs")
    return document


def validate_protected_read_only_reconciliation_handoff(
    value: object,
) -> dict[str, Any]:
    rebuilt = _rebuild_public_json(value)
    canonical_bytes(rebuilt)
    document = _exact(
        rebuilt,
        {
            "schema",
            "owner",
            "handoff_id",
            "uncertain_receipt",
            "observation",
            "scope",
            "handoff_payload_sha256",
        },
        "read-only reconciliation handoff",
    )
    if (
        document["schema"] != RECONCILIATION_SCHEMA
        or document["owner"] != OWNER
    ):
        raise ProtectedRuntimeStateError(
            "read-only reconciliation schema or owner differs"
        )
    if (
        type(document["handoff_id"]) is not str
        or RECONCILIATION_RE.fullmatch(document["handoff_id"]) is None
    ):
        raise ProtectedRuntimeStateError(
            "read-only reconciliation handoff_id is malformed"
        )
    uncertain = _exact(
        document["uncertain_receipt"],
        {
            "receipt_id",
            "receipt_payload_sha256",
            "journal_id",
            "contract_id",
            "attempt_id",
            "state",
        },
        "reconciliation uncertain receipt",
    )
    if uncertain["state"] != "effect_started_outcome_uncertain":
        raise ProtectedRuntimeStateError(
            "reconciliation requires the exact uncertain state"
        )
    for field in (
        "receipt_payload_sha256",
    ):
        _sha(uncertain[field], f"uncertain_receipt.{field}", nonzero=True)
    for field in ("receipt_id", "journal_id", "contract_id", "attempt_id"):
        _text(uncertain[field], f"uncertain_receipt.{field}")
    observation = _exact(
        document["observation"],
        {
            "classification",
            "job_ids",
            "evidence_sha256",
            "observed_at",
            "remote_read_only",
            "observation_acquired_by_this_contract",
            "automatic_effect_authorized",
            "automatic_retry",
        },
        "reconciliation observation",
    )
    classification = observation["classification"]
    if classification not in TERMINAL_CLASSIFICATIONS:
        raise ProtectedRuntimeStateError(
            "reconciliation classification is not accepted terminal"
        )
    if (
        type(observation["job_ids"]) is not list
        or not all(
            type(job_id) is str and JOB_RE.fullmatch(job_id) is not None
            for job_id in observation["job_ids"]
        )
        or len(set(observation["job_ids"])) != len(
            observation["job_ids"]
        )
    ):
        raise ProtectedRuntimeStateError(
            "reconciliation job_ids are malformed"
        )
    expected_count = 0 if classification == "definitely_not_submitted" else 1
    if len(observation["job_ids"]) != expected_count:
        raise ProtectedRuntimeStateError(
            "reconciliation job count differs from classification"
        )
    _sha(observation["evidence_sha256"], "reconciliation evidence", nonzero=True)
    _utc_text(observation["observed_at"], "reconciliation observed_at")
    _fixed_mapping(
        {
            key: observation[key]
            for key in (
                "remote_read_only",
                "observation_acquired_by_this_contract",
                "automatic_effect_authorized",
                "automatic_retry",
            )
        },
        {
            "remote_read_only": True,
            "observation_acquired_by_this_contract": False,
            "automatic_effect_authorized": False,
            "automatic_retry": False,
        },
        "reconciliation observation flags",
    )
    _fixed_mapping(
        document["scope"],
        {
            "typed_handoff_only": True,
            "remote_read": False,
            "effect": False,
            "terminal_acceptance": True,
        },
        "reconciliation scope",
    )
    _sha(
        document["handoff_payload_sha256"],
        "reconciliation handoff payload",
        nonzero=True,
    )
    expected_payload = _payload_sha256(
        document,
        id_field="handoff_id",
        payload_field="handoff_payload_sha256",
    )
    if document["handoff_payload_sha256"] != expected_payload:
        raise ProtectedRuntimeStateError(
            "reconciliation handoff payload differs"
        )
    expected_id = "protected-read-only-reconciliation-" + digest(
        {
            "schema": "auto-g16-protected-read-only-reconciliation-id/1",
            "uncertain_receipt_payload_sha256": uncertain[
                "receipt_payload_sha256"
            ],
            "evidence_sha256": observation["evidence_sha256"],
            "classification": classification,
            "handoff_payload_sha256": expected_payload,
        }
    )
    if document["handoff_id"] != expected_id:
        raise ProtectedRuntimeStateError(
            "reconciliation handoff_id differs"
        )
    return document


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    identity: tuple[int, ...]
    sha256: str
    size_bytes: int
    source_bytes: bytes


@dataclass(frozen=True, slots=True)
class _HandoffBinding:
    module: types.ModuleType
    issued_type: type
    source: _FileSnapshot


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)


def _stable_file(path: Path) -> _FileSnapshot:
    path = Path(os.path.abspath(path))
    if not path.is_absolute():
        raise ProtectedRuntimeStateError("bound file path must be absolute")
    parts = path.parts[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ProtectedRuntimeStateError("bound file path is unsafe")
    directory = -1
    descriptor = -1
    try:
        directory = os.open(
            path.anchor,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        for part in parts[:-1]:
            next_directory = os.open(
                part,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        before = os.stat(
            parts[-1],
            dir_fd=directory,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedRuntimeStateError(
                f"bound file is not a no-follow regular file: {path.name}"
            )
        descriptor = os.open(
            parts[-1],
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory,
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedRuntimeStateError(
                f"bound file changed while opening: {path.name}"
            )
        if opened.st_size < 1 or opened.st_size > _MAX_FILE_BYTES:
            raise ProtectedRuntimeStateError(
                f"bound file size is outside the limit: {path.name}"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(
            parts[-1],
            dir_fd=directory,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise ProtectedRuntimeStateError(
            f"stable file read failed for {path}: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if directory >= 0:
            os.close(directory)
    if len(
        {
            _stat_identity(before),
            _stat_identity(opened),
            _stat_identity(after_fd),
            _stat_identity(after_path),
        }
    ) != 1:
        raise ProtectedRuntimeStateError(
            f"bound file identity drifted: {path.name}"
        )
    raw = b"".join(chunks)
    if len(raw) != opened.st_size:
        raise ProtectedRuntimeStateError(
            f"bound file read was short: {path.name}"
        )
    return _FileSnapshot(
        path=path,
        identity=_stat_identity(opened),
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
        source_bytes=raw,
    )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if (
        type(raw_file) is not str
        or not raw_file
        or type(raw_origin) is not str
        or not raw_origin
    ):
        raise ImportError("runtime/state predecessor has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _handoff_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    path = here.with_name(f"{HANDOFF_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError("exact adjacent PR4N owner is unavailable")
    resolved = path.resolve(strict=True)
    if resolved.parent != here.parent:
        raise ImportError("PR4N owner is not adjacent")
    return resolved


def _owner_path() -> Path:
    path = Path(__file__).resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ImportError("runtime/state owner is unavailable")
    return path


def _capture_handoff_binding() -> _HandoffBinding:
    path = _handoff_path()
    source = _stable_file(path)
    module = sys.modules.get(HANDOFF_MODULE_NAME)
    if not isinstance(module, types.ModuleType):
        raise ImportError(
            "exact protected_legacy_effect_handoff must load before runtime/state owner"
        )
    if _module_origin(module) != (path, path):
        raise ImportError("exact PR4N owner origin differs")
    issued_type = getattr(
        module,
        "SealedProtectedLegacyEffectHandoff",
        None,
    )
    if (
        not isinstance(issued_type, type)
        or issued_type.__module__ != HANDOFF_MODULE_NAME
        or issued_type.__qualname__
        != "SealedProtectedLegacyEffectHandoff"
    ):
        raise ImportError("exact PR4N owner class identity differs")
    return _HandoffBinding(module, issued_type, source)


_OWNER_SOURCE = _stable_file(_owner_path())
_HANDOFF_BINDING = _capture_handoff_binding()


def _assert_sources_current() -> None:
    if _stable_file(_owner_path()) != _OWNER_SOURCE:
        raise ProtectedRuntimeStateError(
            "runtime/state owner source identity differs"
        )
    if (
        _stable_file(_handoff_path()) != _HANDOFF_BINDING.source
        or sys.modules.get(HANDOFF_MODULE_NAME) is not _HANDOFF_BINDING.module
        or _module_origin(_HANDOFF_BINDING.module)
        != (_handoff_path(), _handoff_path())
        or getattr(
            _HANDOFF_BINDING.module,
            "SealedProtectedLegacyEffectHandoff",
            None,
        )
        is not _HANDOFF_BINDING.issued_type
    ):
        raise ProtectedRuntimeStateError(
            "runtime/state PR4N owner binding differs"
        )


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in pairs:
        if key in result:
            raise ProtectedRuntimeStateError(
                f"runtime config repeats JSON key: {key}"
            )
        result[key] = item
    return result


def _reject_constant(token: str) -> None:
    raise ProtectedRuntimeStateError(
        f"runtime config contains non-standard number: {token}"
    )


def _parse_runtime_config(snapshot: _FileSnapshot) -> dict[str, str]:
    try:
        decoded = snapshot.source_bytes.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_closed_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProtectedRuntimeStateError(
            f"runtime config cannot be decoded strictly: {exc}"
        ) from exc
    if type(value) is not dict or not RUNTIME_REQUIRED_KEYS <= set(value):
        raise ProtectedRuntimeStateError(
            "runtime config lacks the complete protected transport subset"
        )
    unknown = set(value) - RUNTIME_ALLOWED_KEYS
    if unknown:
        raise ProtectedRuntimeStateError(
            f"runtime config contains unknown keys: {sorted(unknown)}"
        )
    normalized = {}
    for key, raw in value.items():
        normalized[key] = _text(raw, f"runtime config {key}")
    return normalized


def _normalized_windows_root(raw: str) -> tuple[str, str]:
    if "/" in raw or "'" in raw or '"' in raw or raw.endswith("\\"):
        raise ProtectedRuntimeStateError(
            "Windows project root is not a canonical backslash path"
        )
    if not re.fullmatch(r"[A-Za-z]:\\.*", raw):
        raise ProtectedRuntimeStateError(
            "Windows project root must be drive-absolute"
        )
    parts = raw[3:].split("\\") if len(raw) > 3 else []
    if (
        not parts
        or any(
            part in {"", ".", ".."}
            or part.endswith((" ", "."))
            or WINDOWS_COMPONENT_RE.fullmatch(part) is None
            for part in parts
        )
    ):
        raise ProtectedRuntimeStateError(
            "Windows project root components are not canonical and safe"
        )
    parsed = PureWindowsPath(raw)
    if not parsed.is_absolute() or parsed.drive.upper() != raw[:2].upper():
        raise ProtectedRuntimeStateError(
            "Windows project root identity differs"
        )
    normalized = str(parsed)
    return normalized, normalized.casefold()


def _adapter_reference_sha256(hop_role: str, reference: str) -> str:
    return digest(
        {
            "domain": "auto-g16-adapter-config-reference/1",
            "adapter_owner": "auto-g16-rtwin-pbs",
            "hop_role": hop_role,
            "private_reference": reference,
        }
    )


def _transport_bindings_sha256(first: str, second: str) -> str:
    projection = {
        "adapter_owner": "auto-g16-rtwin-pbs",
        "first_hop": {
            "hop_role": "first_hop",
            "adapter_config_ref": "rtwin_ssh_config",
            "adapter_config_ref_sha256": first,
        },
        "second_hop": {
            "hop_role": "second_hop",
            "adapter_config_ref": "windows_server_config",
            "adapter_config_ref_sha256": second,
        },
    }
    return digest(projection)


def _trusted_now(clock: Callable[[], datetime]) -> str:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProtectedRuntimeStateError(
            "runtime/state owner clock must return aware UTC"
        )
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_and_identity(
    handoff: object,
    runtime_config_path: Path,
) -> tuple[
    dict[str, Any],
    _FileSnapshot,
    _FileSnapshot,
    dict[str, str],
    dict[str, Any],
]:
    _assert_sources_current()
    if type(handoff) is not _HANDOFF_BINDING.issued_type:
        raise TypeError("runtime/state owner accepts only exact PR4N handoff")
    handoff.assert_current()
    handoff_document = handoff.document()
    materialization = handoff.materialization
    invocation = materialization.lifecycle.protected_invocation_bundle
    invocation.assert_owner_sealed()
    invocation_document = invocation.document()
    protected_submit = invocation.protected_submit_bundle
    protected_submit.assert_owner_sealed()
    protected_document = protected_submit.document()
    identity = invocation_document["identity"]
    if (
        identity["attempt_id"]
        != handoff_document["materialization"]["attempt_id"]
        or invocation_document["invocation_id"]
        != handoff_document["materialization"]["invocation_id"]
        or protected_document["identity"]["project"] != identity["project"]
        or protected_document["identity"]["attempt_id"]
        != identity["attempt_id"]
        or protected_document["workspace"]["allowed_root"]
        != FIXED_REMOTE_ROOT
        or protected_document["workspace"]["root_override_allowed"] is not False
    ):
        raise ProtectedRuntimeStateError(
            "PR4N nested owner identity or fixed workspace differs"
        )

    runtime_snapshot = _stable_file(runtime_config_path)
    values = _parse_runtime_config(runtime_snapshot)
    target = values["windows_target"]
    if ALIAS_RE.fullmatch(target) is None:
        raise ProtectedRuntimeStateError(
            "Windows target alias is not a portable exact alias"
        )
    first_path = Path(values["rtwin_ssh_config"])
    if not first_path.is_absolute():
        raise ProtectedRuntimeStateError(
            "first-hop SSH config path must be absolute"
        )
    first_snapshot = _stable_file(first_path)
    normalized_root, root_identity = _normalized_windows_root(
        values["windows_project_root"]
    )
    project_directory = f"{normalized_root}\\{identity['project']}"
    project_directory_identity = project_directory.casefold()
    second = values["windows_server_config"]
    if (
        ".." in PureWindowsPath(second).parts
        or "'" in second
        or '"' in second
        or "\x00" in second
    ):
        raise ProtectedRuntimeStateError(
            "second-hop config reference is not a safe Windows path"
        )
    first_ref = _adapter_reference_sha256(
        "first_hop",
        values["rtwin_ssh_config"],
    )
    second_ref = _adapter_reference_sha256("second_hop", second)
    bindings = _transport_bindings_sha256(first_ref, second_ref)
    expected = protected_document["transport"][
        "transport_config_bindings_sha256"
    ]
    if bindings != expected:
        raise ProtectedRuntimeStateError(
            "runtime config references differ from sealed transport authority"
        )
    binding = {
        "runtime_config_path_sha256": digest(str(runtime_snapshot.path)),
        "runtime_config_sha256": runtime_snapshot.sha256,
        "runtime_config_size_bytes": runtime_snapshot.size_bytes,
        "first_hop_config_path_sha256": digest(str(first_snapshot.path)),
        "first_hop_config_sha256": first_snapshot.sha256,
        "first_hop_config_size_bytes": first_snapshot.size_bytes,
        "windows_target_sha256": digest(target),
        "first_hop_ref_sha256": first_ref,
        "second_hop_ref_sha256": second_ref,
        "transport_config_bindings_sha256": bindings,
        "windows_root_identity_sha256": digest(root_identity),
        "windows_project_dir_identity_sha256": digest(
            project_directory_identity
        ),
        "binding_payload_sha256": "",
    }
    binding["binding_payload_sha256"] = digest(
        {
            key: item
            for key, item in binding.items()
            if key != "binding_payload_sha256"
        }
    )
    return (
        binding,
        runtime_snapshot,
        first_snapshot,
        values,
        {
            "project": identity["project"],
            "attempt_id": identity["attempt_id"],
            "invocation_id": invocation_document["invocation_id"],
            "invocation_payload_sha256": invocation_document[
                "invocation_payload_sha256"
            ],
            "input_sha256": identity["input_sha256"],
        },
    )


def _journal_path(handoff: object, attempt_id: str) -> Path:
    local_dir = handoff.materialization.local_dir
    if not isinstance(local_dir, Path) or not local_dir.is_absolute():
        raise ProtectedRuntimeStateError(
            "PR4L local directory capability differs"
        )
    return local_dir.parent / STATE_CONTAINER / attempt_id


def _open_or_create_journal(path: Path, *, create: bool) -> tuple[int, tuple[int, ...]]:
    parent = path.parent.parent
    parent_fd = os.open(
        parent,
        os.O_RDONLY
        | os.O_DIRECTORY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0),
    )
    container_fd = -1
    journal_fd = -1
    try:
        if create:
            try:
                os.mkdir(STATE_CONTAINER, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
        container_fd = os.open(
            STATE_CONTAINER,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        basename = path.name
        if create:
            os.mkdir(basename, mode=0o700, dir_fd=container_fd)
        journal_fd = os.open(
            basename,
            os.O_RDONLY
            | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=container_fd,
        )
        identity = _directory_identity(os.fstat(journal_fd))
        return os.dup(journal_fd), identity
    except FileExistsError as exc:
        raise ProtectedRuntimeStateError(
            "runtime/state journal already exists; use explicit recovery"
        ) from exc
    except OSError as exc:
        raise ProtectedRuntimeStateError(
            f"runtime/state journal cannot be opened safely: {exc}"
        ) from exc
    finally:
        if journal_fd >= 0:
            os.close(journal_fd)
        if container_fd >= 0:
            os.close(container_fd)
        os.close(parent_fd)


def _write_receipt(directory_fd: int, basename: str, raw: bytes) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            basename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=directory_fd,
        )
        written = 0
        while written < len(raw):
            count = os.write(descriptor, raw[written:])
            if count <= 0:
                raise ProtectedRuntimeStateError(
                    "runtime/state receipt write made no progress"
                )
            written += count
        os.fsync(descriptor)
        os.fsync(directory_fd)
    except FileExistsError as exc:
        raise ProtectedRuntimeStateError(
            "runtime/state receipt no-clobber publication collided"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _build_contract_document(
    handoff: object,
    binding: dict[str, Any],
    identity: dict[str, Any],
    journal_path: Path,
) -> dict[str, Any]:
    handoff_document = handoff.document()
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "contract_id": "",
        "handoff": {
            "schema": handoff_document["schema"],
            "handoff_id": handoff_document["handoff_id"],
            "handoff_payload_sha256": handoff_document[
                "handoff_payload_sha256"
            ],
            "materialization_id": handoff_document["materialization"][
                "materialization_id"
            ],
            "materialization_state_payload_sha256": handoff_document[
                "materialization"
            ]["state_payload_sha256"],
        },
        "identity": identity,
        "runtime_binding": binding,
        "workspace": {
            "windows_path_normalization": (
                "drive-absolute-backslash-casefold/1"
            ),
            "remote_root": FIXED_REMOTE_ROOT,
            "remote_project_dir": f"{FIXED_REMOTE_ROOT}/{identity['project']}",
            "remote_root_override_allowed": False,
        },
        "journal": {
            "journal_id": "protected-runtime-journal-" + _ZERO_SHA,
            "state_container": STATE_CONTAINER,
            "journal_path_sha256": digest(str(journal_path)),
            "receipt_schema": RECEIPT_SCHEMA,
            "receipt_basenames": list(RECEIPT_BASENAMES),
            "append_only": True,
            "no_clobber": True,
            "legacy_ledger_is_sole_authority": False,
        },
        "state_protocol": {
            "states": list(STATES),
            "transitions": list(TRANSITIONS),
            "initial_state": "ready",
            "terminal_state": "accepted_terminal",
            "uncertain_recovery": "typed_read_only_reconciliation_only",
            "not_started_recovery": (
                "resume_before_effect_boundary_without_reconsumption"
            ),
        },
        "validation": dict(VALIDATION_LAYERS),
        "scope": dict(SCOPE),
        "policy": dict(POLICY),
        "contract_payload_sha256": "",
    }
    # The payload projection normalizes both self-identifying fields, so the
    # contract and journal IDs form a deterministic acyclic binding.
    provisional_payload = _contract_payload_sha256(document)
    contract_id = "protected-runtime-state-" + digest(
        {
            "schema": "auto-g16-protected-runtime-state-id/1",
            "handoff_id": document["handoff"]["handoff_id"],
            "attempt_id": identity["attempt_id"],
            "runtime_binding_payload_sha256": binding[
                "binding_payload_sha256"
            ],
            "journal_path_sha256": document["journal"][
                "journal_path_sha256"
            ],
            "contract_payload_sha256": provisional_payload,
        }
    )
    document["contract_id"] = contract_id
    document["contract_payload_sha256"] = provisional_payload
    document["journal"]["journal_id"] = (
        "protected-runtime-journal-"
        + digest(
            {
                "schema": "auto-g16-protected-runtime-journal-id/1",
                "contract_id": contract_id,
                "attempt_id": identity["attempt_id"],
            }
        )
    )
    return validate_protected_runtime_state_contract(document)


def _build_receipt(
    contract: dict[str, Any],
    *,
    sequence: int,
    previous: str,
    issued_at: str,
    reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "owner": OWNER,
        "receipt_id": "protected-runtime-receipt-" + _ZERO_SHA,
        "journal_id": contract["journal"]["journal_id"],
        "contract_id": contract["contract_id"],
        "handoff_id": contract["handoff"]["handoff_id"],
        "materialization_id": contract["handoff"]["materialization_id"],
        "attempt_id": contract["identity"]["attempt_id"],
        "runtime_binding_payload_sha256": contract["runtime_binding"][
            "binding_payload_sha256"
        ],
        "sequence": sequence,
        "state": STATES[sequence],
        "transition": TRANSITIONS[sequence],
        "previous_receipt_sha256": previous,
        "issued_at": issued_at,
        "status": _state_status(STATES[sequence]),
        "reconciliation": reconciliation,
        "policy": dict(POLICY),
        "receipt_payload_sha256": "",
    }
    document["receipt_payload_sha256"] = _payload_sha256(
        document,
        id_field="receipt_id",
        payload_field="receipt_payload_sha256",
    )
    document["receipt_id"] = "protected-runtime-receipt-" + digest(
        {
            "schema": "auto-g16-protected-runtime-receipt-id/1",
            "journal_id": document["journal_id"],
            "sequence": sequence,
            "previous_receipt_sha256": previous,
            "receipt_payload_sha256": document[
                "receipt_payload_sha256"
            ],
        }
    )
    return validate_protected_runtime_state_receipt(document)


@dataclass(frozen=True, slots=True)
class ProtectedReadOnlyReconciliationEvidence:
    classification: str
    job_ids: tuple[str, ...]
    evidence_sha256: str
    observed_at: str


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedRuntimeStateReceipt:
    _canonical_document: bytes
    _path_snapshot: _FileSnapshot
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "SealedProtectedRuntimeStateReceipt":
        raise TypeError("runtime state receipts are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        snapshot: _FileSnapshot,
        *,
        token: object,
    ) -> "SealedProtectedRuntimeStateReceipt":
        if token is not _SEAL_TOKEN:
            raise ProtectedRuntimeStateError("runtime receipt seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "_path_snapshot", snapshot)
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_current(self) -> "SealedProtectedRuntimeStateReceipt":
        if type(self) is not SealedProtectedRuntimeStateReceipt or self._seal is not _SEAL_TOKEN:
            raise ProtectedRuntimeStateError("runtime receipt seal differs")
        document = validate_protected_runtime_state_receipt(self.document())
        if (
            canonical_bytes(document) != self._canonical_document
            or _stable_file(self._path_snapshot.path) != self._path_snapshot
        ):
            raise ProtectedRuntimeStateError("runtime receipt identity differs")
        return self

    def __copy__(self) -> "SealedProtectedRuntimeStateReceipt":
        raise TypeError("runtime state receipts are not clonable")

    def __deepcopy__(self, memo: dict[int, Any]) -> "SealedProtectedRuntimeStateReceipt":
        del memo
        raise TypeError("runtime state receipts are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("runtime state receipts are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("runtime state receipts are not serializable")


@dataclass(slots=True)
class _JournalState:
    lock: threading.Lock
    receipts: list[SealedProtectedRuntimeStateReceipt]
    directory_identity: tuple[int, ...]


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedReadOnlyReconciliationHandoff:
    _canonical_document: bytes
    uncertain_receipt: SealedProtectedRuntimeStateReceipt
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedReadOnlyReconciliationHandoff":
        raise TypeError("reconciliation handoffs are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        receipt: SealedProtectedRuntimeStateReceipt,
        *,
        token: object,
    ) -> "SealedProtectedReadOnlyReconciliationHandoff":
        if token is not _RECONCILIATION_TOKEN:
            raise ProtectedRuntimeStateError("reconciliation seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "uncertain_receipt", receipt)
        object.__setattr__(value, "_seal", _RECONCILIATION_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(
        self,
    ) -> "SealedProtectedReadOnlyReconciliationHandoff":
        if (
            type(self) is not SealedProtectedReadOnlyReconciliationHandoff
            or self._seal is not _RECONCILIATION_TOKEN
        ):
            raise ProtectedRuntimeStateError("reconciliation seal differs")
        self.uncertain_receipt.assert_current()
        document = validate_protected_read_only_reconciliation_handoff(
            self.document()
        )
        if canonical_bytes(document) != self._canonical_document:
            raise ProtectedRuntimeStateError(
                "reconciliation handoff projection differs"
            )
        return self

    def __copy__(self) -> "SealedProtectedReadOnlyReconciliationHandoff":
        raise TypeError("reconciliation handoffs are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedReadOnlyReconciliationHandoff":
        del memo
        raise TypeError("reconciliation handoffs are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("reconciliation handoffs are not serializable")


class ProtectedReadOnlyReconciliationHandoffOwner:
    """Seal caller-acquired read-only evidence without obtaining it."""

    def __init__(self, *, _factory_token: object) -> None:
        if _factory_token is not _OWNER_TOKEN:
            raise TypeError("reconciliation owner requires its fixed factory")
        self._lock = threading.Lock()
        self._sealed = False

    @classmethod
    def production(cls) -> "ProtectedReadOnlyReconciliationHandoffOwner":
        return cls(_factory_token=_OWNER_TOKEN)

    def seal(
        self,
        *,
        uncertain_receipt: SealedProtectedRuntimeStateReceipt,
        evidence: ProtectedReadOnlyReconciliationEvidence,
    ) -> SealedProtectedReadOnlyReconciliationHandoff:
        with self._lock:
            if self._sealed:
                raise ProtectedRuntimeStateError(
                    "reconciliation handoff owner is single-use"
                )
            self._sealed = True
            if type(uncertain_receipt) is not SealedProtectedRuntimeStateReceipt:
                raise TypeError("reconciliation requires an exact uncertain receipt")
            uncertain_receipt.assert_current()
            receipt = uncertain_receipt.document()
            if receipt["state"] != "effect_started_outcome_uncertain":
                raise ProtectedRuntimeStateError(
                    "reconciliation requires uncertain state"
                )
            if type(evidence) is not ProtectedReadOnlyReconciliationEvidence:
                raise TypeError("reconciliation evidence must be exact typed evidence")
            document: dict[str, Any] = {
                "schema": RECONCILIATION_SCHEMA,
                "owner": OWNER,
                "handoff_id": "protected-read-only-reconciliation-" + _ZERO_SHA,
                "uncertain_receipt": {
                    "receipt_id": receipt["receipt_id"],
                    "receipt_payload_sha256": receipt[
                        "receipt_payload_sha256"
                    ],
                    "journal_id": receipt["journal_id"],
                    "contract_id": receipt["contract_id"],
                    "attempt_id": receipt["attempt_id"],
                    "state": receipt["state"],
                },
                "observation": {
                    "classification": evidence.classification,
                    "job_ids": list(evidence.job_ids),
                    "evidence_sha256": evidence.evidence_sha256,
                    "observed_at": evidence.observed_at,
                    "remote_read_only": True,
                    "observation_acquired_by_this_contract": False,
                    "automatic_effect_authorized": False,
                    "automatic_retry": False,
                },
                "scope": {
                    "typed_handoff_only": True,
                    "remote_read": False,
                    "effect": False,
                    "terminal_acceptance": True,
                },
                "handoff_payload_sha256": "",
            }
            document["handoff_payload_sha256"] = _payload_sha256(
                document,
                id_field="handoff_id",
                payload_field="handoff_payload_sha256",
            )
            document["handoff_id"] = (
                "protected-read-only-reconciliation-"
                + digest(
                    {
                        "schema": "auto-g16-protected-read-only-reconciliation-id/1",
                        "uncertain_receipt_payload_sha256": receipt[
                            "receipt_payload_sha256"
                        ],
                        "evidence_sha256": evidence.evidence_sha256,
                        "classification": evidence.classification,
                        "handoff_payload_sha256": document[
                            "handoff_payload_sha256"
                        ],
                    }
                )
            )
            validated = validate_protected_read_only_reconciliation_handoff(
                document
            )
            return SealedProtectedReadOnlyReconciliationHandoff._from_owner(
                validated,
                uncertain_receipt,
                token=_RECONCILIATION_TOKEN,
            )


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedRuntimeStateContract:
    _canonical_document: bytes
    handoff: object
    runtime_config_snapshot: _FileSnapshot
    first_hop_config_snapshot: _FileSnapshot
    runtime_values: tuple[tuple[str, str], ...]
    journal_path: Path
    _journal: _JournalState
    _clock: Callable[[], datetime]
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedRuntimeStateContract":
        raise TypeError("runtime/state contracts are owner-issued only")

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        handoff: object,
        runtime_config_snapshot: _FileSnapshot,
        first_hop_config_snapshot: _FileSnapshot,
        runtime_values: dict[str, str],
        journal_path: Path,
        journal: _JournalState,
        clock: Callable[[], datetime],
        token: object,
    ) -> "SealedProtectedRuntimeStateContract":
        if token is not _SEAL_TOKEN:
            raise ProtectedRuntimeStateError("runtime/state seal differs")
        value = object.__new__(cls)
        object.__setattr__(value, "_canonical_document", canonical_bytes(document))
        object.__setattr__(value, "handoff", handoff)
        object.__setattr__(value, "runtime_config_snapshot", runtime_config_snapshot)
        object.__setattr__(value, "first_hop_config_snapshot", first_hop_config_snapshot)
        object.__setattr__(value, "runtime_values", tuple(sorted(runtime_values.items())))
        object.__setattr__(value, "journal_path", journal_path)
        object.__setattr__(value, "_journal", journal)
        object.__setattr__(value, "_clock", clock)
        object.__setattr__(value, "_seal", _SEAL_TOKEN)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    @property
    def current_receipt(self) -> SealedProtectedRuntimeStateReceipt:
        with self._journal.lock:
            return self._journal.receipts[-1]

    def _assert_journal_current(self) -> None:
        descriptor, identity = _open_or_create_journal(
            self.journal_path,
            create=False,
        )
        try:
            if identity != self._journal.directory_identity:
                raise ProtectedRuntimeStateError(
                    "runtime/state journal directory identity differs"
                )
            expected = [
                RECEIPT_BASENAMES[index]
                for index in range(len(self._journal.receipts))
            ]
            if sorted(os.listdir(descriptor)) != sorted(expected):
                raise ProtectedRuntimeStateError(
                    "runtime/state journal topology differs"
                )
        finally:
            os.close(descriptor)
        previous = _ZERO_SHA
        for index, receipt in enumerate(self._journal.receipts):
            receipt.assert_current()
            document = receipt.document()
            if (
                document["sequence"] != index
                or document["previous_receipt_sha256"] != previous
            ):
                raise ProtectedRuntimeStateError(
                    "runtime/state receipt chain differs"
                )
            previous = document["receipt_payload_sha256"]

    def assert_current(
        self,
    ) -> "SealedProtectedRuntimeStateContract":
        if (
            type(self) is not SealedProtectedRuntimeStateContract
            or self._seal is not _SEAL_TOKEN
            or type(self.handoff) is not _HANDOFF_BINDING.issued_type
        ):
            raise ProtectedRuntimeStateError("runtime/state seal differs")
        _assert_sources_current()
        self.handoff.assert_current()
        document = validate_protected_runtime_state_contract(self.document())
        if canonical_bytes(document) != self._canonical_document:
            raise ProtectedRuntimeStateError(
                "runtime/state contract projection differs"
            )
        if (
            _stable_file(self.runtime_config_snapshot.path)
            != self.runtime_config_snapshot
            or _stable_file(self.first_hop_config_snapshot.path)
            != self.first_hop_config_snapshot
        ):
            raise ProtectedRuntimeStateError(
                "runtime/state bound file identity differs"
            )
        self._assert_journal_current()
        return self

    def _append(
        self,
        *,
        sequence: int,
        reconciliation: dict[str, Any] | None = None,
    ) -> SealedProtectedRuntimeStateReceipt:
        previous = self._journal.receipts[-1].document()[
            "receipt_payload_sha256"
        ]
        document = _build_receipt(
            self.document(),
            sequence=sequence,
            previous=previous,
            issued_at=_trusted_now(self._clock),
            reconciliation=reconciliation,
        )
        descriptor, identity = _open_or_create_journal(
            self.journal_path,
            create=False,
        )
        try:
            if identity != self._journal.directory_identity:
                raise ProtectedRuntimeStateError(
                    "runtime/state journal identity differs before append"
                )
            basename = RECEIPT_BASENAMES[sequence]
            _write_receipt(descriptor, basename, canonical_bytes(document))
        finally:
            os.close(descriptor)
        snapshot = _stable_file(self.journal_path / RECEIPT_BASENAMES[sequence])
        receipt = SealedProtectedRuntimeStateReceipt._from_owner(
            document,
            snapshot,
            token=_SEAL_TOKEN,
        )
        self._journal.receipts.append(receipt)
        return receipt

    def consume_for_effect_once(
        self,
    ) -> SealedProtectedRuntimeStateReceipt:
        """Final current replay and one durable definitely-not-started receipt."""
        with self._journal.lock:
            if len(self._journal.receipts) != 1:
                raise ProtectedRuntimeStateError(
                    "runtime/state contract has already been consumed"
                )
            self.assert_current()
            return self._append(sequence=1)

    def prepare_effect_boundary_once(
        self,
        receipt: SealedProtectedRuntimeStateReceipt,
    ) -> SealedProtectedRuntimeStateReceipt:
        """Persist uncertainty before any future external effect may start."""
        with self._journal.lock:
            if (
                len(self._journal.receipts) != 2
                or receipt is not self._journal.receipts[-1]
            ):
                raise ProtectedRuntimeStateError(
                    "effect boundary requires the exact latest not-started receipt"
                )
            receipt.assert_current()
            self.assert_current()
            return self._append(sequence=2)

    def accept_reconciliation_once(
        self,
        *,
        uncertain_receipt: SealedProtectedRuntimeStateReceipt,
        reconciliation: SealedProtectedReadOnlyReconciliationHandoff,
    ) -> SealedProtectedRuntimeStateReceipt:
        with self._journal.lock:
            if (
                len(self._journal.receipts) != 3
                or uncertain_receipt is not self._journal.receipts[-1]
                or type(reconciliation)
                is not SealedProtectedReadOnlyReconciliationHandoff
            ):
                raise ProtectedRuntimeStateError(
                    "terminal acceptance requires the exact latest uncertain state"
                )
            reconciliation.assert_owner_sealed()
            reconciliation_document = reconciliation.document()
            uncertain = uncertain_receipt.document()
            if (
                reconciliation.uncertain_receipt is not uncertain_receipt
                or reconciliation_document["uncertain_receipt"][
                    "receipt_payload_sha256"
                ]
                != uncertain["receipt_payload_sha256"]
            ):
                raise ProtectedRuntimeStateError(
                    "reconciliation handoff is spliced from another state"
                )
            self.assert_current()
            return self._append(
                sequence=3,
                reconciliation={
                    "schema": reconciliation_document["schema"],
                    "handoff_id": reconciliation_document["handoff_id"],
                    "handoff_payload_sha256": reconciliation_document[
                        "handoff_payload_sha256"
                    ],
                    "classification": reconciliation_document[
                        "observation"
                    ]["classification"],
                    "evidence_sha256": reconciliation_document[
                        "observation"
                    ]["evidence_sha256"],
                },
            )

    def __copy__(self) -> "SealedProtectedRuntimeStateContract":
        raise TypeError("runtime/state contracts are not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedRuntimeStateContract":
        del memo
        raise TypeError("runtime/state contracts are not clonable")

    def __reduce__(self) -> object:
        raise TypeError("runtime/state contracts are not serializable")

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError("runtime/state contracts are not serializable")


class ProtectedRuntimeStateContractOwner:
    """Create or recover one exact runtime-bound append-only journal."""

    def __init__(
        self,
        runtime_config_path: Path,
        clock: Callable[[], datetime],
        *,
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_OWNER_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError("runtime/state owner requires its fixed factory")
        if not runtime_config_path.is_absolute() or not callable(clock):
            raise TypeError("runtime/state owner path and clock differ")
        self._runtime_config_path = runtime_config_path
        self._clock = clock
        self._lock = threading.Lock()
        self._used = False

    @classmethod
    def production(cls) -> "ProtectedRuntimeStateContractOwner":
        raw = os.environ.get("AUTO_G16_RUNTIME_CONFIG")
        path = (
            Path(raw).expanduser()
            if raw
            else Path.home() / ".config" / "auto-g16" / "runtime.json"
        )
        if not path.is_absolute():
            raise ProtectedRuntimeStateError(
                "AUTO_G16_RUNTIME_CONFIG must resolve to an absolute path"
            )
        return cls(path, _utc_now, _factory_token=_OWNER_TOKEN)

    @classmethod
    def _for_testing_with_clock(
        cls,
        runtime_config_path: Path,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "ProtectedRuntimeStateContractOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError("private runtime/state test token differs")
        return cls(
            runtime_config_path,
            clock,
            _factory_token=_TEST_OWNER_TOKEN,
        )

    def _prepare(
        self,
        handoff: object,
    ) -> tuple[
        dict[str, Any],
        _FileSnapshot,
        _FileSnapshot,
        dict[str, str],
        Path,
    ]:
        binding, runtime, first, values, identity = _runtime_and_identity(
            handoff,
            self._runtime_config_path,
        )
        path = _journal_path(handoff, identity["attempt_id"])
        document = _build_contract_document(
            handoff,
            binding,
            identity,
            path,
        )
        return document, runtime, first, values, path

    def seal(
        self,
        handoff: object,
    ) -> SealedProtectedRuntimeStateContract:
        with self._lock:
            if self._used:
                raise ProtectedRuntimeStateError(
                    "runtime/state owner is single-use"
                )
            self._used = True
            document, runtime, first, values, path = self._prepare(handoff)
            directory_fd, identity = _open_or_create_journal(
                path,
                create=True,
            )
            try:
                ready = _build_receipt(
                    document,
                    sequence=0,
                    previous=_ZERO_SHA,
                    issued_at=_trusted_now(self._clock),
                )
                _write_receipt(
                    directory_fd,
                    RECEIPT_BASENAMES[0],
                    canonical_bytes(ready),
                )
            finally:
                os.close(directory_fd)
            receipt = SealedProtectedRuntimeStateReceipt._from_owner(
                ready,
                _stable_file(path / RECEIPT_BASENAMES[0]),
                token=_SEAL_TOKEN,
            )
            sealed = SealedProtectedRuntimeStateContract._from_owner(
                document,
                handoff=handoff,
                runtime_config_snapshot=runtime,
                first_hop_config_snapshot=first,
                runtime_values=values,
                journal_path=path,
                journal=_JournalState(
                    threading.Lock(),
                    [receipt],
                    identity,
                ),
                clock=self._clock,
                token=_SEAL_TOKEN,
            )
            sealed.assert_current()
            return sealed

    def recover(
        self,
        handoff: object,
    ) -> SealedProtectedRuntimeStateContract:
        with self._lock:
            if self._used:
                raise ProtectedRuntimeStateError(
                    "runtime/state owner is single-use"
                )
            self._used = True
            document, runtime, first, values, path = self._prepare(handoff)
            descriptor, identity = _open_or_create_journal(
                path,
                create=False,
            )
            try:
                names = sorted(os.listdir(descriptor))
            finally:
                os.close(descriptor)
            if (
                not names
                or names
                != list(RECEIPT_BASENAMES[: len(names)])
                or len(names) > len(RECEIPT_BASENAMES)
            ):
                raise ProtectedRuntimeStateError(
                    "runtime/state recovery journal topology differs"
                )
            receipts = []
            previous = _ZERO_SHA
            for index, name in enumerate(names):
                snapshot = _stable_file(path / name)
                try:
                    raw = json.loads(
                        snapshot.source_bytes,
                        object_pairs_hook=_closed_pairs,
                        parse_constant=_reject_constant,
                    )
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise ProtectedRuntimeStateError(
                        f"runtime/state recovery receipt is invalid: {exc}"
                    ) from exc
                receipt_document = validate_protected_runtime_state_receipt(raw)
                if (
                    receipt_document["contract_id"] != document["contract_id"]
                    or receipt_document["sequence"] != index
                    or receipt_document["previous_receipt_sha256"] != previous
                ):
                    raise ProtectedRuntimeStateError(
                        "runtime/state recovery chain differs"
                    )
                receipt = SealedProtectedRuntimeStateReceipt._from_owner(
                    receipt_document,
                    snapshot,
                    token=_SEAL_TOKEN,
                )
                receipts.append(receipt)
                previous = receipt_document["receipt_payload_sha256"]
            sealed = SealedProtectedRuntimeStateContract._from_owner(
                document,
                handoff=handoff,
                runtime_config_snapshot=runtime,
                first_hop_config_snapshot=first,
                runtime_values=values,
                journal_path=path,
                journal=_JournalState(threading.Lock(), receipts, identity),
                clock=self._clock,
                token=_SEAL_TOKEN,
            )
            sealed.assert_current()
            return sealed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
