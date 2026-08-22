# Auto-G16 v3 Boundary Specification

This document fixes stable dependency and data boundaries only. It does not
select implementation techniques.

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
-> Controller validates the complete current chain
-> execute_once(exact snapshot and bytes)
   -> record_submission_intent(exact Attempt, exact submission intent)
   -> explicit Core WINNER
   -> first effect
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

Immediately before invoking Execution, the Controller must replay the exact
current Scientific Approval, exact Batch Submit Approval member, and exact
Operational Confirmation against the same Attempt, plan, and snapshot. Missing,
conflicting, malformed, stale, cross-Attempt, cross-plan, or cross-snapshot
evidence fails closed before `execute_once(...)`, the Core claim, and every
external effect. The Controller must not pre-claim submission intent.

Approval alone performs no Core transition, workspace mutation, upload,
submission, retry, reconciliation, cancellation, cleanup, or deletion.
Confirmation alone is also non-effectful. Even a complete approval chain makes
zero submission effect unless the claim owned inside `execute_once(...)`
returns `WINNER`; `REPLAY` and every non-winner path make zero effect calls.

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
→ Controller validates exact Approval authority and all other non-effect inputs
→ Controller calls execute_once without pre-claiming
→ execute_once revalidates snapshot/profile/bytes/port
→ execute_once claims Core submission intent
→ WINNER only
→ allocate/verify attempt workspaces
→ materialize/upload input and PBS bytes
→ invoke adapter submission effect at most once
→ record exact outcome/receipt
```

`execute_once(...)` is the single Execution effect entrypoint and owns
`record_submission_intent(...)`. The Controller, Approval, Workflow, and
Transport layers must not claim on its behalf. This boundary is deliberately
at-most-once rather than a distributed transaction: after `WINNER`, a process
crash or ambiguous remote reply cannot roll the claim back and cannot authorize
another effect attempt. It records durable evidence, leaves the Attempt
`UNKNOWN` when effect status is ambiguous, and permits only same-Attempt
read-only reconciliation.

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
offline adapter. The later V30-EXEC-02 composition contract preserves this
public port and selects an RTwin-first real adapter for V30-A. Live RTwin still
requires separate Owner authorization; OpenSSH is deferred and must later
reuse this public execution port. ExecutionSnapshot and transport/effect
behavior remain outside Core.

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

### Additive Gaussian job attribution contract

This additive Result contract does not change the existing
`GaussianLogParser` or any persisted `gaussian-log-facts` outcome. The legacy
public tuple remains exactly:

```text
parser_name    = auto-g16-v3-gaussian-log
parser_version = 1.0.0
result_kind    = gaussian-log-facts
```

Those outcomes remain readable historical program facts, but are insufficient
for ScientificValidation because their whole-log recognition cannot attribute
marker-like bytes to machine output rather than user-controlled echo. They are
never reinterpreted, migrated, backfilled, or rewritten as attributed facts.

The additive public parser is `GaussianJobParser`, with exact tuple:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.0.0
result_kind    = gaussian-job-facts
```

`auto_g16.result` adds only the public `GaussianJobParser` export for this
slice. It exposes the same pure parser shape as the existing parser:
`parse(envelope: OutputEnvelope, artifact_bytes: Mapping[str, bytes]) ->
ParseOutcome`, plus the three exact class-level tuple values above. Grammar,
token, span, and schema-validation helpers remain private; facts are carried by
the existing immutable `ParseOutcome` mapping rather than a second public
persistence record.

`GaussianJobParser` adds no Core record or identity primitive. `ParseOutcome`
keeps outer `schema_version = 1`, its exact public fields, and the existing
UUIDv5 identity over `(envelope_observation_id, parser_name, parser_version,
result_kind)`. Validation dispatches by that complete exact parser tuple. The
legacy tuple uses its unchanged closed facts validator; the new tuple uses the
closed `gaussian-job-facts` schema below. Missing, unknown, mixed, or
unsupported tuple members fail closed. Old and new outcomes may bind the same
envelope and coexist append-only with distinct Result identities.

#### Exact-byte grammar and capability boundary

The new parser is pure and deterministic over exact artifact bytes already
verified against one stored `OutputEnvelope`. Its source-controlled grammar ID
is `auto-g16-v3-gaussian-job-grammar/1`; that ID is a mandatory
`gaussian-job-facts` semantic field. A grammar change requires a new parser
version and produces a different Result identity. Locale, filesystem state,
mtime, line-ending conversion, lossy decoding, runtime probing, checkpoint
files, process state, and caller hints do not select grammar or facts.

The normative input domain is the original Gaussian-log artifact byte string
`B[0:L]`. The parser derives every offset before decoding or normalization.
Only LF (`0x0A`) and CRLF (`0x0D 0x0A`) terminate lines; CRLF is never rewritten
to LF. Scanning left to right produces records `(line_start, content_end,
line_end)`. For LF, `line_end = content_end + 1`; for CRLF,
`line_end = content_end + 2`. The final unterminated line has
`content_end = line_end = L`. Any other `0x0D` in a complete artifact is
`UNPARSEABLE` with `unparseable-line-terminator`. A blank line has content
matching exactly zero or more ASCII SPACE (`0x20`) or TAB (`0x09`) bytes.
No `.strip()`, Unicode whitespace, decoded-character offset, normalized-LF
offset, trimmed offset, or re-encoded offset participates.

Every normative source span is zero-based and half-open on `B`. A single-line
evidence span is `[anchor.line_start, anchor.line_end)`; a multi-line block is
`[first_grammar_line.line_start, final_grammar_line.line_end)`. Thus a span
includes the final line terminator when present, including both CRLF bytes. If
the final grammar line is the unterminated final line, its span ends at `L`.
No other source-span convention is legal.

All grammar patterns below are ASCII byte regular expressions applied with
full-match semantics (`\A...\Z`) to the raw line content, excluding its line
terminator. The notation is closed as follows:

```text
HT0  = [\x20\x09]*
HT1  = [\x20\x09]+
UINT = [0-9]+
INT  = [+-]?[0-9]+
NUM  = [+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?
SYM  = [A-Za-z0-9?'+-]+
```

`NUM` therefore accepts leading signs, leading or trailing decimal points, and
`E/e/D/d` exponents, but not hexadecimal, comma, whitespace-internal, NaN,
Inf, or another `float()` extension. After ASCII conversion (`D/d` becomes
`E/e`), every number must be finite; overflow or a non-finite value is a
grammar failure. Integers are parsed in base ten and booleans are never
integers.

The exact line anchors are:

```text
BLANK               = \AHT0\Z
JOB_START           = \A\x20Entering Gaussian System, Link 0=g16\Z
OTHER_PROGRAM_START = \AHT1Entering Gaussian System, Link 0=g(?:03|09)HT0\Z
SYMBOLIC_START      = \AHT1Symbolic Z-matrix:HT0\Z
CHARGE_MULT         = \AHT1ChargeHT1=HT1INTHT1MultiplicityHT1=HT1[1-9][0-9]*HT0\Z
GRAD_BOUNDARY       = \AHT1(?:Grad){2,}HT0\Z
LINK1_LITERAL       = \AHT0--Link1--HT0\Z
INTERNAL_JOB_STEP   = \AHT1ProceedingHT1toHT1internalHT1jobHT1stepHT1numberHT1[2-9][0-9]*\.HT0\Z
UNSUPPORTED_ORIENTATION = \AHT1Z-Matrix orientation:HT0\Z
NORMAL_TERMINAL     = \AHT1Normal termination of Gaussian 16(?:HT1atHT1[\x20-\x7e]+)?\.?HT0\Z
ERROR_TERMINAL_A    = \AHT1ErrorHT1terminationHT1viaHT1Lnk1eHT1inHT1[\x21-\x7e]+HT1atHT1[\x20-\x7e]+\.HT0\Z
ERROR_TERMINAL_B    = \AHT1ErrorHT1terminationHT1requestHT1processedHT1byHT1linkHT1[0-9]+\.HT0\Z
```

`HT0`, `HT1`, `INT`, and the other named fragments are text substitutions in
these displayed patterns, not literal letters. `JOB_START` alone starts the
supported job. `OTHER_PROGRAM_START` is the closed unsupported-program case.
A genuine v1 multi-job boundary is `LINK1_LITERAL`, `INTERNAL_JOB_STEP`, or a
second `JOB_START` encountered only after `MACHINE_BODY` has been entered. The
same bytes in an input-echo state have zero effect. No naked `Entering Link 1`
substring is a job boundary.

The echo exit is also exact. `JOB_START` enters `INPUT_ECHO`; the unique ordered
sequence `SYMBOLIC_START`, then `CHARGE_MULT`, then at least one intervening
nonblank molecular-specification line, then `GRAD_BOUNDARY` enters
`MACHINE_BODY`. Every byte from `JOB_START` through the full
`GRAD_BOUNDARY` line is echo/control context and emits no scientific-neutral
fact. A duplicate/out-of-order boundary anchor, a `GRAD_BOUNDARY` before the
complete sequence, or more than one possible echo exit is
`UNPARSEABLE`/`unparseable-echo-boundary`. Thus title, route, comment, or
molecular-specification lines equal to optimization, stationary, frequency,
termination, orientation, `LINK1_LITERAL`, or `JOB_START` are ignored while in
an echo state; a spoofed boundary can only make the grammar fail closed. In
this paragraph and the table below, *echo-boundary anchor* means exactly
`SYMBOLIC_START`, `CHARGE_MULT`, or `GRAD_BOUNDARY`; it does not include
`JOB_START`, `LINK1_LITERAL`, or `INTERNAL_JOB_STEP` while an echo state is
active.

The machine-output anchors are:

```text
SCF = \AHT1SCF Done:HT1E\([^\x0d\x0a()]+\)HT1=HT1NUMHT1A\.U\.(?:HT1afterHT1UINTHT1cycles)?HT0\Z

OPT_HEADER = \AHT1ItemHT1ValueHT1ThresholdHT1Converged\?HT0\Z
OPT_ROW_MAX_FORCE = \AHT1MaximumHT1ForceHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_RMS_FORCE = \AHT1RMSHT1ForceHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_MAX_DISP  = \AHT1MaximumHT1DisplacementHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_ROW_RMS_DISP  = \AHT1RMSHT1DisplacementHT1NUMHT1NUMHT1(?:YES|NO)HT0\Z
OPT_PREDICTED     = \AHT1PredictedHT1changeHT1inHT1Energy=HT0NUMHT0\Z
OPT_DONE          = \AHT1Optimization completed\.HT0\Z
STATIONARY        = \AHT1--HT1Stationary point found\.HT0\Z

FREQ_HEAD_1 = \AHT1Harmonic frequencies \(cm\*\*-1\), IR intensities \(KM/Mole\), Raman scatteringHT0\Z
FREQ_HEAD_2 = \AHT1activities \(A\*\*4/AMU\), depolarization ratios for plane and unpolarizedHT0\Z
FREQ_HEAD_3 = \AHT1incident light, reduced masses \(AMU\), force constants \(mDyne/A\),HT0\Z
FREQ_HEAD_4 = \AHT1and normal coordinates:HT0\Z
MODE_NUMBERS = \AHT1UINT(?:HT1UINT){0,2}HT0\Z
SYMMETRIES   = \AHT1SYM(?:HT1SYM){0,2}HT0\Z
FREQUENCIES  = \AHT1FrequenciesHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
RED_MASSES   = \AHT1Red\. massesHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
FORCE_CONSTS = \AHT1Frc constsHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z
IR_INTEN     = \AHT1IR IntenHT1--HT1NUM(?:HT1NUM){0,2}HT0\Z

ORIENTATION = \AHT1(?:Input|Standard) orientation:HT0\Z
SEPARATOR   = \AHT1-{5,}HT0\Z
GEOM_HEAD_1 = \AHT1CenterHT1AtomicHT1AtomicHT1Coordinates \(Angstroms\)HT0\Z
GEOM_HEAD_2 = \AHT1NumberHT1NumberHT1TypeHT1XHT1YHT1ZHT0\Z
ATOM_ROW    = \AHT1UINTHT1UINTHT1INTHT1NUMHT1NUMHT1NUMHT0\Z

THERMO_ZERO_POINT = \AHT1Zero-point correction=HT0NUMHT1\(Hartree/Particle\)HT0\Z
THERMO_ENERGY     = \AHT1Thermal correction to Energy=HT0NUMHT0\Z
THERMO_ENTHALPY   = \AHT1Thermal correction to Enthalpy=HT0NUMHT0\Z
THERMO_GIBBS      = \AHT1Thermal correction to Gibbs Free Energy=HT0NUMHT0\Z
THERMO_SUM_ZPE    = \AHT1Sum of electronic and zero-point Energies=HT0NUMHT0\Z
THERMO_SUM_H      = \AHT1Sum of electronic and thermal Enthalpies=HT0NUMHT0\Z
THERMO_SUM_G      = \AHT1Sum of electronic and thermal Free Energies=HT0NUMHT0\Z
```

The table's phrase *unrelated line* is closed: it means a line that full-matches
none of the named patterns above and triggers none of the prefix rules below.
Only a state whose row explicitly says that unrelated lines stay may ignore
such a line. Prefix testing is on raw content bytes after the initial `HT1`,
not decoded or stripped text. Outside an already admitted child production,
the closed prefix families are:

| Raw literal prefix after `HT1` | Diagnostic ownership when its exact production does not match |
| --- | --- |
| `Normal termination` or `Error termination` | `unparseable-terminal` |
| `SCF Done:`, or any of the seven displayed thermochemistry labels through and including `=` | `unparseable-numeric-token` only when every fixed literal/separator and the one numeric field slot is structurally present and that slot fails `NUM`/finite conversion; otherwise `unparseable-malformed-prefix` |
| `Item`, `Maximum Force`, `RMS Force`, `Maximum Displacement`, `RMS Displacement`, `Predicted change in Energy=`, `Optimization completed`, or `-- Stationary point found` | `unparseable-malformed-prefix` |
| `Harmonic frequencies`, `activities`, `incident light`, `and normal coordinates:`, `Frequencies`, `Red. masses`, `Frc consts`, or `IR Inten` | `unparseable-malformed-prefix` |
| `Input orientation:`, `Standard orientation:`, `Z-Matrix orientation:`, `Center Atomic Atomic Coordinates`, or `Number Number Type X Y Z` | `unparseable-malformed-prefix` |

