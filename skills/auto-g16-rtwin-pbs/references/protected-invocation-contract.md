# Auto-G16 v2.6 protected invocation successor

`auto-g16-protected-invocation-bundle/1` is an additive, non-executable owner
closure for a future single legacy transaction. It does not reserve, stage,
submit, invoke an adapter, read live configuration, contact any external
system, or grant execution authority.

One typed seal call accepts only:

- the exact PR4D protected-submit evidence; and
- PR4G local-state evidence embedding that same PR4D evidence object.

The owner replays both predecessors, derives the unique PR4G ledger path, and
uses the sole legacy stage planner to capture the approved input, allowed
`.json`/`.xyz` companions, explicit `%oldchk`, fixed PBS bytes and checksum
bytes in their historical order. Callers cannot provide `local_dir`, ledger
path, a stage list, basename, command, callback, backend, adapter, or
configuration.

The portable JSON contains relative logical names plus hashes, sizes, order,
policy and self-hash only. Canonical Paths, stable bytes and initial file
identities remain only in the unconstructible in-process capability. Its
`assert_current()` operation is read-only and fails closed on predecessor
authority expiry, ledger drift or stage-source drift; it has no effect method.

The facade adds only:

- `seal_protected_invocation_bundle(*, evidence)`

Historical request/authorization `/1` and `/2`, protected-submit `/1`,
local-state `/1`, execution-batch owners and CLI semantics remain frozen with
no migration, rehash or backfill. Offline validation never authorizes a
future adapter or a real operation.
