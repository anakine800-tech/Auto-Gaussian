# Auto-G16 v3 Acceptance Cases

These are feature-expansion stop conditions, not authority for a live run.

## V30-CORE-01: Clean Runtime Core

**Status: SATISFIED.** Final Core Review is PASS and `V30-CORE-01 = COMPLETE`.

The Core Interface Review milestone is **PASS WITH CONDITIONS**. The
`auto_g16.core` public path, the ten immutable keyword-only domain records, and
their field-level interface are approved. Canonical payload encoding is a
private implementation detail, not a public symbol, constructor annotation,
runtime payload value, or compatibility promise. Public payload fields expose
only a deeply immutable semantic mapping view. `ExecutionSnapshot` remains
excluded.

The following satisfied conditions remain the frozen V30-CORE-01 acceptance
contract for Python 3.11 or newer:

1. A dependency-free `SQLiteRuntimeStore` persists and reloads all ten Core
   record types. It uses SQLite foreign keys, a versioned fresh-database schema,
   explicit transactions, and no implicit migration of an unknown schema. On
   reopening schema version 1, Core verifies the exact owned schema identity,
   including columns, primary and foreign keys, uniqueness, checks, and indexes;
   same-named counterfeit tables fail closed.
2. Immutable record insertion is replay-safe: an exact repeat is idempotent,
   while the same record identity with different content fails closed without
   overwriting the stored value.
3. Every stored `Attempt` starts in `PLANNED`. Its only states are `PLANNED`,
   `SUBMISSION_INTENT_RECORDED`, `SUBMITTED`, `UNKNOWN`, `RUNNING`, `SUCCEEDED`,
   `FAILED`, and `NOT_SUBMITTED`. State changes outside the documented store
   operations fail closed and leave the transaction unchanged.
4. `record_submission_intent` atomically records exactly one caller-supplied
   intent identity and moves `PLANNED -> SUBMISSION_INTENT_RECORDED`. Exactly
   one concurrent caller receives the explicit `WINNER` claim signal that may
   gate an external submission; exact replay receives the distinct `REPLAY`
   signal and cannot be mistaken for that gate. Implicit truth-value use fails
   closed, requiring an explicit `WINNER` comparison. Reusing an intent identity
   for another Attempt, or a different identity for the same Attempt, is a
   conflict. Core never invokes submission itself.
5. `record_submission_outcome` binds the recorded intent to exactly one
   `SUBMITTED` or `UNKNOWN` outcome. Exact replay is idempotent; conflicting
   outcomes fail. `UNKNOWN` never authorizes retry.
6. Reconciliation of `UNKNOWN` requires a persisted `Observation` for the same
   Attempt. `UNRESOLVED` preserves `UNKNOWN`; terminal evidence may resolve it
   once to `SUBMITTED` or `NOT_SUBMITTED`. Direct or conflicting reconciliation
   fails closed.
7. Normal execution progress permits only `SUBMITTED -> RUNNING`,
   `SUBMITTED -> SUCCEEDED|FAILED`, and `RUNNING -> SUCCEEDED|FAILED`.
   `SUCCEEDED`, `FAILED`, and `NOT_SUBMITTED` are terminal in this slice.
8. Each Task has exactly one persisted root `Attempt`; a second parentless
   Attempt fails closed regardless of the root state. A child `Attempt` is
   created only by an explicit call after its parent is `FAILED` or
   `NOT_SUBMITTED`. It preserves the same `task_id`, records the parent identity,
   has a strictly greater positive ordinal, and is a new `PLANNED` Attempt.
   Core never creates a child automatically, and an `UNKNOWN` parent cannot
   have one or be bypassed by another root.
9. `Observation` and `Result` records are append-only, require an existing
   Attempt, survive close/reopen, retain deterministic insertion order, and
   use the same exact-replay/conflicting-identity rule. Their payload storage
   encoding remains private.
10. Public Core has no Transport, PBS, Gaussian, deployment, scheduler query,
    retry executor, cleanup, or `ExecutionSnapshot` behavior. Focused and
    adversarial tests under `tests/v3/core/` include real concurrent intent
    claim, UNKNOWN root-bypass, counterfeit-schema, and private-encoding
    counterexamples. Syntax compilation, static source checks, and
    `git diff --check` pass offline.

All conditions are satisfied. V30-CORE-01 stops at this boundary; completion
does not authorize another v3 slice.

## V30-3A: Approval Authority and Invalidation Contract