`unparseable-orphan-anchor` applies only to an exact full-match of an
otherwise valid named anchor in a state where that anchor is illegal. Thus an
exact substate-only optimization or stationary pattern seen directly in
`MACHINE_BODY` is an orphan; so is exact `FREQ_HEAD_2`, `FREQ_HEAD_3`,
`FREQ_HEAD_4`, `FREQUENCIES`, `RED_MASSES`, `FORCE_CONSTS`, or `IR_INTEN` in
that state. In an admitted optimization, frequency, or geometry child, another
exact named anchor that is illegal in the current child state is likewise the
child's state-legality failure with this orphan code. A merely similar or
malformed prefix is never an orphan.
Separator, mode-number, symmetry, and atom-row-shaped lines have no standalone
meaning in `MACHINE_BODY` and are unrelated there; after their owning child
state has begun, the child state decides them. Prefix-family rules apply only
in `MACHINE_BODY` and `FREQUENCY_BODY` (including a line reprocessed into
either state); child states instead apply their own structural productions.
Exact-anchor orphan ownership also applies inside those child states. Both are
disabled in `PREAMBLE`, `TERMINATED`, and throughout the three input-echo
states, where the applicable state row alone decides the line. This makes a
user-echoed malformed scientific label as non-evidentiary as a valid echoed
label.

The FSM and its failure behavior are normative. Named transitions within one
state must be pairwise disjoint. If two named patterns match the same line, or
an omitted transition would be needed, the complete capture is
`UNPARSEABLE`/`unparseable-ambiguous-transition`; there is no priority, best
match, nearest marker, or last useful block.

| State | Accepted pattern and next state | Evidence/span | Any other relevant transition |
| --- | --- | --- | --- |
| `PREAMBLE` | `JOB_START -> INPUT_ECHO`; `OTHER_PROGRAM_START -> UNSUPPORTED` | none | other lines stay; EOF is `unparseable-job-start` |
| `INPUT_ECHO` | first `SYMBOLIC_START -> INPUT_MOLECULE` | none | `CHARGE_MULT` or `GRAD_BOUNDARY` fails echo boundary; every other line stays and emits nothing |
| `INPUT_MOLECULE` | first `CHARGE_MULT -> INPUT_MOLECULE_BOUND` | none | `SYMBOLIC_START` or `GRAD_BOUNDARY` fails echo boundary; every other line stays |
| `INPUT_MOLECULE_BOUND` | after at least one nonblank intervening line, `GRAD_BOUNDARY -> MACHINE_BODY` | none | `SYMBOLIC_START` or `CHARGE_MULT`, or `GRAD_BOUNDARY` before a nonblank intervening line, fails echo boundary; every other line stays |
| `MACHINE_BODY` | `SCF` stays; `OPT_HEADER -> OPT_MAX_FORCE`; `FREQ_HEAD_1 -> FREQ_HEAD_2_STATE`; `ORIENTATION -> GEOM_SEP_1`; a thermo line stays; legal terminal -> `TERMINATED`; multi-job anchor -> `LINK1_BOUNDARY`; `OTHER_PROGRAM_START` or `UNSUPPORTED_ORIENTATION -> UNSUPPORTED` | SCF/thermo/terminal lines use full-line spans | the closed prefix/orphan rules above apply; a repeated thermochemistry key is `unparseable-duplicate-evidence`; any `SYMBOLIC_START`, `CHARGE_MULT`, or `GRAD_BOUNDARY` is `unparseable-echo-boundary`; unrelated lines stay |
| `OPT_MAX_FORCE` | `OPT_ROW_MAX_FORCE -> OPT_RMS_FORCE` | none yet | child production precedence below selects numeric-token only for a structurally valid row with an invalid numeric field; every other mismatch is `unparseable-optimization-block` |
| `OPT_RMS_FORCE` | `OPT_ROW_RMS_FORCE -> OPT_MAX_DISP` | none yet | same ownership rule |
| `OPT_MAX_DISP` | `OPT_ROW_MAX_DISP -> OPT_RMS_DISP` | none yet | same ownership rule |
| `OPT_RMS_DISP` | `OPT_ROW_RMS_DISP -> OPT_AFTER_ROWS` | none yet | same ownership rule |
| `OPT_AFTER_ROWS` | optional one `OPT_PREDICTED` stays; `OPT_DONE -> OPT_STATIONARY`; any other line returns to `MACHINE_BODY` and is reprocessed once | `OPT_DONE` full-line span only on completion path | duplicate predicted fails; a complete non-converged table emits no marker evidence |
| `OPT_STATIONARY` | `STATIONARY -> MACHINE_BODY` | `STATIONARY` full-line span | anything else fails block; neither naked marker is evidence |
| `FREQ_HEAD_2_STATE` | `FREQ_HEAD_2 -> FREQ_HEAD_3_STATE` | block begins at `FREQ_HEAD_1.line_start` | anything else is `unparseable-frequency-block` |
| `FREQ_HEAD_3_STATE` | `FREQ_HEAD_3 -> FREQ_HEAD_4_STATE` | none | same failure |
| `FREQ_HEAD_4_STATE` | `FREQ_HEAD_4 -> FREQUENCY_BODY_EMPTY` | none | same failure |
| `FREQUENCY_BODY_EMPTY` | blank lines stay; `MODE_NUMBERS -> FREQ_SYMMETRY` | none | every other line is `unparseable-frequency-block`; a recognized frequency section must contain a complete group |
| `FREQUENCY_BODY` | blank/unrelated displacement lines stay; `MODE_NUMBERS -> FREQ_SYMMETRY`; a new `FREQ_HEAD_1 -> FREQ_HEAD_2_STATE`; `SCF`, `OPT_HEADER`, `ORIENTATION`, each thermo line, each legal terminal, each multi-job anchor, `OTHER_PROGRAM_START`, and `UNSUPPORTED_ORIENTATION` apply exactly as in `MACHINE_BODY` | none | orphan `FREQUENCIES`, `RED_MASSES`, `FORCE_CONSTS`, or `IR_INTEN` fails; echo-boundary anchors fail as in `MACHINE_BODY` |
| `FREQ_SYMMETRY` | `SYMMETRIES` with same 1..3 cardinality -> `FREQ_VALUES` | none | a structurally wrong line is `unparseable-frequency-block` |
| `FREQ_VALUES` | `FREQUENCIES` with same cardinality -> `FREQ_RED_MASSES` | values retained | child production precedence below selects numeric-token only after valid prefix/separators/cardinality; every other mismatch is frequency-block |
| `FREQ_RED_MASSES` | `RED_MASSES` with same cardinality -> `FREQ_FORCE_CONSTS` | none | same ownership rule |
| `FREQ_FORCE_CONSTS` | `FORCE_CONSTS` with same cardinality -> `FREQ_IR_INTEN` | none | same ownership rule |
| `FREQ_IR_INTEN` | `IR_INTEN` with same cardinality -> `FREQUENCY_BODY` | frequency-block span is mode line through IR line | same ownership rule |
| `GEOM_SEP_1` | `SEPARATOR -> GEOM_HEAD_1_STATE` | block begins at orientation heading | anything else is `unparseable-geometry-block` |
| `GEOM_HEAD_1_STATE` | `GEOM_HEAD_1 -> GEOM_HEAD_2_STATE` | none | same failure |
| `GEOM_HEAD_2_STATE` | `GEOM_HEAD_2 -> GEOM_SEP_2` | none | same failure |
| `GEOM_SEP_2` | `SEPARATOR -> GEOM_ROWS` | none | same failure |
| `GEOM_ROWS` | first/next `ATOM_ROW` stays; `SEPARATOR` after at least one row -> `MACHINE_BODY` | complete geometry span is heading through closing separator | wrong row shape or valid-integer row constraint is `unparseable-geometry-row`; a structurally valid row with an invalid numeric field is numeric-token; malformed/missing closure or EOF is geometry-block |
| `TERMINATED` | `BLANK` stays; genuine multi-job anchor -> `LINK1_BOUNDARY`; `OTHER_PROGRAM_START -> UNSUPPORTED`; another legal terminal -> failure | none | second terminal is `unparseable-terminal`; any other line is `unparseable-trailing-content` |
| `LINK1_BOUNDARY` | terminal classification | none | always `UNSUPPORTED`/`unsupported-multiple-job` |

At EOF, `PREAMBLE` reports `unparseable-job-start`; any echo state reports
`unparseable-echo-boundary`; an optimization, frequency (including
`FREQUENCY_BODY_EMPTY`), or geometry substate
reports its corresponding block code; `MACHINE_BODY` or `FREQUENCY_BODY`
reports `unparseable-terminal`; and `TERMINATED` succeeds. A line with a
recognized numeric field label but a token outside `NUM`, or a converted
non-finite value, reports `unparseable-numeric-token`. A legal numeric token
count/cardinality mismatch instead reports the owning block code. A malformed
`Normal termination` or `Error termination` prefix in machine context reports
`unparseable-terminal`.

#### Primary diagnostic ownership and precedence

`gaussian-job-facts` v1 has one primary diagnostic, never a diagnostic set.
`PARSED` persists `diagnostics = ()`; every terminal `PARTIAL`, `UNSUPPORTED`,
or `UNPARSEABLE` outcome persists a one-item tuple containing its single closed
code. Parsing and child productions are strictly left-to-right fail-fast over
original bytes and stop as soon as the active normative production can prove
failure.
No later byte is semantically examined for a competing failure, no second code
is collected, and no parent production may translate an already-owned child
failure into a broader code.

Within an admitted production, ownership is evaluated in this exact order:

1. current FSM/state legality;
2. required structural line or row shape;
3. closed field designation and field count;
4. each designated numeric field in left-to-right byte order;
5. required block closure or completeness.

A later level is evaluated only after all earlier levels succeed. Entry through
`OPT_HEADER`, `FREQ_HEAD_1`, or `ORIENTATION` admits the corresponding child;
that child owns every subsequent failure until it either returns to
`MACHINE_BODY`/`FREQUENCY_BODY` or terminates parsing. An exact valid named
anchor in a state where it is illegal is owned immediately by
`unparseable-orphan-anchor`. A malformed lookalike cannot be an orphan. Outside
an admitted child, one of the closed raw-prefix families above is owned by
`unparseable-malformed-prefix`, except the separately frozen terminal and
structurally complete direct SCF/thermochemistry numeric cases.

For diagnostic classification only, a raw field token is the maximal nonempty
byte sequence matching `[^\x20\x09\x0d\x0a]+`; this does not widen any accepted
line grammar. An optimization row has valid shape only when its exact label,
two raw numeric-field slots, final `YES|NO`, HT separators, and field count are
present. A frequency value row has valid shape only when its exact label,
`HT1--HT1`, the already-required 1..3 field slots, HT separators, and exact
cardinality are present. A geometry atom row has valid shape only when it has
exactly six HT-separated raw field slots after initial `HT1`, in the frozen
center/atomic-number/atomic-type/X/Y/Z order. Once shape succeeds, an invalid
`UINT`/`INT`/`NUM` field or non-finite conversion is
`unparseable-numeric-token`; the enclosing block emits nothing else. If more
than one field is invalid, the field with the smallest token start owns the
failure; equal starts use the displayed field order. Wrong row field count,
missing or extra structural tokens, a noncontiguous but valid integer center,
or an out-of-range but valid integer atomic number is
`unparseable-geometry-row`, never numeric-token. Within `GEOM_ROWS`, a line
whose content after initial `HT1` begins with `-` is a closure candidate:
exact `SEPARATOR` closes only after at least one row, while any malformed
separator or a separator before the first row is
`unparseable-geometry-block`; it is never classified as an atom row.

Consequently, `Frequencies -- NaN` in the legally required `FREQ_VALUES` state
has valid prefix/separators/cardinality and is uniquely
`unparseable-numeric-token`. A wrong frequency prefix, separator, or field
count in that state is `unparseable-frequency-block`; valid numeric rows
followed by a missing required continuation or closure are also frequency-block.
A valid geometry opener followed by a wrong required header/separator is
`unparseable-geometry-block`; a six-field row containing `NaN` is numeric-token;
a five- or seven-field row is geometry-row; valid rows without a closing
separator are geometry-block. In an optimization child, a structurally valid
row with an invalid numeric slot is numeric-token, while a wrong row/marker
sequence is optimization-block. An exact `STATIONARY` in an illegal state is
orphan-anchor and cannot compete with an optimization code.

EOF is a failure of the currently active production. EOF in an optimization,
frequency, or geometry child is owned by its block code; EOF in an echo state
is echo-boundary; EOF in `PREAMBLE` is job-start; and EOF in `MACHINE_BODY` or
`FREQUENCY_BODY` is terminal. EOF never creates an orphan, row, or numeric
failure. An earlier malformed geometry row therefore terminates parsing before
any later malformed frequency token can have authority.

Thermochemistry cardinality is a local child check within its otherwise
unchanged direct machine-fact production. Every candidate that is legal in the
current FSM state runs this exact, non-reorderable pipeline:

```text
validate exact line structure
-> resolve the already-frozen canonical thermochemistry fact key
-> validate the current numeric token against NUM
-> convert the current value and require it to be finite
-> test that key against previously committed thermochemistry evidence
-> commit key/value/source span when unseen
```

Only a current line that has passed the first four steps is eligible for the
duplicate check. A structural failure owns its existing structural diagnostic;
an invalid or non-finite current token owns `unparseable-numeric-token` and its
exact token span, even when the same key was committed earlier. Such a line is
never inserted into the seen-key set, and the outcome is `UNPARSEABLE`. If the
current fully valid canonical key was already committed in this supported job,
`unparseable-duplicate-evidence` owns the failure before the current evidence
is committed, and the outcome is `UNPARSEABLE`. Equal and unequal repeated
values are equally duplicates;
identical evidence is not an idempotent replay inside one ParseOutcome.

The duplicate check is scoped only to successfully committed earlier
thermochemistry evidence in this one supported Gaussian job. Equality is the
exact canonical fact key produced by the already-frozen mapping, never raw
spelling, display label, value, whitespace, or span. It does not cross a job,
capture, parser outcome, Attempt, or repository record. The duplicate
conformance span is always the full current/second line
`[line_start,line_end)`: it includes its LF or CRLF terminator, or ends at
artifact length `L` when the current line is the final unterminated line. It
never points to the first occurrence, both occurrences, a token-only span, or
a zero-width position.

