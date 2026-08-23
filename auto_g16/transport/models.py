"""Immutable public records for the frozen v3 Transport boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import re
from threading import Lock
from typing import Final
import weakref

from auto_g16.execution import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    ReceiptJournal,
    ServerProfile,
    assert_execution_snapshot_identity,
    resolve_server_profile,
)

from ._canonical import (
    TransportBoundaryError,
    _positive,
    _text,
    canonical_bytes,
    capture_id,
    scheduler_id,
)


MAX_ARTIFACT_REQUESTS: Final = 4
MAX_FETCH_ARTIFACT_BYTES: Final = 134_217_728
MAX_FETCH_CAPTURE_BYTES: Final = 268_435_456
_PORTABLE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_JOB_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ARTIFACT_KINDS: Final = frozenset({"gaussian-log", "stdout", "stderr"})
_CAPTURE_STATUSES: Final = frozenset(
    {"captured", "capture-in-progress", "capture-interrupted", "capture-error"}
)
_COMPLETENESS: Final = frozenset({"partial", "complete"})
_BINDING_REGISTRY: dict[
    int, tuple[weakref.ReferenceType[ExactRemoteJobBinding], tuple[str, ...]]
] = {}
_BINDING_REGISTRY_LOCK = Lock()


def _timestamp(value: object, field_name: str) -> str:
    _text(value, field_name)
    assert isinstance(value, str)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise TransportBoundaryError(
            f"{field_name} must be exact UTC with six fractional digits"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        raise TransportBoundaryError(
            f"{field_name} must be exact UTC with six fractional digits"
        )
    return value


def _portable_name(value: object, field_name: str) -> str:
    _text(value, field_name)
    assert isinstance(value, str)
    if value in {".", ".."} or _PORTABLE_NAME.fullmatch(value) is None:
        raise TransportBoundaryError(f"{field_name} must be one portable component")
    if any(character in value for character in "*?[]{};$`|&<>!()'\""):
        raise TransportBoundaryError(f"{field_name} contains shell or glob syntax")
    return value


def _binding_payload(binding: ExactRemoteJobBinding) -> dict[str, object]:
    return {
        "attempt_id": binding.attempt_id,
        "execution_snapshot_id": binding.execution_snapshot_id,
        "submission_intent_id": binding.submission_intent_id,
        "remote_effect_receipt_id": binding.remote_effect_receipt_id,
        "remote_workspace": binding.remote_workspace,
        "job_id": binding.job_id,
    }


def _assert_profile_current(
    snapshot: ExecutionSnapshot, current_profile: ServerProfile
) -> None:
    assert_execution_snapshot_identity(snapshot)
    try:
        current = resolve_server_profile(current_profile)
    except Exception as exc:
        raise TransportBoundaryError("current ServerProfile cannot be resolved") from exc
    frozen = snapshot.resolved_server_profile
    if (
        current != frozen
        or current.resolved_server_profile_id != frozen.resolved_server_profile_id
        or current.effective_config_sha256 != frozen.effective_config_sha256
        or current.semantic_payload() != frozen.semantic_payload()
    ):
        raise TransportBoundaryError("current ServerProfile differs from the exact snapshot")


@dataclass(frozen=True, slots=True, weakref_slot=True, kw_only=True, init=False)
class ExactRemoteJobBinding:
    attempt_id: str
    execution_snapshot_id: str
    submission_intent_id: str
    remote_effect_receipt_id: str
    remote_workspace: str
    job_id: str

    def __init__(self) -> None:
        raise TypeError("ExactRemoteJobBinding requires persisted receipt authority")

    @classmethod
    def from_persisted_receipt(
        cls,
        snapshot: ExecutionSnapshot,
        journal: ReceiptJournal,
        *,
        remote_effect_receipt_id: str,
        current_profile: ServerProfile,
    ) -> ExactRemoteJobBinding:
        if not isinstance(snapshot, ExecutionSnapshot):
            raise TransportBoundaryError("snapshot must be an ExecutionSnapshot")
        if type(journal) is not ReceiptJournal:
            raise TransportBoundaryError("journal must be a public ReceiptJournal")
        _text(remote_effect_receipt_id, "remote_effect_receipt_id")
        try:
            _assert_profile_current(snapshot, current_profile)
            receipts = journal.receipts_for_attempt(snapshot.attempt_id)
        except TransportBoundaryError:
            raise
        except Exception as exc:
            raise TransportBoundaryError("persisted receipt journal is malformed") from exc
        selected = tuple(
            receipt
            for receipt in receipts
            if receipt.remote_effect_receipt_id == remote_effect_receipt_id
        )
        if len(selected) != 1:
            raise TransportBoundaryError("exactly one persisted receipt ID is required")
        receipt = selected[0]
        if receipt.effect_kind not in {
            EffectKind.SUBMISSION,
            EffectKind.SUBMISSION_RECONCILIATION,
        } or receipt.effect_state is not EffectState.CONFIRMED_EFFECT:
            raise TransportBoundaryError("receipt does not confirm submission effect")
        if (
            receipt.attempt_id != snapshot.attempt_id
            or receipt.execution_snapshot_id != snapshot.execution_snapshot_id
            or receipt.submission_intent_id != snapshot.submission_intent_id
            or receipt.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
            or not isinstance(receipt.job_id, str)
            or _JOB_ID.fullmatch(receipt.job_id) is None
        ):
            raise TransportBoundaryError("persisted receipt does not bind the exact remote job")
        value = object.__new__(cls)
        object.__setattr__(value, "attempt_id", snapshot.attempt_id)
        object.__setattr__(value, "execution_snapshot_id", snapshot.execution_snapshot_id)
        object.__setattr__(value, "submission_intent_id", snapshot.submission_intent_id)
        object.__setattr__(value, "remote_effect_receipt_id", remote_effect_receipt_id)
        object.__setattr__(value, "remote_workspace", receipt.remote_workspace)
        object.__setattr__(value, "job_id", receipt.job_id)
        marker = tuple(str(item) for item in _binding_payload(value).values())
        identity = id(value)

        def discard(reference: weakref.ReferenceType[ExactRemoteJobBinding]) -> None:
            with _BINDING_REGISTRY_LOCK:
                registered = _BINDING_REGISTRY.get(identity)
                if registered is not None and registered[0] is reference:
                    _BINDING_REGISTRY.pop(identity, None)

        reference = weakref.ref(value, discard)
        with _BINDING_REGISTRY_LOCK:
            _BINDING_REGISTRY[identity] = (reference, marker)
        return value


def _assert_persisted_binding(binding: ExactRemoteJobBinding) -> None:
    marker = tuple(str(item) for item in _binding_payload(binding).values())
    with _BINDING_REGISTRY_LOCK:
        registered = _BINDING_REGISTRY.get(id(binding))
    if (
        registered is None
        or registered[0]() is not binding
        or registered[1] != marker
    ):
        raise TransportBoundaryError("remote job binding lacks persisted journal authority")


def _assert_binding_matches_snapshot(
    snapshot: ExecutionSnapshot,
    binding: ExactRemoteJobBinding,
    current_profile: ServerProfile,
) -> None:
    if not isinstance(binding, ExactRemoteJobBinding):
        raise TransportBoundaryError("binding must be persisted exact job authority")
    _assert_persisted_binding(binding)
    _assert_profile_current(snapshot, current_profile)
    if (
        binding.attempt_id != snapshot.attempt_id
        or binding.execution_snapshot_id != snapshot.execution_snapshot_id
        or binding.submission_intent_id != snapshot.submission_intent_id
        or binding.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
    ):
        raise TransportBoundaryError("remote job binding differs from the current snapshot")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class SchedulerReadEvidence:
    binding: ExactRemoteJobBinding
    source_identity: str
    observed_at_utc: str
    freshness: str
    state: str
    evidence_sha256: str
    evidence_size_bytes: int
    schema_version: int = field(init=False, default=1)
    source_kind: str = field(init=False, default="scheduler")
    progress_position: None = field(init=False, default=None)

    def __init__(self) -> None:
        raise TypeError("SchedulerReadEvidence is created only by scheduler acquisition")

    @classmethod
    def _from_classified(
        cls,
        *,
        binding: ExactRemoteJobBinding,
        observed_at_utc: str,
        freshness: str,
        state: str,
        evidence_sha256: str,
        evidence_size_bytes: int,
    ) -> SchedulerReadEvidence:
        _timestamp(observed_at_utc, "observed_at_utc")
        if freshness not in {"fresh", "unknown"}:
            raise TransportBoundaryError("new scheduler evidence has invalid freshness")
        if state not in {
            "queued",
            "running",
            "held",
            "exiting",
            "terminal",
            "absent",
            "unknown",
        }:
            raise TransportBoundaryError("scheduler evidence has invalid state")
        if freshness == "unknown" and state != "unknown":
            raise TransportBoundaryError("uncertain scheduler acquisition must remain unknown")
        if len(evidence_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in evidence_sha256
        ):
            raise TransportBoundaryError("evidence_sha256 must be a lowercase digest")
        if isinstance(evidence_size_bytes, bool) or not isinstance(evidence_size_bytes, int) or evidence_size_bytes < 0:
            raise TransportBoundaryError("evidence_size_bytes must be a non-negative integer")
        name = [
            "auto-g16-transport/scheduler-read",
            1,
            _binding_payload(binding),
            observed_at_utc,
            freshness,
            state,
            evidence_sha256,
            evidence_size_bytes,
        ]
        value = object.__new__(cls)
        object.__setattr__(value, "binding", binding)
        object.__setattr__(value, "source_identity", scheduler_id(name))
        object.__setattr__(value, "observed_at_utc", observed_at_utc)
        object.__setattr__(value, "freshness", freshness)
        object.__setattr__(value, "state", state)
        object.__setattr__(value, "evidence_sha256", evidence_sha256)
        object.__setattr__(value, "evidence_size_bytes", evidence_size_bytes)
        object.__setattr__(value, "schema_version", 1)
        object.__setattr__(value, "source_kind", "scheduler")
        object.__setattr__(value, "progress_position", None)
        return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ExactArtifactRequest:
    artifact_kind: str
    logical_name: str
    remote_relative_name: str
    required: bool

    def __post_init__(self) -> None:
        if self.artifact_kind not in _ARTIFACT_KINDS:
            raise TransportBoundaryError("artifact_kind is outside the v1 allowlist")
        _portable_name(self.logical_name, "logical_name")
        _portable_name(self.remote_relative_name, "remote_relative_name")
        if type(self.required) is not bool:
            raise TransportBoundaryError("required must be a boolean")


def _request_payload(request: ExactArtifactRequest) -> dict[str, object]:
    return {
        "artifact_kind": request.artifact_kind,
        "logical_name": request.logical_name,
        "remote_relative_name": request.remote_relative_name,
        "required": request.required,
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedArtifact:
    request: ExactArtifactRequest
    content: bytes
    sha256: str = field(init=False)
    size_bytes: int = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, ExactArtifactRequest):
            raise TransportBoundaryError("request must be an ExactArtifactRequest")
        if type(self.content) is not bytes:
            raise TransportBoundaryError("fetched content must be immutable bytes")
        if len(self.content) > MAX_FETCH_ARTIFACT_BYTES:
            raise TransportBoundaryError("fetched artifact exceeds its byte cap")
        object.__setattr__(self, "sha256", sha256(self.content).hexdigest())
        object.__setattr__(self, "size_bytes", len(self.content))


def _artifact_metadata(artifact: FetchedArtifact) -> dict[str, object]:
    return {
        "artifact_kind": artifact.request.artifact_kind,
        "logical_name": artifact.request.logical_name,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _validate_requests(requests: tuple[ExactArtifactRequest, ...]) -> None:
    if not isinstance(requests, tuple) or not requests or len(requests) > MAX_ARTIFACT_REQUESTS:
        raise TransportBoundaryError("requests must be a finite non-empty tuple of at most four")
    if any(not isinstance(item, ExactArtifactRequest) for item in requests):
        raise TransportBoundaryError("requests contain an invalid item")
    logical_keys = tuple((item.artifact_kind, item.logical_name) for item in requests)
    remote_names = tuple(item.remote_relative_name for item in requests)
    if len(set(logical_keys)) != len(logical_keys) or len(set(remote_names)) != len(remote_names):
        raise TransportBoundaryError("requests contain duplicate authority names")


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedOutputCapture:
    binding: ExactRemoteJobBinding
    input_binding_observation_id: str
    capture_source_id: str = field(init=False)
    capture_sequence: int
    capture_status: str
    capture_completeness: str
    requests: tuple[ExactArtifactRequest, ...]
    artifacts: tuple[FetchedArtifact, ...]
    missing_requests: tuple[ExactArtifactRequest, ...]
    capture_manifest_sha256: str = field(init=False)
    captured_at_utc: str
    schema_version: int = field(init=False, default=1)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ExactRemoteJobBinding):
            raise TransportBoundaryError("binding must be an ExactRemoteJobBinding")
        _assert_persisted_binding(self.binding)
        _text(self.input_binding_observation_id, "input_binding_observation_id")
        _positive(self.capture_sequence, "capture_sequence")
        if self.capture_status not in _CAPTURE_STATUSES:
            raise TransportBoundaryError("capture_status is outside the v1 vocabulary")
        if self.capture_completeness not in _COMPLETENESS:
            raise TransportBoundaryError("capture_completeness is outside the v1 vocabulary")
        _timestamp(self.captured_at_utc, "captured_at_utc")
        _validate_requests(self.requests)
        if not isinstance(self.artifacts, tuple) or not self.artifacts or any(
            not isinstance(item, FetchedArtifact) for item in self.artifacts
        ):
            raise TransportBoundaryError("artifacts must be a non-empty tuple")
        if not isinstance(self.missing_requests, tuple) or any(
            not isinstance(item, ExactArtifactRequest) for item in self.missing_requests
        ):
            raise TransportBoundaryError("missing_requests must be a request tuple")
        successful = tuple(artifact.request for artifact in self.artifacts)
        if successful != self.requests[: len(successful)]:
            raise TransportBoundaryError("artifacts are not the exact request prefix")
        if self.missing_requests != self.requests[len(successful) :]:
            raise TransportBoundaryError("missing requests are not the exact request suffix")
        if sum(artifact.size_bytes for artifact in self.artifacts) > MAX_FETCH_CAPTURE_BYTES:
            raise TransportBoundaryError("capture exceeds its aggregate byte cap")
        if self.capture_completeness == "complete":
            if (
                self.capture_status != "captured"
                or self.missing_requests
                or len(self.artifacts) != len(self.requests)
            ):
                raise TransportBoundaryError("complete capture has an invalid partition")
        elif not self.missing_requests or len(self.artifacts) >= len(self.requests):
            raise TransportBoundaryError("partial capture requires a non-empty exact suffix")
        if self.capture_status != "captured" and self.capture_completeness != "partial":
            raise TransportBoundaryError("non-captured status must remain partial")
        manifest = [
            "auto-g16-transport/capture-manifest",
            1,
            [_request_payload(item) for item in self.requests],
            [_artifact_metadata(item) for item in self.artifacts],
            [_request_payload(item) for item in self.missing_requests],
        ]
        manifest_digest = sha256(canonical_bytes(manifest)).hexdigest()
        identity_name = [
            "auto-g16-transport/output-capture",
            1,
            _binding_payload(self.binding),
            self.input_binding_observation_id,
            self.capture_sequence,
            self.capture_status,
            self.capture_completeness,
            [_request_payload(item) for item in self.requests],
            [_artifact_metadata(item) for item in self.artifacts],
            [_request_payload(item) for item in self.missing_requests],
            manifest_digest,
            self.captured_at_utc,
        ]
        object.__setattr__(self, "capture_manifest_sha256", manifest_digest)
        object.__setattr__(self, "capture_source_id", capture_id(identity_name))
        object.__setattr__(self, "schema_version", 1)


__all__ = [
    "ExactArtifactRequest",
    "ExactRemoteJobBinding",
    "FetchedArtifact",
    "FetchedOutputCapture",
    "SchedulerReadEvidence",
]
