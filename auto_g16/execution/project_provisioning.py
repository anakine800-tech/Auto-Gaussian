"""Offline Project physical-binding foundation for the V31 successor."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import sqlite3
import stat
import secrets
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
from ._paths import (
    require_contained,
    require_windows_contained,
    validate_posix_path,
    validate_windows_path,
)


_CONTRACT_VERSION: Final = "project-physical-provisioning/1"
_LOCATION_KINDS: Final = frozenset({"local", "rtwin", "server"})
_DISPOSITIONS: Final = frozenset({"ABSENT", "PRODUCT_BOUND_EXISTING"})
_CLASSIFICATIONS: Final = frozenset(
    {"ABSENT", "PRODUCT_BOUND_EXISTING", "UNBOUND_EXISTING"}
)
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
_PROOF_LOCK: Final = RLock()
_ACTIVE_PROOFS: Final[dict[bytes, tuple[object, ...]]] = {}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(value[key]) for key in value}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        _plain(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ExecutionValueError(f"{label} must have an exact closed field set")


def _path_for_kind(kind: str, path: str, field_name: str) -> str:
    if kind in {"local", "server"}:
        return validate_posix_path(path, field_name)
    return validate_windows_path(path, field_name)


def _contained_for_kind(kind: str, path: str, root: str, field_name: str) -> None:
    if kind in {"local", "server"}:
        require_contained(path, root, field_name)
    else:
        require_windows_contained(path, root, field_name)


def _validated_location(value: Mapping[str, object], index: int) -> Mapping[str, object]:
    label = f"locations[{index}]"
    _exact_keys(
        value,
        {
            "location_kind",
            "reviewed_root",
            "project_directory",
            "provisioning_disposition",
            "parent_physical_identity",
            "project_physical_identity",
            "evidence_identity",
        },
        label,
    )
    kind = require_text(value["location_kind"], f"{label}.location_kind")
    if kind not in _LOCATION_KINDS:
        raise ExecutionValueError(f"{label}.location_kind is outside the closed V31 set")
    root = _path_for_kind(kind, require_text(value["reviewed_root"], f"{label}.reviewed_root"), f"{label}.reviewed_root")
    directory = _path_for_kind(
        kind,
        require_text(value["project_directory"], f"{label}.project_directory"),
        f"{label}.project_directory",
    )
    _contained_for_kind(kind, directory, root, f"{label}.project_directory")
    disposition = require_text(
        value["provisioning_disposition"], f"{label}.provisioning_disposition"
    )
    if disposition not in _DISPOSITIONS:
        raise ExecutionValueError(f"{label} cannot bind an unbound-existing target")
    for key in (
        "parent_physical_identity",
        "project_physical_identity",
        "evidence_identity",
    ):
        require_text(value[key], f"{label}.{key}")
    return freeze_mapping(dict(value), label)


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class ProjectPhysicalBinding:
    """Opaque durable identity for one Core Project's reviewed locations."""

    project_physical_binding_id: str
    project_id: str
    provisioning_contract_version: str
    locations: tuple[Mapping[str, object], ...]
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("ProjectPhysicalBinding is created only from inspected evidence")

    @classmethod
    def _from_inspected(
        cls,
        *,
        project: Project,
        locations: tuple[Mapping[str, object], ...],
    ) -> ProjectPhysicalBinding:
        if not isinstance(project, Project):
            raise ExecutionValueError("project must be a public Core Project")
        if not isinstance(locations, tuple) or not locations:
            raise ExecutionValueError("locations must be an ordered non-empty tuple")
        closed = tuple(_validated_location(item, index) for index, item in enumerate(locations))
        keys = tuple(
            (item["location_kind"], item["project_directory"]) for item in closed
        )
        if len(set(keys)) != len(keys):
            raise ExecutionValueError("locations contain duplicate physical targets")
        payload = freeze_mapping(
            {
                "project_id": project.project_id,
                "provisioning_contract_version": _CONTRACT_VERSION,
                "locations": closed,
            },
            "ProjectPhysicalBinding identity payload",
        )
        value = object.__new__(cls)
        object.__setattr__(value, "project_id", project.project_id)
        object.__setattr__(value, "provisioning_contract_version", _CONTRACT_VERSION)
        object.__setattr__(value, "locations", closed)
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
        closed = tuple(
            _validated_location(item, index) for index, item in enumerate(self.locations)
        )
        payload = freeze_mapping(
            {
                "project_id": self.project_id,
                "provisioning_contract_version": self.provisioning_contract_version,
                "locations": closed,
            },
            "ProjectPhysicalBinding verification payload",
        )
        if payload != self._identity_payload or semantic_id(
            "project-physical-binding", payload
        ) != self.project_physical_binding_id:
            raise ExecutionValueError("ProjectPhysicalBinding identity is stale")


