"""Versioned read-only xTB receipt seed consumer. Strict handoff is unchanged."""
from dataclasses import dataclass
from collections.abc import Mapping
from hashlib import sha256

from ._identity import ExecutionValueError, freeze_mapping, semantic_id, semantic_sha256
from .program import ProgramExecutionSpec
from .program_runtime import _read_program_receipt_success_authority
from .xtb_crest_handoff import _close_capture_to_snapshot, _profile_identity

_SCHEMA = "v31-xtb-crest-seed-handoff/2"


@dataclass(frozen=True, slots=True, init=False)
class _ReceiptSeedHandoff:
    handoff_authority_id: str
    payload_sha256: str
    payload: Mapping[str, object]

    def __init__(self):
        raise TypeError("receipt seed handoff is service-created")

    def assert_identity_closed(self):
        if self.payload.get("schema") != _SCHEMA or self.handoff_authority_id != semantic_id("xtb-crest-receipt-seed-handoff", self.payload) or self.payload_sha256 != semantic_sha256(self.payload):
            raise ExecutionValueError("receipt seed handoff identity drift")


def _build_receipt_seed_handoff(*, core_store, xtb_program_execution_snapshot,
                              xtb_program_transport_store, xtb_validation_driver,
                              crest_program_execution_spec, crest_exact_input_bytes,
                              sampling_profile):
    source = xtb_program_execution_snapshot
    source.assert_identity_closed()
    spec = source.program_execution_spec
    if (spec.program_kind, spec.adapter_id, spec.adapter_contract_version) != ("xtb", "auto-g16-v31-xtb", 3) or spec.program_data["task"] != "optimize" or spec.program_data["solvent"] is not None:
        raise ExecutionValueError("receipt seed requires exact gas-phase xTB v3 optimize")
    proof, capture = _read_program_receipt_success_authority(core_store,
        snapshot=source, program_transport_store=xtb_program_transport_store,
        driver=xtb_validation_driver)
    geometry = _close_capture_to_snapshot(source, capture, _source_adapter_version=3)
    if proof["schema"] != "program-terminal-success-authority/2" or proof["capture_authority_id"] != capture.capture_authority_id:
        raise ExecutionValueError("receipt seed requires native matching /2 proof and capture")
    target = crest_program_execution_spec
    if type(target) is not ProgramExecutionSpec:
        raise ExecutionValueError("receipt seed destination must be exact spec")
    target.assert_identity_closed()
    if (target.program_kind, target.adapter_id, target.adapter_contract_version) != ("crest", "auto-g16-v31-crest", 3):
        raise ExecutionValueError("receipt seed destination requires CREST v3")
    from auto_g16.conformer.service import _assert_crest_program_execution_alignment
    _assert_crest_program_execution_alignment(sampling_profile, target)
    profile_id, profile_digest, profile = _profile_identity(sampling_profile)
    seed = target.exact_inputs[0]
    if type(crest_exact_input_bytes) is not bytes or crest_exact_input_bytes != geometry.content or seed["portable_name"] != "seed.xyz" or seed["sha256"] != sha256(crest_exact_input_bytes).hexdigest() or seed["size_bytes"] != len(crest_exact_input_bytes):
        raise ExecutionValueError("receipt seed bytes differ from native captured geometry")
    species = profile["species_binding"]
    from ._program_completion import _xyz_elements
    if tuple(species["elements"]) != _xyz_elements(crest_exact_input_bytes):
        raise ExecutionValueError("receipt seed ordered elements differ from reviewed species")
    if (spec.program_data["charge"] != target.program_data["charge"] or target.program_data["charge"] != species["formal_charge"] or spec.program_data["model"] != target.program_data["model"] or spec.program_data["unpaired_electrons"] != 0 or target.program_data["unpaired_electrons"] != 0 or species["multiplicity"] != 1 or species["electronic_state_family"] != "reviewed_closed_shell_singlet"):
        raise ExecutionValueError("receipt seed electronic state or model differs")
    payload = freeze_mapping({"schema": _SCHEMA,
        "xtb_snapshot_id": source.program_execution_snapshot_id,
        "xtb_effect_intent_id": source.effect_intent_id,
        "xtb_project_id": source.project_physical_binding.project_id,
        "xtb_project_physical_binding_id": source.project_physical_binding_id,
        "xtb_project_physical_binding": source.project_physical_binding.semantic_payload(),
        "xtb_terminal_success_authority": proof,
        "optimized_geometry_sha256": geometry.sha256,
        "optimized_geometry_size_bytes": geometry.size_bytes,
        "crest_spec_id": target.program_execution_spec_id,
        "crest_spec_payload_sha256": semantic_sha256(target.semantic_payload()),
        "sampling_profile_id": profile_id, "sampling_profile_payload_sha256": profile_digest,
    }, "receipt seed handoff")
    value = object.__new__(_ReceiptSeedHandoff)
    object.__setattr__(value, "payload", payload)
    object.__setattr__(value, "payload_sha256", semantic_sha256(payload))
    object.__setattr__(value, "handoff_authority_id", semantic_id("xtb-crest-receipt-seed-handoff", payload))
    value.assert_identity_closed()
    return value


