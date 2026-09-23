# Auto-G16 v3 boundary: transport-composition

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [Snapshot-derived PBS resource enactment](transport-resources.md#snapshot-derived-pbs-resource-enactment)
- [Exact Torque 6.1.0 production dialect](transport-resources.md#exact-torque-610-production-dialect)
- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03 Physical and Bootstrap Authority Closeout](transport-bootstrap.md#v30-transport-bootstrap-chain-03-physical-and-bootstrap-authority-closeout)
- [Replacement-safe remote physical authority](transport-bootstrap.md#replacement-safe-remote-physical-authority)
- [Historical bootstrap /1 source-controlled operation construction](transport-bootstrap-v1.md#historical-bootstrap-1-source-controlled-operation-construction)

<!-- Moved from docs/v3/boundary-spec.md:2564-3003 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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

<!-- Moved from docs/v3/boundary-spec.md:3629-3718 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

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
