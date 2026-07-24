"""Backend-neutral facade for the sole Auto-G16 v2.6 legacy backend."""

from __future__ import annotations

import _imp
import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import os
import stat
import sys
import threading
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Protocol

from execution_models import (
    AttestationBoundaryPlan,
    CommandPlan,
    ExactResourceTuple,
    ValidatedRuntimePlan,
    WorkspacePaths,
)

if TYPE_CHECKING:
    from local_state_binding import (
        LocalStateBindingEvidence,
        LocalStatePaths,
        SealedLocalStateBinding,
    )
    from protected_invocation_contract import (
        ProtectedInvocationEvidence,
        SealedProtectedInvocationBundle,
    )
    from protected_lifecycle_contract import ProtectedLifecycleEvidence
    from protected_local_materialization import (
        SealedProtectedLocalMaterialization,
    )
    from protected_legacy_effect_handoff import (
        SealedProtectedLegacyEffectHandoff,
    )
    from protected_submit_contract import (
        ProtectedSubmitContractOwner,
        ProtectedSubmitEvidence,
        ReservedProtectedSubmitBundle,
        SealedProtectedSubmitBundle,
    )


_PROTECTED_SUBMIT_MODULE_NAME = "protected_submit_contract"
_PROTECTED_SUBMIT_IMPORT_LOCK = threading.RLock()
_MISSING_MODULE = object()
_LOCAL_STATE_MODULE_NAME = "local_state_binding"
_LOCAL_STATE_IMPORT_LOCK = threading.RLock()
_PROTECTED_INVOCATION_MODULE_NAME = "protected_invocation_contract"
_PROTECTED_INVOCATION_IMPORT_LOCK = threading.RLock()
_PROTECTED_LOCAL_MATERIALIZATION_MODULE_NAME = (
    "protected_local_materialization"
)
_PROTECTED_LOCAL_MATERIALIZATION_IMPORT_LOCK = threading.RLock()
_PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE: types.ModuleType | None = None
_PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256: str | None = None
_LEGACY_IMPLEMENTATION_MODULE_NAME = "legacy_rtwin_pbs"
_LEGACY_IMPLEMENTATION_IMPORT_LOCK = threading.RLock()
_LEGACY_IMPLEMENTATION_BOUND_MODULE: types.ModuleType | None = None
_LEGACY_IMPLEMENTATION_SOURCE_SHA256: str | None = None
_PROTECTED_LEGACY_HANDOFF_MODULE_NAME = (
    "protected_legacy_effect_handoff"
)
_PROTECTED_LEGACY_HANDOFF_IMPORT_LOCK = threading.RLock()


def _protected_submit_contract_path() -> Path:
    facade = Path(__file__).resolve()
    path = facade.with_name(f"{_PROTECTED_SUBMIT_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(
            f"exact adjacent protected-submit owner is unavailable: {path}"
        )
    resolved = path.resolve()
    if resolved.parent != facade.parent:
        raise ImportError("protected-submit owner is not adjacent to the facade")
    return resolved


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    spec = getattr(module, "__spec__", None)
    raw_spec_origin = getattr(spec, "origin", None)
    if (
        not isinstance(raw_file, str)
        or not raw_file
        or not isinstance(raw_spec_origin, str)
        or not raw_spec_origin
    ):
        raise ImportError("protected-submit owner has no resolved origin")
    return Path(raw_file).resolve(), Path(raw_spec_origin).resolve()


_SourceFileIdentity = tuple[int, int, int, int, int, int]


def _source_file_identity(info: os.stat_result) -> _SourceFileIdentity:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
    )


def _stable_exact_module_source(
    path: Path,
    *,
    label: str,
) -> tuple[bytes, _SourceFileIdentity]:
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ImportError(f"{label} is not an exact regular file")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _source_file_identity(opened) != _source_file_identity(before):
                raise ImportError(f"{label} changed before exact read")
            source_bytes = handle.read()
            after_read = os.fstat(handle.fileno())
        current = path.lstat()
    except OSError as exc:
        raise ImportError(f"{label} cannot be read exactly") from exc
    identity = _source_file_identity(opened)
    if (
        _source_file_identity(after_read) != identity
        or _source_file_identity(current) != identity
        or len(source_bytes) != opened.st_size
    ):
        raise ImportError(f"{label} changed during exact read")
    return source_bytes, identity


