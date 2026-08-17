"""Offline execution coordination over the public Core claim boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import re
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
from ._paths import verify_local_parent_identity
from .models import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    RECEIPT_OBSERVATION_TYPE,
    RemoteEffectReceipt,
    ServerProfile,
    resolve_server_profile,
)
from .preparation import assert_execution_snapshot_identity


_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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


def _exclusive_write(path: Path, value: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o400)
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
    verify_local_parent_identity(
        binding.local_attempt_dir, binding._local_parent_identity
    )
    directory = Path(binding.local_attempt_dir)
    try:
        os.mkdir(directory, 0o700)
    except FileExistsError as exc:
        raise ConfirmedNoEffectError(
            EffectKind.LOCAL_WORKSPACE, "local-attempt-workspace-exists"
        ) from exc
    except OSError as exc:
        raise ConfirmedNoEffectError(
            EffectKind.LOCAL_WORKSPACE, "local-attempt-workspace-unavailable"
        ) from exc
    current = os.lstat(directory)
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISDIR(current.st_mode):
        raise ExecutionRuntimeError("new local Attempt workspace is not a real directory")
    try:
        _exclusive_write(
            directory / snapshot.prepared_input_binding.logical_name,
            prepared_input_bytes,
        )
        _exclusive_write(
            directory / snapshot.pbs_template_binding.logical_name,
            pbs_template_bytes,
        )
        os.chmod(directory, 0o500)
    except Exception as exc:
        raise ExecutionRuntimeError(
            "local Attempt workspace was created but its handoff is incomplete"
        ) from exc


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
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
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
    journal = ReceiptJournal(store)
    journal.append(receipt)
    if receipt.effect_state is EffectState.POSSIBLY_EFFECTFUL:
        resolution = ReconciliationResolution.UNRESOLVED
    elif receipt.effect_state is EffectState.CONFIRMED_NO_EFFECT:
        resolution = ReconciliationResolution.NOT_SUBMITTED
    elif receipt.job_id is not None:
        resolution = ReconciliationResolution.SUBMITTED
    else:
        raise ExecutionValueError("confirmed submission reconciliation requires a job_id")
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
