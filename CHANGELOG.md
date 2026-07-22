# Auto-G16 Changelog

All notable public release changes are recorded here. The project follows
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [2.5.4] - 2026-07-22

### Changed

- Reconciled the mutable README and repository-status pages with the published
  2.5.3 tag and GitHub Release, then advanced every current-version surface to
  2.5.4 under one release-consistency contract.
- Added a root-level `/reports/` boundary and release-hygiene coverage so
  machine-local generated reports cannot enter Git or source-release material.
- Added cross-file version assertions covering `pyproject.toml`, the first
  changelog release, README title/current-release text, repository status, the
  versioned checklist, and compare links.

### Safety

- This documentation and release-hygiene patch preserves all historical
  schemas and release records. It makes no deployment, SSH, RTwin, PBS,
  Gaussian, live-smoke or scientific-success claim and grants no submission,
  retry, qdel, cleanup or scientific authority.

## [2.5.3] - 2026-07-22

### Added

- Added the repository development handbook, isolated-worktree preflight,
  exact required-check contract, Python environment/CI contract audits, pull
  request template, and focused offline regression coverage introduced by
  PR #45.

### Changed

- Aligned the supported Python 3.11–3.13 matrix, source-archive release job,
  chemistry-dependency job, and stable required-check names with locally
  auditable versioned declarations. Static audits remain local declaration
  checks and do not prove current GitHub branch protection or CI success.
- Hardened RTwin terminal snapshot handling for PBS `qstat` return code 153 and
  separated result fetching into bounded, labeled inventory, hashing, staging,
  transfer and verification phases with finite size-derived timeouts,
  sanitized failure diagnostics, retained partial-state evidence, and no
  automatic retry, as introduced by PR #46.

### Safety

- This maintenance patch records offline development and fetch-handling
  hardening only. It makes no claim of deployment, SSH/RTwin/PBS/Gaussian
  execution, successful scientific results, accepted minima or TS/IRC closure,
  and grants no submission, retry, qdel, cleanup or scientific authority.

## [2.5.2] - 2026-07-20

### Added

- Added hash-bound `/2` and `/3` execution ledgers, one-shot live-approval
  successors `/6`–`/11`, exact cancellation approval, and read-only submission
  and cancellation reconciliation without automatic qsub or qdel retry.
- Added resource policy, scheduler snapshot, resource-gate, accounting and
  terminal-receipt contracts that bind exact task, attempt, estimate, cores,
  memory and reviewed walltime before any protected live submission.
- Added owner-replayed `/2` endpoint, checkpoint, minimum-lineage, TS-result and
  IRC-path contracts, plus strict runtime configuration, timed test execution,
  progressive static checks and the private-study migration `/2` workflow.

### Changed

- Classified scheduler, process and transport evidence as explicit
  present/absent/unknown states; unknown evidence cannot prove interruption,
  terminal cleanup or resource release. Result fetching now uses exact
  allowlists, immutable snapshots, no-follow path checks and server-to-Mac
  hash verification.
- Consolidated active monitoring into bounded read-only snapshots, separated
  retryable observations from non-retryable mutations, retained append-only
  freshness/transport evidence and allowed only hash-verified immutable files
  to be reused by incremental fetches.
- Hardened the offline TS/Freq/IRC evidence chain with owner-replayed `/2`
  contracts for exact family/input/job/attempt/terminal/fetch provenance,
  checkpoint continuity, endpoint execution, and mechanism study, charge,
  multiplicity and stable atom-element identity.
- Connected minimum-lineage `/2` to scientific-maturity and thermochemistry
  blocker consumers, and connected TS-result `/2` to recalculation and
  asymmetric-catalysis only through the canonical owner validator.
- Tightened resource-gate, reservation and ledger replay for positive exact
  core-hour estimates and bounded scheduler-clock skew; stale, future-dated,
  forged-age and cross-estimate records fail closed.
- Hardened private migration publication with owner-only atomic file creation,
  source identity checks, destination rehashing and a persisted destination
  receipt. Skill-local runtime configuration remains source-archive
  self-contained while enforcing the root strict loader contract.
