# Auto-G16 Knowledge Record Contract

## Record family

Use only these versioned schemas:

- `auto-g16-structure-record/1`
- `auto-g16-method-record/1`
- `auto-g16-source-record/1`
- `auto-g16-knowledge-link/1`
- `auto-g16-knowledge-snapshot/1`

Every record has a stable logical `record_id`, immutable `revision_id`, exact
canonical `payload_sha256`, creation and review metadata, access policy,
provenance, typed aliases and identifiers, explicit uncertainties,
contradictions and blockers, plus the non-authorization constants.

## Structure scopes

- `identity`: record constitution, components, isotope and stereochemical
  identity. Do not assign charge, multiplicity, coordination or geometry here.
- `state`: bind one exact identity revision and record charge, multiplicity,
  protonation, salt/solvate, oxidation-state hypothesis, coordination,
  aggregation, ion pairing and bound components.
- `geometry`: bind one exact state revision and one or more hash-addressed
  representations. Distinguish source drawings, generated conformers,
  experimental coordinates, optimized minima, TS candidates and visualization.

An XYZ representation does not prove connectivity. A two-dimensional drawing
does not authorize a three-dimensional state.

## Methods and sources

Represent each required method field as a fact with an explicit status. A
`reported` fact requires a source-record revision and anchor. Missing or
ambiguous details remain explicit and force `reviewed_with_limits` rather than
an unqualified reviewed literature method.

Keep source identity separate from claims. Every claim references local anchor
IDs. Books and chapters require edition plus page/chapter anchors. Keep lawful
object hashes separate from citation metadata; do not store a filesystem path
or redistribute licensed content in a canonical record.

## Links and snapshots

Use link records for scientific relationships and supersession. The SQLite
index may derive `superseded_by` and incoming-link views, but canonical target
records never gain backlinks after creation.

A snapshot records exact revisions and hashes, query history, decisions,
redactions, gaps, contradictions and the parent reaction-intake hash. Later
database revisions never change an existing snapshot.
