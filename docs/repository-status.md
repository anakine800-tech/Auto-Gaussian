# Auto-G16 Repository Status

## Current mainline state

Status date: 2026-07-16

Auto-Gaussian 2.3.0 release metadata is based on reviewed `main` commit
`1d730218048c52a395b379cbe4653c9e2b8def97`. That content baseline is 36
commits and 106 changed files after immutable release tag `v2.2.0`. The
annotated `v2.3.0` tag and GitHub Release are not part of release preparation
and remain uncreated pending separate explicit authorization.

The 2.3.0 candidate contains ten repository-owned `auto-g16-*` Skills. It
includes W1 reaction intake and literature foundations, W2 immutable knowledge
records and reviewed store/import/export foundations, W3 mechanism network and
mechanism-support contracts, the separate downstream support matrix,
TS-precedent/de novo planning, a deterministic non-executable calculation DAG
and read-only study index, reviewed candidate-target mapping, and narrow
immutable calculation-artifact adapters. It also includes the self-contained
Gaussian learning library, public-repository confidentiality guardrails,
named-Skill packaging, and deterministic Python environment management.

Repository source under `skills/` is authoritative. A checkout alone says
nothing about `~/.codex/skills`. Machine-local deployment status is an
external fact outside this checkout. The read-only 2026-07-16 comparison
reported all ten named packages synchronized, but this does not authorize
deployment or predict the state of another machine or later checkout.

All candidate planning and adapter artifacts remain non-authorizing. They do
not select scientific methods, make calculation nodes executable, accept a TS,
or grant deployment, SSH, PBS, Gaussian, submission, retry, cancellation,
cleanup, or live-smoke authority.

## Current capability and limits

- The `core` profile is fixed to Python 3.13.13. The `chem` profile is fixed to
  Python 3.11.15 with NumPy 2.4.6, Pillow 12.3.0, and RDKit 2026.03.3. Offline
  CI supports Python 3.11 through 3.13.
- The reaction workflow binds reviewed inputs and immutable upstream evidence,
  keeps mechanism exploration distinct from validation, and keeps scientific,
  input-review, live-approval, execution, and evidence-acceptance states
  independent.
- The mechanism-support matrix is a downstream view over the owner support
  gate. It cannot weaken an owner blocker, validate a mechanism, or create or
  promote a calculation-DAG node.
- The calculation plan and read-only study index are deterministic offline
  bookkeeping artifacts. Every node remains `executable: false`; every plan
  remains `calculation_ready: false` with
  `no_submission_authorization: true`.
- The calculation-artifact adapter binds reviewed handoffs and result evidence
  without owning or mutating DAG node identity and without granting staging or
  submission authority.
- Transition-metal M1/M2 artifacts remain observation and review contracts.
  Runtime support and scientific acceptance are refused pending a separately
  reviewed extension.
- W2 still lacks authentication, signatures, durable audit logging, chemical
  search, and multi-user enforcement. Declared offline principals are not an
  operating-system security boundary.
- Historical BF3 and asymmetric-catalysis records are evidence only. They do
  not authorize retries, IRC, endpoint claims, deployment, or new live work.

## Current release-candidate evidence

- Local candidate validation on 2026-07-16 passed all 288 core offline tests,
  Python compilation, tracked shell syntax checks, `git diff --check`, and the
  same 288-test suite from a `git archive` extracted without `.git` metadata.
- The read-only environment check matched both pinned Python profiles and all
  locked chemistry packages. The same check found all ten repository/deployed
  named-Skill packages synchronized.
- A fresh fetch before release-metadata work confirmed `origin/main` at the
  exact candidate content baseline. Offline tests, CodeQL, and Dependency Graph
  succeeded for that remote commit. Open pull requests and open Dependabot,
  Code Scanning, and Secret Scanning alerts were zero at that observation.
- This candidate validation performed no deployment, live smoke, SSH, PBS,
  Gaussian, submission, retry, cancellation, cleanup, tag, or GitHub Release.

## Historical evidence

The records below preserve dated evidence without presenting old feature
branches, deployed copies, live observations, or test counts as current
checkout state.

### Feature evidence — 2026-07-16 — commit 162489b0ed4afee39ed934ef5f045fbddbbbb0cb

PR #23 merged the distinct
`gaussian-reaction-mechanism-support-matrix/1` contract into `main`. The matrix
binds the exact owner support artifact, network, and immutable review; covers
the complete reviewed row-by-support-record space; preserves exclusions and
supersession; and cannot alter owner-gate decisions or create DAG readiness.

### Deployment evidence — 2026-07-16 — commit 90560e9c48ee2d82e5d00c0fee8d61a44b61d566

An explicitly approved historical deployed-copy DAG smoke compared and
synchronized the named packages required by `auto-g16-reaction-workflow`, then
passed three deployed-entry-point offline tests. It retained
`calculation_ready: false`, `no_submission_authorization: true`, and
`live_actions: false`. This is historical external evidence, not proof of the
current candidate or any later deployment state.

### Test evidence — 2026-07-16 — commit 162489b0ed4afee39ed934ef5f045fbddbbbb0cb

The PR #23 baseline passed 280 full offline repository tests under Python 3.13,
including calculation-artifact, TS-precedent, mechanism-network,
reaction-workflow, naming, packaging, and release-hygiene regressions. No live
or deployment action was part of that validation.

## Next approval gates

- Merge release preparation only after its pull-request checks pass and the PR
  is safely mergeable; then verify final `main`, `origin/main`, PR state, and CI.
- Obtain separate explicit authorization before creating annotated tag
  `v2.3.0` or its GitHub Release.
- Continue W2 authentication, audit logging, chemical search, and service-
  boundary work only through a separately reviewed feature.
- Review one concrete transition-metal M1 case before any M3 runtime or
  promotion design; do not render or submit a metal Gaussian input under the
  current contracts.
- Treat every BF3 retry, IRC, endpoint workflow, deployment, and live smoke as
  a new exact approval scope.
