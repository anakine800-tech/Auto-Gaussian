# Auto-G16 Reusable Knowledge Database Design

Status: W2 design contract. The offline builder, canonical importer,
content-addressed object store, deterministic SQLite index/query, typed links,
permission filtering and immutable snapshot workflow are implemented by
`auto-g16-knowledge-base`. A multi-user service and raw legacy-source migration
adapters remain separate future milestones.

The project Skill is named `auto-g16-knowledge-base`. It provides one
audited knowledge infrastructure with three logically separate registries:

1. a structure registry;
2. a computational-method registry; and
3. a literature and book registry.

Every exported study snapshot or proposal must retain
`no_submission_authorization: true`. A database match is reusable evidence, not
permission to alter chemistry, select a method, render an input, or run Gaussian.

## Contents

1. Design goals
2. Shared record model
3. Structure registry
4. Computational-method registry
5. Literature and book registry
6. Cross-registry relationships
7. Storage and indexing architecture
8. Review, permissions, and provenance
9. Study snapshot and workflow use
10. Import and update rules
11. Failure semantics
12. Future implementation sequence and acceptance

## 1. Design goals

Build a reusable group knowledge layer that can answer questions such as:

- Which catalyst, ligand, precatalyst, additive, substrate, or intermediate
  structures have already been reviewed by the group?
- Which exact molecular or catalyst state was represented, and which files and
  calculations support it?
- Which computational protocols have been reported, used internally,
  benchmarked, rejected, or superseded for a defined chemical scope?
- Which paper, supporting-information file, book edition, chapter, page,
  figure, table, or data repository supports a structure, method, mechanism, or
  transition-state claim?
- What is known, uncertain, contradictory, access-limited, or still unreviewed?

Do not make one mutable spreadsheet the scientific source of truth. Preserve
stable logical identities, immutable revisions, exact hashes, review decisions,
and cross-record provenance.

## 2. Shared record model

The first contract family should contain:

| Planned artifact | Purpose |
| --- | --- |
| `auto-g16-structure-record/1` | one reviewed chemical identity, represented state, and its hashed 2D/3D representations |
| `auto-g16-method-record/1` | one complete reported, internal, benchmarked, blocked, deprecated, or superseded computational protocol |
| `auto-g16-source-record/1` | one paper, SI, book, chapter, thesis, preprint, correction, retraction, or data-repository source with exact anchors |
| `auto-g16-knowledge-link/1` | one typed, evidence-bearing relationship between structure, method, source, reaction, or result records |
| `auto-g16-knowledge-snapshot/1` | immutable list of exact record revisions used by one reaction study |

Every record requires:

- a stable logical ID and immutable revision ID;
- canonical payload SHA-256 and schema version;
- creation time, author/importer, reviewer, review status, and review notes;
- `supersedes` and `superseded_by` links rather than in-place scientific edits;
- source category, access class, license/storage status, and provenance;
- typed aliases and external identifiers;
- explicit uncertainty, missing fields, contradictions, and blockers; and
- typed outgoing and incoming relationship IDs.

Use `draft`, `reviewed`, `reviewed_with_limits`, `deprecated`, `retracted`, and
`blocked` as distinct states. Retrieval may show a draft, but only reviewed
revisions may enter a study snapshot.

## 3. Structure registry

### 3.1 Identity and role

Store group catalyst and ligand knowledge without confusing identity, state,
representation, and conformer. Record:

- preferred name, aliases, internal compound code, literature code, registry
  identifiers, canonical SMILES, InChI/InChIKey, formula, and exact mass;
- roles such as precatalyst, catalyst, ligand, cocatalyst, base, additive,
  substrate, product, intermediate, counterion, solvent, or reference compound;
- constitution, isotopes, formal charge, multiplicity, protonation,
  salt/solvate form, stereochemistry, atropisomerism, and component count;
- catalyst oxidation-state hypothesis, ligand count, coordination number,
  hapticity, aggregation, ion pairing, and bound solvent/additive when relevant;
- ownership, project, inventory/sample reference, public/internal/unpublished
  status, and permitted users; and
- preparation or source references without turning inventory existence into
  computational validation.

One `structure_id` represents one reviewed chemical identity. Distinct charge,
spin, protonation, coordination, aggregation, or association states require
separate state records linked to that identity. Conformers are separate geometry
records under one compatible state.

### 3.2 Representations

Bind every representation by format, exact hash, atom order, and review scope:

- CDX/CDXML, MOL/SDF, SMILES, InChI, XYZ, Gaussian input geometry, and rendered
  2D/3D preview;
