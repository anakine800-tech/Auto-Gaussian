"""Private exact-byte xTB preoptimization to CREST seed authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.transport import program as _transport
from auto_g16.transport._canonical import TransportBoundaryError

from ._identity import (
    ExecutionValueError,
    freeze_mapping,
    require_positive_integer,
    require_sha256,
    require_text,
    semantic_id,
    semantic_sha256,
)
from .program import ProgramExecutionSnapshot, ProgramExecutionSpec
from .program_runtime import _assert_program_output_capture_authority


_HANDOFF_SCHEMA = "v31-xtb-crest-seed-handoff/1"
_XTB_GEOMETRY_ROLE = "optimized-geometry"
_XTB_GEOMETRY_NAME = "xtbopt.xyz"
_XTB_GEOMETRY_FORMAT = "xyz"
_CREST_SEED_NAME = "seed.xyz"
_HANDOFF_PAYLOAD_FIELDS = {
    "schema",
    "xtb_program_execution_snapshot_id",
    "xtb_effect_intent_id",
    "xtb_program_execution_spec_id",
    "xtb_program_execution_spec_payload_sha256",
    "xtb_output_capture_authority_id",
    "xtb_job_authority_id",
    "xtb_project_physical_binding_id",
    "xtb_project_id",
    "optimized_geometry_logical_role",
    "optimized_geometry_portable_name",
    "optimized_geometry_format",
    "optimized_geometry_sha256",
    "optimized_geometry_size_bytes",
    "crest_program_execution_spec_id",
    "crest_program_execution_spec_payload_sha256",
    "crest_exact_input_name",
    "crest_exact_input_sha256",
    "crest_exact_input_size_bytes",
    "sampling_profile_id",
    "sampling_profile_payload_sha256",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExecutionValueError(message)


def _nonnegative_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionValueError(f"{label} must be a non-negative integer")
    return value


def _profile_identity(profile: object) -> tuple[str, str, Mapping[str, object]]:
    # Delayed to preserve the existing execution/conformer import direction.
    from auto_g16.conformer.models import SamplingProfile, _payload_sha256

    _require(type(profile) is SamplingProfile, "profile must be an exact SamplingProfile")
    payload = profile._identity_payload()
    payload_sha256 = _payload_sha256(payload)
    profile_id = (
        "sampling-profile-"
        + _payload_sha256({"domain": "sampling-profile", "payload": payload})
    )
    _require(
        profile.sampling_profile_id == profile_id
        and profile.payload_sha256 == payload_sha256,
        "SamplingProfile identity is stale",
    )
    return profile_id, payload_sha256, payload


def _capture_identity_payload(
    capture: _transport._ProgramOutputCapture,
) -> Mapping[str, object]:
    _require(
        type(capture) is _transport._ProgramOutputCapture,
        "xTB output capture must be the exact private capture type",
    )
    require_text(capture.capture_authority_id, "capture authority ID")
    require_text(capture.program_execution_snapshot_id, "capture snapshot ID")
    require_text(capture.effect_intent_id, "capture effect intent ID")
    require_text(capture.job_authority_id, "capture job authority ID")
    _require(type(capture.artifacts) is tuple, "capture artifacts must be an exact tuple")
    for index, artifact in enumerate(capture.artifacts):
        label = f"capture artifacts[{index}]"
        _require(
            type(artifact) is _transport._ProgramOutputArtifact,
            f"{label} must be an exact captured artifact",
        )
        for name in (
            "logical_role",
            "portable_name",
            "format",
            "program_execution_snapshot_id",
            "effect_intent_id",
            "job_authority_id",
        ):
            require_text(getattr(artifact, name), f"{label}.{name}")
        _require(
            artifact.presence in {"present", "absent"},
            f"{label}.presence is outside the closed set",
        )
        if artifact.presence == "present":
            require_sha256(artifact.sha256, f"{label}.sha256")
            size = _nonnegative_integer(artifact.size_bytes, f"{label}.size_bytes")
            require_text(artifact.fetch_receipt_id, f"{label}.fetch_receipt_id")
            _require(type(artifact.content) is bytes, f"{label}.content must be exact bytes")
            assert isinstance(artifact.content, bytes)
            _require(
                len(artifact.content) == size
                and sha256(artifact.content).hexdigest() == artifact.sha256,
                f"{label} content differs from its exact capture authority",
            )
        else:
            _require(
                artifact.sha256 is None
                and artifact.size_bytes is None
                and artifact.fetch_receipt_id is None
                and artifact.content is None,
                f"{label} absent state must contain no artifact authority",
            )
    return {
        "program_execution_snapshot_id": capture.program_execution_snapshot_id,
        "effect_intent_id": capture.effect_intent_id,
        "job_authority_id": capture.job_authority_id,
        "artifacts": tuple(item.identity_payload() for item in capture.artifacts),
    }


def _close_capture_to_snapshot(
    snapshot: ProgramExecutionSnapshot,
    capture: _transport._ProgramOutputCapture,
) -> _transport._ProgramOutputArtifact:
    _require(type(snapshot) is ProgramExecutionSnapshot, "xTB snapshot must be exact")
    snapshot.assert_identity_closed()
    spec = snapshot.program_execution_spec
    _require(
        spec.program_kind == "xtb"
        and spec.adapter_id == "auto-g16-v31-xtb"
        and spec.adapter_contract_version == 1
        and spec.program_data["task"] == "optimize",
        "source must be the exact xTB optimize successor",
    )
    capture_payload = _capture_identity_payload(capture)
    _require(
        capture.capture_authority_id
        == _transport._identity("output-capture", capture_payload),
        "xTB output capture authority identity is stale",
    )
    _require(
        capture.program_execution_snapshot_id
        == snapshot.program_execution_snapshot_id
        and capture.effect_intent_id == snapshot.effect_intent_id,
        "xTB output capture differs from the exact execution snapshot",
    )
    declarations = (*spec.required_outputs, *spec.optional_outputs)
    _require(
        tuple(
            (item.logical_role, item.portable_name, item.format)
            for item in capture.artifacts
        )
        == tuple(
            (str(item["logical_role"]), str(item["portable_name"]), str(item["format"]))
            for item in declarations
        ),
        "xTB output capture does not exactly cover the declared output sequence",
    )
    for artifact, declaration in zip(capture.artifacts, declarations):
        _require(
            artifact.program_execution_snapshot_id
            == snapshot.program_execution_snapshot_id
            and artifact.effect_intent_id == snapshot.effect_intent_id
            and artifact.job_authority_id == capture.job_authority_id,
            "captured xTB artifact differs from snapshot or job authority",
        )
        if declaration in spec.required_outputs:
            _require(
                artifact.presence == "present",
                "required xTB output artifact must be present",
            )
        if artifact.presence == "present":
            _require(
                artifact.size_bytes <= declaration["max_size_bytes"],
                "captured xTB artifact exceeds its exact declared size limit",
            )
    geometry_declarations = tuple(
        item
        for item in spec.required_outputs
        if item["logical_role"] == _XTB_GEOMETRY_ROLE
    )
    _require(
        len(geometry_declarations) == 1
        and geometry_declarations[0]["portable_name"] == _XTB_GEOMETRY_NAME
        and geometry_declarations[0]["format"] == _XTB_GEOMETRY_FORMAT
        and geometry_declarations[0]["cardinality"] == "exactly-one"
        and geometry_declarations[0]["capture_policy"] == "exact-file"
        and geometry_declarations[0]["completeness"] == "program-success",
        "xTB optimize spec must require exact xtbopt.xyz geometry",
    )
    geometry = tuple(
        item
        for item in capture.artifacts
        if item.logical_role == _XTB_GEOMETRY_ROLE
    )
    _require(len(geometry) == 1, "xTB capture must contain exactly one optimized geometry")
    artifact = geometry[0]
    _require(
        artifact.portable_name == _XTB_GEOMETRY_NAME
        and artifact.format == _XTB_GEOMETRY_FORMAT
        and artifact.presence == "present",
        "xTB optimized geometry artifact differs from exact xtbopt.xyz authority",
    )
    _require(
        type(artifact.content) is bytes and bool(artifact.content),
        "xTB optimized geometry must retain non-empty exact bytes",
    )
    return artifact


@dataclass(frozen=True, slots=True, kw_only=True, init=False)
class _XtbCrestSeedHandoff:
    """One private immutable authority for exact xtbopt.xyz -> seed.xyz bytes."""

    schema: str
    handoff_authority_id: str
    payload_sha256: str
    xtb_program_execution_snapshot_id: str
    xtb_effect_intent_id: str
    xtb_program_execution_spec_id: str
    xtb_program_execution_spec_payload_sha256: str
    xtb_output_capture_authority_id: str
    xtb_job_authority_id: str
    xtb_project_physical_binding_id: str
    xtb_project_id: str
    optimized_geometry_logical_role: str
    optimized_geometry_portable_name: str
    optimized_geometry_format: str
    optimized_geometry_sha256: str
    optimized_geometry_size_bytes: int
    crest_program_execution_spec_id: str
    crest_program_execution_spec_payload_sha256: str
    crest_exact_input_name: str
    crest_exact_input_sha256: str
    crest_exact_input_size_bytes: int
    sampling_profile_id: str
    sampling_profile_payload_sha256: str
    _identity_payload: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError("xTB to CREST seed handoff is service-created")

    def assert_identity_closed(self) -> None:
        _require(
            set(self._identity_payload) == _HANDOFF_PAYLOAD_FIELDS,
            "xTB to CREST handoff payload has an invalid closed field set",
        )
        for name in _HANDOFF_PAYLOAD_FIELDS:
            _require(
                getattr(self, name) == self._identity_payload[name],
                "xTB to CREST handoff fields differ from its identity payload",
            )
        _require(self.schema == _HANDOFF_SCHEMA, "xTB to CREST handoff schema is invalid")
        for name in (
            "handoff_authority_id",
            "xtb_program_execution_snapshot_id",
            "xtb_effect_intent_id",
            "xtb_program_execution_spec_id",
            "xtb_output_capture_authority_id",
            "xtb_job_authority_id",
            "xtb_project_physical_binding_id",
            "xtb_project_id",
            "crest_program_execution_spec_id",
            "sampling_profile_id",
        ):
            require_text(getattr(self, name), name)
        for name in (
            "payload_sha256",
            "xtb_program_execution_spec_payload_sha256",
            "optimized_geometry_sha256",
            "crest_program_execution_spec_payload_sha256",
            "crest_exact_input_sha256",
            "sampling_profile_payload_sha256",
        ):
            require_sha256(getattr(self, name), name)
        _require(
            self.optimized_geometry_logical_role == _XTB_GEOMETRY_ROLE
            and self.optimized_geometry_portable_name == _XTB_GEOMETRY_NAME
            and self.optimized_geometry_format == _XTB_GEOMETRY_FORMAT
            and self.crest_exact_input_name == _CREST_SEED_NAME,
            "xTB to CREST handoff artifact names or formats are invalid",
        )
        require_positive_integer(
            self.optimized_geometry_size_bytes,
            "optimized geometry size",
        )
        require_positive_integer(self.crest_exact_input_size_bytes, "CREST exact input size")
        require_sha256(self.optimized_geometry_sha256, "optimized geometry SHA-256")
        require_sha256(self.crest_exact_input_sha256, "CREST exact input SHA-256")
        _require(
            self.optimized_geometry_sha256 == self.crest_exact_input_sha256
            and self.optimized_geometry_size_bytes == self.crest_exact_input_size_bytes,
            "xTB geometry and CREST seed identities differ",
        )
        _require(
            self.handoff_authority_id
            == semantic_id("xtb-crest-seed-handoff", self._identity_payload)
            and self.payload_sha256 == semantic_sha256(self._identity_payload),
            "xTB to CREST handoff identity is stale",
        )


def _build_xtb_crest_seed_handoff(
    *,
    core_store: SQLiteRuntimeStore,
    xtb_program_execution_snapshot: ProgramExecutionSnapshot,
    xtb_program_transport_store: _transport._ProgramTransportStore,
    xtb_validation_driver: _transport._ProgramEffectDriver,
    xtb_output_capture: _transport._ProgramOutputCapture,
    crest_program_execution_spec: ProgramExecutionSpec,
    crest_exact_input_bytes: bytes,
    sampling_profile: object,
) -> _XtbCrestSeedHandoff:
    """Close exact captured xTB geometry bytes to one CREST v2 seed input."""

    try:
        _assert_program_output_capture_authority(
            core_store,
            snapshot=xtb_program_execution_snapshot,
            program_transport_store=xtb_program_transport_store,
            driver=xtb_validation_driver,
            capture=xtb_output_capture,
        )
    except TransportBoundaryError as exc:
        raise ExecutionValueError(
            f"xTB output capture lacks runtime authority: {exc}"
        ) from exc
    geometry = _close_capture_to_snapshot(
        xtb_program_execution_snapshot,
        xtb_output_capture,
    )
    _require(
        type(crest_program_execution_spec) is ProgramExecutionSpec,
        "CREST spec must be exact",
    )
    crest_program_execution_spec.assert_identity_closed()
    _require(
        crest_program_execution_spec.program_kind == "crest"
        and crest_program_execution_spec.adapter_id == "auto-g16-v31-crest"
        and crest_program_execution_spec.adapter_contract_version == 2,
        "destination must be the exact CREST iMTD-GC v2 successor",
    )
    _require(
        type(crest_exact_input_bytes) is bytes and bool(crest_exact_input_bytes),
        "CREST exact input must be non-empty immutable bytes",
    )
    _require(
        len(crest_program_execution_spec.exact_inputs) == 1,
        "CREST spec must contain exactly one seed input",
    )
    crest_input = crest_program_execution_spec.exact_inputs[0]
    crest_input_sha256 = sha256(crest_exact_input_bytes).hexdigest()
    _require(
        crest_input["logical_role"] == "structure"
        and crest_input["portable_name"] == _CREST_SEED_NAME
        and crest_input["format"] == "xyz"
        and crest_input["sha256"] == crest_input_sha256
        and crest_input["size_bytes"] == len(crest_exact_input_bytes),
        "CREST exact seed bytes differ from its ProgramExecutionSpec",
    )
    _require(
        crest_exact_input_bytes == geometry.content,
        "CREST seed bytes differ from captured xTB optimized geometry",
    )

    profile_id, profile_sha256, profile_payload = _profile_identity(sampling_profile)
    from auto_g16.conformer.service import _assert_crest_program_execution_alignment

    try:
        _assert_crest_program_execution_alignment(
            sampling_profile,
            crest_program_execution_spec,
        )
    except ValueError as exc:
        raise ExecutionValueError(
            f"CREST specification differs from SamplingProfile: {exc}"
        ) from exc
    species = profile_payload["species_binding"]
    assert isinstance(species, Mapping)
    xtb_data = xtb_program_execution_snapshot.program_execution_spec.program_data
    crest_data = crest_program_execution_spec.program_data
    controls = profile_payload["crest_imtd_gc_profile"]
    assert isinstance(controls, Mapping)
    controls = controls["imtd_gc_controls"]
    assert isinstance(controls, Mapping)
    _require(
        xtb_data["charge"] == crest_data["charge"] == species["formal_charge"],
        "xTB, CREST, and SamplingProfile charge must agree",
    )
    _require(
        xtb_data["unpaired_electrons"]
        == crest_data["unpaired_electrons"]
        == controls["unpaired_electrons"]
        == 0
        and species["multiplicity"] == 1
        and species["electronic_state_family"] == "reviewed_closed_shell_singlet",
        "preoptimized CREST handoff requires the reviewed closed-shell singlet state",
    )
    _require(
        xtb_data["model"] == crest_data["model"] == controls["model"],
        "xTB, CREST, and SamplingProfile GFN model must agree",
    )
    assert geometry.sha256 is not None and geometry.size_bytes is not None
    xtb_spec = xtb_program_execution_snapshot.program_execution_spec
    payload = freeze_mapping(
        {
            "schema": _HANDOFF_SCHEMA,
            "xtb_program_execution_snapshot_id": (
                xtb_program_execution_snapshot.program_execution_snapshot_id
            ),
            "xtb_effect_intent_id": xtb_program_execution_snapshot.effect_intent_id,
            "xtb_program_execution_spec_id": xtb_spec.program_execution_spec_id,
            "xtb_program_execution_spec_payload_sha256": semantic_sha256(
                xtb_spec.semantic_payload()
            ),
            "xtb_output_capture_authority_id": xtb_output_capture.capture_authority_id,
            "xtb_job_authority_id": xtb_output_capture.job_authority_id,
            "xtb_project_physical_binding_id": (
                xtb_program_execution_snapshot.project_physical_binding_id
            ),
            "xtb_project_id": (
                xtb_program_execution_snapshot.project_physical_binding.project_id
            ),
            "optimized_geometry_logical_role": geometry.logical_role,
            "optimized_geometry_portable_name": geometry.portable_name,
            "optimized_geometry_format": geometry.format,
            "optimized_geometry_sha256": geometry.sha256,
            "optimized_geometry_size_bytes": geometry.size_bytes,
            "crest_program_execution_spec_id": (
                crest_program_execution_spec.program_execution_spec_id
            ),
            "crest_program_execution_spec_payload_sha256": semantic_sha256(
                crest_program_execution_spec.semantic_payload()
            ),
            "crest_exact_input_name": str(crest_input["portable_name"]),
            "crest_exact_input_sha256": crest_input_sha256,
            "crest_exact_input_size_bytes": len(crest_exact_input_bytes),
            "sampling_profile_id": profile_id,
            "sampling_profile_payload_sha256": profile_sha256,
        },
        "xTB to CREST seed handoff payload",
    )
    value = object.__new__(_XtbCrestSeedHandoff)
    for name, item in payload.items():
        object.__setattr__(value, name, item)
    object.__setattr__(value, "_identity_payload", payload)
    object.__setattr__(
        value,
        "handoff_authority_id",
        semantic_id("xtb-crest-seed-handoff", payload),
    )
    object.__setattr__(value, "payload_sha256", semantic_sha256(payload))
    value.assert_identity_closed()
    return value


def _assert_xtb_crest_seed_handoff_destination(
    handoff: _XtbCrestSeedHandoff,
    *,
    sampling_profile: object,
    crest_program_execution_spec: ProgramExecutionSpec,
    crest_program_execution_snapshot: ProgramExecutionSnapshot | None = None,
    xtb_core_store: SQLiteRuntimeStore | None = None,
    xtb_program_execution_snapshot: ProgramExecutionSnapshot | None = None,
    xtb_program_transport_store: _transport._ProgramTransportStore | None = None,
    xtb_validation_driver: _transport._ProgramEffectDriver | None = None,
    xtb_output_capture: _transport._ProgramOutputCapture | None = None,
) -> None:
    """Reclose a handoff to the exact current profile, CREST spec, and Project."""

    _require(type(handoff) is _XtbCrestSeedHandoff, "handoff must be exact")
    handoff.assert_identity_closed()
    profile_id, profile_sha256, _payload = _profile_identity(sampling_profile)
    crest_program_execution_spec.assert_identity_closed()
    try:
        from auto_g16.conformer.service import _assert_crest_program_execution_alignment

        _assert_crest_program_execution_alignment(
            sampling_profile,
            crest_program_execution_spec,
        )
    except ValueError as exc:
        raise ExecutionValueError(
            f"CREST specification differs from SamplingProfile: {exc}"
        ) from exc
    _require(
        handoff.sampling_profile_id == profile_id
        and handoff.sampling_profile_payload_sha256 == profile_sha256,
        "handoff binds a different SamplingProfile",
    )
    _require(
        handoff.crest_program_execution_spec_id
        == crest_program_execution_spec.program_execution_spec_id
        and handoff.crest_program_execution_spec_payload_sha256
        == semantic_sha256(crest_program_execution_spec.semantic_payload()),
        "handoff binds a different CREST ProgramExecutionSpec",
    )
    crest_input = crest_program_execution_spec.exact_inputs[0]
    _require(
        handoff.crest_exact_input_name == crest_input["portable_name"]
        and handoff.crest_exact_input_sha256 == crest_input["sha256"]
        and handoff.crest_exact_input_size_bytes == crest_input["size_bytes"],
        "handoff differs from the exact CREST seed input",
    )
    runtime_context = (
        xtb_core_store,
        xtb_program_execution_snapshot,
        xtb_program_transport_store,
        xtb_validation_driver,
        xtb_output_capture,
    )
    if any(item is not None for item in runtime_context):
        _require(
            all(item is not None for item in runtime_context),
            "runtime-backed handoff validation context is incomplete",
        )
        assert xtb_core_store is not None
        assert xtb_program_execution_snapshot is not None
        assert xtb_program_transport_store is not None
        assert xtb_validation_driver is not None
        assert xtb_output_capture is not None
        try:
            _assert_program_output_capture_authority(
                xtb_core_store,
                snapshot=xtb_program_execution_snapshot,
                program_transport_store=xtb_program_transport_store,
                driver=xtb_validation_driver,
                capture=xtb_output_capture,
            )
        except TransportBoundaryError as exc:
            raise ExecutionValueError(
                f"xTB output capture lacks runtime authority: {exc}"
            ) from exc
        geometry = _close_capture_to_snapshot(
            xtb_program_execution_snapshot,
            xtb_output_capture,
        )
        xtb_spec = xtb_program_execution_snapshot.program_execution_spec
        _require(
            handoff.xtb_program_execution_snapshot_id
            == xtb_program_execution_snapshot.program_execution_snapshot_id
            and handoff.xtb_effect_intent_id
            == xtb_program_execution_snapshot.effect_intent_id
            and handoff.xtb_program_execution_spec_id
            == xtb_spec.program_execution_spec_id
            and handoff.xtb_program_execution_spec_payload_sha256
            == semantic_sha256(xtb_spec.semantic_payload())
            and handoff.xtb_output_capture_authority_id
            == xtb_output_capture.capture_authority_id
            and handoff.xtb_job_authority_id
            == xtb_output_capture.job_authority_id
            and handoff.xtb_project_physical_binding_id
            == xtb_program_execution_snapshot.project_physical_binding_id
            and handoff.xtb_project_id
            == xtb_program_execution_snapshot.project_physical_binding.project_id
            and handoff.optimized_geometry_logical_role == geometry.logical_role
            and handoff.optimized_geometry_portable_name == geometry.portable_name
            and handoff.optimized_geometry_format == geometry.format
            and handoff.optimized_geometry_sha256 == geometry.sha256
            and handoff.optimized_geometry_size_bytes == geometry.size_bytes,
            "handoff source differs from runtime-attested xTB capture",
        )
    if crest_program_execution_snapshot is not None:
        _require(
            type(crest_program_execution_snapshot) is ProgramExecutionSnapshot,
            "CREST snapshot must be exact",
        )
        crest_program_execution_snapshot.assert_identity_closed()
        _require(
            crest_program_execution_snapshot.program_execution_spec_id
            == crest_program_execution_spec.program_execution_spec_id,
            "CREST snapshot binds a different ProgramExecutionSpec",
        )
        _require(
            handoff.xtb_project_id
            == crest_program_execution_snapshot.project_physical_binding.project_id
            and handoff.xtb_project_physical_binding_id
            == crest_program_execution_snapshot.project_physical_binding_id,
            "xTB and CREST snapshots belong to different Project authority",
        )


__all__: tuple[str, ...] = ()
