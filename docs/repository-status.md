# Auto-G16 Repository Status

## Current mainline state

Status date: 2026-07-22

Auto-Gaussian 2.5.3 is the prepared maintenance-patch source candidate from
clean local and remote `main` baseline
`042f8aeef665f524ac2c0cbdc47ccbf11a208d2e`. Auto-Gaussian 2.5.2 is the
latest published release. Its annotated tag object
`4aead58529a7786968aea8e9cd7ee10f6e0c8553` resolves to release commit
`09a3cad13b07afdab86a70488d4e0ab78aa6c2d9`; the GitHub Release was published
on 2026-07-20. Earlier tags, checklists, and changelog entries remain immutable
release records rather than pending work.

The first-parent delta from `v2.5.2` to the preparation baseline contains only
PR #45 (`98358c8869f6001fd53756a42344c699cb16ab63`) and PR #46
(`042f8aeef665f524ac2c0cbdc47ccbf11a208d2e`). PR #45 adds the development
handbook, isolated-worktree preflight, exact required-check and Python/CI
contracts, and offline audits. PR #46 adds fail-closed handling for RTwin
terminal snapshots and result-fetch stages, including PBS `qstat` return code
153, finite size-derived timeouts, sanitized stage failures, retained partial
state, and no automatic retry.

The 2.5.3 metadata does not claim current remote CI or branch-protection state.
Those remain external facts requiring independent verification before merge or
release. Historical schemas retain their replay meaning; the fetch-stage
evidence is additive and does not authorize a live operation.

Every planning/review artifact remains `calculation_ready: false`; calculation
nodes remain `executable: false`; the integration overlay remains
non-authorizing. Release publication does not claim a successful real reaction
study, accepted minimum, TS/IRC closure, or real PBS/Gaussian validation. Exact
structure, stereochemistry, charge, multiplicity, method, input, resource,
server-directory, and fresh live approvals remain mandatory for any future
execution.

Repository source under `skills/` is authoritative. A checkout alone says
nothing about deployed copies; machine-local deployment status is an
external fact outside this checkout. Historical synchronization evidence is
retained below, but it is neither a current sync gap nor authority to deploy.

## Current capability and limits

- The `core` profile is fixed to Python 3.13.13. The `chem` profile is fixed to
  Python 3.11.15 with NumPy 2.4.6, Pillow 12.3.0, and RDKit 2026.03.3. Offline
  CI supports Python 3.11 through 3.13. Ordinary compatibility tests run on
  all three versions; the complete source-archive and oversized DAG pressure
  path runs once on Python 3.13; the chemistry job executes an actual RDKit
  structure/conformer/depiction smoke.
- The development handbook requires classification, isolated worktrees,
  preflight, a proportional offline test ladder, exact CI-name auditing and
  separate release, deployment and live authority. Static contract audits
  validate local declarations only.
- RTwin result fetching records bounded stage-specific timeout and failure
  evidence without exposing command details or retrying automatically. A
  partial destination blocks an implicit rerun and requires human review.
- The calculation-DAG validator caches only deterministic replay results for
  immutable content identities within one process. Every explicit binding
  still checks symlinks, size, file SHA-256, schema, payload SHA-256, and
  deterministic reconstruction. No persistent trust cache exists.
- Runtime configuration has an offline closed-schema validator for duplicate
  keys, unknown fields, path classes, parent traversal, and leaf or ancestor
  config symlinks. Reads are descriptor-bound and do not follow path aliases.
  Progressive static checks cover only an explicit high-risk module list and
  do not impose repository-wide formatting churn.
- Private study migration is an external operational plan-review-apply copy
  workflow. Its private manifests are refused inside Git; apply requires an
  exact plan hash, owner-only target, no symlinks, no conflicts, and no
  overwrite. Apply completes a full preflight before target creation and uses
  descriptor-relative no-follow I/O. Destination files are atomically created
  with mode 0600, rehashed after writing, and recorded in an immutable
  destination receipt. It never deletes source data or automatically removes
  a partial copy after an unexpected failure. Plan `/2` scans quoted and
  escaped-space paths incrementally, preserves exact occurrence evidence, and
  blocks ambiguous unquoted-space paths; historical `/1` plans must be rebuilt
  and reviewed and cannot be applied.
- Method-evidence records distinguish reported, internally observed, and
  benchmarked evidence. They do not select or authorize a research method.
- Mechanism discussions, method decisions, operator action cards, and learning
  updates preserve the human decision separately from AI recommendations.