- source-exact drawing versus normalized structure;
- atom mapping, stereochemical and coordination annotations;
- geometry provenance: experimental structure, literature coordinates,
  generated conformer, optimized minimum, TS candidate, or visualization only;
- calculation/result/evidence hashes supporting an optimized geometry; and
- limitations such as missing hydrogens, inferred bonds, unsupported metal
  bonding, unresolved disorder, or schematic-only geometry.

A 2D drawing does not authorize a 3D state. An XYZ file does not establish
connectivity. A crystal structure, optimized structure, and hand-built starting
geometry must remain distinguishable.

### 3.3 Search

Support exact identity, alias, internal code, formula, element, substructure,
stereochemistry-aware substructure, fingerprint similarity, catalyst/ligand
class, role, charge/spin/state, project, source, and review-status filters.
Return the matched revision and matching rationale, not only a structure image.

## 4. Computational-method registry

Do not store a method as only a functional and basis-set label. One method
record should define the complete protocol needed to interpret or reproduce a
calculation:

- source class: literature-reported, group custom, group recommended,
  benchmark candidate, validated within scope, blocked, deprecated, or
  superseded;
- program and revision, calculation family, functional, basis by element, ECP,
  dispersion, relativistic treatment, solvent, explicit components, grid, SCF,
  optimization, frequency, TS, IRC, and single-point relationship;
- charge/spin/wavefunction requirements, stability checks, and unsupported
  electronic-structure cases;
- temperature, pressure, standard state, concentration, low-frequency,
  quasi-harmonic, symmetry, entropy, and composite-energy policies;
- intended elements, catalyst classes, reaction classes, state types, and job
  stages, with explicit exclusions;
- benchmark cases, reference data, errors, failure modes, sensitivity results,
  resource observations, and Gaussian-version syntax evidence; and
- exact supporting source, calculation, input, output-summary, and reviewer
  links.

Separate what another group reported from what this group has used and what has
actually been benchmarked. “Commonly used” is metadata, not proof of accuracy.

The registry may populate `loose`, `standard`, and `strict` protocol candidates.
It must never auto-select one from molecular identity or popularity. The
existing three-candidate scientific gate, explicit selection, rendered-input
hash, resources, and live approval remain mandatory.

## 5. Literature and book registry

Store bibliographic identity separately from extracted scientific claims.
Support:

- journal article, supporting information, book, edition, chapter, handbook,
  thesis, preprint, patent, correction, retraction, dataset, and repository;
- DOI, ISBN, ISSN, publisher, authors/editors, title, year, volume, issue,
  edition, chapter, page range, article number, and stable URL or identifier;
- relationships between article/SI, preprint/published version,
  original/correction/retraction, book/edition/chapter, and paper/dataset;
- access date, version, language, license, local-storage permission, local file
  SHA-256 when legally retained, and access limitations;
- exact page, section, scheme, figure, table, equation, paragraph, SI section,
  or coordinate-block anchor; and
- structured extracted claims for structures, conditions, mechanisms,
  computational methods, TS geometries, energies, experimental evidence,
  contradictory conclusions, and reported limitations.

Keep short necessary excerpts separate from paraphrase and reviewer
interpretation. Do not use a book citation without edition and page/chapter
anchors. Do not redistribute publisher PDFs or books when storage rights do not
permit it; retain citation metadata, lawful local-path references, and hashes.

The `auto-g16-reaction-literature` Skill searches metadata and creates reviewed
evidence records. Its later knowledge-base import handoff remains unimplemented;
the knowledge base may accept only records that pass identity, anchor,
extraction, and applicability review.

## 6. Cross-registry relationships

Use typed links with evidence and direction, including:

- `structure_reported_in_source`;
- `structure_coordinates_from_source`;
- `structure_used_in_reaction`;
- `method_reported_in_source`;
- `method_used_by_calculation`;
- `method_benchmarked_by_result`;
- `method_failed_for_case`;
- `source_supports_mechanism_hypothesis`;
- `source_contradicts_mechanism_hypothesis`;
- `ts_precedent_uses_structure_and_method`; and
- `record_supersedes_record`.

Every link records direct versus analogous evidence, exact source anchors,
review status, scope, uncertainty, and important mismatch. A relationship must
not be inferred merely because two records share a name or DOI.

## 7. Storage and indexing architecture

Use a layered implementation:

1. immutable canonical JSON records and content-addressed object hashes as the
   portable scientific source;