The conformance failure position is the lowest original-byte position where
that active production proves failure. A numeric failure owns its exact token
span; a row-shape failure or exact orphan owns the full offending line span; a
block/header failure owns the full offending structural line. At EOF, ordering
position is `L`, while the non-zero conformance span is the full final
successfully consumed grammar-bearing line under the existing half-open span
rule. If no grammar-bearing line has been consumed, the conformance span is the
explicit no-span value, never a zero-width interval. Matrix outcomes have the
explicit no-position/no-span value because grammar is not run. The v1
`diagnostics` payload remains a tuple of code strings and does not add a
persisted position/span field; these positions are nevertheless normative for
implementation conformance and first-failure selection.

The exact optimization source spans are the `OPT_DONE` and `STATIONARY` full
lines, but they become evidence only after the entire ordered convergence block
has matched. Each frequency block span starts at its `MODE_NUMBERS.line_start`
and ends at its `IR_INTEN.line_end`; mode numbers must be strictly increasing
and contiguous across groups. Each geometry span starts at
`ORIENTATION.line_start` and ends at the closing `SEPARATOR.line_end`.
The literal `Input orientation:` heading maps only to
`orientation_kind = input-orientation`; `Standard orientation:` maps only to
`orientation_kind = standard-orientation`. `ATOM_ROW` fields map left to right
to center, atomic number, atomic type, X, Y, and Z. Atomic type is parsed and
discarded as non-authority. A center sequence other than exactly `1..N` or an
atomic number outside `0..118` is `unparseable-geometry-row`. An integer or
coordinate token outside its closed `INT`/`UINT`/`NUM` grammar, or a converted
non-finite coordinate, is `unparseable-numeric-token` after row shape succeeds.
Recognized malformed or truncated blocks emit no partial block fact and make a
complete capture `UNPARSEABLE`.

One supported job span is exactly
`[JOB_START.line_start, terminal.line_end)`, including both line terminators
when present. A final unterminated terminal line ends at `L`. After the terminal
line only `BLANK` lines are legal; another job/multi-job anchor is
`UNSUPPORTED`, and any other byte content is `UNPARSEABLE`. A missing legal
terminal, two legal terminals, or terminal-like text outside `MACHINE_BODY`
cannot be accepted as one parsed job.

Artifact verification precedes status selection. A supplied artifact-name set,
type, size, or SHA mismatch raises `MalformedEnvelopeError` and is never
converted into a `ParseStatus`. After exact verification, artifact cardinality
is fixed:

| CaptureCompleteness | Gaussian-log artifact count | Result |
| --- | ---: | --- |
| `PARTIAL` | 0 | `PARTIAL`, empty facts, `capture-partial` |
| `PARTIAL` | 1 | `PARTIAL`, empty facts, `capture-partial` |
| `PARTIAL` | >1 | `PARTIAL`, empty facts, `capture-partial` |
| `COMPLETE` | 0 | `UNSUPPORTED`, empty facts, `unsupported-gaussian-log-cardinality` |
| `COMPLETE` | 1 | run the exact grammar above |
| `COMPLETE` | >1 | `UNSUPPORTED`, empty facts, `unsupported-gaussian-log-cardinality` |

For one complete Gaussian-log artifact, exactly one supported job with a legal
terminal and complete deterministic attribution is `PARSED`. A genuine Link1,
second job, `OTHER_PROGRAM_START`, or `UNSUPPORTED_ORIENTATION` is
`UNSUPPORTED`; these are the only deliberate version-1 capability-boundary
patterns. Every other unmatched structural claim is malformed or ambiguous.
Malformed, contradictory, incomplete, or ambiguous bytes are `UNPARSEABLE`. A complete
capture never produces `PARTIAL`; uncertainty is not capture incompleteness.
Only `PARSED` carries the closed facts payload.

`PARSED` outcomes persist an empty diagnostics tuple. Non-`PARSED` outcomes
persist exactly one diagnostic code and no prose. This table is the complete
source-controlled vocabulary and single-owner production map:

| Diagnostic code | Owning production | Entry precondition and exact failure | Forbidden competing codes |
| --- | --- | --- | --- |
| `capture-partial` | capture/cardinality matrix | verified envelope is `PARTIAL`, for 0, 1, or >1 Gaussian logs; grammar is not run | every grammar/unsupported code |
| `unsupported-gaussian-log-cardinality` | capture/cardinality matrix | verified complete envelope has 0 or >1 Gaussian logs; grammar is not run | every grammar code |
| `unsupported-program` | FSM capability boundary | exact `OTHER_PROGRAM_START` in a legal non-echo state | every unparseable/prefix code |
| `unsupported-multiple-job` | FSM capability boundary | exact genuine multi-job anchor in `MACHINE_BODY`, `FREQUENCY_BODY`, or `TERMINATED` | orphan, prefix, trailing, and all block codes |
| `unsupported-valid-gaussian-grammar` | FSM capability boundary | exact `UNSUPPORTED_ORIENTATION` in machine context | malformed-prefix, orphan, and geometry codes |
| `unparseable-line-terminator` | raw line tokenizer | first lone `0x0D` in a complete artifact | every FSM/child code |
| `unparseable-job-start` | `PREAMBLE` | EOF before exact `JOB_START` after all earlier bytes were legal preamble | all other EOF/anchor codes |
| `unparseable-echo-boundary` | active echo state | exact out-of-order/duplicate echo-boundary anchor, or EOF before echo exit | orphan, malformed-prefix, and all evidence codes |
| `unparseable-ambiguous-transition` | active FSM state | two named exact transitions match the same current line | either transition's specific code |
| `unparseable-orphan-anchor` | active non-echo machine-output or child FSM state | exact otherwise-valid named anchor occurs where that exact anchor is illegal | malformed-prefix and every parent/child structural/numeric code |
| `unparseable-malformed-prefix` | machine-context prefix dispatcher | closed grammar-bearing prefix resembles a production but neither matches an exact anchor nor has a complete direct numeric-line shape, before a child is admitted | orphan, all child block/row codes, and numeric-token unless the direct numeric-line shape is complete |
| `unparseable-duplicate-evidence` | thermochemistry cardinality check | current FSM state legally admits the exact thermochemistry production; current structure, canonical-key resolution, numeric grammar, and finite conversion all succeed; prior committed evidence with that exact key exists; accepting the current fully valid evidence would make cardinality greater than one; authority span is the full current duplicate line `[line_start,line_end)` | numeric-token, the thermochemistry structural diagnostic, orphan-anchor, and every generic block diagnostic |
| `unparseable-optimization-block` | admitted optimization child | required row/marker shape or sequence is wrong, duplicated, prematurely terminated, or incomplete at EOF | orphan and numeric-token after valid row shape |
| `unparseable-frequency-block` | admitted frequency child | required header/prefix/separator/cardinality/continuation/closure is wrong or missing, including EOF | orphan and numeric-token after valid value-row shape |
| `unparseable-geometry-block` | admitted geometry child except atom-row production | required table header/separator/closure is wrong or missing, including EOF | orphan, geometry-row, and numeric-token |
| `unparseable-geometry-row` | `GEOM_ROWS` atom-row production | row has wrong field shape/count, or valid integers violate center contiguity or atomic-number range | geometry-block and numeric-token |
| `unparseable-numeric-token` | admitted numeric-field production | structural shape, field designation, and cardinality succeeded, then the earliest designated token fails `UINT`/`INT`/`NUM` or finite conversion | malformed-prefix, orphan, block, and row codes |
| `unparseable-terminal` | required terminal production | malformed terminal in `MACHINE_BODY`/`FREQUENCY_BODY`, repeated legal terminal in `TERMINATED`, or EOF in `MACHINE_BODY`/`FREQUENCY_BODY` before a legal terminal | malformed-prefix, orphan, block, and trailing-content |
| `unparseable-trailing-content` | `TERMINATED` | first nonblank line after the one accepted terminal is neither a genuine multi-job nor supported-program boundary | terminal and all child codes |

The first owned failure stops parsing; table order is descriptive and is never
a ranking or tie-break mechanism. `OTHER_PROGRAM_START` therefore maps only to
`unsupported-program`, every genuine multi-job anchor only to
`unsupported-multiple-job`, and `UNSUPPORTED_ORIENTATION` only to
`unsupported-valid-gaussian-grammar`. Invalid source-span bindings are rejected
by `ResultProvenanceService` before append and on reopen; they do not create a
second parser diagnostic or a legal `ParseOutcome`. Human-readable explanation
may be emitted outside persisted semantics only.

Given the same exact envelope, artifact bytes, and parser tuple, two conforming
implementations must produce the same status, job span, evidence spans, facts,
source ordering, primary failure position/span (or the same matrix no-position),
singleton diagnostic code, payload, and Result identity.
Evidence collections sort by `start`, then `end`, then the closed kind order
`termination`, `optimization`, `stationary`, `scf`, `frequency`,
`thermochemistry`, `geometry`. Frequency and geometry collections otherwise
retain byte-source order. No set or implementation traversal order is a
serialization authority.

#### Closed attributed facts schema

For the new exact parser tuple, non-empty `facts` has
`facts_schema_version = 1` and exactly these top-level semantics:

```text
facts_schema_version
grammar_id
source_artifact
job_section
program_status
normal_termination_count
error_termination_count
termination_evidence
optimization_completed_marker
optimization_completed_evidence
stationary_point_marker
stationary_point_evidence
scf_calculation_count
scf_calculations
final_energy_hartree
frequency_count
frequency_parse_complete
imaginary_frequency_count
frequencies_cm-1
frequency_blocks
thermochemistry
geometry_blocks
```

The schema is closed recursively: missing keys, unknown keys, wrong scalar or
container types, booleans used as integers, non-finite numbers, invalid enum
values, inconsistent counts/aggregates, or version drift fail closed on
construction and reopen. `source_artifact` binds exactly the stored
`envelope_observation_id`, `artifact_kind = gaussian-log`, portable logical
name, lowercase SHA-256, and non-negative byte size. Exactly one such artifact
of kind `gaussian-log` is supported as the fact source. Other envelope
artifacts remain part of the exact supplied-byte set and are verified but do
not contribute facts. The parser verifies all supplied bytes against the
envelope before recognition.

`source_artifact` has exactly `envelope_observation_id`, `artifact_kind`,
`logical_name`, `sha256`, and `size_bytes`. Every `source_span` has exactly
those five binding fields plus `start` and `end`. A span is a zero-based
half-open byte interval `[start, end)` with integer
`0 <= start < end <= size_bytes`. `job_section` is one such full source span.
Each termination, optimization, stationary-point, SCF, frequency-block,
thermochemistry, and geometry-block item carries a source span equal in its
five binding fields to `source_artifact` and contained by `job_section`.
Repeated evidence is ordered by `(start, end)` and distinct block instances may
not overlap; only the intentional containment of evidence by `job_section` is
allowed. Cross-envelope, cross-artifact, out-of-range, reversed, duplicate,
unordered, or otherwise impossible overlap fails closed.

`ResultProvenanceService` validates these relationships both before append and
while reopening stored outcomes: the exact envelope exists for the same
Attempt, the named artifact tuple equals the stored envelope artifact, every
span satisfies the closed interval/containment/order rules, the complete
parser tuple dispatches to the correct schema, and the Result identity is
recomputed. Existing Core append semantics make exact replay idempotent and
make the same Result identity with any different payload or span a conflict.
The service does not reconstruct bytes from spans and spans grant no execution
or scientific authority.

Termination, optimization-completed, stationary-point, SCF, frequency, and
thermochemistry facts arise only from grammar-recognized machine-output
records inside the exact job section. A raw occurrence in title, route,
comment, input echo, molecular specification, or other non-machine-output
context is ignored. `termination_evidence` items have exactly `kind`
(`normal-termination` or `error-termination`) and `source_span`.
Optimization and stationary evidence are ordered tuples of source spans.
`scf_calculations` items have exactly `energy_hartree` and `source_span`.
`thermochemistry` is a closed mapping over the existing seven allowlisted
thermochemistry names; each present item has exactly `value_hartree` and
`source_span`. Aggregates are exact projections of their attributed evidence:
counts match item cardinality, booleans match empty/non-empty evidence,
`final_energy_hartree` is the last attributed SCF value or null, and all finite
numerical values preserve source order. `program_status` is derived only from
the one recognized terminal record. A `PARSED` job has exactly one normal or
error terminal item, never both; the corresponding count is one and the other
is zero. Missing, repeated, malformed, or structurally contradictory terminal
evidence makes a complete capture `UNPARSEABLE`.

Each `frequency_blocks` item has exactly `source_span` and
`frequencies_cm-1`, a non-empty ordered tuple of one to three finite values as
required by the version-1 grammar. The top-level frequency tuple is the ordered
concatenation of all blocks; count and imaginary count are derived exactly, and
`frequency_parse_complete` is true for every `PARSED` outcome. A recognized
empty group, invalid token, wrong block cardinality, truncation, overlap, or
mixed context makes the complete capture `UNPARSEABLE`; no token is silently
skipped. Result does not decide whether the frequency set proves a minimum.

`geometry_blocks` contains every complete recognized machine-emitted
orientation block in byte order, not merely the first, last, or most favorable
one. Each block has exactly:

```text
orientation_kind = input-orientation | standard-orientation
units             = angstrom
source_span
atoms
```

`atoms` is a non-empty ordered tuple. Centers are contiguous one-based
integers; each atom has exactly `center`, integer `atomic_number` in `0..118`,
and finite `x`, `y`, `z` Cartesian coordinates. `source_span` uses the exact
closed mapping above. Atomic number `0` is preserved
as an explicit dummy-center fact and is unsupported by downstream minimum
validation; Result does not silently remove or reinterpret it. If any
recognized orientation block is malformed, truncated, mixed, non-contiguous,
non-finite, or incomplete, a complete capture is `UNPARSEABLE`; the parser
never skips that block or falls back to another geometry. Result calls these
generic geometry blocks and never labels one an optimized geometry or a
minimum.

#### Narrow reuse adjudication

The reuse audit is limited to `auto_g16.result.GaussianLogParser`, the public
Result models/service and their adjacent tests, plus the legacy
`skills/auto-g16-rtwin-pbs/scripts/gaussian_log.py` grammar/token helpers and
their adjacent tests.

