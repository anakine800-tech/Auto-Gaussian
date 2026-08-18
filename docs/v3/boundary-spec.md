# Auto-G16 v3 Boundary Specification

This document fixes stable dependency and data boundaries only. It does not
select implementation techniques.

## Dependency Direction

`Skills -> Workflow -> Approval / Execution / Result -> Core`

Skills compose workflows. Workflow may depend only on public Approval,
Execution, Result, and Core surfaces; those layers must not import Workflow.
Core must not depend on a Skill or any higher layer. Reverse imports across
this direction are forbidden.

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

## V30-3A Frozen Approval Authority Contract

**Contract status: FROZEN; IMPLEMENTATION INTEGRATED ON
`main@4a181871b0894161dd74fe91c405aa35e3691fd6`.** Approval belongs to a
Workflow/Controller layer. It does not add an
`auto_g16.core` record, store method, state transition, schema table, or effect
owner, and it does not reopen the frozen Execution or Result contracts. The
approval-layer package is `auto_g16.approval`, with focused tests under
`tests/v3/approval/`. It may depend on the public `auto_g16.core` and
`auto_g16.execution` surfaces; neither Core nor Execution may depend on it.
Workflows or a Controller compose the approval layer with execution. V30-3A
fixes package ownership, authority, and invalidation semantics; V30-3B
separately reviewed and integrated the public type shapes, persistence, and
implementation without changing this contract.

The only legal approval-to-effect chain is:

```text
exact CalculationPlan
-> current Scientific Approval
-> Batch Submit Approval membership for the exact Attempt and plan
-> exact ExecutionSnapshot
-> current Exact Operational Confirmation
-> record_submission_intent(exact Attempt, exact submission intent)
-> explicit Core WINNER
-> effect
```

No item in this chain may stand in for another. An approval record, a
confirmation record, a digest, an `ExecutionSnapshot`, `REPLAY`, or adapter
readiness cannot replace Core `WINNER`.

### Scientific Approval

Scientific Approval binds all of these semantics as one closed decision:

```text
calculation_plan_id
task_id
positive calculation_plan_revision
expanded canonical CalculationPlan.intent
the displayed semantic meaning reviewed by the human
explicit approved decision and reviewer identity/evidence
```

The displayed meaning must be derived from that exact plan and must be
sufficient for a reviewer to understand the current scientific intent;
presentation-only formatting bytes are not a second scientific authority. An
implementation may record a digest for identity or audit, but it must replay
the expanded plan, semantic view, explicit decision, and reviewer evidence
before treating approval as current. A matching hash alone is never approval
authority.

A different plan ID, revision, task binding, canonical intent, or displayed
semantic meaning makes the earlier approval inapplicable to the changed plan.
Manual edits follow OD-02: parse the current input again, display the semantic
diff, and obtain approval for the resulting current CalculationPlan. Resource,
ServerProfile, workspace, PBS-template, and ExecutionSnapshot values are not
scientific-approval fields and their change is not automatically a scientific
change.

Scientific Approval is plan-scoped rather than Attempt-scoped. Creating a new
Attempt does not by itself invalidate it. A later Attempt, including an
explicit recovery child, may rely on the same scientific approval only when it
still resolves to the exact same plan ID, task, revision, canonical intent, and
displayed meaning. It gains no submit permission from that fact.

### Batch Submit Approval

Batch Submit Approval binds one explicit, finite, non-empty set. Every member
contains the exact:

```text
attempt_id
task_id
calculation_plan_id
calculation_plan_revision
Scientific Approval identity/evidence for that exact plan
explicit approved decision and reviewer identity/evidence for the closed set
```

All listed Attempts must already exist and resolve through the frozen Core
ownership relationships. An optional Core `Batch` identity is organizational
context only; it never expands membership to every current or future task or
Attempt in that Batch. Membership is exact and cannot use a query, prefix,
range, future placeholder, or "all current members" rule.

One human decision may cover multiple listed Attempts, but the decision is not
a database, scheduler, or effect transaction. Each member independently passes
later gates. Failure, `UNKNOWN`, non-submission, or staleness of one member does
not authorize a replacement and does not expand or silently rewrite the set;
it also does not by itself revoke another unchanged member's exact scope.

An unlisted root, replacement, or child Attempt is rejected. A changed plan or
scientific approval makes that member's listed binding stale. Creating a child
Attempt after `FAILED` or `NOT_SUBMITTED` always requires new explicit Batch
Submit Approval membership, even when the exact scientific approval remains
applicable. An `UNKNOWN` Attempt creates neither a child nor retry authority.

