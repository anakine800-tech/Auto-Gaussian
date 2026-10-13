# Auto-G16 Immutable Store and Derived Index

## Authority model

Canonical JSON revisions and content-addressed objects are the source of
truth. The SQLite database and its manifest are disposable derived views.
Neither layer grants scientific review, method selection, input generation, or
calculation authority.

## Canonical layout

```text
store.json
records/{structure,method,source,link,snapshot}/{record_id}/{revision_id}.json
objects/sha256/{first_two_hex}/{sha256}
indexes/
```

The verifier rejects symlinks, unexpected top-level entries, noncanonical
record paths or JSON bytes, duplicate payloads, missing exact revisions,
reference-hash drift, unknown source anchors, unlawful missing objects,
unreferenced objects, and object hash or size drift.

`metadata_only` and `external_reference_only` object references do not imply a
local file. `lawful_local_object` requires the exact content-addressed object.
No command deletes or overwrites canonical records or objects.

## Derived SQLite index

`scripts/migrations/001_initial.sql` defines the versioned schema. Rebuilds
validate the complete store, insert canonical sorted rows into a new file,
check foreign keys, and emit a sidecar manifest binding the database hash,
migration hash, store manifest, store content digest, and canonical row digest.
An existing database or sidecar is never overwritten.

Queries verify both the database and current store binding first. They support
exact registry, ID, alias, external-identifier, review, access, and link-type
filters. No fuzzy, structure, embedding, or semantic search is implemented.

## Offline principal declarations

Without `--principal`, queries return public records only. A local principal
declaration can model group membership, project membership, and explicit
confidential-record access for offline acceptance tests. It is not
authentication, operating-system authorization, an audit log, or a multi-user
security boundary.

## Snapshot verification

`verify-snapshot` resolves every included revision and payload hash against the
current canonical store and separately verifies the bound reaction-intake
file, file hash, size, schema, and canonical payload hash. It does not create a
snapshot, choose its members, or authorize downstream calculation.
