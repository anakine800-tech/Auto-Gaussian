# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `auto-g16-knowledge-base`, an offline W2 registry for immutable reviewed
  structure/state, computational-method, source, typed-link and per-study
  snapshot records.
- Five closed Draft 2020-12 contract entry points, semantic and payload-hash
  validation, content-addressed object import, dry-run conflict ledgers,
  deterministic SQLite rebuild/query, permission-negative behavior and stable
  snapshot verification, including a fresh W1-builder-to-W2-snapshot synthetic
  integration smoke.

### Safety

- Every knowledge record, query result and snapshot remains
  `calculation_ready: false` and `no_submission_authorization: true`.
- No live group database, restricted structure, licensed full text, Gaussian
  output, network request, RTwin/PBS action or deployed-Skill mutation is part
  of this feature.

## [2.1.0] - 2026-07-14

### Added

- `auto-g16-reaction-workflow`, an offline hash-bound reaction-intake,
  species-registry, balance-review, and condition-model foundation.
- `auto-g16-reaction-literature`, an offline-first Crossref/OpenAlex discovery,
  deduplication, screening, source-evidence, and fail-closed review workflow.
- MIT licensing and a minimal offline GitHub Actions regression workflow.

### Changed

- Replaced machine-specific Mac, Windows, RTwin, and private-host values in
  published runtime paths with local configuration or environment variables.
- Aligned the public capability summary, release branding, deployment status,
  and current limitations with the eight version-controlled Auto-G16 Skills.
- Made the closed-loop runner accept only an already reviewed Gaussian input;
  removed its built-in research-method defaults and added an exact hash-bound
  live-submission approval record.

### Safety

- The fixed server boundary remains `/home/user100/SDL`; there is no remote-root
  override.
- Raw structures and SMILES cannot enter the live runner before the three-tier
  protocol proposal, explicit selection and exact offline input review.
- This release grants no Gaussian submission, cancellation, overwrite,
  deployment, or server-file deletion authorization.

## [2.0.1] - 2026-07-14

- Standardized all stable repository-owned Skill names under `auto-g16-*` and
  all human-facing Skill names under `Auto-G16`.

## [2.0.0] - 2026-07-14

- Published the guarded RTwin/PBS, TS–Freq–IRC, structure, preview, and
  asymmetric-catalysis baseline.

[2.1.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/v2.0.0
