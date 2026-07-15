# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `auto-g16-knowledge-base` W2A with closed immutable structure, method,
  source, typed-link and study-snapshot contracts; canonical SHA-256
  finalization; strict offline validation; and frozen positive and adversarial
  tests.
- `auto-g16-knowledge-base` W2B-1 with a canonical immutable record/object
  layout, content-addressed-object verification, versioned deterministic
  SQLite rebuild, stale-index refusal, exact offline permission-filtered
  queries, and snapshot/reaction-intake binding verification.
- `auto-g16-knowledge-base` W2B-2 with hash-bound plan-review-apply import,
  exact lawful-object ingestion, exclusive non-overwriting apply, reviewed
  full/metadata-redacted JSON export, `no_export` exclusion, dependency-aware
  redaction downgrade, and transfer manifests.
- A documented optional chemistry dependency set for the RDKit, Pillow and
  NumPy paths.
- CI coverage that extracts a GitHub-style source archive and runs the full
  offline suite without relying on `.git` metadata.

### Changed

- Removed references to the retired long-lived integration branch; `main` is
  protected and feature work is integrated through reviewed pull requests.
- Made release-hygiene scanning work both in a Git checkout and in generated
  source archives.

### Safety

- Knowledge records, stores, indexes, queries and snapshots unconditionally
  retain `calculation_ready: false` and `no_submission_authorization: true`;
  W2 has no network, Gaussian input, PBS or deployment capability. Offline
  principal declarations are not authentication or a multi-user boundary.

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
