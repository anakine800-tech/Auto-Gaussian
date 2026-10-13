#!/usr/bin/env python3
"""Seal one non-executable PR4L -> PR4M lifecycle readiness handoff.

The only public input is the exact owner-issued PR4L local materialization.
This owner replays that materialization, obtains one read-only PR4M lifecycle
witness from the exact legacy module, and stops.  It never creates a legacy
transaction plan, effect plan, raw-effect owner, lifecycle registry entry,
adapter, command, callback, or runner invocation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "auto-g16-protected-legacy-effect-handoff/1"
OWNER = "auto-g16-protected-legacy-effect-handoff-owner"
MATERIALIZATION_MODULE_NAME = "protected_local_materialization"
LEGACY_MODULE_NAME = "legacy_rtwin_pbs"
MATERIALIZATION_SCHEMA = "auto-g16-protected-local-materialization/1"
READINESS_SCHEMA = (
    "auto-g16-legacy-effect-lifecycle-readiness-witness/1"
)
EFFECT_STEPS = (
    "windows_directory_claim",
    "mac_to_windows_copy",
    "windows_sha256",
    "server_directory_claim",
    "windows_to_server_copy",
    "qsub_once",
)
SCOPE = {
    "assert_current_materialization": True,
    "bind_lifecycle_readiness": True,
    "create_transaction_plan": False,
    "create_effect_plan": False,
    "create_raw_effect_owner": False,
    "create_registry_entry": False,
    "invoke_adapter": False,
    "invoke_runner": False,
    "transfer": False,
    "submit": False,
    "status": False,
    "fetch": False,
    "cancel": False,
    "cleanup": False,
    "delete": False,
    "arbitrary_command": False,
}
STATUS = {
    "materialization_current": True,
    "lifecycle_readiness_bound": True,
    "effects_performed": False,
    "adapter_connected": False,
    "qsub_invocation_started": False,
    "runtime_transport_binding_complete": False,
    "live_validation_performed": False,
}
POLICY = {
    "exact_pr4l_materialization_only": True,
    "exact_pr4m_readiness_witness_only": True,
    "automatic_retry": False,
    "automatic_cancel": False,
    "automatic_cleanup": False,
    "automatic_delete": False,
    "automatic_rollback": False,
    "historical_migration": False,
    "legacy_cli_unchanged": True,
    "legacy_adapter_remains_fail_closed": True,
}
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
HANDOFF_ID_RE = re.compile(
    r"^protected-legacy-effect-handoff-[a-f0-9]{64}$"
)
MATERIALIZATION_ID_RE = re.compile(
    r"^protected-local-materialization-[a-f0-9]{64}$"
)
LIFECYCLE_ID_RE = re.compile(
    r"^protected-lifecycle-[a-f0-9]{64}$"
)
INVOCATION_ID_RE = re.compile(
    r"^protected-invocation-[a-f0-9]{64}$"
)
ATTEMPT_ID_RE = re.compile(r"^qsub-attempt-[a-f0-9]{64}$")
_MAX_PUBLIC_JSON_DEPTH = 64
_MAX_OWNER_SOURCE_BYTES = 4 * 1024 * 1024
_OWNER_READ_CHUNK_SIZE = 64 * 1024
_SEAL_TOKEN = object()
_OWNER_TOKEN = object()


class ProtectedLegacyEffectHandoffError(ValueError):
    """The non-executable typed handoff cannot be proved safely."""


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
        raise ProtectedLegacyEffectHandoffError(
            f"protected legacy handoff is not canonical JSON: {exc}"
        ) from exc
    return (encoded + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _rebuild_public_json(
    value: object,
    *,
    depth: int = 0,
    active: set[int] | None = None,
) -> object:
    if depth > _MAX_PUBLIC_JSON_DEPTH:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff exceeds the nesting bound"
        )
    value_type = type(value)
    if value_type in {str, int, bool} or value is None:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ProtectedLegacyEffectHandoffError(
                "protected legacy handoff contains a non-finite number"
            )
        return value
    if value_type not in {dict, list}:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff accepts only exact builtin JSON"
        )
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff contains a cycle"
        )
    active.add(identity)
    try:
        if value_type is list:
            return [
                _rebuild_public_json(
                    item,
                    depth=depth + 1,
                    active=active,
                )
                for item in value
            ]
        rebuilt: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ProtectedLegacyEffectHandoffError(
                    "protected legacy handoff object keys must be strings"
                )
            rebuilt[key] = _rebuild_public_json(
                item,
                depth=depth + 1,
                active=active,
            )
        return rebuilt
    except RuntimeError as exc:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff changed during rebuild"
        ) from exc
    finally:
        active.remove(identity)


def _exact(
    value: object,
    fields: set[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise ProtectedLegacyEffectHandoffError(
            f"{label} must contain exactly {sorted(fields)}"
        )
    return value


def _sha(value: object, label: str) -> str:
    if type(value) is not str or SHA_RE.fullmatch(value) is None:
        raise ProtectedLegacyEffectHandoffError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _fixed_mapping(
    value: object,
    expected: dict[str, bool],
    label: str,
) -> dict[str, Any]:
    result = _exact(value, set(expected), label)
    for field, expected_value in expected.items():
        if (
            type(result[field]) is not bool
            or result[field] is not expected_value
        ):
            raise ProtectedLegacyEffectHandoffError(
                f"{label}.{field} must be exact boolean {expected_value!r}"
            )
    return result


def _payload_sha256(document: dict[str, Any]) -> str:
    projection = {
        key: value
        for key, value in document.items()
        if key not in {"handoff_id", "handoff_payload_sha256"}
    }
    return digest(
        {
            "schema": "auto-g16-protected-legacy-effect-handoff-payload/1",
            "projection": projection,
        }
    )


def validate_protected_legacy_effect_handoff(
    value: object,
) -> dict[str, Any]:
    rebuilt = _rebuild_public_json(value)
    if type(rebuilt) is not dict:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff must be an object"
        )
    document = _exact(
        rebuilt,
        {
            "schema",
            "owner",
            "handoff_id",
            "materialization",
            "lifecycle_readiness",
            "owner_bindings",
            "scope",
            "status",
            "policy",
            "handoff_payload_sha256",
        },
        "handoff",
    )
    if document["schema"] != SCHEMA or document["owner"] != OWNER:
        raise ProtectedLegacyEffectHandoffError(
            "protected legacy handoff schema or owner differs"
        )
    if (
        type(document["handoff_id"]) is not str
        or HANDOFF_ID_RE.fullmatch(document["handoff_id"]) is None
    ):
        raise ProtectedLegacyEffectHandoffError("handoff_id is malformed")

    materialization = _exact(
        document["materialization"],
        {
            "schema",
            "materialization_id",
            "state_payload_sha256",
            "lifecycle_id",
            "invocation_id",
            "invocation_payload_sha256",
            "attempt_id",
            "consumption_sha256",
            "local_state_binding_payload_sha256",
            "stage_manifest_sha256",
        },
        "materialization",
    )
    if materialization["schema"] != MATERIALIZATION_SCHEMA:
        raise ProtectedLegacyEffectHandoffError(
            "materialization schema differs"
        )
    regex_fields = (
        ("materialization_id", MATERIALIZATION_ID_RE),
        ("lifecycle_id", LIFECYCLE_ID_RE),
        ("invocation_id", INVOCATION_ID_RE),
        ("attempt_id", ATTEMPT_ID_RE),
    )
    for field, pattern in regex_fields:
        if (
            type(materialization[field]) is not str
            or pattern.fullmatch(materialization[field]) is None
        ):
            raise ProtectedLegacyEffectHandoffError(
                f"materialization.{field} is malformed"
            )
    for field in (
        "state_payload_sha256",
        "invocation_payload_sha256",
        "consumption_sha256",
        "local_state_binding_payload_sha256",
        "stage_manifest_sha256",
    ):
        _sha(materialization[field], f"materialization.{field}")

    readiness = _exact(
        document["lifecycle_readiness"],
        {
            "schema",
            "owner",
            "lifecycle_protocol",
            "effect_steps",
            "lifecycle_guards",
            "status",
            "policy",
            "witness_payload_sha256",
        },
        "lifecycle_readiness",
    )
    if (
        readiness["schema"] != READINESS_SCHEMA
        or readiness["owner"] != LEGACY_MODULE_NAME
        or readiness["lifecycle_protocol"]
        != "bounded-terminal-retirement/1"
        or type(readiness["effect_steps"]) is not list
        or readiness["effect_steps"] != list(EFFECT_STEPS)
    ):
        raise ProtectedLegacyEffectHandoffError(
            "legacy lifecycle readiness topology differs"
        )
    _fixed_mapping(
        readiness["lifecycle_guards"],
        {
            "one_plan_one_owner": True,
            "single_active_lifecycle": True,
            "terminal_retirement": True,
            "registry_retired_on_every_terminal_exit": True,
        },
        "lifecycle_readiness.lifecycle_guards",
    )
    _fixed_mapping(
        readiness["status"],
        {
            "effect_plan_created": False,
            "raw_effect_owner_created": False,
            "registry_entry_created": False,
            "effects_performed": False,
            "runner_called": False,
            "adapter_connected": False,
        },
        "lifecycle_readiness.status",
    )
    _fixed_mapping(
        readiness["policy"],
        {
            "automatic_retry": False,
            "automatic_cancel": False,
            "automatic_cleanup": False,
            "automatic_delete": False,
        },
        "lifecycle_readiness.policy",
    )
    _sha(
        readiness["witness_payload_sha256"],
        "lifecycle_readiness.witness_payload_sha256",
    )

    bindings = _exact(
        document["owner_bindings"],
        {
            "handoff_owner_source_sha256",
            "materialization_owner_source_sha256",
            "legacy_owner_source_sha256",
        },
        "owner_bindings",
    )
    for field in bindings:
        _sha(bindings[field], f"owner_bindings.{field}")
    _fixed_mapping(document["scope"], SCOPE, "scope")
    _fixed_mapping(document["status"], STATUS, "status")
    _fixed_mapping(document["policy"], POLICY, "policy")
    _sha(document["handoff_payload_sha256"], "handoff_payload_sha256")
    expected_payload = _payload_sha256(document)
    if document["handoff_payload_sha256"] != expected_payload:
        raise ProtectedLegacyEffectHandoffError(
            "handoff payload hash differs"
        )
    expected_id = "protected-legacy-effect-handoff-" + digest(
        {
            "schema": "auto-g16-protected-legacy-effect-handoff-id/1",
            "materialization_id": materialization["materialization_id"],
            "witness_payload_sha256": readiness[
                "witness_payload_sha256"
            ],
            "handoff_payload_sha256": expected_payload,
        }
    )
    if document["handoff_id"] != expected_id:
        raise ProtectedLegacyEffectHandoffError("handoff_id differs")
    return document


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


@dataclass(frozen=True, slots=True)
class _OwnerBinding:
    module: types.ModuleType
    issued_type: type
    snapshot: _OwnerFileSnapshot


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _materialization_owner_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    path = here.with_name(f"{MATERIALIZATION_MODULE_NAME}.py")
    if path.is_symlink() or not path.is_file():
        raise ImportError(
            "exact adjacent protected local-materialization owner is unavailable"
        )
    resolved = path.resolve(strict=True)
    if resolved.parent != here.parent:
        raise ImportError(
            "protected local-materialization owner is not adjacent"
        )
    return resolved


def _handoff_owner_path() -> Path:
    path = Path(__file__).resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ImportError("protected legacy handoff owner is unavailable")
    return path


def _legacy_owner_path() -> Path:
    here = Path(__file__).resolve(strict=True)
    adjacent = here.with_name(f"{LEGACY_MODULE_NAME}.py")
    if (
        not adjacent.is_symlink()
        and adjacent.is_file()
        and adjacent.resolve(strict=True).parent == here.parent
    ):
        return adjacent.resolve(strict=True)
    repository = (
        here.parent.parent
        / "skills"
        / "auto-g16-rtwin-pbs"
        / "scripts"
        / f"{LEGACY_MODULE_NAME}.py"
    )
    if (
        not repository.is_symlink()
        and repository.is_file()
        and repository.resolve(strict=True).parent == repository.parent
    ):
        return repository.resolve(strict=True)
    raise ImportError(
        "exact legacy lifecycle owner is unavailable in repository source "
        "or deployed-package layout"
    )


def _stable_owner_snapshot(path: Path) -> _OwnerFileSnapshot:
    descriptor = -1
    try:
        before = os.stat(path, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ProtectedLegacyEffectHandoffError(
                "handoff predecessor owner must be a regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ProtectedLegacyEffectHandoffError(
                "handoff predecessor owner changed while opening"
            )
        if opened.st_size < 1 or opened.st_size > _MAX_OWNER_SOURCE_BYTES:
            raise ProtectedLegacyEffectHandoffError(
                "handoff predecessor owner size is outside the bound"
            )
        chunks = []
        while True:
            chunk = os.read(descriptor, _OWNER_READ_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        after_descriptor = os.fstat(descriptor)
        after_path = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProtectedLegacyEffectHandoffError(
            f"handoff predecessor stable read failed: {exc}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(
        {
            _stat_identity(before),
            _stat_identity(opened),
            _stat_identity(after_descriptor),
            _stat_identity(after_path),
        }
    ) != 1:
        raise ProtectedLegacyEffectHandoffError(
            "handoff predecessor owner identity drifted"
        )
    source_bytes = b"".join(chunks)
    if len(source_bytes) != opened.st_size:
        raise ProtectedLegacyEffectHandoffError(
            "handoff predecessor owner stable read was short"
        )
    return _OwnerFileSnapshot(
        canonical_path=path,
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


def _module_origin(module: types.ModuleType) -> tuple[Path, Path]:
    raw_file = getattr(module, "__file__", None)
    raw_origin = getattr(getattr(module, "__spec__", None), "origin", None)
    if (
        type(raw_file) is not str
        or not raw_file
        or type(raw_origin) is not str
        or not raw_origin
    ):
        raise ImportError("handoff predecessor owner has no exact origin")
    return Path(raw_file).resolve(), Path(raw_origin).resolve()


def _capture_binding(
    module_name: str,
    issued_type_name: str,
    path: Path,
) -> _OwnerBinding:
    snapshot = _stable_owner_snapshot(path)
    module = sys.modules.get(module_name)
    if not isinstance(module, types.ModuleType):
        raise ImportError(
            f"exact {module_name} must be loaded before the handoff owner"
        )
    if _module_origin(module) != (path, path):
        raise ImportError(f"exact {module_name} origin differs")
    issued_type = getattr(module, issued_type_name, None)
    if (
        not isinstance(issued_type, type)
        or issued_type.__module__ != module_name
        or issued_type.__qualname__ != issued_type_name
    ):
        raise ImportError(f"exact {module_name} class identity differs")
    return _OwnerBinding(
        module=module,
        issued_type=issued_type,
        snapshot=snapshot,
    )


_HANDOFF_OWNER_SNAPSHOT = _stable_owner_snapshot(_handoff_owner_path())
_MATERIALIZATION_BINDING = _capture_binding(
    MATERIALIZATION_MODULE_NAME,
    "SealedProtectedLocalMaterialization",
    _materialization_owner_path(),
)
_LEGACY_BINDING = _capture_binding(
    LEGACY_MODULE_NAME,
    "_LegacyEffectLifecycleReadinessWitness",
    _legacy_owner_path(),
)


def _assert_binding_current(
    binding: _OwnerBinding,
    *,
    path: Path,
    issued_type_name: str,
) -> None:
    if _stable_owner_snapshot(path) != binding.snapshot:
        raise ProtectedLegacyEffectHandoffError(
            "handoff predecessor owner identity differs"
        )
    if _module_origin(binding.module) != (path, path):
        raise ProtectedLegacyEffectHandoffError(
            "handoff predecessor owner origin changed"
        )
    if getattr(binding.module, issued_type_name, None) is not binding.issued_type:
        raise ProtectedLegacyEffectHandoffError(
            "handoff predecessor owner class identity changed"
        )


def _build_document(
    materialization_document: dict[str, Any],
    readiness_document: dict[str, Any],
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "owner": OWNER,
        "handoff_id": "",
        "materialization": {
            "schema": materialization_document["schema"],
            "materialization_id": materialization_document[
                "materialization_id"
            ],
            "state_payload_sha256": materialization_document[
                "state_payload_sha256"
            ],
            "lifecycle_id": materialization_document["lifecycle"][
                "lifecycle_id"
            ],
            "invocation_id": materialization_document["invocation"][
                "invocation_id"
            ],
            "invocation_payload_sha256": materialization_document[
                "invocation"
            ]["invocation_payload_sha256"],
            "attempt_id": materialization_document["reservation"][
                "attempt_id"
            ],
            "consumption_sha256": materialization_document["reservation"][
                "consumption_sha256"
            ],
            "local_state_binding_payload_sha256": materialization_document[
                "local_state"
            ]["binding_payload_sha256"],
            "stage_manifest_sha256": materialization_document["stage_plan"][
                "manifest_sha256"
            ],
        },
        "lifecycle_readiness": readiness_document,
        "owner_bindings": {
            "handoff_owner_source_sha256": (
                _HANDOFF_OWNER_SNAPSHOT.sha256
            ),
            "materialization_owner_source_sha256": (
                _MATERIALIZATION_BINDING.snapshot.sha256
            ),
            "legacy_owner_source_sha256": _LEGACY_BINDING.snapshot.sha256,
        },
        "scope": dict(SCOPE),
        "status": dict(STATUS),
        "policy": dict(POLICY),
        "handoff_payload_sha256": "",
    }
    document["handoff_payload_sha256"] = _payload_sha256(document)
    document["handoff_id"] = "protected-legacy-effect-handoff-" + digest(
        {
            "schema": "auto-g16-protected-legacy-effect-handoff-id/1",
            "materialization_id": document["materialization"][
                "materialization_id"
            ],
            "witness_payload_sha256": readiness_document[
                "witness_payload_sha256"
            ],
            "handoff_payload_sha256": document[
                "handoff_payload_sha256"
            ],
        }
    )
    return validate_protected_legacy_effect_handoff(document)


@dataclass(frozen=True, slots=True, init=False)
class SealedProtectedLegacyEffectHandoff:
    """Owner-issued, non-executable typed handoff."""

    _canonical_document: bytes
    materialization: object
    lifecycle_readiness: object
    materialization_binding: _OwnerBinding
    legacy_binding: _OwnerBinding
    handoff_id: str
    handoff_payload_sha256: str
    _seal: object

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "SealedProtectedLegacyEffectHandoff":
        raise TypeError(
            "SealedProtectedLegacyEffectHandoff is issued only by its owner"
        )

    @classmethod
    def _from_owner(
        cls,
        document: dict[str, Any],
        *,
        materialization: object,
        lifecycle_readiness: object,
        token: object,
    ) -> "SealedProtectedLegacyEffectHandoff":
        if token is not _SEAL_TOKEN:
            raise ProtectedLegacyEffectHandoffError(
                "protected legacy handoff seal differs"
            )
        value = object.__new__(cls)
        for name, item in {
            "_canonical_document": canonical_bytes(document),
            "materialization": materialization,
            "lifecycle_readiness": lifecycle_readiness,
            "materialization_binding": _MATERIALIZATION_BINDING,
            "legacy_binding": _LEGACY_BINDING,
            "handoff_id": document["handoff_id"],
            "handoff_payload_sha256": document[
                "handoff_payload_sha256"
            ],
            "_seal": _SEAL_TOKEN,
        }.items():
            object.__setattr__(value, name, item)
        return value

    def document(self) -> dict[str, Any]:
        return json.loads(self._canonical_document)

    def __copy__(self) -> "SealedProtectedLegacyEffectHandoff":
        raise TypeError("sealed protected legacy handoff is not clonable")

    def __deepcopy__(
        self,
        memo: dict[int, Any],
    ) -> "SealedProtectedLegacyEffectHandoff":
        del memo
        raise TypeError("sealed protected legacy handoff is not clonable")

    def __reduce__(self) -> object:
        raise TypeError(
            "sealed protected legacy handoff is not serializable"
        )

    def __reduce_ex__(self, protocol: int) -> object:
        del protocol
        raise TypeError(
            "sealed protected legacy handoff is not serializable"
        )

    def assert_owner_sealed(
        self,
    ) -> "SealedProtectedLegacyEffectHandoff":
        if (
            type(self) is not SealedProtectedLegacyEffectHandoff
            or self._seal is not _SEAL_TOKEN
            or type(self.materialization)
            is not self.materialization_binding.issued_type
            or type(self.lifecycle_readiness)
            is not self.legacy_binding.issued_type
        ):
            raise ProtectedLegacyEffectHandoffError(
                "protected legacy handoff owner identity differs"
            )
        self.materialization.assert_owner_sealed()
        self.lifecycle_readiness.assert_owner_sealed()
        document = validate_protected_legacy_effect_handoff(
            self.document()
        )
        if (
            document["handoff_id"] != self.handoff_id
            or document["handoff_payload_sha256"]
            != self.handoff_payload_sha256
            or canonical_bytes(document) != self._canonical_document
        ):
            raise ProtectedLegacyEffectHandoffError(
                "protected legacy handoff projection differs"
            )
        return self

    def assert_current(
        self,
    ) -> "SealedProtectedLegacyEffectHandoff":
        self.assert_owner_sealed()
        if (
            _stable_owner_snapshot(_handoff_owner_path())
            != _HANDOFF_OWNER_SNAPSHOT
        ):
            raise ProtectedLegacyEffectHandoffError(
                "protected legacy handoff owner identity differs"
            )
        _assert_binding_current(
            self.materialization_binding,
            path=_materialization_owner_path(),
            issued_type_name="SealedProtectedLocalMaterialization",
        )
        _assert_binding_current(
            self.legacy_binding,
            path=_legacy_owner_path(),
            issued_type_name="_LegacyEffectLifecycleReadinessWitness",
        )
        self.materialization.assert_current()
        self.lifecycle_readiness.assert_owner_sealed()
        return self


class ProtectedLegacyEffectHandoffOwner:
    """One-shot owner for the non-executable readiness handoff."""

    def __init__(self, *, _factory_token: object) -> None:
        if _factory_token is not _OWNER_TOKEN:
            raise TypeError(
                "ProtectedLegacyEffectHandoffOwner requires a fixed factory"
            )
        self._lock = threading.Lock()
        self._sealed = False

    @classmethod
    def production(cls) -> "ProtectedLegacyEffectHandoffOwner":
        return cls(_factory_token=_OWNER_TOKEN)

    def seal(
        self,
        materialization: object,
    ) -> SealedProtectedLegacyEffectHandoff:
        with self._lock:
            if self._sealed:
                raise ProtectedLegacyEffectHandoffError(
                    "protected legacy handoff owner is single-use"
                )
            self._sealed = True
            if type(materialization) is not _MATERIALIZATION_BINDING.issued_type:
                raise TypeError(
                    "handoff accepts only the exact bound PR4L materialization"
                )
            _assert_binding_current(
                _MATERIALIZATION_BINDING,
                path=_materialization_owner_path(),
                issued_type_name="SealedProtectedLocalMaterialization",
            )
            _assert_binding_current(
                _LEGACY_BINDING,
                path=_legacy_owner_path(),
                issued_type_name="_LegacyEffectLifecycleReadinessWitness",
            )
            materialization.assert_current()
            issuer = getattr(
                _LEGACY_BINDING.module,
                "_issue_legacy_effect_lifecycle_readiness_witness",
                None,
            )
            if not isinstance(issuer, types.FunctionType):
                raise ProtectedLegacyEffectHandoffError(
                    "legacy lifecycle readiness issuer identity differs"
                )
            readiness = issuer()
            if type(readiness) is not _LEGACY_BINDING.issued_type:
                raise ProtectedLegacyEffectHandoffError(
                    "legacy lifecycle readiness class identity differs"
                )
            readiness.assert_owner_sealed()
            document = _build_document(
                materialization.document(),
                readiness.document(),
            )
            sealed = SealedProtectedLegacyEffectHandoff._from_owner(
                document,
                materialization=materialization,
                lifecycle_readiness=readiness,
                token=_SEAL_TOKEN,
            )
            sealed.assert_current()
            return sealed
