"""Private deterministic data plan for the bounded synthetic RTwin slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256 as _sha256
import re
from typing import Final

from ._identity import (
    ExecutionValueError,
    require_positive_integer,
    require_sha256,
    require_text,
)
from ._paths import validate_portable_name, validate_posix_path, validate_windows_path
from .models import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    RemoteEffectReceipt,
    _require_job_id,
)
from .preparation import assert_execution_snapshot_identity


_SUBMIT_EXECUTABLE: Final = "qsub"
_DEFERRED: Final = "DEFERRED"
_SUBMIT_BASENAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class _StagedArtifact:
    role: str
    binding_id: str
    logical_name: str
    content: bytes
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        if self.role not in {"prepared-input", "pbs-template"}:
            raise ExecutionValueError("staged artifact has an unsupported role")
        require_text(self.binding_id, "artifact binding_id")
        validate_portable_name(self.logical_name, "artifact logical_name")
        if not isinstance(self.content, bytes) or not self.content:
            raise ExecutionValueError("staged artifact content must be non-empty bytes")
        require_positive_integer(self.size_bytes, "artifact size_bytes")
        require_sha256(self.sha256, "artifact sha256")
        if len(self.content) != self.size_bytes:
            raise ExecutionValueError("staged artifact size differs from its content")
        if _sha256(self.content).hexdigest() != self.sha256:
            raise ExecutionValueError("staged artifact digest differs from its content")


@dataclass(frozen=True, slots=True)
class _SubmissionInvocation:
    executable: str
    argv: tuple[str, ...]
    cwd: str

    def __post_init__(self) -> None:
        if self.executable != _SUBMIT_EXECUTABLE:
            raise ExecutionValueError("submission executable is not the fixed token")
        if not isinstance(self.argv, tuple) or len(self.argv) != 1:
            raise ExecutionValueError("submission argv must contain one PBS basename")
        validate_portable_name(self.argv[0], "submission PBS argv")
        if not _SUBMIT_BASENAME.fullmatch(self.argv[0]):
            raise ExecutionValueError("submission PBS argv has an invalid lexical form")
        validate_posix_path(self.cwd, "submission cwd")


@dataclass(frozen=True, slots=True)
class _RTWinMinimalPlan:
    execution_snapshot_id: str
    attempt_id: str
    submission_intent_id: str
    project_id: str
    workspace_binding_id: str
    local_attempt_dir: str
    rtwin_attempt_dir: str | None
    remote_attempt_dir: str
    artifacts: tuple[_StagedArtifact, _StagedArtifact]
    submission: _SubmissionInvocation

    def __post_init__(self) -> None:
        for name in (
            "execution_snapshot_id",
            "attempt_id",
            "submission_intent_id",
            "project_id",
            "workspace_binding_id",
        ):
            require_text(getattr(self, name), name)
        validate_posix_path(self.local_attempt_dir, "local_attempt_dir")
        validate_posix_path(self.remote_attempt_dir, "remote_attempt_dir")
        if self.rtwin_attempt_dir is not None:
            validate_windows_path(self.rtwin_attempt_dir, "rtwin_attempt_dir")
        if not isinstance(self.artifacts, tuple) or len(self.artifacts) != 2:
            raise ExecutionValueError("plan artifacts must be the ordered input/PBS pair")
        prepared, template = self.artifacts
        if not isinstance(prepared, _StagedArtifact) or not isinstance(
            template, _StagedArtifact
        ):
            raise ExecutionValueError("plan artifacts have an invalid private type")
        if (prepared.role, template.role) != ("prepared-input", "pbs-template"):
            raise ExecutionValueError("plan artifact order must be prepared input then PBS")
        if prepared.logical_name == template.logical_name:
            raise ExecutionValueError("plan artifact logical names must differ")
        if not isinstance(self.submission, _SubmissionInvocation):
            raise ExecutionValueError("plan submission has an invalid private type")
        if self.submission.cwd != self.remote_attempt_dir:
            raise ExecutionValueError("submission cwd differs from the Attempt workspace")
        if self.submission.argv != (template.logical_name,):
            raise ExecutionValueError("submission argv differs from the PBS basename")


@dataclass(frozen=True, slots=True)
class _DeferredFetchBoundary:
    execution_snapshot_id: str
    attempt_id: str
    submission_intent_id: str
    remote_effect_receipt_id: str
    remote_workspace: str
    job_id: str
    disposition: str = field(init=False, default=_DEFERRED)


def _artifact(
    *, role: str, binding_id: str, logical_name: str, content: bytes
) -> _StagedArtifact:
    return _StagedArtifact(
        role=role,
        binding_id=binding_id,
        logical_name=logical_name,
        content=content,
        size_bytes=len(content),
        sha256=_sha256(content).hexdigest(),
    )


def _build_rtwin_minimal_plan(
    snapshot: ExecutionSnapshot,
    prepared_input_bytes: bytes,
    pbs_template_bytes: bytes,
) -> _RTWinMinimalPlan:
    """Derive an immutable stage/submit description and perform no effects."""

    assert_execution_snapshot_identity(snapshot)
    snapshot.prepared_input_binding.verify_bytes(prepared_input_bytes)
    snapshot.pbs_template_binding.verify_bytes(pbs_template_bytes)
    prepared = _artifact(
        role="prepared-input",
        binding_id=snapshot.prepared_input_binding.prepared_input_binding_id,
        logical_name=snapshot.prepared_input_binding.logical_name,
        content=prepared_input_bytes,
    )
    template = _artifact(
        role="pbs-template",
        binding_id=snapshot.pbs_template_binding.pbs_template_binding_id,
        logical_name=snapshot.pbs_template_binding.logical_name,
        content=pbs_template_bytes,
    )
    workspace = snapshot.workspace_binding
    return _RTWinMinimalPlan(
        execution_snapshot_id=snapshot.execution_snapshot_id,
        attempt_id=snapshot.attempt_id,
        submission_intent_id=snapshot.submission_intent_id,
        project_id=workspace.project_id,
        workspace_binding_id=workspace.workspace_binding_id,
        local_attempt_dir=workspace.local_attempt_dir,
        rtwin_attempt_dir=workspace.rtwin_attempt_dir,
        remote_attempt_dir=workspace.remote_attempt_dir,
        artifacts=(prepared, template),
        submission=_SubmissionInvocation(
            executable=_SUBMIT_EXECUTABLE,
            argv=(template.logical_name,),
            cwd=workspace.remote_attempt_dir,
        ),
    )


def _assert_plan_matches_snapshot(
    plan: _RTWinMinimalPlan, snapshot: ExecutionSnapshot
) -> None:
    """Reject replacement or splicing before the synthetic submit seam."""

    assert_execution_snapshot_identity(snapshot)
    if not isinstance(plan, _RTWinMinimalPlan):
        raise ExecutionValueError("synthetic adapter requires a private RTwin plan")
    expected = _build_rtwin_minimal_plan(
        snapshot,
        plan.artifacts[0].content,
        plan.artifacts[1].content,
    )
    if plan != expected:
        raise ExecutionValueError("private RTwin plan differs from its exact snapshot")


def _defer_offline_fetch(
    snapshot: ExecutionSnapshot, confirmed_job_receipt: RemoteEffectReceipt
) -> _DeferredFetchBoundary:
    """Stop at an explicit zero-effect boundary; no output is transferred."""

    assert_execution_snapshot_identity(snapshot)
    if not isinstance(confirmed_job_receipt, RemoteEffectReceipt):
        raise ExecutionValueError("fetch boundary requires a RemoteEffectReceipt")
    receipt = RemoteEffectReceipt.from_payload(confirmed_job_receipt.semantic_payload())
    if (
        receipt.attempt_id != snapshot.attempt_id
        or receipt.execution_snapshot_id != snapshot.execution_snapshot_id
        or receipt.submission_intent_id != snapshot.submission_intent_id
    ):
        raise ExecutionValueError("fetch receipt does not bind the exact snapshot")
    if receipt.effect_kind not in {
        EffectKind.SUBMISSION,
        EffectKind.SUBMISSION_RECONCILIATION,
    }:
        raise ExecutionValueError("fetch receipt is not confirmed submission evidence")
    if receipt.effect_state is not EffectState.CONFIRMED_EFFECT:
        raise ExecutionValueError("fetch receipt does not confirm a job binding")
    if receipt.remote_workspace != snapshot.workspace_binding.remote_attempt_dir:
        raise ExecutionValueError("fetch receipt binds a different remote workspace")
    job_id = _require_job_id(receipt.job_id)
    return _DeferredFetchBoundary(
        execution_snapshot_id=snapshot.execution_snapshot_id,
        attempt_id=snapshot.attempt_id,
        submission_intent_id=snapshot.submission_intent_id,
        remote_effect_receipt_id=receipt.remote_effect_receipt_id,
        remote_workspace=receipt.remote_workspace,
        job_id=job_id,
    )
