# Auto-G16 v3 acceptance: workflow

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:796-929 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-WF-CONTRACT-01: Minimal Deterministic Workflow

**Status: CONTRACT FROZEN; IMPLEMENTATION NOT AUTHORIZED.** The following are
the exact acceptance conditions for V30-4. They grant no selector mutation,
Workflow implementation, Core change, Execution effect, `V30-EXEC-02`, or live
authority:

1. `auto_g16.workflow` is the sole public Workflow package and
   `tests/v3/workflow/` is its focused test package. Core, Approval, Execution,
   and Result never import Workflow.
2. The public inventory is exactly `Node`, `Edge`, `Map`, `Condition`,
   `HumanGate`, `WorkflowDefinition`, `WorkflowEvaluationInput`,
   `ConditionDecision`, `HumanGateDecision`, `WorkflowRunView`,
   `SQLiteWorkflowStore`, `record_workflow_definition`,
   `validate_workflow_definition`,
   `record_condition_decision`, `record_human_gate_decision`, and
   `replay_workflow`. Store lifecycle is exactly `create_new`, `open_existing`,
   and `close`; raw SQL/rows are private. Public functions accept only the
   exact store/Core/definition/evaluation/decision inputs frozen in the
   boundary and no effect adapter or callback.
3. `Node.node_id`, `Edge.edge_id`, `Map.map_id`, `Condition.condition_id`, and
   `HumanGate.human_gate_id` are non-empty local canonical identifiers scoped
   to one exact WorkflowDefinition, immutable inside it, and unique within
   their component namespaces; all intra-definition references use them. They
   are not complete-payload UUIDv5 identities and alone grant no
   cross-definition identity, persistence equivalence, authority, or effect.
   `WorkflowDefinition.workflow_definition_id` is schema-versioned,
   domain-separated UUIDv5 over the complete canonical definition payload,
   including every local ID and every component's complete semantics; reusing
   a local ID with changed semantics changes the definition identity.
   `ConditionDecision` and `HumanGateDecision` have separate domain-separated
   deterministic UUIDv5 identities binding the exact WorkflowDefinition ID,
   frozen Core/run identities, referenced local component ID, and complete
   decision payload. Exact authority-record replay is idempotent and the same
   authority identity with different content conflicts. No circular component
   identity computation is permitted: Edge-to-Condition and
   Condition-to-Edge IDs are ordinary intra-definition references inside the
   single definition payload. `WorkflowEvaluationInput` and the derived
   `WorkflowRunView` remain canonical value records without independent
   authority IDs and replay to byte-equivalent semantic values.
4. A definition is finite, non-empty, deeply immutable, serializable, and
   binds one exact existing Core WorkflowRun. Every Node binds one exact Task
   in that run and one exact existing CalculationPlan ID and positive revision
   for that Task.
5. Duplicate, missing, self, cross-run, cross-Task, stale-plan, unknown-role,
   ambiguous-producer, or orphan references fail closed. No new Core list,
   current-plan, or enumeration API is used or added.
6. The union of unconditional edges, every possible conditional edge, and
   every Map item's source-to-target dependency is acyclic. Map-only and mixed
   Edge/Map cycles fail closed. Stable lexical tie-breaking gives one
   deterministic topological order and readiness projection independent of
   input collection order.
7. A Map contains a finite non-empty set of unique explicit item keys and maps
   only to predeclared Nodes and input roles. Every item participates in the
   graph dependency, topological order, and readiness rules in condition 6. It
   cannot dynamically create, discover, or execute a Task, Node, callback,
   command, or program.
8. A Condition uses only the closed `attempt_state_in` predicate over an exact
   supplied source Attempt and a non-empty subset of `SUCCEEDED`, `FAILED`, and
   `NOT_SUBMITTED`. `always` Edges have no Condition; every conditional Edge is
   listed exactly once in the matching Condition and branch. True and false
   tuples are canonical and disjoint; mismatch, overlap, omission, duplicate,
   or cross-Condition membership fails closed.
