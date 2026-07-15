# Auto-G16 Reviewed Import and Redacted Export

## Import gate

Use exactly three artifacts/actions:

1. `plan-import` validates candidate finalized revisions against the current
   store, resolves their cross-record references, and binds every source file.
2. `review-import` approves or rejects the exact plan hash. It does not write
   the store or confer scientific review.
3. `apply-import` rechecks the store digest, plan, approval, record files,
   lawful objects, destinations, and merged reference graph before exclusive
   creation.

Supply `--object SHA256=PATH` only for a new representation or source object
whose record says `lawful_local_object`. The supplied set must exactly equal
the new lawful-object references. Existing objects may be reused only when
their hash, size, media type, and local presence agree. Metadata-only and
external-reference-only objects must not be ingested.

No step overwrites a revision or object. A failed or interrupted apply never
authorizes deletion or automatic cleanup; run `verify-store` and review the
result before any recovery decision. Rebuild the SQLite index after a
successful import because every prior index is intentionally stale.

## Export gate

Use `plan-export`, `review-export`, and `apply-export` in the same order. The
plan binds the canonical store, SQLite index, optional offline principal
declaration, record selection, destination, per-record action, and payload.

Export decisions are fail-closed:

- an inaccessible record is omitted without disclosing its identity;
- `no_export` is omitted and counted;
- `metadata_redacted` emits only the minimal redacted envelope;
- `full` emits canonical JSON only when the principal can also access every
  locally referenced dependency and each dependency permits full export;
- otherwise the entire record is downgraded to metadata-redacted; and
- binary objects are never exported by this W2 implementation.

The offline principal file is a testable policy declaration, not
authentication. Review artifacts are hash-bound decisions, not signatures.
Actual identity, filesystem authorization, audit logging, and multi-user
enforcement require a later service boundary.