**Status: SATISFIED / INTEGRATED ON
`main@4a181871b0894161dd74fe91c405aa35e3691fd6`.** The conditions below
remain the frozen approval authority contract. They require no Core API/schema
change and perform no external effect:

1. Scientific Approval binds the exact CalculationPlan ID, task, positive
   revision, expanded canonical intent, displayed semantic meaning, explicit
   approved decision, and reviewer identity/evidence. Exact unchanged replay
   is deterministic and idempotent; conflicting content under the same evidence
   identity fails closed.
2. A different CalculationPlan ID, revision, task binding, canonical intent,
   or displayed semantic meaning makes the prior Scientific Approval
   inapplicable to the changed plan.
3. Manual input editing is reparsed into the current semantic plan, displays
   the semantic diff, and requires approval for that current plan. Matching
   artifact hashes alone cannot keep or create approval.
4. Resource, profile/target, workspace, PBS-template, or ExecutionSnapshot
   change is not automatically classified as a scientific change and cannot
   silently modify the approved CalculationPlan.
5. Batch Submit Approval contains an exact finite non-empty list of existing
   Attempts, an explicit approved decision, and reviewer identity/evidence.
   Each member binds its exact task, CalculationPlan ID/revision, and current
   Scientific Approval; one review may approve multiple exact members.
6. An Attempt not listed in the exact set is rejected. Batch identity, a
   prefix/query/range, a future placeholder, or later Batch membership cannot
   expand the approved set.
7. A replacement or recovery-child Attempt is rejected by the parent's Batch
   Submit Approval. A child always requires new explicit membership; the exact
   unchanged Scientific Approval may remain applicable only when the child's
   plan binding is identical.
8. Batch Submit Approval is not a transaction. Failure, `UNKNOWN`, or
   non-submission of one member grants no replacement/retry authority and does
   not expand another member's scope.
9. Exact Operational Confirmation binds one exact ExecutionSnapshot, explicit
   human confirmation and confirmer identity/evidence, plus all nested
   effect-relevant input, resource, profile/target, workspace, PBS-template,
   adapter-contract, Attempt, and submission-intent semantics.
10. Exact unchanged Operational Confirmation replay is deterministic and
    non-effectful. Any snapshot or nested binding change makes the prior
    confirmation stale and is rejected before a Core claim or external effect.
11. Scientific Approval alone, Batch Submit Approval alone, and Exact
    Operational Confirmation alone each produce zero Core transitions and zero
    filesystem, transport, scheduler, PBS, or Gaussian effects.
12. The complete current approval chain still produces zero submission effect
    unless the exact Core claim returns explicit `WINNER`; `REPLAY`, rejection,
    and every non-winner path make zero adapter/effect calls.
13. Missing, malformed, conflicting, cross-Attempt, cross-plan, stale, or
    cross-snapshot evidence fails closed before Core claim and effect.
14. `UNKNOWN` never creates scientific, Batch Submit, confirmation, child, or
    retry authority and permits only the frozen read-only same-Attempt
    reconciliation path.
15. Approval evidence may use hashes for artifact identity or audit, but no
    hash, receipt, legacy owner-chain, capability, or lineage record substitutes
    for semantic replay of the three current approval gates.
16. Contract tests for V30-3B must cover plan-change staleness, unchanged replay,
    unlisted and future-child rejection, exact multi-Attempt membership,
    snapshot-change staleness, zero-effect isolated approvals/confirmation,
    explicit `WINNER`, and UNKNOWN no-retry behavior.
17. Approval implementation is owned by `auto_g16.approval`, with focused tests
    under `tests/v3/approval/`. It may depend on public Core and Execution
    surfaces; neither Core nor Execution imports the approval layer, and no
    approval record or state is added to the Core schema.

V30-3A stops after independent contract review and repository publication.
V30-3B implementation is integrated without changing these conditions;
completion does not authorize V30-EXEC-02, deployment, or live execution.

## V30-EXEC-01: Frozen Offline Execution Boundary

**Status: SATISFIED / INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The numbered conditions
below remain the acceptance contract; integration grants no SSH, RTwin, PBS,
Gaussian, deployment, or other live-effect authority:

1. Semantically identical snapshots keep one identity across JSON key order or
   formatting changes.
2. Any effect-relevant field change produces a new snapshot identity.
3. Mutable ServerProfile changes stale an unexecuted snapshot and require fresh
   resolution.
