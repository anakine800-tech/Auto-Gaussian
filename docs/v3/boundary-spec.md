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

## V30-EXEC-01 Execution Boundary Contract

**Contract status: FROZEN. Implementation remains unauthorized.** This is the
RTwin-first `legacy_rtwin_pbs` execution boundary, not a generic execution or
transport framework. `ExecutionSnapshot`, preparation records, effect evidence,
and transport remain outside `auto_g16.core`.

### Execution identity and preparation

Execution identities use the execution-private canonical encoding
`EXEC-CANON/1`, whose domain prefix is
`auto-g16-exec-canonical/1\0`. It encodes null, booleans, integers, finite
binary64 floats (`-0.0` normalized to `+0.0`), exact UTF-8 strings without
Unicode normalization, ordered sequences, and mappings sorted by UTF-8 key
bytes. Counts and byte lengths are unsigned eight-byte big-endian values;
integers use a sign byte plus a minimally encoded magnitude. Duplicate keys,
cycles, non-finite floats, path objects, timestamps, and unsupported values
fail closed. This encoding is not Core's private encoding, a persistence
format, or a cross-domain serializer.

Before snapshot resolution, the resolver must load and validate the complete
Core chain:

```text
Attempt -> Task -> WorkflowRun -> Project
        -> exact CalculationPlan
        -> exact ResourceSpec
```

The `Attempt`, `CalculationPlan`, and `ResourceSpec` must have the same
`task_id`; the Task must belong to the loaded WorkflowRun and Project. The
executor never reinterprets `CalculationPlan.intent`, changes chemistry,
rewrites the prepared input, supplies defaults, or resizes resources.

The Preparation Owner produces one sealed, read-only local handoff containing
the exact prepared input bytes. It creates the Attempt-local directory as the
single derived child of the approved local root using exclusive, component-wise
no-follow operations; an existing target, symlink, replacement, containment
failure, or partial seal fails closed and retains durable Preparation Owner
evidence of any allocated prefix. It records and verifies the immutable bytes,
size, and SHA-256 before handing the same byte value to execution.
Execution may read that sealed handoff but may not mutate it or reread an
ambient source path.

`ExactInputBinding` has exactly these immutable fields:

| Field | Meaning |
| --- | --- |
| `exact_input_binding_id` | Domain-separated identity of every other field |
| `task_id` | Exact Core Task |
| `calculation_plan_id`, `calculation_plan_revision` | Exact persisted plan version |
| `calculation_plan_content_id` | SHA-256 of `EXEC-CANON/1` over the plan's public semantic fields |
| `input_basename` | Reviewed path-safe basename |
| `input_sha256`, `input_size_bytes` | Exact sealed prepared bytes; size is positive and booleans are invalid |

The ID is `auto-g16-exact-input/1:` plus the lowercase SHA-256 of
`EXEC-CANON/1` over every field except the ID. The execution consumer verifies
the handed-off bytes against basename, size, and digest and consumes those
same bytes without a mutable reread.

`ResourceSpec.resources` has exactly `tier`, `cores`, `memory_gb`, and
`walltime_seconds`. Integers are positive and booleans are invalid. Resolution
has no default or environment override. `ExactResolvedResourceRequest` has
exactly:

| Field | Meaning |
| --- | --- |
| `resolved_resource_request_id` | Domain-separated identity of every other output field |
| `task_id`, `resource_spec_id` | Exact Core join |
| `resource_spec_content_id` | SHA-256 of `EXEC-CANON/1` over the public ResourceSpec fields |
| `tier`, `cores`, `memory_bytes`, `walltime_seconds` | Exact request, with `memory_bytes = memory_gb * 1024^3` |

### ServerProfile resolution and immutable bytes

`ServerProfile` is mutable, closed configuration. Before the Core submission
intent claim, the resolver deterministically freezes its exact revision and all
effect-relevant, non-secret resolved content. The resolved target contains
exactly:

- `server_profile_id`, `server_profile_revision`, and
  `server_profile_content_id`;
- `adapter_kind`, exactly `legacy_rtwin_pbs`;
- normalized local and Windows workspace roots and the fixed server root
  `/home/user100/SDL`;
- `rtwin_config_content_id`, `rtwin_effective_config_id`,
  `server_config_content_id`, and `server_effective_config_id`;
- `runtime_effective_config_id`; and
- `pbs_template_content_id`.

