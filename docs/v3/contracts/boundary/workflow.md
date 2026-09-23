# Auto-G16 v3 boundary: workflow

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:2114-2350 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-WF-CONTRACT-01 Frozen Minimal Workflow Contract

**Contract status: FROZEN; IMPLEMENTATION NOT AUTHORIZED.** The public package
is `auto_g16.workflow`, with focused tests under `tests/v3/workflow/`. This
contract defines V30-4 only. It changes no Core, Approval, Execution, or Result
API or schema; grants no Transport, PBS, Gaussian, deployment, or live
authority; and does not activate `V30-EXEC-02`.

### Package and public record boundary

`auto_g16.workflow` owns deterministic orchestration data and read-only run
projection. Its public value records are immutable, keyword-only, and deeply
closed over canonical semantic values. `Node.node_id`, `Edge.edge_id`,
`Map.map_id`, `Condition.condition_id`, and `HumanGate.human_gate_id` are local
canonical identifiers scoped to one exact `WorkflowDefinition`. Each is
non-empty, immutable inside that definition, and unique within its component
namespace; all intra-definition references use them. These five identifiers
are not complete-payload UUIDv5 identities. A local component identifier alone
grants no cross-definition identity, persistence equivalence, authority, or
effect.

`WorkflowDefinition.workflow_definition_id` is UUIDv5 from a
source-controlled, schema-versioned, domain-separated namespace over the
complete canonical WorkflowDefinition payload, including every local
identifier and the complete semantics of every component. Reusing a local
identifier with changed component semantics therefore changes the definition
identity. `ConditionDecision` and `HumanGateDecision` use separate
schema-versioned, domain-separated deterministic UUIDv5 identities binding the
exact WorkflowDefinition identity, frozen Core/run identities, referenced
local component identifier, and complete decision payload. Exact replay of
each definition or decision authority record has the same identity; the same
authority identity with different content conflicts. No circular component
identity computation is permitted: in particular, `Edge.condition_id` and a
Condition's true/false Edge IDs are ordinary intra-definition references
inside the single definition payload.
`WorkflowEvaluationInput` and the derived `WorkflowRunView` are canonical value
records without independent authority IDs. Timestamps, serialization
formatting, file paths, and hashes that are not explicit semantic fields do not
decide Workflow authority.

The frozen public record inventory and fields are:

| Record | Fields |
| --- | --- |
| `Node` | `node_id`, `task_id`, `calculation_plan_id`, positive `calculation_plan_revision`, `node_kind`, canonical finite `input_roles`, canonical finite `output_roles` |
| `Edge` | `edge_id`, `source_node_id`, `source_output_role`, `target_node_id`, `target_input_role`, optional `condition_id`, `branch` (`always`, `true`, or `false`) |
| `Map` | `map_id`, `source_node_id`, `source_output_role`, canonical finite `items`; every item is the closed tuple `(item_key, target_node_id, target_input_role)` |
| `Condition` | `condition_id`, `source_node_id`, fixed `predicate = attempt_state_in`, canonical non-empty terminal `expected_states`, canonical `true_edge_ids`, canonical `false_edge_ids` |
| `HumanGate` | `human_gate_id`, canonical non-empty `target_node_ids`, `prompt` |
| `WorkflowDefinition` | `schema_version`, `workflow_definition_id`, `workflow_run_id`, `workflow_name`, canonical tuples of all `Node`, `Edge`, `Map`, `Condition`, and `HumanGate` records |
| `WorkflowEvaluationInput` | `workflow_definition_id`, canonical finite `node_attempt_ids` mapping; an omitted node has no allocated Attempt |
| `ConditionDecision` | `condition_decision_id`, `workflow_definition_id`, `workflow_run_id`, `condition_id`, `node_id`, `attempt_id`, exact terminal `observed_state`, canonical `selected_edge_ids` |
| `HumanGateDecision` | `human_gate_decision_id`, `workflow_definition_id`, `workflow_run_id`, `human_gate_id`, `decision`, `reviewer_id`, canonical `review_evidence` |
| `WorkflowRunView` | `workflow_definition_id`, `workflow_run_id`, canonical active, ready, pending, blocked, and terminal node IDs, exact decision IDs, and `run_outcome` (`pending`, `active`, `blocked`, or `completed`) |

`node_kind` is an opaque orchestration discriminator. It is not a Gaussian,
CREST, xTB, PBS, TS, IRC, thermochemistry, or scientific-acceptance policy.
Input and output roles are typed names only; Workflow never interprets their
scientific or program-specific payloads.

