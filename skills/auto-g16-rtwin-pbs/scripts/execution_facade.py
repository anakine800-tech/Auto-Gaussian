"""Backend-neutral facade for the sole Auto-G16 v2.6 legacy backend."""

from __future__ import annotations

import argparse
import importlib
import sys
import types
from typing import Any, Protocol

from execution_models import (
    AttestationBoundaryPlan,
    CommandPlan,
    ExactResourceTuple,
    ValidatedRuntimePlan,
    WorkspacePaths,
)

_BOUND_IMPLEMENTATION = sys.modules.get("gaussian_rtwin_pbs")


class TransportAdapter(Protocol):
    def capabilities(self) -> tuple[str, ...]: ...
    def attest_first_hop_once(self, request: object) -> AttestationBoundaryPlan: ...
    def attest_nested_hop_once(self, first_hop: object, request: object) -> AttestationBoundaryPlan: ...


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
    compatibility = sys.modules.get("gaussian_rtwin_pbs")
    if compatibility is not None and hasattr(compatibility, "LegacyRTWinPBSBackend"):
        return compatibility
    if _BOUND_IMPLEMENTATION is not None and hasattr(_BOUND_IMPLEMENTATION, "LegacyRTWinPBSBackend"):
        return _BOUND_IMPLEMENTATION
    return importlib.import_module("legacy_rtwin_pbs")


def backend() -> ExecutionBackend:
    return _implementation().LegacyRTWinPBSBackend()


def bind_current() -> types.ModuleType:
    # The binding itself is performed by this facade; returning the fixed
    # module preserves the long-standing monkeypatch/import compatibility of
    # callers without creating a second mutable proxy surface.
    return _implementation()


def build_parser(*, backend_module: types.ModuleType | None = None) -> argparse.ArgumentParser:
    return (backend_module or _implementation()).build_parser()


def main(argv: list[str] | None = None, *, backend_module: types.ModuleType | None = None) -> int:
    implementation = backend_module or _implementation()
    args = implementation.build_parser().parse_args(argv)
    implementation.LegacyCLICompatibilityAdapter().dispatch(args)
    return 0


def __getattr__(name: str) -> Any:
    return getattr(_implementation(), name)


class _ForwardingFacade(types.ModuleType):
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        implementation = _implementation()
        if implementation is not None and hasattr(implementation, name):
            setattr(implementation, name, value)


sys.modules[__name__].__class__ = _ForwardingFacade
