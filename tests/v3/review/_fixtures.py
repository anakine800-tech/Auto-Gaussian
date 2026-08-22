"""Synthetic persisted authority chains for ReviewBundle tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile

from auto_g16.core import (
    Attempt,
    CalculationPlan,
    Project,
    SQLiteRuntimeStore,
    Task,
    WorkflowRun,
)
from auto_g16.result import (
    InputBinding,
    OutputArtifact,
    OutputEnvelope,
    ParseOutcome,
    ResultProvenanceService,
)
from auto_g16.scientific_validation import (
    MinimumValidationOutcome,
    SQLiteScientificValidationStore,
    ScientificAcceptance,
    record_minimum_validation,
    record_scientific_acceptance,
    validate_minimum,
)
from tests.v3.scientific_validation._fixtures import attributed_facts


@dataclass
class ReviewAuthority:
    temporary: tempfile.TemporaryDirectory[str]
    core_path: Path
    validation_path: Path
    core: SQLiteRuntimeStore
    validation: SQLiteScientificValidationStore
    input_binding: InputBinding
    output_envelope: OutputEnvelope
    parse_outcome: ParseOutcome
    outcome: MinimumValidationOutcome

    def close(self) -> None:
        self.validation.close()
        self.core.close()
        self.temporary.cleanup()

    def accept(
        self,
        reviewer_id: str,
        *,
        evidence: dict[str, object] | None = None,
    ) -> ScientificAcceptance:
        return record_scientific_acceptance(
            self.validation,
            minimum_validation_outcome_id=self.outcome.minimum_validation_outcome_id,
            reviewer_id=reviewer_id,
            review_evidence={"decision": "accept"} if evidence is None else evidence,
        )


def authority(**facts_options: object) -> ReviewAuthority:
    temporary = tempfile.TemporaryDirectory()
    core_path = Path(temporary.name) / "core.sqlite3"
    validation_path = Path(temporary.name) / "scientific-validation.sqlite3"
    core = SQLiteRuntimeStore(core_path)
    core.store_project(Project(project_id="project-1"))
    core.store_workflow_run(
        WorkflowRun(
            workflow_run_id="run-1",
            project_id="project-1",
            workflow_name="review-fixture",
        )
    )
    core.store_task(
        Task(task_id="task-1", workflow_run_id="run-1", task_kind="gaussian")
    )
    core.store_calculation_plan(
        CalculationPlan(
            calculation_plan_id="plan-1",
            task_id="task-1",
            revision=1,
            intent={"operation": "opt-freq"},
        )
    )
    core.create_attempt(Attempt(attempt_id="attempt-1", task_id="task-1", ordinal=1))
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
        capture_completeness="complete",
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
    parse_outcome = ParseOutcome(
        attempt_id="attempt-1",
        envelope_observation_id=envelope.observation_id,
        parser_name="auto-g16-v3-gaussian-job",
        parser_version="1.0.0",
        result_kind="gaussian-job-facts",
        parse_status="parsed",
        facts=attributed_facts(envelope, **facts_options),
    )
    service = ResultProvenanceService(core)
    service.record_input_binding(binding)
    service.record_output_envelope(envelope)
    service.record_parse_outcome(parse_outcome)
    validation = SQLiteScientificValidationStore.create_new(
        validation_path
    )
    outcome = record_minimum_validation(
        validation,
        validate_minimum(core, binding, envelope, parse_outcome),
    )
    return ReviewAuthority(
        temporary=temporary,
        core_path=core_path,
        validation_path=validation_path,
        core=core,
        validation=validation,
        input_binding=binding,
        output_envelope=envelope,
        parse_outcome=parse_outcome,
        outcome=outcome,
    )