def _opaque_stat_identity(value: os.stat_result, domain: str) -> str:
    return semantic_sha256(
        {
            "domain": domain,
            "device": value.st_dev,
            "inode": value.st_ino,
            "mode": stat.S_IFMT(value.st_mode),
        }
    )


def _inspect_local_target(
    *, reviewed_root: str, project_directory: str
) -> tuple[str, str, str | None]:
    validate_posix_path(reviewed_root, "reviewed_root")
    validate_posix_path(project_directory, "project_directory")
    require_contained(project_directory, reviewed_root, "project_directory")
    root = Path(reviewed_root)
    target = Path(project_directory)
    try:
        root_stat = os.lstat(root)
        parent_stat = os.lstat(target.parent)
    except OSError as exc:
        raise ExecutionValueError("reviewed provisioning root or parent is unavailable") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ExecutionValueError("reviewed provisioning root must be a real directory")
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise ExecutionValueError("Project parent must be a real directory")
    try:
        if str(root.resolve(strict=True)) != reviewed_root or str(target.parent.resolve(strict=True)) != str(target.parent):
            raise ExecutionValueError("provisioning paths must already be canonical and no-follow")
    except OSError as exc:
        raise ExecutionValueError("provisioning parent chain is unavailable") from exc
    parent_identity = _opaque_stat_identity(parent_stat, "project-parent")
    try:
        target_stat = os.lstat(target)
    except FileNotFoundError:
        return "ABSENT", parent_identity, None
    except OSError as exc:
        raise ExecutionValueError("Project target cannot be inspected") from exc
    if stat.S_ISLNK(target_stat.st_mode) or not stat.S_ISDIR(target_stat.st_mode):
        raise ExecutionValueError("Project target must be a real directory")
    return (
        "EXISTING",
        parent_identity,
        _opaque_stat_identity(target_stat, "project-directory"),
    )


def _classify_project_target(
    *,
    project: Project,
    reviewed_root: str,
    project_directory: str,
    stored_binding: ProjectPhysicalBinding | None,
) -> tuple[str, ProjectPhysicalBinding | None]:
    """Read-only three-way classification; this function never calls mkdir."""

    if not isinstance(project, Project):
        raise ExecutionValueError("project must be a public Core Project")
    state, parent_identity, target_identity = _inspect_local_target(
        reviewed_root=reviewed_root, project_directory=project_directory
    )
    if state == "ABSENT":
        if stored_binding is not None:
            raise ExecutionValueError("a Product-bound Project target was replaced or removed")
        return "ABSENT", None
    if stored_binding is None:
        return "UNBOUND_EXISTING", None
    if not isinstance(stored_binding, ProjectPhysicalBinding):
        raise ExecutionValueError("stored_binding must be a ProjectPhysicalBinding")
    stored_binding.assert_identity_closed()
    if stored_binding.project_id != project.project_id:
        raise ExecutionValueError("stored Project binding belongs to another Project")
    matching = tuple(
        location
        for location in stored_binding.locations
        if location["location_kind"] == "local"
        and location["reviewed_root"] == reviewed_root
        and location["project_directory"] == project_directory
    )
    if len(matching) != 1:
        raise ExecutionValueError("stored Project binding does not own the exact target")
    location = matching[0]
    if (
        location["parent_physical_identity"] != parent_identity
        or location["project_physical_identity"] != target_identity
    ):
        raise ExecutionValueError("Project target or parent physical identity drifted")
    return "PRODUCT_BOUND_EXISTING", stored_binding


class _ProjectBindingReattestation:
    """Private single-consumption proof; raw physical evidence never becomes public."""

    __slots__ = (
        "_binding_id",
        "_location_kind",
        "_reviewed_root",
        "_project_directory",
        "_parent_identity",
        "_target_identity",
        "_local_reinspection",
        "_nonce",
    )

    def __init__(self) -> None:
        raise TypeError("Project reattestation proofs are issued only by provisioning")


def _reattest_project_binding(
    binding: ProjectPhysicalBinding,
) -> _ProjectBindingReattestation:
    if not isinstance(binding, ProjectPhysicalBinding):
        raise ExecutionValueError("binding must be a ProjectPhysicalBinding")
    binding.assert_identity_closed()
    local = tuple(
        item for item in binding.locations if item["location_kind"] == "local"
    )
    if len(local) != 1:
        raise ExecutionValueError("offline successor preparation requires one local Project binding")
    location = local[0]
    state, parent_identity, target_identity = _inspect_local_target(
        reviewed_root=str(location["reviewed_root"]),
        project_directory=str(location["project_directory"]),
    )
    if state != "EXISTING" or target_identity is None:
        raise ExecutionValueError("bound Project target is no longer present")
    if (
        location["parent_physical_identity"] != parent_identity
        or location["project_physical_identity"] != target_identity
    ):
        raise ExecutionValueError("Project target or parent physical identity drifted")
    proof = object.__new__(_ProjectBindingReattestation)
    nonce = secrets.token_bytes(32)
    proof._binding_id = binding.project_physical_binding_id
    proof._location_kind = "local"
    proof._reviewed_root = str(location["reviewed_root"])
    proof._project_directory = str(location["project_directory"])
    proof._parent_identity = parent_identity
    proof._target_identity = target_identity
    proof._local_reinspection = True
    proof._nonce = nonce
    with _PROOF_LOCK:
        _ACTIVE_PROOFS[nonce] = (
            proof,
            proof._binding_id,
            proof._location_kind,
            proof._reviewed_root,
            proof._project_directory,
            proof._parent_identity,
            proof._target_identity,
            proof._local_reinspection,
        )
    return proof