4. Windows relative, home-relative, and `~` paths are rejected.
5. POSIX relative or non-canonical paths are rejected.
6. PBS template identity derives from exact bytes; an opaque caller ID is
   rejected.
7. `PreparedInputBinding` binds exact prepared bytes durably to the
   CalculationPlan, revision, and Attempt.
8. `ResolvedResourceRequest` binds the exact ResourceSpec and effect-time
   values while remaining separate from scientific intent.
9. An existing Project can receive a fresh Attempt workspace.
10. Local, RTwin, and server workspaces are Attempt-specific, contained,
    no-follow where effectful, and no-overwrite.
11. Partial workspace allocation persists explicitly and never masquerades as
    globally no effect.
12. Concurrent claims yield exactly one Core `WINNER` for a submission intent
    and at most one submission call for the Attempt.
13. `REPLAY` makes zero adapter or external-effect calls.
14. Pre-effect failure records no-effect evidence and is not `UNKNOWN`.
15. Possibly effectful submission ambiguity becomes `UNKNOWN`.
16. `UNKNOWN` permits same-Attempt reconciliation, never automatic retry.
17. Minimal `RemoteEffectReceipt` replay is idempotent and conflicting content
    is rejected; all three frozen effect states and `effect_sequence` are
    covered.
18. The RTwin synthetic adapter needs no real SSH, PBS, or Gaussian.
19. Core remains transport-free.
20. No `qdel`, cancellation, deletion, cleanup, deployment, or live behavior is
    exercised or authorized.

## V30-RESULT-01: Frozen Result Provenance Boundary

**Status: SATISFIED / INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The numbered conditions
below remain the acceptance contract and do not grant scientific acceptance or
live-effect authority:

1. UUIDv5 namespaces are source-controlled and caller-invariant.
2. Exact replay of the input tuple (`attempt_id`, `calculation_plan_id`,
   `calculation_plan_revision`, `prepared_input_binding_id`,
   `execution_snapshot_id`) produces the same identity.
3. A changed plan revision, prepared input binding, or snapshot identity
   produces a new input-binding identity.
4. Malformed envelope metadata fails closed without a false legal envelope.
5. A valid complete envelope persists under the exact tuple
   (`attempt_id`, `input_binding_observation_id`, `capture_source_id`,
   `capture_manifest_sha256`, `capture_completeness`).
6. A valid partial envelope persists and remains explicitly incomplete.
7. A valid envelope with unparseable output is preserved with an explicit
   `unparseable` Result outcome.
8. `unsupported` output or parser status remains distinct from malformed
   metadata.
9. Exact Result tuple (`envelope_observation_id`, `parser_name`,
   `parser_version`, `result_kind`) replay is idempotent.
10. The same Result identity with a different payload conflicts.
11. A new parser version produces a new Result identity without overwriting the
    earlier result.
12. Multiple captures remain append-only.
13. A Result never splices facts or provenance across captures.
14. The current view chooses the latest legal complete capture by deterministic
    insertion order.
15. With no complete capture, the current view exposes the latest partial
    capture as explicitly incomplete.
16. Durable incomplete prefixes survive close and reopen.
17. Result creation and reading never change Attempt runtime state.
18. Result existence and parser status do not grant scientific acceptance.
19. Synthetic artifacts require no live RTwin or PBS.
20. Core API and schema remain unchanged.

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
3. Exact semantic replay of every identity-bearing Workflow record produces
   the same schema-versioned, domain-separated UUIDv5 identity. Any semantic
   field change produces a different identity; the same identity with
   different content conflicts. `WorkflowEvaluationInput` and the derived
   `WorkflowRunView` are canonical value records without independent authority
   IDs and replay to byte-equivalent semantic values.
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

## v3.0: Closed-Shell Minimum

A real closed-shell minimum completes:

`structure -> plan -> submit -> observe -> fetch -> parse -> ReviewBundle`

When this case meets its reviewed acceptance criteria, stop v3.0 feature
expansion.

## v3.1: Flexible-Molecule Ensemble

A real flexible molecule completes:

`xTB preopt -> CREST -> audit -> DFT -> Freq -> qRRHO -> ensemble`

When this case meets its reviewed acceptance criteria, stop v3.1 feature
expansion.

## v3.2a: Representative Reaction

A representative reaction completes:

`ReactionPlan -> TS search -> mode review -> bidirectional IRC -> endpoints -> barrier`

When this case meets its reviewed acceptance criteria, stop v3.2a feature
expansion.
