# Runtime safety compatibility

Package-1 runtime hardening remains historically compatible. Package 4 adds a
separate `/3` execution ledger and `/9`-`/11` resource-bound approvals for new
live submissions; it does not rewrite old submission or TS/IRC contracts. It
performs no live action and adds no mutating-command retry path.

## Inspection compatibility

`gaussian-job-inspection/1` remains available for historical replay. New
single-job polls emit `gaussian-job-inspection/2` from one remote read-only
snapshot call. Existing read-only
consumers may continue to read `pbs_record_present` and `process_alive`, but
both are now true three-state values:

- `true`: explicit present evidence;
- `false`: explicit absent evidence;
- `null`: SSH, command or parse failure left the evidence unknown.

The additive fields `pbs_evidence_status`, `process_evidence_status`, return
codes and bounded error summaries make that distinction explicit. Consumers
must not coerce `null` to false. Unknown evidence cannot establish stale,
interrupted, self-purged or zombie state. An incomplete log becomes
`interrupted` only after repeated stable observations plus explicit absence.
Whole-log normal/error counters must both be known integers; counter parse
failure is unknown transport/freshness evidence, never an implicit zero.

`pbs-zombie-diagnosis/1` and `pbs-zombie-cleanup/1` are also retained. Cleanup
adds `qdel_outcome` and `verification_outcome`; consumers that only branch on
`status` remain compatible. `cleared` is narrower: qdel must be successful or
explicitly report `Unknown Job Id`, and the verification qstat must explicitly
report `Unknown Job Id`. Every transport, command and parse failure is
`cleanup_unverified`.
The additive `scheduler_record_evidence_status` preserves `present`, `absent`
or `unknown`; `scheduler_record_present` remains `null` when evidence is
unknown instead of being coerced to false.

`batch-status` makes one read-only qstat call for the complete active PBS-user
scope and emits a closed `gaussian-batch-qstat-snapshot/1`. Optional exact IDs
are expectations, not a filter; rc=0 with zero records is operational, while
rc=153 is unknown. Combine that fresh observation with
the exact `/3` ledger using `resource_efficiency.py build-scheduler-snapshot`;
the offline builder supplies attempt IDs and reviewed resources and rejects
missing, unknown or conflicting records. It never infers resources from task
or molecule type.

Fresh exact monitoring can reconcile execution state. Unknown, stale or
conflicting observations remain append-only. Repeated stable interruption
proof maps only to failed execution state and never accepts science.

## Fetch migration

The old unversioned transfer record and project-wide wildcard copy were unsafe
and are replaced by `gaussian-fetch-snapshot/1`. Direct `fetch` callers must
provide the same exact binding already used by `inspect` and `watch`:

```bash
python gaussian_rtwin_pbs.py fetch \
  --project example --job-id 563.master --input-stem example_cartesian \
  --local-dir /path/to/exact-bundle \
  --output-dir /path/to/new-or-empty-snapshot
```

`watch --fetch` already carries these arguments, so its CLI shape is unchanged.
The Python helper `fetch_results(args, project, output_dir)` is source-compatible
only when `args` supplies `job_id`, `input_stem` and `local_dir`; missing binding
now fails closed.

The output directory may be new or empty. Non-empty, concurrent and partial
targets are rejected instead of merged. After a failed transfer, retain that
snapshot as evidence and choose a new output path. Each attempt also uses a
unique non-overwriting RTwin snapshot path, so no remote cleanup is required.
The exact local job record must already be `completed`, `failed` or
`interrupted`; a live or unknown record cannot be fetched as a final snapshot.
The local bundle and output paths are inspected before resolution; a symlink in
the leaf or any existing ancestor is rejected before snapshot creation or any
transport command.

Successful snapshots contain:

- `server-allowlist.json`: exact project/job/input binding and permitted names;
- `fetch.sha256`: Mac hashes for copied server files;
- `transfer.json`: `gaussian-fetch-snapshot/1`, exact-log selection and all
server to RTwin to Mac hashes;
- `result.json` and any parser outputs generated only after transfer validation.

`--reuse-snapshot` may reuse unchanged allowlisted bytes only after the old
immutable snapshot and its local/per-hop hashes are replayed. Reuse copies into
a private no-clobber file, fsyncs and rehashes it; snapshots never share an
inode. Only changed files cross server to RTwin to Mac, while the new snapshot
remains a complete independently verifiable collection. A failed or partial
copy never sets `results_fetched`.

Only `<input_stem>.log` is analyzed. Scratch, arbitrary logs, unrelated JSON and
other server files are not default fetch content. `job.json.results_fetched`
becomes true only after the snapshot completes and all per-hop hashes match.
