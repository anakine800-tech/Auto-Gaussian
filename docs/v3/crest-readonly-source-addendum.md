# Auto-G16 CREST read-only source proof addendum

The independent reviewer `crest_contract_review` accepted this bounded design
delta on 2026-09-16; the primary task accepts it under the same explicit Owner
delegation as the [CREST freeze](crest-live-closure-freeze.md). It resolves the
single-current-installation conflict without extending the expired xTB pilot.

The historical source validator uses no effect driver or current live window.
A separate fixed source locator binds the original Core and Transport paths,
parent chains, object identities and exact retained bytes, plus the original
snapshot identity and frozen bootstrap source digest/size. Both stores must
be exact native types. The locator and pins remain current through validation;
copied/stale alternate stores or replaced files reject before consuming proof.

The source databases must use idle DELETE/rollback journal format, have no
attached database, active transaction or journal/WAL/SHM sidecar. The original
Core file's pinned bytes are deserialized into an internal exact native Core
memory view with query-only enabled and explicit schema validation before any
source reads. All Core history reads use this view, never the caller's potentially
stale same-path connection. The view is closed without being exposed or written
to disk. The external Core handle is only a mistaken-path/type check, not proof
of its connection's inode. Full original file identity and byte pins are
rechecked on return and exception; Transport retains its native inode guard.
Within this read-only proof context, existing effect-intent identity is checked
by SELECT of the unique native attempt/intent pair. It must not enter the
public claim method's BEGIN IMMEDIATE transaction even for replay. This does
not create an intent, return a WINNER or provide new submission authority.

Under the existing completion guard, derive the expected runtime qualification
only from the identity-closed original snapshot material manifest and the
frozen bootstrap source. Do not derive expected data from the row being checked,
adopt an unknown version or create a live driver. A new private read-only method
in `auto_g16/transport/program.py` checks that exactly one persisted runtime row
matches every expected column and its original canonical payload. This adds
that file to the narrow scope; `attest_runtime` behavior, DDL and operations
remain unchanged. Missing/drifted data only raises an error.

Then reclose the entire current Core history, dual-source effects, captured
bundle, latest assessment and SUCCEEDED state. All success and failure paths
perform zero persistent writes. The return is only historical proof/capture,
not current target qualification, installation or execution authority.

Before the new CREST claim, the fixed run validator must recheck the source,
handoff ID and private CalculationPlan intent. Missing or changed authority
must cause zero claim/qsub. Synthetic fixtures retain their explicitly
nonproduction identity path and cannot qualify a real binary or installation.

## Accepted historical reconciliation read delta

On 2026-09-27 the Owner explicitly approved the bounded reconciliation read
exception for the CREST receipt-ingestion candidate. This is an additive
exception to the private Core SQL prohibition; the earlier freeze and the
original effect-intent exception remain unchanged.

Only `_replay_submitted_reconciliation`, under the exact condition
`_READONLY_RECEIPT_SOURCE.get() is store`, may make the following additional
SELECT on the fixed original Core file's pinned, schema-validated, query-only
native memory view:

```sql
SELECT r.observation_id,r.resolution,o.attempt_id
FROM reconciliations r LEFT JOIN observations o
ON o.observation_id=r.observation_id
WHERE r.attempt_id=? AND r.resolution != 'UNRESOLVED'
```

Its sole parameter is `snapshot.attempt_id`. Exactly one result row must equal
`(receipt.observation_id, SUBMITTED, snapshot.attempt_id)`. Missing, additional,
cross-Attempt, differently resolved or malformed evidence, and query errors,
reject. Existing surrounding proof reconstruction still validates the original
UNKNOWN submission, recovery request, physical effect and current compatible
Attempt state.

This exception validates an already-recorded terminal reconciliation. It must
not call the public reconciliation method's write transaction, create or change
reconciliation/history/state, accept an unpinned source, or authorize an effect.
Outside this proof context the existing public Core replay remains unchanged.
Static guards must pin both permitted reads to their exact function, proof
condition, query, receiver, parameters and count, rejecting any additional
private Core access. The broader SQL/API/schema prohibition remains in force.
This delta grants no deployment, live or scientific authority.

## Accepted native read-only open delta

On 2026-09-16 the parent delegate explicitly accepted the narrowly identified
hot-journal gap: a default read-write native constructor can perform SQLite
recovery before the historical proof's sidecar check. Source installation must
therefore use private existing-only native Core/Transport read-only factories.
Those owning factories keep the exact native classes and original paths, reject
sidecars and non-rollback headers before SQLite opens, and use `mode=ro` with
`cache=private` and query-only connections. Missing files are never created.
Existing public constructors, writer paths, DDL, authority rows, and schema
versions remain unchanged. Callers must not monkeypatch connections or fabricate
native stores. Original source pins and native schema/physical identity checks
remain mandatory; every installer exit rechecks source bytes and destination
identities while retaining both primary and recheck failures.

This accepted scope delta adds only the private reader factory in
`auto_g16/core/store.py` and the corresponding private Transport factory plus
focused source-opening tests. It does not approve an installation or live action.
A new candidate is required; unchanged exact publisher, probe and loader source
bytes preserve their own existing evidence lineage rather than pretending the
old observation was produced by the new commit.
