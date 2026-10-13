# Auto-G16 successor Result destination adjustment

Status: ACCEPTED for implementation and offline validation on 2026-09-28.
Owner explicitly accepted the independently reviewed SHA-256
`5c2a06713fd91abba8a76e9d21504ad020cf97775ef97ae781a2ad68bb391df6`.
Parent task: V31-GAUSSIAN-RESULT-REFINEMENT-01.

## Confirmed gap

The accepted contract allows a caller-supplied writable SQLiteRuntimeStore.
Core does not bind that connection to the inode opened originally. Path pins,
PRAGMA database_list and matching database content cannot prove it does not
refer to the original source through a stale connection. Independent read-only
review confirmed there is no reusable writable Core connection owner.

## Proposed narrow replacement

Replace only the on-disk destination writer with an explicit immutable revision
operation in the private Result boundary. Do not accept a caller-supplied disk
write connection, add Core schema/connection APIs, or modify a source database.

The caller selects two distinct existing original source files, an existing
quiescent destination snapshot, and a fresh output revision filename in an
explicit local root. Source ownership remains exactly the accepted parent
contract. Read the destination only with Core's existing read_snapshot owner;
check complete ownership and source/spec/snapshot matches. Serialize from that
same read-only snapshot connection into a byte cache inside its context. Only
after successful context exit and all postchecks may output creation begin.
Never re-read the validated bytes later through the pathname. Deserialize the
cached bytes into a new in-memory Core connection owned by this operation. Validate
and append the deterministic Observation/Result pair there, then serialize the
complete new database revision. No SQL writes occur through any disk connection.

Publish the revision through one no-follow, descriptor-relative exclusive
file creation under the pinned selected parent (O_CREAT|O_EXCL|O_NOFOLLOW).
Retain the full directory descriptor chain and final file descriptor. Before
creation, before the first write and after readback, verify every named path
component still matches its retained physical identity. The final file must
remain a single-link regular file. Drift fails with retained evidence and no
success path receipt.
Write the precomputed bytes, fsync the file and parent, and read back through
the same pinned file descriptor; retain exact SHA-256 and byte count. Never
rename over an existing path, truncate, delete, or clean up. A process failure
may leave a partial new file, which is retained and is not an accepted revision.
An existing output accepts only exact complete-byte replay, validated using
the existing no-follow read owner; any mismatch fails without repair. A prior
fsync failure is not acceptance even when bytes are complete. An explicitly
invoked exact replay must again fsync that verified file and parent and finish
the same identity/readback checks before returning success. Interrupted
publication never retries automatically or replaces the partial file.

This changes physical persistence to a fresh immutable snapshot revision while
preserving Core schema and every prior row and identity. The serialized result
must equal the verified destination snapshot plus exactly the new pair (or its
one missing Result for an explicit source-only partial-pair recovery). It cannot
copy execution history implicitly from the original source. The returned
revision identity is file path, SHA-256 and size; this is a local artifact
receipt, not a new execution record or permission. Current scientific authority
still reopens original proof/capture and replays parser/SV; the new file cannot
self-attest scientific validity.

## Validation and authority

Required tests: destination/source symlink and hardlink aliases, replaced
parents/files, stale caller connections not accepted by the API, exclusive
create collision, partial write/fsync failure and retained incomplete files,
exact replay versus conflicting output, complete row preservation, source
byte invariance, no wire calls, and fresh-process authority reconstruction.
Native local filesystem checks on the actual supported host are required for
the publisher claim; no RTwin/PBS/Gaussian or deployment is needed or authorized.

Implementation remains in the parent's Result/Conformer/test/document paths.
All other parent semantics and existing approvals remain unchanged. Owner need
only accept this destination persistence delta; method/resources and live gates
are not reopened. Publication/merge of the feature remain separate.
