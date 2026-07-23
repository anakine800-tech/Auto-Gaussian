"""Sealed backend-neutral execution models for Auto-G16 v2.6."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar


FIXED_REMOTE_ROOT = "/home/user100/SDL"
PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,14}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FORBIDDEN_TOKEN_RE = re.compile(r"[\x00\r\n\s'\"`$;|&<>()*?\[\]{}\\/]")
_FACTORY_TOKEN = object()
_RESOURCE_OWNER_TOKEN = object()
_AUTHORIZATION_OWNER_TOKEN = object()


class ModelError(ValueError):
    """A caller tried to cross a sealed execution boundary."""


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _load_repository_owner(filename: str, owner_name: str) -> ModuleType:
    """Load the exact repository/deployment owner from a fixed local path."""

    here = Path(__file__).resolve()
    adjacent = here.with_name(filename)
    repository = here.parents[3] / "scripts" / filename
    path = adjacent if adjacent.is_file() and not adjacent.is_symlink() else repository
    if not path.is_file() or path.is_symlink():
        raise ModelError(f"{owner_name} owner is unavailable")
    module_name = f"_auto_g16_{owner_name}_{hashlib.sha256(str(path).encode()).hexdigest()[:16]}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ModelError(f"{owner_name} owner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    if Path(module.__file__).resolve() != path.resolve():
        raise ModelError(f"{owner_name} owner origin changed")
    return module


def _utc(value: str | datetime, label: str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ModelError(f"{label} must be timezone-aware")
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ModelError(f"{label} must be second-precision UTC")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ModelError(f"{label} must be second-precision UTC") from exc


def validate_component(value: str, label: str, *, suffixes: tuple[str, ...] = ()) -> str:
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ModelError(f"{label} is not a closed component")
    if FORBIDDEN_TOKEN_RE.search(value) or ".." in value or not COMPONENT_RE.fullmatch(value):
        raise ModelError(f"{label} contains a forbidden character or traversal")
    if suffixes and not value.lower().endswith(suffixes):
        raise ModelError(f"{label} has an unsupported suffix")
    return value


@dataclass(frozen=True, slots=True, init=False)
class ExactResourceTuple:
    tier: str
    cores: int
    memory_gb: int
    walltime_seconds: int
    catalog_payload_sha256: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "ExactResourceTuple":
        raise TypeError("ExactResourceTuple must be sealed by the PR2 resource owner")

    @classmethod
    def from_owner(cls, tier: str, cores: int, memory_gb: int, walltime_seconds: int) -> "ExactResourceTuple":
        try:
            owner = _load_repository_owner("platform_contracts.py", "platform_contracts")
            catalog = owner.build_resource_catalog()
            exact = owner.validate_exact_resource(
                catalog,
                tier=tier,
                cores=cores,
                memory_gb=memory_gb,
                walltime_seconds=walltime_seconds,
            )
        except (ImportError, OSError, ValueError) as exc:
            raise ModelError(f"PR2 resource owner rejected the exact tuple: {exc}") from exc
        value = object.__new__(cls)
        for name, item in {
            **exact,
            "catalog_payload_sha256": catalog["catalog_payload_sha256"],
            "_seal": _RESOURCE_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _RESOURCE_OWNER_TOKEN or not SHA256_RE.fullmatch(self.catalog_payload_sha256):
            raise ModelError("exact resources lack the PR2 owner seal")


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
        resources.assert_owner_sealed()
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
                "catalog_payload_sha256": resources.catalog_payload_sha256,
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
        self.resources.assert_owner_sealed()


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


def _runtime_binding_from_adapter(
    executable_token: str,
    input_basename: str,
    input_sha256: str,
    workspace: WorkspacePaths,
    resources: ExactResourceTuple,
) -> RuntimeBinding:
    """Narrow adapter-owned bridge; it accepts no mapping or free-form plan."""

    return RuntimeBinding._create(
        executable_token=executable_token,
        input_basename=input_basename,
        input_sha256=input_sha256,
        workspace=workspace,
        resources=resources,
        token=_FACTORY_TOKEN,
    )


@dataclass(frozen=True, slots=True, init=False)
class _ReplayedAttestationOperation:
    operation: str
    operation_version: str
    request_nonce: str
    not_before: str
    expires_at: str
    allowed_read_only_side_effects: tuple[str, ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "_ReplayedAttestationOperation":
        raise TypeError("attestation replay records are created only by the PR3 replay owner")

    @classmethod
    def _create(cls, document: dict[str, Any], token: object) -> "_ReplayedAttestationOperation":
        if token is not _AUTHORIZATION_OWNER_TOKEN:
            raise ModelError("attestation replay record lacks the PR3 owner seal")
        value = object.__new__(cls)
        for name, item in {
            "operation": document["operation"],
            "operation_version": document["operation_version"],
            "request_nonce": document["request_nonce"],
            "not_before": document["not_before"],
            "expires_at": document["expires_at"],
            "allowed_read_only_side_effects": tuple(document["allowed_read_only_side_effects"]),
            "_seal": _AUTHORIZATION_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _AUTHORIZATION_OWNER_TOKEN:
            raise ModelError("attestation replay record seal is invalid")


@dataclass(frozen=True, slots=True, init=False)
class PR3AuthorizationReplay:
    authorization_id: str
    profile_sha256: str
    backend_kind: str
    project: str
    identity_binding_sha256: str
    operations: tuple[_ReplayedAttestationOperation, ...]
    replayed_at: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "PR3AuthorizationReplay":
        raise TypeError("PR3AuthorizationReplay must be loaded by the strict PR3 owner")

    @classmethod
    def from_pr3_owner(cls, path: Path, *, now: str | datetime) -> "PR3AuthorizationReplay":
        try:
            owner = _load_repository_owner("execution_authorization.py", "execution_authorization")
            document = owner._load_new_contract(
                Path(path),
                owner.validate_execution_authorization,
                "execution authorization",
                now=now,
            )
        except (ImportError, OSError, ValueError) as exc:
            raise ModelError(f"PR3 execution authorization owner rejected the successor: {exc}") from exc
        current = _utc(now, "authorization replay time")
        operations: list[_ReplayedAttestationOperation] = []
        expected = (
            (
                "attest_first_hop_once",
                "first-hop-identity-attestation/1",
                ["read_local_identity_sources", "network_identity_handshake"],
            ),
            (
                "attest_nested_hop_once",
                "nested-hop-identity-attestation/1",
                ["read_remote_identity_source_hashes"],
            ),
        )
        raw_operations = document["identity_attestation"]["operations"]
        for index, (operation_name, operation_version, effects) in enumerate(expected):
            operation = raw_operations[index]
            starts = _utc(operation["not_before"], f"attestation operation {index} not_before")
            expires = _utc(operation["expires_at"], f"attestation operation {index} expires_at")
            if not starts <= current < expires:
                raise ModelError(f"attestation operation {index} is outside its active window")
            if (
                operation["operation"] != operation_name
                or operation["operation_version"] != operation_version
                or operation["allowed_read_only_side_effects"] != effects
                or operation["read_only"] is not True
                or operation["automatic_retry"] is not False
                or operation["mutation_allowed"] is not False
            ):
                raise ModelError(f"attestation operation {index} differs from the PR3 owner replay")
            operations.append(_ReplayedAttestationOperation._create(operation, _AUTHORIZATION_OWNER_TOKEN))
        value = object.__new__(cls)
        for name, item in {
            "authorization_id": document["authorization_id"],
            "profile_sha256": document["profile"]["profile_sha256"],
            "backend_kind": document["profile"]["backend_kind"],
            "identity_binding_sha256": document["transport"]["identity_binding_sha256"],
            "project": document["workspace_binding"]["project"],
            "operations": tuple(operations),
            "replayed_at": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_seal": _AUTHORIZATION_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _AUTHORIZATION_OWNER_TOKEN:
            raise ModelError("PR3 authorization replay seal is invalid")


@dataclass(frozen=True, slots=True, init=False)
class TransportAuthorityReplay:
    """Sealed, non-executable replay of the additive /2 authority overlay."""

    authorization_id: str
    request_id: str
    historical_authorization_id: str
    profile_sha256: str
    backend_kind: str
    project: str
    identity_binding_sha256: str
    transport_config_bindings_sha256: str
    operations: tuple[_ReplayedAttestationOperation, ...]
    replayed_at: str
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "TransportAuthorityReplay":
        raise TypeError("TransportAuthorityReplay must be loaded by the successor owner")

    @classmethod
    def from_successor_owner(cls, path: Path, *, now: str | datetime) -> "TransportAuthorityReplay":
        try:
            owner = _load_repository_owner("transport_authority_closure.py", "transport_authority_closure")
            document = owner.load_contract(
                Path(path), owner.validate_execution_authorization_v2, now=now,
            )
        except (ImportError, OSError, ValueError) as exc:
            raise ModelError(f"transport authority successor owner rejected the artifact: {exc}") from exc
        current = _utc(now, "transport authority replay time")
        operations = tuple(
            _ReplayedAttestationOperation._create(item, _AUTHORIZATION_OWNER_TOKEN)
            for item in document["identity_attestation"]["operations"]
        )
        value = object.__new__(cls)
        for name, item in {
            "authorization_id": document["authorization_id"],
            "request_id": document["request"]["request_id"],
            "historical_authorization_id": document["historical_execution_authorization"]["authorization_id"],
            "profile_sha256": document["profile"]["profile_sha256"],
            "backend_kind": document["profile"]["backend_kind"],
            "project": document["project"],
            "identity_binding_sha256": document["transport"]["identity_binding_sha256"],
            "transport_config_bindings_sha256": document["transport"]["transport_config_bindings_sha256"],
            "operations": operations,
            "replayed_at": current.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_seal": _AUTHORIZATION_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _AUTHORIZATION_OWNER_TOKEN or len(self.operations) != 3:
            raise ModelError("transport authority replay seal/topology is invalid")


@dataclass(frozen=True, slots=True, init=False)
class ValidatedAttestationOperation:
    operation: str
    operation_version: str
    request_nonce: str
    profile_sha256: str
    identity_binding_sha256: str
    first_hop_receipt_sha256: str | None
    not_before: str
    expires_at: str
    allowed_read_only_side_effects: tuple[str, ...]
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "ValidatedAttestationOperation":
        raise TypeError("ValidatedAttestationOperation must be derived from a PR3 owner replay")

    @classmethod
    def from_replay(
        cls,
        replay: PR3AuthorizationReplay,
        *,
        operation_index: int,
        first_hop_receipt_sha256: str | None = None,
    ) -> "ValidatedAttestationOperation":
        replay.assert_owner_sealed()
        if isinstance(operation_index, bool) or operation_index not in (0, 1):
            raise ModelError("attestation operation index is invalid")
        document = replay.operations[operation_index]
        document.assert_owner_sealed()
        operation = document.operation
        nonce = document.request_nonce
        if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32,128}", nonce):
            raise ModelError("attestation nonce is malformed")
        for digest in (replay.profile_sha256, replay.identity_binding_sha256):
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
            "operation_version": document.operation_version,
            "request_nonce": nonce,
            "profile_sha256": replay.profile_sha256,
            "identity_binding_sha256": replay.identity_binding_sha256,
            "first_hop_receipt_sha256": first_hop_receipt_sha256,
            "not_before": document.not_before,
            "expires_at": document.expires_at,
            "allowed_read_only_side_effects": document.allowed_read_only_side_effects,
            "_seal": _AUTHORIZATION_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if self._seal is not _AUTHORIZATION_OWNER_TOKEN:
            raise ModelError("attestation operation seal is invalid")


@dataclass(frozen=True, slots=True, init=False)
class AttestationBoundaryPlan:
    """Pure, non-executable description of the separately authorized live gap."""

    operation: str
    operation_version: str
    request_nonce_sha256: str
    profile_sha256: str
    identity_binding_sha256: str
    first_hop_receipt_sha256: str | None
    not_before: str
    expires_at: str
    allowed_read_only_side_effects: tuple[str, ...]
    executable: bool
    automatic_retry: bool
    network_performed: bool
    _seal: object

    def __new__(cls, *args: Any, **kwargs: Any) -> "AttestationBoundaryPlan":
        raise TypeError("AttestationBoundaryPlan must be derived from a sealed PR3 operation")

    @classmethod
    def from_validated(cls, request: ValidatedAttestationOperation) -> "AttestationBoundaryPlan":
        request.assert_owner_sealed()
        value = object.__new__(cls)
        for name, item in {
            "operation": request.operation,
            "operation_version": request.operation_version,
            "request_nonce_sha256": hashlib.sha256(request.request_nonce.encode("ascii")).hexdigest(),
            "profile_sha256": request.profile_sha256,
            "identity_binding_sha256": request.identity_binding_sha256,
            "first_hop_receipt_sha256": request.first_hop_receipt_sha256,
            "not_before": request.not_before,
            "expires_at": request.expires_at,
            "allowed_read_only_side_effects": request.allowed_read_only_side_effects,
            "executable": False,
            "automatic_retry": False,
            "network_performed": False,
            "_seal": _AUTHORIZATION_OWNER_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def assert_owner_sealed(self) -> None:
        if (
            self._seal is not _AUTHORIZATION_OWNER_TOKEN
            or self.executable is not False
            or self.automatic_retry is not False
            or self.network_performed is not False
        ):
            raise ModelError("attestation boundary plan is not the sealed PR4A non-executable form")