- **PORT:** the existing `OutputEnvelope` artifact verification,
  `ParseOutcome` outer schema version 1, deterministic Result UUIDv5 tuple,
  append-only Core Result persistence, exact replay/conflict behavior, and
  same-Attempt provenance resolution.
- **WRAP:** preserve `GaussianLogParser` v1 and its historical
  `gaussian-log-facts` validator unchanged as a separate public parser tuple;
  it is readable history, not attributed ScientificValidation evidence.
- **EXTRACT:** finite D/E numeric-token conversion, SCF/thermochemistry field
  conversion, frequency-token parsing, and orientation-row parsing only after
  the new state machine has established an exact machine-output context. Each
  extracted primitive needs new context-bound and malformed-token tests.
- **REWRITE:** job/echo/context recognition, job multiplicity detection,
  frequency-block assembly, all-geometry-block assembly, and byte-span
  attribution. Existing implementations scan a whole log or select a last
  orientation and therefore cannot safely distinguish user echo or preserve
  complete attributed evidence.
- **DROP:** whole-log substring counts, membership/rfind marker authority,
  unscoped line regexes, last-job/last-orientation selection, silent malformed
  block skipping, and any legacy minimum/TS classification in the new parser.
- **DEFER:** multi-job/Link1 selection, checkpoint-derived geometry, scientific
  minimum/TS/IRC classification, scientific acceptance, live recapture, and
  Gaussian reruns.

This additive contract changes no Core API/schema and reopens no Execution,
Approval, or Workflow contract. It authorizes no ScientificValidation
implementation, transport, PBS, Gaussian, deployment, retry, or live action.

## V30-MIN-VALIDATE-CONTRACT-01 Minimum Scientific Validation Contract

**Contract status: FROZEN / INTEGRATED; IMPLEMENTATION NOT AUTHORIZED.**
The future public package is `auto_g16.scientific_validation`, with focused
tests under `tests/v3/scientific_validation/`. It owns post-Result scientific
classification and human scientific acceptance only. It changes no Core or
Result API/schema, imports no Approval, Execution, Workflow, Transport, or
program adapter, and grants no implementation, selector, effect, retry, or live
authority.

### Public boundary and exact provenance

The public inventory is limited to:

```text
MinimumValidationClassification
MinimumValidationOutcome
ScientificAcceptance
SQLiteScientificValidationStore
validate_minimum
record_minimum_validation
record_scientific_acceptance
require_scientific_acceptance
ScientificValidationError
ScientificValidationConflictError
ScientificValidationPersistenceIntegrityError
```

`MinimumValidationClassification` is exactly `VALIDATED_MINIMUM`,
`NOT_MINIMUM`, `INCOMPLETE`, or `UNSUPPORTED`. Public records are immutable,
keyword-only, and deeply closed over canonical semantic values. No warning,
probability, partial-minimum, or caller-defined outcome exists.

### Exact public shape and identity constants

The source-controlled schema version is exactly `1`, validation policy ID is
exactly `auto-g16-v3-minimum-validation`, and validation policy version is
exactly `1.0.0`. These values are implicit and are not caller-selectable or
additional public exports.

The ScientificValidation UUID namespace root is exactly
`f4617d31-5b90-5c79-888a-9b9ccec5e612`. The only identity domains and their
derived namespaces are:

```text
minimum-validation-outcome  6b963167-a628-5135-ad33-a38383cbf137
scientific-acceptance        333f02d6-ee57-53e6-bd43-3e02a7046e85
```

Each domain namespace is derived exactly as:

```python
uuid5(
    SCIENTIFIC_VALIDATION_NAMESPACE,
    "auto_g16.scientific_validation/v1/" + domain,
)
```

Canonical semantic nodes are tagged by exact runtime type as follows; Boolean
and integer are distinct, and the integer case excludes Boolean values:

```text
None          ["null", null]
bool          ["boolean", value]
int           ["integer", value]
finite float  ["float", value]
str           ["string", value]
mapping       ["mapping", [[key, canonical(value)], ...]]
sequence      ["sequence", [canonical(item), ...]]
```

Mapping keys are strings sorted lexically; sequence order is preserved.
Unsupported types, non-finite floats, and container cycles fail closed.
Canonical bytes are exactly:

```python
json.dumps(
    canonical_node,
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=False,
).encode("utf-8")
```

The UUIDv5 name is the UTF-8 text of that encoding applied to:

```python
{
    "schema_version": 1,
    "domain": domain,
    "authority": complete_record_authority_payload,
}
```

ScientificValidation extracts this reviewed algorithm into its own private
implementation. It does not import Workflow, Core private encoding, or private
identity helpers, and it never substitutes `repr`, `pickle`, `hash`, ordinary
unsorted dictionary JSON, or platform-dependent serialization.

`MinimumValidationOutcome` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
minimum_validation_outcome_id: str  # init=False; deterministic UUIDv5
validation_policy_id: str
validation_policy_version: str
calculation_plan_id: str
calculation_plan_revision: int
attempt_id: str
input_binding_observation_id: str
envelope_observation_id: str
parse_result_id: str
parser_name: str
parser_version: str
result_kind: str
source_artifact: Mapping[str, object] | None
job_section: Mapping[str, object] | None
accepted_optimization_span: Mapping[str, object] | None
accepted_stationary_span: Mapping[str, object] | None
selected_geometry_block: Mapping[str, object] | None
selected_frequency_blocks: tuple[Mapping[str, object], ...]
selected_frequencies_cm1: tuple[float, ...]
classification: MinimumValidationClassification
reason_code: str
```

Schema and policy fields equal the fixed values above. Every ID is a non-empty
canonical string and `calculation_plan_revision` is a positive non-boolean
integer. Parser fields preserve the exact supplied `ParseOutcome` tuple.
Populated mappings and sequences are deeply immutable canonical semantic
copies of persisted Result facts, never bytes or reparsed evidence. When
evidence is unavailable at the first-applicable classification stage, an
optional mapping is `None` and each selected-frequency tuple is empty; no
placeholder mapping is invented. Populated `selected_frequencies_cm1` is
exactly the ordered concatenation of all populated
`selected_frequency_blocks`. A populated geometry block preserves its complete
Result-owned orientation kind, units, source span, and atoms.

`minimum_validation_outcome_id` binds every field above except itself, using
`classification.value` in the authority payload. Exact replay has the same ID
and record; any authority-field change creates a new ID; same ID with different
payload raises `ScientificValidationConflictError`.

`ScientificAcceptance` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
scientific_acceptance_id: str  # init=False; deterministic UUIDv5
minimum_validation_outcome_id: str
validation_policy_id: str
validation_policy_version: str
calculation_plan_id: str
calculation_plan_revision: int
attempt_id: str
parse_result_id: str
classification: MinimumValidationClassification
reviewer_id: str
review_evidence: Mapping[str, object]
```

All expanded outcome-binding fields exactly equal the persisted referenced
outcome, whose classification must be `VALIDATED_MINIMUM`. `reviewer_id` is a
non-empty canonical string. `review_evidence` is a non-empty deeply immutable
mapping whose nested values are limited to `None`, exact booleans, exact
integers, finite floats, strings, mappings with non-empty string keys, and
finite sequences of those values. Bytes, paths, datetimes, callables,
non-finite floats, cycles, and arbitrary objects fail closed. Reviewer identity
and review evidence participate in acceptance identity, so multiple explicit
acceptances for one outcome are legal and no current/latest pointer exists.

The exact public service signatures are:

```python
validate_minimum(
    core_store: SQLiteRuntimeStore,
    input_binding: InputBinding,
    envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
) -> MinimumValidationOutcome

record_minimum_validation(
    store: SQLiteScientificValidationStore,
    outcome: MinimumValidationOutcome,
) -> MinimumValidationOutcome

record_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    reviewer_id: str,
    review_evidence: Mapping[str, object],
) -> ScientificAcceptance

require_scientific_acceptance(
    store: SQLiteScientificValidationStore,
    *,
    minimum_validation_outcome_id: str,
    scientific_acceptance_id: str,
) -> tuple[MinimumValidationOutcome, ScientificAcceptance]
```

The validator accepts no policy argument and is pure except for read-only Core
lookups that close CalculationPlan and Attempt relationships.
`record_minimum_validation` appends the supplied exact outcome and returns the
typed replay. `record_scientific_acceptance` loads the exact persisted outcome,
requires `VALIDATED_MINIMUM`, derives and appends the expanded acceptance, and
returns it. `require_scientific_acceptance` loads both exact IDs, replays all
expanded bindings, and returns the typed pair; absence, mismatch, malformed
content, or ineligibility fails closed. None of these operations chooses a
latest acceptance.

The exact public store signatures are:

```python
SQLiteScientificValidationStore.create_new(
    path: str | Path,
) -> SQLiteScientificValidationStore

SQLiteScientificValidationStore.open_existing(
    path: str | Path,
) -> SQLiteScientificValidationStore

close() -> None
load_minimum_validation(outcome_id: str) -> MinimumValidationOutcome
load_scientific_acceptance(acceptance_id: str) -> ScientificAcceptance
minimum_validations_for_attempt(
    attempt_id: str,
) -> tuple[MinimumValidationOutcome, ...]
acceptances_for_outcome(
    outcome_id: str,
) -> tuple[ScientificAcceptance, ...]
```

The store exposes no raw SQL, connection, cursor, update, delete, migration,
or current/latest pointer. `ScientificValidationError` inherits `ValueError`
and owns semantic, provenance, and eligibility violations;
`ScientificValidationConflictError` and
`ScientificValidationPersistenceIntegrityError` inherit
`ScientificValidationError` and respectively own immutable identity replay
conflicts and database/schema/reopen/path/row integrity failures. There is no
fourth public error class.

Every `MinimumValidationOutcome` closes this one authority chain:

```text
exact CalculationPlan ID and positive revision
-> exact Attempt for that plan
-> exact same-Attempt InputBinding Observation
-> exact same-Attempt COMPLETE OutputEnvelope Observation
-> exact same-envelope ParseOutcome.result_id
-> exact source-controlled validation policy ID/version
-> MinimumValidationOutcome
```

The mandatory outcome semantics are `schema_version`,
`minimum_validation_outcome_id`, policy ID/version, plan ID/revision,
Attempt ID, InputBinding observation ID, envelope observation ID,
`parse_result_id`, exact parser tuple, exact source artifact identity and
selected evidence for a supported attributed tuple (or canonical explicit
absence for a non-parsed/unsupported outcome), accepted optimization and
stationary spans, selected geometry block, selected post-stationary frequency
blocks and values, classification, and exactly one closed primary
`reason_code`. There is no current/latest lookup, cross-capture, cross-envelope,
cross-Result, cross-parser, or cross-Attempt evidence splice.

