"""Private validation of bytes and artifact declarations in frozen snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from auto_g16.transport import program as _transport
from auto_g16.transport._canonical import TransportBoundaryError

from .program import ProgramExecutionSnapshot, _uses_completion_receipt
from . import _program_completion as _completion


def _stage_material(
    snapshot: ProgramExecutionSnapshot,
    *,
    input_bytes: Mapping[str, bytes],
    scheduler_artifact_bytes: Mapping[str, bytes],
) -> tuple[tuple[dict[str, object], bytes], ...]:
    if not isinstance(input_bytes, Mapping) or not isinstance(scheduler_artifact_bytes, Mapping):
        raise TransportBoundaryError("successor stage bytes must be exact mappings")
    inputs = snapshot.program_execution_spec.exact_inputs
    schedulers = snapshot.scheduler_artifacts
    input_names = tuple(str(item["portable_name"]) for item in inputs)
    scheduler_names = tuple(str(item["portable_name"]) for item in schedulers)
    if set(input_bytes) != set(input_names) or len(input_bytes) != len(input_names):
        raise TransportBoundaryError("program input bytes differ from exact declarations")
    if set(scheduler_artifact_bytes) != set(scheduler_names) or len(scheduler_artifact_bytes) != len(scheduler_names):
        raise TransportBoundaryError("scheduler bytes differ from exact declarations")
    material: list[tuple[dict[str, object], bytes]] = []
    for declaration in inputs:
        name = _transport._portable(declaration["portable_name"], "program input name")
        content = input_bytes[name]
        if type(content) is not bytes or len(content) != declaration["size_bytes"] or sha256(content).hexdigest() != declaration["sha256"]:
            raise TransportBoundaryError("program input bytes differ from exact declaration")
        material.append(({
            "artifact_kind": "program-input",
            "logical_role": declaration["logical_role"],
            "portable_name": name,
            "format": declaration["format"],
            "sha256": declaration["sha256"],
            "size_bytes": declaration["size_bytes"],
        }, content))
    for declaration in schedulers:
        name = _transport._portable(declaration["portable_name"], "scheduler artifact name")
        content = scheduler_artifact_bytes[name]
        expected = str(declaration["content_utf8"]).encode("utf-8")
        if type(content) is not bytes or content != expected or len(content) != declaration["size_bytes"] or sha256(content).hexdigest() != declaration["sha256"]:
            raise TransportBoundaryError("scheduler bytes differ from exact snapshot artifact")
        material.append(({
            "artifact_kind": declaration["logical_role"],
            "logical_role": declaration["logical_role"],
            "portable_name": name,
            "format": declaration["format"],
            "sha256": declaration["sha256"],
            "size_bytes": declaration["size_bytes"],
        }, content))
    material.extend((*_completion._gstartup._derived_artifacts(snapshot), *_completion._gfile._derived_artifacts(snapshot)))
    return tuple(material)


def _declared_stage_payload(
    snapshot: ProgramExecutionSnapshot,
    candidate: Mapping[str, object],
) -> dict[str, object]:
    declared = tuple(
        {
            "artifact_kind": "program-input",
            "logical_role": item["logical_role"],
            "portable_name": item["portable_name"],
            "format": item["format"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in snapshot.program_execution_spec.exact_inputs
    ) + tuple(
        {
            "artifact_kind": item["logical_role"],
            "logical_role": item["logical_role"],
            "portable_name": item["portable_name"],
            "format": item["format"],
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for item in snapshot.scheduler_artifacts
    )
    declared += tuple(item for item, _ in (*_completion._gstartup._derived_artifacts(snapshot), *_completion._gfile._derived_artifacts(snapshot)))
    matched = tuple(item for item in declared if item == dict(candidate))
    if len(matched) != 1:
        raise TransportBoundaryError(
            "persisted staged artifact is not uniquely snapshot-declared"
        )
    return matched[0]


def _declared_output(
    snapshot: ProgramExecutionSnapshot,
    candidate: Mapping[str, object],
) -> Mapping[str, object]:
    declarations = (
        *snapshot.program_execution_spec.required_outputs,
        *snapshot.program_execution_spec.optional_outputs,
    )
    if _uses_completion_receipt(snapshot.program_execution_spec):
        declarations += (_completion._METADATA_DECLARATION,)
    matched = tuple(
        item
        for item in declarations
        if all(
            candidate.get(key) == item[key]
            for key in ("logical_role", "portable_name", "format")
        )
    )
    if len(matched) != 1:
        raise TransportBoundaryError(
            "persisted output request is not uniquely spec-declared"
        )
    return matched[0]
