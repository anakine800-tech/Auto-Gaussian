"""Backend-neutral facade for the sole Auto-G16 v2.6 legacy backend."""

from __future__ import annotations

import argparse
import importlib
import types
from typing import Any, Protocol

from execution_models import (
    AttestationBoundaryPlan,
    CommandPlan,
    ExactResourceTuple,
    ValidatedRuntimePlan,
    WorkspacePaths,
)

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
    return importlib.import_module("legacy_rtwin_pbs")


def backend() -> ExecutionBackend:
    return _implementation().LegacyRTWinPBSBackend()


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
