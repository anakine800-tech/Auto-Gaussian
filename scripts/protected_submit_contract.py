#!/usr/bin/env python3
"""Owner-sealed, non-executable protected-submit contract for Auto-G16 v2.6.

The module composes existing owners. It does not implement transport, staging,
scheduler submission, retry, cancellation, cleanup, deletion, or reconciliation.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping


SCHEMA = "auto-g16-protected-submit-bundle/1"
OWNER = "auto-g16-protected-submit-contract"
STAGE_SCHEMA = "auto-g16-immutable-stage-bundle/1"
FIXED_REMOTE_ROOT = "/home/user100/SDL"
OPERATION_ORDER = ("reserve_once", "stage_exact_bundle", "submit_once")
ARTIFACT_ORDER = (
    "exact_gaussian_input",
    "fixed_scheduler_submission_binding",
)
SUPPORTED_INPUT_APPROVALS = {
    "gaussian-input-approval-receipt/1",
    "gaussian-input-approval-receipt/2",
    "gaussian-input-approval-receipt/3",
}
SUPPORTED_LIVE_APPROVALS = {
    "auto-g16-live-submission-approval/9",
    "auto-g16-live-submission-approval/10",
    "auto-g16-live-submission-approval/11",
}
UNRESOLVED_ATTEMPT_STATES = {
    "submission_uncertain",
    "submitted",
    "queued",
    "running",
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
TASK_RE = re.compile(r"^scientific-task-[a-f0-9]{64}$")
ATTEMPT_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
OWNER_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
BUNDLE_ID_RE = re.compile(r"^protected-submit-[a-f0-9]{64}$")
TIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
_SEAL_TOKEN = object()
_RESERVATION_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_GRAPH_LOCK = threading.RLock()
_RUNTIME_ENVIRONMENT_NAMES = (
    "AUTO_G16_RUNTIME_CONFIG",
    "AUTO_G16_RTWIN_SSH_CONFIG",
    "GAUSSIAN_RTWIN_SSH_CONFIG",
    "AUTO_G16_WINDOWS_PROJECT_ROOT",
    "AUTO_G16_WINDOWS_SERVER_CONFIG",
)
_MISSING_ENVIRONMENT = object()
_MISSING_MODULE = object()


class ProtectedSubmitError(ValueError):
    """The exact protected-submit closure cannot be proved."""


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


def _reject_json_constant(token: str) -> None:
    raise ProtectedSubmitError(
        f"scheduler snapshot contains non-standard number {token}"
    )


def _closed_json_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtectedSubmitError(
                f"scheduler snapshot contains duplicate key {key}"
            )
        result[key] = value
    return result


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProtectedSubmitError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or value == "":
        raise ProtectedSubmitError(f"{label} must be a non-empty string")
    return value


def _sha(value: Any, label: str) -> str:
    value = _nonempty(value, label)
    if SHA_RE.fullmatch(value) is None:
        raise ProtectedSubmitError(f"{label} must be a lowercase SHA-256")
    return value


def _draft_integer(value: Any, label: str, *, minimum: int) -> int:
    if isinstance(value, bool):
        raise ProtectedSubmitError(f"{label} must be a Draft integer")
    if isinstance(value, int):
        canonical = value
    elif isinstance(value, float) and value.is_integer():
        canonical = int(value)
    else:
        raise ProtectedSubmitError(f"{label} must be a Draft integer")
    if canonical < minimum:
        raise ProtectedSubmitError(
            f"{label} must be at least {minimum}"
        )
    return canonical


def _positive_integer(value: Any, label: str) -> int:
    return _draft_integer(value, label, minimum=1)


def _canonicalize_portable_integers(
    document: dict[str, Any],
) -> dict[str, Any]:
    """Normalize Draft-integral JSON numbers before portable self-hashing."""

    def normalize(value: Any) -> Any:
        if (
            not isinstance(value, bool)
            and isinstance(value, float)
            and value.is_integer()
        ):
            return int(value)
        return value

    execution = document.get("execution")
    if isinstance(execution, dict) and "resource_state_revision" in execution:
        execution["resource_state_revision"] = normalize(
            execution["resource_state_revision"]
        )
    resources = document.get("resources")
    if isinstance(resources, dict):
        for field in ("cores", "memory_gb", "walltime_seconds"):
            if field in resources:
                resources[field] = normalize(resources[field])
    stage = document.get("stage")
    if isinstance(stage, dict) and "artifact_count" in stage:
        stage["artifact_count"] = normalize(stage["artifact_count"])
    return document


def _time(value: Any, label: str) -> datetime:
    value = _nonempty(value, label)
    if TIME_RE.fullmatch(value) is None:
        raise ProtectedSubmitError(
            f"{label} must be canonical second-precision UTC ending in Z"
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ProtectedSubmitError(
            f"{label} is not a real calendar timestamp"
        ) from exc
    return parsed


def _trusted_now(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProtectedSubmitError(
            "protected-submit owner clock must return timezone-aware UTC"
        )
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@contextlib.contextmanager
def _isolated_owner_environment() -> Iterator[None]:
    """Prevent contract replay from reading caller machine configuration."""

    saved: dict[str, str | object] = {
        name: os.environ.get(name, _MISSING_ENVIRONMENT)
        for name in _RUNTIME_ENVIRONMENT_NAMES
    }
    temporary_parent = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(
        prefix="auto-g16-protected-submit-config-",
        dir=temporary_parent,
    ) as temporary:
        for name in _RUNTIME_ENVIRONMENT_NAMES:
            os.environ.pop(name, None)
        os.environ["AUTO_G16_RUNTIME_CONFIG"] = str(
            Path(temporary) / "intentionally-absent-runtime.json"
        )
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is _MISSING_ENVIRONMENT:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = str(value)


@contextlib.contextmanager
def _bind_existing_owner_clock(
    owner_module: ModuleType,
    trusted_now: datetime,
) -> Iterator[None]:
    """Make the existing live-approval owner use the enclosing trusted UTC."""

    original = owner_module.datetime

    class _OwnerDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            value = trusted_now
            if tz is None:
                return value.replace(tzinfo=None)
            return value.astimezone(tz)

    owner_module.datetime = _OwnerDateTime
    try:
        yield
    finally:
        owner_module.datetime = original


def finalize(document: dict[str, Any]) -> dict[str, Any]:
    result = _canonicalize_portable_integers(copy.deepcopy(document))
    result["bundle_payload_sha256"] = digest(
        {key: value for key, value in result.items() if key != "bundle_payload_sha256"}
    )
    return result


def validate_protected_submit_bundle(value: Any) -> dict[str, Any]:
    """Validate the portable closed topology; this does not issue an owner seal."""

    document = _exact(
        copy.deepcopy(value),
        {
            "schema",
            "owner",
            "bundle_id",
            "identity",
            "workspace",
            "approvals",
            "execution",
            "resources",
            "transport",
            "stage",
            "operation_order",
            "authority",
            "failure_policy",
            "evidence_status",
            "bundle_payload_sha256",
        },
        "protected-submit bundle",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedSubmitError("protected-submit schema/owner differs")
    if (
        not isinstance(document["bundle_id"], str)
        or BUNDLE_ID_RE.fullmatch(document["bundle_id"]) is None
    ):
        raise ProtectedSubmitError("protected-submit bundle_id is malformed")

    identity = _exact(
        document["identity"],
        {
            "project",
            "scientific_task_id",
            "attempt_id",
            "input_sha256",
            "idempotency_key_sha256",
            "scientific_identity_sha256",
        },
        "protected-submit identity",
    )
    if (
        not isinstance(identity["project"], str)
        or PROJECT_RE.fullmatch(identity["project"]) is None
        or not isinstance(identity["scientific_task_id"], str)
        or TASK_RE.fullmatch(identity["scientific_task_id"]) is None
        or not isinstance(identity["attempt_id"], str)
        or ATTEMPT_RE.fullmatch(identity["attempt_id"]) is None
    ):
        raise ProtectedSubmitError("protected-submit identity is malformed")
    for field in (
        "input_sha256",
        "idempotency_key_sha256",
        "scientific_identity_sha256",
    ):
        _sha(identity[field], f"identity.{field}")

    workspace = _exact(
        document["workspace"],
        {
            "allowed_root",
            "workspace_binding_sha256",
            "fresh_project_required",
            "no_overwrite",
            "no_symlink",
            "no_delete",
            "root_override_allowed",
        },
        "protected-submit workspace",
    )
    if workspace != {
        "allowed_root": FIXED_REMOTE_ROOT,
        "workspace_binding_sha256": workspace.get("workspace_binding_sha256"),
        "fresh_project_required": True,
        "no_overwrite": True,
        "no_symlink": True,
        "no_delete": True,
        "root_override_allowed": False,
    }:
        raise ProtectedSubmitError("protected-submit workspace policy differs")
    _sha(workspace["workspace_binding_sha256"], "workspace binding")

    approvals = _exact(
        document["approvals"],
        {
            "scientific_task_owner",
            "input_approval",
            "live_submission_approval",
        },
        "protected-submit approvals",
    )
    if approvals["scientific_task_owner"] != "auto-g16-rtwin-pbs":
        raise ProtectedSubmitError("scientific-task owner differs")
    input_approval = _exact(
        approvals["input_approval"],
        {"schema", "artifact_sha256", "payload_sha256"},
        "protected-submit input approval",
    )
    if (
        not isinstance(input_approval["schema"], str)
        or input_approval["schema"] not in SUPPORTED_INPUT_APPROVALS
    ):
        raise ProtectedSubmitError("input-approval schema is unsupported")
    _sha(input_approval["artifact_sha256"], "input approval artifact")
    _sha(input_approval["payload_sha256"], "input approval payload")
    live_approval = _exact(
        approvals["live_submission_approval"],
        {
            "schema",
            "approval_id",
            "artifact_sha256",
            "not_before",
            "expires_at",
        },
        "protected-submit live approval",
    )
    if (
        not isinstance(live_approval["schema"], str)
        or live_approval["schema"] not in SUPPORTED_LIVE_APPROVALS
    ):
        raise ProtectedSubmitError("live-approval schema is unsupported")
    _nonempty(live_approval["approval_id"], "live approval id")
    _sha(live_approval["artifact_sha256"], "live approval artifact")
    _time(live_approval["not_before"], "live approval not_before")
    _time(live_approval["expires_at"], "live approval expires_at")

    execution = _exact(
        document["execution"],
        {
            "batch_schema",
            "batch_id",
            "review_sha256",
            "ledger_sha256",
            "resource_state_revision",
            "resource_state_sha256",
        },
        "protected-submit execution",
    )
    if execution["batch_schema"] != "gaussian-execution-batch/3":
        raise ProtectedSubmitError("protected submit requires execution batch /3")
    _nonempty(execution["batch_id"], "execution batch id")
    _sha(execution["review_sha256"], "execution review")
    _sha(execution["ledger_sha256"], "execution ledger")
    execution["resource_state_revision"] = _draft_integer(
        execution["resource_state_revision"],
        "resource-state revision",
        minimum=0,
    )
    _sha(execution["resource_state_sha256"], "resource state")

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
        },
        "protected-submit resources",
    )
    _nonempty(resources["policy_id"], "resource policy id")
    _sha(resources["policy_sha256"], "resource policy")
    _nonempty(resources["gate_id"], "resource gate id")
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
        raise ProtectedSubmitError("resource tier is unsupported")
    for field in ("cores", "memory_gb", "walltime_seconds"):
        resources[field] = _positive_integer(
            resources[field],
            f"resources.{field}",
        )

    transport = _exact(
        document["transport"],
        {
            "authorization_id",
            "authorization_sha256",
            "successor_closure_sha256",
            "profile_sha256",
            "identity_binding_sha256",
            "transport_config_bindings_sha256",
            "handshake_receipt_sha256",
        },
        "protected-submit transport",
    )
    if (
        not isinstance(transport["authorization_id"], str)
        or OWNER_ID_RE.fullmatch(transport["authorization_id"]) is None
    ):
        raise ProtectedSubmitError("transport authorization id is malformed")
    for field in set(transport) - {"authorization_id"}:
        _sha(transport[field], f"transport.{field}")

    stage = _exact(
        document["stage"],
        {
            "manifest_schema",
            "manifest_sha256",
            "bundle_sha256",
            "artifact_count",
            "artifact_order",
        },
        "protected-submit stage",
    )
    stage["artifact_count"] = _draft_integer(
        stage["artifact_count"],
        "stage artifact count",
        minimum=0,
    )
    if (
        stage["manifest_schema"] != STAGE_SCHEMA
        or stage["artifact_count"] != 2
        or stage["artifact_order"] != list(ARTIFACT_ORDER)
    ):
        raise ProtectedSubmitError("immutable stage topology differs")
    _sha(stage["manifest_sha256"], "stage manifest")
    _sha(stage["bundle_sha256"], "stage bundle")
    if document["operation_order"] != list(OPERATION_ORDER):
        raise ProtectedSubmitError("protected-submit operation order differs")

    authority = _exact(
        document["authority"],
        {
            "authority_nonce",
            "not_before",
            "expires_at",
            "single_use",
            "consumed",
            "automatic_retry",
            "scope",
        },
        "protected-submit authority",
    )
    _sha(authority["authority_nonce"], "protected-submit authority nonce")
    _time(authority["not_before"], "protected-submit not_before")
    _time(authority["expires_at"], "protected-submit expires_at")
    if (
        authority["single_use"] is not True
        or authority["consumed"] is not False
        or authority["automatic_retry"] is not False
    ):
        raise ProtectedSubmitError("protected-submit lifecycle differs")
    scope = _exact(
        authority["scope"],
        {
            "stage",
            "submit",
            "status",
            "fetch",
            "cancel",
            "cleanup",
            "delete",
            "arbitrary_command",
        },
        "protected-submit scope",
    )
    if scope != {
        "stage": True,
        "submit": True,
        "status": False,
        "fetch": False,
        "cancel": False,
        "cleanup": False,
        "delete": False,
        "arbitrary_command": False,
    }:
        raise ProtectedSubmitError("protected-submit scope differs")

    if document["failure_policy"] != {
        "post_reservation_state": "submission_uncertain",
        "reconciliation": "existing_read_only_reconciliation_only",
        "automatic_retry": False,
        "automatic_cancel": False,
        "automatic_cleanup": False,
    }:
        raise ProtectedSubmitError("protected-submit failure policy differs")
    if document["evidence_status"] != {
        "code_support": True,
        "offline_contract_validation": True,
        "actual_adapter_verified": False,
        "live_validation_performed": False,
        "external_actions_performed": False,
    }:
        raise ProtectedSubmitError("protected-submit evidence status differs")
    _sha(document["bundle_payload_sha256"], "protected-submit bundle payload")
    if document["bundle_payload_sha256"] != digest(
        {key: item for key, item in document.items() if key != "bundle_payload_sha256"}
    ):
        raise ProtectedSubmitError("protected-submit bundle payload hash differs")
    return copy.deepcopy(document)


@dataclass(frozen=True, slots=True)
class ProtectedSubmitEvidence:
    """Raw seal-time sources. They are never serialized into the contract."""

    input_path: Path
    input_approval_path: Path
    live_approval_path: Path
    execution_ledger: Mapping[str, Any]
    resource_policy: Mapping[str, Any]
    resource_gate: Mapping[str, Any]
    scheduler_snapshot: Mapping[str, Any]
    scheduler_snapshot_artifact: bytes
    project: str
    scientific_task_id: str
    idempotency_key: str
    estimated_core_hours_evidence: Mapping[str, str]
    work_kind: str
    transport_artifacts: Mapping[str, Mapping[str, Any]]

    def snapshot(self) -> "ProtectedSubmitEvidence":
        return ProtectedSubmitEvidence(
            input_path=Path(self.input_path),
            input_approval_path=Path(self.input_approval_path),
            live_approval_path=Path(self.live_approval_path),
            execution_ledger=copy.deepcopy(dict(self.execution_ledger)),
            resource_policy=copy.deepcopy(dict(self.resource_policy)),
            resource_gate=copy.deepcopy(dict(self.resource_gate)),
            scheduler_snapshot=copy.deepcopy(dict(self.scheduler_snapshot)),
            scheduler_snapshot_artifact=bytes(
                self.scheduler_snapshot_artifact
            ),
            project=self.project,
            scientific_task_id=self.scientific_task_id,
            idempotency_key=self.idempotency_key,
            estimated_core_hours_evidence=copy.deepcopy(
                dict(self.estimated_core_hours_evidence)
            ),
            work_kind=self.work_kind,
            transport_artifacts=copy.deepcopy(dict(self.transport_artifacts)),
        )


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedSubmitBundle:
    """Immutable in-process capability issued only by complete owner replay."""

    _canonical_document: bytes
    bundle_id: str
    bundle_payload_sha256: str
    attempt_id: str
    idempotency_key_sha256: str
    authority_nonce: str
    attestation_nonces: tuple[str, ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "SealedProtectedSubmitBundle":
        raise TypeError(
            "SealedProtectedSubmitBundle is issued only by the protected-submit owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        attestation_nonces: tuple[str, ...],
        *,
        token: object,
    ) -> "SealedProtectedSubmitBundle":
        if token is not _SEAL_TOKEN:
            raise ProtectedSubmitError("protected-submit seal factory differs")
        validated = validate_protected_submit_bundle(document)
        value = object.__new__(cls)
        for name, item in {
            "_canonical_document": canonical_bytes(validated),
            "bundle_id": validated["bundle_id"],
            "bundle_payload_sha256": validated["bundle_payload_sha256"],
            "attempt_id": validated["identity"]["attempt_id"],
            "idempotency_key_sha256": validated["identity"][
                "idempotency_key_sha256"
            ],
            "authority_nonce": validated["authority"]["authority_nonce"],
            "attestation_nonces": attestation_nonces,
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise ProtectedSubmitError("protected-submit bundle seal differs")
        document = validate_protected_submit_bundle(self.document())
        if (
            document["bundle_id"] != self.bundle_id
            or document["bundle_payload_sha256"] != self.bundle_payload_sha256
            or document["identity"]["attempt_id"] != self.attempt_id
            or document["identity"]["idempotency_key_sha256"]
            != self.idempotency_key_sha256
            or document["authority"]["authority_nonce"] != self.authority_nonce
        ):
            raise ProtectedSubmitError("protected-submit sealed projection differs")


@dataclass(frozen=True, slots=True, init=False)
class ReservedProtectedSubmitBundle:
    """Effect-preceding reservation; no effect method is provided."""

    bundle: SealedProtectedSubmitBundle
    consumption_sha256: str
    consumed_at: str
    submission_state: str
    automatic_retry: bool
    reconciliation: str
    _seal: object

    def __new__(
        cls, *args: Any, **kwargs: Any
    ) -> "ReservedProtectedSubmitBundle":
        raise TypeError(
            "ReservedProtectedSubmitBundle is issued only after trusted reservation"
        )

    @classmethod
    def _from_owner(
        cls,
        bundle: SealedProtectedSubmitBundle,
        consumption: object,
        *,
        token: object,
    ) -> "ReservedProtectedSubmitBundle":
        if token is not _RESERVATION_TOKEN:
            raise ProtectedSubmitError("protected-submit reservation factory differs")
        bundle.assert_owner_sealed()
        if (
            getattr(consumption, "consumed", None) is not True
            or getattr(consumption, "authorization_id", None) != bundle.bundle_id
            or getattr(consumption, "attempt_id", None) != bundle.attempt_id
            or getattr(consumption, "submission_state", None)
            != "submission_uncertain"
        ):
            raise ProtectedSubmitError("trusted reservation result differs")
        value = object.__new__(cls)
        for name, item in {
            "bundle": bundle,
            "consumption_sha256": getattr(consumption, "consumption_sha256"),
            "consumed_at": getattr(consumption, "consumed_at"),
            "submission_state": "submission_uncertain",
            "automatic_retry": False,
            "reconciliation": "existing_read_only_reconciliation_only",
            "_seal": _RESERVATION_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        self.bundle.assert_owner_sealed()
        if (
            self._seal is not _RESERVATION_TOKEN
            or not SHA_RE.fullmatch(self.consumption_sha256)
            or self.submission_state != "submission_uncertain"
            or self.automatic_retry is not False
            or self.reconciliation != "existing_read_only_reconciliation_only"
        ):
            raise ProtectedSubmitError("reserved protected-submit state differs")
        _time(self.consumed_at, "protected-submit consumed_at")


def _repository_skill_scripts() -> Path:
    here = Path(__file__).resolve().parent
    packaged = here / "execution_batch.py"
    if packaged.is_file() and not packaged.is_symlink():
        return here
    candidate = (
        here.parent
        / "skills"
        / "auto-g16-rtwin-pbs"
        / "scripts"
    )
    if not candidate.is_dir() or candidate.is_symlink():
        raise ImportError("auto-g16-rtwin-pbs owner scripts are unavailable")
    return candidate.resolve()


def _load_state_owner_module() -> ModuleType:
    directory = _repository_skill_scripts()
    path = directory / "execution_authorization_state.py"
    if not path.is_file() or path.is_symlink():
        raise ImportError("trusted authorization state owner is unavailable")
    name = (
        "_auto_g16_protected_submit_state_"
        + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    )
    with _GRAPH_LOCK:
        previous = sys.modules.get(name, _MISSING_MODULE)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("trusted authorization state owner cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
    if Path(module.__file__).resolve() != path.resolve():
        raise ImportError("trusted authorization state owner origin changed")
    return module


@contextlib.contextmanager
def _skill_owner_graph() -> Iterator[dict[str, ModuleType]]:
    """Load the exact existing owner graph and restore all same-name modules."""

    names = (
        "runtime_config",
        "protocol_selection",
        "gaussian_log",
        "execution_batch",
        "resource_efficiency",
        "execution_models",
        "gaussian_rtwin_pbs",
        "execution_authorization_state",
    )
    directory = _repository_skill_scripts()
    with _GRAPH_LOCK:
        saved = {
            name: sys.modules.get(name, _MISSING_MODULE)
            for name in names
        }
        old_path = list(sys.path)
        try:
            with _isolated_owner_environment():
                for name in names:
                    sys.modules.pop(name, None)
                sys.path.insert(0, str(directory))
                modules: dict[str, ModuleType] = {}
                for name in names:
                    module = importlib.import_module(name)
                    expected = (directory / f"{name}.py").resolve()
                    if Path(module.__file__).resolve() != expected:
                        raise ImportError(f"{name} owner origin changed")
                    modules[name] = module
                yield modules
        finally:
            sys.path[:] = old_path
            for name in names:
                sys.modules.pop(name, None)
                previous = saved[name]
                if previous is not _MISSING_MODULE:
                    sys.modules[name] = previous


def _load_transport_owner() -> ModuleType:
    path = Path(__file__).resolve().with_name("transport_authority_closure.py")
    if not path.is_file() or path.is_symlink():
        raise ImportError("transport authority owner is unavailable")
    name = (
        "_auto_g16_protected_submit_transport_"
        + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    )
    with _GRAPH_LOCK:
        previous = sys.modules.get(name, _MISSING_MODULE)
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("transport authority owner cannot be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            with _isolated_owner_environment():
                spec.loader.exec_module(module)
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
    if Path(module.__file__).resolve() != path.resolve():
        raise ImportError("transport authority owner origin changed")
    return module


def _transport_snapshot(value: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    expected = {
        "successor_request",
        "successor_authorization",
        "base_request",
        "base_authorization",
        "profile_v1",
        "profile_v2",
        "identity_binding",
        "first_hop_request",
        "first_hop_receipt",
        "nested_hop_request",
        "nested_hop_receipt",
        "handshake_request",
        "handshake_observation",
        "handshake_receipt",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProtectedSubmitError(
            f"transport artifacts must contain exactly {sorted(expected)}"
        )
    result: dict[str, Any] = {}
    for name in sorted(expected):
        item = value[name]
        if not isinstance(item, Mapping):
            raise ProtectedSubmitError(f"transport artifact {name} must be a mapping")
        result[name] = copy.deepcopy(dict(item))
    return result


def _stage_binding(
    input_bytes: bytes,
    scheduler_binding: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(input_bytes, bytes) or not input_bytes:
        raise ProtectedSubmitError("exact Gaussian input bytes are unavailable")
    scheduler_bytes = canonical_bytes(dict(scheduler_binding))
    artifacts = [
        {
            "role": ARTIFACT_ORDER[0],
            "sha256": hashlib.sha256(input_bytes).hexdigest(),
            "size_bytes": len(input_bytes),
        },
        {
            "role": ARTIFACT_ORDER[1],
            "sha256": hashlib.sha256(scheduler_bytes).hexdigest(),
            "size_bytes": len(scheduler_bytes),
        },
    ]
    manifest = {
        "schema": STAGE_SCHEMA,
        "artifact_order": list(ARTIFACT_ORDER),
        "artifacts": artifacts,
    }
    bundle_bytes = b"auto-g16-immutable-stage-bundle-bytes/1\0"
    for role, payload in zip(
        ARTIFACT_ORDER,
        (input_bytes, scheduler_bytes),
        strict=True,
    ):
        encoded_role = role.encode("ascii")
        bundle_bytes += (
            len(encoded_role).to_bytes(4, "big")
            + encoded_role
            + len(payload).to_bytes(8, "big")
            + payload
        )
    return {
        "manifest_schema": STAGE_SCHEMA,
        "manifest_sha256": digest(manifest),
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "artifact_count": len(artifacts),
        "artifact_order": list(ARTIFACT_ORDER),
    }


def _replay_transport(
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    now: datetime,
    project: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    snapshot = _transport_snapshot(artifacts)
    with _GRAPH_LOCK, _isolated_owner_environment():
        owner = _load_transport_owner()
        closure = owner.validate_successor_closure(
            successor_request=snapshot["successor_request"],
            successor_authorization=snapshot["successor_authorization"],
            base_request=snapshot["base_request"],
            base_authorization=snapshot["base_authorization"],
            profile_v1=snapshot["profile_v1"],
            profile_v2=snapshot["profile_v2"],
            identity_binding=snapshot["identity_binding"],
            now=now,
        )
        receipt = owner.validate_handshake_authority_binding(
            successor_closure=closure,
            request=snapshot["handshake_request"],
            observation=snapshot["handshake_observation"],
            receipt=snapshot["handshake_receipt"],
            first_hop_request=snapshot["first_hop_request"],
            first_hop_receipt=snapshot["first_hop_receipt"],
            nested_hop_request=snapshot["nested_hop_request"],
            nested_hop_receipt=snapshot["nested_hop_receipt"],
            now=now,
        )
    authorization = snapshot["successor_authorization"]
    if authorization["project"] != project:
        raise ProtectedSubmitError(
            "transport authority project differs from protected submit"
        )
    operations = authorization["identity_attestation"]["operations"]
    nonces = tuple(item["request_nonce"] for item in operations)
    if len(nonces) != 3 or len(set(nonces)) != 3:
        raise ProtectedSubmitError("transport attestation nonces differ")
    return (
        {
            "authorization_id": authorization["authorization_id"],
            "authorization_sha256": authorization[
                "authorization_payload_sha256"
            ],
            "successor_closure_sha256": closure.payload_sha256,
            "profile_sha256": snapshot["profile_v2"]["profile_payload_sha256"],
            "identity_binding_sha256": snapshot["identity_binding"][
                "binding_payload_sha256"
            ],
            "transport_config_bindings_sha256": snapshot["profile_v2"][
                "transport_config_bindings"
            ]["bindings_payload_sha256"],
            "handshake_receipt_sha256": receipt["receipt_payload_sha256"],
        },
        nonces,
    )


class ProtectedSubmitContractOwner:
    """Compose and atomically reserve the exact protected-submit authority."""

    def __init__(
        self,
        state_owner: object,
        *,
        preflight_clock: Callable[[], datetime],
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_SEAL_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError(
                "ProtectedSubmitContractOwner requires a fixed owner factory"
            )
        self._state_owner = state_owner
        self._preflight_clock = preflight_clock

    @classmethod
    def production(cls) -> "ProtectedSubmitContractOwner":
        state = _load_state_owner_module()
        state_owner = state.TrustedAuthorizationStateOwner()
        return cls(
            state_owner,
            preflight_clock=_utc_now,
            _factory_token=_SEAL_TOKEN,
        )

    @classmethod
    def _for_testing_with_clock(
        cls,
        state_root: Path,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "ProtectedSubmitContractOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError("private protected-submit test factory token differs")
        state = _load_state_owner_module()
        state_owner = state.TrustedAuthorizationStateOwner._for_testing_with_clock(
            state_root,
            clock,
            _test_token=state._TEST_CLOCK_FACTORY_TOKEN,
        )
        return cls(
            state_owner,
            preflight_clock=clock,
            _factory_token=_TEST_OWNER_TOKEN,
        )

    def _seal_at(
        self,
        evidence: ProtectedSubmitEvidence,
        now: datetime,
    ) -> SealedProtectedSubmitBundle:
        if not isinstance(evidence, ProtectedSubmitEvidence):
            raise ProtectedSubmitError(
                "protected-submit evidence must use the typed owner input"
            )
        snapshot = evidence.snapshot()
        current = _trusted_now(now)
        if (
            not isinstance(snapshot.project, str)
            or PROJECT_RE.fullmatch(snapshot.project) is None
        ):
            raise ProtectedSubmitError("protected-submit project is malformed")
        if (
            not isinstance(snapshot.scientific_task_id, str)
            or TASK_RE.fullmatch(snapshot.scientific_task_id) is None
        ):
            raise ProtectedSubmitError("scientific task id is malformed")
        idempotency_key = _nonempty(
            snapshot.idempotency_key, "protected-submit idempotency key"
        )
        idempotency_key_sha256 = hashlib.sha256(
            idempotency_key.encode("utf-8")
        ).hexdigest()
        scheduler_snapshot_bytes = snapshot.scheduler_snapshot_artifact
        if not isinstance(scheduler_snapshot_bytes, bytes) or not scheduler_snapshot_bytes:
            raise ProtectedSubmitError(
                "scheduler snapshot artifact bytes are unavailable"
            )
        scheduler_artifact_sha256 = hashlib.sha256(
            scheduler_snapshot_bytes
        ).hexdigest()
        scheduler_artifact_size = len(scheduler_snapshot_bytes)
        try:
            parsed_scheduler_snapshot = json.loads(
                scheduler_snapshot_bytes.decode("utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_closed_json_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtectedSubmitError(
                "scheduler snapshot artifact is not strict UTF-8 JSON"
            ) from exc
        if parsed_scheduler_snapshot != dict(snapshot.scheduler_snapshot):
            raise ProtectedSubmitError(
                "scheduler snapshot artifact bytes differ from the supplied document"
            )

        with _skill_owner_graph() as modules:
            batch_owner = modules["execution_batch"]
            resource_owner = modules["resource_efficiency"]
            input_owner = modules["gaussian_rtwin_pbs"]
            try:
                ledger = resource_owner.validate_ledger(
                    copy.deepcopy(dict(snapshot.execution_ledger))
                )
                policy = resource_owner.validate_policy(
                    copy.deepcopy(dict(snapshot.resource_policy))
                )
                gate = resource_owner._validate_gate_binding(
                    copy.deepcopy(dict(snapshot.resource_gate)),
                    allow_historical=False,
                )
                scheduler = resource_owner.validate_scheduler_snapshot(
                    copy.deepcopy(dict(snapshot.scheduler_snapshot)),
                    now=current.isoformat().replace("+00:00", "Z"),
                )
            except Exception as exc:
                raise ProtectedSubmitError(
                    f"execution/resource owner rejected the closure: {exc}"
                ) from exc

            if ledger["schema"] != resource_owner.LEDGER_SCHEMA:
                raise ProtectedSubmitError(
                    "protected submit requires execution batch /3"
                )
            task = next(
                (
                    item
                    for item in ledger["tasks"]
                    if item["scientific_task_id"]
                    == snapshot.scientific_task_id
                ),
                None,
            )
            if task is None or task["state"] != "reviewed":
                raise ProtectedSubmitError(
                    "protected submit requires the exact currently reviewed scientific task"
                )
            input_sha256 = task["identity"]["relevant_input_sha256"]
            attempt_id = batch_owner.attempt_id_for(
                ledger["batch"]["batch_id"], idempotency_key
            )
            if (
                any(
                    item["attempt_id"] == attempt_id
                    or item["idempotency_key"] == idempotency_key
                    for item in ledger["attempts"]
                )
                or any(
                    item["scientific_task_id"] == snapshot.scientific_task_id
                    and item["state"] in UNRESOLVED_ATTEMPT_STATES
                    for item in ledger["attempts"]
                )
            ):
                raise ProtectedSubmitError(
                    "execution batch already has a conflicting or unresolved attempt"
                )
            if (
                gate["status"] != "passed"
                or gate["policy_id"] != policy["policy_id"]
                or gate["policy_sha256"] != policy["payload_sha256"]
                or gate["resource_state_sha256"]
                != ledger["resource_state_sha256"]
                or gate["resource_state_revision"]
                != ledger["resource_state_revision"]
                or gate["execution_scope"]
                != {
                    "scientific_task_id": snapshot.scientific_task_id,
                    "attempt_id": attempt_id,
                    "project": snapshot.project,
                    "input_sha256": input_sha256,
                }
            ):
                raise ProtectedSubmitError(
                    "resource gate differs from the exact execution closure"
                )
            scheduler_binding = gate["scheduler_snapshot"]
            if (
                scheduler_binding["snapshot_id"] != scheduler["snapshot_id"]
                or scheduler_binding["payload_sha256"]
                != scheduler["payload_sha256"]
                or scheduler_binding["artifact_sha256"]
                != scheduler_artifact_sha256
                or scheduler_binding["artifact_size"]
                != scheduler_artifact_size
            ):
                raise ProtectedSubmitError(
                    "resource gate scheduler snapshot binding differs"
                )
            request_resources = gate["requested_resources"]
            try:
                resource_owner.validate_resource_tuple(
                    request_resources["resource_tier"],
                    request_resources["cores"],
                    request_resources["memory_gb"],
                )
                estimate_evidence = batch_owner.validate_evidence(
                    copy.deepcopy(
                        dict(snapshot.estimated_core_hours_evidence)
                    ),
                    "estimated_core_hours_evidence",
                )
            except Exception as exc:
                raise ProtectedSubmitError(
                    f"exact resource/evidence binding is invalid: {exc}"
                ) from exc
            if request_resources["walltime_seconds"] < 1:
                raise ProtectedSubmitError(
                    "resource gate walltime must be positive"
                )

            try:
                _, input_bytes_before, input_digest_before = (
                    input_owner.read_stable_bytes(
                        snapshot.input_path, "protected-submit exact input"
                    )
                )
                report = input_owner.parse_gaussian(snapshot.input_path)
                input_approval = input_owner.validate_input_approval(
                    snapshot.input_approval_path,
                    snapshot.input_path,
                    report,
                    snapshot.work_kind,
                )
                _, input_bytes_after, input_digest_after = (
                    input_owner.read_stable_bytes(
                        snapshot.input_path,
                        "protected-submit exact input replay",
                    )
                )
            except SystemExit as exc:
                raise ProtectedSubmitError(
                    "exact input-approval owner blocked protected submit"
                ) from exc
            except Exception as exc:
                raise ProtectedSubmitError(
                    f"exact input-approval owner rejected the closure: {exc}"
                ) from exc
            if (
                input_bytes_before != input_bytes_after
                or input_digest_before != input_digest_after
                or input_digest_after != input_sha256
                or report["input_sha256"] != input_sha256
                or input_approval["input_sha256"] != input_sha256
                or input_approval["schema"] not in SUPPORTED_INPUT_APPROVALS
            ):
                raise ProtectedSubmitError(
                    "exact input bytes, batch identity and input approval differ"
                )
            if (
                report["nprocshared"] != request_resources["cores"]
                or input_owner.parse_memory(report["mem"])
                != request_resources["memory_gb"] * 1024**3
            ):
                raise ProtectedSubmitError(
                    "exact input resources differ from the resource gate"
                )

            summary = input_owner.live_approval_summary(
                snapshot.project,
                report,
                None,
                snapshot.work_kind,
                input_approval,
            )
            summary["execution"] = {
                "batch_id": ledger["batch"]["batch_id"],
                "review_sha256": ledger["batch"]["review_sha256"],
                "scientific_task_id": snapshot.scientific_task_id,
                "attempt_id": attempt_id,
                "idempotency_key": idempotency_key,
                "estimated_core_hours": request_resources[
                    "estimated_core_hours"
                ],
                "estimated_core_hours_evidence": estimate_evidence,
                "resource_binding": {
                    "policy_id": gate["policy_id"],
                    "policy_sha256": gate["policy_sha256"],
                    "gate_id": gate["gate_id"],
                    "gate_sha256": gate["gate_sha256"],
                    "resource_tier": request_resources["resource_tier"],
                    "cores": request_resources["cores"],
                    "memory_gb": request_resources["memory_gb"],
                    "walltime_seconds": request_resources[
                        "walltime_seconds"
                    ],
                },
            }
            try:
                with _bind_existing_owner_clock(input_owner, current):
                    live_approval, live_artifact_sha256 = (
                        input_owner.validate_live_approval_binding(
                            snapshot.live_approval_path, summary
                        )
                    )
            except SystemExit as exc:
                raise ProtectedSubmitError(
                    "live-approval owner blocked protected submit"
                ) from exc
            except Exception as exc:
                raise ProtectedSubmitError(
                    f"live-approval owner rejected the closure: {exc}"
                ) from exc
            if live_approval["schema"] not in SUPPORTED_LIVE_APPROVALS:
                raise ProtectedSubmitError(
                    "protected submit requires resource-bound live approval /9-/11"
                )
            not_before = _time(
                live_approval["approved_at"], "live approval approved_at"
            )
            expires_at = _time(
                live_approval["expires_at"], "live approval expires_at"
            )
            if (
                not_before > current
                or expires_at <= not_before
                or current >= expires_at
            ):
                raise ProtectedSubmitError(
                    "live approval is outside the owner-trusted active window"
                )

        transport, transport_nonces = _replay_transport(
            snapshot.transport_artifacts,
            now=current,
            project=snapshot.project,
        )
        stage = _stage_binding(
            input_bytes_after,
            {
                "schema": "auto-g16-fixed-scheduler-submission-binding/1",
                "project": snapshot.project,
                "attempt_id": attempt_id,
                "input_sha256": input_sha256,
                "resource_tier": request_resources["resource_tier"],
                "cores": request_resources["cores"],
                "memory_gb": request_resources["memory_gb"],
                "walltime_seconds": request_resources[
                    "walltime_seconds"
                ],
                "automatic_retry": False,
            },
        )
        if stage["manifest_sha256"] == stage["bundle_sha256"]:
            raise ProtectedSubmitError(
                "stage manifest and byte-bundle domains are not separated"
            )
        live_identity_sha256 = _sha(
            live_artifact_sha256, "live approval artifact"
        )
        authority_seed = digest(
            {
                "schema": "auto-g16-protected-submit-authority-id/1",
                "live_approval_artifact_sha256": live_identity_sha256,
            }
        )
        bundle_id = f"protected-submit-{authority_seed}"
        authority_nonce = digest(
            {
                "schema": "auto-g16-protected-submit-authority-nonce/1",
                "live_approval_artifact_sha256": live_identity_sha256,
            }
        )
        if authority_nonce in transport_nonces:
            raise ProtectedSubmitError(
                "protected-submit authority nonce collides with transport"
            )
        workspace_projection = {
            "allowed_root": FIXED_REMOTE_ROOT,
            "project": snapshot.project,
            "fresh_project_required": True,
            "no_overwrite": True,
            "no_symlink": True,
            "no_delete": True,
            "root_override_allowed": False,
        }
        document = finalize(
            {
                "schema": SCHEMA,
                "owner": OWNER,
                "bundle_id": bundle_id,
                "identity": {
                    "project": snapshot.project,
                    "scientific_task_id": snapshot.scientific_task_id,
                    "attempt_id": attempt_id,
                    "input_sha256": input_sha256,
                    "idempotency_key_sha256": idempotency_key_sha256,
                    "scientific_identity_sha256": digest(task["identity"]),
                },
                "workspace": {
                    "allowed_root": FIXED_REMOTE_ROOT,
                    "workspace_binding_sha256": digest(workspace_projection),
                    "fresh_project_required": True,
                    "no_overwrite": True,
                    "no_symlink": True,
                    "no_delete": True,
                    "root_override_allowed": False,
                },
                "approvals": {
                    "scientific_task_owner": "auto-g16-rtwin-pbs",
                    "input_approval": {
                        "schema": input_approval["schema"],
                        "artifact_sha256": input_approval["sha256"],
                        "payload_sha256": input_approval["payload_sha256"],
                    },
                    "live_submission_approval": {
                        "schema": live_approval["schema"],
                        "approval_id": live_approval["approval_id"],
                        "artifact_sha256": live_identity_sha256,
                        "not_before": live_approval["approved_at"],
                        "expires_at": live_approval["expires_at"],
                    },
                },
                "execution": {
                    "batch_schema": ledger["schema"],
                    "batch_id": ledger["batch"]["batch_id"],
                    "review_sha256": ledger["batch"]["review_sha256"],
                    "ledger_sha256": ledger["ledger_sha256"],
                    "resource_state_revision": ledger[
                        "resource_state_revision"
                    ],
                    "resource_state_sha256": ledger["resource_state_sha256"],
                },
                "resources": {
                    "policy_id": gate["policy_id"],
                    "policy_sha256": gate["policy_sha256"],
                    "gate_id": gate["gate_id"],
                    "gate_sha256": gate["gate_sha256"],
                    "resource_tier": request_resources["resource_tier"],
                    "cores": request_resources["cores"],
                    "memory_gb": request_resources["memory_gb"],
                    "walltime_seconds": request_resources[
                        "walltime_seconds"
                    ],
                },
                "transport": transport,
                "stage": stage,
                "operation_order": list(OPERATION_ORDER),
                "authority": {
                    "authority_nonce": authority_nonce,
                    "not_before": live_approval["approved_at"],
                    "expires_at": live_approval["expires_at"],
                    "single_use": True,
                    "consumed": False,
                    "automatic_retry": False,
                    "scope": {
                        "stage": True,
                        "submit": True,
                        "status": False,
                        "fetch": False,
                        "cancel": False,
                        "cleanup": False,
                        "delete": False,
                        "arbitrary_command": False,
                    },
                },
                "failure_policy": {
                    "post_reservation_state": "submission_uncertain",
                    "reconciliation": "existing_read_only_reconciliation_only",
                    "automatic_retry": False,
                    "automatic_cancel": False,
                    "automatic_cleanup": False,
                },
                "evidence_status": {
                    "code_support": True,
                    "offline_contract_validation": True,
                    "actual_adapter_verified": False,
                    "live_validation_performed": False,
                    "external_actions_performed": False,
                },
                "bundle_payload_sha256": "",
            }
        )
        return SealedProtectedSubmitBundle._from_owner(
            document,
            transport_nonces + (authority_nonce,),
            token=_SEAL_TOKEN,
        )

    def seal(
        self, evidence: ProtectedSubmitEvidence
    ) -> SealedProtectedSubmitBundle:
        return self._seal_at(evidence, self._preflight_clock())

    def reserve_once(
        self, evidence: ProtectedSubmitEvidence
    ) -> ReservedProtectedSubmitBundle:
        preliminary = self.seal(evidence)
        state = _load_state_owner_module()
        intent = state.ConsumptionIntent(
            authorization_id=preliminary.bundle_id,
            authorization_sha256=preliminary.bundle_payload_sha256,
            readiness_sha256=preliminary.bundle_payload_sha256,
            attempt_id=preliminary.attempt_id,
            idempotency_key_sha256=preliminary.idempotency_key_sha256,
            attestation_nonces=preliminary.attestation_nonces,
        )

        def replay(
            _snapshot: dict[str, tuple[str, ...]],
            trusted_now: datetime,
        ) -> str:
            sealed = self._seal_at(evidence, trusted_now)
            if (
                sealed.bundle_id != preliminary.bundle_id
                or sealed.bundle_payload_sha256
                != preliminary.bundle_payload_sha256
                or sealed.attestation_nonces
                != preliminary.attestation_nonces
            ):
                raise ProtectedSubmitError(
                    "trusted owner replay differs from preliminary closure"
                )
            return sealed.bundle_payload_sha256

        consumption = self._state_owner.consume_after_replay_at_trusted_now(
            intent, replay
        )
        reserved = ReservedProtectedSubmitBundle._from_owner(
            preliminary,
            consumption,
            token=_RESERVATION_TOKEN,
        )
        reserved.assert_owner_sealed()
        return reserved