def _assert_exact_module_source_current(
    path: Path,
    *,
    label: str,
    source_bytes: bytes,
    identity: _SourceFileIdentity,
) -> None:
    current_bytes, current_identity = _stable_exact_module_source(
        path,
        label=label,
    )
    if current_identity != identity or current_bytes != source_bytes:
        raise ImportError(f"{label} changed during exact load")


def _load_exact_source_module(
    name: str,
    path: Path,
    *,
    label: str,
) -> tuple[types.ModuleType, str]:
    source_bytes, identity = _stable_exact_module_source(path, label=label)
    code = compile(
        source_bytes,
        str(path),
        "exec",
        dont_inherit=True,
    )
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"{label} cannot be loaded: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        exec(code, module.__dict__)
        _assert_exact_module_source_current(
            path,
            label=label,
            source_bytes=source_bytes,
            identity=identity,
        )
        if _module_origin(module) != (path, path):
            raise ImportError(f"{label} origin changed")
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module, hashlib.sha256(source_bytes).hexdigest()


@contextlib.contextmanager
def _exact_protected_submit_contract() -> Iterator[types.ModuleType]:
    """Load only the exact adjacent owner and restore its generic cache entry."""

    path = _protected_submit_contract_path()
    with _PROTECTED_SUBMIT_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(
            _PROTECTED_SUBMIT_MODULE_NAME,
            _MISSING_MODULE,
        )
        try:
            sys.modules.pop(_PROTECTED_SUBMIT_MODULE_NAME, None)
            spec = importlib.util.spec_from_file_location(
                _PROTECTED_SUBMIT_MODULE_NAME,
                path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"exact protected-submit owner cannot be loaded: {path}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[_PROTECTED_SUBMIT_MODULE_NAME] = module
            spec.loader.exec_module(module)
            file_origin, spec_origin = _module_origin(module)
            if file_origin != path or spec_origin != path:
                raise ImportError(
                    "protected-submit owner origin changed during exact load"
                )
            yield module
        finally:
            sys.modules.pop(_PROTECTED_SUBMIT_MODULE_NAME, None)
            if previous is not _MISSING_MODULE:
                sys.modules[_PROTECTED_SUBMIT_MODULE_NAME] = previous
            _imp.release_lock()


def _evidence_for_exact_owner(
    contract: types.ModuleType,
    evidence: object,
) -> object:
    expected = _protected_submit_contract_path()
    expected_type = contract.ProtectedSubmitEvidence
    if isinstance(evidence, expected_type):
        return evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    code = getattr(snapshot_method, "__code__", None)
    raw_source = getattr(code, "co_filename", None)
    if not isinstance(raw_source, str) or Path(raw_source).resolve() != expected:
        raise TypeError(
            "protected-submit evidence must come from the facade-adjacent owner"
        )
    snapshot = evidence.snapshot()
    fields = tuple(expected_type.__dataclass_fields__)
    if any(not hasattr(snapshot, field) for field in fields):
        raise TypeError("protected-submit evidence fields differ")
    return expected_type(**{field: getattr(snapshot, field) for field in fields})


def _local_state_contract_path() -> Path:
    facade = Path(__file__).resolve()
    path = facade.with_name(f"{_LOCAL_STATE_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(
            f"exact adjacent local-state owner is unavailable: {path}"
        )
    resolved = path.resolve()
    if resolved.parent != facade.parent:
        raise ImportError("local-state owner is not adjacent to the facade")
    return resolved


@contextlib.contextmanager
def _exact_local_state_contract() -> Iterator[types.ModuleType]:
    """Load only the exact adjacent local-state owner and restore its cache."""

    path = _local_state_contract_path()
    with _LOCAL_STATE_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(
            _LOCAL_STATE_MODULE_NAME,
            _MISSING_MODULE,
        )
        try:
            sys.modules.pop(_LOCAL_STATE_MODULE_NAME, None)
            spec = importlib.util.spec_from_file_location(
                _LOCAL_STATE_MODULE_NAME,
                path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    f"exact local-state owner cannot be loaded: {path}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[_LOCAL_STATE_MODULE_NAME] = module
            spec.loader.exec_module(module)
            file_origin, spec_origin = _module_origin(module)
            if file_origin != path or spec_origin != path:
                raise ImportError(
                    "local-state owner origin changed during exact load"
                )
            yield module
        finally:
            sys.modules.pop(_LOCAL_STATE_MODULE_NAME, None)
            if previous is not _MISSING_MODULE:
                sys.modules[_LOCAL_STATE_MODULE_NAME] = previous
            _imp.release_lock()


def _local_state_evidence_for_exact_owner(
    contract: types.ModuleType,
    evidence: object,
) -> object:
    expected = _local_state_contract_path()
    expected_type = contract.LocalStateBindingEvidence
    if isinstance(evidence, expected_type):
        return evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    code = getattr(snapshot_method, "__code__", None)
    raw_source = getattr(code, "co_filename", None)
    if not isinstance(raw_source, str) or Path(raw_source).resolve() != expected:
        raise TypeError(
            "local-state evidence must come from the facade-adjacent owner"
        )
    snapshot = evidence.snapshot()
    fields = tuple(expected_type.__dataclass_fields__)
    if any(not hasattr(snapshot, field) for field in fields):
        raise TypeError("local-state evidence fields differ")
    return expected_type(
        **{field: getattr(snapshot, field) for field in fields}
    )


def _protected_invocation_contract_path() -> Path:
    facade = Path(__file__).resolve()
    filename = f"{_PROTECTED_INVOCATION_MODULE_NAME}.py"
    skill_directory = facade.parent.parent
    if (
        facade.parent.name == "scripts"
        and skill_directory.name == "auto-g16-rtwin-pbs"
        and skill_directory.parent.name == "skills"
    ):
        source_owner = (
            skill_directory.parent.parent / "scripts" / filename
        )
        if (
            not source_owner.is_symlink()
            and source_owner.is_file()
            and source_owner.resolve().parent
            == skill_directory.parent.parent.resolve() / "scripts"
        ):
            return source_owner.resolve()

    adjacent_owner = facade.with_name(filename)
    if (
        not adjacent_owner.is_symlink()
        and adjacent_owner.is_file()
        and adjacent_owner.resolve().parent == facade.parent
    ):
        return adjacent_owner.resolve()
    raise ImportError(
        "exact protected-invocation owner is unavailable in repository "
        f"source or deployed-package layout for facade {facade}"
    )


@contextlib.contextmanager
def _exact_protected_invocation_contract() -> Iterator[types.ModuleType]:
    """Load the layout-bound invocation owner and restore its cache."""

    path = _protected_invocation_contract_path()
    with _PROTECTED_INVOCATION_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(
            _PROTECTED_INVOCATION_MODULE_NAME,
            _MISSING_MODULE,
        )
        try:
            sys.modules.pop(_PROTECTED_INVOCATION_MODULE_NAME, None)
            spec = importlib.util.spec_from_file_location(
                _PROTECTED_INVOCATION_MODULE_NAME,
                path,
            )
            if spec is None or spec.loader is None:
                raise ImportError(
                    "exact protected-invocation owner cannot be loaded: "
                    f"{path}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[_PROTECTED_INVOCATION_MODULE_NAME] = module
            spec.loader.exec_module(module)
            file_origin, spec_origin = _module_origin(module)
            if file_origin != path or spec_origin != path:
                raise ImportError(
                    "protected-invocation owner origin changed during exact load"
                )
            yield module
        finally:
            sys.modules.pop(_PROTECTED_INVOCATION_MODULE_NAME, None)
            if previous is not _MISSING_MODULE:
                sys.modules[_PROTECTED_INVOCATION_MODULE_NAME] = previous
            _imp.release_lock()


def _protected_invocation_evidence_for_exact_owner(
    contract: types.ModuleType,
    evidence: object,
) -> object:
    expected = _protected_invocation_contract_path()
    expected_type = contract.ProtectedInvocationEvidence
    if isinstance(evidence, expected_type):
        return evidence
    snapshot_method = getattr(type(evidence), "snapshot", None)
    code = getattr(snapshot_method, "__code__", None)
    raw_source = getattr(code, "co_filename", None)
    if not isinstance(raw_source, str) or Path(raw_source).resolve() != expected:
        raise TypeError(
            "protected-invocation evidence must come from the "
            "facade-bound owner"
        )
    snapshot = evidence.snapshot()
    fields = tuple(expected_type.__dataclass_fields__)
    if any(not hasattr(snapshot, field) for field in fields):
        raise TypeError("protected-invocation evidence fields differ")
    return expected_type(
        **{field: getattr(snapshot, field) for field in fields}
    )


def _protected_local_materialization_path() -> Path:
    facade = Path(__file__).resolve()
    filename = f"{_PROTECTED_LOCAL_MATERIALIZATION_MODULE_NAME}.py"
    skill_directory = facade.parent.parent
    if (
        facade.parent.name == "scripts"
        and skill_directory.name == "auto-g16-rtwin-pbs"
        and skill_directory.parent.name == "skills"
    ):
        source_owner = (
            skill_directory.parent.parent / "scripts" / filename
        )
        if (
            not source_owner.is_symlink()
            and source_owner.is_file()
            and source_owner.resolve().parent
            == skill_directory.parent.parent.resolve() / "scripts"
        ):
            return source_owner.resolve()

    adjacent_owner = facade.with_name(filename)
    if (
        not adjacent_owner.is_symlink()
        and adjacent_owner.is_file()
        and adjacent_owner.resolve().parent == facade.parent
    ):
        return adjacent_owner.resolve()
    raise ImportError(
        "exact protected local-materialization owner is unavailable in "
        "repository source or deployed-package layout"
    )


@contextlib.contextmanager
def _exact_protected_local_materialization() -> Iterator[types.ModuleType]:
    """Load the layout-bound materialization owner and restore its cache."""

    global _PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE
    global _PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256

    path = _protected_local_materialization_path()
    name = _PROTECTED_LOCAL_MATERIALIZATION_MODULE_NAME
    with _PROTECTED_LOCAL_MATERIALIZATION_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(name, _MISSING_MODULE)
        try:
            module = _PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE
            if module is None:
                sys.modules.pop(name, None)
                module, source_sha256 = _load_exact_source_module(
                    name,
                    path,
                    label="protected local-materialization owner",
                )
                _PROTECTED_LOCAL_MATERIALIZATION_BOUND_MODULE = module
                _PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256 = source_sha256
            else:
                source_bytes, _identity = _stable_exact_module_source(
                    path,
                    label="protected local-materialization owner",
                )
                source_sha256 = hashlib.sha256(source_bytes).hexdigest()
                if (
                    source_sha256
                    != _PROTECTED_LOCAL_MATERIALIZATION_SOURCE_SHA256
                ):
                    raise ImportError(
                        "protected local-materialization owner bytes changed "
                        "after exact binding"
                    )
            sys.modules[name] = module
            file_origin, spec_origin = _module_origin(module)
            if file_origin != path or spec_origin != path:
                raise ImportError(
                    "protected local-materialization owner origin changed"
                )
            yield module
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
            _imp.release_lock()


def _legacy_implementation_path() -> Path:
    facade = Path(__file__).resolve()
    path = facade.with_name(f"{_LEGACY_IMPLEMENTATION_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError("exact adjacent legacy implementation is unavailable")
    resolved = path.resolve()
    if resolved.parent != facade.parent:
        raise ImportError("legacy implementation is not adjacent to the facade")
    return resolved


@contextlib.contextmanager
def _exact_legacy_implementation() -> Iterator[types.ModuleType]:
    """Bind one exact legacy module without calling any backend operation."""

    global _LEGACY_IMPLEMENTATION_BOUND_MODULE
    global _LEGACY_IMPLEMENTATION_SOURCE_SHA256

    path = _legacy_implementation_path()
    name = _LEGACY_IMPLEMENTATION_MODULE_NAME
    with _LEGACY_IMPLEMENTATION_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(name, _MISSING_MODULE)
        try:
            module = _LEGACY_IMPLEMENTATION_BOUND_MODULE
            if module is None:
                sys.modules.pop(name, None)
                module, source_sha256 = _load_exact_source_module(
                    name,
                    path,
                    label="legacy implementation",
                )
                _LEGACY_IMPLEMENTATION_BOUND_MODULE = module
                _LEGACY_IMPLEMENTATION_SOURCE_SHA256 = source_sha256
            else:
                source_bytes, _identity = _stable_exact_module_source(
                    path,
                    label="legacy implementation",
                )
                source_sha256 = hashlib.sha256(source_bytes).hexdigest()
                if source_sha256 != _LEGACY_IMPLEMENTATION_SOURCE_SHA256:
                    raise ImportError(
                        "legacy implementation bytes changed after exact "
                        "binding"
                    )
            sys.modules[name] = module
            if _module_origin(module) != (path, path):
                raise ImportError("legacy implementation origin changed")
            yield module
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
            _imp.release_lock()


def _protected_legacy_handoff_path() -> Path:
    facade = Path(__file__).resolve()
    filename = f"{_PROTECTED_LEGACY_HANDOFF_MODULE_NAME}.py"
    skill_directory = facade.parent.parent
    if (
        facade.parent.name == "scripts"
        and skill_directory.name == "auto-g16-rtwin-pbs"
        and skill_directory.parent.name == "skills"
    ):
        source_owner = (
            skill_directory.parent.parent / "scripts" / filename
        )
        if (
            not source_owner.is_symlink()
            and source_owner.is_file()
            and source_owner.resolve().parent
            == skill_directory.parent.parent.resolve() / "scripts"
        ):
            return source_owner.resolve()
    adjacent_owner = facade.with_name(filename)
    if (
        not adjacent_owner.is_symlink()
        and adjacent_owner.is_file()
        and adjacent_owner.resolve().parent == facade.parent
    ):
        return adjacent_owner.resolve()
    raise ImportError(
        "exact protected legacy handoff owner is unavailable in repository "
        "source or deployed-package layout"
    )


@contextlib.contextmanager
def _exact_protected_legacy_handoff() -> Iterator[types.ModuleType]:
    """Load the handoff owner while both exact predecessors are bound."""

    path = _protected_legacy_handoff_path()
    name = _PROTECTED_LEGACY_HANDOFF_MODULE_NAME
    with _PROTECTED_LEGACY_HANDOFF_IMPORT_LOCK:
        _imp.acquire_lock()
        previous = sys.modules.get(name, _MISSING_MODULE)
        try:
            sys.modules.pop(name, None)
            module, _source_sha256 = _load_exact_source_module(
                name,
                path,
                label="protected legacy handoff",
            )
            yield module
        finally:
            sys.modules.pop(name, None)
            if previous is not _MISSING_MODULE:
                sys.modules[name] = previous
            _imp.release_lock()


class TransportAdapter(Protocol):
    def capabilities(self) -> tuple[str, ...]: ...
    def attest_first_hop_once(self, request: object) -> AttestationBoundaryPlan: ...
    def attest_nested_hop_once(self, first_hop: object, request: object) -> AttestationBoundaryPlan: ...
    def invoke_reserved_once(self, request: object) -> object: ...


class SchedulerAdapter(Protocol):
    def render(self, plan: ValidatedRuntimePlan) -> bytes: ...
    def submit_once(self, plan: CommandPlan, authorization: object) -> object: ...


class GaussianRuntimeAdapter(Protocol):
    def validate_binding(
        self,
        input_audit: dict[str, Any],
        exact_resources: ExactResourceTuple,
        workspace_paths: WorkspacePaths,
    ) -> ValidatedRuntimePlan: ...


class ExecutionBackend(Protocol):
    transport: TransportAdapter
    scheduler: SchedulerAdapter
    runtime: GaussianRuntimeAdapter
    def capability_report(self) -> dict[str, Any]: ...


def _implementation() -> types.ModuleType:
    return importlib.import_module("legacy_rtwin_pbs")


def backend() -> ExecutionBackend:
    return _implementation().LegacyRTWinPBSBackend()


def integrate_successor_once(*, artifacts: object, attempt: object) -> object:
    """Route one sealed successor attempt through the only configured backend."""

    integration = importlib.import_module("legacy_adapter_integration")
    integrator = integration.LegacyAdapterIntegrator.production()
    return integrator.invoke_once(artifacts=artifacts, attempt=attempt)


def _protected_submit_owner() -> "ProtectedSubmitContractOwner":
    """Return the fixed contract owner; this constructs no adapter."""

    with _exact_protected_submit_contract() as contract:
        return contract.ProtectedSubmitContractOwner.production()


def seal_protected_submit_bundle(
    *,
    evidence: "ProtectedSubmitEvidence",
) -> "SealedProtectedSubmitBundle":
    """Replay and seal one non-executable protected-submit bundle."""

    with _exact_protected_submit_contract() as contract:
        exact_evidence = _evidence_for_exact_owner(contract, evidence)
        owner = contract.ProtectedSubmitContractOwner.production()
        return owner.seal(exact_evidence)


def reserve_protected_submit_bundle_once(
    *,
    evidence: "ProtectedSubmitEvidence",
) -> "ReservedProtectedSubmitBundle":
    """Reserve the sealed authority before any separately implemented effect."""

    with _exact_protected_submit_contract() as contract:
        exact_evidence = _evidence_for_exact_owner(contract, evidence)
        owner = contract.ProtectedSubmitContractOwner.production()
        return owner.reserve_once(exact_evidence)


def _local_state_owner() -> object:
    """Return the fixed read-only path owner; this constructs no adapter."""

    with _exact_local_state_contract() as contract:
        return contract.LocalStateBindingOwner.production()


def derive_local_state_paths(
    *,
    evidence: "LocalStateBindingEvidence",
) -> "LocalStatePaths":
    """Derive exact local-state paths without accepting caller local_dir."""

    with _exact_local_state_contract() as contract:
        exact_evidence = _local_state_evidence_for_exact_owner(
            contract,
            evidence,
        )
        owner = contract.LocalStateBindingOwner.production()
        return owner.derive(exact_evidence)


def seal_local_state_binding(
    *,
    evidence: "LocalStateBindingEvidence",
) -> "SealedLocalStateBinding":
    """Seal one non-authorizing binding with an owner-derived ledger path."""

    with _exact_local_state_contract() as contract:
        exact_evidence = _local_state_evidence_for_exact_owner(
            contract,
            evidence,
        )
        owner = contract.LocalStateBindingOwner.production()
        return owner.seal(exact_evidence)


def seal_protected_invocation_bundle(
    *,
    evidence: "ProtectedInvocationEvidence",
) -> "SealedProtectedInvocationBundle":
    """Seal one owner-composed invocation closure without any effect."""

    with _exact_protected_invocation_contract() as contract:
        exact_evidence = _protected_invocation_evidence_for_exact_owner(
            contract,
            evidence,
        )
        owner = contract.ProtectedInvocationContractOwner.production()
        return owner.seal(exact_evidence)


def materialize_protected_lifecycle_once(
    *,
    evidence: "ProtectedLifecycleEvidence",
) -> "SealedProtectedLocalMaterialization":
    """Reserve, materialize exact sealed bytes, publish state, then stop."""

    with _exact_protected_local_materialization() as contract:
        owner = contract.ProtectedLocalMaterializationOwner.production()
        return owner.materialize_once(evidence)


def seal_protected_legacy_effect_handoff(
    *,
    materialization: "SealedProtectedLocalMaterialization",
) -> "SealedProtectedLegacyEffectHandoff":
    """Bind exact PR4L state to PR4M readiness and perform no effect."""

    with _exact_protected_local_materialization() as materialization_owner:
        if (
            type(materialization)
            is not materialization_owner.SealedProtectedLocalMaterialization
        ):
            raise TypeError(
                "handoff requires the facade-bound PR4L materialization"
            )
        with _exact_legacy_implementation():
            with _exact_protected_legacy_handoff() as handoff_owner:
                owner = (
                    handoff_owner.ProtectedLegacyEffectHandoffOwner.production()
                )
                return owner.seal(materialization)


def bind_current() -> types.ModuleType:
    """Return the one fixed implementation; callers cannot select a module."""
    return _implementation()


def build_parser() -> argparse.ArgumentParser:
    return _implementation().build_parser()


def main(argv: list[str] | None = None) -> int:
    implementation = _implementation()
    args = implementation.build_parser().parse_args(argv)
    implementation.LegacyCLICompatibilityAdapter().dispatch(args)
    return 0


def __getattr__(name: str) -> Any:
    return getattr(_implementation(), name)