Batch Submit Approval intentionally does not bind resource values,
ServerProfile content, workspace paths, PBS-template bytes, or an
ExecutionSnapshot. Those values are checked by exact operational confirmation.
Changing them within an approved operational policy does not silently change
science or Batch membership, but it cannot reuse a stale snapshot confirmation.
This contract neither defines nor bypasses the separate resource policy.

### Exact Operational Confirmation

Exact Operational Confirmation binds one and only one fully resolved
`ExecutionSnapshot`, plus the confirmer identity/evidence and explicit human
confirmation of that exact snapshot. The reviewer must be shown the exact
Attempt and the snapshot's effect-relevant values, including:

```text
execution_snapshot_id
attempt_id and submission_intent_id
calculation_plan_id and revision
exact prepared-input identity and bytes digest/size
resolved resource request
resolved ServerProfile target and effect-relevant configuration identity
Attempt workspace binding
validated exact PBS-template identity
adapter contract version
```

The confirmation is valid only while the complete snapshot identity closes
over those exact values. Any snapshot or nested binding change, including
resource, profile/target, workspace, input, template, adapter-contract, or
submission-intent drift, makes the earlier confirmation stale and requires a
new resolution and confirmation. The unchanged exact confirmation may be
replayed deterministically for validation; replay creates no additional effect
or retry authority.

### Effect gate, replay, and invalidation

Immediately before an effect, the Controller must replay the exact current
Scientific Approval, exact Batch Submit Approval member, and exact Operational
Confirmation against the same Attempt, plan, and snapshot. Missing,
conflicting, malformed, stale, cross-Attempt, cross-plan, or cross-snapshot
evidence fails closed before the Core claim and before every external effect.

Approval alone performs no Core transition, workspace mutation, upload,
submission, retry, reconciliation, cancellation, cleanup, or deletion.
Confirmation alone is also non-effectful. Even a complete approval chain makes
zero submission effect unless the exact Core submission-intent claim returns
`WINNER`; `REPLAY` and every non-winner path make zero effect calls.

Exact replay of unchanged approval evidence is deterministic and idempotent;
the same evidence identity with different content conflicts. Approval evidence
is durable review evidence, not a batch transaction, receipt owner-chain,
single-use capability forest, or hash-lineage authority. The integrated V30-3B
implementation does not port those legacy governance mechanisms as an implicit
requirement.

An ambiguous submission remains `UNKNOWN` under the frozen Core and Execution
contracts. It authorizes only read-only same-Attempt reconciliation, never an
automatic retry, replacement Attempt, new Batch membership, new confirmation,
or second effect. Recovery continues through an explicitly created child after
the Core terminal-state rules permit it, followed by the approval gates stated
above.

## V30-EXEC-01 Frozen Execution Contract

**Contract status: FROZEN; IMPLEMENTATION INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** This is the RTwin-first
`legacy_rtwin_pbs` execution boundary, not a generic execution or transport
framework. `ExecutionSnapshot`, preparation records, effect evidence, and
transport remain outside `auto_g16.core`.

### Package placement and identity

The public package is `auto_g16.execution`; its focused tests belong under
`tests/v3/execution/`. It may depend on `auto_g16.core`, but Core must not
depend on it. The RTwin adapter is an execution/transport adapter, not Core.

Every execution-layer record identity below is deterministically derived from
a schema-versioned, domain-separated canonical semantic payload. Exact replay
has the same identity; the same identity with different content fails closed.
Formatting, serialization byte order, timestamps, log times, and temporary
paths do not affect semantic identity. A caller-supplied digest or path is not
authority, and an implementation may not replace the expanded payload with a
set of unverified, cross-spliceable opaque IDs.

Before snapshot resolution, the resolver must load and validate the complete
Core chain:

```text
Attempt -> Task -> WorkflowRun -> Project
        -> exact CalculationPlan
        -> exact ResourceSpec
```

The `Attempt`, `CalculationPlan`, and `ResourceSpec` must have the same
`task_id`; the Task must belong to the loaded WorkflowRun and Project. The
executor never reinterprets `CalculationPlan.intent`, changes chemistry, or
generates different input at the effect seam. The prepared input bytes are
verified before snapshot creation and remain immutable through execution.

`PreparedInputBinding` has these mandatory semantic fields:

| Field | Meaning |
| --- | --- |
| `prepared_input_binding_id` | Deterministic identity of the canonical payload |
| `attempt_id` | Exact Core Attempt |
| `calculation_plan_id` | Exact reviewed CalculationPlan |
| `calculation_plan_revision` | Exact positive revision |
| `input_format` | Explicit format, such as `gaussian-gjf`; Core does not infer it |
| `logical_name` | Portable logical filename |
| `sha256` | SHA-256 of the exact prepared input bytes |
| `size_bytes` | Exact byte count |

