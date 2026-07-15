# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A closed `gaussian-reaction-mechanism-support/1` contract and deterministic
  standard-library builder/validator in `auto-g16-reaction-workflow`, with
  exact finalized network, W1, knowledge-snapshot and literature-evidence
  bindings plus explicit matrix and evidence-coverage review.

### Changed

- Mechanism support is a forward-only immutable sidecar: later orchestrators
  consume the exact network/support pair without rewriting the finalized
  network or removing its historical support-unavailable markers.
- Repository status and contract documentation now distinguish the implemented
  standalone support and TS-precedent sidecars from their still-unimplemented
  cross-sidecar promotion and seed-construction integration.

### Safety

- Support artifacts retain `calculation_ready: false`,
  `no_submission_authorization: true`, and a mechanism-proof refusal. Their
  `downstream_reviewable_edge_ids` are local review candidates only; no TS map,
  protocol, DAG, input, calculation, execution, or live authority is granted.

## [2.2.0] - 2026-07-15

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
- The W3 offline mechanism-network contract, deterministic builder, reviewed
  condition/species bindings, blocker ledger and non-authorizing fixtures.
- Transition-metal M1 scientific-review and M2 input/result observation and
  manual acceptance-review contracts, with deterministic builders, semantic
  validation, evidence-bound scope and adversarial refusal fixtures.

### Changed

- Removed references to the retired long-lived integration branch; `main` is
  protected and feature work is integrated through reviewed pull requests.
- Made release-hygiene scanning work both in a Git checkout and in generated
  source archives.
- Preserved native Unicode workspace paths when opening the GaussView SSH
  control session from macOS Terminal.

### Safety

- Knowledge records, stores, indexes, queries and snapshots unconditionally
  retain `calculation_ready: false` and `no_submission_authorization: true`;
  W2 has no network, Gaussian input, PBS or deployment capability. Offline
  principal declarations are not authentication or a multi-user boundary.
- Transition-metal artifacts remain offline review records: scientific, input
  and mode acceptance are not granted; runtime remains
  `unsupported_requires_extension`; promotion and submission remain refused.
- GitHub Secret Scanning with push protection, Dependabot security updates,
  dependency graph analysis and Python CodeQL default scanning are enabled for
  the public repository.

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

[Unreleased]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.2.0...HEAD
[2.2.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/v2.0.0