2. a rebuildable SQLite index for the offline MVP, tests, and single-user use;
3. a content-addressed file store for legally retained CDX/SDF/XYZ/PDF/SI and
   other binary objects; and
4. a later PostgreSQL service with appropriate chemical search support, such
   as an audited RDKit integration, when multi-user concurrency is required.

Do not treat the SQLite file as the only source of truth or commit a live
mutable group database into Git. Version schema migrations and deterministic
index builders. Store neither credentials nor server scratch in records.

Search indexes, fingerprints, embeddings, and thumbnails are derived caches.
Bind each to the canonical record revision and model/tool version; permit full
rebuild. Semantic retrieval may propose candidates, but exact structured
filters and source records remain visible.

## 8. Review, permissions, and provenance

Use at least `public`, `group_internal`, `project_restricted`, and
`confidential_unpublished` access classes. Enforce least privilege in the
future service. Record who viewed, imported, reviewed, exported, superseded, or
promoted restricted records.

Never send unpublished structures, licensed full text, credentials, or internal
notes to an external search or embedding provider without explicit authority.
Redact exports by policy while retaining a local hash-bound provenance record.

Require domain review for chemical identity, stereochemistry, catalyst state,
method applicability, source extraction, and TS-coordinate transfer. Database
administrator approval is not a substitute for scientific approval.

## 9. Study snapshot and workflow use

At study start, query the current reviewed registries and create one immutable
`auto-g16-knowledge-snapshot/1` containing:

- exact structure, method, source, and link revision hashes used;
- query strings and selection/exclusion decisions;
- access-redaction status;
- unresolved gaps and contradictions; and
- snapshot author, reviewer, time, and parent reaction-intake hash.

Later database updates do not change the study. A reviewer may explicitly
create and compare a new snapshot, then supersede the study decision through a
new artifact.

The structure registry supplies reviewed candidates to reaction intake and 3D
construction. The source registry supplies search seeds and evidence anchors.
The method registry supplies protocol candidates. None directly supplies a
calculation-ready artifact.

Calculation results may propose new optimized structures, benchmarks, failures,
or source links for ingestion. They enter the reusable database only after
separate curation and review; a successful job does not automatically become a
group standard.

## 10. Import and update rules

The implemented canonical-record and content-object importers accept reviewed
structure, method, source and link records with a dry-run report before commit.
Provide future raw-source adapters for ChemDraw packages, SDF/MOL/XYZ files,
existing catalyst spreadsheets, protocol ledgers, citation exports, DOI/ISBN
metadata and completed study evidence indexes. Keep lawful PDFs/SI in the
content-addressed object workflow rather than teaching an adapter to bypass
access review.

Every importer must:

- produce a dry-run report before writing;
- preserve source-exact fields and hash every imported file;
- propose duplicates and conflicts without silently merging them;
- reject unknown schema versions and invalid encodings;
- separate parsing from scientific promotion;
- write new immutable revisions without overwriting; and
- emit a machine-readable import manifest and error ledger.

## 11. Failure semantics

Retain explicit states for:

- identity or stereochemistry conflict;
- duplicate or near-duplicate structure;
- unresolved catalyst state;
- atom-order or coordinate provenance mismatch;
- incomplete or internally inconsistent protocol;
- missing element basis/ECP coverage;
- method applicability unknown or contradicted by benchmarks;
- bibliographic/version ambiguity;
- missing SI, edition, page, figure, or coordinate anchor;
- copyright or access restriction;
- source correction, retraction, or supersession;
- stale derived index; and
- snapshot dependency drift.

Do not replace these with a generic confidence score or omit them from search
results because they are inconvenient.

## 12. Implementation sequence and acceptance

Implement `auto-g16-knowledge-base` in phases:

1. closed JSON contracts, strict validators, and frozen fixtures;
2. deterministic SQLite schema, migrations, rebuild, and query CLI;
3. structure import/search with group catalyst and ligand examples;
4. method import/search with reported, internal, benchmarked, failed, and
   deprecated examples;
5. literature/book import, anchors, version/correction/retraction relationships,
   and lawful file-object handling;
6. cross-registry links and immutable study snapshots;
7. role/access/export tests for unpublished group records; and
8. only then a separately approved multi-user service prototype.

Offline acceptance requires deterministic rebuilds, exact hash checks,
round-trip export, conflict/duplicate fixtures, permission-negative tests,
snapshot stability after database updates, and unconditional refusal to mark a
record or snapshot as calculation-ready or submission-authorizing.