The frozen public behavior is exposed through `record_workflow_definition`,
`validate_workflow_definition`, `record_condition_decision`,
`record_human_gate_decision`, and `replay_workflow`, plus the minimal opaque
`SQLiteWorkflowStore`. The store's only public lifecycle methods are
`create_new(path)`, `open_existing(path)`, and `close()`; SQL and raw row access
remain private. `record_workflow_definition(store, core_store, definition)`
validates all public Core bindings before append. Condition recording receives
the store, public Core store, exact definition ID, evaluation input, and
condition ID and derives the decision from current Core state. HumanGate
recording receives the store, exact definition ID, gate ID, explicit decision,
reviewer, and canonical evidence. Replay receives the store, public Core store,
exact definition ID, and evaluation input and returns the derived view. None of
these functions accepts an adapter or effect callback. There is no public
plugin, shell, code-evaluation, submit, execute, retry, cancel, or cleanup API.

### Finite graph, mapping, and branch semantics

A `WorkflowDefinition` binds one exact existing Core `WorkflowRun`. Every Node
binds one exact existing Core `Task` in that run and one exact existing
`CalculationPlan` ID and positive revision for that Task. The definition never
asks Core to enumerate Tasks or infer a current plan revision: all identities
are explicit and validated through existing public Core loads.

Node IDs, Edge IDs, Map IDs, Condition IDs, HumanGate IDs, role names, and map
item keys are non-empty and unique in their owning scope. Component IDs are
immutable inside the exact definition. Every referenced node, edge, role,
condition, and gate must exist exactly once. A target input role has one
producer on any active path. Missing, self, duplicate, ambiguous-producer,
role-incompatible, or orphan references fail closed.

Every possible unconditional or conditional Edge and every Map item's
`source_node_id -> target_node_id` dependency belongs to one finite graph. That
combined graph must be acyclic; map-only cycles and cycles formed by a mixture
of Edge and Map dependencies fail closed. Topological order and readiness use
that same combined graph and a stable lexical tie-break, so caller order never
changes either result. A `Map` is only a finite, explicitly enumerated fan-out
from one source role to already declared target Nodes. It cannot discover
inputs, create Nodes or Tasks, evaluate code, or expand after the definition is
frozen.

V30-4 has one Condition predicate: membership of the source Node's exact bound
Attempt state in a declared non-empty subset of Core terminal states
`SUCCEEDED`, `FAILED`, and `NOT_SUBMITTED`. A condition can select only its
predeclared true or false edges. It is recorded only against an exact supplied
Attempt that belongs to the source Node's Task and whose public Core state is
the recorded terminal state. `UNKNOWN`, running, missing, cross-Task, or stale
Attempt evidence cannot produce a branch decision.

Edge and Condition branch metadata are one closed relation, not competing
authorities. `branch = always` requires `condition_id = None` and the Edge must
occur in no Condition tuple. `branch = true` or `false` requires one exact
`condition_id` and membership only in that Condition's corresponding
`true_edge_ids` or `false_edge_ids`. The two tuples are canonical, disjoint,
and together enumerate every conditional Edge exactly once. When the observed
state belongs to `expected_states`, `ConditionDecision.selected_edge_ids` is
the complete canonical `true_edge_ids`; otherwise it is the complete canonical
`false_edge_ids`. A caller cannot omit, add, reorder, or cross-splice selected
Edges.

A HumanGate decision is `approved` or `rejected`, binds the exact definition
and gate, and is append-only. HumanGate target sets are globally disjoint, so a
Node has at most one Workflow gate; overlap fails definition validation. A gate
is only a conjunctive filter on a Node already active through the graph and
branch projection. For an active target, a missing decision leaves the Node
pending, `rejected` blocks it, and `approved` removes only that gate filter. A
decision for an inactive target never activates the Node or changes another
path's readiness or outcome. A Workflow HumanGate is never Scientific
Approval, Batch Submit Approval, Exact Operational Confirmation, or scientific
acceptance.

### Canonical state, persistence, and replay

The immutable `WorkflowDefinition` and append-only `ConditionDecision` and
`HumanGateDecision` records are canonical Workflow-owned state. They persist
in a Workflow-owned SQLite schema version 1, separate from Core and Approval
databases. The SQL layout is private, but fresh-schema identity, exact closed
record decoding, deterministic insertion order, durable reopen, no implicit
migration, exact replay idempotency, same-identity conflict, and no
update/delete semantics are public acceptance requirements.

`SQLiteWorkflowStore.create_new(path)` fails if the target already exists;
`open_existing(path)` fails if it is missing or is not the exact schema version
1 store. Neither operation repairs, migrates, deletes, replaces, or silently
initializes an existing database. Public record/replay functions are the only
semantic access path and reject malformed, extra, conflicting, or cross-domain
records before using them as Workflow state.