For each SSH hop, the content identity binds the exact ordered, validated
config/include-file bytes used for the selected alias. The effective identity
binds the complete normalized non-network resolution, including destination,
port, user, jump topology, host-key behavior, batch and identity-selection
behavior, and identity/known-hosts path identities. Credentials, private-key
bytes, agent material, passwords, and tokens are excluded. Alias, revision,
source path, or caller-supplied digest alone is never authority. Unsupported
command-bearing or ambient expansion (`ProxyCommand`, `LocalCommand`,
`RemoteCommand`, `Match exec`, shell expansion, or include outside the approved
root) fails closed. The runtime identity likewise derives from the complete
closed effect-relevant non-secret runtime record, never from an opaque caller
digest. Resolution failure or mutation during resolution fails closed; after
resolution, execution may not reread the profile, CLI, environment, or mutable
configuration.

Every effect-relevant path is an explicit absolute canonical path. POSIX paths
start at `/` and contain no empty, `.`, `..`, repeated-separator, NUL, or
unresolved-symlink component. Windows paths are already-normalized absolute
uppercase-drive paths using `\\`; UNC, device namespaces, drive-relative,
root-relative, home-relative, `~`, environment/current-directory expansion,
ADS, empty/`.`/`..` components, repeated separators, control characters,
reserved device names, and trailing spaces or dots are forbidden. No resolver
may repair or reinterpret a rejected path.

The fixed `V30-EXEC-01 PBS Template Byte Owner` opens the one approved template
descriptor-relatively from a stable local root with component-wise no-follow
checks. It requires a regular file with `nlink == 1`, reads once from the same
descriptor, verifies stable device/inode/type/size before and after the read,
and records exact raw bytes, size, and lowercase SHA-256. Template bytes may not
contain connection metadata or secrets. Its narrow byte receipt has exactly
`receipt_id`, the fixed owner string, `template_root_id`,
`template_relative_name`, `st_dev`, `st_ino`, `file_type = regular`, `mode`,
`nlink = 1`, `template_size_bytes`, and `template_sha256`; timestamps are
excluded. The receipt ID and content ID are respectively domain-separated over
all receipt fields and over `{encoding = raw-bytes, size, sha256}`. Execution
consumes the same immutable byte value accompanying the receipt; a missing or
mismatched value or any mutable reread fails closed. This is not a template
registry, signature, lineage, or general receipt framework.

### ExecutionSnapshot and workspaces

`ExecutionSnapshot` is keyword-only, deeply immutable, and has exactly these
top-level fields:

| Field | Closed value |
| --- | --- |
| `execution_snapshot_id` | Final deterministic snapshot identity |
| `attempt_id`, `task_id`, `project_id` | Exact validated Core chain |
| `core_submission_intent_id` | Exact caller-supplied Core intent reference |
| `exact_input` | One `ExactInputBinding` |
| `resources` | One exact resolved resource request |
| `target` | All resolved profile, endpoint, runtime, and template identities above |
| `workspace` | Name, normalized roots, derived paths, and three platform identities |
| `program` | `program_kind = gaussian`, `runtime_kind = g16`, `invocation_mode = legacy_stdin`, and the runtime identity |

It contains no timestamp, credentials, mutable path source, approval, or
transport authority. Build `snapshot_body` from every field except the two ID
fields, then derive:

```text
core_submission_intent_id =
  "auto-g16-v30-exec-intent/1:" + sha256(EXEC-CANON/1(snapshot_body))

execution_snapshot_id =
  "auto-g16-v30-exec-snapshot/1:" +
  sha256(EXEC-CANON/1(all fields except execution_snapshot_id))
```

Identical semantic content replays both identities. Changing the Attempt,
Core chain, input, resources, profile/config/runtime/template content,
workspace, program, or exact Core intent changes the relevant identity.

The workspace name is `attempt-` plus the full lowercase SHA-256 of the exact
UTF-8 `attempt_id`. `Project` remains a logical reusable collection and is not
a physical path component. The three derived directories are the single child
of the resolved local root, resolved Windows root, and fixed
`/home/user100/SDL` root. Each workspace identity is domain-separated over the
platform tag, endpoint/effective-config identity, normalized root, workspace
name, and normalized derived path.

The local directory is the Preparation Owner's sealed read-only handoff.
RTwin and server directories are allocated only inside the ordered effect
boundary, descriptor-relatively and exclusively after immediately revalidating
the owned root. Existing targets, root or endpoint drift, symlinks, reparse
points, escape, or capability failure stop with no later effect. No caller
override, fallback, overwrite, reuse, deletion, or automatic cleanup exists.
Any confirmed or ambiguous partial allocation is retained as durable evidence
and remains unresolved rather than being reused.

