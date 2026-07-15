---
name: auto-g16-knowledge-base
description: Validate, store, import, query, snapshot, and permission-aware export immutable hash-bound Auto-G16 structure, computational-method, literature/source, and typed-link records. Use when Codex must curate reusable catalyst or ligand identities and states, distinguish reported/internal/benchmarked methods, preserve paper/SI/book anchors and access limits, run a plan-review-apply knowledge import with lawful object ingestion, or produce a reviewed full or metadata-redacted export. This Skill is offline only and never selects a method, creates a Gaussian input, or authorizes calculation.
---

# Auto-G16 Knowledge Base

## Purpose

Create and validate the portable scientific records behind the Auto-G16 W2
knowledge layer. Treat canonical JSON records and exact object hashes as the
source of truth. Treat SQLite indexes as rebuildable views.

Read `references/record-contract.md` before creating or reviewing a record.
Read `references/permissions-and-export.md` before handling restricted or
unpublished records.
Read `references/store-and-index.md` before initializing, verifying, indexing,
or querying a canonical store, or verifying a study snapshot.
Read `references/import-and-export.md` before planning, reviewing, or applying
any record/object import or permission-aware export.

## Boundaries

- Keep identity, represented state, and geometry as separate structure records.
- Preserve reported, internal, benchmarked, failed, deprecated, and superseded
  method states without turning popularity into validation.
- Require exact article, SI, book-edition, chapter, page, figure, table, or
  coordinate-block anchors for retained scientific claims.
- Represent supersession and every incoming relationship with independent
  `auto-g16-knowledge-link/1` records. Never rewrite an older revision to add a
  backlink.
- Do not silently merge duplicates, resolve conflicts, promote drafts, infer
  chemistry, select a protocol, create a Gaussian input, or access a network.
- Keep `calculation_ready: false` and `no_submission_authorization: true` in
  every record and snapshot.

## Validate records

Run the repository source helper:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  validate RECORD.json
```

The validator uses only the Python standard library. It rejects duplicate JSON
keys, non-finite numbers, unknown fields, unsupported schema versions, invalid
payload hashes, incomplete reviews, unsafe access metadata, incompatible
structure scopes, unanchored reported-method facts, unlocated source claims,
invalid relationship endpoints, and unreviewed snapshot members.

To hash a reviewed draft without changing its scientific or permission state,
set `payload_sha256` to `null` and write a new output:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  finalize DRAFT.json --output RECORD.json
```

`finalize` refuses overwrite and grants no review, promotion, export, method,
or calculation authority.

Audit a bounded set for duplicate candidates or conflicting immutable
revisions without merging it:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  audit-set RECORD.json OTHER-RECORD.json
```

## Store, index, and query

Initialize an empty canonical layout:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  init-store STORE --store-id GROUP_STORE
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  verify-store STORE
```

Build a fresh derived index and run a fail-closed exact query:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  rebuild-index --store STORE --output STORE/indexes/index.sqlite
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  query --store STORE --index STORE/indexes/index.sqlite --registry source
```

Omitting `--principal` returns public records only. A supplied local principal
declaration models access for offline tests; it is not authentication. Querying
refuses a stale or modified index.

Verify a frozen snapshot and its exact parent reaction intake separately:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  verify-snapshot SNAPSHOT.json --store STORE --artifact-root STUDY_DIR
```

## Review workflow

1. Choose exactly one supported record schema.
2. Preserve source-exact values and record missing or contradictory data.
3. Complete the scientific review and access classification outside the
   helper; do not use hashing as a review decision.
4. Finalize into a new path and validate it.
5. Keep each revision immutable. Express later corrections or supersession as
   a new revision plus a reviewed typed link.
6. Include only `reviewed` or `reviewed_with_limits` revisions in a study
   snapshot, together with the exact parent reaction-intake hash, queries, and
   inclusion/exclusion decisions.

## Import and export

Never copy records or objects into a canonical store manually. Use:

```bash
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  plan-import --store STORE --record RECORD.json \
  --object SHA256=OBJECT --plan-id IMPORT_ID --output IMPORT-PLAN.json
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  review-import --plan IMPORT-PLAN.json --decision approved \
  --reviewer REVIEWER --output IMPORT-APPROVAL.json
python3 skills/auto-g16-knowledge-base/scripts/knowledge_base.py \
  apply-import --store STORE --plan IMPORT-PLAN.json \
  --approval IMPORT-APPROVAL.json --output IMPORT-RESULT.json
```

For export, replace the three commands with `plan-export`, `review-export`,
and `apply-export`. Always inspect the plan's excluded counts and per-record
`full_record` or `metadata_redacted` action before approval. W2 exports no
binary objects.

## Current implementation status

W2A implements the immutable record contracts. W2B-1 adds the canonical store,
deterministic SQLite index/query, and snapshot verification. W2B-2 adds
hash-bound plan-review-apply import, exact lawful-object ingestion, and
permission-aware full or metadata-redacted JSON export. Authentication,
signatures, audit logging, binary-object export, chemical search, and a
multi-user service remain later work.
