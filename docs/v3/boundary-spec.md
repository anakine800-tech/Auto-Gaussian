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

### Composite internal-step Gaussian job successor

The additive successor retains the public `GaussianJobParser` name and
`gaussian-job-facts` kind but freezes a new exact tuple and grammar:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.1.0
result_kind    = gaussian-job-facts
grammar_id     = auto-g16-v3-gaussian-job-grammar/2
```

The existing `1.0.0` tuple remains bound only to grammar-1. Both tuples use
outer `ParseOutcome` schema version 1, coexist append-only for one envelope,
and retain distinct deterministic Result identities. No old outcome is
migrated, reinterpreted, overwritten, or backfilled.

Grammar-2 admits exactly one external `JOB_START`. It rejects a second
external `JOB_START` and `LINK1_LITERAL`. An internal step is an exact
`Proceeding to internal job step number N.` marker, optionally with the
Gaussian-emitted `Link1:` prefix; the first `N` is 2 and later values must be
3, 4, and so on without gaps, repeats, or decreases. An internal step may
start only after the preceding component's exact normal terminal and never
after an error terminal. The parser must close every component and the final
component before returning `PARSED`.

At parser top level, an exact `GRAD_BOUNDARY` is a structural separator within
the same external invocation and emits no scientific fact. The same anchor in
an unfinished optimization, frequency, geometry, or other admitted child
production fails under that child production. It is never a free wildcard.

`job_section` spans the complete external invocation through the final
terminal. `termination_evidence` contains every physical terminal item in
strict byte order; the normal and error counts equal those exact items. Overall
`normal-termination` requires one or more terminal items, all normal, a closed
contiguous internal-step chain, no error item, and a final normal terminal.
Any error item yields `error-termination` and forbids continuation. Extra or
unexplained terminals are unparseable.

The existing optimization, stationary, geometry, and frequency fact shapes
remain unchanged. ScientificValidation dispatches on the complete tuple.
Grammar-1 retains its singular terminal rule and final-pair selection.
Grammar-2 requires an all-normal terminal sequence and chooses the rightmost
closed optimization/stationary pair whose stationary span ends no later than
the first attributed frequency block. The unique rightmost complete geometry
before that optimization span and the complete ordered frequency-block suffix
after that stationary span are then evaluated under the unchanged nonlinear
minimum policy. A frequency block with no preceding closed pair is
`INCOMPLETE`; no raw bytes are reopened by ScientificValidation.

This successor changes no public fact field, Core/Result schema, validation
classification, reason vocabulary, acceptance record, execution authority, or
live boundary.

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

The exact supported parser tuples are:

```text
parser_name    = auto-g16-v3-gaussian-job
parser_version = 1.0.0 | 1.1.0
result_kind    = gaussian-job-facts
```

Version `1.0.0` is bound only to grammar-1; version `1.1.0` is bound only to
grammar-2. Every other tuple remains unsupported.

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

For a parsed grammar-1 tuple, ScientificValidation first requires exactly one
normal terminal fact, no error terminal fact, and `program_status =
normal-termination`. For grammar-2 it requires at least one normal terminal,
zero error terminals, terminal-evidence cardinality equal to the normal count,
and every terminal item normal. A context-attributed error termination is
always `INCOMPLETE`, never `NOT_MINIMUM` or `VALIDATED_MINIMUM`.

`optimization_completed_evidence` and `stationary_point_evidence` must be
non-empty tuples of equal cardinality. They pair only by the same tuple index.
For every index, the complete optimization span must precede its stationary
span; each pair must precede the next pair. Grammar-1 accepts the final pair.
Grammar-2 accepts the rightmost closed pair whose stationary span ends no later
than the first attributed frequency block. A missing, unequal, interleaved,
otherwise non-closing sequence, or grammar-2 frequency evidence preceding
every pair is `INCOMPLETE`; no marker boolean repairs it.

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

**Contract status: CLOSED / FROZEN / INTEGRATED.** The physical-authority trust
closeout below is the active successor authority. This additive contract opens only the offline
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

The frozen `auto_g16.transport` export set for the successor implementation is
exactly:

```text
TransportBoundaryError
TransportStore
ExactRemoteJobBinding
SchedulerReadEvidence
ExactArtifactRequest
FetchedArtifact
FetchedOutputCapture
RTWinExecutionAdapter
RTWinReadAdapter
```

`TransportBoundaryError` inherits `ValueError` and owns malformed, stale,
cross-Attempt, cross-snapshot, cross-receipt, unstable-read, unsafe-path, and
persistence-integrity failures at this boundary. `TransportStore` is the only
public persistence owner added by the trust closeout below. Public records are
frozen, slotted, keyword-only, and deeply immutable. Public functions/classes
accept no arbitrary command, shell fragment, callback, remote root, or caller-
selected executable.

`ExactRemoteJobBinding` has exactly these eight fields:

```text
transport_store_id: str
store_instance_id: str
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
    transport_store: TransportStore,
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
supplied `TransportStore` must also contain the unique exact job/receipt record
and its linked workspace physical token frozen below. It copies
`transport_store_id` and `store_instance_id` only from the attested singleton
meta row and requires the same two IDs on every linked store record. The record
has `init=False`; callers cannot construct it from strings alone.

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

`binding_payload` is the exact eight-key object named by the eight
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

The normative fixture uses binding `{transport_store_id:
"108c8d43-2ea9-5658-9607-ade4cbbeac85", store_instance_id:
"28c10d1a-9f8f-5ce6-84d1-555175c0fcde", attempt_id: "attempt-1",
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
a8:s33:auto-g16-transport/scheduler-readi1;o8:s10:attempt_ids9:attempt-1s21:execution_snapshot_ids10:snapshot-1s6:job_ids10:123.servers24:remote_effect_receipt_ids9:receipt-1s16:remote_workspaces16:/srv/p/attempt-1s17:store_instance_ids36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes20:submission_intent_ids8:intent-1s18:transport_store_ids36:108c8d43-2ea9-5658-9607-ade4cbbeac85s27:2026-08-23T00:00:00.000000Zs5:freshs7:runnings64:664e69c9fa7687ddb0b54d38d11eafeff8a4b93d07fb7a97a51263ddf45191b5i37;
```

The scheduler source ID is
`90232e65-d755-5ed7-8c65-0ca18c1f104b`.

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
a12:s33:auto-g16-transport/output-capturei1;o8:s10:attempt_ids9:attempt-1s21:execution_snapshot_ids10:snapshot-1s6:job_ids10:123.servers24:remote_effect_receipt_ids9:receipt-1s16:remote_workspaces16:/srv/p/attempt-1s17:store_instance_ids36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes20:submission_intent_ids8:intent-1s18:transport_store_ids36:108c8d43-2ea9-5658-9607-ade4cbbeac85s19:input-observation-1i1;s8:captureds8:completea1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs20:remote_relative_names7:job.logs8:requiredb1;a1:o4:s13:artifact_kinds12:gaussian-logs12:logical_names7:job.logs6:sha256s64:d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618s10:size_bytesi19;a0:s64:1636f90c920537ebc491e0c7a173377a66db2cef4c28d488d435dd537e43a25fs27:2026-08-23T00:01:00.000000Z
```

The capture source ID is
`a7bc80d8-d7b0-59cc-b68e-617bce8b5168`. Exact replay keeps identity;
any authority-semantic change changes identity; same ID with different payload
fails closed. These evidence identities are audit/source bindings, never
approval or effect authority.

The only public adapter constructors are
`RTWinExecutionAdapter(*, transport_store: TransportStore,
current_profile: ServerProfile)` and
`RTWinReadAdapter(*, transport_store: TransportStore)`. Construction is
non-effectful, and package-private driver/clock seams may be replaced only by
tests without entering the public API.
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
must have been created by `from_persisted_receipt(...)` using the same open
`TransportStore`; no receipt object, receipt payload, physical token, or
alternate store is accepted here. A package-private convenience may receive a
journal plus receipt ID and invoke that same public constructor internally,
but it cannot create a second public read signature or skip either durable
lookup.
Construction/configuration is non-effectful and package-owned; public
construction accepts no raw command or authority token. The read adapter cannot
submit, cancel, delete, clean up, mutate Core, or resolve an ambiguous
submission by itself.

On the effect side, `TransportStore` is persistence rather than configuration.
The execution adapter retains the exact current public `ServerProfile` only so
each port call can resolve it again, compare the complete resolved value with
the supplied snapshot, and obtain the one fixed manifest runtime-content entry.
It accepts no independent manifest bytes. The existing public
`execute_once(..., current_profile=..., port=...)` preflight remains unchanged;
the adapter repeats the same public profile closure before any driver call and
does not read a global profile or reimplement Execution profile identity.

### Snapshot-derived PBS resource enactment

`ExecutionSnapshot.resolved_resource_request` is the sole scheduler-resource
authority. Transport derives a private `ResourceEnactment` mechanical value
with exactly `execution_snapshot_id`, `resolved_resource_request_id`, `cores`,
`memory_mb`, `walltime_seconds`, `queue`, and `scheduler_dialect_id`. The first
six values replay the identity-closed snapshot exactly; the dialect is selected
only by current-profile runtime content named
`pbs-resource-enactment-v1.json`. The canonical descriptor is UTF-8 canonical
JSON plus one LF with exactly `schema` and `dialect`, where `schema` is
`auto-g16-v3-pbs-resource-enactment/1`. It contains no resource value,
executable, argv, option, format string, shell text, or credential.

`SUBMIT_QSUB_ONCE` protocol `/2` carries only the exact PBS basename and the
closed nested resource-enactment object. It carries no rendered argv. The fixed
Transport adapter validates that value against the current identity-closed
snapshot/profile before framing. The fixed bootstrap validates exact key sets,
types, IDs, positive non-boolean integer
resources, optional portable queue, and a closed dialect identifier. A
source-controlled renderer then derives qsub argv solely from dialect, cores,
memory MB, walltime seconds, optional queue, and PBS basename; the exact
manifest-bound qsub executable is invoked with `shell=False`. Any mismatch,
unknown/missing dialect, unrepresentable walltime, queue substitution, extra
token, or caller-supplied argv rejects before qsub.
The bootstrap neither reconstructs nor independently authenticates an
ExecutionSnapshot; equality with snapshot authority is owned by the adapter
before the bounded request crosses the transport boundary.

The one offline dialect is exactly
`auto-g16-v3-pbs-resource-enactment/synthetic-test/1`. It is deliberately not
a scheduler dialect and renders the exact non-production vector
`(--auto-g16-synthetic-cores, <cores>, --auto-g16-synthetic-memory-mb,
<memory_mb>, --auto-g16-synthetic-walltime-seconds, <walltime_seconds>,
[--auto-g16-synthetic-queue, <queue>], <pbs_basename>)`. The live subprocess
driver and fixed bootstrap reject execution of this dialect before process/qsub
creation. Its pure renderer is test evidence only. It proves deterministic
binding without guessing PBS Pro, Torque, OpenPBS, or deployment syntax.

### Exact Torque 6.1.0 production dialect

The accepted read-only deployment preflight qualifies exactly one production
renderer for the first V30-A target:
`auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`. It is not a
generic Torque/PBS renderer. Its deployment evidence is the exact active
single-node Torque `6.1.0` server with `np = 44`, queue `batch`, and these
manifest-owned executable roots:

| root | exact path | size | SHA-256 |
| --- | --- | ---: | --- |
| `server_qsub` | `/usr/local/bin/qsub` | 418920 | `f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d` |
| `server_qstat` | `/usr/local/bin/qstat` | 185656 | `3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a` |

The binaries are not package-manager-owned. Their manifest identity therefore
does not invent a package name or version authority. The production renderer
returns arguments only; the manifest-bound `server_qsub.path` remains the sole
executable selection at `run_exact(...)`.

For positive non-boolean integers `C = cores`, `M = memory_mb`, and
`W = walltime_seconds`, exact queue `Q`, and portable PBS basename `B`, the
complete production argument tuple is exactly:

```text
("-l", "nodes=1:ppn=C,mem=Mmb,walltime=W", "-q", "Q", "B")
```

The integers use canonical decimal digits with no sign. Resources are one
comma-separated `-l` value in the exact order `nodes`, `mem`, `walltime`.
Memory stays integer MB and time stays integer seconds. No GB conversion,
`HH:MM:SS` conversion, split `-l`, alternative spelling, option reordering, or
caller fragment is valid.

For the first V30-A deployment, queue is mandatory and must equal `batch`.
`queue = null` and every other token reject before process creation. The
observed default queue is never used as resource authority. Active PBS
resource directives, including `#PBS -l` and `#PBS -q`, remain rejected by the
staged v3 template contract, so qsub arguments are the only scheduler-resource
enactment.

The descriptor schema remains unchanged and closed. It admits only the exact
synthetic-test ID and this exact Torque ID. There is no submit-time detection,
fallback, alias, version range, executable, argv fragment, or scheduler
default in the descriptor. The Torque dialect is mechanically live-capable;
the synthetic dialect remains non-live. Neither classification grants an
effect: the complete live authority chain and a separate V30-A Live Owner Gate
remain required.

For the synthetic test dialect, `queue = null` emits no synthetic queue pair.
For the production Torque dialect, queue is required and must equal `batch`;
there is no default or omission path. An explicit queue is never replaced.
Walltime uses integer seconds without floating point or rounding. Memory comes
from exact `memory_mb`, never Gaussian `%mem`; cores come from exact `cores`,
never `%nprocshared`. PBS template resource directives remain forbidden.
Descriptor drift changes the resolved profile and snapshot and therefore
requires new exact Operational Confirmation. `REPLAY` performs zero qsub and
`UNKNOWN` never authorizes a second qsub.

Because request and operation-table semantics change, the successor identities
are `auto-g16-v3-rtwin-bootstrap/2`,
`auto-g16-rtwin-operation-table/2`, and
`auto-g16-v3-rtwin-bootstrap-v2.py`. Protocol `/1` and its exact vectors remain
immutable historical evidence. Protocol `/2` keeps the same seven operations,
AGV3 framing, bounded channels, nine deployment trust roots, physical
bindings, no-shell execution, and no-retry semantics. The v2 table changes
only the submit row's declared argv authority to the exact ordered inputs
`scheduler_dialect_id`, `cores`, `memory_mb`, `walltime_seconds`, `queue`, and
`pbs_basename`; final argv is renderer output, never request data.

The exact synthetic descriptor bytes are
`{"dialect":"auto-g16-v3-pbs-resource-enactment/synthetic-test/1","schema":"auto-g16-v3-pbs-resource-enactment/1"}\n`:
114 bytes with SHA-256
`9327ef2f0e11f5292daa7af22c00276bc504e2ffb31c2fdb585642fec1cd462c`.
The exact canonical table-v2 bytes are 1570 bytes with SHA-256
`14cdd511bb6c4eb78af8f07d774cfdae27fc1c661dae8692b45e48ccd7fa31af`.
They equal the historical table object except `version` is `/2` and submit
`argv_template` is exactly
`["{scheduler_dialect_id}","{cores}","{memory_mb}","{walltime_seconds}","{queue}","{pbs_basename}"]`.
For submit only, those markers declare closed renderer inputs rather than
caller/final argv. All other table rows and fields replay byte-for-byte.