def _assert_receipt_seed_handoff(handoff, *, crest_program_execution_snapshot=None, **source_context):
    if type(handoff) is not _ReceiptSeedHandoff:
        raise ExecutionValueError("exact receipt seed handoff required")
    handoff.assert_identity_closed()
    rebuilt = _build_receipt_seed_handoff(**source_context)
    if rebuilt != handoff:
        raise ExecutionValueError("receipt seed source or destination changed")
    if crest_program_execution_snapshot is not None:
        snapshot = crest_program_execution_snapshot
        snapshot.assert_identity_closed()
        source_binding = source_context["xtb_program_execution_snapshot"].project_physical_binding
        target_binding = snapshot.project_physical_binding
        if (snapshot.program_execution_spec_id != handoff.payload["crest_spec_id"]
                or target_binding.resolved_target_identity != source_binding.resolved_target_identity
                or target_binding.locations[0]["reviewed_root"] != source_binding.locations[0]["reviewed_root"]
                or target_binding.project_id == source_binding.project_id
                or target_binding.remote_project_dir == source_binding.remote_project_dir):
            raise ExecutionValueError("receipt seed destination snapshot or Project differs")


@dataclass(frozen=True, slots=True)
class _FixedReceiptSubmission:
    handoff: _ReceiptSeedHandoff
    destination_snapshot_id: str
    destination_project_binding: Mapping[str, object]
    calculation_plan_id: str
    plan_intent_sha256: str
    source_context: Mapping[str, object]


_FIXED_RECEIPT_SUBMISSION: _FixedReceiptSubmission | None = None


def _assert_fixed_receipt_submission(store, snapshot, input_bytes):
    fixed = _FIXED_RECEIPT_SUBMISSION
    if type(fixed) is not _FixedReceiptSubmission:
        raise ExecutionValueError("fixed CREST receipt submission NOT_ACQUIRED")
    if (fixed.destination_snapshot_id != snapshot.program_execution_snapshot_id
            or fixed.destination_project_binding != snapshot.project_physical_binding.semantic_payload()
            or fixed.calculation_plan_id != snapshot.calculation_plan_id):
        raise ExecutionValueError("fixed CREST destination changed")
    plan = store.load_calculation_plan(snapshot.calculation_plan_id)
    expected = {"handoff_authority_id": fixed.handoff.handoff_authority_id,
                "payload_sha256": fixed.handoff.payload_sha256}
    if semantic_sha256(plan.intent) != fixed.plan_intent_sha256 or plan.intent.get("crest_receipt_seed_handoff") != expected:
        raise ExecutionValueError("CREST plan does not bind the fixed receipt handoff")
    context = dict(fixed.source_context)
    if context.get("crest_exact_input_bytes") != input_bytes or context.get("crest_program_execution_spec") != snapshot.program_execution_spec:
        raise ExecutionValueError("fixed CREST seed or spec changed")
    _assert_receipt_seed_handoff(fixed.handoff, crest_program_execution_snapshot=snapshot, **context)
    if _FIXED_RECEIPT_SUBMISSION is not fixed:
        raise ExecutionValueError("fixed CREST receipt submission changed")


__all__: tuple[str, ...] = ()
