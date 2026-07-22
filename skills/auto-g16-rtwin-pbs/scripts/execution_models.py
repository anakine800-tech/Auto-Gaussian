"""Sealed backend-neutral execution models for Auto-G16 v2.6."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, ClassVar


FIXED_REMOTE_ROOT = "/home/user100/SDL"
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FORBIDDEN_TOKEN_RE = re.compile(r"[\x00\r\n\s'\"`$;|&<>()*?\[\]{}\\/]")
_FACTORY_TOKEN = object()


class ModelError(ValueError):
    """A caller tried to cross a sealed execution boundary."""


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_component(value: str, label: str, *, suffixes: tuple[str, ...] = ()) -> str:
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ModelError(f"{label} is not a closed component")
    if FORBIDDEN_TOKEN_RE.search(value) or ".." in value or not COMPONENT_RE.fullmatch(value):
        raise ModelError(f"{label} contains a forbidden character or traversal")
    if suffixes and not value.lower().endswith(suffixes):
        raise ModelError(f"{label} has an unsupported suffix")
    return value


@dataclass(frozen=True, slots=True)
class ExactResourceTuple:
    tier: str
    cores: int
    memory_gb: int
    walltime_seconds: int

    @classmethod
    def from_owner(cls, tier: str, cores: int, memory_gb: int, walltime_seconds: int) -> "ExactResourceTuple":
        if tier not in {"simple", "general", "complex", "custom_reviewed"}:
            raise ModelError("resource tier is not owner-reviewed")
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in (cores, memory_gb, walltime_seconds)):
            raise ModelError("exact resources must be positive integers")
        if cores > 44 or memory_gb > 120:
            raise ModelError("exact resources exceed the fixed legacy capacity")
        reviewed = {"simple": (8, 12), "general": (22, 50), "complex": (44, 120)}
        if tier in reviewed and reviewed[tier] != (cores, memory_gb):
            raise ModelError("resource tuple differs from the legacy catalog owner")
        return cls(tier, cores, memory_gb, walltime_seconds)


@dataclass(frozen=True, slots=True, init=False)
class WorkspacePaths:
    allowed_root: str
    project: str
    remote_workdir: str
    scratch: str
    binding_sha256: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "WorkspacePaths":
        raise TypeError("WorkspacePaths must be derived by WorkspacePolicy")

    @classmethod
    def _create(cls, project: str, token: object) -> "WorkspacePaths":
        if token is not _FACTORY_TOKEN or not PROJECT_RE.fullmatch(project):
            raise ModelError("WorkspacePaths must be derived by WorkspacePolicy")
        remote = f"{FIXED_REMOTE_ROOT}/{project}"
        scratch = f"{remote}/scratch"
        value = object.__new__(cls)
        for name, item in {
            "allowed_root": FIXED_REMOTE_ROOT,
            "project": project,
            "remote_workdir": remote,
            "scratch": scratch,
            "binding_sha256": canonical_digest({
                "allowed_root": FIXED_REMOTE_ROOT,
                "project": project,
                "remote_workdir": remote,
                "scratch": scratch,
                "fresh_project_required": True,
                "no_overwrite": True,
                "no_symlink": True,
                "no_delete": True,
            }),
            "_seal": _FACTORY_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _FACTORY_TOKEN:
            raise ModelError("WorkspacePaths seal is invalid")


class WorkspacePolicy:
    """Fixed SDL policy with no delete, override, or caller path input."""

    allowed_root: ClassVar[str] = FIXED_REMOTE_ROOT

    def derive(self, project: str) -> WorkspacePaths:
        return WorkspacePaths._create(project, _FACTORY_TOKEN)


@dataclass(frozen=True, slots=True, init=False)
class RuntimeBinding:
    invocation_mode: str
    executable_token: str
    input_basename: str
    input_sha256: str
    scratch_component: str
    workspace_binding_sha256: str
    resources: ExactResourceTuple
    binding_sha256: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "RuntimeBinding":
        raise TypeError("RuntimeBinding must be created by GaussianRuntimeAdapter")

    @classmethod
    def _create(
        cls,
        *,
        executable_token: str,
        input_basename: str,
        input_sha256: str,
        workspace: WorkspacePaths,
        resources: ExactResourceTuple,
        token: object,
    ) -> "RuntimeBinding":
        if token is not _FACTORY_TOKEN:
            raise ModelError("RuntimeBinding must be created by GaussianRuntimeAdapter")
        workspace.assert_owner_sealed()
        validate_component(executable_token, "Gaussian executable")
        validate_component(input_basename, "Gaussian input basename", suffixes=(".gjf", ".com"))
        if not SHA256_RE.fullmatch(input_sha256):
            raise ModelError("Gaussian input hash is malformed")
        scratch_component = "scratch"
        payload = {
            "invocation_mode": "legacy_stdin",
            "executable_token": executable_token,
            "input_basename": input_basename,
            "input_sha256": input_sha256,
            "scratch_component": scratch_component,
            "workspace_binding_sha256": workspace.binding_sha256,
            "resources": {
                "tier": resources.tier,
                "cores": resources.cores,
                "memory_gb": resources.memory_gb,
                "walltime_seconds": resources.walltime_seconds,
            },
        }
        value = object.__new__(cls)
        for name, item in {
            **payload,
            "resources": resources,
            "binding_sha256": canonical_digest(payload),
            "_seal": _FACTORY_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _FACTORY_TOKEN:
            raise ModelError("RuntimeBinding seal is invalid")


@dataclass(frozen=True, slots=True)
class ValidatedRuntimePlan:
    runtime_binding: RuntimeBinding
    workspace_paths: WorkspacePaths

    def __post_init__(self) -> None:
        self.runtime_binding.assert_owner_sealed()
        self.workspace_paths.assert_owner_sealed()
        if self.runtime_binding.workspace_binding_sha256 != self.workspace_paths.binding_sha256:
            raise ModelError("runtime/workspace binding differs")


class PlanKind(str, Enum):
    READ_ONLY = "read_only"
    MUTATION_ONCE = "mutation_once"


@dataclass(frozen=True, slots=True, init=False)
class CommandPlan:
    operation: str
    argv: tuple[str, ...]
    stdin: bytes | None
    timeout_seconds: int
    kind: PlanKind
    automatic_retry: bool
    _seal: object

    @classmethod
    def _create(
        cls,
        *,
        operation: str,
        argv: tuple[str, ...],
        stdin: bytes | None,
        timeout_seconds: int,
        kind: PlanKind,
        token: object,
    ) -> "CommandPlan":
        if token is not _FACTORY_TOKEN:
            raise ModelError("CommandPlan must be built by an adapter")
        if not operation or not argv or any(not isinstance(item, str) or not item for item in argv):
            raise ModelError("command plan is incomplete")
        if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
            raise ModelError("command plan timeout is invalid")
        value = object.__new__(cls)
        for name, item in {
            "operation": operation,
            "argv": argv,
            "stdin": stdin,
            "timeout_seconds": timeout_seconds,
            "kind": kind,
            "automatic_retry": False,
            "_seal": _FACTORY_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _FACTORY_TOKEN or self.automatic_retry is not False:
            raise ModelError("command plan seal/retry contract is invalid")


def _runtime_binding_from_adapter(**kwargs: Any) -> RuntimeBinding:
    return RuntimeBinding._create(token=_FACTORY_TOKEN, **kwargs)


@dataclass(frozen=True, slots=True, init=False)
class ValidatedAttestationOperation:
    operation: str
    operation_version: str
    request_nonce: str
    profile_sha256: str
    identity_binding_sha256: str
    first_hop_receipt_sha256: str | None
    _seal: object

    @classmethod
    def from_owner(
        cls,
        document: dict[str, Any],
        *,
        profile_sha256: str,
        identity_binding_sha256: str,
        first_hop_receipt_sha256: str | None = None,
    ) -> "ValidatedAttestationOperation":
        allowed = {
            "operation", "operation_version", "request_nonce", "not_before",
            "expires_at", "allowed_read_only_side_effects", "read_only",
            "automatic_retry", "mutation_allowed",
        }
        if not isinstance(document, dict) or set(document) != allowed:
            raise ModelError("attestation operation is not the closed owner shape")
        operation = document["operation"]
        versions = {
            "attest_first_hop_once": "first-hop-identity-attestation/1",
            "attest_nested_hop_once": "nested-hop-identity-attestation/1",
        }
        if (
            operation not in versions
            or document["operation_version"] != versions[operation]
            or document["read_only"] is not True
            or document["automatic_retry"] is not False
            or document["mutation_allowed"] is not False
        ):
            raise ModelError("attestation operation authority markers changed")
        nonce = document["request_nonce"]
        if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32,128}", nonce):
            raise ModelError("attestation nonce is malformed")
        for digest in (profile_sha256, identity_binding_sha256):
            if not SHA256_RE.fullmatch(digest):
                raise ModelError("attestation binding digest is malformed")
        if operation == "attest_nested_hop_once" and not (
            isinstance(first_hop_receipt_sha256, str)
            and SHA256_RE.fullmatch(first_hop_receipt_sha256)
        ):
            raise ModelError("nested attestation lacks the exact first-hop receipt")
        value = object.__new__(cls)
        for name, item in {
            "operation": operation,
            "operation_version": document["operation_version"],
            "request_nonce": nonce,
            "profile_sha256": profile_sha256,
            "identity_binding_sha256": identity_binding_sha256,
            "first_hop_receipt_sha256": first_hop_receipt_sha256,
            "_seal": _FACTORY_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _FACTORY_TOKEN:
            raise ModelError("attestation operation seal is invalid")


@dataclass(frozen=True, slots=True)
class AttestationBoundaryPlan:
    """Pure, non-executable description of the separately authorized live gap."""

    operation: str
    operation_version: str
    request_nonce_sha256: str
    profile_sha256: str
    identity_binding_sha256: str
    first_hop_receipt_sha256: str | None
    executable: bool = False
    automatic_retry: bool = False
    network_performed: bool = False

    @classmethod
    def from_validated(cls, request: ValidatedAttestationOperation) -> "AttestationBoundaryPlan":
        request.assert_owner_sealed()
        return cls(
            operation=request.operation,
            operation_version=request.operation_version,
            request_nonce_sha256=hashlib.sha256(request.request_nonce.encode("ascii")).hexdigest(),
            profile_sha256=request.profile_sha256,
            identity_binding_sha256=request.identity_binding_sha256,
            first_hop_receipt_sha256=request.first_hop_receipt_sha256,
        )