For protocol `/2`, the exact `SUBMIT_QSUB_ONCE` binding keys remain the `/1`
submitted set: `transport_store_id`, `store_instance_id`,
`runtime_attestation_id`, `attempt_id`, `execution_snapshot_id`,
`submission_intent_id`, `remote_workspace`, `workspace_authority_id`,
`workspace_physical_token_base64`,
`prepared_input_artifact_authority_id`,
`prepared_input_artifact_physical_token_base64`,
`pbs_template_artifact_authority_id`, and
`pbs_template_artifact_physical_token_base64`. Its payload has exactly two
keys: `pbs_basename` and `resource_enactment`. The nested object has exactly
seven keys: `execution_snapshot_id`, `resolved_resource_request_id`, `cores`,
`memory_mb`, `walltime_seconds`, `queue`, and `scheduler_dialect_id`.
Nested `execution_snapshot_id` equals the binding value; the request/resource
ID and four resource values equal the current snapshot. All IDs and dialect
are non-empty closed strings, cores/memory/walltime are positive non-boolean
integers, and queue alone may be JSON `null`; otherwise it is one portable
name. Extra, missing, bool-as-int, alias, or mismatched values reject.

The exact canonical `/2` qsub request vector is 958 bytes with SHA-256
`73c94b0942724b8627016de958bcea247098a5b68b47a3baf0f8c0b9dd8253ad`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","pbs_template_artifact_authority_id":"pbs-artifact-1","pbs_template_artifact_physical_token_base64":"cGJzLXRva2VuLTE=","prepared_input_artifact_authority_id":"input-artifact-1","prepared_input_artifact_physical_token_base64":"aW5wdXQtdG9rZW4tMQ==","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"runtime-1","store_instance_id":"instance-1","submission_intent_id":"intent-1","transport_store_id":"store-1","workspace_authority_id":"workspace-1","workspace_physical_token_base64":"d29ya3NwYWNlLTE="},"operation":"SUBMIT_QSUB_ONCE","payload":{"pbs_basename":"job.pbs","resource_enactment":{"cores":8,"execution_snapshot_id":"snapshot-1","memory_mb":12288,"queue":"simple","resolved_resource_request_id":"resource-request-1","scheduler_dialect_id":"auto-g16-v3-pbs-resource-enactment/synthetic-test/1","walltime_seconds":3600}},"protocol":"auto-g16-v3-rtwin-bootstrap/2"}
```

The other six operation request/response schemas replay `/1` exactly except
their top-level protocol literal is `/2`. The `/2` current runtime-content set
has exactly four required names: `transport-deployment-manifest-v1.json`,
`auto-g16-rtwin-operation-table/2`,
`auto-g16-v3-rtwin-bootstrap-v2.py`, and
`pbs-resource-enactment-v1.json`. The manifest schema stays `/1` but its
`bootstrap_protocol` is exactly `/2`. TransportStore schema-v1 is unchanged:
its runtime row records the resolved-profile identity plus manifest, table-v2,
and source-v2 identities; the dialect descriptor is already transitively bound
by that resolved-profile identity and is reverified directly against the
snapshot runtime identity on every authority resolution. It is not duplicated
as a second mutable store authority.

The `/2` `SUBMIT_QSUB_ONCE` response also replays `/1` exactly except its
top-level protocol literal is `/2`: top-level keys are exactly `operation`,
`protocol`, `result`, and `status`; operation echoes `SUBMIT_QSUB_ONCE`, status
is `ok`, and result contains exactly one strict normalized PBS `job_id`. It
contains no resource, dialect, renderer, argv, executable, environment, or
other echo/evidence field. The exact canonical response is 123 bytes with
SHA-256 `c1a9556d75c9f0fc390ed89100a1241c1fc44abb6d1f2b568a476445672fa2d3`:

```json
{"operation":"SUBMIT_QSUB_ONCE","protocol":"auto-g16-v3-rtwin-bootstrap/2","result":{"job_id":"123.server"},"status":"ok"}
```

The exact Torque-capable Phase-B fixed successor source is
`auto-g16-v3-rtwin-bootstrap-v2.py`: 15597 UTF-8/ASCII bytes, exactly 204 LF,
zero CR/NUL, and SHA-256
`b0b1bcaf8ab8697a80676ac1015503a2fb64c21949678f20bf05f3bd849fb10e`.
It starts with `from __future__ import annotations\n`, ends with `main()\n`,
and contains the closed request validation, unchanged synthetic vector with
pre-qsub non-production rejection, and the exact Torque vector construction
above. Any source name, byte, line-ending, size, count, or digest drift rejects
during profile/snapshot resolution. The pre-Phase-B integrated source was
15195 bytes, 201 LF, with SHA-256
`3f3653a8b13d4cb5a5f5ba6e9caa02c3049caf144af13fd4491674c1fc7eb2f3`;
it remains immutable historical evidence and is not an accepted production-
Torque source.

### Historical bootstrap /1 source-controlled operation construction

This subsection and its `/1` table, basename-only qsub, three-content runtime
inventory, bootstrap-source vector, and wire vectors are immutable historical
evidence for the integrated predecessor. Once the resource-enactment successor
is present, the `/2` rules above are current and override every `/1` statement
for executable Transport resolution; implementations must not satisfy both or
reinterpret `/1`.

The private operation table version is exactly
`auto-g16-rtwin-operation-table/1`. Its immutable entries are:

| operation | token | argv template | timeout seconds | stdin cap | stdout cap | stderr cap |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `ALLOCATE_WORKSPACE` | `allocate-workspace` | `()` | 30 | 65536 | 65536 | 65536 |
| `STAGE_EXACT_FILE` | `stage-exact-file` | `("{logical_name}", "{sha256}", "{size_bytes}")` | 900 | 179306496 | 65536 | 65536 |
| `SUBMIT_QSUB_ONCE` | `submit-qsub-once` | `("{pbs_basename}",)` | 30 | 65536 | 65536 | 65536 |
| `QUERY_SCHEDULER` | `query-scheduler` | `("-f", "{job_id}")` | 30 | 65536 | 524288 | 65536 |
| `STAT_EXACT_FILE` | `stat-exact-file` | `("{remote_relative_name}",)` | 30 | 65536 | 65536 | 65536 |
| `FETCH_EXACT_FILE` | `fetch-exact-file` | `("{remote_relative_name}",)` | 900 | 65536 | 179306496 | 65536 |
| `RECONCILE_SUBMISSION` | `reconcile-submission` | `()` | 30 | 65536 | 262144 | 65536 |

Every operation has `shell=False` at the final server operation/executable
seam, no retry, exact cwd equal to the remote Attempt workspace, and environment
exactly `LANG=C`, `LC_ALL=C`,
`PYTHONNOUSERSITE=1`, and `PYTHONUTF8=1`. The allocate operation is one fixed
driver primitive that creates the fresh remote Attempt directory no-follow and
treats the target workspace as its logical cwd; its argv is empty and it
accepts no parent/root or command string. Stage runs exactly twice in prepared
input then PBS-template order; each argv is
`(<logical_name>, <lowercase_sha256>, <base10_size_bytes>)` and exact bytes
travel in the framed data packet. Qsub argv is exactly
`(<one prepared PBS script basename>,)`; qstat argv is the exact tuple frozen
above; stat/fetch argv is exactly `(<one requested remote_relative_name>,)` for
each request in authoritative order. Reconciliation has no argv and consumes
only the exact binding data packet. Operation tokens are enum data, not
executable names or shell text. The `stdin_cap` and `stdout_cap` columns bound
the complete outer AGV3 request and response frames respectively. The inner
qstat raw stdout/stderr limits remain 262144/65536 bytes; their base64 fields
fit the 524288-byte outer response cap. A fetch returns its exact raw bytes only
as canonical base64 inside the one bounded stdout response frame described
below, never through an unspecified side channel or a local path. Every
operation requires process completion and EOF within all caps; fetch additionally
enforces the raw artifact and total-capture caps before encoding. Any timeout,
overflow, missing EOF, malformed completion, or possibly-effectful ambiguity
fails closed under the existing Execution uncertainty rules. No operation
token or argv fragment is caller supplied.

Allocate, stage, and qsub substitute only values from the current
identity-closed `ExecutionSnapshot`: exact remote Attempt workspace, the two
exact prepared artifact bindings/bytes, and the PBS basename. Qstat and fetch
substitute only fields from `ExactRemoteJobBinding` plus the validated ordered
`ExactArtifactRequest` tuple. The package-private driver accepts those typed
records and byte channels, never a free path, command string, environment, or
prebuilt argv.
This table field does not deny the two explicitly modeled SSH remote shells;
it forbids the fixed bootstrap from invoking another shell for an operation.

Under the canonical grammar above, the complete table object contains keys
`version`, `cwd_policy`, `shell`, `env`, `limits`, and `operations`; limits are
exactly request count 4, per-artifact bytes 134217728, and total-capture bytes
268435456; operations are the seven table rows in displayed order. Canonical
table bytes use the manifest JSON rules below, including one trailing LF. Their
byte size is `1490` and SHA-256 is
`6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6`.
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
    {"name": "ALLOCATE_WORKSPACE", "token": "allocate-workspace", "argv_template": [],
     "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "STAGE_EXACT_FILE", "token": "stage-exact-file",
     "argv_template": ["{logical_name}", "{sha256}", "{size_bytes}"],
     "timeout_seconds": 900, "stdin_cap": 179306496,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "SUBMIT_QSUB_ONCE", "token": "submit-qsub-once",
     "argv_template": ["{pbs_basename}"], "timeout_seconds": 30,
     "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "QUERY_SCHEDULER", "token": "query-scheduler",
     "argv_template": ["-f", "{job_id}"], "timeout_seconds": 30,
     "stdin_cap": 65536, "stdout_cap": 524288, "stderr_cap": 65536},
    {"name": "STAT_EXACT_FILE", "token": "stat-exact-file",
     "argv_template": ["{remote_relative_name}"],
     "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 65536, "stderr_cap": 65536},
    {"name": "FETCH_EXACT_FILE", "token": "fetch-exact-file",
     "argv_template": ["{remote_relative_name}"],
     "timeout_seconds": 900, "stdin_cap": 65536,
     "stdout_cap": 179306496, "stderr_cap": 65536},
    {"name": "RECONCILE_SUBMISSION", "token": "reconcile-submission",
     "argv_template": [], "timeout_seconds": 30, "stdin_cap": 65536,
     "stdout_cap": 262144, "stderr_cap": 65536}
  ]
}
```

The adapter accepts only an identity-closed current `ExecutionSnapshot` whose
resolved profile selects `legacy_rtwin_pbs`. The fixed runtime-content names
are exactly `transport-deployment-manifest-v1.json`,
`auto-g16-rtwin-operation-table/1`, and
`auto-g16-v3-rtwin-bootstrap-v1.py`; the latter is the one
fixed bootstrap-source/bridge content owned by protocol
`auto-g16-v3-rtwin-bootstrap/1`. Exact byte identities for all three must appear
in the snapshot's existing `runtime_identities`. Executable and remote-shell
paths come only from the manifest; Transport does not choose between those
values and duplicate `platform_paths` values. Existing `rtwin_root` and
`known_hosts` profile/config semantics remain bound by the resolved profile but
are not an alternate manifest.

The adapter calls public `assert_execution_snapshot_identity(...)`, obtains the
exact manifest bytes only from the retained/current public `ServerProfile`,
calls public `resolve_server_profile(...)`, and requires complete equality with
the snapshot's resolved profile plus exact manifest `bytes_identity` equality
with `runtime_identities["transport-deployment-manifest-v1.json"]`. Missing,
renamed, duplicated-by-alias, or changed bytes reject before parsing or any
driver call. It relies on `effective_config_sha256` for the already-closed SSH
config/known-host content and neither opens configuration files nor reads
private Execution internals.

These existing resolved profile mappings carry configuration and exact runtime
content identity only, never argv fragments, mutable environment,
credential material, private keys, passwords, tokens, or secret contents.
Host aliases and credential lookup remain driver-private and must match the
attested resolved profile target/config identity; they are not evidence
fields. If any table/runtime binding drifts, the adapter rejects before a port
call. No Core or Execution schema/API change is implied.

### Historical bootstrap /1 canonical deployment-manifest vector

The only manifest authority is the immutable bytes at
`ServerProfile.runtime_contents["transport-deployment-manifest-v1.json"]`.
Transport first resolves the current profile and closes it exactly against the
snapshot as above; it then requires the manifest byte identity
`{"sha256": lowercase_sha256, "size_bytes": positive_integer}` to equal that
exact fixed `runtime_identities` entry. No manifest parameter, alias, fallback,
ambient file, global singleton, latest/current lookup, or stored TransportStore
row may replace those bytes.

Manifest bytes are UTF-8 without BOM and are exactly one JSON object encoded by:

```text
json.dumps(
    object,
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
    sort_keys=True,
).encode("utf-8") + b"\n"
```

Parsing rejects duplicate keys, nonfinite numbers, invalid UTF-8, missing or
extra LF, and any byte sequence unequal to canonical replay. The top-level keys
are exactly `bootstrap_protocol`, `deployment_id`, `schema`, and
`trust_roots`. Constants are exactly
`auto-g16-v3-transport-deployment-manifest/1` and
`auto-g16-v3-rtwin-bootstrap/1`; `deployment_id` is a non-empty canonical
deployment-owned string, never ambiently discovered or generated per Attempt.
It and every other manifest string reject NUL, CR, and LF.

`trust_roots` has exactly `mac_ssh`, `mac_scp`, `rtwin_ssh`,
`rtwin_scp`, `rtwin_remote_shell`, `server_remote_shell`,
`server_python`, `server_qsub`, and `server_qstat`. Every value has exactly
`attestation_mode`, `deployment_identity`, `expected_sha256`,
`expected_size_bytes`, `path`, `platform`, and `shell_grammar`.
`deployment_identity` is non-empty; paths are absolute and platform-native;
platform is exactly `macos`, `windows`, or `posix`; a present digest is
lowercase 64-hex; and a present size is a positive non-boolean integer.

The exact per-name matrix is:

| root | platform | attestation mode | digest/size | shell grammar |
| --- | --- | --- | --- | --- |
| `mac_ssh` | `macos` | `controller-file-v1` | required | null |
| `mac_scp` | `macos` | `controller-file-v1` | required | null |
| `rtwin_ssh` | `windows` | `rtwin-shell-file-v1` | required | null |
| `rtwin_scp` | `windows` | `rtwin-shell-file-v1` | required | null |
| `rtwin_remote_shell` | `windows` | `deployment-root-v1` | null | exactly `powershell-v1` or `cmd-v1` |
| `server_remote_shell` | `posix` | `deployment-root-v1` | null | `posix-sh-v1` |
| `server_python` | `posix` | `server-self-check-v1` | required | null |
| `server_qsub` | `posix` | `server-python-file-v1` | required | null |
| `server_qstat` | `posix` | `server-python-file-v1` | required | null |

No tenth root, missing root, extra field, alternative mode, null outside the
two shell rows, or grammar inference is valid. Shell rows are deployment trust
roots and do not authenticate themselves before interpreting the first remote
command. `server_python` likewise starts from deployment trust; its
`server-self-check-v1` is post-start drift detection, not trust creation.

The complete normative synthetic manifest is the following single line plus
one LF:

