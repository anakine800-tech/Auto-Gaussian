# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A standard-library-only `gaussian-reaction-calculation-plan/1` builder and
  validator with stable DAG/node identities, exact W1 and finalized mechanism-
  network bindings by file SHA-256, byte size and payload SHA-256, explicit
  dependencies, alternatives, supersession, blockers, and preserved failed,
  cancelled, rejected, skipped, inconclusive and superseded history.
- A compact immutable `gaussian-reaction-study-index/1` read-only resume view
  that derives accepted-stage, blocker, supersession, and coverage summaries
  from exact artifact bindings rather than a mutable status flag.
- Closed Draft 2020-12 calculation-plan and study-index schemas,
  `skills/auto-g16-reaction-workflow/scripts/calculation_dag.py`, and the
  offline contract in
  `skills/auto-g16-reaction-workflow/references/calculation-dag-contract.md`.
  Missing mechanism-support and TS-precedent bindings remain explicit
  blockers. Supplied mechanism support must pass the origin evidence-gate
  owner validator and match the exact W1/network parents, but remains blocked
  because calculation-plan review `/1` has no reviewed edge-plus-channel
  mapping. TS-precedent coverage clears only per matching edge after its owner
  validator proves the exact W1/network/support parents and a locally accepted
  complete record.
- Target-shaped dependency checks require an edge single-point to consume a
  reviewed TS-Freq result, and every edge-target node inherits the TS-
  precedent gate. Study-index stages follow W1, mechanism network, mechanism
  support, TS precedent, then calculation plan, while retaining the plan's
  normalized blocker identities, descriptions, scopes and provenance.
- Supersession validation is iterative for long node chains and rejects plan-
  ancestry paths beyond the documented 128-artifact limit with a controlled
  contract error.
- A closed standard-library-only `gaussian-reaction-mechanism-support/1`
  builder/validator with exact W1, mechanism-network, knowledge-snapshot,
  finalized-literature and immutable-review bindings; deterministic claim and
  location hashes; complete edge/channel scientific review; preserved negative
  evidence; and separate hypothesis-exploration and mechanism-claim-support
  decisions.
- Exact mechanism-support binding in `gaussian-ts-precedent-map/1` plus a
  source-free de novo endpoint/QST, scan or reviewed-rebuild planning path for
  exploration-eligible novel hypotheses.

### Changed

- Treat absence of direct literature precedent as a visible
  `novel_hypothesis_no_direct_precedent` evidence gap rather than automatic
  exclusion from reviewed computational exploration. Analogy and internal
  rationale still do not support or validate a mechanism claim.

### Safety

- The calculation-planning slice separates scientific readiness, input-review
  readiness, live-approval readiness, execution state, and evidence
  acceptance. Every node remains non-executable; every artifact retains
  `calculation_ready: false` and `no_submission_authorization: true`.
- This slice does not infer chemistry, choose a protocol, construct geometry,
  render an input, create a server project or job, or perform Gaussian, SSH,
  PBS, submission, retry, cancellation, deletion, deployment, or other live
  action.
- Mechanism-support and TS-planning artifacts remain
  `calculation_ready: false` and `no_submission_authorization: true`; de novo
  plans contain no source precedent or source coordinates and grant no method,
  Gaussian, PBS, deployment or live authority.

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
