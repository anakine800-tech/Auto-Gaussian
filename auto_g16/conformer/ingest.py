"""Private, offline CREST 3.0.2 conformer-output ingestion."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re

from auto_g16.core import SQLiteRuntimeStore
from auto_g16.execution import ExecutionValueError
from auto_g16.execution._identity import semantic_id, semantic_sha256
from auto_g16.execution.program import ProgramExecutionSnapshot, ProgramExecutionSpec
from auto_g16.execution.xtb_crest_handoff import (
    _XtbCrestSeedHandoff,
    _assert_xtb_crest_seed_handoff_destination,
)
from auto_g16.transport import program as _transport

from .models import ConformerError, SamplingProfile, _freeze, _payload_sha256
from .service import _assert_crest_program_execution_alignment


_CREST_OUTPUT_ROLE = "conformer-ensemble"
_CREST_OUTPUT_NAME = "crest_conformers.xyz"
_CREST_OUTPUT_FORMAT = "xyz-trajectory"
# Qualified from CREST tag v3.0.2 (af7eb992): cregen_conffile writes the
# absolute energy as (2x,f18.8), while CREGEN uses this exact conversion for
# relative conformer energies.  This adapter accepts no alternate grammar or
# conversion constant.
_CREST_HARTREE_TO_KCAL_PER_MOL = Decimal("627.509541")
_ENERGY = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{8}")
_COORDINATE = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{10}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CREST_SAMPLING_PLAN_V1_SCHEMA = "v31-crest-sampling-plan/1"
_CREST_SAMPLING_PLAN_V1_FIELDS = {
    "schema",
    "sampling_profile_id",
    "sampling_profile_payload_sha256",
    "program_execution_spec_id",
    "program_execution_spec_payload_sha256",
}
_CREST_SAMPLING_PLAN_V2_SCHEMA = "v31-crest-sampling-plan/2"
_CREST_SAMPLING_PLAN_V2_FIELDS = {
    *_CREST_SAMPLING_PLAN_V1_FIELDS,
    "preoptimization_handoff_authority_id",
    "preoptimization_handoff_payload_sha256",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class _CrestOutputArtifactBinding:
    """Private exact-byte receipt for one declared CREST ensemble output."""

    program_execution_snapshot_id: str
    effect_intent_id: str
    program_execution_spec_id: str
    logical_role: str
    portable_name: str
    format: str
    sha256: str
    size_bytes: int

    def assert_closed(self) -> None:
        for name in (
            "program_execution_snapshot_id",
            "effect_intent_id",
            "program_execution_spec_id",
            "logical_role",
            "portable_name",
            "format",
        ):
            _canonical_text(getattr(self, name), name)
        _require(
            isinstance(self.sha256, str) and _SHA256.fullmatch(self.sha256) is not None,
            "artifact binding sha256 must be a lowercase SHA-256 digest",
        )
        _require(
            type(self.size_bytes) is int and self.size_bytes > 0,
            "artifact binding size_bytes must be a positive integer",
        )

    def semantic_payload(self) -> Mapping[str, object]:
        self.assert_closed()
        return {
            "program_execution_snapshot_id": self.program_execution_snapshot_id,
            "effect_intent_id": self.effect_intent_id,
            "program_execution_spec_id": self.program_execution_spec_id,
            "logical_role": self.logical_role,
            "portable_name": self.portable_name,
            "format": self.format,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConformerError(message)


def _canonical_text(value: object, label: str) -> str:
    _require(
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "\x00" not in value
        and "\n" not in value
        and "\r" not in value,
        f"{label} must be a non-empty canonical string",
    )
    assert isinstance(value, str)
    return value


def _fixed_decimal(field: str, *, width: int, grammar: re.Pattern[str], label: str) -> Decimal:
    _require(len(field) == width and "\t" not in field, f"{label} has invalid fixed width")
    token = field.lstrip(" ")
    _require(token and field == token.rjust(width) and grammar.fullmatch(token) is not None, f"{label} has invalid CREST numeric grammar")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:  # defensive; the closed grammar should make this unreachable
        raise ConformerError(f"{label} is not decimal") from exc
    _require(value.is_finite(), f"{label} must be finite")
    return value


def _closed_index_mapping(
    value: object,
    *,
    member_count: int,
    label: str,
) -> Mapping[int, object]:
    if value is None:
        return {}
    _require(isinstance(value, Mapping), f"{label} must be a mapping or None")
    assert isinstance(value, Mapping)
    for key in value:
        _require(type(key) is int and 0 <= key < member_count, f"{label} contains an invalid member index")
    return value


def _exact_output_declaration(spec: ProgramExecutionSpec) -> Mapping[str, object]:
    matches = tuple(
        item
        for item in spec.required_outputs
        if item["logical_role"] == _CREST_OUTPUT_ROLE
    )
    _require(len(matches) == 1, "CREST spec must require exactly one conformer ensemble output")
    declaration = matches[0]
    _require(
        declaration["portable_name"] == _CREST_OUTPUT_NAME
        and declaration["format"] == _CREST_OUTPUT_FORMAT
        and declaration["cardinality"] == "exactly-one"
        and declaration["capture_policy"] == "exact-file"
        and declaration["completeness"] == "program-success",
        "CREST conformer output declaration differs from the frozen adapter",
    )
    return declaration


def _close_sampling_authority(
    *,
    profile: SamplingProfile,
    snapshot: ProgramExecutionSnapshot,
    core_store: SQLiteRuntimeStore,
    preoptimization_handoff: _XtbCrestSeedHandoff | None,
    xtb_program_execution_snapshot: ProgramExecutionSnapshot | None = None,
    xtb_program_transport_store: _transport._ProgramTransportStore | None = None,
    xtb_validation_driver: _transport._ProgramEffectDriver | None = None,
    xtb_output_capture: _transport._ProgramOutputCapture | None = None,
) -> tuple[ProgramExecutionSpec, Mapping[str, object]]:
    _require(type(profile) is SamplingProfile, "profile must be an exact SamplingProfile")
    _require(
        type(snapshot) is ProgramExecutionSnapshot,
        "program_execution_snapshot must be exact",
    )
    _require(type(core_store) is SQLiteRuntimeStore, "core_store must be the exact Core store")

    profile_payload = profile._identity_payload()
    profile_payload_sha256 = _payload_sha256(profile_payload)
    profile_id = (
        "sampling-profile-"
        + _payload_sha256({"domain": "sampling-profile", "payload": profile_payload})
    )
    _require(
        profile.payload_sha256 == profile_payload_sha256
        and profile.sampling_profile_id == profile_id,
        "SamplingProfile identity is stale",
    )
    try:
        snapshot.assert_identity_closed()
    except ExecutionValueError as exc:
        raise ConformerError(f"ProgramExecutionSnapshot is not identity-closed: {exc}") from exc
    spec = snapshot.program_execution_spec
    _require(
        spec.program_kind == "crest"
        and spec.adapter_id == "auto-g16-v31-crest"
        and spec.adapter_contract_version == 2,
        "snapshot must use the exact CREST iMTD-GC v2 adapter",
    )
    spec_payload_sha256 = semantic_sha256(spec.semantic_payload())
    _require(
        snapshot.program_execution_spec_id == spec.program_execution_spec_id
        and snapshot.program_execution_spec_payload_sha256 == spec_payload_sha256,
        "snapshot ProgramExecutionSpec linkage is stale",
    )

    plan = core_store.load_calculation_plan(snapshot.calculation_plan_id)
    _require(
        plan.revision == snapshot.calculation_plan_revision,
        "persisted CalculationPlan revision differs from snapshot",
    )
    intent = plan.intent
    if preoptimization_handoff is None:
        _require(
            set(intent) == _CREST_SAMPLING_PLAN_V1_FIELDS
            and intent["schema"] == _CREST_SAMPLING_PLAN_V1_SCHEMA,
            "persisted CalculationPlan intent is not the closed CREST sampling contract v1",
        )
    else:
        _require(
            type(preoptimization_handoff) is _XtbCrestSeedHandoff,
            "preoptimization_handoff must be exact",
        )
        _require(
            set(intent) == _CREST_SAMPLING_PLAN_V2_FIELDS
            and intent["schema"] == _CREST_SAMPLING_PLAN_V2_SCHEMA,
            "persisted CalculationPlan intent is not the closed CREST sampling contract v2",
        )
        _require(
            xtb_program_execution_snapshot is not None
            and xtb_program_transport_store is not None
            and xtb_validation_driver is not None
            and xtb_output_capture is not None,
            "preoptimized CREST ingestion requires exact runtime capture context",
        )
        try:
            _assert_xtb_crest_seed_handoff_destination(
                preoptimization_handoff,
                sampling_profile=profile,
                crest_program_execution_spec=spec,
                crest_program_execution_snapshot=snapshot,
                xtb_core_store=core_store,
                xtb_program_execution_snapshot=xtb_program_execution_snapshot,
                xtb_program_transport_store=xtb_program_transport_store,
                xtb_validation_driver=xtb_validation_driver,
                xtb_output_capture=xtb_output_capture,
            )
        except ExecutionValueError as exc:
            raise ConformerError(
                f"xTB to CREST preoptimization handoff is not closed: {exc}"
            ) from exc
        _require(
            intent["preoptimization_handoff_authority_id"]
            == preoptimization_handoff.handoff_authority_id
            and intent["preoptimization_handoff_payload_sha256"]
            == preoptimization_handoff.payload_sha256,
            "persisted CalculationPlan binds a different preoptimization handoff",
        )
    _require(
        intent["sampling_profile_id"] == profile.sampling_profile_id
        and intent["sampling_profile_payload_sha256"] == profile_payload_sha256,
        "persisted CalculationPlan binds a different SamplingProfile",
    )
    _require(
        intent["program_execution_spec_id"] == spec.program_execution_spec_id
        and intent["program_execution_spec_payload_sha256"] == spec_payload_sha256,
        "persisted CalculationPlan binds a different ProgramExecutionSpec",
    )
    try:
        _assert_crest_program_execution_alignment(profile, spec)
    except ExecutionValueError as exc:
        raise ConformerError(f"CREST execution specification is not identity-closed: {exc}") from exc
    return spec, _exact_output_declaration(spec)


def _preoptimized_crest_sampling_plan_intent(
    *,
    profile: SamplingProfile,
    program_execution_spec: ProgramExecutionSpec,
    preoptimization_handoff: _XtbCrestSeedHandoff,
) -> Mapping[str, object]:
    """Build the exact private v2 CalculationPlan intent for preoptimized CREST."""

    _require(type(profile) is SamplingProfile, "profile must be an exact SamplingProfile")
    _require(
        type(program_execution_spec) is ProgramExecutionSpec,
        "program_execution_spec must be exact",
    )
    try:
        _assert_xtb_crest_seed_handoff_destination(
            preoptimization_handoff,
            sampling_profile=profile,
            crest_program_execution_spec=program_execution_spec,
        )
    except ExecutionValueError as exc:
        raise ConformerError(
            f"xTB to CREST preoptimization handoff is not closed: {exc}"
        ) from exc
    value = _freeze(
        {
            "schema": _CREST_SAMPLING_PLAN_V2_SCHEMA,
            "sampling_profile_id": profile.sampling_profile_id,
            "sampling_profile_payload_sha256": profile.payload_sha256,
            "program_execution_spec_id": (
                program_execution_spec.program_execution_spec_id
            ),
            "program_execution_spec_payload_sha256": semantic_sha256(
                program_execution_spec.semantic_payload()
            ),
            "preoptimization_handoff_authority_id": (
                preoptimization_handoff.handoff_authority_id
            ),
            "preoptimization_handoff_payload_sha256": (
                preoptimization_handoff.payload_sha256
            ),
        },
        "preoptimized CREST sampling plan intent",
    )
    assert isinstance(value, Mapping)
    return value


def _parse_crest_frames(
    raw: bytes,
    *,
    expected_elements: tuple[str, ...],
) -> tuple[
    tuple[Decimal, tuple[tuple[float, float, float], ...], bytes, str], ...
]:
    _require(raw and raw.endswith(b"\n"), "CREST ensemble must be non-empty and LF terminated")
    _require(b"\r" not in raw and b"\x00" not in raw, "CREST ensemble must use exact LF-only text boundaries")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ConformerError("CREST ensemble must be exact ASCII output") from exc
    lines = text[:-1].split("\n")
    _require(lines and all(line != "" for line in lines), "CREST ensemble contains a blank or trailing malformed line")
    atom_count = len(expected_elements)
    _require(atom_count > 0, "SamplingProfile atom inventory must not be empty")
    frame_line_count = atom_count + 2
    _require(len(lines) % frame_line_count == 0, "CREST ensemble is truncated or has trailing malformed content")
    frame_count = len(lines) // frame_line_count
    _require(frame_count > 0, "CREST ensemble contains no conformer frames")

    frames: list[
        tuple[Decimal, tuple[tuple[float, float, float], ...], bytes, str]
    ] = []
    byte_offset = 0
    for frame_index in range(frame_count):
        start = frame_index * frame_line_count
        frame_lines = lines[start : start + frame_line_count]
        _require(frame_lines[0] == f"  {atom_count}", f"frame {frame_index} atom count differs from the frozen CREST writer")
        energy = _fixed_decimal(
            frame_lines[1], width=20, grammar=_ENERGY, label=f"frame {frame_index} energy comment"
        )
        coordinates: list[tuple[float, float, float]] = []
        for atom_index, expected_element in enumerate(expected_elements):
            _require(
                re.fullmatch(r"[A-Z][a-z]?", expected_element) is not None,
                "SamplingProfile contains an unsupported element symbol",
            )
            line = frame_lines[atom_index + 2]
            _require(len(line) == 64 and line[0] == " " and line[3] == " ", f"frame {frame_index} atom {atom_index} has invalid CREST width")
            _require(line[1:3] == expected_element.ljust(2), f"frame {frame_index} element order or inventory changed")
            point = tuple(
                float(
                    _fixed_decimal(
                        line[4 + axis * 20 : 24 + axis * 20],
                        width=20,
                        grammar=_COORDINATE,
                        label=f"frame {frame_index} atom {atom_index} coordinate {axis}",
                    )
                )
                for axis in range(3)
            )
            coordinates.append(point)
        encoded_lines = tuple((line + "\n").encode("ascii") for line in frame_lines)
        frame_bytes = b"".join(encoded_lines)
        _require(raw[byte_offset : byte_offset + len(frame_bytes)] == frame_bytes, "CREST frame byte boundaries are inconsistent")
        byte_offset += len(frame_bytes)
        geometry_sha256 = sha256(b"".join(encoded_lines[2:])).hexdigest()
        frames.append((energy, tuple(coordinates), frame_bytes, geometry_sha256))
    _require(byte_offset == len(raw), "CREST ensemble has unconsumed trailing bytes")
    _require(
        all(frames[index - 1][0] <= frames[index][0] for index in range(1, len(frames))),
        "CREST ensemble energies are not nondecreasing in source-file order",
    )
    return tuple(frames)


def _ingest_crest_conformers_xyz_common(
    *,
    profile: SamplingProfile,
    program_execution_snapshot: ProgramExecutionSnapshot,
    core_store: SQLiteRuntimeStore,
    artifact_binding: _CrestOutputArtifactBinding,
    artifact_bytes: bytes,
    descriptors_by_member_index: Mapping[int, Mapping[str, object]] | None,
    relevance_tags_by_member_index: Mapping[int, Sequence[str]] | None = None,
    preoptimization_handoff: _XtbCrestSeedHandoff | None,
    xtb_program_execution_snapshot: ProgramExecutionSnapshot | None = None,
    xtb_program_transport_store: _transport._ProgramTransportStore | None = None,
    xtb_validation_driver: _transport._ProgramEffectDriver | None = None,
    xtb_output_capture: _transport._ProgramOutputCapture | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Translate one exact CREST 3.0.2 ensemble artifact into closed observations."""

    program_execution_spec, declaration = _close_sampling_authority(
        profile=profile,
        snapshot=program_execution_snapshot,
        core_store=core_store,
        preoptimization_handoff=preoptimization_handoff,
        xtb_program_execution_snapshot=xtb_program_execution_snapshot,
        xtb_program_transport_store=xtb_program_transport_store,
        xtb_validation_driver=xtb_validation_driver,
        xtb_output_capture=xtb_output_capture,
    )
    _require(
        type(artifact_binding) is _CrestOutputArtifactBinding,
        "artifact_binding must be exact",
    )
    artifact_binding.assert_closed()
    _require(
        artifact_binding.program_execution_snapshot_id
        == program_execution_snapshot.program_execution_snapshot_id
        and artifact_binding.effect_intent_id == program_execution_snapshot.effect_intent_id
        and artifact_binding.program_execution_spec_id
        == program_execution_spec.program_execution_spec_id,
        "artifact binding differs from the exact execution snapshot",
    )
    _require(
        artifact_binding.logical_role == declaration["logical_role"]
        and artifact_binding.portable_name == declaration["portable_name"]
        and artifact_binding.format == declaration["format"],
        "artifact binding differs from the exact declared CREST output",
    )
    _require(isinstance(artifact_bytes, bytes), "artifact_bytes must be immutable bytes")
    _require(len(artifact_bytes) == artifact_binding.size_bytes, "artifact size differs from exact bytes")
    _require(sha256(artifact_bytes).hexdigest() == artifact_binding.sha256, "artifact SHA-256 differs from exact bytes")
    _require(artifact_binding.size_bytes <= declaration["max_size_bytes"], "artifact exceeds the frozen output size limit")
    _require(
        profile.crest_imtd_gc_profile["sampling_energy"]["unit"]
        == "kcal_per_mol_sampling_only",
        "CREST 3.0.2 ingestion supports only the frozen sampling-energy unit",
    )

    species = profile.species_binding
    elements = tuple(species["elements"])
    frames = _parse_crest_frames(artifact_bytes, expected_elements=elements)
    descriptors = _closed_index_mapping(
        descriptors_by_member_index, member_count=len(frames), label="descriptors_by_member_index"
    )
    relevance = _closed_index_mapping(
        relevance_tags_by_member_index, member_count=len(frames), label="relevance_tags_by_member_index"
    )
    reference_energy = frames[0][0]
    artifact_payload = {
        **artifact_binding.semantic_payload(),
        "output_declaration": declaration,
    }
    artifact_identity = semantic_id("crest-output-artifact", artifact_payload)
    source_set_id = semantic_id(
        "crest-conformer-set",
        {
            "sampling_profile_id": profile.sampling_profile_id,
            "source_artifact_identity": artifact_identity,
        },
    )
    sampling_configuration_identity = _payload_sha256(profile.crest_imtd_gc_profile)
    atom_order = tuple(species["atom_order"])
    correspondence = tuple(
        {
            "source_atom_id": species["atom_mapping"][atom_id],
            "canonical_map_id": atom_id,
            "element": element,
        }
        for atom_id, element in zip(atom_order, elements)
    )

    observations: list[Mapping[str, object]] = []
    for member_index, (
        absolute_energy,
        coordinates,
        frame_bytes,
        geometry_sha256,
    ) in enumerate(frames):
        frame_sha256 = sha256(frame_bytes).hexdigest()
        member_id = semantic_id(
            "crest-conformer-member",
            {
                "source_set_id": source_set_id,
                "source_member_index": member_index,
                "frame_sha256": frame_sha256,
            },
        )
        relative_energy = float(
            (absolute_energy - reference_energy) * _CREST_HARTREE_TO_KCAL_PER_MOL
        )
        observation = {
            "member_id": member_id,
            "atom_order": atom_order,
            "atom_correspondence": correspondence,
            "elements": elements,
            "explicit_hydrogens": tuple(species["explicit_hydrogens"]),
            "fragment_ids": tuple(species["fragment_ids"]),
            "bonds": tuple(tuple(bond) for bond in species["bonds"]),
            "formal_charge": species["formal_charge"],
            "multiplicity": species["multiplicity"],
            "electronic_state_family": species["electronic_state_family"],
            "stereochemistry_binding": profile.stereochemistry_binding,
            "coordinates_angstrom": coordinates,
            "source_binding": {
                "sampling_profile_id": profile.sampling_profile_id,
                "provider": "crest",
                "mode": "imtd-gc",
                "sampling_configuration_identity": sampling_configuration_identity,
                "source_run_id": program_execution_snapshot.program_execution_snapshot_id,
                "source_set_id": source_set_id,
                "source_member_index": member_index,
                "source_geometry_identity": (
                    semantic_id(
                        "crest-frame-geometry",
                        {
                            "elements": elements,
                            "geometry_sha256": geometry_sha256,
                        },
                    )
                ),
                "source_artifact_identity": artifact_identity,
                "seed": None,
                "replica_index": 0,
            },
            "sampling_energy": {
                "value": relative_energy,
                "unit": "kcal_per_mol_sampling_only",
                "formal_thermodynamics_allowed": False,
            },
            "descriptors": descriptors.get(member_index, {}),
            "relevance_tags": relevance.get(member_index, ()),
        }
        frozen = _freeze(observation, f"ingested_observations[{member_index}]")
        assert isinstance(frozen, Mapping)
        observations.append(frozen)
    return tuple(observations)


