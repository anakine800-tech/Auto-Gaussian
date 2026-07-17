# Auto-G16 Manual Evidence Receipt V1

## Purpose and authority ceiling

`auto-g16-manual-evidence-receipt/1` is an immutable, hash-bound, offline
receipt for one manually reviewed passage returned by an existing private
manual-retrieval SQLite database. It is evidence only. It never selects a
method, renders Gaussian input, marks a calculation ready, authorizes a live
action, or changes an existing knowledge record or scientific-maturity
artifact.

Every receipt fixes:

- the canonical-store digest and exact retrieval-database SHA-256;
- the stable source record ID, immutable revision, source payload SHA-256,
  lawful source-object SHA-256, and exact page and/or logical-chunk locator;
- the exact retrieved-text SHA-256 without retaining the private text;
- the query, bounded paraphrase or short quote, text quality, page review and
  logical-chunk review;
- source kind and, only where applicable, Gaussian program/version metadata;
- the target installed Gaussian revision, applicability decision, explicit
  uncertainty, reviewer, and downstream role; and
- the adapter config, normalized retrieval row, review input, and final
  canonical payload hashes.

The four authorization constants and claim ceiling are closed. In particular,
`calculation_ready` is always `false` and `no_submission_authorization` is
always `true`.

## Source metadata versus reviewed claim scope

The adapter returns stable source metadata. It does not decide how a passage
will be used.

`source_kind` is one of:

- `gaussian_program_manual`;
- `gaussian_associated_text`; or
- `general_electronic_structure`.

The reviewer independently assigns `claim_scope` in
`auto-g16-manual-evidence-review/1`:

- `gaussian_syntax_or_version`;
- `gaussian_nonversion_concept`; or
- `general_electronic_structure`.

This separation permits the same Gaussian manual page to support a
version-specific syntax claim in one receipt and a bounded non-version concept
in another. Only the first use invokes the installed-revision gate. A general
electronic-structure source must retain null source program, major version and
version values; it must never be relabeled G09 or G16.

## Lossless text-quality and locator review

Preserve the retrieval library classification exactly:

- `embedded_text`;
- `embedded_ocr_unreviewed`;
- `legacy_word_text_pagination_unstable`; or
- `image_only`.

The latter three require source-quality limitations and receipt uncertainty,
and cannot yield unqualified `applicable`. Legacy Word evidence must use a
logical chunk rather than an unstable page number. Image-only evidence may
have an empty retrieved-text value, but remains hash-bound.

Any positive `applicable` or `applicable_with_limits` decision requires
`whole_page_visual_review.status=reviewed` when a page exists and
`logical_chunk_review.status=reviewed` when a logical chunk exists. A short OCR
hit therefore cannot be promoted without reviewing its complete located
context. Explicit short quotes are limited to both 25 whitespace-delimited
words and 120 Unicode characters, so an unspaced Chinese quotation cannot turn
the receipt into a text cache. The normal retained form is a reviewer-declared
paraphrase of at most 600 characters and must not copy the source passage.

## Configurable read-only SQLite adapter

The adapter configuration contains no database path. It supplies exactly one
parameterized `SELECT` or `WITH` statement for discovery and one for exact
reselection. Discovery parameters are exactly `:query` and `:limit`;
reselection parameters are exactly `:query` and `:result_id`.

Both statements must return these exact aliases:

```text
result_id
canonical_store_digest
source_record_id
source_revision
source_payload_sha256
source_object_sha256
source_kind
locator_kind
page
logical_chunk
text_quality
text_quality_notes
source_program
source_major_version
source_version
evidence_text
```

An existing private library organized as stable `sources` plus page/chunk
rows can expose this alias set with a read-only join and SQL constants; it does
not need a schema migration. `source_kind` may be mapped from the stable
`source_record_id`. `claim_scope` is intentionally absent from this SQL
interface because it belongs to the human review, not the retrieval row.
Compatibility was smoke-checked read-only against the existing private
library with a temporary path-free v2 config after the locator and SQL-budget
gates were added. One text query returned three bounded
`gaussian_associated_text` / `embedded_ocr_unreviewed` candidates; exact-locator
queries separately returned one `image_only` physical page with an empty
preview and one legacy Word logical chunk with `page=null`; the database digest
was unchanged. No path, preview text, database, or source object is retained in
the repository.

