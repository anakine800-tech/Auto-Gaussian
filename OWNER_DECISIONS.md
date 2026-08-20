# Auto-G16 v3 Owner Decisions

These decisions close the design questions accepted in Phase 0 and Phase 0.6.
They govern v3 planning until changed by a later reviewed Git commit.

## OD-01: Clean core and compatibility

v3 deliberately breaks v2 runtime compatibility. It is a clean-core,
selective rewrite: reuse is decided capability by capability, and preserved
data does not imply preservation of the v2 runtime ABI.

## OD-02: Semantic approval and edited inputs

Approval applies to the current `CalculationPlan` and its displayed meaning.
Manual editing of an input file is valid. After an edit, the controller must:

1. parse the current file again;
2. display the semantic diff;
3. obtain approval for the current `CalculationPlan`.

A hash may record artifact identity, but it is not a lock on an earlier
approval. v3 does not add a new hash-bound owner-approval mechanism.

## OD-03: Mutable profiles and execution snapshots

`ServerProfile` is mutable configuration. Every execution produces an
`ExecutionSnapshot` that captures the effective execution inputs for that
run. Review targets current semantics; the snapshot records what was used.

## OD-04: Project reuse and the no-overwrite boundary

An existing `Project` directory may continue to be used. The no-overwrite
boundary is a new `Attempt`; it does not require the entire `Project` to remain
forever fresh. A new execution must allocate a new `Attempt` and must not
overwrite a prior attempt's artifacts.

## OD-05: Single submission and uncertainty

Each `Attempt` may invoke `qsub` at most once. An ambiguous submission becomes
`UNKNOWN` / `submission_uncertain` and enters reconciliation. It must never be
retried automatically.

## OD-06: Transport targets

Direct SSH is the v3.0 transport target, implemented behind a new thin
`OpenSSHTransport`. It does not inherit the old single-use capability or
private owner-chain architecture. The legacy RTwin path remains an adapter and
a reuse source for existing operation. Live deployment always requires
separate, explicit authorization.

## OD-07: Safety semantics and governance implementation

v3 keeps reviewed execution-safety semantics while separating them from the
old governance implementation. Safety requirements are expressed at the v3
core and boundary level; the old governance machinery is not the v3
architecture.

## OD-08: Runtime and change-aware CI

The controller requires Python 3.11 or newer. Python 3.13 is the primary
full-validation runtime. Python 3.11 and 3.12 run compatibility and affected
tests by default instead of duplicating the complete full suite. CI is
change-aware and expands only when the affected surface requires it.

## OD-09: Conformer policy must be benchmarked again

v3 may extract existing conformer-science primitives, but sampling, coverage,
and DFT policy must be benchmarked again. Historical A/B route quotas are not
permanent scientific rules.

## OD-10: Approval authority is separated into three gates

v3 separates scientific meaning, permission to submit selected Attempts, and
effect-time confirmation. They are three different authorities:

```text
CalculationPlan
    -> Scientific Approval
    -> Batch Submit Approval for an exact finite Attempt set
    -> ExecutionSnapshot
    -> Exact Operational Confirmation
    -> Core WINNER
    -> effect
```

Scientific Approval binds the exact current `CalculationPlan`, its revision,
the semantic meaning shown to the reviewer, and an explicit human decision. It
does not bind resources, profiles, workspaces, PBS bytes, or an
`ExecutionSnapshot`. A changed plan or revision requires a new semantic review
under OD-02. A hash may identify an artifact, but cannot substitute for the
expanded plan semantics or make an old approval current.

Batch Submit Approval binds an explicit finite set of already-existing
`Attempt` records and, for each member, the exact currently approved
`CalculationPlan`, with an explicit human decision over that closed set. A
Batch identifier never acts as a wildcard: future, replacement,
recovery-child, or otherwise unlisted Attempts are not covered. The approval
is not a transaction and grants no automatic replacement, submission, retry,
or scope expansion.

