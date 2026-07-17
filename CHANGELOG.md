# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Added closed `gaussian-scientific-maturity-review/1` and
  `gaussian-scientific-maturity-gate/1` contracts plus a standard-library-only
  builder, validator, action check and deterministic DAG-node maturity
  projection over an exact validated calculation plan.
- Added auditable user literature/mechanism intake, ten-lane search saturation,
  exact edge/channel evidence classes, two-endpoint minimum acceptance,
  one-candidate pilot and task/core-hour/concurrency budgets, resource-upgrade
  evidence, TS/IRC/endpoint validation state, common-reference thermochemistry
  and the closed stop-condition set.
- Added prospective `gaussian-ts-irc-workflow/2` creation and
  `auto-g16-live-submission-approval/2` scope. TS family creation and PBS
  preflight/submission reuse the reaction-workflow maturity owner validator.
- Added `gaussian-scientific-action-authorization/1`, an offline-only exact
  binding of one passed scientific gate to one DAG node, Gaussian input hash,
  project, work kind, resource tier and task/core-hour/concurrency request.
- Added owner-built `gaussian-ts-irc-path-acceptance/1`, which reconstructs
  the accepted TS mode and both direction-specific IRC endpoint audits from
  their exact input/log/result/job/checkpoint sources. Endpoint minimum and
  thermochemistry acceptance remain later independent gates.

### Changed

- Extended the named-Skill packaging regression smoke for the scientific
  maturity slice. A temporary installed root now proves that the deployed
  reaction-workflow owner CLI and schema are present and that deployed
  `auto-g16-ts-irc` and `auto-g16-rtwin-pbs` consumers load that exact owner
  validator. Documentation now distinguishes ordinary self-contained Skill
  deployment from optional external-file deployment manifests.
- Formal TS input and submission now fail closed unless both exact endpoint
  structures are accepted Gaussian minima with normal termination, converged
  Opt, complete Freq, zero imaginary frequencies, identity/mapping review and
  retained checkpoint/coordinates. Historical `/1` records remain immutable
  and replayable.
- Missing direct precedent may open only one explicitly reviewed `simple`
  pilot after the endpoint gate; it does not replace mechanism-support or
  TS-precedent owner validation and cannot support a formal mechanism claim.
- Scientific approval summaries now lead with maturity, evidence, endpoints
  and blockers before route, resources and input hash.
- Minimum acceptance now replays exact bound raw logs through the existing
  Gaussian parser and compares the parsed result, XYZ, element order and
  mechanism-owner atom mapping. Hand-written or merely rehashed success facts
  cannot open the TS gate. Historical TS-family `/1` artifacts are replay-only
  for new IRC planning, and protected TS/scan/IRC routes require an explicit
  work classification.

### Safety

- The implementation and validation path is offline. It adds no deployment,
  SSH, PBS, Gaussian, submission, retry, cancellation, cleanup or remote-data
  action, and every maturity artifact retains `calculation_ready: false` and
  `no_submission_authorization: true`.
- Exact scientific action authorization remains offline evidence only and
  cannot replace the separately hash-bound live submission approval.

## [2.3.0] - 2026-07-16

### Changed

- Added deterministic `core` (Python 3.13.13) and `chem` (Python 3.11.15)
  interpreter profiles, exact chemistry dependency locking, a PATH-independent
  launcher, runtime/package self-checks, and interpreter-aware named-Skill
  deployment drift reporting. These changes are local and offline only; they
  do not alter RTwin, Windows, Gaussian or PBS safety gates.

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
- Closed `gaussian-reaction-calculation-target-mapping-review/1` and
  `gaussian-reaction-calculation-node-update/1` contracts plus deterministic
  builder/validators for one exact feature-3 candidate-target import mapped by
  human review to the DAG-owned `{study_id, plan_id, node_id}` locator. Version
  `/1` is append-only and restricted to `candidate_inventory` on a
  `ts_candidate`; it never treats `external_target_key` as `node_id`, accepts
  absolute/null DAG references, mutates a plan, or promotes readiness.
- Owner-valid but blocked or reviewed-with-blockers mechanism support now
  retains the network availability blocker, normalized owner descriptions and
  `mechanism_support_not_promotable`; the study index resumes at owner review
  instead of prematurely suggesting channel mapping. Node-update validation
  also rejects mapping-review/update root reinterpretation.