Execution consumes those same verified bytes without an ambient-source or
mutable-path reread.

`ResolvedResourceRequest` has these mandatory semantic fields:

| Field | Meaning |
| --- | --- |
| `resolved_resource_request_id` | Deterministic identity of the canonical request |
| `resource_spec_id` | Exact Core ResourceSpec |
| `cores` | Positive integer |
| `memory_mb` | Positive integer |
| `walltime_seconds` | Positive integer |
| `queue` | Optional reviewed queue name |

Resource policy remains separate from scientific intent. A Controller may
adjust resources only within policy, and the exact values must be shown before
each effect. Arbitrary PBS-directive passthrough is forbidden; a new resource
field requires an Owner Gate rather than a free-text bypass.

### ServerProfile resolution and immutable bytes

`ServerProfile` is mutable configuration. Before the Core submission-intent
claim, the resolver freezes one immutable `ResolvedServerProfile` with these
mandatory semantics:

```text
resolved_server_profile_id
server_profile_id
profile_revision
effective_config_sha256
transport_kind
target_identity
remote_user
remote_root
platform_paths
runtime_identities
```

For each SSH hop, the content identity binds the exact ordered, validated
config/include-file bytes used for the selected alias. The effective identity
binds the complete normalized non-network resolution, including destination,
port, user, jump topology, host-key behavior, batch and identity-selection
behavior, and identity/known-hosts path identities. `effective_config_sha256`
binds all canonical effect-relevant values, including validated referenced
configuration content. Credentials, private-key bytes, agent material,
passwords, and tokens are excluded. Alias, profile revision, filename, source
path, or caller-supplied digest alone is never authority. Resolution failure,
host-identity drift, or mutation during resolution fails closed; after
resolution, execution may not reread the profile, CLI, environment, or mutable
configuration.

For `legacy_rtwin_pbs`, `remote_root` remains fixed at `/home/user100/SDL`.
`runtime_identities` derive from the complete effect-relevant, non-secret
runtime content, never an opaque runtime digest.

Every effect-relevant path is an explicit absolute canonical path. POSIX paths
start at `/` and contain no empty, `.`, `..`, repeated-separator, NUL, or
unresolved-symlink component. Windows paths are already-normalized absolute
uppercase-drive paths using `\\`; UNC, device namespaces, drive-relative,
root-relative, home-relative, `~`, environment/current-directory expansion,
ADS, empty/`.`/`..` components, repeated separators, control characters,
reserved device names, and trailing spaces or dots are forbidden. No resolver
may repair or reinterpret a rejected path.

`PbsTemplateBinding` has mandatory semantics
`pbs_template_binding_id`, `logical_name`, `sha256`, `size_bytes`, and
`template_contract_version`. Its identity derives from the validated exact
immutable template bytes, size, and SHA-256; changing the bytes changes the
identity. Execution consumes those same bytes without a mutable reread. An
opaque caller template ID, arbitrary shell expansion, or caller-selected
command is forbidden.

### ExecutionSnapshot and workspaces

`WorkspaceBinding` has mandatory semantics `workspace_binding_id`,
`project_id`, `attempt_id`, `local_attempt_dir`, optional
`rtwin_attempt_dir`, and `remote_attempt_dir`. A Project remains reusable, but
every no-overwrite boundary is a new Attempt. Each directory is an explicit
absolute canonical, Attempt-specific path contained under its approved root.
The binding identity derives from this canonical payload, and the local
Attempt directory is a sealed read-only handoff of the exact prepared bytes.
Effectful allocation is no-follow and fresh/exclusive; existing targets,
symlinks or reparse points, replacement, containment escape, or overwrite fail
closed. The three platform strings may differ but bind the same Attempt. A
partial allocation is a durable prefix represented by minimal effect evidence,
not a claim of globally zero effect.

`ExecutionSnapshot` has these mandatory semantic fields:

```text
execution_snapshot_id
attempt_id
submission_intent_id
calculation_plan_id
calculation_plan_revision
prepared_input_binding
resolved_resource_request
resolved_server_profile
workspace_binding
pbs_template_binding
adapter_contract_version
```

Its identity is derived from the canonical expanded payload and binds the
exact Attempt, Core submission intent, reviewed CalculationPlan, prepared
input bytes, resolved resource values, effect-relevant resolved profile,
workspaces, template bytes, and adapter contract. It contains no timestamp,
credentials, mutable path source, approval, or live transport authority.
Profile drift before the effect seam stops the pending operation for fresh
resolution and confirmation; it cannot mutate an existing snapshot.

