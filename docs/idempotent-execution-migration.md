# Auto-G16 idempotent execution migration

This change preserves the package-1 scientific-task cap, stable identity,
server root, no-delete/no-overwrite policy, exact input hash, scientific gates,
and historical approval replay. It does not authorize SSH, PBS, Gaussian,
retry, active cancellation, cleanup, or any TS acceptance change.

## Compatibility boundary

- `gaussian-execution-batch/1` remains valid for package-1 planning and the
  existing v2.5 integration overlay. It is not sufficient for a new live
  submit.
- Package 2 introduced `gaussian-execution-batch/2`; it is now historical
  replay only for package-4 live submission. Run the offline
  `execution_batch.py migrate-v2` command only for an attempt-free `/1` ledger
  or one whose old attempts are all definitively `reconciled_not_submitted`.
  A physical, active, or uncertain legacy attempt fails migration closed.
- New live submit requires `gaussian-execution-batch/3`, created explicitly by
  `resource_efficiency.py migrate-ledger`, plus exact policy, fresh scheduler
  resource snapshot and gate artifacts. No migration itself grants live
  authorization.
- Historical live approvals `/3`-`/8` remain replayable under their
  original contracts. They cannot enter a new submit. New protected successors
  `/9`, `/10`, and `/11` retain the package-2 time/principal/one-use semantics
  and add exact policy/gate/resource binding.
- Existing `job.json` remains the compatible current-state view. New mutations
  are serialized through `job.json.lock`, appended to `job.events.jsonl`, and
  atomically derive `job.json`. A legacy job without an event log is imported
  as the first append-only event on its next mutation.

## Transaction recovery

Submit order is local attempt reservation, immutable intent/approval
consumption, atomic remote project claim, exact upload/hash, one qsub carrying
attempt/input hashes, immutable remote/local receipt, then ledger/job backfill.
A remote project directory must not pre-exist, even if empty. Ambiguous qsub
output never triggers retry.

Use `reconcile-submission` for read-only remote/PBS recovery. It searches the
exact project/job name/input hash/attempt. One unique job backfills the job ID;
zero or multiple scheduler matches remain closed unless the atomic project
directory is absent and therefore proves this transaction never reached qsub.

Active cancellation first atomically publishes `cancellation-intent.json`
before qstat/qdel. The intent is the durable one-shot consumption boundary:
all later cancellation commands refuse qdel, including after transport or
outcome-receipt failure. `reconcile-cancellation` only reports
active/absent/unknown and never qdel.

## Package-4 interface

Every `/2` ledger keeps `gaussian-execution-resource-policy-hook/1` and
`gaussian-execution-resource-gate/1` as historical evidence. Package 4 uses the
explicit `/3` ledger, `gaussian-execution-resource-policy/1`,
`gaussian-scheduler-resource-snapshot/1`, and
`gaussian-execution-resource-gate/2`. Build the scheduler resource snapshot
from one `gaussian-batch-qstat-snapshot/1` observation and the exact `/3`
ledger; absent, unknown or conflicting attempts fail closed. This versioned
chain does not weaken reservation, approval, input or server boundaries.
