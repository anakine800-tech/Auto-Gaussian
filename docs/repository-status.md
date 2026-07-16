# Auto-G16 Repository Status

## Current mainline state

Status date: 2026-07-16

Baseline: `main` at commit
`162489b0ed4afee39ed934ef5f045fbddbbbb0cb` (merged PR #23).

The latest release is Auto-Gaussian 2.2.0, published on 2026-07-15. The
`v2.2.0` release artifact is immutable release history. The reviewed `main`
branch is the publishable source line. Source committed after the release tag
is Unreleased after 2.2.0 until a later release is cut.

The current `main` source contains ten repository-owned `auto-g16-*` Skills.
It includes W1 reaction intake and literature foundations, W2 immutable
knowledge records and reviewed store/import/export foundations, W3 mechanism
network and mechanism-support contracts, the separate downstream mechanism-
support matrix view, deterministic non-executable calculation planning and
study indexing, and the narrow offline calculation-artifact adapter.

Repository source under `skills/` is authoritative. A checkout says nothing
about the state of `~/.codex/skills`: machine-local deployment status is an
external fact outside this checkout and must be established by a read-only
named-Skill comparison. Synchronization remains a separate, explicitly
reviewed action and is not authorized by this document.

All current planning and adapter artifacts remain non-authorizing. They do not
select scientific methods, make calculation nodes executable, accept a TS,
or grant deployment, SSH, PBS, Gaussian, submission, retry, cancellation,
cleanup, or live-smoke authority.

## Current capability and limits

- Offline Python support is 3.11 through 3.13. Core audit and validation paths
  use the standard library; optional ChemDraw, depiction, and conformer paths
  use the minimum versions in `requirements/chemistry.txt`.
- The reaction workflow binds reviewed inputs and immutable upstream evidence,
  keeps mechanism exploration distinct from mechanism validation, and keeps
  scientific, input-review, live-approval, execution, and evidence-acceptance
  states independent.
- The mechanism-support matrix is a downstream comparison view over the owner
  mechanism-support gate. It cannot weaken an owner blocker, validate a
  mechanism, or create or promote a calculation-DAG node.
- The calculation plan and read-only study index are deterministic offline
  bookkeeping artifacts. Every node remains `executable: false`; every plan
  remains `calculation_ready: false` with
  `no_submission_authorization: true`.
- Transition-metal M1/M2 artifacts remain observation and review contracts.
  Runtime support and scientific acceptance are still refused and require a
  separately reviewed extension.
- W2 still lacks authentication, signatures, durable audit logging, chemical
  search, and multi-user enforcement. Declared offline principals are not an
  operating-system security boundary.
- Historical BF3 and asymmetric-catalysis records are evidence only. They do
  not authorize retries, IRC, endpoint claims, deployment, or new live work.

## Historical evidence

The records below preserve dated evidence without presenting old feature
branches, deployed copies, or test counts as current checkout state.

### Feature evidence — 2026-07-16 — commit 162489b0ed4afee39ed934ef5f045fbddbbbb0cb

PR #23 merged the distinct
`gaussian-reaction-mechanism-support-matrix/1` contract into `main`. The matrix
binds the exact owner support artifact, network, and immutable review; covers
the complete reviewed row-by-support-record space; preserves exclusions and
supersession; and cannot alter owner-gate decisions or create DAG readiness.
This baseline also contains the previously merged calculation-plan,
study-index, candidate-target mapping bridge, and calculation-artifact adapter
slices.

### Deployment evidence — 2026-07-16 — commit 90560e9c48ee2d82e5d00c0fee8d61a44b61d566

An explicitly approved historical deployed-copy DAG smoke compared the named
packages required by `auto-g16-reaction-workflow`, synchronized reviewed
packages using exact dry-run plan hashes, and passed three deployed-entry-point
offline tests. It retained `calculation_ready: false`,
`no_submission_authorization: true`, and `live_actions: false`. This is an
external historical fact, not proof that any current machine deployment still
matches repository source.

### Test evidence — 2026-07-16 — commit 162489b0ed4afee39ed934ef5f045fbddbbbb0cb

The merged PR #23 baseline passed 7 focused mechanism-support-matrix tests,
5 named-Skill packaging tests, and 280 full offline repository tests under
Python 3.13. Calculation-artifact, TS-precedent, mechanism-network,
reaction-workflow, naming, and release-hygiene regressions were included. No
live smoke, SSH, PBS, Gaussian, submission, cancellation, cleanup, deployment,
or historical-artifact rewrite was part of that validation.

### Test evidence — 2026-07-15 — commit 90560e9c48ee2d82e5d00c0fee8d61a44b61d566

The calculation-DAG deployed-copy smoke passed deterministic plan/index,
reviewed candidate-target mapping, and adversarial refusal coverage using only
sanitized temporary artifacts. The evidence validates that exact historical
scope only and grants no scientific or execution authority.

## Next approval gates

- Continue W2 authentication, audit logging, chemical search, and service-
  boundary work only through a separately reviewed feature.
- Review one concrete transition-metal M1 case before any M3 runtime or
  promotion design; do not render or submit a metal Gaussian input under the
  current contracts.
- Treat every BF3 retry, IRC, endpoint workflow, deployment, and live smoke as
  a new exact approval scope.
- Change GitHub branch-protection settings only after separate authorization
  for the exact proposed configuration.
