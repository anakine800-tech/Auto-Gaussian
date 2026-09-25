# V31 Gaussian qsub file carrier contract

`V31-GAUSSIAN-QSUB-FILE-CARRIER-01` is a narrow successor supplement to
`V31-GAUSSIAN-SHORT-ENTRY-01` and `PHYSICAL-HANDOFF-01`. It changes only the
handoff transport at the qsub boundary. The reviewed short PBS entry, startup
payload, derived config, submit-intent marker, Gaussian wrapper, scientific
input, resources, output grammar, completion authority and no-retry rules stay
in force. Earlier Attempts and their evidence remain immutable.

## GQF01 — Attempt-local carrier

The launch carrier is canonical JSON with schema
`auto-g16-v31-gaussian-launch-handoff-auth/1`, capped at 65,536 bytes. The
submit owner publishes it as `v31-launch-carrier.pending` and
`v31-launch-carrier.json` using exclusive 0600 creation, complete write, file
fsync, a no-replace hard link, directory fsync, same-owner regular-file checks
and exact identity/readback checks. Existing names stop before qsub. There is
no environment carrier and no fallback to one.

## GQF02 — loader physical binding

The snapshot binds an immutable `gaussian-entry-template.pbs`. After publishing
the carrier, the submit owner performs one qualified substitution into that
template and exclusively publishes `gaussian.pbs.pending` plus
`gaussian.pbs`. The substituted argument is canonical base64 of the carrier's
exact path, SHA-256, size, device, inode and physical token. No caller-provided
source or shell fragment is accepted.

The resulting fixed loader first decodes that carrier pin from its own spooled
argument, then opens both carrier names from the retained scheduler working
directory with no-follow/nonblocking reads. Both names must be regular 0600
files owned by the current user, have exactly two links, and resolve to the
same stable device, inode, size, mtime and ctime. The loader retains both file
descriptors, parses only the exact canonical bytes, binds their SHA-256 and
size to the entry pin, and verifies the carrier's workspace physical token
against the actual retained working directory before reading the handoff or
publishing any startup stage. It also retains the final entry and invocation
start pairs and verifies that the final entry is exactly the qualified template
substitution. Coordinated same-byte replacement of carrier and start, a missing
link, a symlink, mode drift or content drift refuses startup and grants no
completion authority.

## GQF03 — direct qsub argv

The only qsub argument vector after the qualified executable path is:

`-d <exact Attempt workspace> -l nodes=1:ppn=<cores>,mem=<memory_mb>mb,walltime=<seconds> -q batch gaussian.pbs`

The vector contains neither `-v` nor `-V`. qsub receives the existing fixed
four-variable environment allowlist only. This is the direct argument shape
used by the accepted 709 submission boundary; the historical evidence is a
compatibility basis, not evidence for this new candidate or a new live result.

## GQF04 — pre-invocation record

After carrier publication and immediately before the sole qsub call, the same
submit owner publishes `v31-qsub-invocation-start.pending` and
`v31-qsub-invocation-start.json` with the same immutable publication protocol.
The closed record binds the exact Attempt, snapshot, effect, handoff
pre-authority ID, carrier path/hash/size/device/inode/physical token, direct raw
argv and its hash, fixed environment allowlist and creation time. The loader
opens both names, retains them, and validates this record against the carrier
object it already holds and the resource-derived direct argv.

The start record also binds the final `gaussian.pbs` hash and physical identity.
It is evidence that the submit owner reached the immediate
pre-call boundary. It is not evidence that qsub was called or accepted a job.

## GQF05 — post-qsub receipt

The qsub call retains its existing 30-second child deadline. Its surrounding
effect retains the separate receipt-persistence margin. A `finally` path
publishes `v31-qsub-launch-carrier-receipt.pending` and
`v31-qsub-launch-carrier-receipt.json` for every returned, rejected, timed-out
or interrupted invocation observed by that process. Receipt schema `/2` binds
the start-record ID, carrier descriptor, exact argv and environment, captured
stdout/stderr, return code when available, invocation status, outcome and job
ID only when unambiguous.

Only return code zero, empty stderr and one canonical portable job ID line is
`SUCCEEDED`. A nonzero returned code is `FAILED`. Timeout, interruption,
ambiguous output or missing durable receipt is `UNKNOWN`. `FAILED` or `UNKNOWN`
never authorizes another qsub call for the Attempt. A host crash or loss before
receipt fsync remains `UNKNOWN`; the contract cannot claim a receipt that was
not durably published.

## GQF06 — submitted marker and completion separation

The existing `.auto-g16-v31-submitted` marker is written only after an
unambiguous qsub success and retains its existing snapshot/effect/job fields.
Carrier, start record, post receipt and scheduler state are launch evidence;
none is Gaussian completion authority. Completion still requires the frozen
Attempt-local completion receipt, exact outputs and Gaussian-specific normal
termination checks.

## GQF07 — compatibility and qualification

Adapter contract version 4, Q5, material `/6`, scheduler `/7`, prebinding `/7`
and deployment-v5 remain byte-for-byte qualified by their original contract.
The file-carrier implementation is an additive adapter contract version 5 with
Q6, material `/7`, scheduler `/8`, prebinding `/8`, startup mode
`short-entry-file-carrier-v2` and deployment-v6. Its changed loader and submit
source require an exact new qualification and fixed installation before live
use. Historical Q5, deployment-v5, 709 or prior CI cannot qualify the Q6
bytes. Historical adapters and Attempts keep their original parsers and replay
semantics.

## GQF08 — validation and live boundary

Incremental offline validation must cover direct argv, absence of carrier
environment transport, atomic carrier/final-entry/start publication, exact hash
and inode binding, coordinated pre-loader replacement refusal, loader
retained-descriptor behavior,
success, nonzero failure and timeout receipts, single submission and historical
source compatibility. An independent differential review must pass before live
preparation.

After qualification and installation, exactly one newly materialized and
exactly approved Attempt may perform staging and at most one qsub call. Any
ambiguous result is `UNKNOWN` with no retry. No older Attempt may be reused,
and no live action changes scientific acceptance.