### Submission and effect semantics

The only legal Core claim is:

```text
record_submission_intent(
    snapshot.attempt_id,
    snapshot.submission_intent_id,
)
```

Exactly one explicit `WINNER` may enter the effect boundary. `REPLAY` makes
zero adapter, transport, allocation, transfer, or submission calls. Validation,
a snapshot, profile, receipt, or adapter state cannot replace `WINNER`.

Effects use this explicit order:

```text
resolve profile/resources/input
→ create ExecutionSnapshot
→ obtain exact operational confirmation
→ claim Core submission intent
→ allocate/verify attempt workspaces
→ materialize/upload input and PBS bytes
→ invoke adapter submission effect at most once
→ record exact outcome/receipt
```

Each effect preserves containment, no-follow, fresh/no-overwrite, exact-byte,
and endpoint-identity checks. At most one `qsub` call is permitted for the
Attempt.

The only public execution-layer effect evidence is a minimal append-only
`RemoteEffectReceipt` with these mandatory semantic fields:

```text
remote_effect_receipt_id
attempt_id
execution_snapshot_id
submission_intent_id
effect_sequence
effect_kind
effect_state
optional remote_workspace
optional job_id
details
```

`effect_state` is exactly one of `confirmed_no_effect`, `confirmed_effect`, or
`possibly_effectful`. Exact replay is idempotent; the same identity with
different content conflicts. A receipt records evidence and never grants new
authorization. The v3 boundary requires no additional legacy governance
implementation beyond these public records and the safety semantics stated
here.

A proven failure before any effect is not `UNKNOWN` and records explicit
`confirmed_no_effect` evidence. A failure that may have crossed an effect seam
is `possibly_effectful`, drives durable `UNKNOWN`, and permits read-only,
same-Attempt reconciliation only. A reliable confirmed submission records the
exact job identity when available; scheduler success is not scientific
acceptance. Missing, multiple, contradictory, unbound, or unreliable evidence
remains `UNKNOWN`.

`UNKNOWN` never authorizes an automatic retry, another `qsub`, alternate
profile or workspace, bypass or replacement Attempt, cleanup, cancellation,
or `qdel`. This slice validates `Mac -> RTwin -> Server` first with a synthetic
offline adapter. Live RTwin requires separate Owner authorization;
`V30-EXEC-02` OpenSSH remains `WAIT` and must later reuse this public execution
port. ExecutionSnapshot and transport/effect behavior remain outside Core.

## V30-RESULT-01 Frozen Result Provenance Contract

**Contract status: FROZEN; IMPLEMENTATION INTEGRATED ON
`main@2911451eb91a63c4c1df7601b4ac49610b6205a3`.** The public package is
`auto_g16.result`; focused tests belong under `tests/v3/result/`. It may depend
on `auto_g16.core`, but not live Transport, PBS, or RTwin, and it does not
change the Core schema. The only legal append-only chain is:

```text
CalculationPlan
→ Attempt
→ exact input-binding Observation
→ program-output-envelope Observation
→ Result
```

Ownership is resolved only through `Project -> WorkflowRun -> Task -> Attempt`;
provenance payloads do not copy a second ownership truth. The exact
CalculationPlan must bind the Attempt through the frozen Core relationships.
Directory names, mtimes, current filenames, cross-Attempt joins, and
cross-capture joins are not provenance authority.

### Deterministic record identities

Each record type uses a source-controlled, domain-separated UUIDv5 namespace;
a caller cannot choose a namespace or identity. The canonical tuples are:

```text
input-binding Observation = uuid5(
  NS_INPUT_BINDING,
  canonical(
    attempt_id,
    calculation_plan_id,
    calculation_plan_revision,
    prepared_input_binding_id,
    execution_snapshot_id
  )
)

output-envelope Observation = uuid5(
  NS_OUTPUT_ENVELOPE,
  canonical(
    attempt_id,
    input_binding_observation_id,
    capture_source_id,
    capture_manifest_sha256,
    capture_completeness
  )
)

Result = uuid5(
  NS_PARSED_RESULT,
  canonical(
    envelope_observation_id,
    parser_name,
    parser_version,
    result_kind
  )
)
```

Exact replay produces the same identity. A new capture source or manifest,
capture completeness, parser name/version, or result kind produces the
corresponding new identity. Timestamps do not participate. The same identity
with different content is a Core conflict and cannot be evaded with another
caller-chosen ID.

