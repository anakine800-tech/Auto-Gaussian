"""Immutable public records for the frozen v3 execution boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Final

from auto_g16.core import Project, ResourceSpec

from ._identity import (
    ExecutionValueError,
    bytes_identity,
    freeze_mapping,
    require_positive_integer,
    require_text,
    semantic_id,
    semantic_sha256,
)
from ._paths import (
    require_contained,
    require_local_workspace_anchor,
    require_windows_contained,
    validate_platform_path,
    validate_portable_name,
    validate_posix_path,
    validate_windows_path,
)


LEGACY_REMOTE_ROOT: Final = "/home/user100/SDL"
RECEIPT_OBSERVATION_TYPE: Final = "v3.remote-effect-receipt"
_PBS_NAME_DIRECTIVE: Final = re.compile(r"^#PBS -N [A-Za-z0-9][A-Za-z0-9._-]*$")
_PBS_EXECUTION_COMMAND: Final = re.compile(r"^exec g16 [A-Za-z0-9][A-Za-z0-9._-]*$")
_HOST_IDENTITY: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:-]*$")


def _semantic_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {key: value[key] for key in value}


def _reject_secret_content(name: str, content: bytes) -> None:
    lowered = content.lower()
    if b"private key-----" in lowered or b"-----begin encrypted" in lowered:
        raise ExecutionValueError(f"{name} must not contain private-key bytes")
    for line in lowered.splitlines():
        stripped = line.strip()
        if stripped.startswith((b"password ", b"token ", b"secret ")):
            raise ExecutionValueError(f"{name} must not contain secret material")


def _validate_host(value: str, field_name: str) -> str:
    require_text(value, field_name)
    if not _HOST_IDENTITY.fullmatch(value):
        raise ExecutionValueError(f"{field_name} must be an explicit host identity")
    return value


def _profile_marker(profile: ServerProfile) -> tuple[object, ...]:
    try:
        return (
            profile.server_profile_id,
            profile.profile_revision,
            profile.transport_kind,
            profile.target_host,
            profile.target_port,
            profile.remote_user,
            tuple(profile.jump_topology),
            profile.host_key_policy,
            profile.batch_mode,
            profile.identities_only,
            profile.remote_root,
            tuple(sorted(profile.platform_paths.items())),
            tuple(profile.config_files),
            tuple(sorted(profile.runtime_contents.items())),
        )
    except (RuntimeError, TypeError) as exc:
        raise ExecutionValueError("ServerProfile mutated during resolution") from exc


@dataclass(slots=True, kw_only=True)
class ServerProfile:
    """Mutable non-secret configuration resolved before an execution claim."""

    server_profile_id: str
    profile_revision: int
    transport_kind: str
    target_host: str
    target_port: int
    remote_user: str
    jump_topology: list[tuple[str, int, str]]
    host_key_policy: str
    batch_mode: bool
    identities_only: bool
    remote_root: str
    platform_paths: dict[str, str]
    config_files: list[tuple[str, bytes]]
    runtime_contents: dict[str, bytes]


@dataclass(frozen=True, slots=True, kw_only=True)
class PreparedInputBinding:
    attempt_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    input_format: str
    logical_name: str
    sha256: str = field(init=False)
    size_bytes: int = field(init=False)
    prepared_input_binding_id: str = field(init=False)

    def __init__(
        self,
        *,
        attempt_id: str,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        input_format: str,
        logical_name: str,
        prepared_bytes: bytes,
    ) -> None:
        require_text(attempt_id, "attempt_id")
        require_text(calculation_plan_id, "calculation_plan_id")
        require_positive_integer(calculation_plan_revision, "calculation_plan_revision")
        require_text(input_format, "input_format")
        if input_format != "gaussian-gjf":
            raise ExecutionValueError("V30-EXEC-01 only accepts gaussian-gjf prepared input")
        validate_portable_name(logical_name, "logical_name")
        if not isinstance(prepared_bytes, bytes) or not prepared_bytes:
            raise ExecutionValueError("prepared input must be non-empty immutable bytes")
        identity = bytes_identity(prepared_bytes)
        payload = {
            "attempt_id": attempt_id,
            "calculation_plan_id": calculation_plan_id,
            "calculation_plan_revision": calculation_plan_revision,
            "input_format": input_format,
            "logical_name": logical_name,
            "sha256": identity["sha256"],
            "size_bytes": identity["size_bytes"],
        }
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "calculation_plan_id", calculation_plan_id)
        object.__setattr__(self, "calculation_plan_revision", calculation_plan_revision)
        object.__setattr__(self, "input_format", input_format)
        object.__setattr__(self, "logical_name", logical_name)
        object.__setattr__(self, "sha256", identity["sha256"])
        object.__setattr__(self, "size_bytes", identity["size_bytes"])
        object.__setattr__(
            self,
            "prepared_input_binding_id",
            semantic_id("prepared-input-binding", payload),
        )

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "prepared_input_binding_id": self.prepared_input_binding_id,
                "attempt_id": self.attempt_id,
                "calculation_plan_id": self.calculation_plan_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "input_format": self.input_format,
                "logical_name": self.logical_name,
                "sha256": self.sha256,
                "size_bytes": self.size_bytes,
            },
            "prepared_input_binding",
        )

    def verify_bytes(self, value: bytes) -> None:
        observed = bytes_identity(value)
        if observed["sha256"] != self.sha256 or observed["size_bytes"] != self.size_bytes:
            raise ExecutionValueError("prepared input bytes differ from their frozen binding")

    def assert_identity_closed(self) -> None:
        payload = {
            key: self.semantic_payload()[key]
            for key in self.semantic_payload()
            if key != "prepared_input_binding_id"
        }
        if semantic_id("prepared-input-binding", payload) != self.prepared_input_binding_id:
            raise ExecutionValueError("prepared input binding identity is stale")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedResourceRequest:
    resource_spec_id: str
    cores: int
    memory_mb: int
    walltime_seconds: int
    queue: str | None
    resolved_resource_request_id: str = field(init=False)

    def __init__(
        self,
        *,
        resource_spec: ResourceSpec,
        cores: int,
        memory_mb: int,
        walltime_seconds: int,
        queue: str | None = None,
    ) -> None:
        if not isinstance(resource_spec, ResourceSpec):
            raise ExecutionValueError("resource_spec must be a public Core ResourceSpec")
        require_positive_integer(cores, "cores")
        require_positive_integer(memory_mb, "memory_mb")
        require_positive_integer(walltime_seconds, "walltime_seconds")
        if queue is not None:
            validate_portable_name(queue, "queue")
        payload = {
            "resource_spec_id": resource_spec.resource_spec_id,
            "cores": cores,
            "memory_mb": memory_mb,
            "walltime_seconds": walltime_seconds,
            "queue": queue,
        }
        object.__setattr__(self, "resource_spec_id", resource_spec.resource_spec_id)
        object.__setattr__(self, "cores", cores)
        object.__setattr__(self, "memory_mb", memory_mb)
        object.__setattr__(self, "walltime_seconds", walltime_seconds)
        object.__setattr__(self, "queue", queue)
        object.__setattr__(
            self,
            "resolved_resource_request_id",
            semantic_id("resolved-resource-request", payload),
        )

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "resolved_resource_request_id": self.resolved_resource_request_id,
                "resource_spec_id": self.resource_spec_id,
                "cores": self.cores,
                "memory_mb": self.memory_mb,
                "walltime_seconds": self.walltime_seconds,
                "queue": self.queue,
            },
            "resolved_resource_request",
        )

    def assert_identity_closed(self) -> None:
        payload = {
            key: self.semantic_payload()[key]
            for key in self.semantic_payload()
            if key != "resolved_resource_request_id"
        }
        if semantic_id("resolved-resource-request", payload) != self.resolved_resource_request_id:
            raise ExecutionValueError("resolved resource request identity is stale")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ResolvedServerProfile:
    server_profile_id: str
    profile_revision: int
    effective_config_sha256: str
    transport_kind: str
    target_identity: Mapping[str, object]
    remote_user: str
    remote_root: str
    platform_paths: Mapping[str, object]
    runtime_identities: Mapping[str, object]
    resolved_server_profile_id: str
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ResolvedServerProfile is created only by resolve_server_profile")

    @classmethod
    def _from_resolved(
        cls,
        *,
        server_profile_id: str,
        profile_revision: int,
        effective_config_sha256: str,
        transport_kind: str,
        target_identity: Mapping[str, object],
        remote_user: str,
        remote_root: str,
        platform_paths: Mapping[str, object],
        runtime_identities: Mapping[str, object],
        resolved_server_profile_id: str,
        identity_payload: Mapping[str, object],
    ) -> ResolvedServerProfile:
        value = object.__new__(cls)
        object.__setattr__(value, "server_profile_id", server_profile_id)
        object.__setattr__(value, "profile_revision", profile_revision)
        object.__setattr__(value, "effective_config_sha256", effective_config_sha256)
        object.__setattr__(value, "transport_kind", transport_kind)
        object.__setattr__(value, "target_identity", target_identity)
        object.__setattr__(value, "remote_user", remote_user)
        object.__setattr__(value, "remote_root", remote_root)
        object.__setattr__(value, "platform_paths", platform_paths)
        object.__setattr__(value, "runtime_identities", runtime_identities)
        object.__setattr__(value, "resolved_server_profile_id", resolved_server_profile_id)
        object.__setattr__(value, "_identity_payload", identity_payload)
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "resolved_server_profile_id": self.resolved_server_profile_id,
                "server_profile_id": self.server_profile_id,
                "profile_revision": self.profile_revision,
                "effective_config_sha256": self.effective_config_sha256,
                "transport_kind": self.transport_kind,
                "target_identity": self.target_identity,
                "remote_user": self.remote_user,
                "remote_root": self.remote_root,
                "platform_paths": self.platform_paths,
                "runtime_identities": self.runtime_identities,
            },
            "resolved_server_profile",
        )

    def assert_identity_closed(self) -> None:
        identity_payload = self._identity_payload
        effective_payload = freeze_mapping(
            {
                key: identity_payload[key]
                for key in identity_payload
                if key != "effective_config_sha256"
            },
            "effective server profile verification",
        )
        if semantic_sha256(effective_payload) != self.effective_config_sha256:
            raise ExecutionValueError("resolved server profile digest is stale")
        if identity_payload["effective_config_sha256"] != self.effective_config_sha256:
            raise ExecutionValueError("resolved server profile digest payload is stale")
        for key in (
            "server_profile_id",
            "profile_revision",
            "transport_kind",
            "target_identity",
            "remote_user",
            "remote_root",
            "platform_paths",
            "runtime_identities",
        ):
            if identity_payload[key] != getattr(self, key):
                raise ExecutionValueError(f"resolved server profile {key} is stale")
        if semantic_id("resolved-server-profile", identity_payload) != self.resolved_server_profile_id:
            raise ExecutionValueError("resolved server profile identity is stale")


def resolve_server_profile(profile: ServerProfile) -> ResolvedServerProfile:
    if not isinstance(profile, ServerProfile):
        raise ExecutionValueError("profile must be a ServerProfile")
    initial_marker = _profile_marker(profile)
    server_profile_id = require_text(profile.server_profile_id, "server_profile_id")
    revision = require_positive_integer(profile.profile_revision, "profile_revision")
    if profile.transport_kind != "legacy_rtwin_pbs":
        raise ExecutionValueError("V30-EXEC-01 only resolves legacy_rtwin_pbs profiles")
    target_host = _validate_host(profile.target_host, "target_host")
    target_port = require_positive_integer(profile.target_port, "target_port")
    if target_port > 65_535:
        raise ExecutionValueError("target_port must be at most 65535")
    remote_user = validate_portable_name(profile.remote_user, "remote_user")
    if profile.host_key_policy != "strict":
        raise ExecutionValueError("legacy_rtwin_pbs requires strict host-key behavior")
    if profile.batch_mode is not True or profile.identities_only is not True:
        raise ExecutionValueError(
            "legacy_rtwin_pbs requires batch mode and explicit identity selection"
        )
    jump_topology: list[Mapping[str, object]] = []
    for index, hop in enumerate(profile.jump_topology):
        if not isinstance(hop, tuple) or len(hop) != 3:
            raise ExecutionValueError(f"jump_topology[{index}] must be (host, port, user)")
        host, port, user = hop
        _validate_host(host, f"jump_topology[{index}].host")
        require_positive_integer(port, f"jump_topology[{index}].port")
        if port > 65_535:
            raise ExecutionValueError(f"jump_topology[{index}].port must be at most 65535")
        validate_portable_name(user, f"jump_topology[{index}].user")
        jump_topology.append(
            freeze_mapping(
                {"host": host, "port": port, "user": user},
                f"jump_topology[{index}]",
            )
        )
    target = freeze_mapping(
        {
            "destination_host": target_host,
            "destination_port": target_port,
            "jump_topology": jump_topology,
            "host_key_policy": profile.host_key_policy,
            "batch_mode": profile.batch_mode,
            "identities_only": profile.identities_only,
        },
        "target_identity",
    )
    if validate_posix_path(profile.remote_root, "remote_root") != LEGACY_REMOTE_ROOT:
        raise ExecutionValueError(f"legacy remote_root must be {LEGACY_REMOTE_ROOT}")

    forbidden_names = {"password", "token", "secret", "private_key", "credential", "agent"}
    platform_paths: dict[str, str] = {}
    for key, value in profile.platform_paths.items():
        require_text(key, "platform_paths key")
        if any(fragment in key.lower() for fragment in forbidden_names):
            raise ExecutionValueError("platform_paths must not identify credential material")
        platform_paths[key] = validate_platform_path(value, f"platform_paths.{key}")

    if not profile.config_files:
        raise ExecutionValueError("resolved profile requires exact config content")
    ordered_config: list[Mapping[str, object]] = []
    seen_config_names: set[str] = set()
    for name, content in profile.config_files:
        validate_portable_name(name, "config logical name")
        if name in seen_config_names:
            raise ExecutionValueError("config logical names must be unique and ordered")
        if not isinstance(content, bytes):
            raise ExecutionValueError("config content must be immutable bytes")
        _reject_secret_content(name, content)
        seen_config_names.add(name)
        ordered_config.append(
            freeze_mapping(
                {"logical_name": name, **_semantic_mapping(bytes_identity(content))},
                "config content identity",
            )
        )

    runtime_identities: dict[str, object] = {}
    for name, content in profile.runtime_contents.items():
        require_text(name, "runtime content name")
        if any(fragment in name.lower() for fragment in forbidden_names):
            raise ExecutionValueError("runtime contents must not include credential material")
        if not isinstance(content, bytes):
            raise ExecutionValueError("runtime content must be immutable bytes")
        _reject_secret_content(name, content)
        runtime_identities[name] = bytes_identity(content)

    effective_payload = freeze_mapping(
        {
            "server_profile_id": server_profile_id,
            "profile_revision": revision,
            "transport_kind": profile.transport_kind,
            "target_identity": target,
            "remote_user": remote_user,
            "remote_root": profile.remote_root,
            "platform_paths": platform_paths,
            "ordered_config_content": ordered_config,
            "runtime_identities": runtime_identities,
        },
        "effective server profile",
    )
    effective_digest = semantic_sha256(effective_payload)
    identity_payload = freeze_mapping(
        {
            **_semantic_mapping(effective_payload),
            "effective_config_sha256": effective_digest,
        },
        "resolved server profile identity",
    )
    resolved_id = semantic_id("resolved-server-profile", identity_payload)
    resolved = ResolvedServerProfile._from_resolved(
        server_profile_id=server_profile_id,
        profile_revision=revision,
        effective_config_sha256=effective_digest,
        transport_kind=profile.transport_kind,
        target_identity=target,
        remote_user=remote_user,
        remote_root=profile.remote_root,
        platform_paths=freeze_mapping(platform_paths, "platform_paths"),
        runtime_identities=freeze_mapping(runtime_identities, "runtime_identities"),
        resolved_server_profile_id=resolved_id,
        identity_payload=identity_payload,
    )
    if _profile_marker(profile) != initial_marker:
        raise ExecutionValueError("ServerProfile mutated during resolution")
    return resolved


@dataclass(frozen=True, slots=True, kw_only=True)
class PbsTemplateBinding:
    logical_name: str
    sha256: str = field(init=False)
    size_bytes: int = field(init=False)
    template_contract_version: str
    pbs_template_binding_id: str = field(init=False)
    _prepared_input_logical_name: str = field(init=False, repr=False, compare=False)

    def __init__(
        self,
        *,
        logical_name: str,
        template_bytes: bytes,
        template_contract_version: str,
        prepared_input_logical_name: str,
    ) -> None:
        validate_portable_name(logical_name, "logical_name")
        validate_portable_name(
            prepared_input_logical_name, "prepared_input_logical_name"
        )
        require_text(template_contract_version, "template_contract_version")
        if template_contract_version != "pbs-template-v1":
            raise ExecutionValueError("unsupported PBS template contract version")
        if not isinstance(template_bytes, bytes) or not template_bytes:
            raise ExecutionValueError("PBS template must be non-empty immutable bytes")
        try:
            text = template_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExecutionValueError("PBS template must be UTF-8") from exc
        if "\x00" in text or "\r" in text or "`" in text or "$(" in text:
            raise ExecutionValueError("PBS template contains forbidden shell expansion bytes")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or lines[0] != "#!/bin/bash":
            raise ExecutionValueError("PBS template must start with the frozen bash shebang")
        commands: list[str] = []
        for line in lines[1:]:
            if line.startswith("#PBS"):
                if not _PBS_NAME_DIRECTIVE.fullmatch(line):
                    raise ExecutionValueError(
                        "PBS template may not bypass the resolved resource request"
                    )
            elif line.startswith("#"):
                continue
            else:
                commands.append(line)
        if len(commands) != 1 or not _PBS_EXECUTION_COMMAND.fullmatch(commands[0]):
            raise ExecutionValueError(
                "PBS template must contain exactly one fixed Gaussian execution command"
            )
        if commands[0] != f"exec g16 {prepared_input_logical_name}":
            raise ExecutionValueError("PBS template command targets another prepared input")
        identity = bytes_identity(template_bytes)
        payload = {
            "logical_name": logical_name,
            "sha256": identity["sha256"],
            "size_bytes": identity["size_bytes"],
            "template_contract_version": template_contract_version,
        }
        object.__setattr__(self, "logical_name", logical_name)
        object.__setattr__(self, "sha256", identity["sha256"])
        object.__setattr__(self, "size_bytes", identity["size_bytes"])
        object.__setattr__(self, "template_contract_version", template_contract_version)
        object.__setattr__(
            self, "_prepared_input_logical_name", prepared_input_logical_name
        )
        object.__setattr__(
            self,
            "pbs_template_binding_id",
            semantic_id("pbs-template-binding", payload),
        )

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "pbs_template_binding_id": self.pbs_template_binding_id,
                "logical_name": self.logical_name,
                "sha256": self.sha256,
                "size_bytes": self.size_bytes,
                "template_contract_version": self.template_contract_version,
            },
            "pbs_template_binding",
        )

    def verify_bytes(self, value: bytes) -> None:
        observed = bytes_identity(value)
        if observed["sha256"] != self.sha256 or observed["size_bytes"] != self.size_bytes:
            raise ExecutionValueError("PBS template bytes differ from their frozen binding")

    def assert_identity_closed(self) -> None:
        payload = {
            key: self.semantic_payload()[key]
            for key in self.semantic_payload()
            if key != "pbs_template_binding_id"
        }
        if semantic_id("pbs-template-binding", payload) != self.pbs_template_binding_id:
            raise ExecutionValueError("PBS template binding identity is stale")
        validate_portable_name(
            self._prepared_input_logical_name, "prepared_input_logical_name"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceBinding:
    project_id: str
    attempt_id: str
    local_attempt_dir: str
    rtwin_attempt_dir: str | None
    remote_attempt_dir: str
    workspace_binding_id: str = field(init=False)
    _local_parent_identity: tuple[int, int] = field(
        init=False, repr=False, compare=False
    )
    _local_approved_root: str = field(init=False, repr=False, compare=False)
    _local_parent_parts: tuple[str, ...] = field(
        init=False, repr=False, compare=False
    )
    _local_component_identities: tuple[tuple[int, int], ...] = field(
        init=False, repr=False, compare=False
    )
    _local_anchor_sha256: str = field(init=False, repr=False, compare=False)

    def __init__(
        self,
        *,
        project: Project,
        attempt_id: str,
        local_approved_root: str,
        local_attempt_dir: str,
        remote_approved_root: str,
        remote_attempt_dir: str,
        rtwin_approved_root: str | None = None,
        rtwin_attempt_dir: str | None = None,
    ) -> None:
        if not isinstance(project, Project):
            raise ExecutionValueError("project must be a public Core Project")
        validate_portable_name(attempt_id, "attempt_id")
        validate_portable_name(project.project_id, "project_id")
        validate_posix_path(local_attempt_dir, "local_attempt_dir")
        validate_posix_path(local_approved_root, "local_approved_root")
        require_contained(local_attempt_dir, local_approved_root, "local_attempt_dir")
        approved_root, parent_parts, component_identities = (
            require_local_workspace_anchor(
                local_attempt_dir, local_approved_root
            )
        )
        validate_posix_path(remote_attempt_dir, "remote_attempt_dir")
        validate_posix_path(remote_approved_root, "remote_approved_root")
        require_contained(remote_attempt_dir, remote_approved_root, "remote_attempt_dir")
        if not remote_attempt_dir.endswith("/" + attempt_id):
            raise ExecutionValueError("remote_attempt_dir must be Attempt-specific")
        if not local_attempt_dir.endswith("/" + attempt_id):
            raise ExecutionValueError("local_attempt_dir must be Attempt-specific")
        if (rtwin_approved_root is None) != (rtwin_attempt_dir is None):
            raise ExecutionValueError("RTwin root and Attempt directory must be provided together")
        if rtwin_attempt_dir is not None and rtwin_approved_root is not None:
            validate_windows_path(rtwin_attempt_dir, "rtwin_attempt_dir")
            validate_windows_path(rtwin_approved_root, "rtwin_approved_root")
            require_windows_contained(
                rtwin_attempt_dir, rtwin_approved_root, "rtwin_attempt_dir"
            )
            if not rtwin_attempt_dir.endswith("\\" + attempt_id):
                raise ExecutionValueError("rtwin_attempt_dir must be Attempt-specific")
        payload = {
            "project_id": project.project_id,
            "attempt_id": attempt_id,
            "local_attempt_dir": local_attempt_dir,
            "rtwin_attempt_dir": rtwin_attempt_dir,
            "remote_attempt_dir": remote_attempt_dir,
        }
        object.__setattr__(self, "project_id", project.project_id)
        object.__setattr__(self, "attempt_id", attempt_id)
        object.__setattr__(self, "local_attempt_dir", local_attempt_dir)
        object.__setattr__(self, "rtwin_attempt_dir", rtwin_attempt_dir)
        object.__setattr__(self, "remote_attempt_dir", remote_attempt_dir)
        object.__setattr__(
            self, "_local_parent_identity", component_identities[-1]
        )
        object.__setattr__(self, "_local_approved_root", approved_root)
        object.__setattr__(self, "_local_parent_parts", parent_parts)
        object.__setattr__(
            self, "_local_component_identities", component_identities
        )
        object.__setattr__(
            self,
            "_local_anchor_sha256",
            semantic_sha256(
                {
                    "approved_root": approved_root,
                    "parent_parts": parent_parts,
                    "component_identities": component_identities,
                }
            ),
        )
        object.__setattr__(
            self, "workspace_binding_id", semantic_id("workspace-binding", payload)
        )

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "workspace_binding_id": self.workspace_binding_id,
                "project_id": self.project_id,
                "attempt_id": self.attempt_id,
                "local_attempt_dir": self.local_attempt_dir,
                "rtwin_attempt_dir": self.rtwin_attempt_dir,
                "remote_attempt_dir": self.remote_attempt_dir,
            },
            "workspace_binding",
        )

    def assert_identity_closed(self) -> None:
        payload = {
            key: self.semantic_payload()[key]
            for key in self.semantic_payload()
            if key != "workspace_binding_id"
        }
        if semantic_id("workspace-binding", payload) != self.workspace_binding_id:
            raise ExecutionValueError("workspace binding identity is stale")
        validate_posix_path(self.local_attempt_dir, "local_attempt_dir")
        validate_posix_path(self._local_approved_root, "local_approved_root")
        expected_parent = self._local_approved_root
        if self._local_parent_parts:
            expected_parent += "/" + "/".join(self._local_parent_parts)
        if self.local_attempt_dir.rsplit("/", 1)[0] != expected_parent:
            raise ExecutionValueError("local workspace descriptor anchor is stale")
        if (
            len(self._local_component_identities)
            != len(self._local_parent_parts) + 1
            or self._local_component_identities[-1] != self._local_parent_identity
        ):
            raise ExecutionValueError("local workspace component identities are stale")
        if self._local_anchor_sha256 != semantic_sha256(
            {
                "approved_root": self._local_approved_root,
                "parent_parts": self._local_parent_parts,
                "component_identities": self._local_component_identities,
            }
        ):
            raise ExecutionValueError("local workspace descriptor anchor identity is stale")
        validate_posix_path(self.remote_attempt_dir, "remote_attempt_dir")
        if self.rtwin_attempt_dir is not None:
            validate_windows_path(self.rtwin_attempt_dir, "rtwin_attempt_dir")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ExecutionSnapshot:
    attempt_id: str
    submission_intent_id: str
    calculation_plan_id: str
    calculation_plan_revision: int
    prepared_input_binding: PreparedInputBinding
    resolved_resource_request: ResolvedResourceRequest
    resolved_server_profile: ResolvedServerProfile
    workspace_binding: WorkspaceBinding
    pbs_template_binding: PbsTemplateBinding
    adapter_contract_version: str
    execution_snapshot_id: str

    def __init__(self) -> None:
        raise TypeError("ExecutionSnapshot is created only by prepare_execution_snapshot")

    @classmethod
    def _from_verified(
        cls,
        *,
        attempt_id: str,
        submission_intent_id: str,
        calculation_plan_id: str,
        calculation_plan_revision: int,
        prepared_input_binding: PreparedInputBinding,
        resolved_resource_request: ResolvedResourceRequest,
        resolved_server_profile: ResolvedServerProfile,
        workspace_binding: WorkspaceBinding,
        pbs_template_binding: PbsTemplateBinding,
        adapter_contract_version: str,
        execution_snapshot_id: str,
    ) -> ExecutionSnapshot:
        value = object.__new__(cls)
        for field_name, field_value in {
            "attempt_id": attempt_id,
            "submission_intent_id": submission_intent_id,
            "calculation_plan_id": calculation_plan_id,
            "calculation_plan_revision": calculation_plan_revision,
            "prepared_input_binding": prepared_input_binding,
            "resolved_resource_request": resolved_resource_request,
            "resolved_server_profile": resolved_server_profile,
            "workspace_binding": workspace_binding,
            "pbs_template_binding": pbs_template_binding,
            "adapter_contract_version": adapter_contract_version,
            "execution_snapshot_id": execution_snapshot_id,
        }.items():
            object.__setattr__(value, field_name, field_value)
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "execution_snapshot_id": self.execution_snapshot_id,
                **_semantic_mapping(self.identity_payload()),
            },
            "execution_snapshot",
        )

    def identity_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "attempt_id": self.attempt_id,
                "submission_intent_id": self.submission_intent_id,
                "calculation_plan_id": self.calculation_plan_id,
                "calculation_plan_revision": self.calculation_plan_revision,
                "prepared_input_binding": self.prepared_input_binding.semantic_payload(),
                "resolved_resource_request": self.resolved_resource_request.semantic_payload(),
                "resolved_server_profile": self.resolved_server_profile.semantic_payload(),
                "workspace_binding": self.workspace_binding.semantic_payload(),
                "pbs_template_binding": self.pbs_template_binding.semantic_payload(),
                "adapter_contract_version": self.adapter_contract_version,
            },
            "execution snapshot identity payload",
        )


class EffectState(str, Enum):
    CONFIRMED_NO_EFFECT = "confirmed_no_effect"
    CONFIRMED_EFFECT = "confirmed_effect"
    POSSIBLY_EFFECTFUL = "possibly_effectful"


class EffectKind(str, Enum):
    LOCAL_WORKSPACE = "local-workspace"
    REMOTE_WORKSPACE = "remote-workspace"
    INPUT_TRANSFER = "input-transfer"
    SUBMISSION = "submission"
    SUBMISSION_RECONCILIATION = "submission-reconciliation"


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteEffectReceipt:
    attempt_id: str
    execution_snapshot_id: str
    submission_intent_id: str
    effect_sequence: int
    effect_kind: EffectKind
    effect_state: EffectState
    remote_workspace: str | None = None
    job_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    remote_effect_receipt_id: str = field(init=False)

    def __post_init__(self) -> None:
        require_text(self.attempt_id, "attempt_id")
        require_text(self.execution_snapshot_id, "execution_snapshot_id")
        require_text(self.submission_intent_id, "submission_intent_id")
        require_positive_integer(self.effect_sequence, "effect_sequence")
        if not isinstance(self.effect_kind, EffectKind):
            raise ExecutionValueError("effect_kind must be an EffectKind")
        if not isinstance(self.effect_state, EffectState):
            raise ExecutionValueError("effect_state must be an EffectState")
        if self.remote_workspace is not None:
            validate_posix_path(self.remote_workspace, "remote_workspace")
        if self.job_id is not None:
            require_text(self.job_id, "job_id")
        if self.effect_state is EffectState.CONFIRMED_EFFECT and self.effect_kind is EffectKind.SUBMISSION:
            if self.job_id is None:
                raise ExecutionValueError("confirmed submission evidence requires a job_id")
        if self.effect_state is not EffectState.CONFIRMED_EFFECT and self.job_id is not None:
            raise ExecutionValueError("only confirmed effect evidence may carry a job_id")
        frozen_details = freeze_mapping(self.details, "details")
        object.__setattr__(self, "details", frozen_details)
        object.__setattr__(
            self,
            "remote_effect_receipt_id",
            semantic_id("remote-effect-receipt", self.record_identity_payload()),
        )

    def record_identity_payload(self) -> Mapping[str, object]:
        """Return the immutable sequence key; changed content must conflict."""

        return freeze_mapping(
            {
                "attempt_id": self.attempt_id,
                "execution_snapshot_id": self.execution_snapshot_id,
                "submission_intent_id": self.submission_intent_id,
                "effect_sequence": self.effect_sequence,
            },
            "remote effect receipt record identity",
        )

    def identity_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "attempt_id": self.attempt_id,
                "execution_snapshot_id": self.execution_snapshot_id,
                "submission_intent_id": self.submission_intent_id,
                "effect_sequence": self.effect_sequence,
                "effect_kind": self.effect_kind.value,
                "effect_state": self.effect_state.value,
                "remote_workspace": self.remote_workspace,
                "job_id": self.job_id,
                "details": self.details,
            },
            "remote effect receipt identity",
        )

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "remote_effect_receipt_id": self.remote_effect_receipt_id,
                **_semantic_mapping(self.identity_payload()),
            },
            "remote effect receipt",
        )

    @classmethod
    def from_payload(cls, value: Mapping[str, object]) -> RemoteEffectReceipt:
        required = {
            "remote_effect_receipt_id",
            "attempt_id",
            "execution_snapshot_id",
            "submission_intent_id",
            "effect_sequence",
            "effect_kind",
            "effect_state",
            "remote_workspace",
            "job_id",
            "details",
        }
        if set(value) != required:
            raise ExecutionValueError("remote effect receipt payload has an invalid shape")
        details = value["details"]
        if not isinstance(details, Mapping):
            raise ExecutionValueError("remote effect receipt details must be a mapping")
        attempt_id = value["attempt_id"]
        snapshot_id = value["execution_snapshot_id"]
        intent_id = value["submission_intent_id"]
        sequence = value["effect_sequence"]
        effect_kind = value["effect_kind"]
        effect_state = value["effect_state"]
        remote_workspace = value["remote_workspace"]
        job_id = value["job_id"]
        if not all(isinstance(item, str) for item in (attempt_id, snapshot_id, intent_id)):
            raise ExecutionValueError("remote effect receipt identities must be strings")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ExecutionValueError("remote effect receipt sequence must be an integer")
        if not isinstance(effect_kind, str) or not isinstance(effect_state, str):
            raise ExecutionValueError("remote effect receipt enums must be strings")
        if remote_workspace is not None and not isinstance(remote_workspace, str):
            raise ExecutionValueError("remote_workspace must be a string or null")
        if job_id is not None and not isinstance(job_id, str):
            raise ExecutionValueError("job_id must be a string or null")
        try:
            receipt = cls(
                attempt_id=attempt_id,
                execution_snapshot_id=snapshot_id,
                submission_intent_id=intent_id,
                effect_sequence=sequence,
                effect_kind=EffectKind(effect_kind),
                effect_state=EffectState(effect_state),
                remote_workspace=remote_workspace,
                job_id=job_id,
                details=details,
            )
        except (TypeError, ValueError) as exc:
            raise ExecutionValueError("remote effect receipt payload is invalid") from exc
        if value["remote_effect_receipt_id"] != receipt.remote_effect_receipt_id:
            raise ExecutionValueError("remote effect receipt identity does not match its payload")
        return receipt
