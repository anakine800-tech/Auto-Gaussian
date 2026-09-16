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