```json
{"bootstrap_protocol":"auto-g16-v3-rtwin-bootstrap/1","deployment_id":"synthetic-rtwin-deployment-v1","schema":"auto-g16-v3-transport-deployment-manifest/1","trust_roots":{"mac_scp":{"attestation_mode":"controller-file-v1","deployment_identity":"synthetic-macos-openssh-9.8p1","expected_sha256":"2222222222222222222222222222222222222222222222222222222222222222","expected_size_bytes":1049600,"path":"/usr/bin/scp","platform":"macos","shell_grammar":null},"mac_ssh":{"attestation_mode":"controller-file-v1","deployment_identity":"synthetic-macos-openssh-9.8p1","expected_sha256":"1111111111111111111111111111111111111111111111111111111111111111","expected_size_bytes":1048576,"path":"/usr/bin/ssh","platform":"macos","shell_grammar":null},"rtwin_remote_shell":{"attestation_mode":"deployment-root-v1","deployment_identity":"synthetic-windows-powershell-5.1","expected_sha256":null,"expected_size_bytes":null,"path":"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe","platform":"windows","shell_grammar":"powershell-v1"},"rtwin_scp":{"attestation_mode":"rtwin-shell-file-v1","deployment_identity":"synthetic-windows-openssh-9.5p1","expected_sha256":"4444444444444444444444444444444444444444444444444444444444444444","expected_size_bytes":1110000,"path":"C:\\Windows\\System32\\OpenSSH\\scp.exe","platform":"windows","shell_grammar":null},"rtwin_ssh":{"attestation_mode":"rtwin-shell-file-v1","deployment_identity":"synthetic-windows-openssh-9.5p1","expected_sha256":"3333333333333333333333333333333333333333333333333333333333333333","expected_size_bytes":1100000,"path":"C:\\Windows\\System32\\OpenSSH\\ssh.exe","platform":"windows","shell_grammar":null},"server_python":{"attestation_mode":"server-self-check-v1","deployment_identity":"synthetic-server-python-3.13","expected_sha256":"5555555555555555555555555555555555555555555555555555555555555555","expected_size_bytes":1200000,"path":"/usr/bin/python3","platform":"posix","shell_grammar":null},"server_qstat":{"attestation_mode":"server-python-file-v1","deployment_identity":"synthetic-pbs-2024.1","expected_sha256":"7777777777777777777777777777777777777777777777777777777777777777","expected_size_bytes":140000,"path":"/usr/bin/qstat","platform":"posix","shell_grammar":null},"server_qsub":{"attestation_mode":"server-python-file-v1","deployment_identity":"synthetic-pbs-2024.1","expected_sha256":"6666666666666666666666666666666666666666666666666666666666666666","expected_size_bytes":130000,"path":"/usr/bin/qsub","platform":"posix","shell_grammar":null},"server_remote_shell":{"attestation_mode":"deployment-root-v1","deployment_identity":"synthetic-posix-sh-v1","expected_sha256":null,"expected_size_bytes":null,"path":"/bin/sh","platform":"posix","shell_grammar":"posix-sh-v1"}}}
```

Its exact byte count is `2753`, SHA-256 is
`70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983a`,
and its exact resolved-profile runtime identity is
`{"sha256":
"70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983a",
"size_bytes": 2753}`. Tests construct a current `ServerProfile` with these
exact bytes, call public `resolve_server_profile`, and require that exact
mapping under the fixed logical name before and after snapshot construction.

### Historical bootstrap /1 fixed source and remote-shell grammars

The real trust chain is controller -> exact `mac_ssh` -> Windows OpenSSH
server -> manifest-declared RTwin remote shell -> exact `rtwin_ssh` -> server
OpenSSH server -> manifest-declared `posix-sh-v1` shell -> exact
`server_python` -> exact qsub/qstat or descriptor-relative file operation.
Local `shell=False` removes only an additional controller shell.
The two OpenSSH server services are part of their host OS/deployment boundary,
not caller-selected executables or extra runtime manifest roots; changing their
deployment/security authority is outside this offline contract.

`mac_ssh` and `mac_scp` are opened no-follow and compared with their
manifest path, regular/executable type, size, digest, and deployment-owned
permission conditions before absolute-path structured-argv launch. The
deployment-trusted RTwin shell performs `rtwin-shell-file-v1` for RTwin
SSH/SCP. For `powershell-v1`, manifest strings reject NUL/CR/LF and are
single-quoted with each `'` replaced by `''`. One fixed script sets
`ErrorActionPreference=Stop`, uses `Get-Item -LiteralPath` to reject
containers/reparse links and compare exact length, then
`Get-FileHash -LiteralPath ... -Algorithm SHA256` and ordinal-lowercase digest
equality. It launches the exact path through
`System.Diagnostics.ProcessStartInfo` with `UseShellExecute=false`; the
`Arguments` string is produced only by the frozen Windows CRT encoder already
specified below, and process completion/EOF remain bounded.

`cmd-v1` recognizes only manifest/fixed-launcher tokens matching
`[A-Za-z0-9_:.\\/ -]+`; its deterministic token encoder surrounds each token
with `"` and rejects `"`, `%`, `!`, `^`, `&`, `|`, `<`, `>`,
`(`, `)`, NUL, CR, or LF. The nine-root model intentionally contains no
cmd builtin capable of exact SHA-256 verification of an arbitrary executable.
Therefore a `cmd-v1` deployment parses deterministically but fails
`rtwin-shell-file-v1` compatibility with zero RTwin child invocation. Adding
PowerShell, certutil, a bridge, or another hasher would be a tenth trust root
and requires a new Owner contract; Transport never falls back. This is the
frozen meaning of “if the selected grammar cannot attest safely, fail closed.”

The server shell is exactly `posix-sh-v1`. It has two deliberately separate
encoders with the same byte-preserving single-quote construction:

```text
quote_variable(token) = "'" + token.replace("'", "'\"'\"'") + "'"
quote_bootstrap_source(source) = "'" + source.replace("'", "'\"'\"'") + "'"

command = " ".join([
  quote_variable(server_python), quote_variable("-I"), quote_variable("-S"),
  quote_variable("-B"), quote_variable("-c"),
  quote_bootstrap_source(EXACT_BOOTSTRAP_SOURCE),
  quote_variable(manifest_base64),
])
```

Every variable token rejects NUL, CR, and LF; an empty variable token becomes
`''`. The exact bootstrap source is not a variable token. It permits ASCII LF
but rejects NUL and CR, uses LF-only line endings, and is passed as exactly one
shell word. POSIX single quotes keep embedded LF literal, and a source literal
`'` uses the deterministic close/escaped-quote/reopen sequence above. Decoding
either quoted form reproduces the exact input bytes. No variable value is
concatenated into the quoted source, and source LF cannot terminate the one
quoted shell word or create another command.

The one launcher is exact manifest `server_python` with fixed flags
`-I -S -B -c` and exact source-controlled
`auto-g16-v3-rtwin-bootstrap-v1.py` bytes. That constant is ASCII, begins
`from __future__ import annotations\n`, ends `main()\n`, contains exactly 190
LF bytes and no CR/NUL, has exact size `13904`, and has SHA-256
`056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`.
The implementation test computes size/digest from the exact source constant;
no hand-maintained alternate source or digest is accepted. The earlier
synthetic placeholder digest `b` repeated 64 times with size `2048` and the
prior 12540-byte/170-LF source identity with SHA-256
`724869c6767c1570075812832d57c94e8c9e17ae2d4cd1d9f8781b0796671d2f`
are superseded and must fail runtime-content
closure. This reviewed successor implements only the already-frozen channel
caps and postlaunch attestation. Protocol remains exactly
`auto-g16-v3-rtwin-bootstrap/1` because the AGV3 frame, seven closed schemas,
operation table, and trust semantics are unchanged; any change to those
protocol semantics still requires a reviewed protocol version. The source
reads one
request frame from stdin and writes one response frame to stdout. Both frames
are ASCII magic `AGV3`, one unsigned 64-bit big-endian length, then exactly that
many canonical JSON bytes containing one trailing LF, followed by EOF. The
length counts the JSON bytes including that LF, not the 12-byte header. Request
keys are exactly `binding`, `operation`, `payload`, and `protocol`; response
keys are exactly `operation`, `protocol`, `result`, and `status`. Protocol is
exactly `auto-g16-v3-rtwin-bootstrap/1`, response operation must echo the
request enum, and every accepted response has status exactly `ok`. The table's
`stdin_cap`/`stdout_cap` include the complete header and JSON bytes. There is
one frame, one stdout response channel, and no second binary or authority
channel. Bootstrap-process stderr is diagnostic-only, capped by the table, and
must be empty for an accepted authority response; inner qstat stderr is data
inside the response result. Diagnostics are never parsed as state, job, token,
retry, or scientific authority. Extra frames/bytes, unknown keys/enum/status,
noncanonical JSON, overflow, truncation, nonempty bootstrap stderr, or missing
EOF rejects.

The normative source-quoting fixture is the 12-byte ASCII source represented
as `alpha'\nbeta\n`, with SHA-256
`6053f05b9d4ccfee917933fbaf678ce477573102c2c6b62eaaa3d0290d8dcfb7`.
`quote_bootstrap_source` produces exactly the 18 bytes represented as
`'alpha'"'"'\nbeta\n'`, with SHA-256
`582f76adb6db7219ffaea960e5b01ee95939b0600c002c92d0601199369e9735`.
A POSIX `shlex`-equivalent grammar must decode that complete quoted word to
exactly one argv element whose bytes equal the 12-byte source; zero or two
elements, line-ending normalization, quote loss, or command separation
rejects. The production-source test performs the same one-element byte-exact
round trip for all 13904 source bytes. Replacing any variable token with a
value containing LF/CR/NUL rejects before launcher construction; replacing
the fixed source with CR/NUL also rejects, while LF is preserved.

Binary values use RFC 4648 standard base64 with required padding and canonical
decode/re-encode equality. Tokens decode to `1..4096` bytes. Content decoded
size and lowercase SHA-256 must equal the separately bound fields. Integers are
non-boolean; sizes are non-negative and `effect_sequence` is positive, while
`returncode` is a signed process integer. Every string obeys its frozen lexical
rule. The exact per-operation request schemas are:

| operation | exact `binding` keys | exact `payload` keys |
| --- | --- | --- |
| `ALLOCATE_WORKSPACE` | `transport_store_id`, `store_instance_id`, `runtime_attestation_id`, `attempt_id`, `execution_snapshot_id`, `submission_intent_id`, `remote_workspace` | none (`{}`) |
| `STAGE_EXACT_FILE` | all allocation binding keys plus `workspace_authority_id`, `workspace_physical_token_base64` | `artifact_kind`, `logical_name`, `remote_relative_name`, `sha256`, `size_bytes`, `content_base64` |
| `SUBMIT_QSUB_ONCE` | all stage binding keys plus `prepared_input_artifact_authority_id`, `prepared_input_artifact_physical_token_base64`, `pbs_template_artifact_authority_id`, `pbs_template_artifact_physical_token_base64` | `pbs_basename` |
| `QUERY_SCHEDULER` | all stage binding keys plus `job_authority_id`, `receipt_binding_id`, `remote_effect_receipt_id`, `job_id` | `job_id` |
| `STAT_EXACT_FILE` | all query binding keys | `remote_relative_name` |
| `FETCH_EXACT_FILE` | all query binding keys | `remote_relative_name`, `expected_size_bytes`, `expected_file_physical_token_base64` |
| `RECONCILE_SUBMISSION` | all qsub binding keys | `effect_sequence` |

“All ... keys plus” is exact set union, never optional inheritance. For stage,
`artifact_kind` is exactly `prepared-input` or `pbs-template`; the other fields
equal the current snapshot artifact, and decoded content equals its exact
prepared bytes. For qsub, the two artifact IDs/tokens are distinct, already
persisted under the same workspace, and correspond respectively to those two
kinds. Qstat payload `job_id` equals binding `job_id`. Stat/fetch use the one
exact portable request component. Fetch expected size/token equal the
immediately preceding same-binding stat result. Reconciliation binds the same
workspace and two staged artifacts as qsub and the exact positive receipt
sequence; it never takes a caller job ID.

Field types/cardinality are closed as follows. Every `*_id` is one non-empty
string copied exactly from the already identity-checked snapshot/store/receipt
row named by that field; it is never discovered or recomputed remotely.
`remote_workspace` is one absolute normalized POSIX path equal to the snapshot,
while each basename/logical/relative name is one non-empty portable component
under its existing grammar. Every `*_sha256` is one lowercase 64-hex string.
Every `*_size_bytes` is one non-negative non-boolean integer; stage sizes also
obey the snapshot's stricter prepared-artifact rule. `effect_sequence` is one
positive non-boolean integer. `returncode` is one signed non-boolean integer.
Every `*_base64` is one canonical string; content may decode to zero bytes only
where the bound artifact permits it, while each physical token decodes to
`1..4096` bytes. Every EOF member is the JSON boolean `true`. No field is null,
repeated, optional, defaulted, or accepted under an alias except the two
explicit conditional result schemas below.

The exact successful response result schemas are:

| operation | exact `result` keys and closed values |
| --- | --- |
| `ALLOCATE_WORKSPACE` | `remote_workspace`, `workspace_physical_token_base64`; workspace echoes the request and token is newly created by the trusted agent |
| `STAGE_EXACT_FILE` | `artifact_kind`, `logical_name`, `remote_relative_name`, `sha256`, `size_bytes`, `artifact_physical_token_base64`; semantic fields echo the request and token is the post-write reattested object |
| `SUBMIT_QSUB_ONCE` | `job_id`; one strict normalized PBS job ID |
| `QUERY_SCHEDULER` | `stdout_base64`, `stderr_base64`, `returncode`, `eof_stdout`, `eof_stderr`, `completion_status`; EOF values are exactly `true`, completion is exactly `completed`, and decoded streams remain within 262144/65536 bytes |
| `STAT_EXACT_FILE` | when present: `presence`, `remote_relative_name`, `size_bytes`, `file_physical_token_base64`, with presence `present`; when absent: only `presence`, `remote_relative_name`, with presence `absent` |
| `FETCH_EXACT_FILE` | `remote_relative_name`, `size_bytes`, `sha256`, `content_base64`, `file_physical_token_base64`, `eof`; name/size/token echo the request, token is unchanged after read, digest covers decoded bytes, and `eof` is exactly `true` |
| `RECONCILE_SUBMISSION` | `effect_state`, `job_id` for `confirmed_effect`; only `effect_state` for `confirmed_no_effect` or `possibly_effectful`; states are those exact strings and only confirmed effect carries one strict job ID |

A protocol/operation failure returns no accepted authority frame. In
particular, qsub timeout, lost response, malformed job ID, or any ambiguity is
handled by Execution as possibly effectful/`UNKNOWN`; it is never converted to
an alternate `ok` response or retried. Stat `absent` is a completed exact
observation, not a transport failure. Query's raw nonzero return code remains
data for the existing fixed classifier. Reconciliation does not turn
`confirmed_no_effect` into same-Attempt resubmission authority.

The maximum raw artifact is 134217728 bytes, so its canonical base64 is at most
178956972 bytes. For stage/fetch the header and all fixed non-content JSON are
bounded to at most 65536 bytes; their exact 179306496-byte outer cap therefore
contains the largest legal frame without truncation. Qstat's two inner stream
caps encode to at most 436912 base64 bytes and its 524288-byte outer cap covers
the complete framed result. Other schemas fit their displayed caps. A cap is
checked before allocation, while reading, and at EOF; no truncated response is
ever accepted.

