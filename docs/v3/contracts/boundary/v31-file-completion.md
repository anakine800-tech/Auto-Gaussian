# Auto-G16 v3 boundary: v31-file-completion

Component of [boundary-spec.md](../../boundary-spec.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [C4 native controller directory guard proposal](v31-controller-guard.md#c4-native-controller-directory-guard-proposal)
- [V31 publisher R4 private offline boundary](v31-successors.md#v31-publisher-r4-private-offline-boundary)
- [V31 same-Attempt collection recovery boundary](v31-successors.md#v31-same-attempt-collection-recovery-boundary)

<!-- Moved from docs/v3/boundary-spec.md:5191-5663 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V31-PBS-COMPAT-FILE-COMPLETION-01 candidate boundary

**CANDIDATE, not an active frozen contract.** OD-32 requires exact-candidate
repository Owner L3 review. This section is the proposed normative delta,
not an implementation status claim. It supersedes only the V31 shared
contract's missing-required-output rule for a trustworthy failed invocation,
and its DO NOT TOUCH restrictions on private successor rendering/acquisition/
completion in this task's allowed paths. Strict/V30 behavior, all public Core,
Observe, Result and Approval schemas, the two-record execution budget, and
Transport operation/protocol vocabulary are unchanged.

### Mode and non-circular execution binding

The initial builder keeps xTB version 2 as its default. Explicit receipt mode
selects private registry key `(xtb, auto-g16-v31-xtb, 3)`. Version 3 retains v2
scientific data/argv/XTBPATH semantics and adds exactly
`completion_mode = receipt-on-absence-v1` to closed `program_data`; it accepts
no other value. Historical versions reject this field. The two public record
shapes stay unchanged; no new public completion record or extension bag exists.
Receipt mode supports the existing `single-point` and `optimize` operations;
it is not selected by detecting scheduler trouble. Review shows the expanded
mode, operation, inputs, outputs, resources, workspace and wrapper meaning.
Changing them requires a fresh Attempt and fresh approvals, never re-signing
an already consumed Attempt. Old serializers/IDs/vectors remain byte exact.

Define a private pre-execution binding B as the existing snapshot identity
payload without `scheduler_artifacts`, plus exact keys `binding_schema`
(`v31-completion-prebinding/1`), `wrapper_source_sha256`, and
`wrapper_source_size_bytes`. Thus B includes Attempt, plan/revision, spec
ID/hash, Project binding, resolved resource/profile IDs, workspace ID and cwd.
Its hash uses existing Execution `semantic_sha256`, with no final snapshot or
effect ID. Source is a fixed source-controlled wrapper, independent of B.
Render one deterministic scheduler artifact from B, its exact closed spec,
resolved resources/profile and that source; the normal final snapshot then
binds these scheduler bytes and derives the normal effect/snapshot IDs.

Existing trusted bootstrap, after reattesting all staged inputs and scheduler
bytes, exclusively publishes `.auto-g16-v31-submit-intent` **before qsub**.
Its existing exact two keys are final `program_execution_snapshot_id` and
`effect_intent_id`. The wrapper reads that marker descriptor-relative/no-follow
as data, before program launch, and retains its exact bytes/file identity.
No marker content selects a command. The later `.auto-g16-v31-submitted` is
not a wrapper prerequisite: qsub can start the job before that marker exists.
`PBS_JOBID` is a scheduler-provided claim, checked against the controller's
persisted exact confirmed job authority before any conclusion.

The resulting DAG is B -> scheduler bytes -> final snapshot -> submit marker
-> receipt. Controller independently rebuilds B, scheduler bytes and final
snapshot from the already approved authority, then compares both IDs from the
receipt and marker, the retained staged scheduler identity, and exact durable
job/workspace bindings. A digest copied into a file does not prove this chain.
No self-containing snapshot, post-approval scheduler rewrite or new sidecar
submission command is permitted. Existing one-XYZ input limit remains; receipt
serialization uses ordered tuples for all inputs/outputs so no scalar-input
assumption can silently drop a future declared member.

### Publisher trust and wrapper ownership

Trust starts with the currently qualified manifest-v3 bootstrap and its exact
resolved profile/runtime identities, the existing durable Core plus private
Transport predecessor chain, fresh 0700 Attempt workspace, staged file tokens,
and the scheduler artifact checked before the sole qsub. It never starts from
receipt contents. The candidate renderer embeds fixed wrapper source in the
one scheduler script and launches it with the manifest-bound `server_python`
using `-I -S -B -c`, fixed arguments and no ambient interpreter lookup. The
wrapper invokes exact xTB argv directly (`shell=False`), using the v2 closed
program environment; PBS_JOBID is read only as metadata. No caller code,
interpreter path, environment map, pipeline or plugin is accepted.

Wrapper source identity is part of B and the scheduler bytes. Existing
manifest-bound Python/xTB identities and runtime-data authority are checked
before launch and after program termination. Wrapper publication qualification
must additionally establish descriptor-relative no-follow behavior, exclusive
single publisher, managed descendant termination, and filesystem atomic-link
semantics on the actual target. Offline tests do not grant that qualification.
For this first offline implementation, a production receipt-mode driver is
unconditionally unavailable: construction with any real RTwin/profile target
fails `publisher-not-qualified` before any driver call or effect. Only the
existing qualified synthetic driver path can exercise version 3. Enabling a
real publisher requires a later separately reviewed deployment/qualification
contract and exact Owner gate binding wrapper/source, manifest, interpreter,
xTB, target filesystem and every eligible execution host; the generic current
manifest is insufficient. That later contract must define the qualification
record and its trusted ingestion before removing this hard stop. This task
neither creates such a record nor leaves an unchecked boolean override. The
same guard applies when evaluating purported production completion evidence.
OD-18's exclusions (malicious same UID, privileged/kernel/filesystem or trusted
bootstrap compromise) apply explicitly; this is no cryptographic attestation
against those actors. Program and wrapper are trusted source/runtime actors
within that model. File hash, chmod and finished_at prove neither authenticity
nor physical immutability by themselves.

The wrapper retains workspace/parent descriptors and identities throughout.
Before starting xTB it acquires a fixed exclusive create-new launch marker
`v31-completion-launch.lock` (never deleted); an existing marker or any existing
reserved log, receipt or pending receipt path fails closed with no invocation.
The log is opened once with O_CREAT|O_EXCL|O_NOFOLLOW, never shell truncation.
The qualified Linux wrapper uses a child subreaper and waits for the direct
child and every adopted descendant to be reaped before publication; failure
to establish subreaper ownership, wait failure, descendants still alive, or an
unsupported platform produces no receipt. Threads end with their process.
It never cancels a scheduler job, kills unrelated processes or cleans files.
Process waits have the Attempt's bound walltime as ceiling; expiry leaves no
receipt, never a manufactured program exit. Arbitrary daemon escape or
external writers are outside qualified execution and cannot be accepted.

No `set -e`, EXIT trap, tee or pipeline determines the program exit. The direct
child wait status is the only exit source: `exited` carries rc 0..255;
`signaled` carries signal 1..64 and rc null. Launch failure, wrapper signal or
crash before publication, metadata/input/output hash failure, required file
close/fsync failure and failure before atomic publication produce **no valid
receipt**, even if a program rc was observed. They
are not encoded as a program rc. A direct-child signal can be reported only if
the wrapper survives and completes the same validation and publication steps.
The wrapper's PBS exit is rc for `exited`, 128+signal for `signaled`; an internal
wrapper failure has no trustworthy receipt and cannot acquire completion
through its shell exit code.

After all managed writers terminate, close/fsync the log, reattest inputs,
program, marker and workspace, and collect metadata for each declared output.
Safely confirmed required or optional absence is recorded for every exit kind,
including rc=0; it never prevents publication by itself. Thus rc=0 plus missing
required output can reach FAILED/output-incomplete. Any present output must be
safely readable/hashable; metadata failure is never encoded as absence. Write the complete canonical receipt to
`v31-completion.pending` with create-new no-follow, flush/fsync and close;
reopen/recheck that exact object and workspace, then publish by descriptor-
relative hard link to `v31-completion.json` with no replacement. This link is
the sole publication linearization point; all required validation, file fsync
and close precede it. No post-link directory-fsync success is a condition for
receipt validity. Both names are retained forever. No ordinary overwrite rename,
unlink, rm, truncation or cleanup is allowed. Concurrent publishers lose at
the launch marker; a preexisting final/pending file stops rather than replaying
publication. A crash before link leaves only pending evidence; after link,
publication is not revoked by a wrapper crash. An uncertain link outcome is
not fabricated into an exit or a retry: later separately authorized exact
read may find a complete visible final object and apply all source/capture
checks; otherwise completion is UNKNOWN. No permanent server immutability or
power-loss retention is claimed. Local durable capture separately retains the
observed evidence. Unsupported atomic-link behavior fails qualification.

### Closed receipt bytes and evidence types

Receipt schema is `auto-g16-v31-program-completion/1`. Encoding is UTF-8,
canonical JSON sorted keys, compact separators, ensure_ascii=false,
allow_nan=false, followed by exactly one LF, maximum 65536 bytes. Reject
BOM/NUL, duplicate keys at any depth, extra/missing keys, trailing data,
noncanonical numbers, floats, booleans in integer positions and unknown
versions. JSON arrays map to ordered tuples. All SHA-256 values are lowercase
64 hex; positive sizes except present outputs may have zero size; IDs are
nonempty exact strings, names use existing portable-name grammar. No path
normalization repairs invalid evidence.

Exact top-level keys are:

- `schema`, `pre_execution_binding_sha256`, `attempt_id`,
  `program_execution_snapshot_id`, `effect_intent_id`, `job_id`,
  `workspace_binding_id`, `remote_workspace`, `workspace_physical_token`;
- `program_execution_spec_id`, `program_execution_spec_payload_sha256`,
  `program_kind` (xtb), `adapter_id`, `adapter_contract_version` (3),
  `operation` (single-point or optimize), `completion_mode`;
- `wrapper_source_sha256`, `wrapper_source_size_bytes`,
  `submit_marker_sha256`, `inputs`, `outputs`, `termination`, `finished_at`.

`inputs` contains every spec input in declaration order, each with exactly
`logical_role`, `portable_name`, `format`, `size_bytes`, `sha256`. Reject
missing/extra/reordered/duplicate members and all collisions among input,
scheduler and reserved metadata names. `outputs` contains each program output
in required-then-optional declaration order, each with exactly `logical_role`,
`portable_name`, `format`, `presence`, `size_bytes`, `sha256`. Presence is
`present` or `absent`; absent means both size/hash null, never a failed stat.
Every present member must match captured size/hash and spec cap. Reserved
completion metadata is not a program output and is not in this list.
`termination` has exactly `kind`, `returncode`, `signal`: exited means integer
rc and null signal; signaled means null rc and integer signal. `finished_at`
is canonical UTC with microseconds and Z, display-only, never ordering proof.

Receipt reads use an internal fixed declaration (role `completion-receipt`,
name `v31-completion.json`, format `json`, cap 65536) derived only for version 3.
Extend the existing exact declaration checks to this one reserved metadata
file, not to paths suggested by file contents. Program output tuples remain
unchanged. The same existing STAT/FETCH operations and dual-source persisted
receipts enforce containment, tokens, bounds and exact job authority.

A private closed `Observation` data vocabulary may record completion reduction
under observation_type `program-completion-assessment/1`; it is not a new
public record, transport operation, scheduler axis, Result or effect receipt.
Exact data keys: `schema` (same string), `attempt_id`,
`program_execution_snapshot_id`, `effect_intent_id`, `job_authority_id`,
`completion_mode`, `epoch_id` (null before an opening absence),
`evidence_observation_ids` (ordered unique exact IDs), `evidence_result_id`
(null unless the closed byte bundle exists), `observation_prefix_sha256`,
`verdict` (SUCCEEDED/FAILED/UNKNOWN), `diagnostic`,
`capture_authority_id` (null unless complete), `receipt_sha256` (null if no
valid captured receipt). Identity uses existing Execution semantic_id with
domain `program-completion-assessment`; replay rechecks underlying evidence,
never trusts the assessment alone. Its diagnostic is exactly one primary
code from the priority table below, plus `publisher-not-qualified` for the
production stop. No free-text authority or secondary arbitrary code exists.

Durable bytes use existing Core `Result` with
`result_type = program-completion-evidence/1`, explicitly an unparsed private
execution evidence carrier, not a scientific Result parser outcome. No new
public record or schema is introduced. Exact data keys: `schema` (same
string), `attempt_id`, `program_execution_snapshot_id`, `effect_intent_id`,
`job_authority_id`, `epoch_id`, `inputs`, `captured_files`. Its `result_id` is
Execution semantic_id under domain `program-completion-evidence` over the
complete data mapping; byte content participates in identity.

Each input member has exactly `logical_role`, `portable_name`, `format`,
`size_bytes`, `sha256`, `content_base64`, `stage_observation_id`. Inputs remain
in spec declaration order and must close to both spec bytes and the exact
persisted STAGE receipt. Each captured-file member has exactly `logical_role`,
`portable_name`, `format`, `presence`, `size_bytes`, `sha256`, `content_base64`,
`stat_observation_id`, `fetch_observation_id`, `restat_observation_id`. Files
are the reserved receipt first, then required and optional program outputs in
declaration order. Absent members have null size/hash/content/fetch ID and
exact initial/final absent STAT IDs; present members have exact STAT/FETCH/
re-STAT source IDs and canonical padded RFC4648 base64 for immutable bytes.
The receipt cannot be absent in this bundle. Recompute all bytes/hash/size/
cap/source and physical-token associations; a self-consistent Result ID alone
gives no provenance. Unknown/duplicate fields or members reject at any depth.

Input bytes cannot be recovered from a digest: the authorized local caller
provides the exact original input bytes to capture, verified against spec and
persisted stage authority, then included in this bundle. They select no new
read path. Missing bytes make closure UNKNOWN/acquisition-unknown. Cap each
input and program output at the lesser of its declared size/cap and 64 MiB;
receipt at 65536 bytes; cap the complete canonical bundle at 384 MiB including
base64. These bounds suffice for the current one-input/two-output adapter;
exceeding them is a rejected candidate, not truncated evidence.

Persist the bundle through public append_result and re-read/verify it through
results_for_attempt **before** appending a final assessment or advancing Core.
Assessment references that exact Result ID. Corrupt/missing/spliced stored
bytes give UNKNOWN/evidence-conflict and no transition/promotion. Exact crash
replay consumes these local bytes, making zero remote reads. Core/Transport
FETCH receipt shapes remain unchanged; neither in-memory capture nor hash-only
receipt is claimed to be durable byte storage. Scientific consumers must
reject this unparsed result_type as an acceptance input.

### Acquisition, ordering and final reduction

Core UNKNOWN continues to mean uncertain submission and must first reconcile
through the existing exact confirmed-job path. Completion UNKNOWN below is a
private assessment; it leaves SUBMITTED/RUNNING unchanged. No Core lifecycle
or schema migration is proposed. In receipt mode `_apply_program_scheduler_disposition`
may still advance RUNNING but never terminalizes from scheduler evidence.
Strict keeps its existing terminal/capture semantics.

For a submitted/reconciled exact job, retain every raw scheduler observation
before parsing and preserve known/absent/unknown distinctions. A **fresh exact
absent** observation opens a bounded evidence epoch, not completion authority.
The epoch is a private derived value, no additional persisted record. Its ID
is semantic_id domain `program-completion-epoch` over exactly `attempt_id`,
`program_execution_snapshot_id`, `effect_intent_id`, `job_authority_id`, and
`initial_absence_observation_id`. A later explicit collection gets a new
opening observation and epoch; reuse of the same opening is exact local
replay only. Assessment, byte bundle and success proof must name the same ID.
Read receipt via STAT/FETCH, verify publisher chain and closed binding before
interpreting termination, then collect exact required/optional output evidence.
Stable capture uses before/after tokens, sizes and byte digests; retain bytes,
re-stat each present file after the complete set, and require unchanged token
(including mtime/ctime), not just equal hashes. Re-stat absent members as
absent. Recheck the receipt too. One final exact scheduler query must be absent.
All these receipts and both absence observations must be in Core append order
inside one epoch. No timestamp comparison or caller-chosen newest record can
replace this ordering. Only exact current persisted job/profile authority
allows reads; receipt file contents grant zero read/command authority.

`_require_pre_capture_success` remains the strict helper. Version 3 uses an
absence/evidence gate that requires no SUCCEEDED state. Final reduction runs
only after capture/closure and append-only assessment persistence; only then
may existing Core advance_attempt apply SUCCEEDED/FAILED.

All legal version-3 scheduler/capture/reduction/replay entries share one
nonblocking physical single-owner guard in the existing private
ProgramTransportStore, on a retained no-follow descriptor of its exact bound
database inode, using POSIX flock(LOCK_EX|LOCK_NB) plus a nonblocking in-process
lock. Reattest path/parent/store identity before and after acquiring; lock
failure yields a boundary error with zero driver calls and zero epoch writes.
The descriptor is never unlinked, truncated or recreated for locking. The
lock is released by close/OS on crash; this is not a cleanup/retry mechanism.
A private held-lock token is passed through internal calls to avoid nested
acquisition. Every legal writer for that receipt-mode Attempt participates;
bypassing this Execution owner with direct Core/Transport writes is an
unqualified composition and cannot be used for a completion claim.

Under the same held guard, reload the entire matching dual-store evidence
prefix, open/collect/close the epoch, persist/re-read the byte bundle, append
assessment, recheck its exact prefix, and advance Core before releasing. No
Core private SQL/transaction access or public API/schema change is allowed.
The guard serializes existing public calls, not a claim of one cross-store
SQLite transaction. Reopen/crash replay first reacquires the guard and
revalidates current full history. Only an identical fully bound assessment
whose prefix has no intervening invalidator may finish its pending Core
transition; otherwise append UNKNOWN or stop with a boundary error. Never
blindly advance from a saved assessment, automatically recollect, or resubmit.
Capture re-attestation selects exact STAT/FETCH IDs per epoch; it does not
require a file to have exactly one STAT in all historical observations.

Apply this priority table after exact persisted job authority is established:

| Evidence | Receipt-mode verdict / primary diagnostic |
| --- | --- |
| malformed/foreign authority, corrupt history, changed publisher/runtime/input/receipt/output identity, conflicting epochs or scheduler/receipt | UNKNOWN / evidence-conflict |
| any acquired newer Q/R/H/E (including mapped W/B/S/T), even with receipt | UNKNOWN / scheduler-active |
| acquisition error, timeout, truncation, absent/unknown ambiguity, final query unknown | UNKNOWN / acquisition-unknown |
| latest scheduler terminal but not confirmed absent | UNKNOWN / awaiting-absence |
| exact absent, receipt missing | UNKNOWN / receipt-missing |
| exact absent, receipt malformed/unsupported/untrusted | UNKNOWN / receipt-invalid |
| exact absent, valid trusted nonzero rc or signal, safe metadata/capture closure for every present output | FAILED / program-nonzero or program-signaled |
| exact absent, rc=0, trustworthy missing required output | FAILED / output-incomplete |
| exact absent, rc=0, present outputs captured but operation closure fails | FAILED / output-invalid |
| exact absent, rc=0, complete stable capture and operation closure | SUCCEEDED / completed |

Within the first row, trust/binding is evaluated before any rc. Within errors
of equal priority, preserve evidence order and choose the first offending
member. Unknown receipt/metadata publication is never diagnosed as nonzero rc.
A failed program may have absent required outputs; a stat/hash/fetch failure
for a present output remains evidence failure, not absence. Optional absence
is explicit and does not fail success. Early UNKNOWN assessments carry only
the acquired evidence IDs, never fabricated capture/receipt identities.

All exact terminal scheduler observations already acquired for this Attempt
must agree with each other and with the wrapper's specified PBS exit mapping;
any disagreement, missing trustworthy exit value or impossible ordering (active
observation after terminal/accepted completion) blocks reduction. Terminal=0
with failed output closure is output failure, not an exit contradiction.
Terminal observations never substitute for either absent boundary in this
mode. A query failure parsed as unknown does not become terminal evidence.

Replay with the exact same evidence IDs is idempotent and makes zero driver
calls. New explicitly authorized read epochs append evidence; no background
poll/retry loop is introduced. A later contradictory active/terminal/file
observation or physical drift appends UNKNOWN/evidence-conflict and prevents
all subsequent promotion, retaining an earlier terminal Core state/history
without rollback. A later query unknown gives UNKNOWN/acquisition-unknown;
it cannot silently reuse an earlier success for a new promotion. Absent
consistent rechecks can attest the same frozen capture. No same-ID payload
replacement or retry/recovery-child authority follows any verdict.

`observation_prefix_sha256` is Execution semantic_sha256 over the ordered
tuple of every public Observation for this Attempt strictly before the
assessment being appended. Each member is exactly `{observation_id,
attempt_id, observation_type, data}`. Core append order, not lexical IDs or
timestamps, determines the sequence. Include all types and prior assessments;
exclude the new assessment itself to avoid self-reference. The assessment's
evidence IDs select the epoch's relevant receipts inside that same prefix;
foreign, missing, duplicate or out-of-order references reject.

`_assert_program_terminal_success_authority` retains strict `/1`. Receipt-mode
success has an exact private `/2` payload: `schema` =
`program-terminal-success-authority/2`, `attempt_id`,
`program_execution_snapshot_id`, `effect_intent_id`, `job_authority_id`,
`completion_mode`, `epoch_id`, `assessment_observation_id`,
`evidence_result_id`, `capture_authority_id`, `receipt_sha256`,
`initial_absence_observation_id`, `final_absence_observation_id`,
`observation_prefix_sha256`. Its returned mapping additionally contains only
`program_terminal_success_authority_id`, derived by Execution semantic_id
under existing domain `program-terminal-success-authority` over that payload.
The schema discriminator separates `/1` and `/2` identities. Prefix hash is
exactly the assessment's pre-assessment prefix hash above, not a new snapshot
of arbitrarily selected observations. It has no `terminal_scheduler_state`
or synthetic exit_status. Re-attestation reloads current complete history
under the guard, checks the original prefix and all later matching evidence,
including later contradiction/unknown assessments, before accepting proof.
Any downstream consumer that only understands `/1` rejects `/2`; xTB-to-CREST
seed promotion remains strict-only in this first implementation. Execution
completion therefore cannot silently enable CREST or scientific acceptance.

### Operation closure and dependency direction

The version-3 adapter checks captured bytes only, after provenance validation.
For single-point it requires exact `program-log/xtb.out/text`, nonempty UTF-8
text with no NUL, under its declared cap. For optimize it additionally requires
exact `optimized-geometry/xtbopt.xyz/xyz`: a positive integer atom-count line,
one comment line, exactly that many element/three-finite-coordinate rows and
no nonblank trailing content; atom count and ordered element identities must
match the exact input XYZ. No extra columns or NaN/Inf are accepted. Optional
geometry on a single-point Attempt, when present, must satisfy the same shape.
Missing roles, duplicate/colliding names or mismatched operation fail. These
checks establish declared-output closure, not energy validity, SCF or geometry
convergence, chemical identity/stereochemistry acceptance or minimum status.
Those remain separate scientific parse/review gates. Historical synthetic
`normal xtb` bytes are not advertised as scientific evidence.

Reuse the current private Execution-owned successor composition as the narrow
existing exception to the general dependency sketch; do not introduce a new
reverse dependency. Execution owns mode, wrapper derivation, assessment and
Core transitions. Transport retains only fixed request validation, physical
no-follow acquisition and raw evidence. It imports no completion evaluator,
Observe, Result, ScientificValidation or Review. The pure adapter output check
stays private to Execution; public Result/Observation records carry evidence
through existing APIs. No new service, transport hop/operation, public Result
schema, parser framework or scientific rule is added. Deferred consumers fail
closed on the unsupported completion authority version.

### C3 rendering-material supplement candidate

**CANDIDATE / OWNER REVIEW PENDING.** This closes a C2 input-availability gap:
`ResolvedServerProfile` retains runtime digest/size, not manifest bytes. No
existing digest can recover an interpreter path or an xTB file inventory.
Only this derivation delta changes; all C2 safety, receipt schema, qualification
hard stop, output closure, allowed paths and two-record budget remain intact.

Only version 3's private snapshot builder accepts optional keyword
`completion_rendering_material`; version 3 requires it, historical versions
reject any non-null material. It is an immutable closed mapping, not a new
public class or record. Exact fields are `schema` =
`v31-completion-rendering-material/1`, `resolved_server_profile_id`,
`deployment_manifest_base64`, `xtb_runtime_data_manifest_base64`.

A pure private builder obtains only the two exact existing runtime_contents
names `transport-deployment-manifest-v3.json` and
`xtb-runtime-data-manifest-v1.json` from an existing non-secret ServerProfile.
Resolve that current profile through the existing public resolver and require
complete equality with the selected ResolvedServerProfile. Parse deployment
bytes using the existing manifest-v3 canonical JSON grammar; normalize xTB
manifest bytes with Execution's existing `_canonical_xtb_runtime_data_manifest`.
Compare each resulting byte string's size/SHA-256 against the corresponding
resolved runtime identity before constructing the material. No separate
interpreter path argument, environment lookup, hash-to-path registry or
Transport driver's later private profile supplies missing information.

Use canonical padded RFC4648 base64 for the two verified byte strings; each
decoded manifest is bounded to 1 MiB, and the complete material JSON to 3 MiB.
Use the C2 canonical JSON rule, including exactly one final LF and recursive
duplicate/unknown-key rejection. Missing, wrong version, noncanonical data,
extra field, profile drift, hash/size mismatch or oversized content rejects
snapshot preparation and replay before any effect.

The single scheduler artifact keeps exactly its existing six fields
`logical_role`, `portable_name`, `format`, `sha256`, `size_bytes`, `content_utf8`.
Its content has fixed first lines `#!/bin/bash`,
`# auto-g16-v31-scheduler/2`, and
`# completion-material-base64: ` followed by canonical base64 of the complete
canonical material JSON. There is exactly one such data line, at line 3. It is
not executable text. No new field is added to either public execution record.

C3 uses `binding_schema = v31-completion-prebinding/2` and adds exactly
`rendering_material_sha256` to C2's B. This is Execution semantic_sha256 over
the closed material mapping. Render the remaining script from the verified
material, exact spec, resources/profile, cwd and fixed wrapper source. The
final snapshot continues to bind the complete resulting scheduler bytes.

Snapshot identity verification extracts only that fixed data line, checks all
material bytes against the embedded resolved profile, derives interpreter and
runtime-data entries again, recomputes B and the entire scheduler artifact,
and requires exact byte equality. A data-line claim or script hash alone never
supplies command authority. Reopening needs neither a mutable profile object
nor process-local cache. The acyclic order is verified material/profile -> B
-> script -> final snapshot -> pre-qsub marker -> receipt; neither the material
nor B contains the final snapshot/effect ID or script hash.

Execution's allowed private completion module EXTRACTS the manifest-v3 closed
shape and trust-root validation semantics from the baseline Transport parser
(`auto_g16/transport/_driver.py`, `_parse_deployment_manifest`, manifest-v3
branch), without importing Transport or invoking its resolver/driver. Keep
exact top-level keys, exact five trust-root names and closed per-root fields;
derive `server_python` only from that validated manifest, including path,
expected size/SHA, platform and attestation mode. This is a pure projection of
already profile-bound bytes, never deployment or publisher qualification.
Use the existing Execution xTB manifest validator for the ordered data list.
No general parser, plugin, additional environment or public API is introduced.

New completion tests explicitly construct synthetic profile and manifest
content, put it into runtime_contents before resolving, and derive material
through the same checks. Existing LaneAFixture and strict vectors are unchanged;
no missing fixture identity is silently invented or called production-qualified.
Real receipt-mode driver construction/evaluation still fails
`publisher-not-qualified`, exactly as C2 requires.