- A closed standard-library-only `gaussian-reaction-mechanism-support/1`
  builder/validator with exact W1, mechanism-network, knowledge-snapshot,
  finalized-literature and immutable-review bindings; deterministic claim and
  location hashes; complete edge/channel scientific review; preserved negative
  evidence; and separate hypothesis-exploration and mechanism-claim-support
  decisions.
- A separate closed standard-library-only
  `gaussian-reaction-mechanism-support-matrix/1` view with exact owner-support,
  mechanism-network and immutable-review bindings; complete row-by-support-
  record coverage; native-cell anti-forgery checks; explicit exclusions and
  supersession; and evidence-gate-compatible downstream review targets.
- Exact mechanism-support binding in `gaussian-ts-precedent-map/1` plus a
  source-free de novo endpoint/QST, scan or reviewed-rebuild planning path for
  exploration-eligible novel hypotheses.
- A standard-library-only offline calculation-artifact adapter in
  `auto-g16-reaction-workflow`, with closed schemas for stable candidate-target
  imports, exact reviewed candidate/protocol-to-input handoffs,
  blocked/electronic-only energy records and lineage, sanitized job
  observations, and immutable six-artifact attempt links with an exact bound
  TS mode-review file.
- Deterministic sanitized fixtures and adversarial tests for exact source
  hashes/sizes/payloads, candidate/XYZ/protocol/input drift, unsupported
  variants, strict JSON, symlinks, overwrite refusal, specialist-validator
  delegation, and fully rehashed derived-fact or preserved-classification
  forgery.
- Narrow TS-specialist helpers now own parsed-result and terminal
  classification recomputation plus exact mode-review geometry arithmetic;
  the adapter also refuses parsed element/atomic-number/order drift from the
  reviewed input handoff.
- Closed named-Skill deployment manifests and a fail-closed standard-library
  synchronizer now package repository-root contracts and the asymmetric owner
  validator without duplicating their version-controlled sources. Temporary
  installed-root tests import the deployed adapter and validate a sanitized
  artifact through the packaged schemas and specialist validator.

### Changed

- Clarified the post-2.2.0 release boundary, Python 3.11–3.13 support, and
  current-versus-historical repository status. Offline CI now covers Python
  3.13, pins GitHub Actions to audited full commit SHAs, and resolves the
  optional chemistry stack through a separately verified constraints file
  while preserving user-facing minimum dependency versions.
- Treat absence of direct literature precedent as a visible
  `novel_hypothesis_no_direct_precedent` evidence gap rather than automatic
  exclusion from reviewed computational exploration. Analogy and internal
  rationale still do not support or validate a mechanism claim.
- Reserve `gaussian-reaction-mechanism-support/1` for the merged evidence gate.
  Experimental PR #19 matrix semantics migrate only by an explicit rebuild
  into `gaussian-reaction-mechanism-support-matrix/1`; historical immutable
  artifacts are not renamed, aliased, or rewritten.

### Safety

- The calculation-planning slice separates scientific readiness, input-review
  readiness, live-approval readiness, execution state, and evidence
  acceptance. Every node remains non-executable; every artifact retains
  `calculation_ready: false` and `no_submission_authorization: true`.
- This slice does not infer chemistry, choose a protocol, construct geometry,
  render an input, create a server project or job, or perform Gaussian, SSH,
  PBS, submission, retry, cancellation, deletion, deployment, or other live
  action.
- Mechanism-support, mechanism-support-matrix and TS-planning artifacts remain
  `calculation_ready: false` and `no_submission_authorization: true`; de novo
  plans contain no source precedent or source coordinates and grant no method,
  Gaussian, PBS, deployment or live authority.
- Adapter artifacts retain `calculation_ready: false` and
  `no_submission_authorization: true`. The adapter implements no DAG plan or
  node mutation, staging, SSH, PBS, Gaussian, retry, cancellation, cleanup,
  deployment, or live-smoke action.
- Named-Skill synchronization requires the exact hash of a reviewed dry-run
  plan plus explicit `--apply --confirmed`, rejects symlinks and path escape,
  and refuses rather than deletes unexpected installed files.

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

[Unreleased]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/v2.0.0
