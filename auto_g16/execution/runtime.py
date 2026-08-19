"""Offline execution coordination over the public Core claim boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import stat
from typing import Protocol, runtime_checkable

from auto_g16.core import (
    AttemptState,
    Observation,
    ReconciliationResolution,
    SQLiteRuntimeStore,
    SubmissionIntentClaim,
    SubmissionOutcome,
)

from ._identity import (
    ExecutionValueError,
    canonical_bytes,
    freeze_mapping,
    require_text,
    semantic_id,
)
from .models import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    RECEIPT_OBSERVATION_TYPE,
    RemoteEffectReceipt,
    ServerProfile,
    WorkspaceBinding,
    _require_job_id,
    resolve_server_profile,
)
from .preparation import assert_execution_snapshot_identity


class ExecutionRuntimeError(RuntimeError):
    """Execution coordination could not satisfy the frozen contract."""


class ExecutionConflictError(ExecutionRuntimeError):
    """Durable execution evidence conflicts with an existing fact."""


class ConfirmedNoEffectError(ExecutionRuntimeError):
    """An adapter operation failed with reliable evidence of no stage effect."""

    def __init__(self, stage: EffectKind, code: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = require_text(code, "failure code")


class PossiblyEffectfulError(ExecutionRuntimeError):
    """An adapter operation may have crossed its effect seam."""

    def __init__(self, stage: EffectKind, code: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = require_text(code, "failure code")


@runtime_checkable
class ExecutionPort(Protocol):
    """Thin RTwin-first port reused later by the separately gated transport."""

    @property
    def contract_version(self) -> str: ...

    def allocate_attempt_workspace(self, snapshot: ExecutionSnapshot) -> str: ...

    def transfer_exact_bytes(
        self,
        snapshot: ExecutionSnapshot,
        prepared_input_bytes: bytes,
        pbs_template_bytes: bytes,
    ) -> None: ...

    def submit_once(self, snapshot: ExecutionSnapshot) -> str: ...

    def reconcile_submission(
        self, snapshot: ExecutionSnapshot, *, effect_sequence: int
    ) -> RemoteEffectReceipt: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionAttemptResult:
    claim: SubmissionIntentClaim
    attempt_state: AttemptState
    receipts: tuple[RemoteEffectReceipt, ...]


class ReceiptJournal:
    """Append-only receipt projection stored as public Core Observations."""

    def __init__(self, store: SQLiteRuntimeStore) -> None:
        if not isinstance(store, SQLiteRuntimeStore):
            raise ExecutionValueError("store must be a public Core SQLiteRuntimeStore")
        self._store = store

    def receipts_for_attempt(self, attempt_id: str) -> tuple[RemoteEffectReceipt, ...]:
        receipts: list[RemoteEffectReceipt] = []
        for observation in self._store.observations_for_attempt(attempt_id):
            if observation.observation_type != RECEIPT_OBSERVATION_TYPE:
                continue
            try:
                receipts.append(RemoteEffectReceipt.from_payload(observation.data))
            except ExecutionValueError as exc:
                raise ExecutionConflictError("stored execution receipt is malformed") from exc
            if receipts[-1].remote_effect_receipt_id != observation.observation_id:
                raise ExecutionConflictError(
                    "stored Observation identity differs from its execution receipt"
                )
        return tuple(receipts)

    def append(self, receipt: RemoteEffectReceipt) -> None:
        if not isinstance(receipt, RemoteEffectReceipt):
            raise ExecutionValueError("receipt must be a RemoteEffectReceipt")
        if (
            semantic_id("remote-effect-receipt", receipt.record_identity_payload())
            != receipt.remote_effect_receipt_id
        ):
            raise ExecutionValueError("remote effect receipt identity is stale")
        existing = self.receipts_for_attempt(receipt.attempt_id)
        for item in existing:
            if item.execution_snapshot_id != receipt.execution_snapshot_id:
                raise ExecutionConflictError("Attempt receipts cross-splice snapshots")
            if item.submission_intent_id != receipt.submission_intent_id:
                raise ExecutionConflictError("Attempt receipts cross-splice submission intents")
            if item.effect_sequence == receipt.effect_sequence:
                if canonical_bytes(item.semantic_payload()) == canonical_bytes(
                    receipt.semantic_payload()
                ):
                    return
                raise ExecutionConflictError("effect_sequence already has different evidence")
        expected_sequence = len(existing) + 1
        if receipt.effect_sequence != expected_sequence:
            raise ExecutionConflictError(
                f"effect_sequence must append {expected_sequence}, got {receipt.effect_sequence}"
            )
        self._store.append_observation(
            Observation(
                observation_id=receipt.remote_effect_receipt_id,
                attempt_id=receipt.attempt_id,
                observation_type=RECEIPT_OBSERVATION_TYPE,
                data=receipt.semantic_payload(),
            )
        )


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
if hasattr(os, "O_CLOEXEC"):
    _DIRECTORY_OPEN_FLAGS |= os.O_CLOEXEC


def _local_allocation_checkpoint(
    _stage: str, _binding: WorkspaceBinding
) -> None:
    """Private deterministic test seam; production execution is a no-op."""


def _directory_identity(descriptor: int) -> tuple[int, int]:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode):
        raise ExecutionValueError("workspace descriptor is not a directory")
    return (value.st_dev, value.st_ino)


def _open_verified_workspace_parent(binding: WorkspaceBinding) -> int:
    descriptor = os.open(binding._local_approved_root, _DIRECTORY_OPEN_FLAGS)
    try:
        if _directory_identity(descriptor) != binding._local_component_identities[0]:
            raise ExecutionValueError("local approved-root descriptor changed")
        for index, part in enumerate(binding._local_parent_parts, start=1):
            child = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
            try:
                if (
                    _directory_identity(child)
                    != binding._local_component_identities[index]
                ):
                    raise ExecutionValueError("local workspace component changed")
            except Exception:
                os.close(child)
                raise
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _verify_workspace_parent_still_named(
    binding: WorkspaceBinding, expected_descriptor: int
) -> None:
    observed = _open_verified_workspace_parent(binding)
    try:
        if _directory_identity(observed) != _directory_identity(expected_descriptor):
            raise ExecutionValueError("local workspace parent was replaced")
    finally:
        os.close(observed)


def _verify_attempt_directory_still_named(
    parent_descriptor: int,
    attempt_name: str,
    attempt_descriptor: int,
    created_identity: tuple[int, int],
) -> None:
    named = os.stat(
        attempt_name,
        dir_fd=parent_descriptor,
        follow_symlinks=False,
    )
    named_identity = (named.st_dev, named.st_ino)
    if (
        not stat.S_ISDIR(named.st_mode)
        or named_identity != created_identity
        or _directory_identity(attempt_descriptor) != created_identity
    ):
        raise ExecutionRuntimeError("local Attempt workspace was replaced")


def _exclusive_write_at(
    directory_descriptor: int, logical_name: str, value: bytes
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(logical_name, flags, 0o400, dir_fd=directory_descriptor)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        current = os.fstat(descriptor)
        if not stat.S_ISREG(current.st_mode) or current.st_size != len(value):
            raise ExecutionRuntimeError("materialized handoff is not the expected regular file")
    finally:
        os.close(descriptor)


def _materialize_local_handoff(
    snapshot: ExecutionSnapshot,
    prepared_input_bytes: bytes,
    pbs_template_bytes: bytes,
) -> None:
    binding = snapshot.workspace_binding
    parent_descriptor: int | None = None
    attempt_descriptor: int | None = None
    created = False
    try:
        parent_descriptor = _open_verified_workspace_parent(binding)
        _local_allocation_checkpoint("before-allocation", binding)
        _verify_workspace_parent_still_named(binding, parent_descriptor)
        attempt_name = binding.attempt_id
        try:
            os.mkdir(attempt_name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError as exc:
            raise ConfirmedNoEffectError(
                EffectKind.LOCAL_WORKSPACE, "local-attempt-workspace-exists"
            ) from exc
        created = True
        created_value = os.stat(
            attempt_name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if not stat.S_ISDIR(created_value.st_mode):
            raise ExecutionRuntimeError(
                "new local Attempt workspace is not a real directory"
            )
        created_identity = (created_value.st_dev, created_value.st_ino)
        _local_allocation_checkpoint("after-directory-creation", binding)
        attempt_descriptor = os.open(
            attempt_name,
            _DIRECTORY_OPEN_FLAGS,
            dir_fd=parent_descriptor,
        )
        _verify_attempt_directory_still_named(
            parent_descriptor,
            attempt_name,
            attempt_descriptor,
            created_identity,
        )
        _local_allocation_checkpoint("before-handoff-write", binding)
        _verify_workspace_parent_still_named(binding, parent_descriptor)
        _verify_attempt_directory_still_named(
            parent_descriptor,
            attempt_name,
            attempt_descriptor,
            created_identity,
        )
        _exclusive_write_at(
            attempt_descriptor,
            snapshot.prepared_input_binding.logical_name,
            prepared_input_bytes,
        )
        _exclusive_write_at(
            attempt_descriptor,
            snapshot.pbs_template_binding.logical_name,
            pbs_template_bytes,
        )
        _verify_attempt_directory_still_named(
            parent_descriptor,
            attempt_name,
            attempt_descriptor,
            created_identity,
        )
        os.fchmod(attempt_descriptor, 0o500)
        os.fsync(attempt_descriptor)
    except ConfirmedNoEffectError:
        raise
    except (ExecutionValueError, OSError) as exc:
        if not created:
            raise ConfirmedNoEffectError(
                EffectKind.LOCAL_WORKSPACE,
                "local-workspace-anchor-unavailable",
            ) from exc
        raise ExecutionRuntimeError(
            "local Attempt workspace was created but its handoff is incomplete"
        ) from exc
    finally:
        if attempt_descriptor is not None:
            os.close(attempt_descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def _receipt(
    snapshot: ExecutionSnapshot,
    sequence: int,
    kind: EffectKind,
    state: EffectState,
    *,
    remote_workspace: str | None = None,
    job_id: str | None = None,
    details: Mapping[str, object] | None = None,
) -> RemoteEffectReceipt:
    return RemoteEffectReceipt(
        attempt_id=snapshot.attempt_id,
        execution_snapshot_id=snapshot.execution_snapshot_id,
        submission_intent_id=snapshot.submission_intent_id,
        effect_sequence=sequence,
        effect_kind=kind,
        effect_state=state,
        remote_workspace=remote_workspace,
        job_id=job_id,
        details=freeze_mapping(details or {}, "receipt details"),
    )


def _record_no_effect(
    journal: ReceiptJournal,
    snapshot: ExecutionSnapshot,
    sequence: int,
    error: ConfirmedNoEffectError,
) -> None:
    journal.append(
        _receipt(
            snapshot,
            sequence,
            error.stage,
            EffectState.CONFIRMED_NO_EFFECT,
            details={"code": error.code},
        )
    )


def _record_unknown(
    store: SQLiteRuntimeStore,
    journal: ReceiptJournal,
    snapshot: ExecutionSnapshot,
    sequence: int,
    error: PossiblyEffectfulError,
) -> ExecutionAttemptResult:
    journal.append(
        _receipt(
            snapshot,
            sequence,
            error.stage,
            EffectState.POSSIBLY_EFFECTFUL,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            details={"code": error.code},
        )
    )
    state = store.record_submission_outcome(
        snapshot.attempt_id,
        snapshot.submission_intent_id,
        SubmissionOutcome.UNKNOWN,
    )
    return ExecutionAttemptResult(
        claim=SubmissionIntentClaim.WINNER,
        attempt_state=state,
        receipts=journal.receipts_for_attempt(snapshot.attempt_id),
    )


def execute_once(
    store: SQLiteRuntimeStore,
    *,
    snapshot: ExecutionSnapshot,
    current_profile: ServerProfile,
    prepared_input_bytes: bytes,
    pbs_template_bytes: bytes,
    confirmed_execution_snapshot_id: str,
    port: ExecutionPort,
) -> ExecutionAttemptResult:
    """Consume the Core claim once and drive only the synthetic/offline port."""

    assert_execution_snapshot_identity(snapshot)
    if not isinstance(port, ExecutionPort):
        raise ExecutionValueError("port does not implement the frozen ExecutionPort")
    if store.attempt_state(snapshot.attempt_id) is AttemptState.PLANNED:
        if confirmed_execution_snapshot_id != snapshot.execution_snapshot_id:
            raise ExecutionValueError("operational confirmation does not match ExecutionSnapshot")
        if port.contract_version != snapshot.adapter_contract_version:
            raise ExecutionValueError("adapter contract version differs from ExecutionSnapshot")
        if resolve_server_profile(current_profile) != snapshot.resolved_server_profile:
            raise ExecutionValueError("mutable ServerProfile drifted before the effect seam")
        snapshot.prepared_input_binding.verify_bytes(prepared_input_bytes)
        snapshot.pbs_template_binding.verify_bytes(pbs_template_bytes)
        if (
            snapshot.prepared_input_binding.logical_name
            == snapshot.pbs_template_binding.logical_name
        ):
            raise ExecutionValueError(
                "prepared input and PBS template logical names must differ"
            )

    journal = ReceiptJournal(store)
    claim = store.record_submission_intent(
        snapshot.attempt_id, snapshot.submission_intent_id
    )
    if claim is SubmissionIntentClaim.REPLAY:
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )

    sequence = 1
    try:
        _materialize_local_handoff(snapshot, prepared_input_bytes, pbs_template_bytes)
    except ConfirmedNoEffectError as exc:
        _record_no_effect(journal, snapshot, sequence, exc)
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )
    except ExecutionRuntimeError:
        journal.append(
            _receipt(
                snapshot,
                sequence,
                EffectKind.LOCAL_WORKSPACE,
                EffectState.CONFIRMED_EFFECT,
                details={"status": "incomplete"},
            )
        )
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )
    journal.append(
        _receipt(
            snapshot,
            sequence,
            EffectKind.LOCAL_WORKSPACE,
            EffectState.CONFIRMED_EFFECT,
            details={"status": "sealed"},
        )
    )

    sequence += 1
    try:
        remote_workspace = port.allocate_attempt_workspace(snapshot)
        if remote_workspace != snapshot.workspace_binding.remote_attempt_dir:
            raise PossiblyEffectfulError(
                EffectKind.REMOTE_WORKSPACE, "remote-workspace-identity-mismatch"
            )
    except ConfirmedNoEffectError as exc:
        _record_no_effect(journal, snapshot, sequence, exc)
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )
    except PossiblyEffectfulError as exc:
        return _record_unknown(store, journal, snapshot, sequence, exc)
    except Exception as exc:
        return _record_unknown(
            store,
            journal,
            snapshot,
            sequence,
            PossiblyEffectfulError(EffectKind.REMOTE_WORKSPACE, type(exc).__name__),
        )
    journal.append(
        _receipt(
            snapshot,
            sequence,
            EffectKind.REMOTE_WORKSPACE,
            EffectState.CONFIRMED_EFFECT,
            remote_workspace=remote_workspace,
        )
    )

    sequence += 1
    try:
        port.transfer_exact_bytes(snapshot, prepared_input_bytes, pbs_template_bytes)
    except ConfirmedNoEffectError as exc:
        _record_no_effect(journal, snapshot, sequence, exc)
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )
    except PossiblyEffectfulError as exc:
        return _record_unknown(store, journal, snapshot, sequence, exc)
    except Exception as exc:
        return _record_unknown(
            store,
            journal,
            snapshot,
            sequence,
            PossiblyEffectfulError(EffectKind.INPUT_TRANSFER, type(exc).__name__),
        )
    journal.append(
        _receipt(
            snapshot,
            sequence,
            EffectKind.INPUT_TRANSFER,
            EffectState.CONFIRMED_EFFECT,
            remote_workspace=remote_workspace,
        )
    )

    sequence += 1
    try:
        job_id = port.submit_once(snapshot)
        try:
            _require_job_id(job_id)
        except ExecutionValueError:
            raise PossiblyEffectfulError(EffectKind.SUBMISSION, "invalid-job-identity")
    except ConfirmedNoEffectError as exc:
        _record_no_effect(journal, snapshot, sequence, exc)
        return ExecutionAttemptResult(
            claim=claim,
            attempt_state=store.attempt_state(snapshot.attempt_id),
            receipts=journal.receipts_for_attempt(snapshot.attempt_id),
        )
    except PossiblyEffectfulError as exc:
        return _record_unknown(store, journal, snapshot, sequence, exc)
    except Exception as exc:
        return _record_unknown(
            store,
            journal,
            snapshot,
            sequence,
            PossiblyEffectfulError(EffectKind.SUBMISSION, type(exc).__name__),
        )
    journal.append(
        _receipt(
            snapshot,
            sequence,
            EffectKind.SUBMISSION,
            EffectState.CONFIRMED_EFFECT,
            remote_workspace=remote_workspace,
            job_id=job_id,
        )
    )
    state = store.record_submission_outcome(
        snapshot.attempt_id,
        snapshot.submission_intent_id,
        SubmissionOutcome.SUBMITTED,
    )
    return ExecutionAttemptResult(
        claim=claim,
        attempt_state=state,
        receipts=journal.receipts_for_attempt(snapshot.attempt_id),
    )


def reconcile_unknown_from_receipt(
    store: SQLiteRuntimeStore,
    *,
    snapshot: ExecutionSnapshot,
    receipt: RemoteEffectReceipt,
) -> AttemptState:
    """Apply one persisted, read-only, same-Attempt reconciliation fact."""

    assert_execution_snapshot_identity(snapshot)
    if receipt.effect_kind is not EffectKind.SUBMISSION_RECONCILIATION:
        raise ExecutionValueError("reconciliation requires submission-reconciliation evidence")
    if (
        receipt.attempt_id != snapshot.attempt_id
        or receipt.execution_snapshot_id != snapshot.execution_snapshot_id
        or receipt.submission_intent_id != snapshot.submission_intent_id
    ):
        raise ExecutionValueError("reconciliation evidence does not bind the same snapshot")
    if receipt.remote_workspace != snapshot.workspace_binding.remote_attempt_dir:
        raise ExecutionValueError(
            "reconciliation evidence does not bind the exact remote workspace"
        )
    journal = ReceiptJournal(store)
    if store.attempt_state(snapshot.attempt_id) is not AttemptState.UNKNOWN:
        raise ExecutionValueError("read-only execution reconciliation requires UNKNOWN")
    if receipt.effect_state is EffectState.POSSIBLY_EFFECTFUL:
        resolution = ReconciliationResolution.UNRESOLVED
    elif receipt.effect_state is EffectState.CONFIRMED_NO_EFFECT:
        resolution = ReconciliationResolution.NOT_SUBMITTED
    elif receipt.job_id is not None:
        _require_job_id(receipt.job_id)
        resolution = ReconciliationResolution.SUBMITTED
    else:
        raise ExecutionValueError("confirmed submission reconciliation requires a job_id")
    existing_receipts = journal.receipts_for_attempt(snapshot.attempt_id)
    existing_reconciliation_receipts = tuple(
        item
        for item in existing_receipts
        if item.effect_kind is EffectKind.SUBMISSION_RECONCILIATION
    )
    if any(
        item.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
        for item in existing_reconciliation_receipts
    ):
        raise ExecutionConflictError(
            "existing reconciliation evidence does not bind the exact remote workspace"
        )
    existing_job_receipts = tuple(
        item for item in existing_receipts if item.job_id is not None
    )
    if any(
        item.remote_workspace != snapshot.workspace_binding.remote_attempt_dir
        for item in existing_job_receipts
    ):
        raise ExecutionConflictError(
            "existing job evidence does not bind the exact remote workspace"
        )
    existing_job_ids = {item.job_id for item in existing_job_receipts}
    if len(existing_job_ids) > 1 or (
        existing_job_ids
        and (
            receipt.job_id is None
            or any(item != receipt.job_id for item in existing_job_ids)
        )
    ):
        raise ExecutionConflictError("reconciliation job identity conflicts with existing evidence")
    journal.append(receipt)
    return store.reconcile_unknown(
        snapshot.attempt_id,
        receipt.remote_effect_receipt_id,
        resolution,
    )


def reconcile_unknown(
    store: SQLiteRuntimeStore,
    *,
    snapshot: ExecutionSnapshot,
    port: ExecutionPort,
) -> AttemptState:
    """Request one read-only reconciliation fact; never submit or retry."""

    assert_execution_snapshot_identity(snapshot)
    if not isinstance(port, ExecutionPort):
        raise ExecutionValueError("port does not implement the frozen ExecutionPort")
    if port.contract_version != snapshot.adapter_contract_version:
        raise ExecutionValueError("adapter contract version differs from ExecutionSnapshot")
    if store.attempt_state(snapshot.attempt_id) is not AttemptState.UNKNOWN:
        raise ExecutionValueError("read-only execution reconciliation requires UNKNOWN")
    journal = ReceiptJournal(store)
    sequence = len(journal.receipts_for_attempt(snapshot.attempt_id)) + 1
    receipt = port.reconcile_submission(snapshot, effect_sequence=sequence)
    return reconcile_unknown_from_receipt(store, snapshot=snapshot, receipt=receipt)