`locator_kind=physical_page` requires `page >= 1`. Existing `page_number=0`
metadata rows must be excluded by operational SQL, or deliberately mapped to
`locator_kind=metadata`, `page=NULL`, and a stable metadata logical-chunk ID;
they are never physical page zero. Numeric blocks from a legacy Word document
with unstable pagination must be mapped as `locator_kind=logical_chunk`,
`page=NULL`, and a stable synthesized chunk ID, then receive a complete
`logical_chunk_review` before positive use.

`image_only` is supported without pretending OCR exists. A locator-oriented
adapter may retrieve it by exact source/result/page identifier with
`evidence_text=''`; its preview remains empty and the empty-text SHA-256 is
bound in the receipt. It cannot be discovered by full-text search. A positive
receipt requires review of the exact whole-page image, with the source image
object hash, locator, human paraphrase and uncertainty carrying the evidence.

The CLI opens a regular non-symlink SQLite file with
`mode=ro&immutable=1`, installs an authorizer that permits only read/select
operations and the deterministic `lower` and `instr` SQL functions, rejects
journal/WAL/SHM sidecars, and verifies the expected file SHA-256 and file
identity before and after every query. Unknown functions are denied. A fixed
1,000,000 SQLite VM-step progress budget stops recursive or unexpectedly
expensive statements while leaving ample room for a simple lookup over the
current roughly 1300-page library. Discovery fetches at most `limit + 1` rows
and fails if the statement ignored its declared limit; exact reselection
fetches at most two rows and requires exactly one. Use a stable, checkpointed
database snapshot; do not point the adapter at a live WAL-backed writer.

`query` prints only a bounded preview to standard output and labels it private
operational output. Never commit that output. `build-receipt` reselects one
exact row, stores only its text SHA-256 and the reviewed bounded statement,
and refuses to overwrite an existing receipt.

```bash
PYTHON="${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}"
TOOL=skills/auto-g16-knowledge-base/scripts/manual_evidence.py
PRIVATE_DB="${AUTO_G16_PRIVATE_MANUAL_DB:?set an operational private database path}"

"$PYTHON" "$TOOL" validate-config adapter.json
"$PYTHON" "$TOOL" query \
  --config adapter.json \
  --database "$PRIVATE_DB" \
  --expected-db-sha256 REVIEWED_DATABASE_SHA256 \
  --query 'optimization convergence' --limit 10
"$PYTHON" "$TOOL" build-receipt \
  --config adapter.json \
  --database "$PRIVATE_DB" \
  --expected-db-sha256 REVIEWED_DATABASE_SHA256 \
  --review manual-review.json --output manual-evidence-receipt.json
"$PYTHON" "$TOOL" validate manual-evidence-receipt.json
```

The absolute database path is an operational command argument only. The
validator rejects machine absolute paths in configs, reviews and receipts.

## Gaussian source-to-installed-version gate

For `gaussian_syntax_or_version`, a positive applicability decision requires a
hash-bound `installed_revision_review.status=reviewed`. In particular, a G09
source used for a G16 syntax/version claim must remain
`blocked_pending_installed_revision_review` until the exact installed G16
revision has been reviewed. The validator rejects a positive decision, rather
than inferring compatibility.

For `gaussian_nonversion_concept` and `general_electronic_structure`, use
`installed_revision_review.status=not_applicable_non_version_claim` unless an
actual revision comparison was independently performed. These claim scopes
must not fabricate a pending G09-to-G16 gate.

## Exact scientific-maturity handoff

Do not add a manual receipt to `gaussian-scientific-maturity-review/1` or
reinterpret any field in that schema. A future integration must either create
a new schema version or a separate overlay. Its artifact binding must contain
exactly:

```json
{
  "path": "relative/path/to/manual-evidence-receipt.json",
  "sha256": "<exact receipt file sha256>",
  "size_bytes": 123,
  "schema": "auto-g16-manual-evidence-receipt/1",
  "payload_sha256": "<receipt payload_sha256>",
  "receipt_id": "<receipt_id>",
  "downstream_role": "scientific_maturity_supporting_evidence"
}
```

Before accepting that binding, the integration owner must:

1. run `manual_evidence.py validate` on the exact file;
2. independently verify file SHA-256, size, schema, payload SHA-256 and receipt
   ID;
3. require all non-authorization constants and the fixed claim ceiling;
4. require `downstream_role=scientific_maturity_supporting_evidence`;
5. treat `applicable` or `applicable_with_limits` only as supporting evidence,
   carrying every uncertainty forward; and
6. retain blocked/not-applicable receipts as gaps or negative evidence, never
   as positive support.

Even after this handoff, the receipt cannot satisfy structure, method,
minimum, TS-mode, IRC, thermochemistry, live approval, or submission gates by
itself.
