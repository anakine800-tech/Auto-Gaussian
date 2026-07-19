# Auto-G16 package 4 resource, monitor, and fetch contract

Package 4 is owned by `auto-g16-rtwin-pbs` and is offline by default. It adds
no SSH, PBS, Gaussian, deployment, retry, cancellation, cleanup, or deletion
authority. `/1`, `/2`, and approvals `/6`-`/8` retain historical replay
semantics; every new live submission requires ledger `/3` and approval
`/9`, `/10`, or `/11`.

## Exact resource chain

1. Finalize a closed `gaussian-execution-resource-policy/1` with explicit
   limits for estimated/remaining core-hours, unresolved/active concurrency,
   aggregate cores/memory, and per-job cores/memory/walltime.
2. Collect one `gaussian-batch-qstat-snapshot/1` with `batch-status`. One poll
   enumerates the complete active PBS-user scope. Optional exact job IDs are
   expectations, never a scope filter; zero IDs is the first-job path.
3. Run `resource_efficiency.py build-scheduler-snapshot`. The builder uses the
   `/3` ledger and qstat-reported resources; it never derives resources from a
   molecule, task kind, tier default, or filename. Missing/unknown records,
   unresolved reservations, state mismatch, resource mismatch, and stale or
   malformed evidence fail closed. Only rc=0 with no records proves zero
   active jobs; rc=153 is unknown. Owner conflicts, duplicate blocks/resources
   incomplete parsing, and any warning/non-job text outside exact blocks fail
   closed; multi-node cores are `nodes * ppn`.
4. Run `evaluate-gate` with the exact task, deterministic attempt ID, project,
   input hash, tier, cores, memory, walltime, estimate, policy, ledger, and
   scheduler snapshot. The gate binds both scheduler payload hash and exact
   artifact byte hash/size, plus the `/3` resource-state projection hash and
   revision. Append-only monitor journal entries do not starve an unchanged
   resource gate; task/attempt/resource/accounting changes do invalidate it.
5. Approval `/9`-`/11` binds policy/gate hashes and requested resources. Submit
   replays policy, gate, scheduler artifact and freshness before reservation
   and immediately before qsub. Failure after reservation reconciles the
   attempt as `reconciled_not_submitted`; qsub is not invoked. This includes
   every local intent/consumption/checksum/job-state/verification failure after
   reservation and before the first network command.

PBS `nodes/ppn`, memory, walltime and tier annotation must agree with Gaussian
`%nprocshared`/`%mem` and the resource gate. Any unknown scheduler or ledger
occupancy blocks the gate.

## Monitoring and accounting

One job poll uses one read-only remote snapshot script for qstat, session
process, log size/mtime/tail, whole-log terminal counts, manifest, collection
time and transport status. Timeout, parse failure, conflict, or stale evidence
is `unknown`. Read-only probes alone may retry at most twice with bounded
exponential backoff. qsub, qdel, mkdir, upload, scp, and every other mutating
path are never automatically retried; timeout means outcome uncertain.

Job events and `/3` events append timestamp, source, freshness/age, transport
classification and evidence hash. New observations never overwrite history or
change scientific acceptance.

Fresh successful exact observations reconcile execution state only along the
ledger transition graph and only for the already-bound exact project/job/input.
They never advance `submission_uncertain` or fill a null scheduler reference;
that requires `reconcile-submission` evidence. Timeout/stale/conflict stays
append-only. Repeated
stable interruption proof maps to failed execution state so occupancy is
released, without accepting a scientific result. It requires explicit PBS
record absence, unchanged log metadata, zero whole-log terminal counts, and a
minimum 60-second stable/log-age window. A still-present `R` record is stale or
zombie evidence, never interruption. Whole-log error count has terminal
precedence over normal count when no workflow manifest exists, even if the
marker is outside the 500-line tail.

Completed/failed/interrupted fetch authorization comes from an immutable,
hash-sealed terminal inspection receipt bound to exact project, scheduler job,
input stem/hash, and attempt. Mutable `job.json` status alone is insufficient.

`parse-accounting` accepts common PBS `resources_used` fields. Missing dialect
fields are unknown and duplicates are ambiguous, never last-wins. Only a known
record with one exact parsed PBS job identity, bound to the same terminal
job/attempt/input, may reconcile actual
core-hours. Estimated and actual values, parser identity, source, raw evidence
hash/size and collection time remain recorded. No method/resource change or
retry follows automatically.

## Incremental immutable fetch

The remote allowlist remains exact and excludes scratch, symlinks, and
unrelated files. A prior snapshot file is reusable only after its binding and
remote size/hash match and its local bytes are rehashed. Reuse writes a private
`O_EXCL` temporary file, fsyncs, verifies, and atomically no-clobber publishes;
it never shares an inode with the old snapshot. Changed files alone cross the
two network hops. The new snapshot must contain the complete verified set.
Partial snapshots retain `.fetch-in-progress` and never set `results_fetched`.
`transfer.json` seals its payload, binds the terminal receipt and every
generated artifact hash/size, and the job event records the transfer artifact
hash/size rather than trusting a path.
