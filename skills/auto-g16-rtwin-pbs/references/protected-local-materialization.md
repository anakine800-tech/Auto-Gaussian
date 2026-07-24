# Auto-G16 protected local materialization boundary

Use PR4L only after exact typed PR4K evidence already exists in the same
owner-loaded process.

The bounded owner order is fixed:

1. exact PR4K seal and current replay;
2. exact nested PR4D reservation;
3. PR4F byte-for-byte no-clobber local materialization in the PR4G-derived
   directory;
4. file and directory fsync; and
5. final no-clobber state-record publication.

The result remains `submission_uncertain`. It provides a sealed local state
capability and no effect method. Never treat it as adapter, transfer, qsub,
job-status, result, reconciliation, or scientific-acceptance evidence.

On any failure, stop. Do not overwrite, remove partial files, retry the
reservation, roll back, clean up, migrate, rehash, or backfill. Use separate
read-only reconciliation under its existing authority.

The long-process owner-lifetime gate remains closed. No adapter or external
operation may be connected by this successor.
