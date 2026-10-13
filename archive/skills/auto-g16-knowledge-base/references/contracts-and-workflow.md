# Auto-G16 Knowledge Base Contracts and Workflow

## Contents

1. Canonical source and store layout
2. Shared immutable record contract
3. Registry-specific contracts
4. Review and access rules
5. Import and conflict semantics
6. SQLite index and query semantics
7. Study snapshot contract
8. Integration boundaries

## 1. Canonical source and store layout

Treat canonical JSON and content-addressed objects as the portable source of
truth. Treat SQLite as a fully rebuildable cache.

```text
KNOWLEDGE_STORE/
├── store.json
├── records/
│   └── <record_type>/<logical_id>/<revision_id>.json
└── objects/
    ├── sha256/<first-two-hex>/<full-sha256>
    └── metadata/<first-two-hex>/<full-sha256>.json
```

Do not commit a live mutable group store. Commit only public, frozen fixtures
that contain no restricted structures, copyrighted full text, credentials,
machine-specific paths, Gaussian outputs, or server data.

Keep the store and raw SQLite index private. The SQLite file contains all
indexed access classes even though query and export commands filter results.
Never distribute the index as if it were a redacted export; use the JSON export
command with explicit grants and transfer lawful file objects separately.

## 2. Shared immutable record contract

Use one stable `logical_id` and immutable `revision_id`. Format revision IDs as
`<logical_id>_rNNN`; increment `revision` and set `supersedes` for a scientific
correction. Do not edit an imported revision.

Bind every record to:

- schema and record type;
- creation author and UTC timestamp;
- review status, reviewer, timestamp, and notes;
- access class, projects, license, and storage status;
- provenance with exact source locator and optional SHA-256;
- aliases and typed external identifiers;
- uncertainties, blockers, supersession, and typed link IDs;
- canonical payload SHA-256; and
- `calculation_ready: false` plus `no_submission_authorization: true`.

Use `draft`, `reviewed`, `reviewed_with_limits`, `deprecated`, `retracted`, and
`blocked` as distinct states. Only the two reviewed states may enter a study
snapshot.

The five public schema entry points live under `contracts/knowledge-base/`.
`record.schema.json` contains their shared Draft 2020-12 definitions. The
standard-library validator additionally enforces cross-field and hash rules.

## 3. Registry-specific contracts

### Structure

Use `auto-g16-structure-record/1`. Keep `identity_id` and `state_id` distinct.
Record formula, charge, multiplicity, component count, protonation,
salt/solvate form, stereochemistry, coordination state, roles, ownership, and
hashed representations. A reviewed structure requires at least one lawful
content-addressed representation. State changes require distinct logical
records; compatible conformers remain separate hashed representations.

Do not treat a 2D drawing as a 3D state, an XYZ as proven connectivity, or an
optimized structure as equivalent to a hand-built starting geometry.

### Computational method

Use `auto-g16-method-record/1`. Keep source classification explicit. Record
program/version, calculation family, complete protocol dimensions, basis/ECP by
element, scope, exclusions, benchmarks, and failure modes. A reviewed method
requires explicit element scope, complete per-element basis/ECP coverage, and
non-null functional, grid, SCF, optimization, frequency, and thermochemistry
statements.

A method record may supply protocol candidates. It may not select one or claim
accuracy outside reviewed scope.

### Literature and book source

Use `auto-g16-source-record/1`. Separate bibliographic identity from extracted
claims. Record type, authors/editors, version identifiers, article/SI or
book/edition/chapter relationships, access date, exact anchors, lawful local
objects, and source-located paraphrases. Require edition plus page/chapter for
reviewed books. Require a `supplement_to` relationship for reviewed SI.

Store metadata when full-text storage is not permitted. Do not store a book or
publisher PDF merely because it was available to a reviewer.

### Typed link

Use `auto-g16-knowledge-link/1`. Bind both exact record revisions and payload
hashes. Record an allowed directional relationship, direct versus analogous
evidence, exact anchors, scope, uncertainty, and mismatches. Make link access
at least as restrictive as both bound records. Shared names, DOIs, or keywords
do not create a relationship automatically.

### Study snapshot

Use `auto-g16-knowledge-snapshot/1`. Build it from a reviewed snapshot request;
do not hand-edit it. Bind exact selected revision hashes, queries, exclusions,
redactions, gaps, contradictions, database fingerprint, author/reviewer, and
the parent W1 reaction intake.

## 4. Review and access rules

Order access from least to most restrictive:

1. `public`
2. `group_internal`
3. `project_restricted`
4. `confidential_unpublished`

Require at least one matching project ID for project-restricted retrieval.
Omit records outside explicit grants without exposing their identifiers. Make
a snapshot and each link at least as restrictive as every bound record.

Database administration is not scientific review. Require domain review for
identity, stereochemistry, catalyst state, method applicability, source
extraction, and TS-coordinate transfer.

## 5. Import and conflict semantics

Run record and object imports without `--commit` first. Preserve a new
machine-readable report for every attempt. Bind commit to the reviewed dry-run
payload, exact candidate/object and pre-commit store fingerprint. Refuse:

- the same revision ID with different content;
- conflicting logical revision identity;
- duplicate structure identity/state under a different logical record;
- duplicate DOI identity under a different source record;
- missing or hash-mismatched content-addressed objects;
- silently overwritten records, reports, stores, objects, or indexes; and
- commit without an unchanged `--approved-dry-run` manifest.

Treat exact duplicates as an idempotent skip. Resolve scientific conflicts by
reviewing both sources and creating a deliberate immutable revision; never let
an importer choose the winner.

## 6. SQLite index and query semantics

Build a fresh index from all canonical records in revision-ID order. Validate
payload hashes, object hashes, supersession, link targets, and access dominance
before writing the index. Store migration version and a database fingerprint.

Index exact IDs, aliases, external identifiers, review/access state, canonical
JSON, link endpoints, and object references. Use lexical retrieval only as a
candidate finder. Report the exact index fingerprint and access grants with
each query. A finite or permission-filtered search cannot prove absence.

## 7. Study snapshot contract

Require the snapshot request to list the same selected revisions globally and
within its query decisions. Require a reason for every recorded exclusion.
Refuse drafts, blocked/deprecated/retracted records, missing dependencies,
multiple revisions of one logical record, and access downgrade.

Compute the snapshot fingerprint only from sorted pairs of selected revision
IDs and payload hashes. Later unrelated database updates therefore leave the
snapshot stable. Verification fails if a selected revision is absent or its
payload differs.

## 8. Integration boundaries

- Give reviewed structure candidates to `auto-g16-reaction-workflow` or a
  structure-preparation Skill without granting a 3D state or calculation.
- Give reviewed source records and links to
  `auto-g16-reaction-literature` as evidence and search seeds.
- Give method candidates to the three-candidate protocol gate; never bypass
  explicit scientific selection.
- Give snapshots to later mechanism-network or TS-precedent work only with all
  gaps and access constraints intact.
- Accept completed calculation facts only as new curation proposals. Do not
  promote a successful job automatically to a standard method or structure.