The exact supported parser tuple is:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.0.0
result_kind    = gaussian-job-facts
```

The envelope must be complete and the ParseOutcome must bind that exact
envelope and same Attempt. Every relied-upon span must bind the exact
`source_artifact` mapping already closed by Result, including envelope ID,
artifact kind and logical name, SHA-256, size, and job-section bounds. The
validator consumes the persisted public records and facts only. It never opens
an artifact, accepts artifact bytes, scans a file, applies a Gaussian regex,
infers context from a substring, reparses output, or reconstructs a missing
fact. `AttemptResultView`, filesystem state, mtime, and a latest parser are not
authority.

Legacy `auto-g16-v3-gaussian-log` / `1.0.0` / `gaussian-log-facts`, any unknown
tuple, and a Result with `ParseStatus.UNSUPPORTED` classify `UNSUPPORTED`.
`PARTIAL` or `UNPARSEABLE`, an incomplete envelope, missing provenance, an
identity conflict, or missing required supported evidence classifies
`INCOMPLETE`. No migration, conversion, merge, backfill, or raw-output fallback
is permitted.

### Deterministic attributed-evidence selection

For a parsed supported tuple, ScientificValidation first requires exactly one
normal terminal fact, no error terminal fact, and `program_status =
normal-termination`. A context-attributed error termination is always
`INCOMPLETE`, never `NOT_MINIMUM` or `VALIDATED_MINIMUM`.

`optimization_completed_evidence` and `stationary_point_evidence` must be
non-empty tuples of equal cardinality. They pair only by the same tuple index.
For every index, the complete optimization span must precede its stationary
span; each pair must precede the next pair. The accepted pair is the final
pair. A missing, unequal, interleaved, or otherwise non-closing pair sequence is
`INCOMPLETE`; no marker boolean repairs it.

The final optimized geometry is the unique rightmost complete
`geometry_blocks` item in source-byte order whose `source_span.end` is less
than or equal to the accepted optimization-completed span's `start`. The block
and every atom are reused exactly as Result persisted them. A tie, overlap, or
absence is `INCOMPLETE`. No orientation preference, nearest-looking geometry,
filename, checkpoint, raw-output scan, coordinate reconstruction, or earlier
fallback participates.

The minimum-validation frequency evidence is the entire ordered suffix of
`frequency_blocks` whose `source_span.start` is greater than or equal to the
accepted stationary span's `end`. Every such block and every value is included
in byte order. A validator may not choose a favorable block or subset. Result's
closed grammar already requires ordered non-overlapping complete blocks,
continuous mode numbering, finite values, and an exact top-level projection;
ScientificValidation neither regroups analyses nor recomputes those rules.
Blocks before the accepted stationary evidence are not Hessian evidence for
this decision. The selected suffix and its spans are bound into the outcome.

These rules use only current `gaussian-job-facts` v1 fields and spans. They do
not add or reinterpret a Result fact. If a conforming implementation cannot
derive exactly these selections from those facts, it must stop rather than
read Gaussian output.

### V3.0 classification policy

Let `N` be the atom count in the selected geometry. V3.0 supports only the
ordinary nonlinear mode-count case and intentionally performs no geometric
linearity calculation. `N < 3` or any atom with atomic number `0` is
`UNSUPPORTED`. Otherwise the supported expected count is exactly `3*N - 6`.

The observed count is the number of values in the selected complete
post-stationary frequency-block suffix:

```text
observed < 3*N - 6  -> INCOMPLETE
observed = 3*N - 6  -> supported for minimum classification
observed > 3*N - 6  -> UNSUPPORTED
```

There is no linear-molecule angle, inertia, collinearity, or tolerance policy
in v3.0. Linear-molecule support may be introduced only by a later additive
policy version.

For otherwise complete supported evidence, every finite frequency `< 0.0` is
imaginary and every frequency `>= 0.0` is non-imaginary. There is no soft-mode,
rounding, low-frequency, or human-override tolerance:

```text
negative count = 0  -> VALIDATED_MINIMUM
negative count >= 1 -> NOT_MINIMUM
```

`-1e-12` is therefore imaginary and `0.0` is not. `NOT_MINIMUM` is used only
for complete supported evidence; it is never an error, incomplete, or
unsupported bucket.

Classification precedence is deterministic. Broken provenance, incomplete
capture, unparseable evidence, error termination, missing accepted marker pair,
missing eligible geometry, or too few selected modes is `INCOMPLETE`.
Structurally present evidence outside v3.0 support, including a legacy or
unsupported parser tuple, dummy center, `N < 3`, or too many modes, is
`UNSUPPORTED`. Only then do negative modes decide `NOT_MINIMUM` versus
`VALIDATED_MINIMUM`.

Each outcome carries exactly one primary reason code. Validation evaluates the
following ordered table top to bottom and stops at the first applicable row;
later conditions are not collected as secondary reasons:

| Order | First applicable condition | Classification | Exact reason code |
| ---: | --- | --- | --- |
| 1 | plan/Attempt/InputBinding/envelope/Result identity or same-source provenance cannot be closed | `INCOMPLETE` | `incomplete-provenance` |
| 2 | envelope is not complete | `INCOMPLETE` | `incomplete-capture` |
| 3 | parser tuple is legacy, unknown, or otherwise unsupported | `UNSUPPORTED` | `unsupported-result-tuple` |
| 4 | supported tuple has `ParseStatus.UNSUPPORTED` | `UNSUPPORTED` | `unsupported-parse-status` |
| 5 | supported tuple is partial, unparseable, or not parsed with closed facts | `INCOMPLETE` | `incomplete-parse` |
| 6 | attributed program status is error termination | `INCOMPLETE` | `incomplete-error-termination` |
| 7 | normal-terminal cardinality/status is missing or contradictory | `INCOMPLETE` | `incomplete-terminal-evidence` |
| 8 | optimization/stationary evidence does not form the required final ordered pair | `INCOMPLETE` | `incomplete-marker-pair` |
| 9 | no unique eligible final geometry exists | `INCOMPLETE` | `incomplete-final-geometry` |
| 10 | selected geometry has `N < 3` | `UNSUPPORTED` | `unsupported-atom-cardinality` |
| 11 | selected geometry contains atomic number `0` | `UNSUPPORTED` | `unsupported-dummy-center` |
| 12 | selected post-stationary mode count is below `3*N - 6` | `INCOMPLETE` | `incomplete-mode-count` |
| 13 | selected post-stationary mode count is above `3*N - 6` | `UNSUPPORTED` | `unsupported-mode-count` |
| 14 | one or more selected frequencies are `< 0.0` | `NOT_MINIMUM` | `negative-frequency` |
| 15 | every prior rule passes | `VALIDATED_MINIMUM` | `validated-minimum` |

The table is the complete reason-code vocabulary for policy v1. Exactly one
row owns every returned outcome; a tuple/set of multiple reasons, warning code,
exception string, presentation message, or caller-selected reason is invalid.
Thus simultaneous missing marker, geometry, and mode evidence is owned only by
`incomplete-marker-pair`, the first applicable row.

### Identity, acceptance, and persistence

`MinimumValidationOutcome` uses a source-controlled namespace and a
schema-versioned, domain-separated UUIDv5 over its complete canonical authority
payload, including expanded selected evidence, classification, and the one
primary reason code. Exact replay
has the same identity and payload. The same identity with different content is
a conflict. A changed Result, plan revision, policy version, selected fact, or
classification produces a new identity. Timestamps, serialization formatting,
temporary paths, and opaque digests never decide authority by themselves.

`ScientificAcceptance` is a separate immutable record containing its schema
version and domain-separated deterministic ID, the exact persisted
`minimum_validation_outcome_id`, expanded outcome identity/policy binding,
reviewer identity, and canonical review evidence. It may be created only for
an exact persisted `VALIDATED_MINIMUM`. No acceptance record exists for
`NOT_MINIMUM`, `INCOMPLETE`, or `UNSUPPORTED`; refusing acceptance creates no
promotion record. Acceptance never mutates Result, Attempt, CalculationPlan,
or the validation outcome and grants no effect authority.

`validate_minimum(core_store, input_binding, envelope, parse_outcome)` is pure
and non-persisting. It validates the exact public Core/Result chain and returns
one deterministic outcome without artifact bytes. `record_minimum_validation`
appends that exact outcome. `record_scientific_acceptance` derives and appends
an acceptance for an exact persisted validated outcome.
`require_scientific_acceptance` replays the exact pair or fails closed; all four
operations have zero Core transition and zero external effect.

`SQLiteScientificValidationStore` owns schema version 1 separately from Core
and Result. Its lifecycle is `create_new(path)`, `open_existing(path)`, and
`close()`. Its minimum reads are `load_minimum_validation(outcome_id)`,
`load_scientific_acceptance(acceptance_id)`,
`minimum_validations_for_attempt(attempt_id)`, and
`acceptances_for_outcome(outcome_id)`, with deterministic insertion order.
Rows are append-only; exact replay is idempotent; conflicting replay fails;
closed typed rows and unexpected schema objects are attested on reopen. There
is no migration, update, delete, current pointer, raw-SQL public surface, Core
table, or Result mutation. Fresh creation is no-overwrite, and reopen rejects
terminal symlink/non-regular/replacement identity drift without resolving away
the caller's terminal path.

### Reuse disposition and non-goals

- **PORT:** public immutable Core/Result records, exact Result identity and
  provenance closure, `GaussianJobParser` tuple dispatch, attributed source
  spans, closed geometry/frequency facts, append-only replay/conflict patterns,
  and local SQLite file-integrity patterns.
- **DROP:** every failed-candidate raw-byte scanner, one-section workaround,
  terminal-orientation parser, whole-log aggregate assumption, duplicated
  Gaussian grammar, favorable-block selection, empirical frequency tolerance,
  legacy minimum/receipt/owner/hash-currentness authority, and any attempt to
  repair or backfill Result evidence.
- **DEFER:** linear-molecule policy, TS/IRC/connectivity, conformer ensembles,
  qRRHO/thermochemistry policy, reaction barriers, excited/open-shell/metal
  policy, Observe, ReviewBundle, generic scientific plugins, and all live work.

This contract defines no implementation, selector ownership, transport,
execution, retry, recovery, submission, Gaussian run, or scientific acceptance
for a real artifact. `UNKNOWN` creates no retry or replacement authority. Any
need for a new Result fact/span, raw-output interpretation, upstream contract
change, or broader scientific policy is an Owner stop.

## V30-REVIEW-MIN-CONTRACT-01 Minimum ReviewBundle Contract

**Contract status: FROZEN CANDIDATE; IMPLEMENTATION NOT AUTHORIZED.** The
future public package is `auto_g16.review`, with focused tests under
`tests/v3/review/`. It owns only a deterministic human-review projection. It
may depend on public Core, Result, and ScientificValidation surfaces; it does
not import Execution merely to repeat snapshot semantics. No upstream package
imports Review. This contract changes no upstream API/schema and grants no
selector, implementation, persistence, acceptance, effect, retry, viewer, or
live authority.

### Exact public boundary

The public inventory is exactly:

```text
ReviewAcceptanceState
ReviewBundle
ReviewBundleError
build_review_bundle
render_review_bundle_json
```

`ReviewAcceptanceState` is exactly a `str, Enum` with
`INELIGIBLE = "ineligible"`,
`ELIGIBLE_UNACCEPTED = "eligible-unaccepted"`, and
`ACCEPTED = "accepted"`. It describes only what the exact supplied records
establish for this projection. It does not select an acceptance or perform an
acceptance operation.

`ReviewBundle` is exactly
`@dataclass(frozen=True, slots=True, kw_only=True, init=False)` with these and
only these public fields:

```python
schema_version: int
review_bundle_id: str  # init=False; deterministic UUIDv5
calculation_plan: Mapping[str, object]
attempt: Mapping[str, object]
input_binding: Mapping[str, object]
execution_snapshot_id: str
output_envelope: Mapping[str, object]
parse_outcome: Mapping[str, object]
selected_final_geometry: Mapping[str, object] | None
selected_frequency_blocks: tuple[Mapping[str, object], ...]
selected_frequencies_cm1: tuple[float, ...]
minimum_validation_outcome: Mapping[str, object]
minimum_validation_classification: MinimumValidationClassification
primary_reason_code: str
scientific_acceptance_state: ReviewAcceptanceState
scientific_acceptances: tuple[Mapping[str, object], ...]
```

Every mapping is a deeply immutable canonical semantic copy of the named
public record. `calculation_plan` has exactly `calculation_plan_id`, `task_id`,
`revision`, and complete `intent`; `attempt` has exactly `attempt_id`,
`task_id`, and `ordinal`. MinimumValidationOutcome and ScientificAcceptance
mappings preserve every public field of their exact typed source records,
using enum values and the complete expanded mappings already frozen by their
owner.

The InputBinding projection has exactly these 11 keys and no others:

```text
schema_version
observation_id
attempt_id
calculation_plan_id
calculation_plan_revision
prepared_input_binding_id
execution_snapshot_id
input_format
logical_name
sha256
size_bytes
```

`observation_id` is obtained from and must equal the exact validated typed
`InputBinding.observation_id`; the builder accepts no independent replacement
ID. Every other value comes from that same typed InputBinding.

The OutputEnvelope projection has exactly these 12 keys and no others:

```text
schema_version
observation_id
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

`observation_id` is obtained from and must equal the exact validated typed
`OutputEnvelope.observation_id`; the builder accepts no independent replacement
ID. `capture_status` and `capture_completeness` are their exact public enum
values. `artifacts` preserves the normalized typed-record order, and every
artifact mapping has exactly `artifact_kind`, `logical_name`, `sha256`, and
`size_bytes`. Artifact paths, mtimes, local source paths, and an added
capture/currentness field are forbidden. The exact persisted `captured_at_utc`
remains part of the upstream record and is neither replaced nor interpreted as
currentness.

The ParseOutcome projection has exactly these 10 keys and no others:

```text
schema_version
result_id
attempt_id
envelope_observation_id
parser_name
parser_version
result_kind
parse_status
facts
diagnostics
```

`result_id` is obtained from and must equal the exact validated typed
`ParseOutcome.result_id`; the builder accepts no independent replacement ID.
`parse_status` is its exact public enum value, `facts` is the already-frozen
public semantic mapping from that typed ParseOutcome, and `diagnostics`
preserves exact tuple order. Raw output, artifact bytes, parser-local prose,
and latest/current markers are forbidden.

These three mappings do not use `payload()` verbatim because those public
payload helpers intentionally omit the corresponding derived authority ID.
The builder starts with the complete typed public semantic fields, adds the
typed record's derived public ID, and fails closed if reconstruction/replay
does not reproduce that ID. No additional record-kind discriminator is added;
the enclosing ReviewBundle field determines the record type. No path, raw
output, artifact bytes, mtime, newly generated display timestamp, viewer state,
or private object is a bundle field.

The selected geometry and frequencies are byte-semantic copies of the exact
`selected_geometry_block`, `selected_frequency_blocks`, and
`selected_frequencies_cm1` already stored in the supplied
MinimumValidationOutcome. Review never calls a parser, reads a span from disk,
selects another geometry, shortens the complete frequency suffix, applies a
tolerance, or derives a new scientific fact. `primary_reason_code` is the exact
outcome `reason_code`, and `minimum_validation_classification` is its exact
classification.

The one builder signature is:

```python
build_review_bundle(
    core_store: SQLiteRuntimeStore,
    validation_store: SQLiteScientificValidationStore,
    *,
    input_binding: InputBinding,
    output_envelope: OutputEnvelope,
    parse_outcome: ParseOutcome,
    minimum_validation_outcome_id: str,
    scientific_acceptance_ids: tuple[str, ...] = (),
) -> ReviewBundle
```

The builder loads the exact persisted MinimumValidationOutcome and every
explicitly named ScientificAcceptance. It also loads the exact CalculationPlan
and Attempt and replays the persisted same-Attempt InputBinding, OutputEnvelope,
and ParseOutcome through public Core records. It requires the complete plan,
task, Attempt, InputBinding observation, envelope observation, Result ID,
parser tuple, and ScientificValidation policy bindings to agree. It requires
the one `execution_snapshot_id` in InputBinding and OutputEnvelope to agree and
projects that identity without reconstructing or authenticating an
ExecutionSnapshot. Missing, malformed, duplicate acceptance IDs, or any
cross-plan, cross-Task, cross-Attempt, cross-input, cross-envelope,
cross-Result, cross-policy, or cross-outcome splice raises
`ReviewBundleError` before a bundle is returned.

`ReviewBundleError` inherits `ValueError` and owns every invalid public input,
relationship/provenance mismatch, unsupported canonical value, forged bundle
identity, and rendering failure in this slice. There is no second public error
class and Review never translates an upstream record into a different upstream
error or status.

The explicit acceptance-ID tuple is a closed caller-supplied review set, not a
query or latest/current selector. The builder sorts its distinct loaded
ScientificAcceptance records lexically by `scientific_acceptance_id`. A
non-`VALIDATED_MINIMUM` outcome requires an empty set and projects
`INELIGIBLE`. A `VALIDATED_MINIMUM` with no explicit acceptance projects
`ELIGIBLE_UNACCEPTED`; one or more exact acceptances for that outcome project
`ACCEPTED`. Multiple acceptances remain separate complete mappings and no
winner, newest, preferred reviewer, or implicit revocation is inferred.

### Deterministic identity and rendering

Schema version is exactly `1`. The source-controlled Review namespace root is
`061dffea-e54e-580e-9928-e284abc0997f`. The only identity domain is
`review-bundle`, whose namespace is
`62e6a827-7dbf-5efe-8625-729e43bc9d46`, derived exactly as:

```python
uuid5(REVIEW_NAMESPACE, "auto_g16.review/v1/review-bundle")
```

