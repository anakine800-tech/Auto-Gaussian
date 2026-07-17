# Auto-G16 Repository Status

## Current mainline state

Status date: 2026-07-18

Auto-Gaussian 2.4.0 release preparation is based on confirmed `origin/main`
commit `69222eb40fc4485392c753b240989719fcec56a4`. That content baseline is
58 commits and 235 changed files after immutable release tag `v2.3.0`. The
annotated `v2.4.0` tag and GitHub Release are separate publication actions and
are not authorized or created by this preparation.

The 2.4.0 source retains the complete 2.3.0 foundation and adds metal TS P0–P5
readiness and candidate closure, offline dual-route conformer discovery,
main-group open-shell state/minimum/result contracts, multiplicity families,
same-spin open-shell TS/Freq/IRC, open-shell reaction networks, and
scientific-maturity owner gates. Compatibility-preserving input receipts `/2`
and `/3` remain non-authorizing; prospective live approvals `/4` and `/5`
define separate single-stage and two-stage exact-scope paths.

Repository source under `skills/` is authoritative. A checkout alone says
nothing about `~/.codex/skills`. Machine-local deployment status is an
external fact outside this checkout. Read-only 2026-07-18 named-Skill dry runs
found one changed packaged file for `auto-g16-chemdraw-pipeline` and two for
`auto-g16-view-rt-win`; no missing or extra files were reported. No deployment
was authorized or performed.

All candidate planning, review, receipt, and adapter artifacts remain
non-authorizing unless the distinct exact live gate is satisfied. They do not
select scientific methods, make calculation nodes executable, accept a TS, or
grant deployment, SSH, PBS, Gaussian, submission, retry, cancellation,
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
- Transition-metal P0–P5 artifacts define offline readiness, input/result
  acceptance, promotion and first-smoke decision boundaries. The reviewed
  candidates remain blocked and no metal input, runtime, or live authority is
  granted.
- Dual-route conformer search is an offline plan/audit layer over supplied
  candidates. It does not execute xTB, CREST, Gaussian, PBS, or SSH and does
  not promote a candidate without a separate exact review.
- Main-group open-shell support is limited to explicitly reviewed
  single-reference doublet/high-spin-triplet states. Multiplicity members,
  minimum families, TS/IRC paths, and reaction-network nodes remain
  state-bound; no cross-state ranking or ground-state inference is permitted.
- Single-stage receipt `/2` can only feed a separately approved `/4`. Each
  two-stage receipt `/3` can only feed a stage-specific `/5`; stage 2 remains
  blocked until accepted stage-1 checkpoint continuity is reviewed.
- W2 still lacks authentication, signatures, durable audit logging, chemical
  search, and multi-user enforcement. Declared offline principals are not an
  operating-system security boundary.
- Historical BF3 and asymmetric-catalysis records are evidence only. They do
  not authorize retries, IRC, endpoint claims, deployment, or new live work.

## Current release-preparation evidence

- Before branch creation, local `HEAD` and `origin/main` were both confirmed as
  exact commit `69222eb40fc4485392c753b240989719fcec56a4` in a clean detached
  worktree. The unique `codex/release-2.4.0-prep` branch was created from that
  commit without switching or modifying the original checkout's local `main`.
- Complete offline validation passed: 522 worktree tests and the same 522 tests
  from a source archive without `.git`, plus compilation, shell syntax,
  release hygiene, diff checks, and both pinned environment checks. Exact
  evidence is recorded in `docs/release-2.4.0-checklist.md`.
- Named-Skill drift evidence is a no-write dry-run plan only. Exact public plan
  hashes and sanitized repository-relative summaries are recorded in the 2.4.0
  checklist; `--apply` was not used.
- Live smoke remains blocked and not authorized. The `/4` single-stage path and
  both `/5` two-stage stages require their own exact inputs, hashes, scope and
  explicit approvals.
- This release preparation performs no push, pull request, merge, tag, GitHub
  Release, deployment, live smoke, SSH, PBS, Gaussian, submission, retry,
  cancellation, or cleanup.

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

### Pd(PHOX) TS20 candidate closure - 2026-07-16

The source-bound replacement review is recorded in
`studies/metal_m4_p0_p1_baseline/pd-phox-ts20-candidate-closure.json`. It
corrects the DOI identity, preserves original SI SHA-256 and coordinate-block
lineage, and records a strict gap ledger. Its status is
`blocked_source_incomplete_no_real_m1`; P5 and all live actions remain blocked.

- Review and commit the 2.4.0 release preparation locally only after every
  offline check and sensitive-string review passes. Push, pull request, merge,
  and CI observation remain separate actions requiring authorization.
- Obtain separate explicit authorization before creating annotated tag
  `v2.4.0` or its GitHub Release.
- Review a fresh exact named-Skill dry-run plan and obtain separate deployment
  authorization before synchronizing either drifted Skill.
- Supply exact inputs, hashes, projects, resources, and separate approvals for
  the `/4` single-stage path or each `/5` two-stage stage before any live smoke.
- Continue W2 authentication, audit logging, chemical search, and service-
  boundary work only through a separately reviewed feature.
- Review one concrete transition-metal M1 case before any M3 runtime or
  promotion design; do not render or submit a metal Gaussian input under the
  current contracts.
- Treat every BF3 retry, IRC, endpoint workflow, deployment, and live smoke as
  a new exact approval scope.
