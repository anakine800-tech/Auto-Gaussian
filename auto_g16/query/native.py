"""Source-scoped read-only inventory and owned facts; no private runtime decoding."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
import re
from hashlib import sha256
from typing import Callable

from auto_g16.conformer.readonly import OptReadout, OptReadBusy
from auto_g16.execution.readonly import ProgramReadSnapshot, ProgramReadQuery
from auto_g16.result import (GaussianResultQuery, ResultProvenanceService,
    INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION, PARSED_RESULT_TYPE)
from .models import QueryError
from .service import QueryService, _field, _missing

NATIVE_QUERY_SCHEMA = "auto-g16-native-query/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_SUCCESSOR = frozenset({"program-completion-evidence/1", "v31-program-effect-receipt/1",
                        "program-completion-assessment/1", "auto-g16-v31-collection-start/1"})
_KNOWN = _SUCCESSOR | {INPUT_BINDING_OBSERVATION, OUTPUT_ENVELOPE_OBSERVATION,
                       PARSED_RESULT_TYPE, "v3.remote-effect-receipt", "auto-g16-v3-attempt-observation",
                       "v31-gaussian-result-source/1", "v31-gaussian-parsed-result/1"}


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


@dataclass(frozen=True, kw_only=True)
class NativeSource:
    """Trusted startup registration. Paths are never accepted from an HTTP request."""
    source_id: str
    database: Path = field(repr=False)
    snapshots: tuple[ProgramReadSnapshot, ...] = field(default=(), repr=False)
    opt_readout: OptReadout | None = field(default=None, repr=False)

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
        if self.opt_readout is not None:
            if type(self.opt_readout) is not OptReadout or len(self.snapshots) != 1:
                raise QueryError("invalid-opt-registration")
            selected = self.opt_readout.source_for(self.snapshots[0].attempt_id)
            if selected.revision.path != str(path) or selected.snapshot != self.snapshots[0]:
                raise QueryError("invalid-opt-registration")


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
                          "optimization": _absent(unavailable), "sampling": _absent(unavailable)},
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
            data["facts"] = {key: _absent("unsupported-native-result-contract" if unknown else "parsed-native-fact-not-recorded", field["unit"], unavailable=unknown) for key, field in data["facts"].items()}
            readout = self._sources[source_id].opt_readout
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
                data["facts"]["sampling"] = _absent("not-a-sampling-result")
                data["axes"]["validation"] = _fact(facts['assessment'], "Conformer:Opt-source-replay")
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