`review_bundle_id` is UUIDv5 in that domain over every field above except
itself, with enum values substituted for enum objects. It uses the same frozen
tagged canonical-value grammar as the ScientificValidation public-shape
contract: distinct null/Boolean/integer/finite-float/string/mapping/sequence
tags, lexical mapping-key order, sequence-order preservation, and compact
UTF-8 canonical JSON. Review extracts that reviewed algorithm into one private
helper and imports no private Core, Result, ScientificValidation, Workflow, or
Execution helper. Exact replay gives the same ID; any projected source,
selected evidence, reason, classification, acceptance set, or acceptance-state
change gives a new ID. Unsupported values, non-finite numbers, cycles, or a
forged/stale identity fail closed.

The exact InputBinding, OutputEnvelope, and ParseOutcome mappings specified
above are the same semantic values used by both ReviewBundle UUIDv5 identity
and deterministic JSON rendering; Review maintains no separate identity-only
or render-only projection. Consequently, adding, removing, or changing one of
their derived authority IDs changes ReviewBundle identity. Caller mapping
insertion order does not change identity because canonical mapping keys are
ordered lexically.

The only public renderer is:

```python
render_review_bundle_json(bundle: ReviewBundle) -> str
```

It first recomputes the complete bundle identity and rejects drift. It renders
the exact complete public payload including `review_bundle_id` using
`json.dumps(..., ensure_ascii=False, allow_nan=False, indent=2,
sort_keys=True, separators=(",", ": "))` followed by exactly one LF. Output is
deterministic JSON text; when encoded as bytes its required encoding is UTF-8,
with no filesystem access, hidden field, prose inference, current-time value,
scientific recommendation, or authority flag. A renderer does not persist the
bundle, write a geometry file, open a viewer, or grant ScientificAcceptance.

The bundle itself is sufficient for v3.0 human review: the selected geometry
mapping contains exact ordered atomic numbers and Cartesian coordinates, and
the selected frequency evidence contains exact Result source bindings and
values. A later external-viewer adapter may transform this explicit geometry
projection under a separate gate. Viewer file generation, inferred bonds,
GaussView opening, SSH transfer, and load probing are not Review public APIs.

### Narrow reuse and ownership preparation

The reuse audit is limited to the public Core/Execution/Result and frozen
ScientificValidation shapes, the existing reaction-workflow review/projection
helpers adjacent to `calculation_artifacts.py`, and the
`auto-g16-view-rt-win` preview/GaussView handoff with its adjacent tests.

- **PORT:** public `CalculationPlan` and `Attempt` records, Result
  InputBinding/OutputEnvelope/ParseOutcome payloads, the frozen
  MinimumValidationOutcome and ScientificAcceptance records, and their exact
  append-only identities and source bindings. Only the ExecutionSnapshot ID
  already present in Result provenance is ported; no Execution internals are.
- **EXTRACT:** deeply immutable semantic projection, exact relationship replay,
  deterministic tagged canonical identity, stable JSON rendering, and the
  adjacent no-overwrite/non-authorizing review tests. Each extracted behavior
  receives Review-owned cross-splice and determinism tests.
- **WRAP:** a future explicitly authorized viewer adapter may consume the exact
  selected geometry projection and wrap the existing GaussView handoff. The
  wrapper remains outside Review authority and may not reinterpret geometry or
  make a calculation-ready artifact.
- **REWRITE:** the bundle builder and renderer are clean typed projections
  because legacy review/report helpers mix chemistry-specific policy, paths,
  hashes, mutable files, reviewer decisions, and `calculation_ready`/
  submission flags. Porting them would create a second authority and the wrong
  dependency direction.
- **DROP:** hash-currentness, file-path identity, implicit latest/current
  selection, favorable evidence selection, raw-log parsing, embedded approval
  or readiness decisions, effect flags, and any receipt/owner/capability
  governance as Review authority.
- **DEFER:** GUI, HTML/rich report, ReviewBundle persistence, geometry-file
  export, bond inference, normal-mode animation, external-viewer invocation,
  SSH/RTwin transfer, viewer load probing, TS/IRC/connectivity review, and all
  live work.

After this contract is integrated, `V30-VAL-REVIEW-01` may separately propose
one `affected / fail_closed=false` selector route for `auto_g16/review/` and
`tests/v3/review/`. The smallest expected evidence is `tests.v3.review`,
`tests.v3.scientific_validation`, `tests.v3.result`, and
`tests.v3.core.test_store`, retaining `no-overwrite` and
`unknown-no-automatic-retry`. Selector, test package, and product bytes are not
created by this contract candidate. Review implementation remains `WAIT` until
ScientificValidation implementation is integrated and a separate Owner Gate
opens.

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

## V30-OBS-MIN-CONTRACT-01 Frozen Minimal Observe Contract

**Status: CONTRACT FREEZE CANDIDATE; IMPLEMENTATION NOT AUTHORIZED.** This is a
read-only evidence boundary. It introduces no Core, Execution, Result,
ScientificValidation, Approval, or Workflow API/schema change and authorizes no
transport or live observation.

### Package and exact public inventory

The only public package is `auto_g16.observe`; its focused test package is
`tests/v3/observe/`. The public inventory is exactly:

```text
OBSERVATION_TYPE
AttemptObservation
AttemptObservationProjection
ObserveBoundaryError
record_attempt_observation
project_attempt_observations
```

`OBSERVATION_TYPE` is the source-controlled string
`auto-g16-v3-attempt-observation`. `ObserveBoundaryError` is a `ValueError`.
No public transport, callback, parser, retry, diagnosis, policy, mutable view,
or effect interface is part of this contract.

`AttemptObservation` is frozen, slotted, keyword-only, and immutable. Its exact
fields are:

```text
observation_id: str                         # init=False
attempt_id: str
source_kind: str
source_identity: str
observed_at_utc: str
freshness: str
state: str
progress_position: int | None
```

`attempt_id`, `source_identity`, and `observed_at_utc` are nonempty. The time
uses exact `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC syntax, must denote a real UTC
instant, and is evidence only; it is not used to reorder persisted history.
`freshness` is exactly `fresh`, `stale`, or `unknown` and remains the source
acquisition owner's classification. Observe does not recompute it from ambient
time. Freshness is independent of `state`: a closed known state does not become
`unknown` merely because its evidence is stale, and explicit state `unknown`
may itself carry `fresh`, `stale`, or `unknown` freshness.

The closed state matrix is:

```text
scheduler -> queued | running | held | exiting | terminal | absent | unknown
process   -> active | absent | unknown
gaussian  -> not-started | startup | scf | optimization | frequency |
             termination | unknown
```

`progress_position` is `None` for scheduler and process samples. For a Gaussian
sample it is `None` or a nonnegative integer denoting an exact coarse source
position supplied by the read-only acquisition owner. It is not a percentage,
convergence claim, liveness proof, completion claim, or scientific fact.

`AttemptObservationProjection` is a frozen, slotted, keyword-only derived view
with exact fields:

```text
attempt_id: str
scheduler: AttemptObservation | None
process: AttemptObservation | None
gaussian: AttemptObservation | None
observation_count: int
```

It has no separately persisted identity and cannot be caller-constructed as
authority.

### Deterministic identity and Core persistence

Observe schema version is `1`. Its source-controlled UUIDv5 namespace root is
`653e9a6f-0d59-503c-ab13-ddd6e5055fe4`; the
`attempt-observation` domain namespace is
`7c81caec-1f1d-5114-81a6-b72a537c4f4e`. The domain namespace is UUIDv5 of the
root and literal `attempt-observation`.

The UUIDv5 name is compact UTF-8 JSON over this exact ordered array:

```text
[
  1,
  attempt_id,
  source_kind,
  source_identity,
  observed_at_utc,
  freshness,
  state,
  progress_position
]
```

JSON uses `ensure_ascii=false`, separators `,` and `:`, and `allow_nan=false`.
Every element is already closed to string, integer, or null; Boolean is not an
integer. Formatting, local path, insertion order, ambient time, and temporary
location never affect identity.

The normative replay vector is:

```text
payload = [1,"attempt-1","scheduler","source-qstat-1",
           "2026-08-22T00:00:00.000000Z","fresh","running",null]