The active identity fixture below supplies four normative canonical JSON
vectors, each shown as its one line; counted bytes include the final LF. The
allocate request is 420 bytes with SHA-256
`dd01886713ad2a41e45ae60ba85fd0a88fa42666d7a9db661c4a0ab2e748fe5e`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"55823409-18d5-5ec8-8cd1-95fc2070fcfa","store_instance_id":"28c10d1a-9f8f-5ce6-84d1-555175c0fcde","submission_intent_id":"intent-1","transport_store_id":"108c8d43-2ea9-5658-9607-ade4cbbeac85"},"operation":"ALLOCATE_WORKSPACE","payload":{},"protocol":"auto-g16-v3-rtwin-bootstrap/1"}
```

Its response is 202 bytes with SHA-256
`ae29cd3e8300a6b90441c431cef7a0d00786c9f5c676ea1a8be6bacdd95f660c`:

```json
{"operation":"ALLOCATE_WORKSPACE","protocol":"auto-g16-v3-rtwin-bootstrap/1","result":{"remote_workspace":"/srv/p/attempt-1","workspace_physical_token_base64":"d29ya3NwYWNlLXRva2VuLXYx"},"status":"ok"}
```

The fetch request is 844 bytes with SHA-256
`4e57b3c5b1a71fc8fdee3ac29c963cf94bcc30c8d64125420388fae9ba6a331b`:

```json
{"binding":{"attempt_id":"attempt-1","execution_snapshot_id":"snapshot-1","job_authority_id":"51eef369-a569-53e2-8c44-2d22e20057f7","job_id":"123.server","receipt_binding_id":"e824ab64-5fcf-5014-be1a-b53ad70f8cce","remote_effect_receipt_id":"receipt-1","remote_workspace":"/srv/p/attempt-1","runtime_attestation_id":"55823409-18d5-5ec8-8cd1-95fc2070fcfa","store_instance_id":"28c10d1a-9f8f-5ce6-84d1-555175c0fcde","submission_intent_id":"intent-1","transport_store_id":"108c8d43-2ea9-5658-9607-ade4cbbeac85","workspace_authority_id":"ceff0991-4089-5c97-90b5-199c00467e67","workspace_physical_token_base64":"d29ya3NwYWNlLXRva2VuLXYx"},"operation":"FETCH_EXACT_FILE","payload":{"expected_file_physical_token_base64":"YXJ0aWZhY3QtdG9rZW4tdjE=","expected_size_bytes":19,"remote_relative_name":"job.log"},"protocol":"auto-g16-v3-rtwin-bootstrap/1"}
```

Its response is 341 bytes with SHA-256
`300f841ea40e23c6d03f668b3a5fc9e2fcd2478a20321f870fbe3022a0804e35`:

```json
{"operation":"FETCH_EXACT_FILE","protocol":"auto-g16-v3-rtwin-bootstrap/1","result":{"content_base64":"Tm9ybWFsIHRlcm1pbmF0aW9uCg==","eof":true,"file_physical_token_base64":"YXJ0aWZhY3QtdG9rZW4tdjE=","remote_relative_name":"job.log","sha256":"d66fc1aad228af405f4e1d2e5faaf681bd9db338e6810f82ef5a74f9a685c618","size_bytes":19},"status":"ok"}
```

Tests replay all four vectors and reject a missing/extra binding, payload,
result, or top-level key; wrong echoed operation/protocol/status; an illegal
conditional result shape; noncanonical/badly padded base64; a boolean integer;
size/digest/token/EOF mismatch; extra/multiple stdout frames; authority data on
stderr; stdout/stderr/request cap overflow; missing EOF; and fetch bytes that
do not reproduce the exact original content. Thus variable artifact bytes are
closed data, never Python or shell source.

The fixed loader accepts no module name, import path, callback, executable,
argv, source, script, shell fragment, or generic `RUN`, `EXEC`, `SHELL`,
`PYTHON`, or `SCRIPT` operation. After deployment-trusted startup,
`server_python` may compare its own path/size/digest to the manifest to detect
drift and may open/stat/hash exact qsub/qstat paths before structured-argv
launch. None of those post-start checks proves the manifest, remote shell,
server OpenSSH service, OS, or deployment boundary.

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
  records/services, `GaussianJobParser`, ScientificValidation, Review APIs,
  public `resolve_server_profile`, and existing `runtime_contents` ->
  `runtime_identities` byte binding.
- **EXTRACT:** strict qstat present/absent/unknown classification, finite timeout
  and stable-read rules, append-only SQLite/schema-attestation patterns,
  descriptor-relative/no-follow exact-copy and file-identity checks,
  duplicate-key/canonical-JSON checks, fixed PowerShell/CRT/POSIX quoting
  encoders, and adjacent
  adversarial tests from the reviewed RTwin/direct implementations.
- **WRAP:** the existing `legacy_rtwin_pbs` RTwin/PBS running path behind
  `RTWinExecutionAdapter` and `RTWinReadAdapter`; its internal dictionaries and
  commands are not the new public ABI or authority.
- **REWRITE:** typed transport records, `TransportStore`, store-instance and
  physical-token binding, closed data-only remote protocol glue, exact
  profile-bound nine-root manifest validation, the fixed remote-shell/bootstrap
  command chain, exact snapshot/receipt wrappers, and Result-compatible capture
  mapping. Existing
  code mixes CLI parsing, dynamic command/source behavior, mutable dictionaries,
  legacy project-level state, and owner/capability governance, so directly
  porting it would preserve the wrong authority, trust model, and API.
- **DROP:** legacy owner/receipt/capability/hash-lineage authority, non-empty
  project as a v3 rule, qdel/cancellation, deletion/cleanup, implicit latest
  discovery, the superseded independent executable inventory/manifest input,
  bootstrap self-attestation, dynamic remote agent execution,
  parser/scientific policy, and automatic retry.
- **DEFER:** OpenSSH, process and Gaussian-phase acquisition, checkpoint fetch,
  native executable wrapper, rich telemetry/stall diagnosis, deployment,
  credentials, production smoke, and every live operation.

`V30-VAL-TRANSPORT-01` is integrated and owns `auto_g16/transport/**` and
`tests/v3/transport/**` through `affected / fail_closed=false`. The composition
contract grants no live authority.

## V30-TRANSPORT-BOOTSTRAP-CHAIN-03 Physical and Bootstrap Authority Closeout

This integrated section freezes the TransportStore, physical-binding, threat
model, and trust-chain semantics retained by resource-enactment `/2`. Its
protocol/table/source names and exact canonical runtime vectors describe the
historical `/1` integration only. For the executable successor, the `/2`
runtime inventory and attestation handling under
`Snapshot-derived PBS resource enactment` are authoritative; no SQLite schema
or public store API changes.

**Contract status: FROZEN CANDIDATE; IMPLEMENTATION NOT AUTHORIZED BY THIS
DOCUMENT.** This additive closeout preserves the physical-authority decisions
and resolves the bootstrap/deployment trust-chain findings without changing
Core, Execution, receipt, Approval, Workflow,
Observe, Result, ScientificValidation, or Review APIs/schemas. When this exact
authority content is present on authoritative main after independent review,
the task is `CLOSED / FROZEN / INTEGRATED` and the successor offline Transport
implementation is gate-eligible. `V30-VAL-TRANSPORT-01` is already integrated;
Transport product paths use `affected / fail_closed=false` validation.
Commits `798d3559d7c5ee6211a0b29977310f8adb871a5f`,
`e49136e23c564cc9e0d9d97b905e43c45db73adc`, and
`44db04180af8222c6e4619accfab0049e89bd3e0` remain immutable failed evidence.
The last lacked exact per-operation request/response schemas and a realizable
single fetch response channel; this successor closes that remaining bootstrap
protocol defect class.

### Public surface and ownership

The exact Transport export inventory above expands from eight symbols to nine
by adding `TransportStore`; the not-yet-integrated Transport
`ExactRemoteJobBinding` expands only by its two store identity fields. No
already-integrated upstream public record changes. The store's exact public
lifecycle is:

```text
TransportStore.create_new(
    path: str | os.PathLike[str],
    *,
    approved_root: str | os.PathLike[str],
) -> TransportStore
TransportStore.open_existing(
    path: str | os.PathLike[str],
    *,
    approved_root: str | os.PathLike[str],
) -> TransportStore
TransportStore.close() -> None
```

There is no public generic `put`, SQL, token, transaction, migration, delete,
or authority-query method. Package-private adapter methods append and replay
the exact rows below. `RTWinExecutionAdapter` and `RTWinReadAdapter` each
require one `transport_store: TransportStore` keyword argument and must share
the same durable database for one Attempt. An already-closed store, wrong store
schema/identity, or store swap fails before any driver call.

`TransportStore` is owned entirely by `auto_g16.transport`. It is independent
of the Core SQLite store and Execution `ReceiptJournal`; it adds no table,
migration, or method to either owner. It persists physical operation evidence
only. A valid row cannot claim Core `WINNER`, confirm an effect, authorize a
read, create a receipt, resolve `UNKNOWN`, retry, cancel, delete, or grant
scientific authority.

### Exact threat model

This closeout detects accidental or unprivileged copy, alias, replacement,
path/root drift, stale reopen, and cross-store evidence splicing. It provides
store-instance binding and clone/replacement detection within that model; it
does **not** claim cryptographic uncloneability or protection from a malicious
same-UID process, root/administrator, kernel/filesystem compromise, or a
compromised deployment/bootstrap trust root. Those actors can copy database
bytes, forge ordinary filesystem metadata, replace trusted executables, or
interfere after an OS path check. Such compromise is outside this offline
product boundary and requires host/deployment/security authority, not a hidden
Transport capability scheme.

Within the model, create-new obtains a non-caller-selectable 32-byte nonce from
the operating-system CSPRNG exactly once, persists it before returning the
store, and never regenerates it on reopen. Store instance evidence also closes
the physical database file identity, approved lexical store path/root, and the
ordered physical identity chain from approved root through the database parent.
This is the strongest supported local clone/replacement evidence, not a promise
against an excluded actor that can control the same UID or kernel.

### Exact SQLite schema-v1

The database uses `PRAGMA application_id = 1093879636` (`A3GT`),
`user_version = 1`,
`foreign_keys = ON`, `trusted_schema = OFF`, and `synchronous = FULL`.
Its application objects are exactly these six tables plus package-owned
BEFORE-UPDATE and BEFORE-DELETE abort triggers for every table:

```text
transport_meta(
  singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
  schema_identity BLOB NOT NULL,
  transport_store_id TEXT NOT NULL UNIQUE,
  store_instance_id TEXT NOT NULL UNIQUE,
  creation_nonce BLOB NOT NULL CHECK(length(creation_nonce) = 32),
  approved_store_root TEXT NOT NULL,
  approved_store_path TEXT NOT NULL,
  store_file_identity BLOB NOT NULL,
  parent_identity_chain BLOB NOT NULL
)

transport_runtime_attestation(
  runtime_attestation_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  resolved_server_profile_id TEXT NOT NULL,
  effective_config_sha256 TEXT NOT NULL,
  deployment_manifest_name TEXT NOT NULL,
  deployment_manifest_sha256 TEXT NOT NULL,
  deployment_manifest_size_bytes INTEGER NOT NULL,
  deployment_id TEXT NOT NULL,
  bootstrap_protocol TEXT NOT NULL,
  operation_table_sha256 TEXT NOT NULL,
  operation_table_size_bytes INTEGER NOT NULL,
  bootstrap_source_name TEXT NOT NULL,
  bootstrap_source_sha256 TEXT NOT NULL,
  bootstrap_source_size_bytes INTEGER NOT NULL,
  payload BLOB NOT NULL
)

transport_workspace_authority(
  workspace_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  remote_workspace TEXT NOT NULL,
  workspace_physical_token BLOB NOT NULL,
  payload BLOB NOT NULL,
  UNIQUE(attempt_id, execution_snapshot_id, submission_intent_id,
         remote_workspace)
)

transport_artifact_authority(
  artifact_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  workspace_authority_id TEXT NOT NULL
    REFERENCES transport_workspace_authority(workspace_authority_id),
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  artifact_kind TEXT NOT NULL,
  logical_name TEXT NOT NULL,
  remote_relative_name TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  artifact_physical_token BLOB NOT NULL,
  payload BLOB NOT NULL,
  UNIQUE(workspace_authority_id, artifact_kind, logical_name),
  UNIQUE(workspace_authority_id, remote_relative_name)
)

transport_job_authority(
  job_authority_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  workspace_authority_id TEXT NOT NULL UNIQUE
    REFERENCES transport_workspace_authority(workspace_authority_id),
  runtime_attestation_id TEXT NOT NULL
    REFERENCES transport_runtime_attestation(runtime_attestation_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  job_id TEXT NOT NULL,
  payload BLOB NOT NULL
)

transport_receipt_binding(
  receipt_binding_id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL CHECK(schema_version = 1),
  transport_store_id TEXT NOT NULL,
  store_instance_id TEXT NOT NULL,
  job_authority_id TEXT NOT NULL UNIQUE
    REFERENCES transport_job_authority(job_authority_id),
  workspace_authority_id TEXT NOT NULL
    REFERENCES transport_workspace_authority(workspace_authority_id),
  attempt_id TEXT NOT NULL,
  execution_snapshot_id TEXT NOT NULL,
  submission_intent_id TEXT NOT NULL,
  remote_effect_receipt_id TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL,
  payload BLOB NOT NULL
)
```

The exact append-only trigger names are
`transport_meta_no_update`, `transport_meta_no_delete`,
`transport_runtime_attestation_no_update`,
`transport_runtime_attestation_no_delete`,
`transport_workspace_authority_no_update`,
`transport_workspace_authority_no_delete`,
`transport_artifact_authority_no_update`,
`transport_artifact_authority_no_delete`,
`transport_job_authority_no_update`, `transport_job_authority_no_delete`,
`transport_receipt_binding_no_update`, and
`transport_receipt_binding_no_delete`; each executes `RAISE(ABORT, ...)` before
its named operation. `transport_meta` has exactly one `singleton = 1` row.
`schema_identity` binds the ordered SQL object inventory and schema-v1 DDL;
the remaining exact fields bind the logical store, one physical instance, its
one-time nonce, approved lexical root/path, file identity, and ordered parent
identity chain. Every evidence row repeats exact `transport_store_id` and
`store_instance_id`; a cross-store row rejects even if every other field and
payload byte is copied. Every foreign identity is
replayed in application code and by foreign keys where applicable. On every
open, the store attests application/user versions, the exact meta row, every
table/column/index/foreign-key/trigger definition, and rejects unexpected
application objects, missing append-only triggers, malformed rows, identity
drift, natural-key conflicts, or foreign-binding mismatch. Every adapter read
or append repeats schema/meta attestation inside one `BEGIN IMMEDIATE`
transaction before using rows; it never relies only on the constructor-time
check or an unlocked check-then-use interval.

Each runtime row requires manifest name exactly
`transport-deployment-manifest-v1.json`, bootstrap protocol exactly
`auto-g16-v3-rtwin-bootstrap/1`, and manifest digest/size/deployment ID exactly
from canonical bytes already closed against the current snapshot. Its operation
table and bootstrap-source identities equal the two other fixed runtime-content
entries. No row supplies or overrides manifest bytes; it only records the
already-validated deployment/profile identity for cross-profile replay checks.

The caller supplies both one path and its independently deployment-approved
local store root; the persisted root cannot approve itself on reopen. Transport
normalizes both to absolute lexical paths without `resolve()` or `realpath()`,
requires the path to be a strict descendant of that root, opens the approved
root descriptor, and walks the relative parent chain descriptor-relative and
no-follow. Every component must be an expected directory; symlink/reparse,
root escape, replacement, or chain mismatch rejects.
The ordered parent identities are captured from held descriptors. An existing
terminal symlink or non-regular file rejects. Create-new uses no-follow
`O_CREAT | O_EXCL`; reopen records the terminal file identity before SQLite
open and reattests the same lexical file and parent chain immediately after
open. No pathname fallback, overwrite, replacement, or migration is allowed.
The strongest practical pre/post SQLite transaction check reattests approved
root, parent chain, path, regular-file type, and file identity before and after
every transaction. Exact reopen remains durable and idempotent within the
threat model. This does not claim an atomic path/SQLite capability or eliminate
TOCTOU against an excluded malicious same-UID/root/kernel actor.

### Store identity and replay

Store identities reuse the frozen Transport namespace root
`6e54140f-f4e7-5482-a6c1-8f5729e3c112`, canonical tagged encoding, and
`uuid5(domain_namespace, canonical_bytes.decode("ascii"))`. New domain
namespaces are exactly:

```text
transport-store     -> 08b51475-e12f-5c8a-9c29-ac1a50c4778d
store-instance      -> 10b04ccd-414d-502e-a23b-8347087797fd
runtime-attestation -> 4fd2e62a-471b-5cdf-a41c-c73cd15df6be
workspace-physical  -> cf5d20c0-dcf7-5017-b550-a4b86d2e2315
artifact-physical   -> 1bb613c9-3d29-584e-a061-ba3bf03589b5
job-physical        -> d82d6457-637e-5262-8741-d721d2b5057f
receipt-binding     -> 26685dd2-091e-5476-9556-1b6416d6a200
```

`creation_nonce` is exactly 32 raw bytes. The canonical POSIX physical file
identity is `['posix-file', st_dev, st_ino, 'regular']`. Each canonical parent
entry is `[absolute_lexical_component_path, st_dev, st_ino, 'directory']`;
`parent_identity_chain` is the ordered non-empty array beginning with the
approved root and ending with the database's direct parent. Equivalent Windows
implementation uses `['windows-file', volume_serial_number,
file_id_128_hex, 'regular']` and parent entries with `directory`; reparse points
reject. One store uses exactly one platform form and cannot change form on
reopen.

The complete schema-v1 identity-name arrays are exactly:

```text
["auto-g16-transport/store", 1,
 approved_store_root, approved_store_path]

["auto-g16-transport/store-instance", 1,
 transport_store_id, creation_nonce, approved_store_root,
 approved_store_path, store_file_identity, parent_identity_chain]

["auto-g16-transport/runtime-attestation", 1,
 transport_store_id, store_instance_id,
 execution_snapshot_id, resolved_server_profile_id,
 effective_config_sha256, deployment_manifest_name,
 deployment_manifest_sha256, deployment_manifest_size_bytes,
 deployment_id, bootstrap_protocol, operation_table_sha256,
 operation_table_size_bytes, bootstrap_source_name, bootstrap_source_sha256,
 bootstrap_source_size_bytes]

["auto-g16-transport/workspace-physical", 1,
 transport_store_id, store_instance_id,
 runtime_attestation_id, attempt_id, execution_snapshot_id,
 submission_intent_id, remote_workspace, workspace_physical_token]

["auto-g16-transport/artifact-physical", 1,
 transport_store_id, store_instance_id,
 workspace_authority_id, runtime_attestation_id, attempt_id,
 execution_snapshot_id, submission_intent_id, artifact_kind, logical_name,
 remote_relative_name, sha256, size_bytes, artifact_physical_token]

["auto-g16-transport/job-physical", 1,
 transport_store_id, store_instance_id,
 workspace_authority_id, runtime_attestation_id, attempt_id,
 execution_snapshot_id, submission_intent_id, job_id]

["auto-g16-transport/receipt-binding", 1,
 transport_store_id, store_instance_id,
 job_authority_id, workspace_authority_id, attempt_id,
 execution_snapshot_id, submission_intent_id,
 remote_effect_receipt_id, job_id]
```

`transport_store_id` is the deterministic logical identity of one approved
root/path pair. `store_instance_id` is the identity of one creation at that
pair and binds the one-time nonce plus then-current physical file/parent chain.
A byte-for-byte database clone at another path, another file identity, or
another parent chain cannot satisfy both IDs within the threat model. Reopen at
the same approved path and physical identity preserves both IDs. Neither ID is
a secret or an unforgeable capability.

The normative store fixture uses approved root
`/var/lib/auto-g16/transport`, approved path
`/var/lib/auto-g16/transport/store.sqlite3`, nonce bytes
`000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f`,
file identity `['posix-file', 42, 9001, 'regular']`, and parent chain
`[['/var/lib/auto-g16/transport', 42, 8001, 'directory']]`. That nonce is a
deterministic test fixture only; production creation must use the OS CSPRNG.
The exact canonical bytes and UUIDs are:

```text
transport-store bytes:
a4:s24:auto-g16-transport/storei1;s27:/var/lib/auto-g16/transports41:/var/lib/auto-g16/transport/store.sqlite3
transport_store_id:
108c8d43-2ea9-5658-9607-ade4cbbeac85

store-instance bytes:
a8:s33:auto-g16-transport/store-instancei1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85y32:000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1fs27:/var/lib/auto-g16/transports41:/var/lib/auto-g16/transport/store.sqlite3a4:s10:posix-filei42;i9001;s7:regulara1:a4:s27:/var/lib/auto-g16/transporti42;i8001;s9:directory
store_instance_id:
28c10d1a-9f8f-5ce6-84d1-555175c0fcde
```

The following superseded identity-codec fixture is retained only as readable
negative evidence from failed candidate `e49136e23c564cc9e0d9d97b905e43c45db73adc`.
It uses `snapshot-1`, `profile-1`,
`attempt-1`, `intent-1`, remote workspace `/srv/p/attempt-1`, job
`123.server`, receipt `receipt-1`, workspace token `workspace-token-v1`, and
prepared-input token `artifact-token-v1`. Its fixed nested raw-byte executable
payload preserves the earlier codec vector with digest
`4e31987b253d5d9edb353074f91ad39c0544f5f18ec8571da45af457faa85451`.
It is not current authority or deployment-manifest evidence; the semantic
manifest validator must reject that abbreviated four-field payload and its
dependent IDs. The superseded bytes were:

```text
superseded runtime-attestation bytes:
a13:s38:auto-g16-transport/runtime-attestationi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes10:snapshot-1s9:profile-1s64:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaas64:3502638017454526cdbfee01de47a543a9870c9c57697e4373732cb7909a71d1i1040;s64:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbi2048;y889:61333a7334303a6175746f2d6731362d7472616e73706f72742f65786563757461626c652d6964656e74697469657369313b61383a61343a73373a6d61632d7373687331303a2f782f6d61632d7373687336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369313b61343a73373a6d61632d7363707331303a2f782f6d61632d7363707336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369323b61343a73393a727477696e2d7373687331323a2f782f727477696e2d7373687336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369333b61343a73393a727477696e2d7363707331323a2f782f727477696e2d7363707336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369343b61343a7331323a727477696e2d6272696467657331353a2f782f727477696e2d6272696467657336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369353b61343a7331333a7365727665722d707974686f6e7331363a2f782f7365727665722d707974686f6e7336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369363b61343a7331313a7365727665722d717375627331343a2f782f7365727665722d717375627336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369373b61343a7331323a7365727665722d71737461747331353a2f782f7365727665722d71737461747336343a6363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636363636369383bs64:4e31987b253d5d9edb353074f91ad39c0544f5f18ec8571da45af457faa85451
superseded runtime_attestation_id:
d497b2fa-c567-5c44-bb49-1ec01586d4cd

superseded workspace-physical bytes:
a10:s37:auto-g16-transport/workspace-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s16:/srv/p/attempt-1y18:776f726b73706163652d746f6b656e2d7631
superseded workspace_authority_id:
8bc410b7-b0ed-5050-bc53-b75126610f45

superseded artifact-physical bytes:
a15:s36:auto-g16-transport/artifact-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:8bc410b7-b0ed-5050-bc53-b75126610f45s36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s14:prepared-inputs7:job.gjfs7:job.gjfs64:ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddi123;y17:61727469666163742d746f6b656e2d7631
superseded artifact_authority_id:
c140b8e0-93e2-566d-b1c6-d0e6b0d86522

superseded job-physical bytes:
a10:s31:auto-g16-transport/job-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:8bc410b7-b0ed-5050-bc53-b75126610f45s36:d497b2fa-c567-5c44-bb49-1ec01586d4cds9:attempt-1s10:snapshot-1s8:intent-1s10:123.server
superseded job_authority_id:
12ae30ec-eaa5-516f-9967-4a4987b86f9d

superseded receipt-binding bytes:
a11:s34:auto-g16-transport/receipt-bindingi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:12ae30ec-eaa5-516f-9967-4a4987b86f9ds36:8bc410b7-b0ed-5050-bc53-b75126610f45s9:attempt-1s10:snapshot-1s8:intent-1s9:receipt-1s10:123.server
superseded receipt_binding_id:
3e51a223-b74b-5f9a-946d-3c4e0b419a39
```

The active complete-manifest fixture uses the normative manifest identity
above, operation-table digest/size above, bootstrap-source name
`auto-g16-v3-rtwin-bootstrap-v1.py`, the exact source digest
`056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952`
and size `13904`, effective-config digest `a` repeated 64 times, and the same
remaining literal inputs. Its exact current canonical vectors are:

```text
runtime-attestation bytes:
a17:s38:auto-g16-transport/runtime-attestationi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes10:snapshot-1s9:profile-1s64:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaas37:transport-deployment-manifest-v1.jsons64:70be894f90c8fd42f417b517ba426db80cba436062c044e834079cb7d340983ai2753;s29:synthetic-rtwin-deployment-v1s29:auto-g16-v3-rtwin-bootstrap/1s64:6b9c1f8574bb3541a884ca1532aae0d12a54d52cb158c8f8a9521f2421dc4cc6i1490;s33:auto-g16-v3-rtwin-bootstrap-v1.pys64:056e27cab0a00e305c5e5acc7f5673e7d196dd0dc27516c31ec2cb95d6b58952i13904;
runtime_attestation_id:
55823409-18d5-5ec8-8cd1-95fc2070fcfa

workspace-physical bytes:
a10:s37:auto-g16-transport/workspace-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s16:/srv/p/attempt-1y18:776f726b73706163652d746f6b656e2d7631
workspace_authority_id:
ceff0991-4089-5c97-90b5-199c00467e67

artifact-physical bytes:
a15:s36:auto-g16-transport/artifact-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:ceff0991-4089-5c97-90b5-199c00467e67s36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s14:prepared-inputs7:job.gjfs7:job.gjfs64:ddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddi123;y17:61727469666163742d746f6b656e2d7631
artifact_authority_id:
5ed7b28e-72ab-55b7-8c66-37f2d5ecab11

job-physical bytes:
a10:s31:auto-g16-transport/job-physicali1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:ceff0991-4089-5c97-90b5-199c00467e67s36:55823409-18d5-5ec8-8cd1-95fc2070fcfas9:attempt-1s10:snapshot-1s8:intent-1s10:123.server
job_authority_id:
51eef369-a569-53e2-8c44-2d22e20057f7

receipt-binding bytes:
a11:s34:auto-g16-transport/receipt-bindingi1;s36:108c8d43-2ea9-5658-9607-ade4cbbeac85s36:28c10d1a-9f8f-5ce6-84d1-555175c0fcdes36:51eef369-a569-53e2-8c44-2d22e20057f7s36:ceff0991-4089-5c97-90b5-199c00467e67s9:attempt-1s10:snapshot-1s8:intent-1s9:receipt-1s10:123.server
receipt_binding_id:
e824ab64-5fcf-5014-be1a-b53ad70f8cce
```

The `payload` column is the exact canonical encoding of the corresponding
array. Physical tokens are immutable raw bytes, length `1..4096`; Transport
does not parse, synthesize, shorten, or treat them as secrets. The trusted
remote agent alone creates and reattests them. Same identity plus byte-identical
payload is an idempotent replay. Same identity/different payload, a different
identity for one natural binding, a duplicate job for one workspace, or a
receipt/job mismatch is a `TransportBoundaryError` and leaves the database
unchanged. Append uses one immediate transaction; zero-row or multi-row
trigger interference, suppressed insert, mutation, or post-insert mismatch
fails closed. Failure after a possibly effectful remote operation remains
possibly effectful/`UNKNOWN`; it never causes automatic replay of that
operation.

The runtime row repeats the exact manifest name, byte identity, deployment ID,
bootstrap protocol, operation-table identity, and fixed bootstrap-source
identity from the current resolved profile/snapshot. It stores no second
manifest projection and no independently caller-supplied executable inventory.
Every workspace/artifact/job/receipt row links that runtime row, preventing
cross-profile or cross-deployment replay while keeping deployment trust and
physical-object evidence separate.

`transport_artifact_authority` stores only the two effect-side staged artifacts.
Its `artifact_kind` is exactly `prepared-input` or `pbs-template`; its logical
and remote-relative names, digest, and size must equal the corresponding exact
`ExecutionSnapshot` prepared-artifact binding. Generated Gaussian output is
not inserted into this table because output may grow across legal captures.

The effect adapter appends runtime attestation before the operation, workspace
authority immediately after fresh allocation, artifact authority immediately
after each exact staged write, and job authority after strict qsub extraction
or confirmed same-Attempt reconciliation. Once the public ReceiptJournal has
durably appended the matching confirmed receipt,
`ExactRemoteJobBinding.from_persisted_receipt(...)` appends/replays the exact
receipt-binding row before returning. This split preserves the unchanged
ExecutionPort and receipt APIs while making process restart safe.

### Replacement-safe remote physical authority

The installed remote agent begins from the approved root descriptor. Fresh
allocation walks and creates every Attempt-workspace component descriptor-
relative and no-follow, then returns the opaque workspace token only after the
new final directory is reattested. Existing targets, symlink/reparse points,
replacement, escape, or inability to obtain a stable token fail closed.

Every later stage, qsub, qstat, reconciliation, and fetch request carries the
exact persisted workspace token in the package-controlled physical-binding
envelope `auto-g16-rtwin-physical-binding/1`. The agent reopens from the root,
walks no-follow, compares the complete physical token, and performs the
operation relative to the still-held final descriptor. There is no
`resolve/check -> pathname mutation` fallback. Process restart is irrelevant:
the token is loaded from `TransportStore`, not an in-memory allocation set.

After a stage write, the agent returns an artifact token only after fresh
no-follow create, exact-byte digest/size verification, fsync as supported, and
descriptor reattestation. Qsub requires the exact two persisted staged
artifacts and reattests their tokens from the held workspace descriptor before
invocation. Fetch requires the persisted workspace token; for generated output
the agent creates one operation-local read token from bounded before/read/after
descriptor evidence and returns it with the exact bytes for adapter validation.
That evolving output token is not inserted into the staged-artifact table.
Cross-workspace, cross-Attempt, cross-snapshot, stale, replaced, or unpersisted
workspace/staged tokens reject before effect/read.

The physical-binding envelope is typed fixed data, not argv, a capability, or
an authority shortcut. The exact seven-operation table v1 tokens, argv
templates, limits, and digest are frozen above. A token never authorizes a new Attempt,
retry, qdel, delete, cleanup, profile change, or scientific conclusion.

### Bootstrap trust and fixed command construction

The exact manifest-bound `server_python` root is preinstalled and trusted by
deployment before it starts. It neither proves the manifest nor establishes its
own pre-start integrity. The configured RTwin and server remote shells likewise
start as explicit deployment roots. Their exact role, nine-root inventory, and
grammar-specific launchers are frozen in “Canonical deployment manifest” and
“Fixed bootstrap and remote-shell grammars” above; no universal pre-bootstrap
file verifier is claimed.

After start, the exact fixed bootstrap source accepts the seven operation enums,
physical-binding envelope, and bounded framed data only. No caller source,
module, bytecode, callback, command, shell fragment, executable, or operation is
uploaded or selected. The server process may detect drift in its own manifest
entry and attest exact qsub/qstat before absolute-path structured-argv launch;
RTwin executable checks remain owned by the deployment-trusted declared RTwin
shell. Missing/drifted evidence rejects with zero next operation. This grants
neither credential nor host-key authority; secrets remain out-of-band.

Controller Mac executables and post-bootstrap server executables use strict
prelaunch and practical postlaunch reattestation. Prelaunch drift causes zero
process call. Postlaunch drift makes evidence unusable and, if an effect may
have crossed, preserves `UNKNOWN` with no retry. This is replacement detection
inside the stated model, not a TOCTOU guarantee against excluded actors.
Descriptor execution and a native wrapper are neither required nor authorized.

The controller launches Mac OpenSSH by structured argv with local
`shell=False`; that does not remove either remote shell. Whenever Windows
`CreateProcess` serialization is required inside the frozen PowerShell
launcher, its parser contract is the Microsoft CRT/`CommandLineToArgvW`
backslash-and-double-quote grammar. The exact encoder leaves a nonempty
argument containing no space, tab, or `"` unchanged; otherwise it surrounds the
argument with `"`, doubles every run of backslashes immediately before a
literal `"`, prefixes that quote with one additional backslash, doubles
trailing backslashes before the closing `"`, and encodes an empty argument as
`""`. NUL is rejected. Tests round-trip every fixed nested SSH token. The
manifest-selected PowerShell/cmd and server POSIX shell grammars are the only
remote-shell interpretation and are never auto-detected or bypassed.

If the RTwin-to-server POSIX hop unavoidably accepts one command string,
Transport constructs it solely from the exact launcher tuple with the two
class-specific encoders frozen above. For every variable launcher token:

```text
quote_variable(token) = "'" + token.replace("'", "'\"'\"'") + "'"
```

Variable tokens containing NUL, CR, or LF reject and empty tokens encode as
`''`. Only the exact digest/size-closed protocol source uses
`quote_bootstrap_source`, which rejects NUL/CR but preserves LF and literal
single quotes as one word. The caller can supply no command token, source, or
shell fragment. Where an argv/subsystem form exists it is preferred and no
command string is built. All stdin/stdout/stderr/control channels are
separately bounded, require process completion and EOF, and reject overflow,
truncation, extra bytes, timeout, or unstable completion. No retry follows any
uncertain result.

### Frozen adversarial implementation matrix

Implementation must prove: create/reopen store; terminal-symlink and
replacement rejection; exact schema/object/trigger attestation; durable replay;
same-ID conflict; natural-binding conflict; trigger suppression/mutation;
workspace allocation replacement; component symlink/escape; process restart
between allocate/stage/qsub/read; stale or forged workspace token; both staged
artifact tokens; artifact replacement before qsub; job/receipt exact binding;
cross-store and cross-Attempt/snapshot/intent/workspace/job splicing; dynamic
caller source/module/command spies zero; every canonical manifest negative;
profile/snapshot/runtime-content mismatch; fixed bootstrap source/operation
table/frame drift; PowerShell file/hash/launcher drift; cmd incompatibility with
zero fallback; server shell/Python/qsub/qstat drift; digest-to-exec replacement;
PowerShell/CRT/cmd/POSIX quote vectors including empty, spaces, apostrophe,
metacharacters, and NUL/CR/LF rejection; bounded-channel overflow/EOF/timeout;
qsub at most
once; post-WINNER ambiguity to `UNKNOWN`; restart without automatic retry;
exact qstat/fetch after reopen; generated-output read-token stability; and zero
qdel/delete/cleanup/live calls.

The five already-reviewed product blobs outside the eventual narrow repair
delta remain byte-identical unless an independently reviewed implementation
finding proves a change uniquely required by this contract. OpenSSH, process
and Gaussian-phase acquisition, deployment, credentials, qdel, deletion,
cleanup, automatic retry, and every live operation remain deferred.

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

## V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01

### Exact profile-bound configuration inventory

The RTwin live-capable driver must enact the same SSH configuration bytes that
the existing public Execution resolver freezes into the snapshot. The private
Transport convention uses these exact names:

| Hop | `platform_paths` config key | `config_files` config name | `platform_paths` known-hosts key | `config_files` known-hosts name |
| --- | --- | --- | --- | --- |
| Mac to RTwin | `mac_ssh_config_path` | `mac-ssh-config` | `mac_known_hosts_path` | `mac-known-hosts` |
| RTwin to server | `rtwin_ssh_config_path` | `rtwin-ssh-config` | `rtwin_known_hosts_path` | `rtwin-known-hosts` |

All four path keys are mandatory for a Transport operation. Its complete
`config_files` logical-name set is exactly the four names in the table, with
one occurrence each; no fifth unrelated or legacy name is accepted by
Transport. This exact-set rule does not narrow the generic Execution resolver.
No alias, fallback lookup, ambient config, or independently supplied byte/path
input exists. Mac paths are canonical absolute POSIX paths;
RTwin paths are canonical absolute Windows paths. Config and known-host bytes
remain non-secret profile content. Dedicated private-key paths may appear only
inside the configs; private-key bytes and digests are neither read nor bound.
The four effect paths and both config `IdentityFile` values reject `%`, `$`,
`~`, `*`, `?`, `[`, `]`, `{`, and `}`. Therefore OpenSSH token,
environment-variable, home, or glob expansion cannot select a different file
than the exact literal path that Transport attests. A Windows backslash is a
literal path separator, never escape syntax.

### Closed SSH config grammar

The source-reviewed grammar is deliberately narrower than OpenSSH. Config
bytes decode as strict UTF-8 without BOM, contain no NUL, CR, or HTAB, and end
in exactly one LF; therefore the final split line is empty. A non-final empty
line is blank. A comment line starts with `#` in column one. Every other
physical line matches exactly `^ *[A-Za-z][A-Za-z0-9]* [^ ]+$`: zero or more
leading ASCII SP, one directive, exactly one separating SP, one nonempty value,
and no trailing SP. Quote, backslash, inline comment, escape, and continuation
syntax do not exist. Directive spelling and the literal value `yes` are
case-sensitive and exactly as shown below.

The first semantic line is exactly `Host A`, where alias `A` matches
`[A-Za-z0-9][A-Za-z0-9._-]*`; it is the only `Host` line and contains one
alias. After it, exactly one each of `HostName`, `User`, `IdentityFile`, `IdentitiesOnly`,
`StrictHostKeyChecking`, and `UserKnownHostsFile` is required; `Port` occurs
zero or one time. No other directive is legal.

`IdentitiesOnly` and `StrictHostKeyChecking` equal `yes`; `IdentityFile` is one
dedicated absolute path for that platform; `UserKnownHostsFile` equals the
corresponding bound path; and an omitted port resolves to 22. The Mac alias
must reproduce the sole resolved RTwin hop. The RTwin alias must reproduce the
resolved server destination. This excludes `Include`, `Match`/`exec`,
`ProxyCommand`, `ProxyJump`, command hooks, every forwarding directive,
known-host commands, providers, agent overrides, and any config that redirects
host, user, or port. An additional proxy hop has no first-live authority.

### Exact command and attestation seam

The outer structured argv begins with exact manifest `mac_ssh`, then exact
`-F mac_ssh_config_path`. The inner manifest-bound PowerShell launch invokes
exact `rtwin_ssh` with exact `-F rtwin_ssh_config_path`. Both commands
explicitly set `BatchMode=yes`, `IdentitiesOnly=yes`,
`StrictHostKeyChecking=yes`, `IdentityAgent=none`,
`PreferredAuthentications=publickey`, `PubkeyAuthentication=yes`,
`PasswordAuthentication=no`, and `KbdInteractiveAuthentication=no`. Both set
`GSSAPIAuthentication=no`, `HostbasedAuthentication=no`,
`VerifyHostKeyDNS=no`, and `UpdateHostKeys=no`. Both set
`UserKnownHostsFile` and `GlobalKnownHostsFile` to the same hop-specific bound
known-hosts path, closing additional ambient host-key sources. The destination
token is the exact validated Host alias; explicit port/user values equal the
resolved profile. Local argv remains structured with `shell=False`; no caller
option, config path, target, shell fragment, or credential enters it.

For exact values `MC`, `MK`, `MA`, `MP`, `MU`, and generated PowerShell script
`PS`, the complete ordered outer argv is:

```text
(mac_ssh,
 "-F", MC,
 "-o", "BatchMode=yes",
 "-o", "IdentitiesOnly=yes",
 "-o", "StrictHostKeyChecking=yes",
 "-o", "UserKnownHostsFile=" + MK,
 "-o", "GlobalKnownHostsFile=" + MK,
 "-o", "IdentityAgent=none",
 "-o", "PreferredAuthentications=publickey",
 "-o", "PubkeyAuthentication=yes",
 "-o", "PasswordAuthentication=no",
 "-o", "KbdInteractiveAuthentication=no",
 "-o", "GSSAPIAuthentication=no",
 "-o", "HostbasedAuthentication=no",
 "-o", "VerifyHostKeyDNS=no",
 "-o", "UpdateHostKeys=no",
 "-p", canonical_decimal(MP),
 "-l", MU,
 "--", MA, PS)
```

For exact values `RC`, `RK`, `RA`, `RP`, `RU`, and exact bootstrap command
`BC`, the ordered RTwin child argv encoded by the frozen CRT/PowerShell
launcher is:

```text
(rtwin_ssh,
 "-F", RC,
 "-o", "BatchMode=yes",
 "-o", "IdentitiesOnly=yes",
 "-o", "StrictHostKeyChecking=yes",
 "-o", "UserKnownHostsFile=" + RK,
 "-o", "GlobalKnownHostsFile=" + RK,
 "-o", "IdentityAgent=none",
 "-o", "PreferredAuthentications=publickey",
 "-o", "PubkeyAuthentication=yes",
 "-o", "PasswordAuthentication=no",
 "-o", "KbdInteractiveAuthentication=no",
 "-o", "GSSAPIAuthentication=no",
 "-o", "HostbasedAuthentication=no",
 "-o", "VerifyHostKeyDNS=no",
 "-o", "UpdateHostKeys=no",
 "-p", canonical_decimal(RP),
 "-l", RU,
 "--", RA, BC)
```

For a synthetic RTwin config path `C:\cfg\server`, known-host path
`C:\cfg\server-known`, alias `server-a`, port `22`, user `server-user`, and
bootstrap command `BOOTSTRAP`, the complete child token tuple after the exact
`rtwin_ssh` executable is:

```text
"-F","C:\cfg\server","-o","BatchMode=yes","-o","IdentitiesOnly=yes",
"-o","StrictHostKeyChecking=yes",
"-o","UserKnownHostsFile=C:\cfg\server-known",
"-o","GlobalKnownHostsFile=C:\cfg\server-known",
"-o","IdentityAgent=none","-o","PreferredAuthentications=publickey",
"-o","PubkeyAuthentication=yes","-o","PasswordAuthentication=no",
"-o","KbdInteractiveAuthentication=no","-o","GSSAPIAuthentication=no",
"-o","HostbasedAuthentication=no","-o","VerifyHostKeyDNS=no",
"-o","UpdateHostKeys=no","-p","22","-l","server-user","--",
"server-a","BOOTSTRAP"
```

The exact PowerShell `Arguments` value is the single-SP join of
`crt_quote_v1(token)` for that ordered tuple. The existing frozen CRT quoting
grammar is reused; no other joiner, combined option, or destination placement
is conforming.

`canonical_decimal` is ASCII base-10 with no sign or leading zero. For a
synthetic Mac config path `/cfg/mac`, known-host path `/cfg/mac-known`, alias
`rtwin-a`, port `22`, and user `rtwin-user`, the outer tokens from `-F` through
the destination are exactly:

```text
"-F","/cfg/mac","-o","BatchMode=yes","-o","IdentitiesOnly=yes",
"-o","StrictHostKeyChecking=yes","-o","UserKnownHostsFile=/cfg/mac-known",
"-o","GlobalKnownHostsFile=/cfg/mac-known","-o","IdentityAgent=none",
"-o","PreferredAuthentications=publickey","-o","PubkeyAuthentication=yes",
"-o","PasswordAuthentication=no","-o","KbdInteractiveAuthentication=no",
"-o","GSSAPIAuthentication=no","-o","HostbasedAuthentication=no",
"-o","VerifyHostKeyDNS=no","-o","UpdateHostKeys=no",
"-p","22","-l","rtwin-user","--","rtwin-a"
```

For every platform path and both config `IdentityFile` values, any `%`, `$`,
`~`, `*`, `?`, bracket, or brace character rejects before command
construction. Negative fixtures include `/cfg/%h`, `/cfg/${HOME}`,
`~/.ssh/id`, `C:\cfg\%h`, and `C:\cfg\${HOME}`.

The private deployment authority produced by
`_resolve_deployment_authority(snapshot, current_profile)` carries only parsed
mechanical config evidence after public profile/snapshot equality succeeds.
Before local process creation, controller-file attestation opens the exact Mac
config and known-host files no-follow, requires regular-file identity, and
compares exact size and SHA-256 with `config_files`. A prelaunch failure creates
zero subprocess. After process completion it reopens and requires the same
descriptor/name identity and bytes; postlaunch drift rejects the child result
and, if an effect may have crossed, preserves `UNKNOWN` with no retry. The
PowerShell launcher requires non-directory, non-reparse exact size/SHA-256 for
RTwin config and known-hosts immediately before nested SSH and after the nested
process terminates. A prelaunch RTwin mismatch creates zero nested SSH. A
postlaunch RTwin drift makes the result unusable and preserves `UNKNOWN` where
applicable. No mismatch retries or switches files.

These four files do not change the exact nine-root deployment manifest. They
close effect configuration through the already identity-bound ServerProfile.
The pre-repair resolved profile is unusable for live authority. Integration
requires a new profile revision/resolution before Phase 7 of the live packet
may pass, and no Attempt may be created under the stale identity. This contract
changes no public Core, Approval, Workflow, Execution, Observe, Result,
ScientificValidation, or Review API/schema and authorizes no live effect.

## V30-TRANSPORT-RTWIN-LAUNCHER-CHAIN-02 current live-launch contract

Historical `transport-deployment-manifest-v1.json` remains a nine-root record
and is rejected by the repaired live seam. Current live-capable profiles use
exact runtime logical name `transport-deployment-manifest-v2.json`, schema
`auto-g16-v3-transport-deployment-manifest/2`, bootstrap protocol
`auto-g16-v3-rtwin-bootstrap/2`, and exactly these ten roots:

```text
mac_ssh mac_scp rtwin_ssh rtwin_scp rtwin_remote_shell rtwin_launcher
server_remote_shell server_python server_qsub server_qstat
```

The other eight historical roots retain their frozen roles. Manifest v2
intentionally reclassifies `rtwin_remote_shell`: it no longer claims to be the
Windows OpenSSH command boundary and instead binds the exact explicit
PowerShell child below CMD. `rtwin_launcher` is a Windows absolute-path
`rtwin-shell-file-v1` root with exact positive byte size,
lowercase SHA-256, null shell grammar, regular-file requirement, and
non-reparse requirement. Its fixed source identity is
`auto-g16-v3-rtwin-launcher-v1.ps1`, 7684 bytes, 125 LF, zero CR/NUL, SHA-256
`2eb539d4510988f892b52beeb743e088a27853cdfd9dc60ef0890978e0863444`.

Windows OpenSSH's actual boundary is CMD. `rtwin_remote_shell` binds the exact
explicit system PowerShell child and uses the sole closed grammar
`cmd-powershell-launcher-v1`; CMD is boundary grammar, not an eleventh trust
root. The complete remote command is exact PowerShell path, `-NoProfile`,
`-NonInteractive`, `-Command`, and one fixed loader string. It is shorter than
4096 characters and contains neither bootstrap source nor deployment-manifest
bytes. Injected values are exact current-authority paths, decimal sizes,
lowercase digests, and closed alias/port/user values only; CMD expansion and
metacharacter forms reject.

Manifest v2 is canonical JSON with exactly the four top-level keys
`bootstrap_protocol`, `deployment_id`, `schema`, and `trust_roots`. Every root
has exactly `attestation_mode`, `deployment_identity`, `expected_sha256`,
`expected_size_bytes`, `path`, `platform`, and `shell_grammar`; the existing
required/null rules apply, and no extension key is legal. The short loader is
the exact 1021-byte ASCII placeholder template with SHA-256
`e9417a66f6597791c519c403dd709a9bd791d516e3c421a1eb79cb6dc9fd0a47`.
Every named placeholder occurs once and is replaced once in sorted placeholder
name order. Paths/aliases/users use the frozen PowerShell single-quote grammar,
positive sizes/ports/lengths use unsigned canonical decimal, and digests use
lowercase 64-hex. The exact prefix/order is PowerShell path, `-NoProfile`,
`-NonInteractive`, `-Command`, then one double-quoted rendered template. No
alternate quoting, field order, omitted field, extra field, or caller fragment
is conforming.

The loader reads the literal launcher path, rejects container/reparse or
size/digest drift, strict-decodes the verified bytes as UTF-8, creates one
ScriptBlock from exactly those bytes, and invokes that in-memory block. Outer
stdin is not loader source: it remains exactly one byte-identical AGV3 request
frame from controller through outer SSH, launcher, nested SSH, and bootstrap.

The bootstrap and manifest are RTwin runtime data, not roots. Their only byte
authority is current `ServerProfile.runtime_contents`; their exact paths are
`platform_paths["rtwin_bootstrap_source_path"]` and
`platform_paths["rtwin_deployment_manifest_path"]`. Resolution requires two
distinct canonical Windows absolute paths, exact snapshot runtime identities,
and no latest, fallback, alias, or discovery. Launcher pre/post attestation
requires exact literal path, regular/non-reparse, size, and SHA-256.

The launcher has no generic operation surface. It may only attest the exact
RTwin SSH/SCP roots and bound RTwin config/known-hosts/runtime files, construct
the frozen nested SSH tokens, start manifest `rtwin_ssh` with
`System.Diagnostics.Process` and `UseShellExecute = false`, forward binary
stdin and output streams whose caps are enforced during each read, terminate
the child on overflow, reattest, and return the nested result. The
complete CRT-rendered inner argument line is strictly shorter than 30000
characters and is never routed through `cmd.exe`. Its exact character length
and UTF-8 SHA-256 are independently rendered by the controller and verified by
the launcher before Process creation.

The successor fixed bootstrap is logical name
`auto-g16-v3-rtwin-bootstrap-v2-py36.py`, 15562 bytes, 203 LF, zero CR/NUL,
SHA-256
`ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`.
It has no `from __future__ import annotations`; complete source must parse for
Python 3.6 and compile/start under exact manifest-bound CPython 3.6.8 without a
workspace operation. Protocol/table `/2` and all seven operation semantics are
unchanged.

After normal integration, deployment may no-overwrite publish exactly three
identity-qualified RTwin files: launcher, bootstrap runtime data, and manifest
runtime data. Existing unexpected targets stop; no overwrite, cleanup, or
delete is permitted. Read-only qualification then proves actual
CMD-to-PowerShell parsing, verified launcher invocation, runtime attestation,
nested SSH startup, exact server Python 3.6.8, compile/start prerequisites, and
binary forwarding without `ALLOCATE_WORKSPACE`, staging, qsub, or Gaussian.
Only a new ServerProfile revision 3 and new operational authorities may be used
by a later separately approved recovery Attempt.

## V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01 boundary

The revision-3 launcher and manifest are immutable deployed history. The
successor launcher is the version-qualified
`auto-g16-v3-rtwin-launcher-v2.ps1`, 8576 bytes, 140 LF, zero CR/NUL, SHA-256
`1e6a82100cdcdffc258a0c29ab4d76d3d385b72565f5030806b19e3ea22f2d48`.
Its manifest remains
schema `auto-g16-v3-transport-deployment-manifest/2`, protocol
`auto-g16-v3-rtwin-bootstrap/2`, and exactly the existing ten trust roots. A
new canonical manifest content identity changes only the `rtwin_launcher`
path, deployment identity, size, and digest required by the successor.

The ordinary PowerShell `Quote-Posix` function remains the sole renderer for
dynamic tokens and rejects NUL, CR, and LF. One separate
`Quote-PosixFixedBootstrap` function may receive only `$Bootstrap` produced by
this closed sequence:

1. read the literal current-profile bootstrap path as bytes;
2. require regular/non-reparse identity, exactly 15562 bytes, and SHA-256
   `ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`;
3. decode those exact bytes with strict UTF-8;
4. encode the decoded value with the same strict UTF-8 instance and require
   byte-for-byte equality with the attested input;
5. reject NUL or CR, permit literal LF, and replace every single quote with the
   POSIX single-quote boundary sequence;
6. surround the result with one single-quoted boundary and use it exactly once
   as the Python `-c` word.

Arbitrary caller text, another runtime content, or a value that has not passed
that exact identity gate cannot enter the fixed-bootstrap function. Dollar,
backtick, semicolon, pipe, glob, substitution, and literal LF characters inside
the attested value remain data inside the one shell word. They never become a
second command, word, expansion, or quoting policy.

The nested command remains exactly server Python, `-I`, `-S`, `-B`, `-c`, the
one fixed multiline bootstrap word, and the canonical base64 manifest word.
The controller's existing Python renderer and the PowerShell launcher must
produce the same exact CRT argument-line character length and UTF-8 SHA-256;
the existing strict 30000-character bound is unchanged. AGV3 framing, seven
operations, response semantics, binary stdin forwarding, caps, and pre/post
attestation are unchanged, so protocol/table `/2` do not advance.

Revision 4 is a new immutable ServerProfile revision. It binds the successor
launcher path and successor manifest-v2 path while reusing the exact revision-3
bootstrap path/bytes, SSH config, known-hosts, server Python, qsub, qstat, and
resource descriptor. It resolves a new profile ID/effective digest. Revision 3
and its deployed files remain historical and are not overwritten, deleted, or
cleaned. The repair integration prepares, but does not authorize, one future
fresh two-file no-overwrite deployment of launcher plus manifest.

## V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01 boundary

The revision-4 launcher, manifest, bootstrap, and profile identities are
immutable historical evidence. Deployment passed; the subsequent read-only
qualification failed because the launcher made nested-stdin closure depend on
outer EOF while the unchanged bootstrap required EOF after its one exact AGV3
frame. This section supersedes only that forwarding sequence.

The successor launcher performs one closed mechanical acquisition before any
nested process exists:

1. read exactly 12 bytes from outer stdin;
2. require bytes 0..3 to equal ASCII `AGV3`;
3. decode bytes 4..11 as one unsigned 64-bit big-endian length;
4. require the declared payload length to be at most 179306484;
5. read exactly that many payload bytes and nothing afterward.

It does not decode canonical JSON, inspect `protocol`, `operation`, `binding`,
or `payload`, select an executable, or create authority. A high 32-bit length
word is necessarily above the frozen cap and rejects. A short header or short
payload reaches no nested process. If a producer neither completes the frame
nor closes stdin, the existing controller deadline may terminate the outer
process; no partial frame may cross into nested SSH.

Only after the complete frame is resident does the launcher create and start
the one exact attested `rtwin_ssh` process. It starts the existing bounded
stdout/stderr asynchronous drains before one finite asynchronous write of the
exact header and payload bytes. All three tasks share the bounded completion
pump; when the finite input task completes, the launcher flushes and closes
nested stdin immediately while output drains continue. This prevents a child
that emits output before consuming a large request from deadlocking against a
synchronous write. It never uses
`ReadToEnd`, `CopyToAsync` through EOF, line/text conversion, a post-frame read,
or an outer-EOF wait. The required ordering is:

```text
FULL_FRAME_ACQUIRED < NESTED_SSH_STARTED
NESTED_SSH_STARTED < NESTED_FRAME_WRITE_COMPLETE
NESTED_FRAME_WRITE_COMPLETE < NESTED_STDIN_CLOSED
```

Nested-stdin closure does not read, observe, or wait for outer EOF. In the
required held-open proof vector, closure precedes the producer's later
deliberate EOF. A conforming controller may instead close immediately after
its one frame, so no universal event order is imposed on EOF. The bootstrap
still reads its own 12-byte header and exact payload, then requires one
additional read to return EOF; that check is not weakened. The Controller
still serializes exactly one frame with no prefix/suffix. Consequently a
full-length mutation passes the launcher mechanically but fails at the
bootstrap's existing canonical protocol/binding validation.

The source-controlled successor is
`auto-g16-v3-rtwin-launcher-v3.ps1`, 9579 bytes, 161 LF, zero CR/NUL,
SHA-256 `7247beda73482146c26b997702c9f74e6e9fb930e0bc55605fde42caa218658f`.
Bootstrap protocol/table/source and manifest schema stay `/2`; only a new
manifest-v2 content instance changes to bind the new launcher identity/path.
A future live chain must create immutable ServerProfile revision 5 and resolve
new `resolved_server_profile_id` and `effective_config_sha256` values. No
revision-4 object may be refreshed in place.

Before future deployment or read-only qualification, the six residual
launcher/nested processes reported by the failed qualification must be
reconciled by exact identity and count. Count zero is mandatory. A nonzero
count requires a separate exact-process termination gate; this contract grants
no broad kill, cleanup, deletion, or deployment authority. It also grants no
workspace/staging, qsub, Gaussian, retry, recovery Attempt, or live effect.

## V30-TRANSPORT-WINDOWS-OPENSSH-REDIRECTED-OUTPUT-COMPLETION-CONTRACT-01 boundary

Revision-5 deployment remains PASS and its deployed launcher/manifest remain
immutable. Production qualification remains failed evidence because exact
Windows OpenSSH 9.5p1 returned emitted bytes through redirected stdout/stderr
but kept the owned child process nonterminal. This section supersedes only the
nested response-completion rule. It does not authorize a revision-5 replay or
alter any deployed file.

The launcher mechanically recognizes response completion in this exact order:

1. collect at least the 12-byte response header under the existing
   179306496-byte stdout cap;
2. require bytes 0..3 to equal ASCII `AGV3`;
3. decode bytes 4..11 as one unsigned 64-bit big-endian length;
4. require that length to be at most 179306484;
5. collect exactly `12 + length` bytes;
6. require zero stderr bytes and zero stdout bytes beyond that exact frame.

No earlier state is response-complete. Partial header/payload, bad magic,
oversize, stderr, cap overflow, extra byte, or second frame rejects. A full
frame does not mean protocol success: the launcher parses no JSON and assigns
no operation, binding, status, result, retry, scheduler, or scientific
authority.

After both `NESTED_STDIN_CLOSED` and `RESPONSE_FRAME_COMPLETE`, a source-fixed
monotonic 5000-millisecond grace begins. Throughout the grace the existing
bounded asynchronous drains continue, so late extra output or stderr rejects.
If the child exits naturally, both streams must still reach EOF and the exact
child exit status is preserved. If it remains alive after the grace, only the
exact `Process` instance that this launcher created may be terminated. The
launcher then waits for that exact process and both pipes to close, rejects any
new bytes, and performs every existing postlaunch attestation before emitting
the buffered response. The owned-teardown mechanical outcome maps to launcher
exit zero only after those predicates pass. There is no process discovery,
PID-only lookup, name filter, tree kill, substitute process, or retry.

The Controller remains the sole response semantic authority. Its existing
decoder requires the exact frame length and canonical JSON, exact `/2`
protocol, matching operation, closed status/result schema, and operation-
specific binding. A malformed or semantically wrong complete frame therefore
fails after mechanical transport completion. For a possibly-effectful request,
anything short of one Controller-accepted response retains `UNKNOWN` and zero
automatic retry; it never permits a second qsub.

The unchanged bootstrap still reads one complete request and requires request
EOF. Its response bytes, AGV3 `/2`, seven operations, manifest schema v2, ten
trust roots, command construction, resource enactment, no-overwrite rules,
physical identities, and all public APIs remain unchanged. General process
completion/EOF rules elsewhere remain binding; this exception applies only to
the attested revision-6 RTwin launcher and its one owned nested Windows
OpenSSH child after an exact response frame.

The successor is `auto-g16-v3-rtwin-launcher-v4.ps1`, 11790 bytes, 200 LF,
zero CR/NUL, SHA-256
`52ce86be68356832b5b357c1c088aee9fc1b19701fe98115ef97b2a077dd7f60`.
Bootstrap identity remains 15562 bytes and SHA-256
`ad0ba2af50a3bfedf186acf13d8468d5951f5d201b71687ba5dd2ef7b2a208ae`.
A successor manifest-v2 content instance changes only the launcher identity
and path; ServerProfile revision 6 must resolve a new profile ID and effective
digest. Integration prepares, but does not authorize, its fresh two-file
no-overwrite deployment.

## V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01 boundary

The selected successor execution chain is Controller -> exact buffered AGV3
frame -> exact Mac `/usr/bin/ssh` -> one config-bound `ProxyJump` through RTwin
-> final server -> unchanged fixed bootstrap. RTwin is only the jump-host SSH
endpoint and direct-tcpip forwarder. It does not consume AGV3 stdin,
authenticate to the final server, or hold the final-server private key.

Route selection is closed and private. An exact Option-1 config inventory
selects `mac-openssh-proxyjump-v1`; the prior exact four-file inventory selects
only the historical Windows route. A mixed, incomplete, or additional inventory
rejects. Option-1 never falls back to Windows nested SSH, STARTUPINFOEX,
ProxyCommand, direct Mac-to-server, or the old RTwin launcher.

The Option-1 config has exactly two closed host blocks, one calculated final-key
fingerprint comment, and one frozen final private-file physical-identity
comment. It binds the one RTwin jump identity and known-hosts file,
the distinct dedicated final-server identity and known-hosts file, the exact
target identities already present in the resolved ServerProfile, and all
frozen authentication restrictions. The four config artifacts, including the
dedicated final public key, and `/usr/bin/ssh` are attested before and after the
process. The public key is strict canonical ED25519 and its calculated
fingerprint must equal the config binding. Each private identity reference is
a current-user-owned, non-symlink regular file with exact mode `0600`; the final
identity must also match the frozen device/inode/size/mtime/ctime tuple. Private
content is never opened or read. Exact `CertificateFile none` is mandatory in
both host blocks, disabling OpenSSH's implicit sibling user-certificate lookup.

The final argv is exactly the attested executable, `-F`, the bound private
config path, `--`, the bound final alias, and the existing quoted server
bootstrap command. Variable argv positions reject NUL, CR, and LF. LF is
permitted only inside the already identity-gated fixed bootstrap source word.
Process creation remains `shell=False`; the existing bounded binary
stdin/stdout/stderr supervisor and strict response decoder are reused.

ServerProfile revision 8 binds the qualified OpenSSH 10.3p1 executable,
Option-1 config/trust identities, exact final public-key fingerprint, unchanged
ten-root manifest schema, unchanged Torque/resource descriptor, and unchanged
bootstrap/table bytes. It resolves as
`44f3b829-e2d1-5500-b463-5acd8851d279` with effective config SHA-256
`110bac5e2fbcecd2a01a81f8df5004f797cb191b2089b620b4379db28a7cb99d`;
the new 3294-byte manifest SHA-256 is
`bf422724e83cc16031136783fb042207959cb0cd7f602e7d0f63df787350019e`.
No public Execution/Transport API or schema changes.
Deployment and every calculation effect remain separate Owner gates.

## Scheduled job working-directory enactment

The resource renderer also derives one mechanical workdir argument from the
already-bound `remote_workspace`. Its semantic source is exclusively
`ExecutionSnapshot.workspace_binding.remote_attempt_dir`; it is not a resource
field and does not enter `ResourceEnactment`. For the exact Torque dialect the
complete argument tuple is:

```text
("-d", "<exact remote Attempt workspace>",
 "-l", "nodes=1:ppn=C,mem=Mmb,walltime=W",
 "-q", "batch", "B")
```

The qsub client continues to execute with descriptor-derived cwd equal to the
same workspace. Immediately before qsub, the bootstrap reopens the exact named
workspace no-follow, replays its frozen physical token, and compares the named
descriptor's device/inode with the retained descriptor. Any path, symlink,
replacement, token, or descriptor mismatch rejects before qsub.

The request schema is unchanged: `remote_workspace` remains in the existing
submitted binding and no argv/workdir value is accepted from the payload. The
private operation table declares `remote_workspace` as a submit renderer input
and its cwd policy covers both qsub client and scheduled shell. Protocol `/2`,
the seven operations, manifest schema v2, and public APIs are unchanged.

The exact successor operation table is 1623 bytes with SHA-256
`ce3efce070694831c32dbadd71fc2e7991f02cd985055193966666ea19dc9ffc`.
The fixed Python-3.6 bootstrap is 15926 bytes, 210 LF, zero CR/NUL, with
SHA-256 `a90edecf87916c149e865256d69e6f57820cb29336380bd45d2107c7c00c64f0`.
The corresponding source-controlled RTwin launcher-v5 is 11790 bytes, 200 LF,
with SHA-256
`184b806c07f05fdd1e51a669e9ff245f43c22b22b2efa17e5578f501d2e2d06d`.
Predecessor identities remain immutable historical evidence.

## V31-SHARED-CONTRACT-01 shared execution and ensemble contract

This section freezes contract only. It defines no product classes, schema
files, registry implementation, parser, transport operation, command renderer,
or live effect.

### Exact change disposition

| Disposition | Frozen V31 treatment |
| --- | --- |
| **KEEP** | Core `Project` remains exactly `{project_id}`; the Core schema, Task/Attempt lifecycle, approvals, no-overwrite, at-most-one effect, `REPLAY` zero effect, `UNKNOWN` reconciliation-only, and no automatic retry stay authoritative. |
| **ADD** | One Project first-use physical-provisioning contract and provisioning-domain `ProjectPhysicalBinding`; the private closed ProgramAdapter registry; public `SamplingProfile`, `ConformerEnsemble`, and `ThermodynamicEnsemble` ensemble records. |
| **VERSIONED SUCCESSOR** | Public execution records `ProgramExecutionSpec` and `ProgramExecutionSnapshot` support the V31 Gaussian/xTB/CREST path without changing a V30 record or existing Attempt. |
| **DO NOT TOUCH** | V30 `PreparedInputBinding`, `PbsTemplateBinding`, `ExecutionSnapshot`, and vectors; Core Project shape/schema; Approval, Workflow, Observe, Result, ScientificValidation, and Review public contracts; Transport topology/protocol/operations; every current parser and grammar; live/deployment behavior. |

The future V31 product must expose no more than the two named new execution-
domain records. `ProjectPhysicalBinding` is owned by the separate provisioning/
physical-authority boundary and is not an execution record. Nested closed
values described below are record fields, not additional public execution
records, protocols, adapters, or extension bags.

### Project first-use physical provisioning

`ProjectPhysicalBinding` has these mandatory semantic fields:

- `project_physical_binding_id` and `project_id`;
- `provisioning_contract_version`;
- an ordered, non-empty `locations` tuple whose closed members bind
  `location_kind`, reviewed root, exact Project directory, provisioning
  disposition, retained parent physical identity, resulting Project-directory
  physical identity, and exact create/re-attestation evidence identity;
- the complete identity payload used to derive the record ID.

Location kinds are a closed V31 set selected by the owning target contract;
they do not add a Transport topology or select a program. Resolution has
exactly three branches:

1. **target absent:** under a reviewed no-follow root, one unique intent wins;
   the implementation replays the retained parent identity immediately before
   one exact nonrecursive no-follow mkdir, then durably records the resulting
   Project-directory physical identity in `ProjectPhysicalBinding`;
2. **already Product-bound existing:** the exact durable Product binding is
   loaded first, the current named target is no-follow re-attested to the same
   physical identity, and reuse is idempotent with no second mkdir; or
3. **unbound existing:** an existing target without the exact durable Product
   binding returns `UNBOUND_EXISTING`, performs zero effects, and stops for a
   later explicit Owner migration/adoption decision.

A non-directory, symlink/reparse point, root escape, parent or target
replacement, identity drift, conflicting binding, or implicit adoption fails
closed. A concurrent loser performs zero effects. Provisioning does not
allocate an Attempt, and it may not overwrite, truncate, recursively replace,
delete, or clean any path. An ambiguous first-use effect yields no usable
`ProjectPhysicalBinding`, enters exact same-intent reconciliation, and creates
no automatic retry or alternate-location authority.

The provisioning journal and effect receipt are private implementation details
for a later contract. They live outside the Core schema. Their future design
must preserve the above outcomes and cannot be inferred from legacy v2 owner,
receipt, or capability machinery.

### Additive versioned multi-program execution successor

`ProgramExecutionSpec` has these mandatory semantic fields:

- `program_execution_spec_id`, `program_kind`, `adapter_id`, and positive
  `adapter_contract_version`;
- an ordered, non-empty closed `exact_inputs` tuple binding logical role,
  portable name, format, SHA-256, and size for every immutable input byte set;
- closed `program_data` matching the exact adapter/version schema, with no
  unknown key, extension bag, callback, or executable content;
- closed `invocation` semantics binding exact executable identity, ordered argv
  tokens, declared stdin/data source, and closed environment inputs; and
- ordered `required_outputs` and `optional_outputs` tuples, each with exact
  logical role, portable path/name grammar, format, cardinality, size/capture
  policy, and required completeness meaning.

An output cannot appear in both tuples. Missing required output is failure;
missing optional output is an explicit absent observation and cannot change
overall program success semantics unless the exact adapter version says so.
The spec contains no Attempt, resource, target, workspace, or scheduler choice.

`ProgramExecutionSnapshot` has these mandatory semantic fields:

- `program_execution_snapshot_id`, `attempt_id`, `effect_intent_id`,
  `calculation_plan_id`, and positive `calculation_plan_revision`;
- the exact `program_execution_spec_id` and spec payload hash;
- the exact `project_physical_binding_id` and one exact Attempt workspace below
  a bound Project location;
- the resolved resource and target bindings, exact cwd binding, plus any
  derived scheduler artifact identities required by that target; and
- the complete canonical identity payload used to derive both the effect
  intent and snapshot IDs.

The snapshot is the sole V31 program-effect meaning. It is immutable and
self-authenticating; any byte, token, parameter, adapter version, resource,
target, Project binding, workspace, or output-declaration change requires a new
snapshot and current approval/confirmation under a later implementation
contract. One Attempt selects exactly one execution generation. A V30 Attempt
cannot acquire a V31 snapshot, and a V31 Attempt cannot also carry V30
`PreparedInputBinding`, `PbsTemplateBinding`, or `ExecutionSnapshot` authority.

`ProgramExecutionSpec.program_kind` is exactly one of `gaussian`, `xtb`, or
`crest`. `ProgramAdapter` is the name of a private closed registry role only.
The registry contains exactly the three program kinds above and maps each exact
`(program_kind, adapter_id, adapter_contract_version)` key to closed data
validation and deterministic rendering. It exports no public adapter object,
generic plugin hook, arbitrary program name, or caller registry mutation.
Unknown keys fail closed.

Primary invocation semantics live in `ProgramExecutionSpec` as an executable
identity plus argv tokens and typed data. Every token is separately represented
and validated; process creation is non-shell. A `command`, `command_line`, or
equivalent shell string cannot be the primary meaning or a fallback. Ambient
PATH, shell expansion, caller environment, response files, and undeclared files
cannot supply missing semantics. When PBS or another unchanged target mechanism
needs script bytes, the private renderer deterministically derives and byte-
binds that secondary artifact from the closed snapshot. The script cannot
replace the argv/data meaning. This contract adds no AGV3 operation, SSH hop,
PBS dialect, transport route, parser, or result grammar.

### Independent SamplingProfile policy record

`SamplingProfile` is an independent public ensemble-domain record with these
mandatory semantics:

- `sampling_profile_id`, immutable revision/supersession binding, exact species
  and electronic-state scope, and exact stereochemical scope;
- closed route/category definitions, engine and implementation identities,
  immutable configuration identities, seeds, constraints, and reviewed
  allocation/quotas;
- candidate-legality rules for atom map/order, connectivity, explicit
  hydrogens, charge, multiplicity/state, fragments, stereochemistry, finite
  geometry, clashes, association/dissociation, and required/forbidden changes;
- the complete cluster/dedup metric, descriptor weights, units, thresholds,
  symmetry treatment, independent-backend requirements, tie-breaks, and
  category-crossing rules;
- explicit coverage criteria and exact failure/blocker semantics; and
- explicit thermodynamic-eligibility and TS-seed-eligibility policies.

The profile is separate from `ConformerEnsemble` because policy must be frozen
before candidate observations, independently identified, and reusable without
copy drift across immutable ensemble revisions. An ensemble embeds the exact
profile identity and payload hash; it cannot override any policy value.

Every applicable numeric or categorical policy value is explicit. V31 defines
no universal `6 kcal/mol` window, Top-N, RMSD threshold, A/B route quota,
temperature, or implicit fallback. Values from legacy conformer Skills are
reuse/benchmark evidence only. `null`, omission, and implementation defaults
cannot silently select policy; a genuinely inapplicable field uses an explicit
closed tagged disposition with rationale.

### ConformerEnsemble minimum public shape

`ConformerEnsemble` has these mandatory semantic fields:

- `conformer_ensemble_id`, `project_id`, exact source CalculationPlan/revision,
  and the exact `sampling_profile_id` plus profile payload hash;
- one closed `species_binding` covering graph and atom-order identities,
  explicit hydrogens, fragments, charge, multiplicity, electronic-state family,
  and atom mapping;
- one closed `stereochemistry_binding` covering every specified center, axis,
  face, geometric isomer, and binding-mode/category identity applicable to the
  reviewed species;
- ordered source provenance and immutable geometry provenance for every member,
  including coordinates identity, atom order, source observation/execution,
  engine/configuration/seed lineage, and any accepted minimum evidence;
- complete sampling observations; a complete audit and negative-evidence
  ledger with every rejection and reason; explicit cluster membership, medoid,
  dedup comparison/decision, independent-backend review, and deterministic
  tie-break evidence; and
- the exact coverage evaluation, ordered `thermodynamic_eligible_members`, and
  ordered `ts_seed_members` projections.

One ensemble contains exactly one species graph, atom order, charge,
multiplicity, and electronic-state family. Cross-state ranking or population is
forbidden. Different reviewed stereochemical or category identities are not
silently merged. Geometry identity never implies minimum or TS acceptance.
Sampling/FF/xTB/CREST energies remain provenance and cannot become formal DFT
thermodynamics or barriers.

Member eligibility is derived, never asserted. The deterministic projections
filter the canonical member order through the exact SamplingProfile policy and
the recorded audit/minimum evidence. Missing evidence, an unresolved audit,
failed coverage, state/stereo drift, incompatible geometry lineage, or required
independent-backend blocker makes the affected projection unavailable rather
than choosing a fallback subset.

`ts_seed_members` is the complete V31 TS-seed handoff from the ensemble. It
does not select a reaction, reaction coordinate, primary/backup portfolio, TS
algorithm, or method and does not claim that a member is a TS. An independent
TS-seed record would duplicate the ensemble member identity and drift from the
same audit lifecycle, so V31 intentionally does not add one. The later
TS-seed workflow consumes an eligible member and separately binds the exact
reaction hypothesis, atom mapping, coordinate lineage, and review gates.

### ThermodynamicEnsemble handoff

`ThermodynamicEnsemble` has these mandatory semantic fields:

- `thermodynamic_ensemble_id`, exact `conformer_ensemble_id` and payload hash,
  and the exact ordered source member set, which must equal the available
  `thermodynamic_eligible_members` projection;
- temperature with units, a complete standard-state definition and conversion
  convention, and the gas constant/unit convention used by aggregation;
- a closed low-frequency treatment binding with scheme name/version, every
  parameter and unit, interpolation/cutoff rules, mode-selection semantics,
  and the exact implementation package/version/source identity;
- one exact method-compatibility binding covering geometry, frequencies,
  electronic energies/corrections, solvent/environment, reference/state,
  basis/model, symmetry-number convention, and result-contract identities;
- for each conformer, exact result provenance, raw RRHO components and raw
  standard-state Gibbs energy, separately recorded treated qRRHO components
  and treated Gibbs energy, degeneracy and its scientific rationale, inclusion
  status, relative statistical weight, and normalized population; and
- the reference member, relative partition function, ensemble treated free
  energy, population normalization evidence, and deterministic identity
  payload.

No temperature, standard state, low-frequency scheme/cutoff/interpolation,
implementation, degeneracy, or method-compatibility value is inferred or
defaulted. Every included conformer must be method-compatible under the one
binding. A missing or incompatible eligible member blocks the ensemble; the
builder cannot silently renormalize a convenient subset. Degeneracy cannot
duplicate a rotational symmetry number or another statistical factor already
included by the raw RRHO implementation.

For treated per-conformer free energies `G_i` at the bound temperature, with
explicit degeneracies `d_i`, the aggregation is:

```text
G_ref = min_i(G_i)
w_i   = d_i * exp(-(G_i - G_ref) / (R*T))
Q_rel = sum_i(w_i)
p_i   = w_i / Q_rel
G_ens = G_ref - R*T*ln(Q_rel)
```

The stored raw RRHO values are evidence and are never overwritten by treated
values. Low-frequency treatment is applied once per conformer before the
ensemble sum. Because `Q_rel` already represents conformer mixing and
degeneracy, a separately calculated conformational entropy may be reported only
as a diagnostic decomposition; it must not be subtracted from `G_ens` or added
to any member again.

### Zero-effect and compatibility boundary

This freeze creates no implementation authority. It does not provision a
Project, allocate or mutate an Attempt, create structures, run a program,
render an input/script, invoke a process, parse output, move data, or accept a
scientific result. Product/API/schema implementation, tests/vectors, and any
live use each require a later exact Owner gate. The Core schema, Transport
topology, current parsers, V30 vectors, and all pre-existing public meanings
remain byte- and semantics-preservation targets for that later work.