def _ingest_crest_conformers_xyz(
    *,
    profile: SamplingProfile,
    program_execution_snapshot: ProgramExecutionSnapshot,
    core_store: SQLiteRuntimeStore,
    artifact_binding: _CrestOutputArtifactBinding,
    artifact_bytes: bytes,
    descriptors_by_member_index: Mapping[int, Mapping[str, object]] | None,
    relevance_tags_by_member_index: Mapping[int, Sequence[str]] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Preserve the historical v1 CREST ingest semantics without xTB authority."""

    return _ingest_crest_conformers_xyz_common(
        profile=profile,
        program_execution_snapshot=program_execution_snapshot,
        core_store=core_store,
        artifact_binding=artifact_binding,
        artifact_bytes=artifact_bytes,
        descriptors_by_member_index=descriptors_by_member_index,
        relevance_tags_by_member_index=relevance_tags_by_member_index,
        preoptimization_handoff=None,
    )


def _ingest_preoptimized_crest_conformers_xyz(
    *,
    profile: SamplingProfile,
    program_execution_snapshot: ProgramExecutionSnapshot,
    core_store: SQLiteRuntimeStore,
    preoptimization_handoff: _XtbCrestSeedHandoff,
    xtb_program_execution_snapshot: ProgramExecutionSnapshot,
    xtb_program_transport_store: _transport._ProgramTransportStore,
    xtb_validation_driver: _transport._ProgramEffectDriver,
    xtb_output_capture: _transport._ProgramOutputCapture,
    artifact_binding: _CrestOutputArtifactBinding,
    artifact_bytes: bytes,
    descriptors_by_member_index: Mapping[int, Mapping[str, object]] | None,
    relevance_tags_by_member_index: Mapping[int, Sequence[str]] | None = None,
) -> tuple[Mapping[str, object], ...]:
    """Ingest CREST output only after the private preoptimization chain closes."""

    return _ingest_crest_conformers_xyz_common(
        profile=profile,
        program_execution_snapshot=program_execution_snapshot,
        core_store=core_store,
        artifact_binding=artifact_binding,
        artifact_bytes=artifact_bytes,
        descriptors_by_member_index=descriptors_by_member_index,
        relevance_tags_by_member_index=relevance_tags_by_member_index,
        preoptimization_handoff=preoptimization_handoff,
        xtb_program_execution_snapshot=xtb_program_execution_snapshot,
        xtb_program_transport_store=xtb_program_transport_store,
        xtb_validation_driver=xtb_validation_driver,
        xtb_output_capture=xtb_output_capture,
    )
