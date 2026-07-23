#!/usr/bin/env python3
"""Owner-sealed, non-executable protected invocation successor for Auto-G16.

The owner composes the existing protected-submit and local-state owners with
the unique legacy stage-byte planner.  It exposes no adapter, reservation,
command, callback, backend selector, configuration, or effect.
"""

from __future__ import annotations

import _imp
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator


SCHEMA = "auto-g16-protected-invocation-bundle/1"
OWNER = "auto-g16-protected-invocation-owner"
STAGE_PLAN_SCHEMA = "auto-g16-legacy-stage-byte-plan/1"
STAGE_MANIFEST_SCHEMA = "auto-g16-legacy-stage-manifest/1"
OPERATION_ORDER = (
    "replay_protected_submit_owner",
    "replay_local_state_owner",
    "plan_full_legacy_stage_bytes",
    "seal_non_executable_invocation",
)
FUTURE_LEGACY_TRANSACTION_ORDER = (
    "reserve_execution_attempt_once",
    "materialize_exact_stage_bytes",
    "transfer_exact_stage_bytes",
    "submit_once",
)
SOURCE_ROLES = {
    "gaussian_input",
    "companion_json",
    "companion_xyz",
    "old_checkpoint",
}
GENERATED_ROLES = {
    "pbs_script",
    "checksums_manifest",
}
ALL_ROLES = SOURCE_ROLES | GENERATED_ROLES
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
TASK_RE = re.compile(r"^scientific-task-[a-f0-9]{64}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
INVOCATION_RE = re.compile(r"^protected-invocation-[a-f0-9]{64}$")
SAFE_BASENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SEAL_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_MODULE_LOCK = threading.RLock()
_MISSING_MODULE = object()


class ProtectedInvocationError(ValueError):
    """The exact non-executable invocation closure cannot be proved."""


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _compact_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProtectedInvocationError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtectedInvocationError(f"{label} must be a non-empty string")
    return value


def _sha(value: Any, label: str) -> str:
    value = _text(value, label)
    if SHA_RE.fullmatch(value) is None:
        raise ProtectedInvocationError(f"{label} must be a lowercase SHA-256")
    return value


def _integer(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise ProtectedInvocationError(f"{label} must be a Draft integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    else:
        raise ProtectedInvocationError(f"{label} must be a Draft integer")
    if result < minimum:
        raise ProtectedInvocationError(
            f"{label} must be at least {minimum}"
        )
    return result


def _utc_time(value: Any, label: str) -> datetime:
    value = _text(value, label)
    try:
        parsed = datetime.strptime(
            value,
            "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ProtectedInvocationError(
            f"{label} must be canonical second-precision UTC"
        ) from exc
    return parsed


def _normalize_integers(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(document)
    if not isinstance(result, dict):
        raise ProtectedInvocationError(
            "protected invocation bundle must be an object"
        )
    ledger = result.get("ledger")
    if isinstance(ledger, dict):
        for field in (
            "artifact_size_bytes",
            "revision",
            "resource_state_revision",
        ):
            if (
                isinstance(ledger.get(field), float)
                and ledger[field].is_integer()
            ):
                ledger[field] = int(ledger[field])
    resources = result.get("resources")
    if isinstance(resources, dict):
        for field in ("cores", "memory_gb", "walltime_seconds"):
            if (
                isinstance(resources.get(field), float)
                and resources[field].is_integer()
            ):
                resources[field] = int(resources[field])
    stage = result.get("stage_plan")
    if isinstance(stage, dict):
        if (
            isinstance(stage.get("artifact_count"), float)
            and stage["artifact_count"].is_integer()
        ):
            stage["artifact_count"] = int(stage["artifact_count"])
        artifacts = stage.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if not isinstance(artifact, dict):
                    continue
                for field in ("order", "size_bytes"):
                    if (
                        isinstance(artifact.get(field), float)
                        and artifact[field].is_integer()
                    ):
                        artifact[field] = int(artifact[field])
    return result


def finalize(document: dict[str, Any]) -> dict[str, Any]:
    result = _normalize_integers(document)
    result["invocation_payload_sha256"] = digest(
        {
            key: value
            for key, value in result.items()
            if key != "invocation_payload_sha256"
        }
    )
    return result


def validate_protected_invocation_bundle(value: Any) -> dict[str, Any]:
    """Validate portable topology; this never issues an in-process seal."""

    document = _exact(
        _normalize_integers(value),
        {
            "schema",
            "owner",
            "invocation_id",
            "identity",
            "predecessors",
            "local_state",
            "ledger",
            "resources",
            "transport",
            "stage_plan",
            "operation_order",
            "future_legacy_transaction_order",
            "scope",
            "policy",
            "invocation_payload_sha256",
        },
        "protected invocation bundle",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedInvocationError("protected invocation schema/owner differs")
    if (
        not isinstance(document["invocation_id"], str)
        or INVOCATION_RE.fullmatch(document["invocation_id"]) is None
    ):
        raise ProtectedInvocationError("protected invocation ID is malformed")

    identity = _exact(
        document["identity"],
        {
            "project",
            "attempt_id",
            "scientific_task_id",
            "input_sha256",
            "idempotency_key_sha256",
            "scientific_identity_sha256",
        },
        "protected invocation identity",
    )
    if (
        not isinstance(identity["project"], str)
        or PROJECT_RE.fullmatch(identity["project"]) is None
        or not isinstance(identity["attempt_id"], str)
        or ATTEMPT_RE.fullmatch(identity["attempt_id"]) is None
        or not isinstance(identity["scientific_task_id"], str)
        or TASK_RE.fullmatch(identity["scientific_task_id"]) is None
    ):
        raise ProtectedInvocationError("protected invocation identity differs")
    for field in (
        "input_sha256",
        "idempotency_key_sha256",
        "scientific_identity_sha256",
    ):
        _sha(identity[field], f"identity.{field}")

    predecessors = _exact(
        document["predecessors"],
        {"protected_submit", "local_state_binding"},
        "protected invocation predecessors",
    )
    protected = _exact(
        predecessors["protected_submit"],
        {"schema", "bundle_payload_sha256"},
        "protected-submit predecessor",
    )
    if protected["schema"] != "auto-g16-protected-submit-bundle/1":
        raise ProtectedInvocationError("protected-submit predecessor differs")
    _sha(
        protected["bundle_payload_sha256"],
        "protected-submit predecessor payload",
    )
    local = _exact(
        predecessors["local_state_binding"],
        {"schema", "binding_payload_sha256"},
        "local-state predecessor",
    )
    if local["schema"] != "auto-g16-local-state-binding/1":
        raise ProtectedInvocationError("local-state predecessor differs")
    _sha(local["binding_payload_sha256"], "local-state predecessor payload")

    local_state = _exact(
        document["local_state"],
        {
            "relative_local_dir",
            "ledger_basename",
            "workspace_root_path_sha256",
            "local_dir_path_sha256",
        },
        "protected invocation local state",
    )
    expected_relative = PurePosixPath(
        "outputs",
        identity["project"],
        identity["attempt_id"],
    )
    if (
        local_state["relative_local_dir"] != str(expected_relative)
        or local_state["ledger_basename"] != "execution-batch-v3.json"
    ):
        raise ProtectedInvocationError(
            "local-state logical identity differs from invocation identity"
        )
    _sha(
        local_state["workspace_root_path_sha256"],
        "workspace-root path binding",
    )
    _sha(local_state["local_dir_path_sha256"], "local-dir path binding")

    ledger = _exact(
        document["ledger"],
        {
            "schema",
            "artifact_sha256",
            "artifact_size_bytes",
            "ledger_identity_sha256",
            "ledger_sha256",
            "revision",
            "resource_state_revision",
            "resource_state_sha256",
            "review_sha256",
        },
        "protected invocation ledger",
    )
    if ledger["schema"] != "gaussian-execution-batch/3":
        raise ProtectedInvocationError("protected invocation requires ledger /3")
    for field in (
        "artifact_sha256",
        "ledger_identity_sha256",
        "ledger_sha256",
        "resource_state_sha256",
        "review_sha256",
    ):
        _sha(ledger[field], f"ledger.{field}")
    ledger["artifact_size_bytes"] = _integer(
        ledger["artifact_size_bytes"],
        "ledger artifact size",
        minimum=1,
    )
    ledger["revision"] = _integer(
        ledger["revision"],
        "ledger revision",
        minimum=0,
    )
    ledger["resource_state_revision"] = _integer(
        ledger["resource_state_revision"],
        "ledger resource-state revision",
        minimum=0,
    )

    resources = _exact(
        document["resources"],
        {
            "policy_id",
            "policy_sha256",
            "gate_id",
            "gate_sha256",
            "resource_tier",
            "cores",
            "memory_gb",
            "walltime_seconds",
            "resource_binding_sha256",
        },
        "protected invocation resources",
    )
    _text(resources["policy_id"], "resource policy id")
    _sha(resources["policy_sha256"], "resource policy")
    _text(resources["gate_id"], "resource gate id")
    _sha(resources["gate_sha256"], "resource gate")
    if (
        not isinstance(resources["resource_tier"], str)
        or resources["resource_tier"]
        not in {
            "simple",
            "general",
            "complex",
            "custom_reviewed",
        }
    ):
        raise ProtectedInvocationError("resource tier differs")
    for field in ("cores", "memory_gb", "walltime_seconds"):
        resources[field] = _integer(
            resources[field],
            f"resources.{field}",
            minimum=1,
        )
    expected_resource_hash = digest(
        {
            key: item
            for key, item in resources.items()
            if key != "resource_binding_sha256"
        }
    )
    if resources["resource_binding_sha256"] != expected_resource_hash:
        raise ProtectedInvocationError("resource binding hash differs")

    transport = _exact(
        document["transport"],
        {
            "protected_transport_payload_sha256",
            "authorization_sha256",
            "successor_closure_sha256",
            "handshake_receipt_sha256",
        },
        "protected invocation transport",
    )
    for field in transport:
        _sha(transport[field], f"transport.{field}")

    stage = _exact(
        document["stage_plan"],
        {
            "schema",
            "manifest_schema",
            "manifest_sha256",
            "artifact_count",
            "artifacts",
            "protected_submit_stage_manifest_sha256",
            "protected_submit_stage_bundle_sha256",
        },
        "protected invocation stage plan",
    )
    if (
        stage["schema"] != STAGE_PLAN_SCHEMA
        or stage["manifest_schema"] != STAGE_MANIFEST_SCHEMA
    ):
        raise ProtectedInvocationError("legacy stage plan schema differs")
    stage["artifact_count"] = _integer(
        stage["artifact_count"],
        "stage artifact count",
        minimum=3,
    )
    artifacts = stage["artifacts"]
    if (
        not isinstance(artifacts, list)
        or len(artifacts) != stage["artifact_count"]
    ):
        raise ProtectedInvocationError("stage artifact count differs")
    names: set[str] = set()
    roles: list[str] = []
    for index, raw in enumerate(artifacts, start=1):
        artifact = _exact(
            raw,
            {"role", "relative_name", "order", "sha256", "size_bytes"},
            f"stage artifact {index}",
        )
        if (
            not isinstance(artifact["role"], str)
            or artifact["role"] not in ALL_ROLES
        ):
            raise ProtectedInvocationError("stage artifact role differs")
        name = artifact["relative_name"]
        if (
            not isinstance(name, str)
            or SAFE_BASENAME_RE.fullmatch(name) is None
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or name in names
        ):
            raise ProtectedInvocationError(
                "stage artifact relative name is unsafe or repeated"
            )
        names.add(name)
        roles.append(artifact["role"])
        artifact["order"] = _integer(
            artifact["order"],
            "stage artifact order",
            minimum=1,
        )
        if artifact["order"] != index:
            raise ProtectedInvocationError("stage artifact order differs")
        _sha(artifact["sha256"], "stage artifact hash")
        artifact["size_bytes"] = _integer(
            artifact["size_bytes"],
            "stage artifact size",
            minimum=1,
        )
    expected_role_order = {
        "gaussian_input": 0,
        "companion_json": 1,
        "companion_xyz": 2,
        "old_checkpoint": 3,
        "pbs_script": 4,
        "checksums_manifest": 5,
    }
    if (
        roles[0] != "gaussian_input"
        or roles[-2:] != ["pbs_script", "checksums_manifest"]
        or roles.count("gaussian_input") != 1
        or roles.count("pbs_script") != 1
        or roles.count("checksums_manifest") != 1
        or len(set(roles)) != len(roles)
        or [
            expected_role_order[role]
            for role in roles
        ]
        != sorted(expected_role_order[role] for role in roles)
    ):
        raise ProtectedInvocationError("stage artifact topology differs")
    manifest = {
        "schema": STAGE_MANIFEST_SCHEMA,
        "artifacts": artifacts,
    }
    if stage["manifest_sha256"] != _compact_digest(manifest):
        raise ProtectedInvocationError("stage manifest hash differs")
    for field in (
        "protected_submit_stage_manifest_sha256",
        "protected_submit_stage_bundle_sha256",
    ):
        _sha(stage[field], f"stage.{field}")

    if document["operation_order"] != list(OPERATION_ORDER):
        raise ProtectedInvocationError("invocation operation order differs")
    if document["future_legacy_transaction_order"] != list(
        FUTURE_LEGACY_TRANSACTION_ORDER
    ):
        raise ProtectedInvocationError("future legacy transaction order differs")
    if document["scope"] != {
        "seal": True,
        "read_only_replay": True,
        "reserve": False,
        "stage": False,
        "submit": False,
        "status": False,
        "fetch": False,
        "cancel": False,
        "cleanup": False,
        "delete": False,
        "arbitrary_command": False,
    }:
        raise ProtectedInvocationError("protected invocation scope differs")
    if document["policy"] != {
        "future_single_legacy_transaction_only": True,
        "no_execution_authority": True,
        "no_reservation_acquired": True,
        "no_stage_materialization_performed": True,
        "no_ledger_lock_acquired": True,
        "no_ledger_write_performed": True,
        "no_external_action_performed": True,
        "automatic_retry": False,
        "automatic_cancel": False,
        "automatic_cleanup": False,
        "historical_migration": False,
        "legacy_cli_unchanged": True,
    }:
        raise ProtectedInvocationError("protected invocation policy differs")

    seed = digest(
        {
            "schema": "auto-g16-protected-invocation-id/1",
            "protected_submit_bundle_payload_sha256": protected[
                "bundle_payload_sha256"
            ],
            "local_state_binding_payload_sha256": local[
                "binding_payload_sha256"
            ],
            "stage_manifest_sha256": stage["manifest_sha256"],
            "ledger_identity_sha256": ledger["ledger_identity_sha256"],
        }
    )
    if document["invocation_id"] != f"protected-invocation-{seed}":
        raise ProtectedInvocationError("protected invocation ID binding differs")
    expected_payload = digest(
        {
            key: item
            for key, item in document.items()
            if key != "invocation_payload_sha256"
        }
    )
    if document["invocation_payload_sha256"] != expected_payload:
        raise ProtectedInvocationError("protected invocation payload hash differs")
    return copy.deepcopy(document)


@dataclass(frozen=True, slots=True)
class ProtectedInvocationEvidence:
    """One typed seal call; no path list, local_dir, command, or backend exists."""

    protected_submit_evidence: object
    local_state_evidence: object

    def snapshot(self) -> "ProtectedInvocationEvidence":
        return ProtectedInvocationEvidence(
            protected_submit_evidence=self.protected_submit_evidence,
            local_state_evidence=self.local_state_evidence,
        )


@dataclass(frozen=True, slots=True)
class _StageArtifact:
    role: str
    relative_name: str
    order: int
    data: bytes
    sha256: str
    size_bytes: int
    source_path: Path | None
    source_identity: tuple[tuple[str, int | str], ...] | None


@dataclass(frozen=True, slots=True, init=False)
class SealedLegacyStagePlan:
    """Exact source/generated bytes retained only inside this process."""

    schema: str
    manifest_sha256: str
    artifacts: tuple[_StageArtifact, ...]
    input_path: Path
    project: str
    resource_binding: tuple[tuple[str, Any], ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "SealedLegacyStagePlan":
        raise TypeError(
            "SealedLegacyStagePlan is issued only by the invocation owner"
        )

    @classmethod
    def _from_owner(
        cls,
        plan: dict[str, Any],
        *,
        input_path: Path,
        project: str,
        resource_binding: dict[str, Any],
        token: object,
    ) -> "SealedLegacyStagePlan":
        if token is not _SEAL_TOKEN:
            raise ProtectedInvocationError("legacy stage-plan seal differs")
        if (
            not isinstance(plan, dict)
            or set(plan) != {
                "schema",
                "manifest",
                "manifest_sha256",
                "artifacts",
            }
            or plan["schema"] != STAGE_PLAN_SCHEMA
            or not isinstance(plan["artifacts"], list)
        ):
            raise ProtectedInvocationError("legacy stage planner result differs")
        portable = plan["manifest"]
        if (
            not isinstance(portable, dict)
            or portable.get("schema") != STAGE_MANIFEST_SCHEMA
            or _compact_digest(portable) != plan["manifest_sha256"]
            or len(portable.get("artifacts", [])) != len(plan["artifacts"])
        ):
            raise ProtectedInvocationError("legacy stage manifest differs")
        artifacts: list[_StageArtifact] = []
        for metadata, raw in zip(
            portable["artifacts"],
            plan["artifacts"],
            strict=True,
        ):
            data = raw.get("bytes")
            if not isinstance(data, bytes):
                raise ProtectedInvocationError("stage artifact bytes differ")
            source_path = raw.get("source_path")
            source_identity = raw.get("source_identity")
            if source_path is not None and not isinstance(source_path, Path):
                raise ProtectedInvocationError("stage source path differs")
            frozen_identity = (
                tuple(sorted(source_identity.items()))
                if isinstance(source_identity, dict)
                else None
            )
            expected = {
                "role": raw.get("role"),
                "relative_name": raw.get("basename"),
                "order": metadata.get("order"),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
            if metadata != expected:
                raise ProtectedInvocationError(
                    "legacy stage bytes and manifest differ"
                )
            artifacts.append(
                _StageArtifact(
                    role=expected["role"],
                    relative_name=expected["relative_name"],
                    order=expected["order"],
                    data=data,
                    sha256=expected["sha256"],
                    size_bytes=expected["size_bytes"],
                    source_path=source_path,
                    source_identity=frozen_identity,
                )
            )
        value = object.__new__(cls)
        for name, item in {
            "schema": STAGE_PLAN_SCHEMA,
            "manifest_sha256": plan["manifest_sha256"],
            "artifacts": tuple(artifacts),
            "input_path": input_path,
            "project": project,
            "resource_binding": tuple(sorted(resource_binding.items())),
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def portable_artifacts(self) -> list[dict[str, Any]]:
        return [
            {
                "role": artifact.role,
                "relative_name": artifact.relative_name,
                "order": artifact.order,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in self.artifacts
        ]

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN or self.schema != STAGE_PLAN_SCHEMA:
            raise ProtectedInvocationError("legacy stage-plan seal differs")
        manifest = {
            "schema": STAGE_MANIFEST_SCHEMA,
            "artifacts": self.portable_artifacts(),
        }
        if _compact_digest(manifest) != self.manifest_sha256:
            raise ProtectedInvocationError("sealed stage manifest differs")
        for artifact in self.artifacts:
            if (
                hashlib.sha256(artifact.data).hexdigest() != artifact.sha256
                or len(artifact.data) != artifact.size_bytes
            ):
                raise ProtectedInvocationError("sealed stage bytes differ")

    def assert_current(self) -> "SealedLegacyStagePlan":
        self.assert_owner_sealed()
        _assert_stage_plan_current(self)
        return self


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedInvocationBundle:
    """Owner-issued portable closure plus exact in-process predecessor state."""

    _canonical_document: bytes
    protected_submit_bundle: object
    local_state_binding: object
    stage_plan: SealedLegacyStagePlan
    invocation_id: str
    invocation_payload_sha256: str
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedInvocationBundle":
        raise TypeError(
            "SealedProtectedInvocationBundle is issued only by its owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        protected_submit_bundle: object,
        local_state_binding: object,
        stage_plan: SealedLegacyStagePlan,
        *,
        token: object,
    ) -> "SealedProtectedInvocationBundle":
        if token is not _SEAL_TOKEN:
            raise ProtectedInvocationError("protected invocation seal differs")
        protected_submit_bundle.assert_owner_sealed()
        local_state_binding.assert_owner_sealed()
        stage_plan.assert_owner_sealed()
        validated = validate_protected_invocation_bundle(document)
        value = object.__new__(cls)
        for name, item in {
            "_canonical_document": canonical_bytes(validated),
            "protected_submit_bundle": protected_submit_bundle,
            "local_state_binding": local_state_binding,
            "stage_plan": stage_plan,
            "invocation_id": validated["invocation_id"],
            "invocation_payload_sha256": validated[
                "invocation_payload_sha256"
            ],
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise ProtectedInvocationError("protected invocation seal differs")
        self.protected_submit_bundle.assert_owner_sealed()
        self.local_state_binding.assert_owner_sealed()
        self.stage_plan.assert_owner_sealed()
        document = validate_protected_invocation_bundle(self.document())
        if (
            document["invocation_id"] != self.invocation_id
            or document["invocation_payload_sha256"]
            != self.invocation_payload_sha256
        ):
            raise ProtectedInvocationError(
                "protected invocation sealed projection differs"
            )

    def assert_current(self) -> "SealedProtectedInvocationBundle":
        """Read-only replay of active authority and retained local identities."""

        self.assert_owner_sealed()
        current = _utc_now()
        if (
            not isinstance(current, datetime)
            or current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise ProtectedInvocationError(
                "protected invocation replay clock must return aware UTC"
            )
        current = current.astimezone(timezone.utc)
        authority = self.protected_submit_bundle.document()["authority"]
        not_before = _utc_time(
            authority["not_before"],
            "protected invocation authority not_before",
        )
        expires_at = _utc_time(
            authority["expires_at"],
            "protected invocation authority expires_at",
        )
        if not_before > current or current >= expires_at:
            raise ProtectedInvocationError(
                "protected invocation predecessor authority is not current"
            )
        self.local_state_binding.assert_current()
        self.stage_plan.assert_current()
        return self


def _adjacent_path(name: str) -> Path:
    here = Path(__file__).resolve()
    path = here.with_name(f"{name}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(f"exact adjacent owner is unavailable: {path}")
    resolved = path.resolve()
    if resolved.parent != here.parent:
        raise ImportError(f"{name} owner is not adjacent")
    return resolved


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_spec = getattr(getattr(module, "__spec__", None), "origin", None)
    if (
        not isinstance(raw_file, str)
        or not raw_file
        or not isinstance(raw_spec, str)
        or not raw_spec
    ):
        raise ImportError("adjacent owner has no resolved origin")
    return Path(raw_file).resolve(), Path(raw_spec).resolve()


@contextlib.contextmanager
def _exact_adjacent(name: str) -> Iterator[types.ModuleType]:
    path = _adjacent_path(name)
    with _MODULE_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(name, _MISSING_MODULE)
        try:
            sys.modules.pop(name, None)
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"exact adjacent owner cannot load: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            if _module_origin(module) != (path, path):
                raise ImportError(f"{name} owner origin changed")
            yield module
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
            _imp.release_lock()


def _typed_evidence(
    module: types.ModuleType,
    type_name: str,
    evidence: object,
) -> object:
    expected_path = _adjacent_path(module.__name__)
    expected_type = getattr(module, type_name)
    if isinstance(evidence, expected_type):
        return evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    code = getattr(snapshot_method, "__code__", None)
    raw_source = getattr(code, "co_filename", None)
    if (
        not isinstance(raw_source, str)
        or Path(raw_source).resolve() != expected_path
    ):
        raise TypeError(
            f"{type_name} must come from the exact adjacent owner"
        )
    snapshot = evidence.snapshot()
    fields = tuple(expected_type.__dataclass_fields__)
    if any(not hasattr(snapshot, field) for field in fields):
        raise TypeError(f"{type_name} fields differ")
    return expected_type(
        **{field: getattr(snapshot, field) for field in fields}
    )


def _ledger_identity_sha256(binding: object) -> str:
    identity = binding.paths.ledger_identity
    fields = {
        name: getattr(identity, name)
        for name in (
            "device",
            "inode",
            "uid",
            "mode",
            "size",
            "mtime_ns",
            "ctime_ns",
            "sha256",
        )
    }
    return digest(
        {
            "schema": "auto-g16-ledger-file-identity/1",
            **fields,
        }
    )


def _stage_plan(
    protected: types.ModuleType,
    exact_protected_evidence: object,
    protected_document: dict[str, Any],
) -> SealedLegacyStagePlan:
    with protected._skill_owner_graph() as modules:
        legacy = modules["gaussian_rtwin_pbs"]
        input_path = Path(exact_protected_evidence.input_path)
        try:
            audit = legacy.parse_gaussian(input_path)
            sources = legacy._legacy_stage_source_paths(input_path, audit)
            resources = copy.deepcopy(protected_document["resources"])
            plan = legacy.plan_legacy_stage_bytes(
                project=protected_document["identity"]["project"],
                audit=audit,
                source_paths=sources,
                resource_binding=resources,
            )
        except SystemExit as exc:
            raise ProtectedInvocationError(
                "legacy stage validator blocked invocation sealing"
            ) from exc
        except Exception as exc:
            raise ProtectedInvocationError(
                f"legacy stage-byte owner rejected the closure: {exc}"
            ) from exc
    sealed = SealedLegacyStagePlan._from_owner(
        plan,
        input_path=input_path.resolve(),
        project=protected_document["identity"]["project"],
        resource_binding=resources,
        token=_SEAL_TOKEN,
    )
    input_artifact = sealed.artifacts[0]
    scheduler_binding = {
        "schema": "auto-g16-fixed-scheduler-submission-binding/1",
        "project": protected_document["identity"]["project"],
        "attempt_id": protected_document["identity"]["attempt_id"],
        "input_sha256": protected_document["identity"]["input_sha256"],
        "resource_tier": resources["resource_tier"],
        "cores": resources["cores"],
        "memory_gb": resources["memory_gb"],
        "walltime_seconds": resources["walltime_seconds"],
        "automatic_retry": False,
    }
    abstract_stage = protected._stage_binding(
        input_artifact.data,
        scheduler_binding,
    )
    if (
        input_artifact.sha256
        != protected_document["identity"]["input_sha256"]
        or abstract_stage != protected_document["stage"]
    ):
        raise ProtectedInvocationError(
            "full legacy stage bytes differ from PR4D stage evidence"
        )
    return sealed


def _assert_stage_plan_current(plan: SealedLegacyStagePlan) -> None:
    with _exact_adjacent("protected_submit_contract") as protected:
        with protected._skill_owner_graph() as modules:
            legacy = modules["gaussian_rtwin_pbs"]
            try:
                audit = legacy.parse_gaussian(plan.input_path)
                sources = legacy._legacy_stage_source_paths(
                    plan.input_path,
                    audit,
                )
                replay = legacy.plan_legacy_stage_bytes(
                    project=plan.project,
                    audit=audit,
                    source_paths=sources,
                    resource_binding=dict(plan.resource_binding),
                )
            except SystemExit as exc:
                raise ProtectedInvocationError(
                    "legacy stage replay blocked"
                ) from exc
            except Exception as exc:
                raise ProtectedInvocationError(
                    f"legacy stage replay failed closed: {exc}"
                ) from exc
    replay_seal = SealedLegacyStagePlan._from_owner(
        replay,
        input_path=plan.input_path,
        project=plan.project,
        resource_binding=dict(plan.resource_binding),
        token=_SEAL_TOKEN,
    )
    if replay_seal.artifacts != plan.artifacts:
        raise ProtectedInvocationError(
            "legacy stage source identity or bytes changed"
        )


class ProtectedInvocationContractOwner:
    """Compose all predecessor owners in one non-consuming typed call."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_SEAL_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError(
                "ProtectedInvocationContractOwner requires a fixed factory"
            )
        self._clock = clock
        self._testing = _factory_token is _TEST_OWNER_TOKEN

    @classmethod
    def production(cls) -> "ProtectedInvocationContractOwner":
        return cls(clock=_utc_now, _factory_token=_SEAL_TOKEN)

    @classmethod
    def _for_testing_with_clock(
        cls,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "ProtectedInvocationContractOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError("private invocation test factory token differs")
        return cls(clock=clock, _factory_token=_TEST_OWNER_TOKEN)

    def seal(
        self,
        evidence: ProtectedInvocationEvidence,
    ) -> SealedProtectedInvocationBundle:
        if not isinstance(evidence, ProtectedInvocationEvidence):
            raise ProtectedInvocationError(
                "protected invocation evidence must use the typed owner input"
            )
        snapshot = evidence.snapshot()
        local_snapshot_method = getattr(
            snapshot.local_state_evidence,
            "snapshot",
            None,
        )
        if not callable(local_snapshot_method):
            raise ProtectedInvocationError(
                "local-state evidence is not typed"
            )
        local_snapshot = local_snapshot_method()
        if (
            getattr(local_snapshot, "protected_submit_evidence", None)
            is not snapshot.protected_submit_evidence
        ):
            raise ProtectedInvocationError(
                "one invocation seal must reuse the exact same PR4D evidence "
                "inside PR4G evidence"
            )
        current = self._clock()
        if (
            not isinstance(current, datetime)
            or current.tzinfo is None
            or current.utcoffset() is None
        ):
            raise ProtectedInvocationError(
                "protected invocation owner clock must return aware UTC"
            )
        current = current.astimezone(timezone.utc)

        with _exact_adjacent("protected_submit_contract") as protected:
            exact_protected = _typed_evidence(
                protected,
                "ProtectedSubmitEvidence",
                snapshot.protected_submit_evidence,
            )
            try:
                protected_bundle = (
                    protected.ProtectedSubmitContractOwner.production()
                    ._seal_at(exact_protected, current)
                )
                protected_bundle.assert_owner_sealed()
                protected_document = protected_bundle.document()
            except Exception as exc:
                raise ProtectedInvocationError(
                    f"protected-submit owner rejected invocation evidence: {exc}"
                ) from exc

            with _exact_adjacent("local_state_binding") as local:
                exact_local = _typed_evidence(
                    local,
                    "LocalStateBindingEvidence",
                    snapshot.local_state_evidence,
                )
                try:
                    if self._testing:
                        local_owner = (
                            local.LocalStateBindingOwner
                            ._for_testing_with_clock(
                                lambda: current,
                                _test_token=local._TEST_OWNER_TOKEN,
                            )
                        )
                    else:
                        local_owner = local.LocalStateBindingOwner.production()
                    local_binding = local_owner.seal(exact_local)
                    local_binding.assert_owner_sealed()
                    local_binding.assert_current()
                    local_document = local_binding.document()
                except Exception as exc:
                    raise ProtectedInvocationError(
                        f"local-state owner rejected invocation evidence: {exc}"
                    ) from exc

            identity = protected_document["identity"]
            local_identity = local_document["identity"]
            if (
                local_identity
                != {
                    "project": identity["project"],
                    "attempt_id": identity["attempt_id"],
                    "scientific_task_id": identity[
                        "scientific_task_id"
                    ],
                    "input_sha256": identity["input_sha256"],
                    "idempotency_key_sha256": identity[
                        "idempotency_key_sha256"
                    ],
                }
                or local_document["protected_submit"][
                    "bundle_payload_sha256"
                ]
                != protected_document["bundle_payload_sha256"]
            ):
                raise ProtectedInvocationError(
                    "PR4D and PR4G owner identities differ"
                )
            local_ledger = local_document["ledger"]
            protected_execution = protected_document["execution"]
            if (
                local_ledger["schema"] != protected_execution["batch_schema"]
                or local_ledger["ledger_sha256"]
                != protected_execution["ledger_sha256"]
                or local_ledger["resource_state_revision"]
                != protected_execution["resource_state_revision"]
                or local_ledger["resource_state_sha256"]
                != protected_execution["resource_state_sha256"]
                or local_ledger["review_sha256"]
                != protected_execution["review_sha256"]
            ):
                raise ProtectedInvocationError(
                    "PR4G ledger differs from PR4D typed execution evidence"
                )
            stage_plan = _stage_plan(
                protected,
                exact_protected,
                protected_document,
            )

        ledger_identity_sha256 = _ledger_identity_sha256(local_binding)
        resources = copy.deepcopy(protected_document["resources"])
        resources["resource_binding_sha256"] = digest(resources)
        transport = protected_document["transport"]
        stage_artifacts = stage_plan.portable_artifacts()
        invocation_seed = digest(
            {
                "schema": "auto-g16-protected-invocation-id/1",
                "protected_submit_bundle_payload_sha256": protected_document[
                    "bundle_payload_sha256"
                ],
                "local_state_binding_payload_sha256": local_document[
                    "binding_payload_sha256"
                ],
                "stage_manifest_sha256": stage_plan.manifest_sha256,
                "ledger_identity_sha256": ledger_identity_sha256,
            }
        )
        document = finalize(
            {
                "schema": SCHEMA,
                "owner": OWNER,
                "invocation_id": f"protected-invocation-{invocation_seed}",
                "identity": {
                    "project": identity["project"],
                    "attempt_id": identity["attempt_id"],
                    "scientific_task_id": identity["scientific_task_id"],
                    "input_sha256": identity["input_sha256"],
                    "idempotency_key_sha256": identity[
                        "idempotency_key_sha256"
                    ],
                    "scientific_identity_sha256": identity[
                        "scientific_identity_sha256"
                    ],
                },
                "predecessors": {
                    "protected_submit": {
                        "schema": protected_document["schema"],
                        "bundle_payload_sha256": protected_document[
                            "bundle_payload_sha256"
                        ],
                    },
                    "local_state_binding": {
                        "schema": local_document["schema"],
                        "binding_payload_sha256": local_document[
                            "binding_payload_sha256"
                        ],
                    },
                },
                "local_state": {
                    "relative_local_dir": local_document["layout"][
                        "relative_local_dir"
                    ],
                    "ledger_basename": local_document["layout"][
                        "ledger_basename"
                    ],
                    "workspace_root_path_sha256": local_document[
                        "path_bindings"
                    ]["workspace_root_path_sha256"],
                    "local_dir_path_sha256": local_document[
                        "path_bindings"
                    ]["local_dir_path_sha256"],
                },
                "ledger": {
                    "schema": local_ledger["schema"],
                    "artifact_sha256": local_ledger["artifact_sha256"],
                    "artifact_size_bytes": local_ledger[
                        "artifact_size_bytes"
                    ],
                    "ledger_identity_sha256": ledger_identity_sha256,
                    "ledger_sha256": local_ledger["ledger_sha256"],
                    "revision": local_ledger["revision"],
                    "resource_state_revision": local_ledger[
                        "resource_state_revision"
                    ],
                    "resource_state_sha256": local_ledger[
                        "resource_state_sha256"
                    ],
                    "review_sha256": local_ledger["review_sha256"],
                },
                "resources": resources,
                "transport": {
                    "protected_transport_payload_sha256": digest(transport),
                    "authorization_sha256": transport[
                        "authorization_sha256"
                    ],
                    "successor_closure_sha256": transport[
                        "successor_closure_sha256"
                    ],
                    "handshake_receipt_sha256": transport[
                        "handshake_receipt_sha256"
                    ],
                },
                "stage_plan": {
                    "schema": stage_plan.schema,
                    "manifest_schema": STAGE_MANIFEST_SCHEMA,
                    "manifest_sha256": stage_plan.manifest_sha256,
                    "artifact_count": len(stage_artifacts),
                    "artifacts": stage_artifacts,
                    "protected_submit_stage_manifest_sha256": (
                        protected_document["stage"]["manifest_sha256"]
                    ),
                    "protected_submit_stage_bundle_sha256": (
                        protected_document["stage"]["bundle_sha256"]
                    ),
                },
                "operation_order": list(OPERATION_ORDER),
                "future_legacy_transaction_order": list(
                    FUTURE_LEGACY_TRANSACTION_ORDER
                ),
                "scope": {
                    "seal": True,
                    "read_only_replay": True,
                    "reserve": False,
                    "stage": False,
                    "submit": False,
                    "status": False,
                    "fetch": False,
                    "cancel": False,
                    "cleanup": False,
                    "delete": False,
                    "arbitrary_command": False,
                },
                "policy": {
                    "future_single_legacy_transaction_only": True,
                    "no_execution_authority": True,
                    "no_reservation_acquired": True,
                    "no_stage_materialization_performed": True,
                    "no_ledger_lock_acquired": True,
                    "no_ledger_write_performed": True,
                    "no_external_action_performed": True,
                    "automatic_retry": False,
                    "automatic_cancel": False,
                    "automatic_cleanup": False,
                    "historical_migration": False,
                    "legacy_cli_unchanged": True,
                },
                "invocation_payload_sha256": "",
            }
        )
        return SealedProtectedInvocationBundle._from_owner(
            document,
            protected_bundle,
            local_binding,
            stage_plan,
            token=_SEAL_TOKEN,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