def _consume_project_binding_reattestation(
    binding: ProjectPhysicalBinding,
    proof: _ProjectBindingReattestation,
) -> tuple[str, str]:
    if not isinstance(binding, ProjectPhysicalBinding) or not isinstance(
        proof, _ProjectBindingReattestation
    ):
        raise ExecutionValueError("fresh Project reattestation proof is required")
    with _PROOF_LOCK:
        active = _ACTIVE_PROOFS.pop(proof._nonce, None)
        if active is None or active[0] is not proof or len(active) != 8:
            raise ExecutionValueError("Project reattestation proof is stale or already consumed")
        (
            _active_proof,
            binding_id,
            location_kind,
            reviewed_root,
            project_directory,
            parent_identity,
            target_identity,
            local_reinspection,
        ) = active
        if binding_id != binding.project_physical_binding_id:
            raise ExecutionValueError("Project reattestation proof belongs to another binding")
        matching = tuple(
            item
            for item in binding.locations
            if item["location_kind"] == location_kind
            and item["reviewed_root"] == reviewed_root
            and item["project_directory"] == project_directory
        )
        if len(matching) != 1 or (
            matching[0]["parent_physical_identity"] != parent_identity
            or matching[0]["project_physical_identity"] != target_identity
        ):
            raise ExecutionValueError("fresh proof does not match the exact Project binding")
        if local_reinspection:
            if location_kind != "local":
                raise ExecutionValueError("local reinspection proof has an invalid location")
            state, current_parent_identity, current_target_identity = _inspect_local_target(
                reviewed_root=str(reviewed_root),
                project_directory=str(project_directory),
            )
            if (
                state != "EXISTING"
                or current_target_identity is None
                or current_parent_identity != parent_identity
                or current_target_identity != target_identity
            ):
                raise ExecutionValueError(
                    "Project target changed after fresh reattestation"
                )
        return str(location_kind), str(project_directory)


def _binding_from_existing_local_target(
    *, project: Project, reviewed_root: str, project_directory: str, evidence_identity: str
) -> ProjectPhysicalBinding:
    state, parent_identity, target_identity = _inspect_local_target(
        reviewed_root=reviewed_root, project_directory=project_directory
    )
    if state != "EXISTING" or target_identity is None:
        raise ExecutionValueError("a durable binding requires an existing inspected target")
    require_text(evidence_identity, "evidence_identity")
    return ProjectPhysicalBinding._from_inspected(
        project=project,
        locations=(
            {
                "location_kind": "local",
                "reviewed_root": reviewed_root,
                "project_directory": project_directory,
                "provisioning_disposition": "PRODUCT_BOUND_EXISTING",
                "parent_physical_identity": parent_identity,
                "project_physical_identity": target_identity,
                "evidence_identity": evidence_identity,
            },
        ),
    )


class _ProvisioningJournal:
    """Private append-only store for durable Project physical bindings."""

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
        if not isinstance(raw, dict) or set(raw) != {
            "project_physical_binding_id",
            "project_id",
            "provisioning_contract_version",
            "locations",
        }:
            raise ExecutionValueError("persisted Project binding is malformed")
        value = ProjectPhysicalBinding._from_inspected(
            project=Project(project_id=raw["project_id"]),
            locations=tuple(raw["locations"]),
        )
        if value.semantic_payload() != freeze_mapping(raw, "persisted Project binding"):
            raise ExecutionValueError("persisted Project binding is noncanonical or stale")
        return value

    def _append(self, table: str, values: tuple[str, ...]) -> None:
        self._attest()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            placeholders = ",".join("?" for _ in values)
            try:
                self._connection.execute(f"INSERT INTO {table} VALUES({placeholders})", values)
            except sqlite3.IntegrityError:
                row = self._connection.execute(
                    f"SELECT * FROM {table} WHERE project_physical_binding_id=?",
                    (values[0],),
                ).fetchone()
                if row is None or tuple(row) != values:
                    raise ExecutionValueError("conflicting immutable provisioning authority")
            self._attest()
            self._connection.execute("COMMIT")
        except Exception:
            self._connection.execute("ROLLBACK")
            raise


__all__ = ["ProjectPhysicalBinding"]
