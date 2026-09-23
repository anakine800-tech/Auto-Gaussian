# Auto-G16 v3 boundary: foundation

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:6-128 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## Dependency Direction

```text
Skills -> Workflow -> Approval / Execution / Result -> Core
Skills -> ScientificValidation -> Result -> Core
Skills -> Review -> ScientificValidation / Result -> Core
```

Skills compose workflows. Workflow may depend only on public Approval,
Execution, Result, and Core surfaces; those layers must not import Workflow.
ScientificValidation may depend only on public Result and Core surfaces; Core,
Result, Approval, Execution, and Workflow must not import it. Core must not
depend on a Skill or any higher layer. Reverse imports across these directions
are forbidden.

Review may depend only on public ScientificValidation, Result, and Core
surfaces. It may carry the exact ExecutionSnapshot identity already closed by
InputBinding and OutputEnvelope, but it does not import Execution or reconstruct
a snapshot. Core, Result, ScientificValidation, Approval, Execution, and
Workflow must not import Review.

The V30-A Controller is an application composition role, not a new public
package or authority layer. The future `auto_g16.transport` package may depend
only on public Execution records/ports and standard-library facilities. It
does not import Observe, Result, ScientificValidation, or Review. The
Controller translates transport read evidence into those layers through their
existing public APIs; no upstream package imports Transport.

## Core Objects

- `Project`: durable workspace identity and collection boundary.
- `WorkflowRun`: one invocation of a reviewed workflow definition.
- `Batch`: a related set of tasks scheduled or reviewed together.
- `Task`: one planned unit of work within a workflow.
- `Attempt`: one no-overwrite execution instance for a task.
- `CalculationPlan`: the current semantically reviewed calculation intent.
- `ResourceSpec`: requested compute resources, separate from scientific intent.
- `Observation`: typed evidence about execution or program state.
- `Result`: parsed output presented for scientific review.
- `RecoveryProposal`: a proposal for a new reviewed action, never an automatic
  retry instruction.

## V30-CORE-01 Runtime Contract

V30-CORE-01 introduces the dependency-free Python package `auto_g16.core`.
`auto_g16.core` is the public import surface for Core consumers; adapters do
not import private helpers from `models.py` or `store.py`. The package exports
immutable, keyword-only value records. Domain-record construction may validate
only the value being constructed; it must not read a repository, allocate an
identity, infer a relationship, or perform filesystem, process, network,
transport, scheduler, or program activity.

Identifiers and descriptive discriminators are opaque, case-sensitive strings.
They must be non-empty, contain no leading or trailing whitespace, and are
never generated or rewritten by Core. Revisions and attempt ordinals are
positive integers; booleans are not integers for this contract. Optional
references use `None`, never an empty-string sentinel.

The public records and their exact fields are:

| Record | Fields |
| --- | --- |
| `Project` | `project_id` |
| `WorkflowRun` | `workflow_run_id`, `project_id`, `workflow_name` |
| `Batch` | `batch_id`, `workflow_run_id`, `purpose` |
| `Task` | `task_id`, `workflow_run_id`, `task_kind`, optional `batch_id` |
| `Attempt` | `attempt_id`, `task_id`, positive `ordinal` |
| `CalculationPlan` | `calculation_plan_id`, `task_id`, positive `revision`, canonical `intent` |
| `ResourceSpec` | `resource_spec_id`, `task_id`, canonical `resources` |
| `Observation` | `observation_id`, `attempt_id`, `observation_type`, canonical `data` |
| `Result` | `result_id`, `attempt_id`, `result_type`, canonical `data` |
| `RecoveryProposal` | `recovery_proposal_id`, `attempt_id`, `reason`, `proposed_calculation_plan_id` |

Canonical payloads accept mappings with string keys and recursively accept only
`None`, booleans, integers, finite floats, strings, mappings, lists, and tuples.
Core snapshots them behind a deeply immutable semantic mapping view so later
mutation of caller-owned containers cannot change a record. Public constructor
annotations and runtime payload values expose only mappings, immutable
sequences, and the accepted semantic scalar values; they never expose a private
record type or tagged encoding. Unsupported values, non-string keys, and
non-finite floats fail closed with `CoreValidationError`. The canonical tagged
comparison and SQLite encodings are private implementation details, not public
symbols or compatibility contracts.

Object references are stored as identifiers rather than nested private runtime
objects. Core preserves a supplied reference exactly and does not claim that the
referenced object exists during value-record construction. The runtime store
owns cross-object existence, lifecycle transitions, a single root Attempt per
Task, unique attempt ordinals, and durable no-overwrite allocation.

`CalculationPlan` records current semantic intent and its revision. It does not
grant approval. `ResourceSpec` remains separate from scientific intent.
`RecoveryProposal` is passive data and cannot trigger a retry or execution.

V30-CORE-01 deliberately excludes `ExecutionSnapshot`, public serialization
formats, controller services, approval and semantic-diff workflows, transport,
program adapters, and any v2 runtime ABI. No symbol named `ExecutionSnapshot`
is part of `auto_g16.core`.

SQLite persistence and the Attempt lifecycle are Core-owned local services;
they do not authorize or perform transport, submission, scheduler observation,
program execution, retry, cleanup, or scientific acceptance. The complete
state, transaction, replay, reconciliation, child-Attempt, and persistence
contract is the V30-CORE-01 section of `acceptance.md`.

The submission-intent transaction returns a distinct claim result: exactly one
caller can receive `WINNER` for a globally unique intent identity, while exact
idempotent replay receives `REPLAY`. Only `WINNER` is a claim signal; neither
result permits implicit truth-value use, and neither performs or authorizes
transport or submission. An UNKNOWN Attempt stays the Task's root until
persisted Observation evidence reconciles that same Attempt; creating another
root is not a recovery path.

SQLite schema version 1 is the current runtime persistence contract.
Exactly-once submission claim, persisted Observation-based UNKNOWN
reconciliation, and one root Attempt per Task are Core invariants. The tagged
canonical representation and SQL construction details remain private
implementation details.

Any future change to the `auto_g16.core` exports, public record fields,
constructor or store method contracts, enum or error names, or schema-v1 Core
invariants requires a new Core boundary review before integration.

<!-- Moved from docs/v3/boundary-spec.md:4293-4316 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## Context Boundaries

- **Scientific:** scientific intent, method-specific review, and acceptance.
- **Workflow:** ordering, dependencies, and stage-specific stop conditions.
- **Execution Safety:** attempt allocation, no-overwrite, submission limits,
  uncertainty, and reconciliation.
- **Transport:** bounded movement and remote invocation primitives; no
  scientific policy.
- **Program Adapter:** program-specific input, invocation, and output parsing.
- **Knowledge:** reusable typed scientific and source records.
- **Runtime State:** current projects, runs, tasks, attempts, observations, and
  results.
- **Observe:** exact-Attempt read-only source observations and deterministic
  projections; no execution, retry, diagnosis, or scientific authority.

Contexts exchange typed canonical data. A context must not pass private
implementation objects across a boundary as an implicit contract.

## Artifact Identity

Use hashes where artifact identity must be recorded. A hash is not the default
authority mechanism and does not replace semantic review of the current
`CalculationPlan`.
