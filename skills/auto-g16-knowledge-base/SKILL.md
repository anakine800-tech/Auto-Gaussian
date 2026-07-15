---
name: auto-g16-knowledge-base
description: Build, validate, import, index, query, link, and snapshot reviewed Auto-G16 structure, computational-method, and literature/book knowledge as immutable offline records. Use when Codex must curate reusable catalyst or ligand states, complete reported or internal protocols, paper/SI/book anchors, typed evidence links, content-addressed lawful files, permission-filtered retrieval, duplicate/conflict review, or a hash-bound W2 study snapshot. This Skill retrieves reviewed candidates and evidence only; it never selects chemistry or methods, marks a calculation ready, or authorizes Gaussian, SSH, RTwin, or PBS work.
---

# Auto-G16 Knowledge Base

## Purpose

Maintain a portable scientific source of truth as immutable canonical JSON
revisions and content-addressed objects. Rebuild SQLite indexes from that source;
never treat an index as the only copy of scientific knowledge.

Read `references/contracts-and-workflow.md` before creating or promoting a
record, importing a local file, or building a study snapshot.

## Boundaries

- Keep identity, exact chemical state, representation, and conformer distinct.
- Keep literature-reported, group-internal, recommended, benchmarked, failed,
  deprecated, and superseded methods distinct.
- Bind source claims to exact page, chapter, figure, table, section, SI, or
  coordinate-block anchors. Retain only lawfully stored files.
- Preserve `public`, `group_internal`, `project_restricted`, and
  `confidential_unpublished` access classes. Query with least privilege.
- Treat the canonical store and raw SQLite index as private local data. The
  index contains records from every indexed access class; query filtering does
  not make the SQLite file safe to distribute.
- Treat duplicate and conflict results as review tasks. Never merge scientific
  records silently or overwrite an immutable revision.
- Snapshot only `reviewed` or `reviewed_with_limits` exact revisions. Preserve
  gaps, contradictions, exclusions, redactions, and the parent reaction-intake
  hash.
- Keep every output `calculation_ready: false` and
  `no_submission_authorization: true`. A match cannot select a protocol,
  generate a Gaussian input, or approve a calculation.
- Do not access a network, Gaussian, SSH, RTwin, PBS, a deployed Skill copy, or
  a multi-user service from this Skill.

## Workflow

Run the deterministic standard-library helper from repository source:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py --help
```

Every artifact output and derived index uses a fresh path. Every canonical
import is a dry run unless `--commit` is explicitly supplied.

### 1. Validate canonical revisions

Create one closed `auto-g16-structure-record/1`,
`auto-g16-method-record/1`, `auto-g16-source-record/1`, or
`auto-g16-knowledge-link/1` JSON record. Bind the exact review decision,
access class, provenance, immutable revision, payload hash, uncertainty, and
blockers. Validate before import:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  validate RECORD.json
```

Use the entry-point schemas under `contracts/knowledge-base/` for authoring.
Use the helper for authoritative hash and semantic validation.

### 2. Initialize an offline store

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  init-store KNOWLEDGE_STORE
```

Create a fresh store only. Keep live mutable stores, private group records,
licensed full text, and unpublished structures outside Git.

### 3. Import lawful objects first

Dry-run an object import, inspect the SHA-256 reference and policy, then repeat
with a fresh report path, `--approved-dry-run`, and `--commit` after review:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  import-object KNOWLEDGE_STORE FILE \
  --media-type chemical/x-mdl-molfile \
  --license internal-reviewed-storage \
  --access-class group_internal --storage-status lawful_local_object \
  --report object-dry-run.json
```

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  import-object KNOWLEDGE_STORE FILE \
  --media-type chemical/x-mdl-molfile \
  --license internal-reviewed-storage \
  --access-class group_internal --storage-status lawful_local_object \
  --approved-dry-run object-dry-run.json \
  --report object-commit.json --commit
```

Reference the committed object by exact SHA-256, size, media type, and original
basename. Preserve immutable license, storage-status and access metadata beside
the object, and make every referencing record at least as restrictive. Do not
store a publisher file merely because its metadata is public.

### 4. Dry-run and commit records

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  import KNOWLEDGE_STORE RECORD.json --report import-dry-run.json
```

Review exact duplicates, revision conflicts, identity/state collisions, DOI
duplicates, provenance, permissions, and scientific status. Commit only a
reviewed batch with a new report path:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  import KNOWLEDGE_STORE RECORD.json \
  --approved-dry-run import-dry-run.json \
  --report import-commit.json --commit
```

The approved dry run is payload-hash bound to the exact candidate batch,
access policy, object, and pre-commit store fingerprint. Re-run the dry review
if any of them changes.

Create a new immutable revision to correct scientific content; never edit an
imported canonical record in place.

### 5. Rebuild and query an index

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  rebuild KNOWLEDGE_STORE --index knowledge-index.sqlite3

python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  verify-index KNOWLEDGE_STORE knowledge-index.sqlite3

python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  query knowledge-index.sqlite3 --registry structure --query ligand \
  --output structure-results.json
```

Default query grants expose only reviewed public records. Add an access grant
only when the user is authorized; add the matching project ID for a
`project_restricted` record. Do not infer that a missing result does not exist:
it may be absent, unreviewed, inaccessible, or outside the query.

Export a permission-filtered canonical JSON round trip into a fresh directory
when another offline workflow needs exact revisions:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  export knowledge-index.sqlite3 --registry source \
  --output-dir source-export
```

The export omits all records outside explicit grants and all binary objects.
Transfer a lawful object separately only after its access and license are
reviewed.

### 6. Create and verify a study snapshot

Prepare a reviewed `auto-g16-knowledge-snapshot-request/1` with exact query
strings, selected revisions, exclusion reasons, access/redaction status,
unresolved gaps, contradictions, and a hash-bound W1 reaction intake. Build a
fresh snapshot:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  snapshot KNOWLEDGE_STORE snapshot-request.json \
  --output knowledge-snapshot.json
```

Verify its exact dependencies later, even after unrelated database updates:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  verify-snapshot KNOWLEDGE_STORE knowledge-snapshot.json
```

Create a new snapshot revision for a deliberate knowledge update. Never mutate
an accepted study because the reusable database changed.

## Required handoff

Report record types and exact revisions, review and access states, import mode,
duplicate/conflict decisions, object hashes and storage limits, index
fingerprint, query terms and grants, selected/excluded revisions, gaps,
contradictions, snapshot hash, and redactions. State explicitly that the
knowledge result is evidence only and grants no calculation authority.
