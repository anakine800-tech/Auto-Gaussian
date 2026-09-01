"""Offline remote Project physical-provisioning foundation for V31."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
from typing import Final

from auto_g16.core import Project

from ._identity import (
    ExecutionValueError,
    freeze_mapping,
    require_text,
    semantic_id,
    semantic_sha256,
)
from ._paths import require_contained, validate_posix_path
from .models import LEGACY_REMOTE_ROOT, ResolvedServerProfile


_CONTRACT_VERSION: Final = "remote-project-physical-binding/2"
_TRANSPORT_KIND: Final = "legacy_rtwin_pbs"
_LOCATION_KIND: Final = "server"
_CLASSIFICATIONS: Final = frozenset(
    {"ABSENT", "PRODUCT_BOUND_EXISTING", "UNBOUND_EXISTING"}
)
_BINDING_DISPOSITIONS: Final = frozenset({"ABSENT", "PRODUCT_BOUND_EXISTING"})
_SYNTHETIC_TEST_HARNESS_PRIVILEGE: Final = object()
_APPLICATION_ID: Final = 0x41335042
_USER_VERSION: Final = 1
_DDL: Final = (
    "CREATE TABLE project_physical_bindings("
    "project_physical_binding_id TEXT PRIMARY KEY,"
    "project_id TEXT NOT NULL UNIQUE,"
    "payload_json TEXT NOT NULL) WITHOUT ROWID",
    "CREATE TRIGGER project_physical_bindings_no_update BEFORE UPDATE ON "
    "project_physical_bindings BEGIN SELECT RAISE(ABORT,'append-only'); END",
    "CREATE TRIGGER project_physical_bindings_no_delete BEFORE DELETE ON "
    "project_physical_bindings BEGIN SELECT RAISE(ABORT,'append-only'); END",
)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validated_target_identity(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != {
        "destination_host",
        "destination_port",
        "jump_topology",
        "host_key_policy",
        "batch_mode",
        "identities_only",
    }:
        raise ExecutionValueError("resolved target identity must have an exact closed field set")
    return freeze_mapping(dict(value), "resolved target identity")


def _validate_remote_target(
    profile: ResolvedServerProfile, remote_project_dir: str
) -> str:
    if not isinstance(profile, ResolvedServerProfile):
        raise ExecutionValueError("target must be an exact ResolvedServerProfile")
    profile.assert_identity_closed()
    if profile.transport_kind != _TRANSPORT_KIND:
        raise ExecutionValueError("remote Project binding requires legacy_rtwin_pbs")
    if profile.remote_root != LEGACY_REMOTE_ROOT:
        raise ExecutionValueError(
            f"legacy remote Project root must be {LEGACY_REMOTE_ROOT}"
        )
    path = validate_posix_path(remote_project_dir, "remote_project_dir")
    require_contained(path, profile.remote_root, "remote_project_dir")
    if path == profile.remote_root:
        raise ExecutionValueError("remote_project_dir must name a Project below remote_root")
    return path


def _validated_location(value: Mapping[str, object]) -> Mapping[str, object]:
    if set(value) != {
        "location_kind",
        "reviewed_root",
        "project_directory",
        "provisioning_disposition",
        "parent_physical_identity",
        "project_physical_identity",
        "evidence_identity",
    }:
        raise ExecutionValueError("Project location must have the frozen closed field set")
    if value["location_kind"] != _LOCATION_KIND:
        raise ExecutionValueError(
            "legacy_rtwin_pbs Project binding must contain only the server location"
        )
    root = validate_posix_path(
        require_text(value["reviewed_root"], "reviewed_root"), "reviewed_root"
    )
    if root != LEGACY_REMOTE_ROOT:
        raise ExecutionValueError(
            f"legacy remote Project root must be {LEGACY_REMOTE_ROOT}"
        )
    directory = validate_posix_path(
        require_text(value["project_directory"], "project_directory"),
        "project_directory",
    )
    require_contained(directory, root, "project_directory")
    if value["provisioning_disposition"] not in _BINDING_DISPOSITIONS:
        raise ExecutionValueError("Project binding has an invalid provisioning disposition")
    for key in (
        "parent_physical_identity",
        "project_physical_identity",
        "evidence_identity",
    ):
        require_text(value[key], key)
    return freeze_mapping(dict(value), "remote Project location")


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProjectPhysicalBinding:
    """Durable binding for one Project in the final-server namespace."""

    project_physical_binding_id: str
    project_id: str
    provisioning_contract_version: str
    transport_kind: str
    resolved_server_profile_id: str
    resolved_target_identity: Mapping[str, object]
    provisioning_authority_id: str
    locations: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProjectPhysicalBinding is created only by Project provisioning")

    @property
    def remote_root(self) -> str:
        return str(self.locations[0]["reviewed_root"])

    @property
    def remote_project_dir(self) -> str:
        return str(self.locations[0]["project_directory"])

    @property
    def project_physical_identity(self) -> str:
        return str(self.locations[0]["project_physical_identity"])

    @property
    def parent_physical_identity(self) -> str:
        return str(self.locations[0]["parent_physical_identity"])

    @property
    def evidence_identity(self) -> str:
        return str(self.locations[0]["evidence_identity"])

    @classmethod
    def _from_attested(
        cls,
        *,
        project: Project,
        target: ResolvedServerProfile,
        remote_project_dir: str,
        provisioning_disposition: str,
        parent_physical_identity: str,
        project_physical_identity: str,
        evidence_identity: str,
        provisioning_authority_id: str,
    ) -> ProjectPhysicalBinding:
        if not isinstance(project, Project):
            raise ExecutionValueError("project must be a public Core Project")
        path = _validate_remote_target(target, remote_project_dir)
        location = _validated_location(
            {
                "location_kind": _LOCATION_KIND,
                "reviewed_root": target.remote_root,
                "project_directory": path,
                "provisioning_disposition": provisioning_disposition,
                "parent_physical_identity": parent_physical_identity,
                "project_physical_identity": project_physical_identity,
                "evidence_identity": evidence_identity,
            }
        )
        payload = freeze_mapping(
            {
                "project_id": project.project_id,
                "provisioning_contract_version": _CONTRACT_VERSION,
                "transport_kind": _TRANSPORT_KIND,
                "resolved_server_profile_id": target.resolved_server_profile_id,
                "resolved_target_identity": _validated_target_identity(
                    target.target_identity
                ),
                "provisioning_authority_id": require_text(
                    provisioning_authority_id, "provisioning_authority_id"
                ),
                "locations": (location,),
            },
            "ProjectPhysicalBinding identity payload",
        )
        value = object.__new__(cls)
        for name, item in payload.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_identity_payload", payload)
        object.__setattr__(
            value,
            "project_physical_binding_id",
            semantic_id("project-physical-binding", payload),
        )
        return value

    def semantic_payload(self) -> Mapping[str, object]:
        return freeze_mapping(
            {
                "project_physical_binding_id": self.project_physical_binding_id,
                **{key: self._identity_payload[key] for key in self._identity_payload},
            },
            "ProjectPhysicalBinding",
        )

    def assert_identity_closed(self) -> None:
        if self.provisioning_contract_version != _CONTRACT_VERSION:
            raise ExecutionValueError("ProjectPhysicalBinding contract version is stale")
        if self.transport_kind != _TRANSPORT_KIND:
            raise ExecutionValueError("ProjectPhysicalBinding transport is stale")
        if not isinstance(self.locations, tuple) or len(self.locations) != 1:
            raise ExecutionValueError(
                "legacy_rtwin_pbs Project binding requires exactly one server location"
            )
        location = _validated_location(self.locations[0])
        payload = freeze_mapping(
            {
                "project_id": require_text(self.project_id, "project_id"),
                "provisioning_contract_version": self.provisioning_contract_version,
                "transport_kind": self.transport_kind,
                "resolved_server_profile_id": require_text(
                    self.resolved_server_profile_id, "resolved_server_profile_id"
                ),
                "resolved_target_identity": _validated_target_identity(
                    self.resolved_target_identity
                ),
                "provisioning_authority_id": require_text(
                    self.provisioning_authority_id, "provisioning_authority_id"
                ),
                "locations": (location,),
            },
            "ProjectPhysicalBinding verification payload",
        )
        if payload != self._identity_payload or semantic_id(
            "project-physical-binding", payload
        ) != self.project_physical_binding_id:
            raise ExecutionValueError("ProjectPhysicalBinding identity is stale")


def _target_key(
    target: ResolvedServerProfile, remote_project_dir: str
) -> tuple[str, str, str]:
    target.assert_identity_closed()
    path = validate_posix_path(remote_project_dir, "observed remote Project path")
    return (
        target.resolved_server_profile_id,
        semantic_sha256(target.target_identity),
        path,
    )


class _SyntheticRemoteProjectAttestor:
    """Explicitly privileged offline stand-in for future Transport observation."""

    __slots__ = ("_observations", "_provision_count", "_lock")

    def __init__(self) -> None:
        raise TypeError("synthetic attestors require the privileged test harness")

    @classmethod
    def _from_privileged_test_fixture(
        cls,
        *,
        privilege: object,
        target: ResolvedServerProfile,
        observed_project_dir: str,
        observed_state: str,
        observed_parent_physical_identity: str,
        observed_project_physical_identity: str | None,
        provisioned_project_physical_identity: str | None = None,
    ) -> _SyntheticRemoteProjectAttestor:
        if privilege is not _SYNTHETIC_TEST_HARNESS_PRIVILEGE:
            raise ExecutionValueError("synthetic Project attestor privilege is required")
        if not isinstance(target, ResolvedServerProfile):
            raise ExecutionValueError("synthetic target must be a ResolvedServerProfile")
        target.assert_identity_closed()
        if observed_state not in {"ABSENT", "EXISTING"}:
            raise ExecutionValueError("synthetic Project state is outside the closed set")
        parent_identity = require_text(
            observed_parent_physical_identity,
            "observed_parent_physical_identity",
        )
        if observed_state == "EXISTING":
            project_identity = require_text(
                observed_project_physical_identity,
                "observed_project_physical_identity",
            )
            if provisioned_project_physical_identity is not None:
                raise ExecutionValueError(
                    "existing synthetic target cannot carry a provisioned identity"
                )
            provisioned_identity = None
        else:
            if observed_project_physical_identity is not None:
                raise ExecutionValueError("absent synthetic target has a Project identity")
            project_identity = None
            provisioned_identity = require_text(
                provisioned_project_physical_identity,
                "provisioned_project_physical_identity",
            )
        value = object.__new__(cls)
        value._observations = {
            _target_key(target, observed_project_dir): (
                observed_state,
                parent_identity,
                project_identity,
                provisioned_identity,
            )
        }
        value._provision_count = 0
        value._lock = RLock()
        return value

    def _observe_current(
        self, target: ResolvedServerProfile, remote_project_dir: str
    ) -> tuple[str, str, str | None]:
        key = _target_key(target, remote_project_dir)
        with self._lock:
            observation = self._observations.get(key)
        if observation is None:
            raise ExecutionValueError(
                "no current observation exists for the exact remote Project target"
            )
        state, parent_identity, project_identity, _provisioned_identity = observation
        return str(state), str(parent_identity), (
            None if project_identity is None else str(project_identity)
        )

    def _provision_absent_for_test(
        self, target: ResolvedServerProfile, remote_project_dir: str
    ) -> tuple[str, str]:
        key = _target_key(target, remote_project_dir)
        with self._lock:
            observation = self._observations.get(key)
            if observation is None or observation[0] != "ABSENT":
                raise ExecutionValueError("synthetic target is not absent")
            _state, parent_identity, _project_identity, provisioned_identity = observation
            if provisioned_identity is None:
                raise ExecutionValueError("synthetic provisioned identity is missing")
            self._observations[key] = (
                "EXISTING",
                parent_identity,
                provisioned_identity,
                None,
            )
            self._provision_count += 1
        return str(parent_identity), str(provisioned_identity)

    def _replace_fixture_identity(
        self,
        *,
        target: ResolvedServerProfile,
        remote_project_dir: str,
        observed_parent_physical_identity: str | None = None,
        observed_project_physical_identity: str,
    ) -> None:
        key = _target_key(target, remote_project_dir)
        identity = require_text(
            observed_project_physical_identity, "observed_project_physical_identity"
        )
        with self._lock:
            observation = self._observations.get(key)
            if observation is None or observation[0] != "EXISTING":
                raise ExecutionValueError("synthetic replacement target is not existing")
            parent = (
                str(observation[1])
                if observed_parent_physical_identity is None
                else require_text(
                    observed_parent_physical_identity,
                    "observed_parent_physical_identity",
                )
            )
            self._observations[key] = ("EXISTING", parent, identity, None)


class _CurrentProjectProof:
    """Private, authority-bound, target-scoped current observation."""

    __slots__ = (
        "_binding_id",
        "_provisioning_authority_id",
        "_resolved_server_profile_id",
        "_target_identity_sha256",
        "_remote_project_dir",
        "_parent_physical_identity",
        "_project_physical_identity",
        "_service_token",
        "_nonce",
    )

    def __init__(self) -> None:
        raise TypeError("current Project proofs are issued only by provisioning")


class _ProjectProvisioningService:
    """Private owning authority for Project classification and freshness."""

    __slots__ = (
        "_attestor",
        "_authority_id",
        "_service_token",
        "_active_proofs",
        "_lock",
    )

    def __init__(self) -> None:
        raise TypeError("Project provisioning requires an owning authority")

    @classmethod
    def _from_privileged_synthetic_attestor(
        cls,
        *,
        privilege: object,
        attestor: _SyntheticRemoteProjectAttestor,
    ) -> _ProjectProvisioningService:
        if privilege is not _SYNTHETIC_TEST_HARNESS_PRIVILEGE:
            raise ExecutionValueError("synthetic Project provisioning privilege is required")
        if type(attestor) is not _SyntheticRemoteProjectAttestor:
            raise ExecutionValueError("Project provisioning requires the exact private attestor")
        value = object.__new__(cls)
        value._attestor = attestor
        value._service_token = secrets.token_bytes(32)
        value._authority_id = semantic_id(
            "project-provisioning-authority",
            {"opaque_authority_nonce": value._service_token.hex()},
        )
        value._active_proofs = {}
        value._lock = RLock()
        return value

    def classify_remote_project(
        self,
        *,
        project: Project,
        target: ResolvedServerProfile,
        remote_project_dir: str,
        stored_binding: ProjectPhysicalBinding | None,
    ) -> tuple[str, ProjectPhysicalBinding | None]:
        if not isinstance(project, Project):
            raise ExecutionValueError("project must be a public Core Project")
        path = _validate_remote_target(target, remote_project_dir)
        state, parent_identity, project_identity = self._attestor._observe_current(
            target, path
        )
        if state == "ABSENT":
            if stored_binding is not None:
                raise ExecutionValueError(
                    "a Product-bound remote Project was replaced or removed"
                )
            return "ABSENT", None
        if state != "EXISTING" or project_identity is None:
            raise ExecutionValueError("remote Project observation has an invalid state")
        if stored_binding is None:
            return "UNBOUND_EXISTING", None
        self._assert_owned_binding(
            binding=stored_binding,
            project=project,
            target=target,
            remote_project_dir=path,
        )
        if (
            stored_binding.parent_physical_identity != parent_identity
            or stored_binding.project_physical_identity != project_identity
        ):
            raise ExecutionValueError("remote Project physical identity drifted")
        return "PRODUCT_BOUND_EXISTING", stored_binding

    def provision_remote_project(
        self,
        *,
        project: Project,
        target: ResolvedServerProfile,
        remote_project_dir: str,
        evidence_identity: str,
        stored_binding: ProjectPhysicalBinding | None = None,
    ) -> ProjectPhysicalBinding:
        classification, replay = self.classify_remote_project(
            project=project,
            target=target,
            remote_project_dir=remote_project_dir,
            stored_binding=stored_binding,
        )
        if classification == "UNBOUND_EXISTING":
            raise ExecutionValueError(
                "UNBOUND_EXISTING remote Project requires an Owner adoption decision"
            )
        if classification == "PRODUCT_BOUND_EXISTING":
            if replay is None:
                raise ExecutionValueError("Product-bound replay lost its binding")
            return replay
        if classification != "ABSENT":
            raise ExecutionValueError("Project classification is outside the closed set")
        parent_identity, project_identity = self._attestor._provision_absent_for_test(
            target, remote_project_dir
        )
        return ProjectPhysicalBinding._from_attested(
            project=project,
            target=target,
            remote_project_dir=remote_project_dir,
            provisioning_disposition="ABSENT",
            parent_physical_identity=parent_identity,
            project_physical_identity=project_identity,
            evidence_identity=require_text(evidence_identity, "evidence_identity"),
            provisioning_authority_id=self._authority_id,
        )

    def _assert_owned_binding(
        self,
        *,
        binding: ProjectPhysicalBinding,
        project: Project,
        target: ResolvedServerProfile,
        remote_project_dir: str,
    ) -> None:
        if not isinstance(binding, ProjectPhysicalBinding):
            raise ExecutionValueError("binding must be a ProjectPhysicalBinding")
        binding.assert_identity_closed()
        if (
            binding.project_id != project.project_id
            or binding.transport_kind != target.transport_kind
            or binding.resolved_server_profile_id
            != target.resolved_server_profile_id
            or binding.resolved_target_identity != target.target_identity
            or binding.remote_root != target.remote_root
            or binding.remote_project_dir != remote_project_dir
            or binding.provisioning_authority_id != self._authority_id
        ):
            raise ExecutionValueError(
                "Project binding belongs to another owning provisioning authority or target"
            )

    def _attest_current(
        self,
        binding: ProjectPhysicalBinding,
        target: ResolvedServerProfile,
    ) -> _CurrentProjectProof:
        self._assert_owned_binding(
            binding=binding,
            project=Project(project_id=binding.project_id),
            target=target,
            remote_project_dir=binding.remote_project_dir,
        )
        state, parent_identity, project_identity = self._attestor._observe_current(
            target, binding.remote_project_dir
        )
        if state != "EXISTING" or project_identity is None:
            raise ExecutionValueError("bound remote Project is not currently existing")
        proof = object.__new__(_CurrentProjectProof)
        proof._binding_id = binding.project_physical_binding_id
        proof._provisioning_authority_id = self._authority_id
        proof._resolved_server_profile_id = target.resolved_server_profile_id
        proof._target_identity_sha256 = semantic_sha256(target.target_identity)
        proof._remote_project_dir = binding.remote_project_dir
        proof._parent_physical_identity = parent_identity
        proof._project_physical_identity = project_identity
        proof._service_token = self._service_token
        proof._nonce = secrets.token_bytes(32)
        active = (
            proof,
            proof._binding_id,
            proof._provisioning_authority_id,
            proof._resolved_server_profile_id,
            proof._target_identity_sha256,
            proof._remote_project_dir,
            proof._parent_physical_identity,
            proof._project_physical_identity,
            proof._service_token,
        )
        with self._lock:
            self._active_proofs[proof._nonce] = active
        return proof

    def _consume_current(
        self,
        *,
        binding: ProjectPhysicalBinding,
        target: ResolvedServerProfile,
        proof: _CurrentProjectProof,
    ) -> str:
        if type(proof) is not _CurrentProjectProof:
            raise ExecutionValueError("fresh private Project proof is required")
        binding.assert_identity_closed()
        target.assert_identity_closed()
        with self._lock:
            active = self._active_proofs.pop(proof._nonce, None)
        if active is None or len(active) != 9 or active[0] is not proof:
            raise ExecutionValueError("Project proof is stale or already consumed")
        proof_payload = (
            proof._binding_id,
            proof._provisioning_authority_id,
            proof._resolved_server_profile_id,
            proof._target_identity_sha256,
            proof._remote_project_dir,
            proof._parent_physical_identity,
            proof._project_physical_identity,
            proof._service_token,
        )
        expected = (
            binding.project_physical_binding_id,
            binding.provisioning_authority_id,
            target.resolved_server_profile_id,
            semantic_sha256(target.target_identity),
            binding.remote_project_dir,
            binding.parent_physical_identity,
            binding.project_physical_identity,
            self._service_token,
        )
        if tuple(active[1:]) != proof_payload or proof_payload != expected:
            raise ExecutionValueError(
                "fresh Project proof does not match the exact binding and owner"
            )
        return binding.remote_project_dir


class _ProvisioningJournal:
    """Private append-only store for durable remote Project bindings."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ExecutionValueError("provisioning journal path must be an absolute Path")
        if path.is_symlink():
            raise ExecutionValueError("provisioning journal must not be a symlink")
        existed = path.exists()
        self._connection = sqlite3.connect(path, isolation_level=None)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        self._connection.execute("PRAGMA synchronous=FULL")
        if not existed:
            self._connection.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            self._connection.execute(f"PRAGMA user_version={_USER_VERSION}")
            for statement in _DDL:
                self._connection.execute(statement)
        self._attest()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> _ProvisioningJournal:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _attest(self) -> None:
        if self._connection.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION_ID:
            raise ExecutionValueError("provisioning journal application identity drifted")
        if self._connection.execute("PRAGMA user_version").fetchone()[0] != _USER_VERSION:
            raise ExecutionValueError("provisioning journal schema version drifted")
        observed = {
            row[0]: row[1]
            for row in self._connection.execute(
                "SELECT name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }
        expected = {}
        for statement in _DDL:
            words = statement.split()
            name = words[2].split("(", 1)[0]
            expected[name] = statement
        if observed != expected:
            raise ExecutionValueError("provisioning journal schema identity drifted")

    def append_binding(self, binding: ProjectPhysicalBinding) -> None:
        if not isinstance(binding, ProjectPhysicalBinding):
            raise ExecutionValueError("binding must be a ProjectPhysicalBinding")
        binding.assert_identity_closed()
        payload = _canonical_json(binding.semantic_payload())
        self._append(
            "project_physical_bindings",
            (binding.project_physical_binding_id, binding.project_id, payload),
        )

    def load_binding(self, project_id: str) -> ProjectPhysicalBinding | None:
        require_text(project_id, "project_id")
        rows = self._connection.execute(
            "SELECT payload_json FROM project_physical_bindings WHERE project_id=?",
            (project_id,),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ExecutionValueError("provisioning journal contains duplicate bindings")
        raw = json.loads(rows[0][0])
        expected = {
            "project_physical_binding_id",
            "project_id",
            "provisioning_contract_version",
            "transport_kind",
            "resolved_server_profile_id",
            "resolved_target_identity",
            "provisioning_authority_id",
            "locations",
        }
        if not isinstance(raw, dict) or set(raw) != expected:
            raise ExecutionValueError("persisted Project binding is malformed")
        if raw["provisioning_contract_version"] != _CONTRACT_VERSION:
            raise ExecutionValueError("persisted Project binding contract is stale")
        locations = raw["locations"]
        if not isinstance(locations, list):
            raise ExecutionValueError("persisted Project locations are malformed")
        payload = freeze_mapping(
            {
                **{
                    key: raw[key]
                    for key in raw
                    if key not in {"project_physical_binding_id", "locations"}
                },
                "locations": tuple(locations),
            },
            "persisted Project binding payload",
        )
        value = object.__new__(ProjectPhysicalBinding)
        for name, item in payload.items():
            object.__setattr__(value, name, item)
        object.__setattr__(value, "_identity_payload", payload)
        object.__setattr__(
            value,
            "project_physical_binding_id",
            raw["project_physical_binding_id"],
        )
        value.assert_identity_closed()
        if value.semantic_payload() != freeze_mapping(
            {**raw, "locations": tuple(locations)}, "persisted Project binding"
        ):
            raise ExecutionValueError("persisted Project binding is noncanonical or stale")
        return value

    def _append(self, table: str, values: tuple[str, ...]) -> None:
        self._attest()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            placeholders = ",".join("?" for _ in values)
            try:
                self._connection.execute(
                    f"INSERT INTO {table} VALUES({placeholders})", values
                )
            except sqlite3.IntegrityError:
                row = self._connection.execute(
                    f"SELECT * FROM {table} WHERE project_physical_binding_id=?",
                    (values[0],),
                ).fetchone()
                if row is None or tuple(row) != values:
                    raise ExecutionValueError(
                        "conflicting immutable provisioning authority"
                    )
            self._attest()
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise


__all__ = ["ProjectPhysicalBinding"]