### Submission and effect semantics

The only legal Core claim is:

```text
record_submission_intent(
    snapshot.attempt_id,
    snapshot.core_submission_intent_id,
)
```

Exactly one explicit `WINNER` may enter the effect boundary. `REPLAY` makes
zero adapter, transport, allocation, transfer, or submission calls. Validation,
a snapshot, profile, receipt, or adapter state cannot replace `WINNER`.

Effects are strictly ordered: RTwin allocation; server allocation; transfer of
the exact prepared bytes to RTwin; transfer of the same verified bytes to the
server; and one submission call. Each step requires all earlier evidence to be
confirmed, immediately revalidates the root and endpoint identity, consumes a
single-use descriptor- or capability-bound internal handle, and persists its
outcome before the next step. This handle is internal; no public owner-chain or
capability framework is introduced. At most one `qsub` call is permitted for
the Attempt.

The only public execution-layer effect evidence is a minimal, private,
append-only `RemoteEffectReceipt` with exactly `attempt_id`,
`execution_snapshot_id`, `core_submission_intent_id`, one remote workspace
platform/path/identity, `effect_kind`, `effect_outcome`, and optional exact
`remote_job_id`. Effect kinds are RTwin allocation, server allocation, transfer
to RTwin, transfer to server, and submission; outcomes are `CONFIRMED` or
`AMBIGUOUS`. Sanitized views remove paths and connection metadata. Receipt
presence is evidence, never authority; exact replay is idempotent and
conflicting content fails closed.

A proven failure during preparation, profile resolution, path derivation,
template sealing, or snapshot validation occurs before the Core intent and any
effect, leaves the Attempt `PLANNED`, and is not `UNKNOWN`. After `WINNER`, a
proven no-effect stop is semantically not submission uncertainty, but the
frozen Core API requires the legal persisted path `UNKNOWN` -> same-Attempt
no-submission Observation -> reconciliation to `NOT_SUBMITTED`. Any failure
that may have crossed allocation, transfer, or submission without exact bound
evidence is genuinely `UNKNOWN`. Only exact Attempt/snapshot/intent-bound
reliable evidence can establish `SUBMITTED`; missing, multiple, contradictory,
unbound, or unreliable evidence remains `UNKNOWN`.

`UNKNOWN` is reconciled durably on the same Attempt. It never authorizes an
automatic retry, another `qsub`, alternate profile or workspace, replacement
root Attempt, child Attempt, cleanup, cancellation, or `qdel`. ExecutionSnapshot
and all transport/effect behavior remain outside Core.

## V30-RESULT-01 Result Provenance Contract

**Contract status: FROZEN. Implementation remains unauthorized.** The frozen
append-only chain is:

```text
CalculationPlan -> Attempt
                -> exact input-binding Observation
                -> program-output-envelope Observation
                -> Result
```

Ownership is resolved only through
`Attempt -> Task -> WorkflowRun -> Project`; provenance payloads do not copy a
second ownership truth. The loaded CalculationPlan must have the Attempt's
`task_id`. Under the frozen Core store, a new semantic plan revision requires a
new `calculation_plan_id`, and an input-bound Attempt cannot be rebound.

### Deterministic record identities

The boundary namespace is UUIDv5 of URL namespace name
`https://github.com/anakine800-tech/Auto-Gaussian/contracts/v30-result-provenance/1`:

```text
52422c7e-cbef-589a-b1d0-0da41666d8eb
```

Each ordered identity field is exact UTF-8 encoded as
`ASCII(decimal byte length) + ":" + bytes`; decimal lengths have no sign or
leading zero except zero itself. Names are the concatenation of those fields.
There is no Unicode normalization, no empty identity field, and no use of
Core's private canonical encoding. UUID text is canonical lowercase.

The input binding uses `observation_type` and `contract`
`auto-g16.program-input-binding/1`. Its UUIDv5 name fields are, in order,
record kind without version, `1`, `attempt_id`, exact input SHA-256, decimal
size, and media type. Its payload has exactly `contract`,
`calculation_plan_id`, `calculation_plan_revision`, `input_artifact` containing
`sha256`, `size_bytes`, and `media_type`, and `bound_at_utc`. Exact replay keeps
the same ID and timestamp. A different plan under the deterministic ID is a
conflict; more than one distinct valid binding for one Attempt is a semantic
conflict.