observation_id = cdce89f6-8d2e-51b1-b5b0-7f6c48358e95
```

```text
record_attempt_observation(
    store: SQLiteRuntimeStore,
    observation: AttemptObservation,
) -> None
```

This function verifies the record and appends one public Core `Observation` whose
`observation_id` and `attempt_id` match the Observe record, whose
`observation_type` is exactly `OBSERVATION_TYPE`, and whose canonical `data`
contains exactly `source_kind`, `source_identity`, `observed_at_utc`,
`freshness`, `state`, and `progress_position`. The existing Core store proves
that the Attempt exists, preserves append order and reopen durability, makes
exact same-ID/same-payload replay idempotent, and rejects
same-ID/different-payload conflicts. Observe creates no separate database and
no Core migration.

```text
project_attempt_observations(
    store: SQLiteRuntimeStore,
    *,
    attempt_id: str,
) -> AttemptObservationProjection
```

This function loads the existing Attempt through the public Core store and
scans the complete append-ordered Observation history.
Non-Observe observation types are ignored. Every matching Observe record is
decoded with exact fields and its identity is recomputed before projection;
one malformed, cross-Attempt, or identity-inconsistent matching record fails
the whole projection closed. For each `source_kind`, the last appended valid
record wins. Its `state` and `freshness` are projected independently: a newer
stale `running` or `queued` record remains respectively `running` or `queued`,
while a newer explicit state `unknown` remains unknown whether fresh or stale.
When an axis has no usable persisted Observe record, its projection slot is
`None`, which is the projection's no-evidence UNKNOWN case; it must not be
confused with the known source state `absent`. Malformed matching evidence
still fails the whole projection closed rather than being silently converted to
unknown. `observation_count` counts all validated matching Observe records. The
same persisted history always yields the same projection.

### Authority, replay, and failure boundaries

An Observe record preserves a supplied source evidence identity but does not
self-authenticate the acquisition, transport, file, process, qstat executable,
or Gaussian source. A later acquisition owner must separately validate those
bytes and source semantics before recording a sample. Observe never follows a
path, reads a Gaussian log, invokes qstat/ps, opens SSH, or calls a program.

`scheduler=terminal` or `scheduler=absent` does not imply Gaussian completion;
`process=absent` does not imply failure; `gaussian=termination` does not encode
normal versus error termination and does not create a Result. A repeated or
unchanged `progress_position`, stale sample, slow job, or nonterminal state is
not failure. Stale known evidence preserves its latest durable known state and
marks freshness separately; it is neither `unknown` nor `failed`. Explicit
state `unknown` replaces an older optimistic state for its axis, while absence
of any usable axis evidence remains `None`/UNKNOWN. None of these states or
freshness values changes Core Attempt state or authorizes retry, replacement,
child creation, submission, cancellation, cleanup, execution, parsing,
validation, or acceptance.

### Narrow reuse adjudication and non-goals

**PORT:** the public Core `Observation`, `SQLiteRuntimeStore`, Attempt existence
check, append-order query, idempotent exact replay, conflict rejection, and
durable reopen behavior.

**EXTRACT:** only the neutral scheduler lifecycle vocabulary and strict
present/absent/unknown and process present/absent/unknown distinctions evidenced
by the legacy direct qstat/read-only tests. The legacy stale-to-unknown coupling
is not ported; v3 preserves typed state and freshness as independent evidence
axes.

**WRAP:** exact Core Attempt binding and Core Observation persistence behind
the two small public Observe service functions.

**REWRITE:** the compact typed Observe record and deterministic per-axis
projection. The legacy monitor cannot reasonably be ported because it couples
freshness and acquisition outcomes to remote acquisition, v2
owner/receipt/capability/profile/hash-lineage governance, projection, and live
operational policy instead of preserving independent typed evidence axes.

**DROP:** legacy owner chains, receipts, capabilities, profile/hash-lineage
authority, caller path fallbacks, qsub/qdel/cancellation/retry behavior,
scientific acceptance, and any inference that scheduler terminal means
Gaussian completion.

**DEFER:** live qstat/ps/log acquisition, transport, OpenSSH/RTwin/PBS wiring,
the exact incremental Gaussian phase recognizer/source grammar, full stall or
failure diagnosis, resource telemetry/planning, automatic repair/retry,
ReviewBundle, and every live operation. Existing `GaussianLogParser` and
`GaussianJobParser` remain Result parsers and are not ported into Observe.

Core owns Attempt state/history; Execution owns effects; Observe owns only its
Observation payload and derived projection; Workflow owns orchestration;
Result owns parsed facts; ScientificValidation owns scientific classification.
The dependency direction is `Observe -> Core`; upstream layers never import
Observe. Contract integration alone authorizes neither selector ownership nor
implementation.

## V30-EXEC-02-COMPOSITION-CONTRACT-01 RTwin-First Composition Contract

**Contract status: FROZEN; IMPLEMENTATION NOT AUTHORIZED.** This exact
authority content is eligible for integration only after its successor
independent review is `PASS`; once present on authoritative main it is active
without another wording change. This additive contract opens only the offline
V30-EXEC-02 composition boundary. It does not alter any public Core, Approval, Workflow,
Execution, Observe, Result, ScientificValidation, or Review API/schema. The new
public package is `auto_g16.transport`, with future focused tests under
`tests/v3/transport/`. Transport may depend on public Execution only. The
Controller is a composition role and receives no new public package in this
slice.

### Single effect owner and RTwin-first boundary

The Controller must finish pure `validate_effect_authority(...)` replay and all
other non-effect validation, then call the existing public `execute_once(...)`
without first claiming Core submission intent. `execute_once(...)` remains the
single effect entrypoint, owns `record_submission_intent(...)`, and calls an
RTwin adapter only after `WINNER`. `REPLAY` makes zero local-workspace,
transport, scheduler, or Gaussian calls. The RTwin implementation conforms to
the unchanged public `ExecutionPort`; it does not add another submit method or
bypass the existing receipt journal.

Official composition requires Approval replay while the Attempt is still
`PLANNED`. The concurrency proof has two Controllers complete that pure replay
before one barrier, then call `execute_once(...)` concurrently: exactly one
returns `WINNER` and reaches its port, while the other returns `REPLAY` and its
port receives zero calls. Sequential replay is not an official composition
path. A later Controller observes the non-`PLANNED` Attempt during
`validate_effect_authority(...)`, fails before `execute_once(...)`, and makes
zero Execution/adapter calls. Directly calling Execution after skipping that
pure replay is invalid Controller behavior even if Core would return `REPLAY`.

This sequencing is at-most-once, not distributed atomicity. A crash,
disconnect, timeout, or malformed reply after `WINNER` cannot undo the claim.
Any outcome that may have crossed a remote seam records
`possibly_effectful`, leaves the Attempt `UNKNOWN`, and permits only the
existing same-Attempt read-only reconciliation. It never invokes `qsub` again,
creates a child, changes a workspace/profile, or grants retry authority.

V30-A selects `Mac -> RTwin -> PBS server` as its first real adapter path. The
existing `legacy_rtwin_pbs` running path is wrapped behind the v3 port and is
never allowed to own Core state, Approval, receipt lineage, or a v3 capability.
Direct `OpenSSHTransport` remains deferred. This contract and its later
implementation are offline-only; live RTwin, PBS, Gaussian, `qsub`, `qdel`,
deployment, cancellation, cleanup, and remote mutation require later explicit
Owner authorization.

### Exact minimum Transport public inventory

The future `auto_g16.transport` export set is exactly:

```text
TransportBoundaryError
ExactRemoteJobBinding
SchedulerReadEvidence
ExactArtifactRequest
FetchedArtifact
FetchedOutputCapture
RTWinExecutionAdapter
RTWinReadAdapter
```

`TransportBoundaryError` inherits `ValueError` and owns malformed, stale,
cross-Attempt, cross-snapshot, cross-receipt, unstable-read, and unsafe-path
failures at this boundary. Public records are frozen, slotted, keyword-only,
and deeply immutable. Public functions/classes accept no arbitrary command,
shell fragment, callback, remote root, or caller-selected executable.

`ExactRemoteJobBinding` has exactly these six fields:

```text
attempt_id: str
execution_snapshot_id: str
submission_intent_id: str
remote_effect_receipt_id: str
remote_workspace: str
job_id: str
```

The only public constructor is exactly:

```text
ExactRemoteJobBinding.from_persisted_receipt(
    snapshot: ExecutionSnapshot,
    journal: ReceiptJournal,
    *,
    remote_effect_receipt_id: str,
    current_profile: ServerProfile,
) -> ExactRemoteJobBinding
```

It calls public `assert_execution_snapshot_identity(snapshot)`, then public
`resolve_server_profile(current_profile)` and requires complete semantic
equality, `resolved_server_profile_id`, and `effective_config_sha256` equality
with `snapshot.resolved_server_profile`. It calls public
`journal.receipts_for_attempt(snapshot.attempt_id)` and selects by the exact
non-empty receipt ID. Exactly one durable receipt must have that ID. Absence,
duplicate IDs, malformed stored evidence, or the same record ID with different
durable semantic payload fails closed. The selected receipt must be
`confirmed_effect` submission or submission-reconciliation evidence and must
exactly match the snapshot's Attempt, snapshot ID, submission intent, remote
Attempt workspace, and non-empty job ID. A transient or caller-created
`RemoteEffectReceipt` is never an input and grants no read authority. The
record has `init=False`; callers cannot construct it from strings alone.

`ServerProfile` is existing public non-secret mutable configuration. Its
public resolver already closes ordered config bytes, strict host-key policy,
target/jump topology, platform paths, and runtime contents. Secrets and
credential handles remain out-of-band driver mechanics and are never snapshot,
binding, receipt, or evidence authority. No private Execution identity/config
helper or unspecified process-global configuration is used.

`SchedulerReadEvidence` has exactly these ten fields:

```text
binding: ExactRemoteJobBinding
source_identity: str
observed_at_utc: str
freshness: str
state: str
evidence_sha256: str
evidence_size_bytes: int
schema_version: int = 1
source_kind: str = "scheduler"
progress_position: None = None
```

The record has `init=False` and only the package-private qstat classifier may
construct it. Public callers supply neither `state`, `freshness`, timestamp,
digest, size, nor source identity. `RTWinReadAdapter.read_scheduler(...)`
captures bounded raw stdout/stderr plus completion metadata, derives every
field through the fixed classifier below, and returns the closed record.

Its closed state vocabulary equals Observe scheduler state exactly:
`queued`, `running`, `held`, `exiting`, `terminal`, `absent`, or `unknown`.
Freshness is `fresh`, `stale`, or `unknown`, but a new live acquisition derives
only `fresh` for an exact completed response or `unknown` for an uncertain
response; it never accepts caller-selected `stale`. The exact inner operation
is executable token `qstat`, argv `("-f", binding.job_id)`, cwd equal
to `binding.remote_workspace`, environment exactly
`{"LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1",
"PYTHONUTF8": "1"}`, `shell=False`, timeout 30 seconds, stdout cap 262144
bytes, and stderr cap 65536 bytes. The adapter must receive process completion
and EOF on both streams within those caps. Overflow, timeout, missing EOF,
decode failure, or transport failure is `unknown/unknown`; no truncation is
classified as evidence.

Raw streams are strict UTF-8 with no NUL or CR. A present response requires
return code 0, empty stderr, and exactly one stdout record. Its first line is
exactly `Job Id: <binding.job_id>`; stdout ends in exactly one LF and has no
blank line. Every remaining line is exactly four spaces, one ASCII field name
matching `[A-Za-z_][A-Za-z0-9_.-]*`, ` = `, and one nonempty value. Duplicate
field names, extra preamble/trailer, or any line outside that grammar is
malformed. Exactly one `job_state` value is
required and mapped by this closed table: `Q/W -> queued`, `R/B -> running`,
`H/S -> held`, `E/T -> exiting`, and `C/F/X -> terminal`; any other one-byte
uppercase state maps to `unknown` with `fresh` evidence. An absent response is
only return code 153, empty stdout, and stderr exactly
`qstat: Unknown Job Id <binding.job_id>\n`; it maps to `absent/fresh`. Every
other return-code/stream/grammar combination maps to `unknown/unknown`.

The evidence digest/size cover one fixed acquisition byte array:
`[stdout_bytes, stderr_bytes, returncode_or_null, eof_stdout, eof_stderr,
completion_status]` encoded by the canonical grammar below. Completion status
is exactly `completed`, `timeout`, or `transport-error`; present/absent require
`completed`, while either other value is `unknown/unknown` regardless of
partial streams. A scheduler read is not
reconciliation, Gaussian completion, scientific success, or retry authority.
The Controller creates an existing public `AttemptObservation` by copying the
exact attempt, source identity, timestamp, freshness, state, and `None`
progress, then calls `record_attempt_observation(...)`. Transport does not
write Core or Observe records. Process acquisition remains deferred.

`ExactArtifactRequest` has exactly these four fields:

```text
artifact_kind: str
logical_name: str
remote_relative_name: str
required: bool
```

The tuple supplied to one fetch is finite, non-empty, contains at most
`MAX_ARTIFACT_REQUESTS = 4` entries, preserves the caller-supplied order as
authority, and is duplicate-free by both `(artifact_kind, logical_name)` and
`remote_relative_name`. Transport never sorts or discovers requests. Names
are portable single components: no absolute path, separator, dot component,
parent traversal, shell syntax, glob, or symlink is accepted. The v1 required
artifact is one Gaussian log derived from the exact prepared-input basename;
optional stdout/stderr may be named explicitly. Artifact kind is exactly
`gaussian-log`, `stdout`, or `stderr` in v1. Checkpoint bytes, recursive
directories, arbitrary caller paths, and implicit "all files" discovery are
outside this contract.

`FetchedArtifact` has exactly these four fields:

```text
request: ExactArtifactRequest
content: bytes
sha256: str
size_bytes: int
```

Its public constructor is exactly
`FetchedArtifact(*, request: ExactArtifactRequest, content: bytes)`; `sha256`
and `size_bytes` are `init=False` derived fields.

The adapter accepts an artifact only when the exact remote Attempt workspace
and regular source file are stable across bounded before/read/after identity,
size, and SHA-256 checks. V1 is byte-return-only: it performs no local output
materialization, accepts no local target path, and writes no fetched file.
Source stability is adapter validation, not a caller-supplied boolean. Digest
and size are recomputed from exact immutable bytes. Replacement,
symlink/reparse, escape, short read, or digest drift fails closed with zero
overwrite or cleanup. `MAX_FETCH_ARTIFACT_BYTES = 134217728` and
`MAX_FETCH_CAPTURE_BYTES = 268435456`; the adapter rejects an impossible
request before reading where size metadata is available and aborts while
reading before either cap can be exceeded. It never returns truncated bytes.

`FetchedOutputCapture` has exactly these twelve fields:

```text
binding: ExactRemoteJobBinding
input_binding_observation_id: str
capture_source_id: str
capture_sequence: int
capture_status: str
capture_completeness: str
requests: tuple[ExactArtifactRequest, ...]
artifacts: tuple[FetchedArtifact, ...]
missing_requests: tuple[ExactArtifactRequest, ...]
capture_manifest_sha256: str
captured_at_utc: str
schema_version: int = 1
```

Its public constructor accepts only `binding`,
`input_binding_observation_id`, `capture_sequence`, `capture_status`,
`capture_completeness`, `requests`, `artifacts`, `missing_requests`, and
`captured_at_utc` as keyword arguments. `capture_source_id`,
`capture_manifest_sha256`, and `schema_version` are derived/constant
`init=False` fields.

Capture status is exactly `captured`, `capture-in-progress`,
`capture-interrupted`, or `capture-error`; completeness is exactly `partial`
or `complete`. `requests` is the complete exact ordered request tuple.
`artifacts` must correspond one-for-one, in the same order, to a prefix of
`requests`; `missing_requests` must be the exact remaining suffix. `complete`
is legal only for `captured`, an empty missing tuple, and an artifact for every
request in exact order. `partial` is legal only when `artifacts` is a non-empty
exact prefix and `missing_requests` is the non-empty exact suffix;
`capture-in-progress`, `capture-interrupted`, and `capture-error` require
`partial`. Reordering, an interior hole, duplicate, extra artifact, or a
request absent from the partition fails closed. Zero stable artifacts returns
a transport failure and creates no Result envelope. The manifest digest covers
the complete ordered request tuple, ordered Result-compatible successful
artifact metadata, and exact missing suffix; it does not cover paths outside
the requests or mutable timestamps.

Transport never allocates or infers capture history. Before fetch, the
Controller reads the Result-owned append-only envelope history for the exact
Attempt: sequence is `1` when no envelope exists and otherwise
`max(capture_sequence) + 1`. It supplies that exact positive integer to
Transport and subsequently appends the mapped envelope through Result. Result
remains the sequence/conflict authority; a concurrent duplicate or conflicting
sequence fails closed. Transport never chooses a latest/current capture and
cannot replace history.

### Canonical transport evidence identity

The transport UUID namespace root is
`6e54140f-f4e7-5482-a6c1-8f5729e3c112`. Per-domain namespaces are
`uuid5(root, "scheduler-read") =
b863c565-aa1b-5ea9-8c9e-170dc7af33c6` and
`uuid5(root, "output-capture") =
8ea6ba6d-0365-5493-9bda-87f4be9f23a8`. Evidence IDs are
`uuid5(domain_namespace, canonical_bytes.decode("ascii"))`.

Canonical encoding accepts only null, boolean, integer, string, raw bytes,
array/tuple, and object. Float is forbidden. Tags are exact: null `n;`; false
`b0;`; true `b1;`; integer `i<base10>;`; string
`s<UTF-8-byte-count>:<UTF-8-bytes>`; raw bytes
`y<raw-byte-count>:<lowercase-hex>`; array `a<count>:` followed by member
encodings; object `o<count>:` followed by key/value encodings with string keys
sorted by their UTF-8 bytes. Integers have no plus sign or leading zero except
`0`. Strings reject NUL, CR, and LF and use shortest-form UTF-8. The complete
canonical document is ASCII/UTF-8 with no BOM, whitespace, or trailing newline.

The exact schema-v1 scheduler identity name array is:

```text
["auto-g16-transport/scheduler-read", 1, binding_payload,
 observed_at_utc, freshness, state, evidence_sha256, evidence_size_bytes]
```

`binding_payload` is the exact six-key object named by the six
`ExactRemoteJobBinding` fields above. A request payload is the exact four-key
object named by `ExactArtifactRequest`. Successful artifact metadata is the
exact four-key object `{artifact_kind, logical_name, sha256, size_bytes}`
derived from its request and fetched bytes; mutable paths/content/timestamps
are excluded because the complete request tuple and byte digest/size are bound
separately.

The acquisition digest input is exactly
`[stdout_bytes, stderr_bytes, returncode_or_null, eof_stdout, eof_stderr,
completion_status]` under the
same grammar. `evidence_size_bytes` is the sum of original stdout and stderr
byte counts. The exact schema-v1 capture manifest array is:

```text
["auto-g16-transport/capture-manifest", 1,
 ordered_request_payloads, ordered_successful_artifact_metadata,
 ordered_missing_request_payloads]
```

`capture_manifest_sha256` is lowercase SHA-256 of those canonical manifest
bytes. The exact schema-v1 capture identity name array is:

```text
["auto-g16-transport/output-capture", 1, binding_payload,
 input_binding_observation_id, capture_sequence, capture_status,
 capture_completeness, ordered_request_payloads,
 ordered_successful_artifact_metadata, ordered_missing_request_payloads,
 capture_manifest_sha256, captured_at_utc]