The input-binding Observation payload has mandatory semantics
`schema_version`, `attempt_id`, `calculation_plan_id`,
`calculation_plan_revision`, `prepared_input_binding_id`,
`execution_snapshot_id`, `input_format`, `logical_name`, `sha256`, and
`size_bytes`. It records one exact durable input binding; it authorizes neither
execution nor scientific acceptance.

Each `OutputArtifact` has mandatory semantics `artifact_kind`, `logical_name`,
`sha256`, and `size_bytes`. Artifact kinds are allowlisted, and a local
absolute path is not portable identity. The output-envelope payload has
mandatory semantics:

```text
schema_version
attempt_id
input_binding_observation_id
execution_snapshot_id
capture_source_id
capture_sequence
capture_status
capture_completeness
artifacts
capture_manifest_sha256
captured_at_utc
```

`capture_completeness` is exactly `partial` or `complete`; partial capture is
never promoted to complete. `capture_status` expresses capture-layer fact only
and does not replace Core runtime state. A caller- or owner-issued `capture_id`
is not authority; the frozen tuple uses the resolved `capture_source_id` and
exact capture manifest.

The Result payload has mandatory semantics `schema_version`, `attempt_id`,
`envelope_observation_id`, `parser_name`, `parser_version`, `result_kind`,
`parse_status`, `facts`, and `diagnostics`. `parse_status` supports exactly the
frozen outcomes `parsed`, `partial`, `unparseable`, and `unsupported`. Facts
are program/output facts, not scientific acceptance, and a parser cannot
modify Attempt state or complete facts across captures.

### Envelope, parsing, and durable views

Malformed envelope metadata or relationships are provenance-boundary invalid:
they produce diagnostics but are not persisted as a legal envelope. By
contrast, a valid envelope with exact captured-byte identities remains legal
when a parser cannot interpret the program output. The envelope is preserved
and a Result records the explicit `unparseable` or `unsupported` parse outcome;
this is neither execution failure nor scientific rejection. A partial capture
remains explicitly partial and is never treated as complete.

These are all legal durable prefixes:

```text
Attempt only
Attempt + input binding
Attempt + input binding + partial envelope
Attempt + input binding + complete envelope
Attempt + input binding + envelope + parse outcome
```

Readers distinguish `awaiting-input-binding`, `awaiting-capture`,
`capture-incomplete`, `awaiting-parse`, `parsed`, `unparseable`, and
`unsupported`. Missing later records are explicitly incomplete, not failure
and not permission to synthesize a record.

Captures, envelopes, and parser Results are append-only. One Result binds one
exact envelope; no fact or provenance is spliced across captures, and new
captures or parser versions never overwrite history. The current view resolves
the Core ownership relationships, selects the latest legal complete capture by
deterministic Core insertion order, or the latest partial capture when no
complete capture exists while marking it incomplete. It exposes all prior
captures and Results plus the selection reason. Filesystem mtime and scan order
never select the current view; runtime status comes from Core, not the parser.

Result creation and reading never advance or reconcile Attempt runtime state,
infer execution success or failure, or grant retry authority. Program status,
capture completeness, parse status, Result existence, and scientific
acceptance remain separate facts. Minimum, transition-state, IRC, workflow,
and other scientific acceptance require a later independent review. Core API
and schema remain unchanged.

## V30-WF-CONTRACT-01 Frozen Minimal Workflow Contract

**Contract status: FROZEN; IMPLEMENTATION NOT AUTHORIZED.** The public package
is `auto_g16.workflow`, with focused tests under `tests/v3/workflow/`. This
contract defines V30-4 only. It changes no Core, Approval, Execution, or Result
API or schema; grants no Transport, PBS, Gaussian, deployment, or live
authority; and does not activate `V30-EXEC-02`.

### Package and public record boundary

`auto_g16.workflow` owns deterministic orchestration data and read-only run
projection. Its public value records are immutable, keyword-only, and deeply
closed over canonical semantic values. Every identity-bearing record identity
is UUIDv5 from a source-controlled, schema-versioned, domain-separated
namespace and the complete canonical authority payload. Exact replay has the
same identity; the same identity with different content conflicts.
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

Node IDs, edge IDs, map IDs, condition IDs, gate IDs, role names, and map item
keys are non-empty and unique in their owning scope. Every referenced node,
edge, role, condition, and gate must exist exactly once. A target input role has
one producer on any active path. Missing, self, duplicate, ambiguous-producer,
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

Contexts exchange typed canonical data. A context must not pass private
implementation objects across a boundary as an implicit contract.

## Artifact Identity

Use hashes where artifact identity must be recorded. A hash is not the default
authority mechanism and does not replace semantic review of the current
`CalculationPlan`.
