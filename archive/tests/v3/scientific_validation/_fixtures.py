"""Synthetic attributed Result fixtures; no Gaussian bytes are read."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from auto_g16.core import (
    Attempt,
    CalculationPlan,
    Project,
    Result,
    SQLiteRuntimeStore,
    Task,
    WorkflowRun,
)
from auto_g16.result import (
    PARSED_RESULT_TYPE,
    CaptureCompleteness,
    InputBinding,
    OutputArtifact,
    OutputEnvelope,
    ParseOutcome,
    ParseStatus,
    ResultProvenanceService,
)


def _source(envelope: OutputEnvelope) -> dict[str, object]:
    artifact = envelope.artifacts[0]
    return {
        "envelope_observation_id": envelope.observation_id,
        "artifact_kind": artifact.artifact_kind,
        "logical_name": artifact.logical_name,
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _span(source: Mapping[str, object], start: int, end: int) -> dict[str, object]:
    return {**source, "start": start, "end": end}


def atom(center: int, atomic_number: int = 1) -> dict[str, object]:
    return {
        "center": center,
        "atomic_number": atomic_number,
        "x": float(center),
        "y": 0.0,
        "z": 0.0,
    }


def initialized_core() -> SQLiteRuntimeStore:
    store = SQLiteRuntimeStore(":memory:")
    store.store_project(Project(project_id="project-1"))
    store.store_workflow_run(
        WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="scientific-validation-fixture",
        )
    )
    store.store_task(
        Task(task_id="task-1", workflow_run_id="run-1", task_kind="gaussian")
    )
    store.store_calculation_plan(
        CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent={"operation": "opt-freq"},
        )
    )
    store.create_attempt(Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
    return store


def attributed_facts(
    envelope: OutputEnvelope,
    *,
    frequencies: Sequence[float] = (100.0, 200.0, 300.0),
    atom_numbers: Sequence[int] = (8, 1, 1),
    program_status: str = "normal-termination",
    optimization_spans: Sequence[tuple[int, int]] = ((100, 110),),
    stationary_spans: Sequence[tuple[int, int]] = ((120, 130),),
    geometry_specs: Sequence[tuple[int, int, Sequence[int]]] | None = None,
    frequency_specs: Sequence[tuple[int, int, Sequence[float]]] | None = None,
    grammar_id: str = "auto-g16-v3-gaussian-job-grammar/1",
    terminal_specs: Sequence[tuple[str, int, int]] | None = None,
    source_changes: Mapping[str, object] | None = None,
) -> dict[str, object]:
    source = _source(envelope)
    if source_changes:
        source.update(source_changes)
    geometries = (
        ((10, 60, atom_numbers),)
        if geometry_specs is None
        else tuple(geometry_specs)
    )
    if frequency_specs is None:
        groups = tuple(
            tuple(frequencies[index : index + 3])
            for index in range(0, len(frequencies), 3)
        )
        blocks = tuple(
            (140 + index * 20, 150 + index * 20, group)
            for index, group in enumerate(groups)
        )
    else:
        blocks = tuple(frequency_specs)
    all_frequencies = tuple(float(item) for _start, _end, group in blocks for item in group)
    terminals = (
        ((program_status, 880, 900),)
        if terminal_specs is None
        else tuple(terminal_specs)
    )
    normal_count = sum(kind == "normal-termination" for kind, _start, _end in terminals)
    error_count = sum(kind == "error-termination" for kind, _start, _end in terminals)
    return {
        "facts_schema_version": 1,
        "grammar_id": grammar_id,
        "source_artifact": source,
        "job_section": _span(source, 0, 900),
        "program_status": program_status,
        "normal_termination_count": normal_count,
        "error_termination_count": error_count,
        "termination_evidence": tuple(
            {"kind": kind, "source_span": _span(source, start, end)}
            for kind, start, end in terminals
        ),
        "optimization_completed_marker": bool(optimization_spans),
        "optimization_completed_evidence": tuple(
            _span(source, start, end) for start, end in optimization_spans
        ),
        "stationary_point_marker": bool(stationary_spans),
        "stationary_point_evidence": tuple(
            _span(source, start, end) for start, end in stationary_spans
        ),
        "scf_calculation_count": 0,
        "scf_calculations": (),
        "final_energy_hartree": None,
        "frequency_count": len(all_frequencies),
        "frequency_parse_complete": True,
        "imaginary_frequency_count": sum(item < 0.0 for item in all_frequencies),
        "frequencies_cm-1": all_frequencies,
        "frequency_blocks": tuple(
            {
                "source_span": _span(source, start, end),
                "frequencies_cm-1": tuple(float(item) for item in group),
            }
            for start, end, group in blocks
        ),
        "thermochemistry": {},
        "geometry_blocks": tuple(
            {
                "orientation_kind": "standard-orientation",
                "units": "angstrom",
                "source_span": _span(source, start, end),
                "atoms": tuple(
                    atom(index, atomic_number)
                    for index, atomic_number in enumerate(numbers, start=1)
                ),
            }
            for start, end, numbers in geometries
        ),
    }


def stored_chain(
    *,
    completeness: CaptureCompleteness = CaptureCompleteness.COMPLETE,
    parser_name: str = "auto-g16-v3-gaussian-job",
    parser_version: str = "1.0.0",
    result_kind: str = "gaussian-job-facts",
    parse_status: ParseStatus = ParseStatus.PARSED,
    diagnostics: tuple[str, ...] = (),
    facts_options: Mapping[str, object] | None = None,
    bypass_result_service: bool = False,
) -> tuple[SQLiteRuntimeStore, InputBinding, OutputEnvelope, ParseOutcome]:
    core = initialized_core()
    binding = InputBinding(
        attempt_id="attempt-1",
        calculation_plan_id="plan-1",
        calculation_plan_revision=1,
        prepared_input_binding_id="prepared-1",
        execution_snapshot_id="snapshot-1",
        input_format="gaussian-gjf",
        logical_name="job.gjf",
        sha256="a" * 64,
        size_bytes=100,
    )
    envelope = OutputEnvelope(
        attempt_id="attempt-1",
        input_binding_observation_id=binding.observation_id,
        execution_snapshot_id="snapshot-1",
        capture_source_id="capture-1",
        capture_sequence=1,
        capture_status="captured",
        capture_completeness=completeness,
        artifacts=(
            OutputArtifact(
                artifact_kind="gaussian-log",
                logical_name="job.log",
                sha256="b" * 64,
                size_bytes=1000,
            ),
        ),
        capture_manifest_sha256="c" * 64,
        captured_at_utc="2026-08-22T00:00:00Z",
    )
    if parse_status is ParseStatus.PARSED and result_kind == "gaussian-job-facts":
        options = {} if facts_options is None else dict(facts_options)
        options.setdefault(
            "grammar_id",
            "auto-g16-v3-gaussian-job-grammar/2"
            if parser_version == "1.1.0"
            else "auto-g16-v3-gaussian-job-grammar/1",
        )
        facts = attributed_facts(envelope, **options)
    else:
        facts = {}
    outcome = ParseOutcome(
        attempt_id="attempt-1",
        envelope_observation_id=envelope.observation_id,
        parser_name=parser_name,
        parser_version=parser_version,
        result_kind=result_kind,
        parse_status=parse_status,
        facts=facts,
        diagnostics=diagnostics,
    )
    service = ResultProvenanceService(core)
    service.record_input_binding(binding)
    service.record_output_envelope(envelope)
    if bypass_result_service:
        core.append_result(
            Result(
                result_id=outcome.result_id,
                attempt_id=outcome.attempt_id,
                result_type=PARSED_RESULT_TYPE,
                data=outcome.payload(),
            )
        )
    else:
        service.record_parse_outcome(outcome)
    return core, binding, envelope, outcome
