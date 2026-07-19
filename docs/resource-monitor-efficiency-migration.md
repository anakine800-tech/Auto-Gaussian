# Auto-G16 package 4 migration

This is a versioned, fail-closed migration. It grants no live authorization.

- Preserve `gaussian-execution-batch/1` planning and `/2` idempotent records as
  historical evidence. Run `execution_batch.py migrate-v2`, then offline
  `resource_efficiency.py migrate-ledger ...` to create `/3`.
- Existing `/2` attempts migrate as `historical_unbound_v2_replay_only` and
  cannot satisfy a new resource gate while unresolved.
- Approvals `/6`-`/8` remain replayable only under their old contracts. New
  generic, open-shell minimum, and open-shell family-stage submits require
  closed approvals `/9`, `/10`, and `/11`, respectively.
- New submit additionally requires policy `/1`, scheduler snapshot `/1`, gate
  `/2`, exact tier/cores/memory/walltime CLI binding, and a `/3` ledger. The
  live approval scope binds policy and gate hashes.
- `/3` has a separate hash-bound `resource_state_revision`. Append-only
  same/unknown/conflict monitor evidence advances the audit-ledger revision but
  does not invalidate another already reviewed gate; any task, attempt state,
  resource, estimate, or accounting change advances the resource revision.
- Monitoring schema `/2` is structured and freshness/transport aware. It is
  evidence only and never changes a scientific conclusion.
- Fetch snapshot `/1` stays compatible. Incremental reuse is additive and
  produces a complete private snapshot; old snapshots are never modified.

Required offline sequence:

```bash
python skills/auto-g16-rtwin-pbs/scripts/resource_efficiency.py migrate-ledger ledger.json \
  --migrated-at 2026-07-19T10:00:00Z --source reviewed-package4-migration
python skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py batch-status \
  --job-id 123.master --job-id 124.master > batch-qstat.json
python skills/auto-g16-rtwin-pbs/scripts/resource_efficiency.py build-scheduler-snapshot \
  ledger.json batch-qstat.json --snapshot-id poll-1 --max-age-seconds 120 \
  --output scheduler-resource-snapshot.json
```

`batch-status` always enumerates the complete active scheduler-user scope in
one read-only call. Optional IDs only assert expected ledger jobs. Omit them
for a brand-new ledger; only rc=0 with no records proves zero active jobs.
rc=153, partial parsing, warning text outside exact job blocks, duplicate
records/resources and owner conflicts are unknown. Multi-node requests count
`nodes * ppn`.

Fresh successful exact monitoring may reconcile execution state. Timeout,
stale and conflict evidence remains append-only. It cannot advance
`submission_uncertain` or bind a null scheduler reference; only the exact
`reconcile-submission` chain may do that. Repeated stable interruption
proof maps to failed execution state to release occupancy, without scientific
acceptance or automatic retry. Interruption needs explicit scheduler absence,
stable log identity, no whole-log terminal marker, and at least a 60-second
stable/log-age window. A still-present stale PBS record never proves
interruption. Whole-log normal/error counts determine terminal state even when
the marker lies outside the 500-line tail.

After reservation, immutable intent/approval-consumption publication, checksum
rewrite, local job update, and verification remain inside the pre-network
transaction. A proven local failure reconciles `reconciled_not_submitted` and
releases the budget; only a failure of that ledger reconciliation remains
uncertain.

The migration and builders are offline/read-only contract operations. Running
unit tests does not authorize or invoke SSH, PBS, Gaussian, deployment, qsub,
qdel, upload, or cleanup.
