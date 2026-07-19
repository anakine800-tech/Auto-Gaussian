# Auto-G16 Gaussian execution-batch governance

`gaussian-execution-batch-review/1` is an immutable human review. Its
`payload_sha256`, `batch_id` and `review_id` become the fixed identity of one
persistent `gaussian-execution-batch/1` ledger. The ledger is mutable only by
locked, atomic, hash-chain-preserving updates. Renaming a file, PBS project or
job; adding an alias; splitting work across files; or resubmitting does not
create a different reviewed batch or reset a counter.

## Scientific-task identity and cap

One `scientific_task_id` is deterministically derived from exactly these
reviewed identities:

- structure;
- chemical hypothesis;
- method/protocol;
- calculation objective; and
- relevant Gaussian input.

Each identity is represented by a SHA-256. A reviewed batch admits at most ten
distinct combinations. Tasks remain counted after submission, queueing,
running, completion or failure. An already admitted identity is idempotent and
does not consume another slot. A valid eleventh identity is deferred with an
operator-visible reason. A requested task ID that does not match its identity
is rejected.

`classify_retry` compares all five fields. Only an exact match is an
`exact_resubmission`; every changed field produces `new_scientific_task` and
requires a new reviewed slot. Classification never authorizes qsub.

## Attempts and accounting

The ledger keeps separate counters for:

1. distinct scientific tasks;
2. physical qsub attempts assumed or observed;
3. estimated core-hours for those attempts; and
4. observed consumed core-hours.

Before any external submitter can issue qsub, it must reserve one attempt with
the exact admitted identity, relevant input hash, a new live-approval hash and
an idempotency key. Reservation is recorded as `submission_uncertain`; this is
intentional. It occupies the task and attempt until read-only evidence
reconciles it as submitted/queued/running/completed/failed or proves
`reconciled_not_submitted`. A second unresolved attempt for the same task is
refused. Replaying the same idempotency key returns the same record. Reusing a
live-approval hash is refused.

Failure diagnosis and retry proposals may be automated outside this ledger,
but neither `execution_batch.py` nor its records can issue qsub, change
chemistry or approve a retry. An exact resubmission still needs the ordinary
fresh input-hash and live-approval replay before its reservation. A scientific
change first needs admission as a new task.

## Locking and audit

Every mutation takes an exclusive sibling lock, revalidates the ledger inside
that lock, applies one change, recomputes counters, extends the event hash
chain, writes a same-directory temporary file with `fsync`, and atomically
replaces the ledger. Tampering, duplicate identities, reused idempotency keys,
stale counters and changed immutable batch identity fail closed.

Admission decisions and attempt state changes retain explicit reasons. The
read-only monitoring summary returns important state/error events immediately
and, by default, a cumulative operator summary after 60 minutes from the
provided prior-summary time (or batch creation). It does not mutate the
ledger, submit, retry, cancel, edit chemistry or expand a search.

This governance does not alter scheduler-zombie authority. The existing
repeated-evidence policy remains the only automatic exact qdel path, applies
only after results are fetched, and never authorizes cancellation or server
file deletion.

## Offline API

The standard-library module is
`scripts/execution_batch.py`. Its CLI exposes only `validate` and read-only
`summary`; reviewed callers use its Python functions to initialize, admit,
classify, reserve and reconcile ledger records. The module imports no network,
SSH, PBS or Gaussian execution client.