9. Condition recording rejects missing, running, `UNKNOWN`, stale,
   cross-definition, cross-run, cross-node, cross-Task, or mismatched-state
   evidence without persisting a branch decision. The selected tuple is the
   complete canonical true tuple when the exact terminal state is expected and
   the complete canonical false tuple otherwise; caller-selected subsets,
   supersets, reordering, or cross-splicing fail closed.
10. A HumanGate decision binds the exact definition, run, and gate plus the
    explicit reviewer and evidence. HumanGate target sets are globally
    disjoint. For an already active target, missing means pending, rejected
    means blocked, and approved removes only that gate filter; a decision for
    an inactive target never activates it. Exact replay is idempotent; overlap,
    conflict, or cross-gate reuse fails closed and survives durable reopen.
    There is at most one decision for an exact definition/gate authority key.
11. HumanGate approval changes orchestration readiness only. It never creates
    Scientific Approval, Batch Submit Approval, Exact Operational
    Confirmation, scientific acceptance, a Core claim, or an external effect.
12. Workflow-owned SQLite schema version 1 stores immutable definitions and
    append-only typed decisions independently of Core and Approval stores.
    Fresh schema, exact replay, same-ID conflict, closed decoding, deterministic
    order, durable reopen, no implicit migration, and no update/delete behavior
    are tested. Create-new rejects an existing target; reopen rejects missing,
    wrong-version, malformed, extra, or conflicting state and performs no
    repair or initialization. Competing Condition decisions for one exact
    definition/condition/Attempt key also fail closed.
13. `WorkflowRunView` is always recomputed from the exact definition,
    decisions, explicit node-to-Attempt mapping, and public Core records. The
    same reopened inputs yield the same view; a stored mutable view cannot
    override those authorities.
14. Every supplied Attempt exists and belongs to the exact Node Task. Missing
    bindings remain explicit; Workflow neither enumerates nor chooses Attempts.
    Active roots and reachability are derived only from the combined graph and
    selected conditional Edges; neither an Attempt binding nor HumanGate can
    activate an inactive Node. A ready Node is only a proposal and creates no
    root Attempt.
15. Completed branch and HumanGate decisions survive reopen and cannot be
    spliced across definitions, runs, nodes, conditions, gates, Tasks, or
    Attempts. Map expansion and active-path projection are deterministic.
16. An active no-Attempt Node is ready only when all active always/Map
    predecessors are `SUCCEEDED`, selected conditional predecessors have exact
    terminal decisions, every input role has one active producer, and its gate
    is approved. Missing decisions are pending; rejection, failed always/Map
    predecessors, producer gaps, and `UNKNOWN` block. A run becomes
    orchestration-complete only when every active Node has an
    exact terminal Core outcome and all required decisions close. Completion
    does not imply execution success, valid chemistry, parsed Result maturity,
    or scientific acceptance. `pending`, `active`, `blocked`, and `completed`
    outcomes are deterministically derived rather than caller-selected.
17. `UNKNOWN` blocks the affected path and creates no retry, replacement,
    child, approval, confirmation, submission, or effect authority. Workflow
    never silently creates or adopts a recovery child.
18. Node readiness, Map, ConditionDecision, HumanGateDecision, and complete
    Workflow replay each produce zero Core transitions, workspace writes,
    adapter calls, transport, scheduler, PBS, Gaussian, cancellation, cleanup,
    or deletion.
19. The later Controller still needs current Scientific Approval, exact Batch
    membership, exact Operational Confirmation, and explicit Core `WINNER`
    before an effect. `REPLAY` and every non-winner path make zero effect calls.
20. Focused adversarial tests cover identity drift, Edge-only, Map-only, and
    mixed Edge/Map cycles, deterministic order and Map-aware readiness, role
    and mapping closure, Edge/Condition branch mismatch, true/false overlap,
    subset selection, terminal branch replay, overlapping gates,
    approved-plus-missing/rejected gates, inactive-target approval, store
    create/reopen closure, durable reopen, cross-splicing, `UNKNOWN`,
    zero-effect behavior, absence of
    callback/shell/eval surfaces, and byte-identical Core/Approval/Execution/
    Result public contracts.

V30-WF-CONTRACT-01 stops after independent contract review and repository
publication. V30-4 implementation remains blocked until separate Workflow
validation ownership is integrated and a new implementation Owner Gate opens.
