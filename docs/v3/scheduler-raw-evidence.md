# Auto-G16 V31 scheduler raw evidence durability

Task: `V31-SCHEDULER-RAW-EVIDENCE-DURABILITY-01`.
Base: `065d016830240962c0aeb22873d3c82aa2f016d3`.
Status: coordinator-approved bounded offline implementation.

The production successor records the already received, transport-frame-closed
scheduler result durably before calling the unchanged scheduler parser. This
is local audit evidence only. It cannot establish a normalized receipt, job
success, retry authority, or scientific acceptance. Wire acquisition failures
before a result is returned are outside this slice.

The private versioned payload uses canonical JSON with one terminal LF. Its
closed fields are `schema` (`auto-g16-v31-scheduler-raw-evidence/1`), `purpose`
(`audit-only`), `acquired_at` (UTC ISO8601 microseconds followed by `Z`), the
complete QUERY `binding`, complete `request`, `request_sha256` (existing
Transport tagged canonical request digest), exact `job_id`, `raw_result`,
`stdout_sha256`, `stderr_sha256`, and `raw_result_sha256` (canonical JSON).

`raw_result` has exactly `stdout_base64`, `stderr_base64`, `returncode`,
`eof_stdout`, `eof_stderr`, and `completion_status`. The streams use canonical
base64 with decoded limits 262144 and 65536 bytes; their digests cover decoded
bytes. The return code is an exact integer and EOF fields are exact booleans.
Completion is a nonempty canonical string. False EOF or non-completed results
can be retained for the existing parser to reject. Invalid closed shape,
unrepresentable streams, or cap overflow fails closed before parsing.

The existing `program_effect_physical_authority` table retains its exact `/1`
DDL. Audit rows use an independent `scheduler-raw-audit` identity domain over the complete
canonical JSON payload bytes,
a `scheduler-raw-audit:` ID prefix, classification `UNKNOWN`, null SQL `job_id` and `submit_once_key`, and the
versioned canonical JSON payload. Existing normalized records use another
identity domain and tagged canonical bytes; audit rows cannot satisfy their
`require_matching_effect` lookup. No Core receipt or public API is extended.

A private record helper generates acquisition time and uses the existing
append-only transaction primitive. A private read helper requires the expected
exact QUERY request, reattests the physical store, and revalidates canonical
payload, full row identity, all digests, indexed columns, runtime binding, and
request/job/snapshot/store identities. Reading never starts a process. Matching
request and bytes at different acquisition timestamps are distinct records;
timestamps are not a global sequence or a guarantee of unique sampling. The
time is the local controller time after acquisition, not a server event time
or scientific ordering evidence. A narrow discovery helper accepts only the
complete exact QUERY request. It enumerates the current physical store's
prefixed audit records, revalidates each against its embedded closed request,
then returns only the caller's exact request matches. It does not trust
denormalized request indexes for discovery; job-only queries are not provided.
This detects damaged indexed columns and retained prefixed payloads, but does
not claim completeness against deletion, removal of the audit ID prefix, or
a privileged attacker recomputing an entire database. The existing physical
store and append-only protection model remains the boundary.

Acceptance requires byte-exact durable reopen, persistence-before-parser,
preservation when normalization fails, no normalization or Attempt promotion
when persistence fails, cross-binding and payload/index tamper rejection,
non-authority of raw audit rows, old-store compatibility, and unchanged
scheduler/capture behavior. Validation is focused then authoritative affected,
with no full suite, publication, main merge, SSH, qstat, qsub, deployment,
cleanup, or live scientific effect authorized by this task.