- Made private migration `/2` path auditing quote/escape aware and
  occurrence-positioned, retained same-prefix external references, blocked
  ambiguous unquoted-space candidates, rejected Boolean count substitutions,
  and classified NUL-bearing binaries before text-candidate limits.
- Made prospective TS/IRC qualification require endpoint review and path
  acceptance `/2`, including one shared accepted TS `%oldchk` lineage, while
  keeping `/1` artifacts strictly historical and non-qualifying.
- Added bounded streaming for Gaussian log parsing, private migration and
  checkpoint/result snapshots, including plan/review migration passes, plus
  separate size-derived finite transfer and hash budgets and bounded adaptive
  monitoring persistence without active-state whole-log scans.
- Required new endpoint Opt/Freq inputs to replay an endpoint-structure review
  `/2` and the completed IRC job's exact transported TS checkpoint and companion
  manifest; standalone or historical endpoint audits remain non-authorizing.
- Upgraded private migration planning to `/2`: UTF-8 classification and
  absolute-path scanning now cover files of every size with bounded reads,
  occurrence-counted boundary-safe rewrites, while true binary files are
  explicitly classified and copied unchanged.

### Performance

- Reused only deterministic in-process calculation-DAG owner replay for exact
  immutable content identities, retained full path/size/hash/schema checks and
  moved the oversized DAG pressure case to the single source-archive release
  path while preserving Python 3.11–3.13 compatibility coverage.

### Safety

- All hardening and validation in this entry is offline. It performs no SSH,
  PBS, Gaussian, deployment, submission, retry, cancellation, cleanup or live
  scientific acceptance.

## [2.5.0] - 2026-07-19

### Added

- Added evidence-bound method-selection contracts for reusable benchmark
  cases, run observations, method-selection contexts, and evidence briefs.
  The database layer separates reported, internally observed, and benchmarked
  method evidence without inferring or approving a production method.
- Added an offline human scientific decision layer with explicit mechanism
  discussion, method decisions, operator action cards, and immutable study
  learning updates. Human decisions remain distinct from AI proposals and
  from every input or live-action approval.
- Added hash-bound, non-executable TS-seed candidates and bounded 1+1
  portfolios. Each primary and backup seed retains exact target, atom mapping,
  geometry lineage, construction rationale, review status, and supersession
  provenance without rendering or authorizing a Gaussian input.
- Added closure-priority planning that ranks already reviewed calculation
  targets by scientific evidence, initial-guess quality, convergence and
  TS-closure likelihood, information value, and practical compute cost while
  preserving hard blockers and bounded search scope.
- Added the offline `gaussian-v25-integration-review/1` owner overlay linking
  method evidence to an explicit human method decision, mechanism discussion
  to closure hard gates, TS-seed portfolios to exact initial-guess provenance,
  and selected closure calculation nodes to the immutable execution-batch
  review and ten-task ledger.
- Added immutable reviewed `gaussian-execution-batch/1` governance with stable
  scientific-task identities, a ten-task cap, separate physical-attempt and
  core-hour accounting, fail-closed retry classification, uncertain-submission
  reservation, atomic locking, and read-only immediate/60-minute monitoring.

### Changed

- Connected the six v2.5 planning and governance slices through a
  cross-Skill, owner-validator replay rather than copying or weakening their
  individual contracts. Selected closure nodes must retain their exact
  evidence, human decision, seed, priority, batch-review, and ledger bindings.

### Safety

- The v2.5 integration overlay replays owner validators and fixes every
  component and cross-Skill artifact as non-executable and non-authorizing.
  Exact input review, stage dependency evidence, and fresh per-attempt live
  approval remain separate gates.
- Execution-batch planning and tests are standard-library and offline only.
  They add no automatic qsub, retry, scientific change, cancellation, search
  expansion, scheduler cleanup, deployment, SSH, PBS or Gaussian action.
- Release publication makes no claim of a successful real reaction study,
  accepted minimum, TS/IRC closure, or real PBS/Gaussian validation. Exact
  structure, stereochemistry, charge, multiplicity, method, input, resource,
  server-directory, and live approvals remain mandatory before future
  execution.

## [2.4.0] - 2026-07-18

### Added

