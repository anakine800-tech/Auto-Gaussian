# Environment and failure handling

## Verified path

The working path is Mac OpenSSH → RTwin OpenSSH over Tailscale → server OpenSSH → PBS/Torque 6.1.0 → Gaussian 16 Rev. A.03. The Linux server is not directly reachable from the Mac.

RTwin uses the dedicated server key and alias `gaussian-server`. The Mac uses the dedicated `rtwin` alias. Do not replace either host key silently and do not copy passwords into automation.

## Reviewed server contract

- Host/user: resolved only from the ignored RTwin SSH configuration; never
  publish the private address or credentials
- Work root: `/home/user100/SDL`
- Queue: `batch`
- Resource syntax: `nodes=1:ppn=44`
- G16 root/executable: `/opt/soft/g16`, `/opt/soft/g16/g16`
- Allowed data root: `/home/user100/SDL` only
- Scratch: `/home/user100/SDL/<project>/scratch`; never inherit `/tmp` for Skill-submitted jobs
- Login-shell environment provides `g16root`, `GAUSS_EXEDIR`, and `GAUSS_SCRDIR`

## Failure decisions

- Mac cannot reach RTwin: check Tailscale, then port 22. Do not fall back to storing a password.
- RTwin cannot reach the server: inspect its SSH alias/key and host-key error. Do not install or rotate credentials without explicit approval.
- Per-hop hash mismatch: stop before `qsub`, retransmit once after identifying the bad hop, and verify again.
- SDL containment or symlink check fails: stop. Do not choose another directory, follow the symlink, or bypass `realpath` checks.
- Server project directory is non-empty: stop and preserve it. Use a new project name unless the user explicitly requests a separately audited recovery operation.
- Ambiguous `qsub` result caused by connection loss: query `qstat -f` and search the exact job name before any retry.
- PBS `Q`: report a normal queued state and wait; do not submit another copy, cancel, lower resources, or change the calculation. A 44-core full-node job commonly remains queued while no suitable node is free, but `Q` alone is not proof that the server is full. Attribute the delay to capacity, priority, policy, or another cause only when PBS provides matching reason/comment evidence.
- PBS `R`: inspect the Gaussian log; scheduling alone is not chemical success.
- `Error termination`: preserve the input/log and diagnose the final 80–120 lines before changing resources or chemistry.
- `End of file in ZSymb`: check required blank lines and malformed Gaussian sections.
- Memory failure: compare `%mem` with the 120 GB physical ceiling and current node use; do not increase beyond the server cap.
- Log has terminal evidence but PBS remains `R`: treat one observation as a zombie candidate and monitor for self-purge. Use `diagnose-zombie` for two stable observations; never call `qdel` from the first observation.
- Fetch failure: leave the server directory intact and retry only the transfer into a new local snapshot directory. A partial target is intentionally retained and blocked; never merge into it, delete the sole copy of `.chk` or `.log`, resubmit, or run qdel as recovery.

## Deletion policy

The bundled CLI intentionally has no server cleanup/delete command. Do not delete server files as part of submit, retry, fetch, status, scheduler cleanup, or cancellation. An evidence-gated zombie `qdel` may run automatically; cancelling a queued or running job still requires exact user approval. Neither is permission to remove the project directory. Any future server-data deletion must be a separate task with exact paths, canonical proof that every target is inside `/home/user100/SDL`, a preview of affected files, and a final explicit confirmation.

## PBS zombie diagnosis and cleanup

A scheduler record is cleanup-eligible only after `diagnose-zombie` proves all of the following twice, at least 5 seconds apart:

- the local `job.json` binds the exact project, input stem, remote SDL directory, and PBS job ID;
- results have already been fetched;
- `qstat -f <job-id>` reports the exact expected job name and state `R`;
- the PBS session ID is present but `ps -s <session-id>` reports no process;
- Gaussian has definite terminal evidence, including all expected Link1 normal terminations or an error termination;
- log size and modification time are unchanged.

After all evidence passes, `watch --fetch` or `cleanup-zombie` may automatically issue at most one exact `qdel` and verify the same exact job with `qstat -f`. `cleared` requires both an accepted qdel response (return code zero or explicit `Unknown Job Id`) and explicit post-qdel `Unknown Job Id`. A qdel error, qstat transport/command error, malformed qstat output, or a still-present record is `cleanup_unverified`; absence must never be inferred from empty error output. No per-job confirmation is required for this terminal zombie cleanup. If the record self-purges during diagnosis, issue no `qdel`. Never retry qdel automatically. The operation does not delete or modify any server project file. This standing authorization does not apply to `cancel`, which still requires exact approval for the queued or running job ID.

## Success evidence

For an optimization, require `Normal termination` plus optimization/stationary-point evidence in the log. Report the final SCF energy only when it is read from the completed output. Preserve the PBS job ID, server directory, input SHA-256, log, checkpoint, and manifests.

## State classification

- `queued`: PBS `Q`; the job is waiting for scheduling and is not a failed launch. Absence of a session, Gaussian process, or log is expected before execution begins.
- `running`: PBS `R` and the recorded PBS session process exists.
- `stale`: PBS `R`, session process explicitly absent, log not yet proven stable.
- `confirmed_scheduler_zombie`: two stable observations prove a terminal Gaussian job with a lingering PBS `R` record and absent session process; eligible for one automatic exact scheduler cleanup.
- `completed`: Gaussian log has `Normal termination`; for an optimization also verify optimization/stationary-point evidence.
- `failed`: Gaussian log has `Error termination`.
- `interrupted`: scheduler-record absence is explicit and an incomplete log has stopped changing across repeated observations.
- `unknown`: any required PBS/process evidence is unavailable because of SSH, command or parse failure. `unknown` cannot be promoted to `stale`, `interrupted`, `self_purged` or `confirmed_scheduler_zombie` by empty output.

## Immutable fetch contract

`fetch` and `watch --fetch` bind the exact project, PBS job ID and input stem to
the local `job.json`. The staged `checksums.sha256` names the required uploaded
files; the exact `<input_stem>.log`, declared checkpoint and project PBS output
are the only generated names considered. The server inventory rejects symlinks,
records SHA-256 and size, and copies explicit basenames only. It never uses a
wildcard, descends into `scratch`, or selects the first matching log/manifest.

The RTwin destination has a unique fetch-snapshot ID and refuses overwrite.
The Mac target must be new or empty and is reserved with an immutable binding
marker before network access. Server, RTwin and Mac hashes and sizes must match
before only the exact log is analyzed. `server-allowlist.json`, `fetch.sha256`
and `transfer.json` preserve the allowlist and per-hop evidence. Missing required
files, extra Mac entries, partial transfer, concurrent use or any hash mismatch
leaves `results_fetched` false. See
[`runtime-safety-compatibility.md`](runtime-safety-compatibility.md) for CLI and
schema migration details.

Use `watch` to update local `job.json`, fetch terminal results, produce `result.json`, and automatically clear a repeatedly proven terminal scheduler zombie. Automatic scientific retries are disabled; diagnostics may recommend a separately approved restart but must never submit it automatically.
