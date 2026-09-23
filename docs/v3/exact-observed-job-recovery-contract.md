# Auto-G16 exact observed-job recovery

## Authority and scope

This is the private offline implementation delta for the coordinating task's
2026-09-16 delegated freeze, on original producer commit
`ceff406def65b575babb898d51683c47238c91fb`, tree
`a3dce15ec06c3ac1707f876d0145bfe88d9e8fde`.

The externally retained normative v2 contract is SHA256
`047571852ab6244bba9813a805833e9b1565af81030e9a47f7c028e979cd304b`.
Its delegated freeze/implementation gate is SHA256
`57e5f8bae12f2b343e456d92db441499090bac3d2a7bd1864de9ca4358709b4e`;
the independent v2 closure is SHA256
`e096ef1babedce2d96004771aed4d709f3ea6bde633891c3b6702fa28fc373d6`.
The earlier design draft is supporting history only. Private operational paths,
host observations, job identity and store contents are retained outside Git.

This delta admits one original UNKNOWN submission and one explicitly reviewed
observed job, through a separately installed read-only recovery continuation.
It does not reinterpret the old C2 collect-only exclusion of reconciled jobs.
The original marker-only reconciliation, successful-submission collection,
public Core DDL, operation table, producer/bootstrap, wrapper/loader/prebinding,
scientific input/resources and original approvals remain unchanged.

## Separate fixed authority

`auto-g16-v31-exact-job-recovery-continuation/1` extends the existing private
collection document with `reconciliation`, a closed mapping of:

- `submit_receipt_id`: the original ambiguous native receipt;
- `job_owner`, `server`, `host`: exact reviewed scheduler and machine/boot identity;
- `probe_source`: SHA256 and size of the new read-only source;
- `prior_recovery_authority`: null for the first recovery, or SHA256/size of
  that immutable first continuation in the later installation's pinned evidence.

The original snapshot, source/Q, four physical stores, approvals, prepared
inputs and scheduler script are rebound through the existing fixed Controller.
New source inventory must include both recovery modules and the recovery process
owner. Old Q is predecessor evidence, never qualification of these new bytes.
The current recovery window is finite and independently reviewed; it cannot
change the original submission window. The scope has one reconciliation epoch,
one collection epoch, the exact original job and declared output names.

A later reviewed collection continuation may pin the original recovery authority
to replay its native proof while granting one new collection epoch. It must
preserve original identity, stores and reconciliation fields. Chains are rejected.
The global per-Attempt START record still prevents a second reconciliation read;
a new continuation never resets that consumption. Historical window expiry does
not erase an existing native receipt, and does not authorize a fresh read.

## Read and persistence order

Under the existing cross-process completion guard, reconstruct all original
Core/Transport receipts and preserve the original UNKNOWN outcome. Append a
private `v31-exact-job-recovery-start/1` Observation durably before wire. It binds
the exact request, first continuation digest and entire prior observation prefix.

The new probe contains only read helpers and exact `qstat -f <reviewed-id>`.
Before the query it verifies no-follow ancestors/workspace, original intent
marker, submitted-marker absence, staged hashes/sizes/tokens and machine/boot.
Machine-ID hashing uses the original raw file bytes, including any newline.
It repeats target observations after the query. There is no allocation, stage,
submit, cancel, deletion or marker-writing entrypoint.

The scheduler child has a fixed 10-second bound, 98,304-byte stdout and
32,768-byte stderr caps. The original 30-second outer operation retains
262,144-byte stdout and 65,536-byte stderr caps. The recovery-only process reader
preserves acquired bounded raw bytes, status, code and EOF flags on timeout,
cap, executable/target/local identity drift and post-query failures. Rejected
or incomplete evidence cannot establish identity. Exceeding a cap retains its
bounded prefix with a non-success status; it never claims a complete transcript.

Append `v31-exact-job-recovery-raw/1` before interpretation or promotion.
Even an observation-prefix conflict discovered after wire retains raw before
stopping. Successful proof requires unchanged ordered START/raw provenance;
raw with a drifted history never promotes. Crashes after START stop further reads.
An incomplete Transport/Core pair is not repaired by another read. A complete
native receipt may locally replay its Core reconciliation disposition after a
crash. No new Attempt/intent or submission is permitted.

## Identity and native recovery

Strict Torque parsing accepts one exact header, four-space fields, TAB folds
without added whitespace, and the retained final LF/blank-line format. Duplicate
fields, injected headers, malformed folds, absent/ambiguous/nonzero replies and
conflicting identity fail closed. Match job ID, owner/effective user, server,
queue/resources, scheduler name, all relevant workspace fields, output/error
paths and exact submit arguments. Scheduler Q/R/terminal state is separate from
submission identity; an absent job stays UNKNOWN.

The closed versioned proof references the original ambiguous receipt, request,
expected predecessor-derived identity and persisted raw observation. Persist it
through the existing Transport effect and Core Observation owners, then call
native Core reconciliation. The original UNKNOWN submission receipt/outcome
remain immutable. Fresh restoration admits only this exact native lineage and
replays UNKNOWN separately from its successful reconciliation disposition.

Collection then uses the existing same-job collector, receipt binding, parsers,
Result, capture and replay. A completion receipt naming another job cannot
promote. Receipt-only recovery, scheduler absence as success, fabricated remote
markers and direct database state repair are excluded.

## Validation and remaining gates

Focused acceptance covers parser/identity rejection, partial/EOF failure raw,
pre-query checks, real local read-child execution, native UNKNOWN recovery,
original-history preservation, real process crash boundaries, independent
process/handle contention, fresh-process capture/replay, later continuation and
wrong-job completion rejection. Compatibility checks bind unchanged old producer
and strict paths. Record actual commands, candidate and limitations separately;
this contract does not claim tests have passed merely by listing them.

Offline implementation/review, new read-only seam production qualification,
exact one-shot native application, native completion capture/replay and
scientific acceptance are separate gates. Only the parent coordinates live
operations. This task grants no SSH, qsub, new Attempt, qdel, deployment,
publication, merge or scientific approval.