- Added transition-metal P0–P5 offline readiness contracts, candidate-bound
  M1/input/result review closure, replacement-candidate decisions, and a
  source-audited Pd(PHOX) TS20 case. R33 is explicitly rejected and the
  replacement remains blocked before P2/P5 and every live action.
- Added the offline dual-route conformer-search workflow: exact reviewed R08
  intake, freedom analysis, preregistered A/B route quotas, dependency
  diagnostics, candidate legality ledgers, cross-route clustering/medoids,
  negative-evidence retention, and candidate-only reviewed handoff.
- Added candidate-bound main-group open-shell electronic-state review,
  Cartesian/input/result lineage, minimum Opt/Freq handoff and acceptance for
  reviewed single-reference doublets and high-spin triplets. Open-shell
  singlets, multireference states, metals, unsupported references and inferred
  ground states remain refused.
- Added multiplicity-family planning, per-member protocol/input/result lineage,
  comparison audit, and explicit cross-state non-ranking rules; each member is
  reviewed and accepted independently and no family infers a ground state.
- Added same-spin-surface main-group open-shell TS/Freq/IRC contracts with
  exact state, candidate, route, mode and endpoint bindings. They grant no
  submission authority and cannot reuse ordinary closed-shell evidence.
- Added reviewed open-shell reaction-network contracts and immutable
  recalculation decisions that bind exact state, attempt, input, protocol,
  result and terminal evidence without authorizing an automatic retry.
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
- Added the compatibility-preserving scientific-maturity owner-evidence `/2`
  overlay, manual scientific-evidence receipts/reviews, immutable
  recalculation decisions, and thermochemistry-readiness audits. The overlay
  replays the calculation-plan, mechanism-support, TS-precedent, conformer,
  open-shell and manual-evidence owners and records unresolved lineage instead
  of treating artifact presence as readiness.
- Added raw QST2/QST3 input syntax auditing against exact installed-revision
  evidence. Unsupported syntax, atom-map drift, absent evidence and hand-filled
  success facts fail closed and grant no input-rendering or live authority.
- Added compatibility-preserving open-shell input receipt paths. Generic
  `gaussian-input-approval-receipt/1` remains unchanged; `/2` binds one exact
  reviewed open-shell minimum Opt/Freq handoff and audit, while `/3` binds each
  stage of the separate two-stage Opt/Freq then `Stable=Opt` family.
- Added prospective live approval `/4` for one exact single-stage open-shell
  minimum receipt `/2`, and `/5` for one exact stage receipt `/3`. The `/5`
  family requires separate stage-1 and stage-2 approvals and only permits
  stage 2 after accepted stage-1 checkpoint continuity.

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
- Input review and live approval remain separate: `/2` and `/3` receipts are
  offline, non-authorizing records; `/4` and `/5` are closed exact-scope live
  records and do not alter historical receipt `/1` or live approval `/1`–`/3`
  semantics. The single-stage `/4` and two-stage `/5` paths are not
  interchangeable.
- The two-stage open-shell minimum family forbids `Opt` and `Stable` in one
  Gaussian input. Stage 1 performs Opt/Freq; only its accepted final checkpoint
  may feed coordinate-free `Stable=Opt Geom=AllCheck Guess=Read` stage 2.

### Safety

- The implementation and validation path is offline. It adds no deployment,
  SSH, PBS, Gaussian, submission, retry, cancellation, cleanup or remote-data
  action, and every maturity artifact retains `calculation_ready: false` and
  `no_submission_authorization: true`.
- Exact scientific action authorization remains offline evidence only and
  cannot replace the separately hash-bound live submission approval.
- All metal, conformer, open-shell, multiplicity, reaction-network, maturity,
  receipt, and prospective live-approval work in this release was implemented
  and validated offline. No SSH, PBS, Gaussian, deployment, submission, retry,
  cancellation, cleanup, remote-root override, or server-data deletion is
  authorized by the release metadata.

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

[Unreleased]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.5.4...HEAD
[2.5.4]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.5.3...v2.5.4
[2.5.3]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.5.2...v2.5.3
[2.5.2]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.5.0...v2.5.2
[2.5.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.1...v2.1.0
[2.0.1]: https://github.com/anakine800-tech/Auto-Gaussian/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anakine800-tech/Auto-Gaussian/releases/tag/v2.0.0
