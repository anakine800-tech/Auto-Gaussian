"""Public offline execution boundary for Auto-G16 v3."""

from ._identity import ExecutionValueError
from .models import (
    EffectKind,
    EffectState,
    ExecutionSnapshot,
    LEGACY_REMOTE_ROOT,
    PbsTemplateBinding,
    PreparedInputBinding,
    RemoteEffectReceipt,
    ResolvedResourceRequest,
    ResolvedServerProfile,
    ServerProfile,
    WorkspaceBinding,
    resolve_server_profile,
)
from .preparation import assert_execution_snapshot_identity, prepare_execution_snapshot
from .runtime import (
    ConfirmedNoEffectError,
    ExecutionAttemptResult,
    ExecutionConflictError,
    ExecutionPort,
    ExecutionRuntimeError,
    PossiblyEffectfulError,
    ReceiptJournal,
    execute_once,
    reconcile_unknown,
    reconcile_unknown_from_receipt,
)
from .synthetic_rtwin import SyntheticRTWinAdapter

__all__ = [
    "ConfirmedNoEffectError",
    "EffectKind",
    "EffectState",
    "ExecutionAttemptResult",
    "ExecutionConflictError",
    "ExecutionPort",
    "ExecutionRuntimeError",
    "ExecutionSnapshot",
    "ExecutionValueError",
    "LEGACY_REMOTE_ROOT",
    "PbsTemplateBinding",
    "PossiblyEffectfulError",
    "PreparedInputBinding",
    "ReceiptJournal",
    "RemoteEffectReceipt",
    "ResolvedResourceRequest",
    "ResolvedServerProfile",
    "ServerProfile",
    "SyntheticRTWinAdapter",
    "WorkspaceBinding",
    "assert_execution_snapshot_identity",
    "execute_once",
    "prepare_execution_snapshot",
    "reconcile_unknown",
    "reconcile_unknown_from_receipt",
    "resolve_server_profile",
]