Exact Operational Confirmation binds one exact `ExecutionSnapshot`, including
its prepared bytes, resolved resources and profile/target, workspace, PBS
template, and submission intent. Any snapshot change makes the prior
confirmation stale. Resource, profile, or workspace changes are operational
changes rather than automatic scientific changes, but they require a newly
resolved snapshot and a new exact confirmation.

Each approval or confirmation is non-effectful by itself. Only the complete
current chain followed by the explicit Core `WINNER` claim may reach an effect.
`UNKNOWN` creates no retry authority. A child Attempt may reuse scientific
approval only when it still binds the exact same CalculationPlan; it always
requires new Batch Submit Approval membership, a new snapshot, and a new exact
operational confirmation.

## OD-11: Minimal workflow is deterministic orchestration, not effect authority

The v3.0 Workflow layer is an immutable, finite DAG over exact existing Core
identities. Its public package is `auto_g16.workflow`, with focused tests under
`tests/v3/workflow/`. It owns dependency order, bounded static mapping,
condition branches, human orchestration gates, and a deterministic read-only
run projection. It does not redefine Core records or persistence semantics.

Every node binds one exact Core `Task` and one exact `CalculationPlan` ID and
positive revision. The workflow definition enumerates those identities
explicitly; it never discovers the current plan or lists Tasks through a new
Core API. Every possible edge and mapped target is present in the finite
definition. Every Map item contributes its source-to-target dependency to the
same graph as every possible Edge; that combined graph is acyclic and owns the
deterministic topological order and readiness projection. Conditions use a
closed, data-only predicate over an exact supplied Attempt state. Conditional
Edge metadata and each Condition's true/false Edge tuples must agree exactly;
the observed terminal state uniquely derives the complete selected tuple, not
a caller-chosen subset. Arbitrary Python callbacks, shell commands, code
evaluation, dynamic node creation, and open-ended fan-out are not Workflow
features.

The existing Core `WorkflowRun`, `Task`, `Attempt`, and `CalculationPlan`
records remain authoritative for runtime identity and state. A Workflow
evaluation receives an explicit finite node-to-Attempt mapping and validates
every supplied record through public Core APIs. Missing bindings remain
explicitly pending. HumanGate target sets are disjoint; a gate filters only an
already active Node and never activates an inactive branch. A ready node is
only a proposal for the next separately gated action. Workflow never creates a
root or recovery Attempt, claims Core `WINNER`, calls Execution, or crosses an
effect boundary.

`Node.node_id`, `Edge.edge_id`, `Map.map_id`, `Condition.condition_id`, and
`HumanGate.human_gate_id` are non-empty local canonical identifiers scoped to
one exact `WorkflowDefinition`. Each is immutable inside that definition and
unique within its component namespace; all intra-definition references use
these local identifiers. They are not complete-payload UUIDv5 identities and,
alone, grant no cross-definition identity, persistence equivalence, authority,
or effect. Edge-to-Condition and Condition-to-Edge references are ordinary
intra-definition references; component identity computation is never circular.

`WorkflowDefinition.workflow_definition_id` is a schema-versioned,
domain-separated UUIDv5 over the complete canonical definition payload,
including every local identifier and every component's complete semantics.
Reusing a local identifier with changed component semantics therefore changes
the definition identity. Completed `ConditionDecision` and
`HumanGateDecision` records have separate domain-separated deterministic
UUIDv5 identities that bind the exact WorkflowDefinition identity, frozen
Core/run identities, referenced local component identifier, and complete
decision payload. These canonical records use a small Workflow-owned
append-only persistence surface. Exact replay is idempotent; the same authority
identity with different content conflicts. A `WorkflowRunView` is a derived
projection, not separately mutable state. Reopening the same exact definition,
decisions, explicit Attempt bindings, and Core state produces the same view.

A Workflow `HumanGate` is orchestration state only. It never substitutes for
Scientific Approval, Batch Submit Approval, Exact Operational Confirmation,
scientific acceptance, or Core `WINNER`. `UNKNOWN` blocks the affected path and
creates no retry, replacement, child, approval, or effect authority. Recovery
children remain governed by the existing Core and Approval contracts and are
outside automatic Workflow behavior.
