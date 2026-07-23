"""Backend-neutral facade for the sole Auto-G16 v2.6 legacy backend."""

from __future__ import annotations

import _imp
import argparse
import contextlib
import importlib
import importlib.util
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
