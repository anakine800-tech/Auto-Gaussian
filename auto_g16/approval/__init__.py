"""Public, non-effectful Auto-G16 v3 approval authority boundary."""

from .models import (
    ApprovalConflictError,
    ApprovalDecision,
    ApprovalError,
    ApprovalRejectedError,
    ApprovalScopeError,
    ApprovalValueError,
    BatchApprovalMember,
    BatchSubmitApproval,
    ExactOperationalConfirmation,
    ScientificApproval,
    StaleApprovalError,
    validate_effect_authority,
)
from .store import (
    ApprovalPersistenceIntegrityError,
    ApprovalStoreConflictError,
    ApprovalStoreError,
    ApprovalStoreNotFoundError,
    ApprovalStoreSchemaError,
    SQLiteApprovalStore,
)

__all__ = [
    "ApprovalConflictError",
    "ApprovalDecision",
    "ApprovalError",
    "ApprovalRejectedError",
    "ApprovalScopeError",
    "ApprovalPersistenceIntegrityError",
    "ApprovalStoreConflictError",
    "ApprovalStoreError",
    "ApprovalStoreNotFoundError",
    "ApprovalStoreSchemaError",
    "ApprovalValueError",
    "BatchApprovalMember",
    "BatchSubmitApproval",
    "ExactOperationalConfirmation",
    "SQLiteApprovalStore",
    "ScientificApproval",
    "StaleApprovalError",
    "validate_effect_authority",
]