```

The normative fixture uses binding `{attempt_id: "attempt-1",
execution_snapshot_id: "snapshot-1", submission_intent_id: "intent-1",
remote_effect_receipt_id: "receipt-1", remote_workspace:
"/srv/p/attempt-1", job_id: "123.server"}`. For qstat stdout
`Job Id: 123.server\n    job_state = R\n`, empty stderr, return code 0, and
both EOF flags true, and completion status `completed`, the exact acquisition
bytes are:

```text
a6:y37:4a6f622049643a203132332e7365727665720a202020206a6f625f7374617465203d20520ay0:i0;b1;b1;s9:completed
```

Their SHA-256 is
`664e69c9fa7687ddb0b54d38d11eafeff8a4b93d07fb7a97a51263ddf45191b5`,
their stream-size field is `37`, and the scheduler name bytes are:

```text
a8:s33:auto-g16-transport/scheduler-readi1;o6:s10:attempt_ids9:attempt-1s21:execution_snapshot_ids10:snapshot-1s6:job_ids10:123.servers24:remote_effect_receipt_ids9:receipt-1s16:remote_workspaces16:/srv/p/attempt-1s20:submission_intent_ids8:intent-1s27:2026-08-23T00:00:00.000000Zs5:freshs7:runnings64:664e69c9fa7687ddb0b54d38d11eafeff8a4b93d07fb7a97a51263ddf45191b5i37;
```

The scheduler source ID is
`1a30e48e-fa53-5eb8-b186-cc7b4ea5f996`.

For one required `gaussian-log` request with logical/remote name `job.log`
and immutable content `Normal termination\n` (SHA-256
`d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618`,
19 bytes), the complete manifest bytes are:

```text
a5:s35:auto-g16-transport/capture-manifesti1;a1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs20:remote_relative_names7:job.logs8:requiredb1;a1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs6:sha256s64:d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618s10:size_bytesi19;a0:
```

The manifest SHA-256 is
`1636f90c920537ebc491e0c7a173377a66db2cef4c28d488d435dd537e43a25f`.
At timestamp `2026-08-23T00:01:00.000000Z`, InputBinding observation
`input-observation-1`, sequence 1, `captured/complete`, the capture name bytes
are:

```text
a12:s33:auto-g16-transport/output-capturei1;o6:s10:attempt_ids9:attempt-1s21:execution_snapshot_ids10:snapshot-1s6:job_ids10:123.servers24:remote_effect_receipt_ids9:receipt-1s16:remote_workspaces16:/srv/p/attempt-1s20:submission_intent_ids8:intent-1s19:input-observation-1i1;s8:captureds8:completea1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs20:remote_relative_names7:job.logs8:requiredb1;a1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs6:sha256s64:d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618s10:size_bytesi19;a0:s64:1636f90c920537ebc491e0c7a173377a66db2cef4c28d488d435dd537e43a25fs27:2026-08-23T00:01:00.000000Z
```

The capture source ID is
`337f05ea-7f62-581b-b1bf-46af0914bd6c`. Exact replay keeps identity;
any authority-semantic change changes identity; same ID with different payload
fails closed. These evidence identities are audit/source bindings, never
approval or effect authority.

`RTWinExecutionAdapter()` and `RTWinReadAdapter()` have no public constructor
arguments; creation is non-effectful, and package-private driver/clock seams
may be replaced only by tests without entering the public API.
`RTWinExecutionAdapter` implements the unchanged public `ExecutionPort` and
advertises adapter contract version `rtwin-pbs-v1`. It wraps only exact
Attempt-specific allocate, exact-byte transfer, single qsub, and read-only
submission-reconciliation operations. `RTWinReadAdapter` exposes exactly:

```text
read_scheduler(
    snapshot: ExecutionSnapshot,
    binding: ExactRemoteJobBinding,
    current_profile: ServerProfile,
) -> SchedulerReadEvidence

fetch_exact_output(
    snapshot: ExecutionSnapshot,
    binding: ExactRemoteJobBinding,
    current_profile: ServerProfile,
    *,
    input_binding_observation_id: str,
    requests: tuple[ExactArtifactRequest, ...],
    capture_sequence: int,
) -> FetchedOutputCapture
```

Both read methods call public `assert_execution_snapshot_identity(snapshot)`,
require every binding field to equal that snapshot, resolve the supplied
current public profile, and require complete resolved-profile semantic/ID/
effective-digest equality before any driver call. The already-attested binding
must have been created by `from_persisted_receipt(...)`; no receipt object or
receipt payload is accepted here. A package-private convenience may receive a
journal plus receipt ID and invoke that same public constructor internally,
but it cannot create a second public read signature or skip durable lookup.
Construction/configuration is non-effectful and package-owned; public
construction accepts no raw command or authority token. The read adapter cannot
submit, cancel, delete, clean up, mutate Core, or resolve an ambiguous
submission by itself.

On the effect side, `RTWinExecutionAdapter` receives no additional config API:
the existing public `execute_once(..., current_profile=..., port=...)` already
calls `resolve_server_profile(current_profile)` and rejects drift before the
Core claim/port seam. The adapter relies on that frozen public preflight plus
the exact snapshot runtime bindings below; it does not read a global profile or
reimplement Execution profile identity.

### Source-controlled RTwin operation construction

The private operation table version is exactly
`auto-g16-rtwin-operation-table/1`. Its immutable entries are:

| operation | token | argv template | timeout seconds | stdout cap | stderr cap |
| --- | --- | --- | ---: | ---: | ---: |
| allocate | `mkdir-attempt` | `()` | 30 | 65536 | 65536 |
| stage | `stage-exact-bytes` | `("{logical_name}", "{sha256}", "{size_bytes}")` | 900 | 65536 | 65536 |
| qsub | `qsub` | `("{pbs_basename}",)` | 30 | 65536 | 65536 |
| qstat | `qstat` | `("-f", "{job_id}")` | 30 | 262144 | 65536 |
| fetch | `fetch-exact-bytes` | `("{remote_relative_name}",)` | 900 | 0 | 65536 |

Every operation has `shell=False`, no retry, exact cwd equal to the remote
Attempt workspace, and environment exactly `LANG=C`, `LC_ALL=C`,
`PYTHONNOUSERSITE=1`, and `PYTHONUTF8=1`. The allocate operation is one fixed
driver primitive that creates the fresh remote Attempt directory no-follow and
treats the target workspace as its logical cwd; its argv is empty and it
accepts no parent/root or command string. Stage runs exactly twice in prepared
input then PBS-template order; each argv is
`(<logical_name>, <lowercase_sha256>, <base10_size_bytes>)` and exact bytes
travel on the bounded binary input channel. Qsub argv is exactly
`(<one prepared PBS script basename>,)`; qstat argv is the exact tuple frozen
above; fetch argv is exactly `(<one requested remote_relative_name>,)` for each
request in authoritative order and returns content on its bounded binary result
channel, never stdout or a local path. Operation tokens are executable names
and are not repeated inside argv. All text operations require process
completion and EOF within their caps; fetch additionally enforces the artifact
and total-capture caps before returning. Any timeout, overflow, missing EOF,
malformed completion, or possibly-effectful ambiguity fails closed under the
existing Execution uncertainty rules. No operation token or argv fragment is
caller supplied.

Allocate, stage, and qsub substitute only values from the current
identity-closed `ExecutionSnapshot`: exact remote Attempt workspace, the two
exact prepared artifact bindings/bytes, and the PBS basename. Qstat and fetch
substitute only fields from `ExactRemoteJobBinding` plus the validated ordered
`ExactArtifactRequest` tuple. The package-private driver accepts those typed
records and byte channels, never a free path, command string, environment, or
prebuilt argv.

Under the canonical grammar above, the complete table object contains keys
`version`, `cwd_policy`, `shell`, `env`, `limits`, and `operations`; limits are
exactly request count 4, per-artifact bytes 134217728, and total-capture bytes
268435456; operations are the five table rows in displayed order. Its canonical
byte size is `1040` and SHA-256 is
`3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1`.
The exact object shape used for that digest is:

```text
{
  "version": "auto-g16-rtwin-operation-table/1",
  "cwd_policy": "exact-remote-attempt-workspace",
  "shell": false,
  "env": {"LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1",
          "PYTHONUTF8": "1"},
  "limits": {"max_artifact_requests": 4,
             "max_artifact_bytes": 134217728,
             "max_capture_bytes": 268435456},
  "operations": [
    {"name": "allocate", "token": "mkdir-attempt", "argv_template": [],
     "timeout_seconds": 30, "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "stage", "token": "stage-exact-bytes",
     "argv_template": ["{logical_name}", "{sha256}", "{size_bytes}"],
     "timeout_seconds": 900, "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "qsub", "token": "qsub",
     "argv_template": ["{pbs_basename}"], "timeout_seconds": 30,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "qstat", "token": "qstat",
     "argv_template": ["-f", "{job_id}"], "timeout_seconds": 30,
     "stdout_cap": 262144, "stderr_cap": 65536},
    {"name": "fetch", "token": "fetch-exact-bytes",
     "argv_template": ["{remote_relative_name}"],
     "timeout_seconds": 900, "stdout_cap": 0, "stderr_cap": 65536}
  ]
}
```

The adapter accepts only an identity-closed current `ExecutionSnapshot` whose
resolved profile selects `legacy_rtwin_pbs` and whose effect-relevant
`platform_paths` contains these exact required Transport keys; Transport
consults no other platform-path key: `rtwin_root`, `known_hosts`,
`mac_ssh_executable`, `mac_scp_executable`, `rtwin_ssh_executable`,
`rtwin_scp_executable`, `rtwin_bridge_executable`, `server_python_executable`,
`server_qsub_executable`, and `server_qstat_executable`. The first two preserve
their existing meanings; every executable value is an absolute canonical path
to the implementation selected for the corresponding fixed token. The
operation table bytes live under runtime-content name
`auto-g16-rtwin-operation-table/1`; wrapper implementation bytes live under
runtime-content name `rtwin-pbs-v1`; executable byte identities use names
`mac-ssh`, `mac-scp`, `rtwin-ssh`, `rtwin-scp`, `rtwin-bridge`, `server-python`,
`server-qsub`, and `server-qstat`. These exact runtime-content identities and
the table digest/size must all appear in the snapshot's existing
`runtime_identities` and are re-attested before an
operation. The adapter calls public `assert_execution_snapshot_identity(...)`
and relies on `resolved_server_profile.effective_config_sha256` for the
already-closed SSH config/known-host content; it neither opens configuration
files nor reads private profile internals.

These existing resolved profile mappings carry executable/configuration
identity only, never argv fragments, shell text, mutable environment,
credential material, private keys, passwords, tokens, or secret contents.
Host aliases and credential lookup remain driver-private and must match the
attested resolved profile target/config identity; they are not evidence
fields. If any table/runtime binding drifts, the adapter rejects before a port
call. No Core or Execution schema/API change is implied.

### Observe, Result, and full synthetic composition

The Controller owns the mapping seam. It records scheduler evidence through
the existing public Observe constructor/service only after exact binding
validation. It verifies every fetched byte against `FetchedArtifact`, builds
public Result `OutputArtifact` values, then builds and records one public
`OutputEnvelope` with exactly the capture's Attempt, InputBinding observation,
ExecutionSnapshot, source ID, sequence, status/completeness, ordered metadata,
manifest digest, and timestamp. `OutputEnvelope`, `ParseOutcome`,
`GaussianJobParser`, capture cardinality, program facts, and parsing remain
Result-owned. Transport neither imports Result nor parses Gaussian bytes.

After Transport implementation is integrated, one separately gated mandatory
full synthetic composition test under `tests/v3/transport/` uses two test-local
Controllers and only public APIs. Both complete pure Approval replay while the
Attempt is still `PLANNED`, synchronize at a barrier, and then call
`execute_once(...)` concurrently. It proves:

```text
CalculationPlan
-> Scientific Approval
-> exact finite Batch Submit Approval member
-> ExecutionSnapshot
-> Exact Operational Confirmation
-> pure validate_effect_authority
-> execute_once owns Core claim
-> WINNER and exactly one synthetic qsub seam
-> public ReceiptJournal lookup by exact persisted receipt ID
-> ExactRemoteJobBinding with current-profile replay
-> scheduler evidence -> Observe record
-> exact fetched bytes -> Result OutputEnvelope
-> GaussianJobParser -> ParseOutcome
-> MinimumValidationOutcome persistence
-> ReviewBundle
-> separate explicit ScientificAcceptance
```

Exactly one concurrent call obtains `WINNER` and exactly one obtains `REPLAY`;
the replaying port receives zero calls. A later Controller must be rejected by
pure Approval before calling `execute_once(...)`, also with zero port calls;
calling Execution directly after skipping Approval is expressly not official
composition evidence. The test also injects a post-WINNER ambiguous submission
and proves `UNKNOWN` with zero automatic retry; rejects cross-Attempt/snapshot/
receipt/workspace/job, unstable fetch, capture/InputBinding splice, and Result
provenance splice. It also rejects a forged unpersisted receipt, duplicate or
same-record-ID/different-payload durable receipts, and current profile
semantic/identity/effective-digest drift before any driver call. Network/
subprocess/qsub/qdel/Gaussian spies remain at zero. The test-local Controller
is composition evidence only, not a product API. It must not depend on
unmerged Transport bytes. Product
Controller/orchestration code, live transport, and real credentials remain
outside this contract.

### Narrow reuse adjudication and follow-on ownership

- **PORT:** existing public `ExecutionPort`, `execute_once`, snapshot identity
  verifier, `RemoteEffectReceipt`, Observe records/services, Result provenance
  records/services, `GaussianJobParser`, ScientificValidation, and Review APIs.
- **EXTRACT:** strict qstat present/absent/unknown classification, finite timeout
  and stable-read rules, descriptor/no-follow exact-copy checks, and adjacent
  adversarial tests from the reviewed RTwin/direct implementations.
- **WRAP:** the existing `legacy_rtwin_pbs` RTwin/PBS running path behind
  `RTWinExecutionAdapter` and `RTWinReadAdapter`; its internal dictionaries and
  commands are not the new public ABI or authority.
- **REWRITE:** typed transport records, exact snapshot/receipt wrappers, and
  Result-compatible capture mapping. Existing code mixes CLI parsing, mutable
  dictionaries, legacy project-level state, and owner/capability governance, so
  directly porting it would preserve the wrong authority and API.
- **DROP:** legacy owner/receipt/capability/hash-lineage authority, non-empty
  project as a v3 rule, qdel/cancellation, deletion/cleanup, implicit latest
  discovery, parser/scientific policy, and automatic retry.
- **DEFER:** OpenSSH, process and Gaussian-phase acquisition, checkpoint fetch,
  rich telemetry/stall diagnosis, deployment, credentials, production smoke,
  and every live operation.

Before Transport implementation, a separate `V30-VAL-TRANSPORT-01` must add
change-aware ownership for `auto_g16/transport/**` and
`tests/v3/transport/**`. Until then those paths remain intentionally
fail-closed. This contract candidate stops after independent adversarial
review and publication gates; it grants no implementation or live authority.

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
