# Auto-G16 v3 Boundary Specification

This document fixes stable dependency and data boundaries only. It does not
select implementation techniques.

## Dependency Direction

`Skills -> Workflows -> Core`

Skills compose workflows, and workflows depend on Core. Core must not depend
on a Skill. Reverse imports across this direction are forbidden.

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

## V30-EXEC-01 Frozen Execution Contract

**Contract status: FROZEN. Implementation remains unauthorized.** This is the
RTwin-first `legacy_rtwin_pbs` execution boundary, not a generic execution or
transport framework. `ExecutionSnapshot`, preparation records, effect evidence,
and transport remain outside `auto_g16.core`.

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

**Contract status: FROZEN. Implementation remains unauthorized.** The public
package is `auto_g16.result`; focused tests belong under `tests/v3/result/`.
It may depend on `auto_g16.core`, but not live Transport, PBS, or RTwin, and it
does not change the Core schema. The only legal append-only chain is:

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