- TS-seed candidates and bounded 1+1 portfolios retain exact target, mapping,
  geometry, review, and supersession provenance without rendering a Gaussian
  input or promoting a candidate.
- Closure-priority plans preserve hard scientific blockers and rank only
  reviewed targets by evidence, initial-guess quality, closure likelihood,
  information value, and practical compute cost.
- Execution batches have stable task identities, a ten-task cap, separate
  physical-attempt and core-hour accounting, diagnosed retry classification,
  uncertain-submission reservation, atomic ledgers, and read-only monitoring.
  They do not submit, retry, cancel, clean up, or change chemistry.
- The `gaussian-v25-integration-review/1` overlay replays every owner validator
  and binds exact evidence, human decision, seed, priority, batch review, and
  ledger artifacts. It cannot weaken a blocker or replace an input/live gate.
- The fixed `/home/user100/SDL` server boundary, non-empty-directory refusal,
  no-deletion policy, exact job-ID cancellation gate, and scheduler-spool
  prohibition are unchanged.
- W2 still lacks authentication, signatures, durable audit logging, chemical
  search, and multi-user enforcement. Declared offline principals are not an
  operating-system security boundary.
- Historical BF3, open-shell, metal, and asymmetric-catalysis records remain
  evidence only. They do not authorize retries, IRC, endpoint claims,
  deployment, or new live work.

## Current engineering validation policy

- The standard local ladder is the timed complete offline suite, focused
  tests, `compileall`, progressive static checks, tracked shell/template
  syntax, `git diff --check`, release hygiene, a `.git`-free source-copy replay,
  and a sensitive-string/private-key/raw-output scan.
- The 1101-node/128-level calculation-DAG pressure case remains part of local
  full and single-version release validation. A dedicated equivalence test
  compares cached and uncached results, and a mutation test proves that an
  already populated cache does not admit size/hash drift.
- Runtime-config tests and migration tests are synthetic and offline. No
  private study directory is scanned, copied, moved, deleted, or printed as
  engineering evidence.
- The published 2.5.2 preparation recorded 690/690 offline tests for both its
  worktree and `.git`-free source archive, with one expected RDKit skip per core
  run. Those are historical machine-local checks for different candidate
  bytes, not current 2.5.3 evidence, a CI guarantee or a scientific result.
- No deployment, SSH, RTwin, PBS, Gaussian, live smoke, submission, retry,
  cancellation, server cleanup, or scientific acceptance action is included.

## Historical and external evidence

These records preserve dated evidence without presenting an old feature
branch, deployment, live observation, or test count as a current scientific
result.

### Feature evidence — 2026-07-19 — commit c46301bdcfc08fef4292abf17cfed256963cc5f1

PR #41 integrated the six offline v2.5 slices: method-evidence contracts,
human scientific decisions, bounded TS seeds, closure-priority planning,
execution-batch governance, and the cross-Skill owner-validation overlay. The
PR did not deploy Skills or perform RTwin/PBS/Gaussian validation.

### Deployment evidence — 2026-07-19 — commit c46301bdcfc08fef4292abf17cfed256963cc5f1

The delegated external record states that repository copies of the four v2.5
owner Skills were synchronized exactly and that the subsequent read-only
named-Skill check reported all 14 repository/deployed pairs synchronized. The
release checklist records this as deployment evidence, not as authority for
another deployment and not as a live scientific result.

### Test evidence — 2026-07-19 — commit c46301bdcfc08fef4292abf17cfed256963cc5f1

PR #41 reported 564/564 offline unit tests, and the exact post-merge commit's
GitHub Offline tests and CodeQL checks passed. This remains dated baseline
evidence rather than a claim about later engineering changes.

## Remaining validation boundary

- A source/deployed drift finding may be inspected read-only. Any required
  synchronization remains a separately reviewed deployment action.
- Private migration apply remains a later operational action bound to its own
  external plan and review; versioned code or tests do not authorize it.
- No release artifact can satisfy scientific readiness, exact input review,
  stage dependency, live approval, execution, or evidence-acceptance gates.
- Every real calculation still requires exact reviewed structure and mapping,
  stereochemistry, charge, multiplicity, method/route, input hash, resources,
  fresh server directory, and operation-specific live approval.
- A TS requires exactly one reviewed intended imaginary mode; IRC validation
  requires both directions to terminate and both endpoints to be structurally
  identified. This release supplies neither result.
