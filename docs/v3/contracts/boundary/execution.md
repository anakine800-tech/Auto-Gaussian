# Auto-G16 v3 boundary: execution

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/boundary-spec.md:293-538 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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
