"""In-memory RTwin adapter used only for offline execution-boundary evidence."""

from __future__ import annotations

from threading import Lock

from ._rtwin_minimal import (
    _RTWinMinimalPlan,
    _assert_plan_matches_snapshot,
    _build_rtwin_minimal_plan,
)
from .models import EffectKind, EffectState, ExecutionSnapshot, RemoteEffectReceipt
from .runtime import ConfirmedNoEffectError, PossiblyEffectfulError


class SyntheticRTWinAdapter:
    """Deterministic synthetic adapter with no network or process access."""

    def __init__(
        self,
        *,
        contract_version: str = "synthetic-rtwin-v1",
        job_id: str = "12345.synthetic",
        fail_stage: EffectKind | None = None,
        ambiguous: bool = False,
        reconciliation_state: EffectState = EffectState.POSSIBLY_EFFECTFUL,
        reconciliation_job_id: str | None = None,
    ) -> None:
        self._contract_version = contract_version
        self._job_id = job_id
        self._fail_stage = fail_stage
        self._ambiguous = ambiguous
        self._reconciliation_state = reconciliation_state
        self._reconciliation_job_id = reconciliation_job_id
        self._calls: list[str] = []
        self._submitted_attempts: set[str] = set()
        self._plans: dict[str, _RTWinMinimalPlan] = {}
        self._lock = Lock()

    @property
    def contract_version(self) -> str:
        return self._contract_version

    @property
    def calls(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._calls)

    @property
    def submission_calls(self) -> int:
        with self._lock:
            return sum(call.startswith("submit:") for call in self._calls)

    def _stage(self, kind: EffectKind, call: str) -> None:
        with self._lock:
            self._calls.append(call)
        if self._fail_stage is kind:
            if self._ambiguous:
                raise PossiblyEffectfulError(kind, f"synthetic-{kind.value}-ambiguous")
            raise ConfirmedNoEffectError(kind, f"synthetic-{kind.value}-no-effect")

    def allocate_attempt_workspace(self, snapshot: ExecutionSnapshot) -> str:
        self._stage(
            EffectKind.REMOTE_WORKSPACE,
            f"allocate:{snapshot.attempt_id}",
        )
        return snapshot.workspace_binding.remote_attempt_dir

    def transfer_exact_bytes(
        self,
        snapshot: ExecutionSnapshot,
        prepared_input_bytes: bytes,
        pbs_template_bytes: bytes,
    ) -> None:
        plan = _build_rtwin_minimal_plan(
            snapshot, prepared_input_bytes, pbs_template_bytes
        )
        self._stage(EffectKind.INPUT_TRANSFER, f"transfer:{snapshot.attempt_id}")
        with self._lock:
            existing = self._plans.get(snapshot.attempt_id)
            if existing is not None and existing != plan:
                raise RuntimeError("synthetic adapter refuses a conflicting private plan")
            self._plans[snapshot.attempt_id] = plan

    def submit_once(self, snapshot: ExecutionSnapshot) -> str:
        with self._lock:
            plan = self._plans.get(snapshot.attempt_id)
            if plan is None:
                raise RuntimeError("synthetic adapter requires an exact staged plan")
            if snapshot.attempt_id in self._submitted_attempts:
                raise RuntimeError("synthetic adapter refuses a second submission call")
            self._submitted_attempts.add(snapshot.attempt_id)
        _assert_plan_matches_snapshot(plan, snapshot)
        self._stage(EffectKind.SUBMISSION, f"submit:{snapshot.attempt_id}")
        return self._job_id

    def reconcile_submission(
        self, snapshot: ExecutionSnapshot, *, effect_sequence: int
    ) -> RemoteEffectReceipt:
        with self._lock:
            self._calls.append(f"reconcile:{snapshot.attempt_id}")
        return RemoteEffectReceipt(
            attempt_id=snapshot.attempt_id,
            execution_snapshot_id=snapshot.execution_snapshot_id,
            submission_intent_id=snapshot.submission_intent_id,
            effect_sequence=effect_sequence,
            effect_kind=EffectKind.SUBMISSION_RECONCILIATION,
            effect_state=self._reconciliation_state,
            remote_workspace=snapshot.workspace_binding.remote_attempt_dir,
            job_id=self._reconciliation_job_id,
            details={"source": "synthetic-read-only"},
        )
