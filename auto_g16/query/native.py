"""Source-scoped read-only inventory and owned facts; no private runtime decoding."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
import math
import re
import sqlite3
from hashlib import sha256
from typing import Callable

from auto_g16.conformer.readonly import OptReadout, OptReadBusy
from auto_g16.conformer.frequency_readonly import FreqReadout
from auto_g16.conformer.thermochemistry_readonly import NativeThermodynamicReadout
from auto_g16.core import RecordNotFoundError, RuntimeStoreError, RuntimeStoreSchemaError
from auto_g16.transport import TransportBoundaryError
from auto_g16.execution.readonly import ProgramReadSnapshot, ProgramReadQuery
from auto_g16.result import (GaussianResultQuery, ResultProvenanceService,
    INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION, PARSED_RESULT_TYPE)
from .models import QueryError
from .service import QueryService, _field, _missing

NATIVE_QUERY_SCHEMA = "auto-g16-native-query/1"
NATIVE_THERMODYNAMICS_SCHEMA = "auto-g16-native-thermodynamics-query/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_SUCCESSOR = frozenset({"program-completion-evidence/1", "v31-program-effect-receipt/1",
                        "program-completion-assessment/1", "auto-g16-v31-collection-start/1"})
_KNOWN = _SUCCESSOR | {INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION,
                       PARSED_RESULT_TYPE, "v3.remote-effect-receipt", "auto-g16-v3-attempt-observation",
                       "v31-gaussian-result-source/1", "v31-gaussian-parsed-result/1",
                       "v31-gaussian-result-source/2", "v31-gaussian-parsed-result/2"}


def _identifier(value: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise QueryError("invalid-id")
    return value


def _evidence_id(value):
    try:
        return _identifier(value)
    except QueryError:
        raise QueryError("invalid-evidence") from None


def _fact(value, source, unit=None):
    return {**_field(value, source), "unit": unit}


def _absent(reason, unit=None, *, unavailable=True):
    return {**_missing(reason, unavailable=unavailable), "unit": unit}


def _same_registration(left, right):
    """Complete typed equality, including physical bindings (True is not 1)."""
    if type(left) is not type(right):
        return False
    if is_dataclass(left):
        return all(_same_registration(getattr(left, f.name), getattr(right, f.name)) for f in fields(left))
    if type(left) is tuple:
        return len(left) == len(right) and all(_same_registration(a, b) for a, b in zip(left, right))
    return left == right


def _thermo_require(condition):
    if not condition:
        raise QueryError("invalid-evidence")


def _thermo_closed(value, keys):
    _thermo_require(isinstance(value, Mapping) and set(value) == set(keys))
    return dict(value)


def _thermo_number(value, *, positive=False):
    _thermo_require(type(value) in (int, float) and math.isfinite(value)
                    and (not positive or value > 0))
    return value


def _thermo_integer(value):
    _thermo_require(type(value) is int and value > 0)
    return value


def _thermo_text(value):
    _thermo_require(type(value) is str and bool(value.strip()) and value == value.strip())
    return value


def _thermo_digest(value):
    _thermo_require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None)
    return value


def _thermo_ref(identity, digest, revision=None):
    result = dict(id=_evidence_id(identity), payload_sha256=_thermo_digest(digest))
    if revision is not None:
        result['revision'] = _thermo_integer(revision)
    return result


def _thermo_source_ref(value, key):
    value = _thermo_closed(value, (key, 'payload_sha256'))
    return {key: _evidence_id(value[key]), 'payload_sha256': _thermo_digest(value['payload_sha256'])}


def _thermodynamics_result(reader, pair, selected_member):
    """Project saved values only, after the owning read has exited successfully."""
    qualified, thermo = pair
    audit = qualified.audit_evidence[-1]
    request = audit['request_payload']
    policy = thermo.thermochemistry_policy
    source = _thermo_closed(request['source_ensemble'], ('conformer_ensemble_id', 'payload_sha256', 'revision'))
    profile = _thermo_closed(request['sampling_profile'], ('sampling_profile_id', 'payload_sha256'))
    parameters = dict(temperature_k=_thermo_number(thermo.temperature_k, positive=True),
        standard_state=thermo.standard_state, entropy_method=policy['qrrho_entropy_method'],
        enthalpy_method=policy['qrrho_enthalpy_method'], moment_of_inertia=policy['moment_of_inertia'],
        degeneracy_excludes_rotational_symmetry=policy['degeneracy_excludes_rotational_symmetry'],
        functional_kernel_implementation_id=_evidence_id(thermo.functional_kernel_implementation_id))
    _thermo_require(parameters['standard_state'] in ('1atm', '1M')
        and parameters['entropy_method'] == 'grimme' and parameters['enthalpy_method'] == 'head_gordon'
        and parameters['moment_of_inertia'] == 'global_grimme_bav'
        and parameters['degeneracy_excludes_rotational_symmetry'] is True)
    for key in ('entropy_frequency_cutoff_cm1', 'enthalpy_frequency_cutoff_cm1',
                'frequency_scaling_factor', 'zpe_scaling_factor'):
        parameters[key] = _thermo_number(policy[key], positive=True)
    ids = tuple(row['member_id'] for row in thermo.member_observations)
    _thermo_require(len(ids) == 2 and len(set(ids)) == len(ids) and selected_member in ids
        and ids == thermo.source_member_ids == qualified.thermodynamic_eligible_members)
    stages = []
    for sources in (reader.readout.optimization_sources, reader.readout.frequency_sources):
        by_member = {s.member_id: s.snapshot.attempt_id for s in sources}
        _thermo_require(len(by_member) == len(sources) and set(by_member) == set(ids))
        stages.append(by_member)
    members = []
    for row in thermo.member_observations:
        mid = _evidence_id(row['member_id'])
        raw = _thermo_closed(row['raw_rrho'], ('electronic_energy_hartree', 'zero_point_energy_hartree',
            'enthalpy_hartree', 'entropy_hartree_per_kelvin', 'gibbs_free_energy_hartree'))
        treated = _thermo_closed(row['treated_qrrho'], ('enthalpy_hartree', 'entropy_hartree_per_kelvin',
            'gibbs_free_energy_hartree', 'entropy_treatment', 'enthalpy_treatment'))
        for value in raw.values():
            _thermo_number(value)
        for key in ('enthalpy_hartree', 'entropy_hartree_per_kelvin', 'gibbs_free_energy_hartree'):
            _thermo_number(treated[key])
        _thermo_require(treated['entropy_treatment'] == 'grimme' and treated['enthalpy_treatment'] == 'head_gordon')
        population = _thermo_number(row['normalized_population'])
        _thermo_require(0 <= population <= 1 and row['inclusion_status'] == 'included_thermodynamic_eligible')
        minimum = row['source_provenance']['minimum_authority']
        provenance = dict(optimization_attempt_id=_evidence_id(stages[0][mid]),
            frequency_attempt_id=_evidence_id(stages[1][mid]),
            two_stage_minimum_authority_id=_evidence_id(row['two_stage_minimum_authority_id']))
        for stage in ('optimization', 'frequency'):
            provenance[stage + '_parsed_result'] = _thermo_source_ref(minimum[stage]['parsed_result'], 'result_id')
            provenance[stage + '_result_source'] = _thermo_source_ref(minimum[stage]['result_source'], 'observation_id')
        members.append(dict(member_id=mid, is_selected=mid == selected_member,
            degeneracy=_thermo_integer(row['degeneracy']), degeneracy_rationale=_thermo_text(row['degeneracy_rationale']),
            inclusion_status=row['inclusion_status'], raw_rrho=raw, treated_qrrho=treated,
            normalized_population=population, source=provenance))
    normalization = _thermo_closed(thermo.population_normalization,
        ('population_sum', 'absolute_error', 'numeric_tolerance', 'status', 'tolerance_purpose'))
    for key in ('population_sum', 'absolute_error', 'numeric_tolerance'):
        _thermo_number(normalization[key])
    _thermo_require(normalization['status'] == 'normalized'
        and normalization['tolerance_purpose'] == 'floating_point_normalization_only_not_scientific_selection')
    coverage = _thermo_closed(request['coverage_scope'], ('kind', 'rationale'))
    _thermo_require(coverage['kind'] == 'frozen_profile_nonexhaustive_scope')
    _thermo_text(coverage['rationale'])
    return dict(artifact_sha256=_thermo_digest(reader.artifact.sha256),
        source_ensemble=_thermo_ref(source['conformer_ensemble_id'], source['payload_sha256'],
                                    _thermo_integer(source['revision'])),
        qualified_ensemble=_thermo_ref(qualified.conformer_ensemble_id, qualified.payload_sha256,
                                       _thermo_integer(qualified.revision)),
        thermodynamic_ensemble=_thermo_ref(thermo.thermodynamic_ensemble_id, thermo.payload_sha256),
        sampling_profile=_thermo_ref(profile['sampling_profile_id'], profile['payload_sha256']),
        request=_thermo_ref(audit['request_id'], audit['request_payload_sha256']), parameters=parameters,
        members=members, ensemble_treated_free_energy_hartree=_thermo_number(thermo.ensemble_treated_free_energy_hartree),
        population_normalization=normalization, coverage_scope=coverage, scientific_acceptance='unavailable')


# These exact reasons belong to the pinned existing owners. No substring or
# traceback inference; ambiguous or future transport failures remain internal.
_THERMO_TRANSPORT_EVIDENCE = frozenset({
    'publisher-not-qualified: ' + reason for reason in (
        'invalid installed path', 'invalid installed content identity', 'invalid installed parent inventory',
        'invalid installed physical identity', 'installed object is not a regular file',
        'installed size drift', 'short installed read', 'installed bytes/identity drift',
        'installed path/descriptor drift')
}) | frozenset({
    'invalid Gaussian historical source catalogue', 'Gaussian historical source catalogue changed',
    'registered historical association source NOT_ACQUIRED', 'fixed historical source locator NOT_ACQUIRED',
    'historical source requires the exact original receipt tuple', 'historical bootstrap source changed',
    'historical source locator changed', 'historical source requires idle DELETE journal databases',
    'historical source is not the fixed original database', 'historical source has a journal sidecar',
    'historical source bytes require rollback journal format', 'historical Core bytes have an unsupported schema',
    'completion store path is not canonical', 'completion store escapes its approved root',
    'completion directory identity is invalid', 'completion directory identity drifted',
    'program transport store paths must be strings', 'program transport store root must not be a symlink',
    'program transport store parent is invalid', 'program transport store must be a regular file',
    'read-only source has a SQLite sidecar', 'read-only source must be a single regular file',
    'read-only source requires rollback journal format', 'read-only source path changed',
    'completion directory changed across SQLite open', 'read-only source changed across SQLite open',
    'program transport store schema drifted', 'program transport store changed across SQLite open',
    'completion persistent directory identity drifted', 'completion database identity or hardlink drifted',
    'program transport store identity drifted', 'program transport store inventory drifted',
    'program transport store meta drifted', 'program transport store meta authority drifted',
    # Receipt/source replay rejects these exact persisted-evidence conditions.
    'Core SUBMITTED reconciliation does not replay for the job receipt',
    'Core reconciliation replay changed successor Attempt state',
    'Gaussian completion source is not unique',
    'Gaussian config or marker differs from unique snapshot derivation',
    'Gaussian handoff requires four ordered durable stages',
    'Gaussian source input/log inventory differs',
    'Gaussian source requires a supported pure stage adapter',
    'Gaussian source requires exact native owners',
    'absent captured file carries bytes or is receipt',
    'accepted completion history was contradicted',
    'ambiguous submit request does not re-close to prior authorities',
    'captured FETCH source differs',
    'captured STAT sources are missing',
    'captured bytes differ from persisted FETCH',
    'captured evidence order is not exact',
    'captured file declaration differs',
    'captured file drifted across STAT',
    'captured file inventory differs',
    'captured file presence is invalid',
    'captured input STAGE order differs',
    'captured input STAGE source differs',
    'captured input identity differs',
    'collection checkpoint scope differs',
    'completion assessment omits exact evidence sources',
    'completion assessment or prefix is corrupt',
    'completion bundle identity differs',
    'completion checkpoint requires its exact store',
    'completion durable bytes are missing',
    'completion epoch opening is not unique',
    'completion evidence bundle exceeds cap',
    'completion input inventory differs',
    'dual-source successor receipt closure is incomplete',
    'exact persisted successor job-establishing receipt is required',
    'fetch cannot consume an absent STAT authority',
    'fetch requires one exact successful STAT predecessor',
    'final observation is not exact absence',
    'foreign or interleaved completion epoch evidence',
    'historical runtime attestation differs or is missing',
    'historical source lacks the exact recorded SUBMITTED reconciliation',
    'historical source lacks the exact recorded intent',
    'historical tuple cannot gain handoff stages',
    'input STAGE provenance is not unique',
    'job-establishing request does not re-close to prior authorities',
    'later capture evidence is unknown',
    'later captured file identity changed',
    'missing final absence',
    'mixed V30/successor execution or Result generation',
    'multiple unassessed completion bundles',
    'one successful dual-source ALLOCATE predecessor is required',
    'persisted fetch response differs from exact request',
    'persisted successor receipt is malformed',
    'persisted successor request does not re-close to predecessor authority',
    'read-only receipt proof requires persisted success',
    'read-only receipt proof was invalidated',
    'read-only source requires exact native stores',
    'receipt outputs differ from captured outputs',
    'reconciliation requires one exact Core UNKNOWN submit predecessor',
    'saved assessment differs from source evidence',
    'stage receipt request is malformed',
    'staged artifact authority is inconsistent',
    'submit requires exact startup payload authority',
    'submit requires one authority for every exact program input',
    'submit staged predecessor authority set is not exact',
    'successor authority cannot claim a PLANNED effect intent',
    'successor effect intent does not replay through public Core',
    'successor effect intent requires exact public Core REPLAY',
    'successor job authority requires a submitted-compatible Core state',
    'successor receipt operation differs from its exact request',
    'successor receipt request payload is malformed',
    'terminal completion assessment lacks captured provenance',
    'workspace authority does not close to snapshot',
})


def _thermodynamics_error(error):
    if isinstance(error, QueryError):
        return error.code
    if isinstance(error, OptReadBusy):
        return 'store-unavailable'
    if isinstance(error, RecordNotFoundError):
        return 'invalid-evidence'
    if isinstance(error, (TransportBoundaryError, RuntimeStoreSchemaError)):
        cause, seen = error.__cause__, set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, OSError):
                return 'store-unavailable'
            cause = cause.__cause__
    if isinstance(error, TransportBoundaryError):
        if str(error) in ('completion owner is busy', 'completion native fork/lock primitives unavailable'):
            return 'store-unavailable'
        return 'invalid-evidence' if str(error) in _THERMO_TRANSPORT_EVIDENCE else 'internal-error'
    if isinstance(error, RuntimeStoreSchemaError):
        return 'invalid-evidence'
    if isinstance(error, sqlite3.Error):
        code = getattr(error, 'sqlite_errorcode', None)
        if code is None:
            return 'internal-error'
        primary = code & 255
        if primary in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB, sqlite3.SQLITE_SCHEMA,
                       sqlite3.SQLITE_FORMAT, sqlite3.SQLITE_CONSTRAINT):
            return 'invalid-evidence'
        if primary in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CANTOPEN,
                       sqlite3.SQLITE_IOERR, sqlite3.SQLITE_NOMEM, sqlite3.SQLITE_PERM,
                       sqlite3.SQLITE_AUTH, sqlite3.SQLITE_READONLY, sqlite3.SQLITE_FULL):
            return 'store-unavailable'
        return 'internal-error'
    if isinstance(error, (OSError, RuntimeStoreError)):
        return 'store-unavailable'
    if isinstance(error, (ValueError, TypeError, KeyError, IndexError, OverflowError)):
        return 'invalid-evidence'
    return 'internal-error'


@dataclass(frozen=True, kw_only=True)
class NativeSource:
    """Trusted startup registration. Paths are never accepted from an HTTP request."""
    source_id: str
    database: Path = field(repr=False)
    snapshots: tuple[ProgramReadSnapshot, ...] = field(default=(), repr=False)
    opt_readout: OptReadout | None = field(default=None, repr=False)

    freq_readout: FreqReadout | None = field(default=None, repr=False)
    thermodynamic_readout: NativeThermodynamicReadout | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.snapshots) is not tuple or any(type(s) is not ProgramReadSnapshot for s in self.snapshots):
            raise QueryError("invalid-source-registration")
        if len({s.attempt_id for s in self.snapshots}) != len(self.snapshots):
            raise QueryError("duplicate-snapshot-registration")
        _identifier(self.source_id)
        path = Path(self.database)
        if not path.is_absolute() or str(path) != str(self.database) or ".." in path.parts:
            raise QueryError("invalid-source-registration")
        object.__setattr__(self, "database", path)
        if self.opt_readout is not None and self.freq_readout is not None:
            raise QueryError("conflicting-stage-registration")
        if self.freq_readout is not None:
            if type(self.freq_readout) is not FreqReadout or len(self.snapshots) != 1:
                raise QueryError("invalid-freq-registration")
            selected = self.freq_readout.source_for(self.snapshots[0].attempt_id)
            if selected.revision.path != str(path) or selected.snapshot != self.snapshots[0]:
                raise QueryError("invalid-freq-registration")
        if self.opt_readout is not None:
            if type(self.opt_readout) is not OptReadout or len(self.snapshots) != 1:
                raise QueryError("invalid-opt-registration")
            selected = self.opt_readout.source_for(self.snapshots[0].attempt_id)
            if selected.revision.path != str(path) or selected.snapshot != self.snapshots[0]:
                raise QueryError("invalid-opt-registration")

        if self.thermodynamic_readout is not None:
            if (type(self.thermodynamic_readout) is not NativeThermodynamicReadout
                    or type(self.freq_readout) is not FreqReadout
                    or not _same_registration(self.thermodynamic_readout.readout, self.freq_readout)):
                raise QueryError("invalid-thermodynamic-registration")


class NativeQueryService:
    """Independent source snapshots; no claim of a transaction across sources."""
    def __init__(self, sources: tuple[NativeSource, ...]):
        if not sources or any(type(source) is not NativeSource for source in sources):
            raise QueryError("invalid-source-registration")
        if (len({s.source_id for s in sources}) != len(sources)
                or len({s.database for s in sources}) != len(sources)):
            raise QueryError("duplicate-source-registration")
        self._sources = {s.source_id: s for s in sorted(sources, key=lambda s: s.source_id)}

    def _read(self, source_id: str, operation: Callable):
        _identifier(source_id)
        if source_id not in self._sources:
            raise QueryError("not-found")
        return QueryService(self._sources[source_id].database)._read("native", operation)["data"]

    @staticmethod
    def _dto(kind, data):
        return {"schema": NATIVE_QUERY_SCHEMA, "kind": kind, "data": data}

    def _attempt(self, store, source_id, attempt_id):
        attempt = store.load_attempt(attempt_id)
        task = store.load_task(attempt.task_id)
        run = store.load_workflow_run(task.workflow_run_id)
        for identity in (attempt_id, task.task_id, run.workflow_run_id, run.project_id):
            _evidence_id(identity)
        observations = store.observations_for_attempt(attempt_id)
        results = store.results_for_attempt(attempt_id)
        # Public record identity/type only. Payloads belong to their owning readers.
        inventory = []
        for kind, records, identity_key, type_key in (
            ("observation", observations, "observation_id", "observation_type"),
            ("result", results, "result_id", "result_type"),
        ):
            for record in records:
                identity = _evidence_id(getattr(record, identity_key))
                record_type = getattr(record, type_key)
                inventory.append({"kind": kind, "record_id": identity,
                                  "contract": record_type if record_type in _KNOWN else "unavailable",
                                  "contract_sha256": sha256(record_type.encode()).hexdigest()})
        types = {item.observation_type for item in observations} | {item.result_type for item in results}
        successor = bool(types & _SUCCESSOR)
        gaussian = GaussianResultQuery(store).get_summary(attempt_id)
        conflict = gaussian["availability"] == "conflict"
        reason = gaussian["reasons"][0] if gaussian["reasons"] else None
        generation = (_absent("mixed-execution-generations") if conflict and reason == "mixed-execution-generations" else
                      _fact("V31", "Core.record-type-inventory") if successor else
                      _fact("V30", "Result.InputBinding") if gaussian["source"] else
                      _absent("execution-generation-not-bound"))
        unavailable = "v31-owner-readonly-interface-unavailable" if successor else "no-attributed-result"
        data = {"source_id": source_id, "origin": "native-core", "project_id": run.project_id,
                "workflow_run_id": run.workflow_run_id, "task_id": task.task_id,
                "attempt_id": attempt_id, "ordinal": attempt.ordinal,
                "generation": generation, "program": _absent(unavailable),
                "bound_plan": _absent("no-exact-attempt-input-binding"),
                "input": _absent(unavailable), "artifacts": _absent(unavailable),
                "record_inventory": inventory,
                "axes": {"execution": _fact(store.attempt_state(attempt_id).value, "Core.attempt_state"),
                         "capture": _absent(unavailable),
                         "result": _fact({"count": len(results)}, "Core.results_for_attempt"),
                         "validation": _absent("scientific-validation-reader-not-connected"),
                         "review": _absent("scientific-review-reader-not-connected")},
                "facts": {"energy": _absent(unavailable, "hartree"),
                          "geometry": _absent(unavailable, "angstrom"),
                          "frequencies": _absent(unavailable, "cm^-1"),
                          "optimization": _absent(unavailable), "sampling": _absent(unavailable),
                          "thermochemistry": _absent("thermochemistry-unavailable", "hartree")},
                "availability": "unavailable" if successor or conflict else "missing",
                "reason": reason or unavailable, "provenance": None, "history": gaussian["history"]}
        if conflict:
            data["reason"] = reason
            return data
        if successor:
            registrations = [s for s in self._sources[source_id].snapshots if s.attempt_id == attempt_id]
            if not registrations:
                data["reason"] = "native-snapshot-not-registered"
                return data
            try:
                native = ProgramReadQuery(store).get_summary(registrations[0])
            except (ValueError, KeyError, TypeError, StopIteration, AttributeError):
                data["reason"] = "native-evidence-mismatch"
                return data
            _evidence_id(native["bound_plan"]["id"])
            attribution = "Execution:" + _evidence_id(native["snapshot_id"])
            data.update(availability="available", reason=None, provenance=native)
            data["program"] = _fact(native["program"], attribution)
            data["bound_plan"] = _fact(native["bound_plan"], attribution)
            data["input"] = _fact(native["inputs"], attribution)
            data["artifacts"] = _fact(native["artifacts"], attribution)
            data["axes"]["capture"] = (_fact(native["capture"], attribution) if native["capture"] else _absent("capture-not-recorded", unavailable=False))
            unknown = native["scientific_facts"] != "not-recorded"
            data["facts"] = {key: field if key == "thermochemistry" else _absent("unsupported-native-result-contract" if unknown else "parsed-native-fact-not-recorded", field["unit"], unavailable=unknown) for key, field in data["facts"].items()}
            readout = self._sources[source_id].freq_readout or self._sources[source_id].opt_readout
            if readout is not None:
                try:
                    facts = readout.read(store, attempt_id)
                except OptReadBusy:
                    raise QueryError("store-unavailable") from None
                for key, unit in (("energy", "hartree"), ("geometry", "angstrom"),
                                  ("frequencies", "cm^-1"), ("optimization", None)):
                    value = facts[key]
                    data["facts"][key] = (_fact(value, facts['source'], unit)
                        if value is not None and value != [] else
                        _absent(key + "-not-recorded", unit, unavailable=False))
                if type(readout) is FreqReadout:
                    thermo = facts["thermochemistry"]
                    if thermo is not None:
                        data["facts"]["thermochemistry"] = (_fact(thermo, facts["source"], "hartree") if thermo else
                            _absent("thermochemistry-not-recorded", "hartree", unavailable=False))
                data["facts"]["sampling"] = _absent("not-a-sampling-result")
                data["axes"]["validation"] = _fact(facts['assessment'], "Conformer:Opt-Freq-source-replay" if type(readout) is FreqReadout else "Conformer:Opt-source-replay")
                data["provenance"] = {**native, "parsed_result": facts['provenance']}
            return data
        source = gaussian["source"]
        if source:
            data["provenance"] = source
            data["bound_plan"] = _fact({"id": source["calculation_plan_id"],
                "revision": source["calculation_plan_revision"]}, "Result.InputBinding")
            data["input"] = _fact(source["input"], "Result.InputBinding")
            data["artifacts"] = _fact(source["outputs"], "Result.OutputEnvelope")
            if source["envelope_id"]:
                data["axes"]["capture"] = _fact({"status": source["capture_status"],
                    "completeness": source["capture_completeness"]}, "Result.OutputEnvelope")
        if gaussian["availability"] != "available":
            return data
        view = ResultProvenanceService(store).current_view(attempt_id)
        if len(view.selected_results) != 1:
            data.update(availability="unavailable", reason="multiple-result-interpretations")
            return data
        outcome = view.selected_results[0]
        plan = store.load_calculation_plan(view.input_binding.calculation_plan_id)
        if plan.intent.get("program") not in (None, "gaussian"):
            data.update(availability="unavailable", reason="program-plan-conflict")
            return data
        facts = outcome.facts
        attribution = "Result:" + outcome.result_id
        data["program"] = _fact("gaussian", attribution)
        data["availability"], data["reason"] = "available", None
        energy = facts["final_energy_hartree"]
        data["facts"]["energy"] = (_fact(energy, attribution, "hartree") if energy is not None else
                                     _absent("energy-not-recorded", "hartree", unavailable=False))
        # Preserve every attributed geometry block and source span. No scientific selection.
        data["facts"]["geometry"] = (_fact(facts["geometry_blocks"], attribution, "angstrom") if facts["geometry_blocks"] else
                                       _absent("geometry-not-recorded", "angstrom", unavailable=False))
        data["facts"]["frequencies"] = (_fact(facts["frequency_blocks"], attribution, "cm^-1") if facts["frequency_count"] else
                                          _absent("frequency-not-recorded", "cm^-1", unavailable=False))
        data["facts"]["optimization"] = _fact(gaussian["summary"]["optimization"], attribution)
        data["facts"]["sampling"] = _absent("not-a-sampling-result")
        return data

    def list_sources(self):
        return self._dto("sources", {"items": [{"source_id": source_id, "origin": "native-core"}
                                                   for source_id in self._sources]})

    def list_projects(self):
        items, sources = [], []
        for source_id in self._sources:
            try:
                def read(store):
                    return {"items": [{"source_id": source_id, "origin": "native-core",
                                       "project_id": _evidence_id(project.project_id),
                                       "workflow_run_ids": [_evidence_id(run.workflow_run_id) for run in store.list_workflow_runs(project.project_id)]}
                                      for project in store.list_projects()]}
                items.extend(self._read(source_id, read)["items"])
                sources.append({"source_id": source_id, "availability": "available", "reason": None})
            except QueryError as error:
                sources.append({"source_id": source_id, "availability": "unavailable", "reason": error.code})
        counts = Counter(item["project_id"] for item in items)
        for item in items:
            item["identity_collision"] = counts[item["project_id"]] > 1
        return self._dto("projects", {"items": items, "sources": sources,
                                       "consistency": "independent-source-snapshots"})

    def list_attempts(self, source_id, project_id):
        _identifier(project_id)
        def read(store):
            return {"items": [self._attempt(store, source_id, attempt.attempt_id)
                              for run in store.list_workflow_runs(project_id)
                              for task in store.list_tasks(run.workflow_run_id)
                              for attempt in store.list_attempts(task.task_id)]}
        return self._dto("attempts", self._read(source_id, read))

    def get_attempt(self, source_id, attempt_id):
        _identifier(attempt_id)
        return self._dto("attempt", self._read(source_id,
                         lambda store: self._attempt(store, source_id, attempt_id)))

    def get_thermodynamics(self, source_id, attempt_id):
        """Separate saved-result query; never reads through the old detail view."""
        _identifier(attempt_id)
        _identifier(source_id)
        if source_id not in self._sources:
            raise QueryError('not-found')
        source = self._sources[source_id]
        reader = source.thermodynamic_readout
        data = dict(availability='unavailable', reason='not-registered', source_id=source_id,
                    attempt_id=attempt_id, selected_member_id=None, result=None)
        try:
            if reader is None:
                # Only confirm membership; no result inventory or scientific read.
                self._read(source_id, lambda store: store.load_attempt(attempt_id))
            else:
                if len(source.snapshots) != 1 or source.snapshots[0].attempt_id != attempt_id:
                    raise QueryError('not-found')
                selected = reader.readout.source_for(attempt_id)
                pair = reader.read()
                # All reader locks, pins and source exit checks have completed.
                result = _thermodynamics_result(reader, pair, selected.member_id)
                data.update(availability='available', reason=None,
                            selected_member_id=_evidence_id(selected.member_id), result=result)
        except Exception as error:
            raise QueryError(_thermodynamics_error(error)) from None
        return dict(schema=NATIVE_THERMODYNAMICS_SCHEMA, kind='thermodynamics', data=data)
