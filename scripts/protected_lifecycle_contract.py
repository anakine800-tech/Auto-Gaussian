#!/usr/bin/env python3
"""Owner-sealed, read-only protected lifecycle contract for Auto-G16.

This module composes the exact protected-invocation owner into a future
lifecycle order.  It performs no reservation, materialization, adapter call,
effect, state publication, reconciliation, configuration read, or external
action.
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
import stat
import sys
import threading
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


SCHEMA = "auto-g16-protected-lifecycle-structural-projection/1"
OWNER = "auto-g16-protected-lifecycle-owner"
INVOCATION_SCHEMA = "auto-g16-protected-invocation-bundle/1"
INVOCATION_OWNER_NAME = "protected_invocation_contract"
PROTECTED_SUBMIT_ORDER = (
    "reserve_once",
    "stage_exact_bundle",
    "submit_once",
)
PROTECTED_INVOCATION_ORDER = (
    "reserve_execution_attempt_once",
    "materialize_exact_stage_bytes",
    "transfer_exact_stage_bytes",
    "submit_once",
)
LEGACY_EFFECT_SEQUENCE = (
    "windows_directory_claim",
    "mac_to_windows_copy",
    "windows_sha256",
    "server_directory_claim",
    "windows_to_server_copy",
    "qsub_once",
)
REQUIRED_FUTURE_IMPLEMENTATION_ORDER = (
    "replay_protected_invocation_owner",
    "assert_protected_invocation_current",
    "reserve_protected_submit_once_and_enter_submission_uncertain",
    "materialize_exact_stage_bytes_no_clobber",
    "publish_materialized_local_state",
    "run_fixed_pre_submit_effects_once",
    "replay_effect_time_facts",
    "publish_qsub_invocation_started",
    "run_qsub_once",
    "classify_qsub_outcome",
    "publish_immutable_receipt_if_unique",
    "reconcile_exact_attempt_once",
)
EFFECT_TIME_REVALIDATION = (
    "protected_invocation_owner_identity",
    "protected_submit_authority_and_evidence",
    "local_state_ledger_identity_and_bytes",
    "stage_source_identity_and_bytes",
    "resource_artifacts_and_freshness",
    "live_approval_immediately_before_qsub",
)
SCOPE = {
    "seal": True,
    "read_only_replay": True,
    "reserve": False,
    "materialize": False,
    "invoke_adapter": False,
    "submit": False,
    "status": False,
    "fetch": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
    "arbitrary_command": False,
}
STATUS = {
    "reserved": False,
    "effects_performed": False,
    "local_materialization_implemented": False,
    "state_publication_implemented": False,
    "actual_adapter_verified": False,
    "outcome_implementation_verified": False,
    "reconciliation_implemented": False,
    "live_validation_performed": False,
    "runtime_config_read": False,
    "raw_effect_owner_created": False,
    "automatic_retry": False,
}
LEGACY_COMPATIBILITY = {
    "legacy_cli_unchanged": True,
    "legacy_adapter_remains_fail_closed": True,
    "legacy_pre_reservation_stage_strategy_reusable": False,
    "legacy_caller_path_or_command_strategy_reusable": False,
    "legacy_raw_effect_owner_reusable": False,
    "legacy_job_state_strategy_reusable": False,
    "legacy_reconciliation_implementation_reuse_proven": False,
    "future_long_process_adapter_requires_bounded_owner_lifecycle": True,
    "historical_migration": False,
}
VALIDATION_LAYERS = {
    "structural_validation_only": True,
    "owner_replay_required": True,
    "schema_validity_grants_owner_acceptance": False,
    "schema_validity_grants_seal": False,
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
LIFECYCLE_RE = re.compile(r"^protected-lifecycle-[a-f0-9]{64}$")
_SEAL_TOKEN = object()
_TEST_OWNER_TOKEN = object()
_MODULE_LOCK = threading.RLock()
_MISSING_MODULE = object()
_OWNER_READ_CHUNK_SIZE = 64 * 1024
_MAX_OWNER_SOURCE_BYTES = 3 * 1024 * 1024
_OWNER_STAT_FIELDS = (
    "st_dev",
    "st_ino",
    "st_uid",
    "st_mode",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


class ProtectedLifecycleError(ValueError):
    """The non-executable lifecycle closure cannot be proved."""


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
        raise ProtectedLifecycleError(
            f"protected lifecycle value is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ProtectedLifecycleError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise ProtectedLifecycleError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if (
        isinstance(value, float)
        and value.is_integer()
        and value >= minimum
    ):
        return int(value)
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
    ):
        raise ProtectedLifecycleError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _adjacent_invocation_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    path = here.with_name(f"{INVOCATION_OWNER_NAME}.py")
    if path.parent != here.parent:
        raise ImportError("protected invocation owner is not adjacent")
    return path


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return tuple(getattr(info, name) for name in _OWNER_STAT_FIELDS)


@dataclass(frozen=True, slots=True)
class _OwnerFileSnapshot:
    canonical_path: Path
    device: int
    inode: int
    uid: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int
    sha256: str
    source_bytes: bytes

    def identity(self) -> tuple[int, ...]:
        return (
            self.device,
            self.inode,
            self.uid,
            self.mode,
            self.size,
            self.mtime_ns,
            self.ctime_ns,
        )


def _stable_invocation_owner_snapshot() -> _OwnerFileSnapshot:
    path = _adjacent_invocation_path()
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedLifecycleError(
                "protected invocation owner must be a no-follow regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedLifecycleError(
                "protected invocation owner changed while opening"
            )
        if (
            opened.st_size < 1
            or opened.st_size > _MAX_OWNER_SOURCE_BYTES
        ):
            raise ProtectedLifecycleError(
                "protected invocation owner size is outside the fixed bound"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, _OWNER_READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        after_descriptor = os.fstat(descriptor)
        after_path = os.stat(path, follow_symlinks=False)
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, ProtectedLifecycleError):
            raise
        raise ProtectedLifecycleError(
            f"protected invocation owner stable read failed closed: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    identities = (
        _stat_identity(before),
        _stat_identity(opened),
        _stat_identity(after_descriptor),
        _stat_identity(after_path),
    )
    if len(set(identities)) != 1:
        raise ProtectedLifecycleError(
            "protected invocation owner identity drifted during stable read"
        )
    source_bytes = b"".join(chunks)
    if len(source_bytes) != opened.st_size:
        raise ProtectedLifecycleError(
            "protected invocation owner stable read was short"
        )
    canonical_path = path.resolve(strict=True)
    if canonical_path != path:
        raise ProtectedLifecycleError(
            "protected invocation owner canonical path differs"
        )
    return _OwnerFileSnapshot(
        canonical_path=canonical_path,
        device=opened.st_dev,
        inode=opened.st_ino,
        uid=opened.st_uid,
        mode=opened.st_mode,
        size=opened.st_size,
        mtime_ns=opened.st_mtime_ns,
        ctime_ns=opened.st_ctime_ns,
        sha256=hashlib.sha256(source_bytes).hexdigest(),
        source_bytes=source_bytes,
    )


def _assert_owner_snapshot_integrity(snapshot: _OwnerFileSnapshot) -> None:
    if (
        snapshot.canonical_path != _adjacent_invocation_path()
        or snapshot.size != len(snapshot.source_bytes)
        or hashlib.sha256(snapshot.source_bytes).hexdigest()
        != snapshot.sha256
        or not stat.S_ISREG(snapshot.mode)
    ):
        raise ProtectedLifecycleError(
            "protected invocation owner sealed snapshot differs"
        )


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_spec = getattr(getattr(module, "__spec__", None), "origin", None)
    if (
        not isinstance(raw_file, str)
        or not raw_file
        or not isinstance(raw_spec, str)
        or not raw_spec
    ):
        raise ImportError("protected invocation owner has no resolved origin")
    return Path(raw_file).resolve(), Path(raw_spec).resolve()


@contextlib.contextmanager
def _exact_invocation_owner(
    *,
    snapshot: _OwnerFileSnapshot | None = None,
    required_module: types.ModuleType | None = None,
) -> Iterator[types.ModuleType]:
    if snapshot is None:
        snapshot = _stable_invocation_owner_snapshot()
    path = _adjacent_invocation_path()
    if snapshot.canonical_path != path:
        raise ImportError("protected invocation owner snapshot origin differs")
    _assert_owner_snapshot_integrity(snapshot)
    code = compile(
        snapshot.source_bytes,
        str(path),
        "exec",
        dont_inherit=True,
    )
    with _MODULE_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(
            INVOCATION_OWNER_NAME,
            _MISSING_MODULE,
        )
        try:
            if required_module is not None:
                if previous is not required_module:
                    raise ImportError(
                        "protected invocation owner module identity differs"
                    )
                if _module_origin(required_module) != (path, path):
                    raise ImportError(
                        "protected invocation owner origin changed"
                    )
                yield required_module
                return
            sys.modules.pop(INVOCATION_OWNER_NAME, None)
            spec = importlib.util.spec_from_file_location(
                INVOCATION_OWNER_NAME,
                path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    "exact protected invocation owner cannot load"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[INVOCATION_OWNER_NAME] = module
            exec(code, module.__dict__)
            if _module_origin(module) != (path, path):
                raise ImportError(
                    "protected invocation owner origin changed"
                )
            yield module
        finally:
            sys.modules.pop(INVOCATION_OWNER_NAME, None)
            if previous is not _MISSING_MODULE:
                sys.modules[INVOCATION_OWNER_NAME] = previous
            _imp.release_lock()


def _typed_invocation_evidence(
    module: types.ModuleType,
    evidence: object,
) -> object:
    expected_type = module.ProtectedInvocationEvidence
    if type(evidence) is not expected_type:
        raise TypeError(
            "ProtectedInvocationEvidence must come from the exact adjacent owner"
        )
    return evidence


def _snapshot_invocation_evidence(
    module: types.ModuleType,
    evidence: object,
) -> object:
    """Take an owner-owned deep snapshot after exact class-identity proof."""

    exact = _typed_invocation_evidence(module, evidence)
    try:
        first = copy.deepcopy(exact)
        second = copy.deepcopy(exact)
    except Exception as exc:
        raise TypeError(
            f"ProtectedInvocationEvidence snapshot failed closed: {exc}"
        ) from exc
    if (
        type(first) is not module.ProtectedInvocationEvidence
        or type(second) is not module.ProtectedInvocationEvidence
        or first != second
    ):
        raise TypeError(
            "ProtectedInvocationEvidence changed during owner snapshot"
        )
    return first


@contextlib.contextmanager
def _bind_invocation_clock(
    module: types.ModuleType,
    current: datetime,
) -> Iterator[None]:
    original = module._utc_now
    module._utc_now = lambda: current
    try:
        yield
    finally:
        module._utc_now = original


def _invocation_projection(
    invocation_document: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": invocation_document["schema"],
        "invocation_id": invocation_document["invocation_id"],
        "invocation_payload_sha256": invocation_document[
            "invocation_payload_sha256"
        ],
        "ledger_identity_sha256": invocation_document["ledger"][
            "ledger_identity_sha256"
        ],
        "stage_manifest_sha256": invocation_document["stage_plan"][
            "manifest_sha256"
        ],
        "stage_artifact_count": invocation_document["stage_plan"][
            "artifact_count"
        ],
    }


def validate_protected_lifecycle_structure(
    value: Any,
) -> dict[str, Any]:
    """Validate only the constraints expressible by the public Draft Schema."""

    document = copy.deepcopy(value)
    canonical_bytes(document)
    document = _exact(
        document,
        {
            "schema",
            "semantic_owner_required",
            "validation",
            "lifecycle_id",
            "protected_invocation_projection",
            "protected_submit_order",
            "protected_invocation_order",
            "legacy_effect_sequence",
            "required_future_implementation_order",
            "effect_time_revalidation",
            "scope",
            "status",
            "legacy_compatibility",
            "structural_projection_sha256",
        },
        "protected lifecycle structural projection",
    )
    if (
        document["schema"] != SCHEMA
        or document["semantic_owner_required"] != OWNER
    ):
        raise ProtectedLifecycleError(
            "protected lifecycle structural schema/owner declaration differs"
        )
    if document["validation"] != VALIDATION_LAYERS:
        raise ProtectedLifecycleError(
            "protected lifecycle validation-layer markers differ"
        )
    if (
        not isinstance(document["lifecycle_id"], str)
        or LIFECYCLE_RE.fullmatch(document["lifecycle_id"]) is None
    ):
        raise ProtectedLifecycleError("protected lifecycle ID is malformed")
    projection = _exact(
        document["protected_invocation_projection"],
        {
            "schema",
            "invocation_id",
            "invocation_payload_sha256",
            "ledger_identity_sha256",
            "stage_manifest_sha256",
            "stage_artifact_count",
        },
        "protected invocation structural projection",
    )
    if projection["schema"] != INVOCATION_SCHEMA:
        raise ProtectedLifecycleError(
            "protected invocation schema declaration differs"
        )
    if (
        not isinstance(projection["invocation_id"], str)
        or re.fullmatch(
            r"^protected-invocation-[a-f0-9]{64}$",
            projection["invocation_id"],
        )
        is None
    ):
        raise ProtectedLifecycleError(
            "protected invocation ID is malformed"
        )
    for field in (
        "invocation_payload_sha256",
        "ledger_identity_sha256",
        "stage_manifest_sha256",
    ):
        _sha(projection[field], f"protected invocation {field}")
    projection["stage_artifact_count"] = _integer(
        projection["stage_artifact_count"],
        "protected invocation stage_artifact_count",
        minimum=1,
    )
    exact_lists = (
        ("protected_submit_order", PROTECTED_SUBMIT_ORDER),
        ("protected_invocation_order", PROTECTED_INVOCATION_ORDER),
        ("legacy_effect_sequence", LEGACY_EFFECT_SEQUENCE),
        (
            "required_future_implementation_order",
            REQUIRED_FUTURE_IMPLEMENTATION_ORDER,
        ),
        ("effect_time_revalidation", EFFECT_TIME_REVALIDATION),
    )
    for field, expected in exact_lists:
        if document[field] != list(expected):
            raise ProtectedLifecycleError(
                f"protected lifecycle {field} differs"
            )
    if document["scope"] != SCOPE:
        raise ProtectedLifecycleError(
            "protected lifecycle scope differs"
        )
    if document["status"] != STATUS:
        raise ProtectedLifecycleError(
            "protected lifecycle status differs"
        )
    if document["legacy_compatibility"] != LEGACY_COMPATIBILITY:
        raise ProtectedLifecycleError(
            "protected lifecycle legacy compatibility differs"
        )
    _sha(
        document["structural_projection_sha256"],
        "protected lifecycle structural projection",
    )
    return copy.deepcopy(document)


def _finalize_owner_projection(
    document: dict[str, Any],
) -> dict[str, Any]:
    result = copy.deepcopy(document)
    result["structural_projection_sha256"] = digest(
        {
            key: item
            for key, item in result.items()
            if key != "structural_projection_sha256"
        }
    )
    return result


def _validate_owner_projection(
    value: Any,
    invocation_document: dict[str, Any],
) -> dict[str, Any]:
    """Bind a structural projection to an actual owner-replayed PR4F bundle."""

    document = validate_protected_lifecycle_structure(value)
    expected_projection = _invocation_projection(invocation_document)
    if document["protected_invocation_projection"] != expected_projection:
        raise ProtectedLifecycleError(
            "protected invocation owner projection differs"
        )
    invocation = expected_projection
    lifecycle_seed = digest(
        {
            "schema": "auto-g16-protected-lifecycle-id/1",
            "invocation_payload_sha256": invocation["invocation_payload_sha256"],
            "ledger_identity_sha256": invocation["ledger_identity_sha256"],
            "stage_manifest_sha256": invocation["stage_manifest_sha256"],
        }
    )
    if document["lifecycle_id"] != f"protected-lifecycle-{lifecycle_seed}":
        raise ProtectedLifecycleError(
            "protected lifecycle ID binding differs"
        )
    expected_projection_hash = digest(
        {
            key: item
            for key, item in document.items()
            if key != "structural_projection_sha256"
        }
    )
    if (
        document["structural_projection_sha256"]
        != expected_projection_hash
    ):
        raise ProtectedLifecycleError(
            "protected lifecycle structural projection hash differs"
        )
    return copy.deepcopy(document)


@dataclass(frozen=True, slots=True)
class ProtectedLifecycleEvidence:
    """One exact typed PR4F input; no caller path, state, plan, or effect."""

    protected_invocation_evidence: object


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedLifecycleContract:
    """Owner-issued portable contract plus exact in-process PR4F state."""

    _canonical_document: bytes
    protected_invocation_bundle: object
    protected_invocation_evidence: object
    _invocation_owner_module: types.ModuleType
    _invocation_owner_snapshot: _OwnerFileSnapshot
    lifecycle_id: str
    structural_projection_sha256: str
    _testing: bool
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedLifecycleContract":
        raise TypeError(
            "SealedProtectedLifecycleContract is issued only by its owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        protected_invocation_bundle: object,
        protected_invocation_evidence: object,
        invocation_owner_module: types.ModuleType,
        invocation_owner_snapshot: _OwnerFileSnapshot,
        *,
        testing: bool,
        token: object,
    ) -> "SealedProtectedLifecycleContract":
        if token is not _SEAL_TOKEN:
            raise ProtectedLifecycleError(
                "protected lifecycle seal differs"
            )
        protected_invocation_bundle.assert_owner_sealed()
        _assert_owner_snapshot_integrity(invocation_owner_snapshot)
        validated = _validate_owner_projection(
            document,
            protected_invocation_bundle.document(),
        )
        value = object.__new__(cls)
        for name, item in {
            "_canonical_document": canonical_bytes(validated),
            "protected_invocation_bundle": protected_invocation_bundle,
            "protected_invocation_evidence": (
                protected_invocation_evidence
            ),
            "_invocation_owner_module": invocation_owner_module,
            "_invocation_owner_snapshot": invocation_owner_snapshot,
            "lifecycle_id": validated["lifecycle_id"],
            "structural_projection_sha256": validated[
                "structural_projection_sha256"
            ],
            "_testing": testing,
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def __copy__(self) -> "SealedProtectedLifecycleContract":
        raise TypeError("protected lifecycle sealed capability is not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedLifecycleContract":
        del memo
        raise TypeError("protected lifecycle sealed capability is not clonable")

    def __reduce__(self) -> object:
        raise TypeError(
            "protected lifecycle sealed capability is not serializable"
        )

    def assert_owner_sealed(self) -> None:
        if self._seal is not _SEAL_TOKEN:
            raise ProtectedLifecycleError(
                "protected lifecycle seal differs"
            )
        self.protected_invocation_bundle.assert_owner_sealed()
        _assert_owner_snapshot_integrity(
            self._invocation_owner_snapshot
        )
        document = _validate_owner_projection(
            self.document(),
            self.protected_invocation_bundle.document(),
        )
        if (
            document["lifecycle_id"] != self.lifecycle_id
            or document["structural_projection_sha256"]
            != self.structural_projection_sha256
        ):
            raise ProtectedLifecycleError(
                "protected lifecycle sealed projection differs"
            )

    def assert_current(self) -> "SealedProtectedLifecycleContract":
        self.assert_owner_sealed()
        current_snapshot = _stable_invocation_owner_snapshot()
        if current_snapshot != self._invocation_owner_snapshot:
            raise ProtectedLifecycleError(
                "protected invocation owner identity differs"
            )
        current = _trusted_now(_utc_now)
        with _exact_invocation_owner(
            snapshot=current_snapshot,
            required_module=self._invocation_owner_module,
        ) as invocation:
            try:
                exact_evidence = _typed_invocation_evidence(
                    invocation,
                    self.protected_invocation_evidence,
                )
                with _bind_invocation_clock(invocation, current):
                    replay = (
                        _invocation_owner(
                            invocation,
                            current,
                            testing=self._testing,
                        )
                        .seal(exact_evidence)
                    )
                    replay.assert_owner_sealed()
                    replay.assert_current()
            except Exception as exc:
                raise ProtectedLifecycleError(
                    "protected invocation current replay failed closed: "
                    f"{exc}"
                ) from exc
            replay_document = replay.document()
        if (
            replay_document
            != self.protected_invocation_bundle.document()
            or _invocation_projection(replay_document)
            != self.document()["protected_invocation_projection"]
        ):
            raise ProtectedLifecycleError(
                "protected invocation complete replay differs"
            )
        if (
            _stable_invocation_owner_snapshot()
            != self._invocation_owner_snapshot
        ):
            raise ProtectedLifecycleError(
                "protected invocation owner identity differs"
            )
        return self


class ProtectedLifecycleContractOwner:
    """Seal one read-only future lifecycle from exact typed PR4F evidence."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        _factory_token: object,
    ) -> None:
        if _factory_token not in {_SEAL_TOKEN, _TEST_OWNER_TOKEN}:
            raise TypeError(
                "ProtectedLifecycleContractOwner requires a fixed factory"
            )
        self._clock = clock
        self._testing = _factory_token is _TEST_OWNER_TOKEN

    @classmethod
    def production(cls) -> "ProtectedLifecycleContractOwner":
        return cls(clock=_utc_now, _factory_token=_SEAL_TOKEN)

    @classmethod
    def _for_testing_with_clock(
        cls,
        clock: Callable[[], datetime],
        *,
        _test_token: object,
    ) -> "ProtectedLifecycleContractOwner":
        if _test_token is not _TEST_OWNER_TOKEN:
            raise TypeError("private lifecycle test factory token differs")
        return cls(clock=clock, _factory_token=_TEST_OWNER_TOKEN)

    def seal(
        self,
        evidence: ProtectedLifecycleEvidence,
    ) -> SealedProtectedLifecycleContract:
        if type(evidence) is not ProtectedLifecycleEvidence:
            raise ProtectedLifecycleError(
                "protected lifecycle evidence must use the typed owner input"
            )
        raw_invocation_evidence = evidence.protected_invocation_evidence
        owner_snapshot = _stable_invocation_owner_snapshot()
        invocation_module = sys.modules.get(INVOCATION_OWNER_NAME)
        if not isinstance(invocation_module, types.ModuleType):
            raise ProtectedLifecycleError(
                "exact adjacent protected invocation owner must already "
                "own the typed evidence"
            )
        current = _trusted_now(self._clock)
        with _exact_invocation_owner(
            snapshot=owner_snapshot,
            required_module=invocation_module,
        ) as invocation:
            try:
                exact_evidence = _snapshot_invocation_evidence(
                    invocation,
                    raw_invocation_evidence,
                )
                with _bind_invocation_clock(invocation, current):
                    protected_invocation = (
                        _invocation_owner(
                            invocation,
                            current,
                            testing=self._testing,
                        )
                        .seal(exact_evidence)
                    )
                    protected_invocation.assert_owner_sealed()
                    protected_invocation.assert_current()
            except Exception as exc:
                raise ProtectedLifecycleError(
                    "protected invocation owner rejected lifecycle evidence: "
                    f"{exc}"
                ) from exc
            invocation_document = protected_invocation.document()
        if _stable_invocation_owner_snapshot() != owner_snapshot:
            raise ProtectedLifecycleError(
                "protected invocation owner identity differs during seal"
            )
        lifecycle_seed = digest(
            {
                "schema": "auto-g16-protected-lifecycle-id/1",
                "invocation_payload_sha256": invocation_document[
                    "invocation_payload_sha256"
                ],
                "ledger_identity_sha256": invocation_document["ledger"][
                    "ledger_identity_sha256"
                ],
                "stage_manifest_sha256": invocation_document[
                    "stage_plan"
                ]["manifest_sha256"],
            }
        )
        document = _finalize_owner_projection(
            {
                "schema": SCHEMA,
                "semantic_owner_required": OWNER,
                "validation": copy.deepcopy(VALIDATION_LAYERS),
                "lifecycle_id": (
                    f"protected-lifecycle-{lifecycle_seed}"
                ),
                "protected_invocation_projection": (
                    _invocation_projection(invocation_document)
                ),
                "protected_submit_order": list(PROTECTED_SUBMIT_ORDER),
                "protected_invocation_order": list(
                    PROTECTED_INVOCATION_ORDER
                ),
                "legacy_effect_sequence": list(
                    LEGACY_EFFECT_SEQUENCE
                ),
                "required_future_implementation_order": list(
                    REQUIRED_FUTURE_IMPLEMENTATION_ORDER
                ),
                "effect_time_revalidation": list(
                    EFFECT_TIME_REVALIDATION
                ),
                "scope": copy.deepcopy(SCOPE),
                "status": copy.deepcopy(STATUS),
                "legacy_compatibility": copy.deepcopy(
                    LEGACY_COMPATIBILITY
                ),
                "structural_projection_sha256": "",
            }
        )
        sealed = SealedProtectedLifecycleContract._from_owner(
            document,
            protected_invocation,
            exact_evidence,
            invocation_module,
            owner_snapshot,
            testing=self._testing,
            token=_SEAL_TOKEN,
        )
        final_current = _trusted_now(self._clock)
        try:
            with _bind_invocation_clock(invocation, final_current):
                protected_invocation.assert_current()
        except Exception as exc:
            raise ProtectedLifecycleError(
                "protected invocation final local/stage replay failed closed: "
                f"{exc}"
            ) from exc
        if _stable_invocation_owner_snapshot() != owner_snapshot:
            raise ProtectedLifecycleError(
                "protected invocation owner identity differs before final seal"
            )
        sealed.assert_owner_sealed()
        return sealed


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    current = clock()
    if (
        not isinstance(current, datetime)
        or current.tzinfo is None
        or current.utcoffset() is None
    ):
        raise ProtectedLifecycleError(
            "protected lifecycle owner clock must return aware UTC"
        )
    return current.astimezone(timezone.utc)


def _invocation_owner(
    module: types.ModuleType,
    current: datetime,
    *,
    testing: bool,
) -> object:
    if testing:
        return (
            module.ProtectedInvocationContractOwner
            ._for_testing_with_clock(
                lambda: current,
                _test_token=module._TEST_OWNER_TOKEN,
            )
        )
    return module.ProtectedInvocationContractOwner.production()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