A capture ID is a durable canonical lowercase UUID issued and reserved by the
owner of exact output-byte capture before exposure to this boundary. Replaying
or rereading the same sealed capture reuses it; every new acquisition gets a
new ID even if its bytes match an older capture. A parser, rescan, mtime, or
result materialization cannot issue or change it. Without a stable owner-issued
capture ID there is no valid envelope.

The output envelope uses `observation_type` and `contract`
`auto-g16.program-output-envelope/1`. Its UUIDv5 name fields are, in order,
record kind without version, `1`, `attempt_id`, exact input-binding Observation
ID, and `capture_id`. Its payload has exactly:

- `contract`, `input_binding_observation_id`, and `capture_id`;
- `program` with `name` and nullable `version`;
- `adapter` with `name`, `version`, and `output_contract`;
- exact repeated `input_artifact` and exact captured `output_artifact`, each
  with `sha256`, `size_bytes`, and `media_type`;
- `observed_at_utc` and `sealed_at_utc`;
- `program_status`; and
- `capture_completeness`.

`program_status` is one of `completed`, `failed`, `interrupted`, `nonterminal`,
or `unknown`. It is a runtime/program fact, not Attempt state or scientific
acceptance. Capture completeness is `complete` or `partial`, is asserted by the
capture layer, and cannot be promoted by the parser.

The Result uses `result_type` and `contract`
`auto-g16.program-result/1`. Its UUIDv5 name fields are, in order, record kind
without version, `1`, exact envelope Observation ID, parser name, parser
version, parser result contract, and parser result kind. Its payload has
exactly `contract`, `source_envelope_observation_id`,
`input_binding_observation_id`, `parser` with those four parser fields, exact
repeated input/output artifact identities, `materialized_at_utc`,
`parse_status`, `facts`, `missing_fact_codes`, and `diagnostic_codes`.
Persisted parse status is only `complete` or `partial`.

Exact replay produces the same record identity. A new capture or parser
name/version/contract/kind produces a new identity. All captures, parser
identities, envelopes, and Results append; none overwrites prior history.

### Envelope, parsing, and durable views

Artifact SHA-256 is exactly 64 lowercase hexadecimal characters. Size is a
nonnegative integer with booleans rejected. Media type is nonempty and has no
surrounding whitespace. Times are calendar-valid RFC3339 UTC with `Z`, optional
one-to-nine fractional digits, no surrounding whitespace or leap second, and
`sealed_at_utc >= observed_at_utc`. Replay retains original times.

Malformed envelope metadata, identity, relationship, repeated input, captured
byte hash/size, timestamps, status/completeness, or payload types produces no
valid envelope and no Result. By contrast, a valid envelope with exact captured
bytes remains valid when output is unparseable or unsupported; it is persisted,
and no Result exists unless at least one unambiguous fact justifies an explicit
partial Result. A partial Result requires nonempty `facts` and nonempty
`missing_fact_codes`. A partial capture can produce only a partial Result; a
complete capture may also produce a partial Result. A malformed Result
candidate produces no Result and leaves its envelope unchanged. None of these
conditions is execution failure or scientific rejection.

Readers enumerate all typed Observations and Results in frozen Core persisted
order, validate exact field sets and types, rederive every UUID, revalidate all
references and repeated artifact identities, and reject cross-Attempt or
cross-capture splicing. One Result binds exactly one envelope. Results are
grouped by exact envelope plus parser name/version/contract/kind and are never
combined across groups.

The current view prefers the last valid complete capture in Core persisted
Observation order. If no complete capture exists, it exposes the last valid
partial capture as explicitly incomplete. A newer partial capture never
displaces an existing valid complete capture. Filesystem mtime, filename,
directory/scan order, embedded time, or parser output never selects the current
view.

The legal durable states include `input-bound/output-absent`,
`output-sealed/result-absent`, `output-sealed/partial-result`, and
`output-sealed/complete-result`. Each record append is independently atomic;
the absence of a later record is a valid explicit incomplete prefix, not an
error or permission to synthesize data. Later captures, parser versions, and
Results append without changing the prefix's history.

Result creation and reading never advance, reconcile, or otherwise mutate
Attempt runtime state, infer success or failure, synthesize a record, or grant
retry authority. Program completion, capture completeness, parse status,
Result existence, and scientific acceptance are separate facts. Minimum,
transition-state, IRC, workflow, and other scientific acceptance remain a
later independent review layer. Core API and schema remain unchanged.

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