`WorkflowRunView` is not stored as mutable truth. `replay_workflow` derives it
from the exact immutable definition, exact persisted decisions, explicit
`WorkflowEvaluationInput`, and public Core records. Reopening with those same
inputs produces the same view. A decision from another definition, run, node,
gate, condition, Task, or Attempt is rejected rather than spliced.

There is at most one ConditionDecision for an exact definition, condition, and
source Attempt, and at most one HumanGateDecision for an exact definition and
gate. Exact replay is idempotent; a second different decision for either
authority key conflicts. The store never resolves competing branch or human
decisions by insertion order.

The explicit node-to-Attempt mapping closes the absence of a public Core list
API. Every supplied Attempt must exist and belong to the exact Node Task; no
Attempt may be discovered, selected, created, replaced, or retried because a
Node exists. A Node without an Attempt may become `ready`, which is only a
proposal for a separately gated Controller action. A Node with an Attempt
reflects the public Core state; Workflow never writes or overrides that state.

Active roots are Nodes with no incoming dependency in the combined Edge/Map
graph. An unconditional Edge or Map dependency is active when its source Node
is active; a conditional Edge is active only when the exact persisted
ConditionDecision selects it. Reachability through those active dependencies
derives the active Node set; an inactive Node cannot become active through an
Attempt binding or HumanGate decision. A no-Attempt active Node is `ready` only
when every active unconditional/Map predecessor is exactly `SUCCEEDED`, every
active conditional predecessor has its exact terminal decision, every declared
input role has exactly one active producer, and its optional HumanGate is
approved. Missing branch or gate decisions remain pending; rejected gates,
failed always/Map predecessors, producer gaps, and `UNKNOWN` block rather than
grant readiness.

An active run is `completed` only when every active Node has an exact terminal
Core outcome and every required branch and HumanGate decision closes. This
means orchestration is exhausted, not that any structure, calculation, result,
minimum, TS, IRC, or scientific conclusion is accepted. Missing evidence,
rejected gates, and `UNKNOWN` remain explicit blocked states.

`pending` means the exact definition is valid but required upstream inputs or
decisions are not yet available; `active` means at least one active Node is
ready or has a nonterminal exact Attempt; `blocked` means no legal progress is
available because a required gate was rejected or exact failure/`UNKNOWN`
evidence stops the path; `completed` has the closed meaning above. The result
is derived deterministically, never caller-selected.

### Authority and failure boundaries

Workflow may validate or compose public Approval, Execution, Result, and Core
records, but it never owns their meaning. In particular:

- Node readiness, a branch decision, a Map, and a HumanGate each grant zero
  Core transition and zero filesystem, transport, scheduler, PBS, or Gaussian
  effect.
- Workflow never creates a root or recovery-child Attempt, changes a
  CalculationPlan, chooses resources, resolves an `ExecutionSnapshot`, or
  manufactures approval evidence.
- A future Controller must still replay the current Scientific Approval, exact
  Batch member, exact Operational Confirmation, and obtain explicit Core
  `WINNER` before calling Execution. Workflow provides no shortcut.
- `REPLAY` and every non-winner path make zero effect calls. `UNKNOWN` blocks
  the affected path and creates no retry, replacement, child, Batch membership,
  confirmation, or submission authority.
- A separately authorized recovery child must already satisfy Core and
  Approval contracts and be supplied explicitly to a later evaluation; V30-4
  does not create or silently adopt it.

The minimum implementation must remain offline and deterministic. A need for a
new Core field, schema, enumeration method, state transition, public callback,
dynamic node creation, distributed scheduler, event bus, or effectful API is a
contract stop, not an implementation choice.

### Narrow reuse boundary

V30-4 ports the existing public Core `WorkflowRun`, `Task`, `Attempt`,
`CalculationPlan`, and `SQLiteRuntimeStore` load/state APIs without changing
them. It extracts finite-DAG, cycle, missing-reference, deterministic
topological-order, and read-only-projection invariants and adversarial tests
from `skills/auto-g16-reaction-workflow/scripts/calculation_dag.py` and
`tests/test_calculation_dag.py`.

The legacy `gaussian-reaction-calculation-plan/1` artifact may be wrapped only
as an external scientific-plan input through an explicit validated identity
mapping. Its chemistry-specific node kinds, stage matrix, alternatives,
supersession, embedded execution state, `executable`, `calculation_ready`, file
hash lineage, and resume index are not Workflow runtime authority. Generic
typed graph validation and run projection are rewritten because the legacy
private dictionary implementation mixes orchestration with chemistry and file
artifact policy. Transport, program execution, scientific policy, and live
work remain deferred.
