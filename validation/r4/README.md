# Auto-G16 R4 directed Linux evidence candidate

## Task contract and disposition

Feature development, v3 validation support, L3 CI/boundary review; not BUS-managed.
Task `01a0a413-60be-7641-a817-5156c3205437`, isolated branch
`codex/v31-r4-linux-harness`, base `3116d1f1919eff164ef3593171d0ed7f42c778b5`.
The parent task `01a09f0f-11ed-7d53-a902-a46f0bad8762` controls independent review
and subsequent single publication. Local implementation and focused tests are
allowed; this Executor must not push, start CI, merge or execute Linux/science.
The exact Owner request and finite interpretation are retained in
`owner-request-and-scope.json`; it is evidence, not identity attestation or a
production authority token. Its SHA256 is
`b5d2bf7385c5eeeeb0abdfb30460ac61d43794d98d04daf01703ea239925b1cb`.

Allowed changes: `validation/r4/**`, `.github/workflows/r4-linux.yml`,
`config/auxiliary-workflows.json`, `scripts/audit_ci_contract.py`, and
`tests/test_audit_ci_contract.py`. Product, original workflow, required checks
and selector remain unchanged. CI-control selection may require legacy-release;
record that result without running full discovery or claiming PR/release readiness.

## Frozen product and preparation lineage

Product HEAD `8d49ef23e7c74c4333c551e81461e3f0921948ab`, tree
`6141c8ef3764fa54d1b5705bc303b8c9f6abc0c9`. Binding retains all 437 tracked
product/import/fixture files, including real factory/consumer tests. New wrapper
source SHA256 `cb3c0b5f129e944c4ffd24ec1144b066fd619ebd32a19949a933d3611aa71cf6`.
Probe SHA256 `d06b155a2b0be80c9ef6fd76ec70939841394e8e55bbfe9d12c16e5466303036`.
The old source remains separately bound. No product source is copied or edited.

This package adapts external reviewed candidate2, manifest SHA256
`c66c57b9e15e2168164b6bb6446407e6b9a680a85394dc231c5e03828afb21f7`, binding SHA256
`a2192ffbea73bc21bdb3f6c5a7dbec97e12217a8a781aa65dd70d565d58d40a3`.
That original package and its LIMITED_STATIC_PASS evidence remain immutable and
supersede neither this candidate's review nor its pending Linux execution.

The observer, product factory adapter, inert C actor, 28-case inventory and
synthetic evidence text retain their candidate2 bytes. Only the runner adapts
scope replay and per-UID process budgeting. New hosted launcher/support and
finite provisioning helper instantiate the reviewed run plan on actual hosted
Ubuntu 24.04. Binding package hashes cover these runtime files, plan and exact
Owner attachment. Binding has no self-hash cycle; the reviewed Git HEAD/tree
binds binding, workflow and documentation. The auxiliary registry hashes the
workflow, and accepts only its one exact branch/job/trigger declaration.

## Single execution and evidence

Only the ten ordered names in `run-plan.json` may execute; `host_match` first,
then `large_q`, six wrong-host dimensions, runtime-root-before-child and
publication-data-root drift. Stop at the first failure. No rerun: the launcher
requires `push`, this exact branch, repository identity and `run_attempt=1`.
No workflow_dispatch/PR/main expansion, service, container or self-hosted runner.
The parent must publish the frozen product ref before the reviewed validation
ref; an absent product ref is a failure, not permission to select another ref.

The launcher first verifies both checkouts, package files, actual CI environment,
fixed paths and tool bytes. It retains actual machine/boot IDs, numeric-process
mountinfo, namespace identities, Ubuntu version, Python/tool identity and UID
thread observations before deriving any runtime scope. The scope can be replayed
from `run-plan.json`, the exact Owner attachment, binding and platform bytes.
It does not invent a future observation or approval hash.

Before the first fixture mutation, the launcher saves actual no-follow FD
observations for `/`, `/opt`, `/home`, the runner UID/GID and both top-level
target absences. It records failed opens/reads with the affected path and first
error, then evaluates the trusted `/` and `/home` boundaries and both absences.
The parent descriptors remain open through the ordinary-runner creation step.

The ordinary runner creates only absent `/opt/auto-g16-fixtures` and its `bin`
through the fixed `/opt` descriptor. It checks the new top's runner UID/GID,
0700 mode and named inode before creating the leaf, and records/compares both
new directory identities. It does not change `/opt` permissions/ownership,
chown any existing entry, or fall back to sudo after a failure. Writable `/opt`
is not treated as a privileged trusted parent.

One bounded `sudo` helper opens only the root-owned, non-group/world-writable
`/` and `/home` chain. It records each parent before its rejection predicate,
creates only absent `/home/user100` and `SDL`, and changes ownership only via
new directory descriptors. The root entrypoint never opens `/opt`. No account
changes, installation, existing-path chown, deletion, network/scientific call
or retry. Both ordinary and privileged creation records are retained; the
launcher checks all four final root identities against their original new FDs
and includes both records in platform/scope binding. Partial failure retains
its first error and every newly created directory without rollback.

The root helper self-times out after 10 seconds; launcher wait is 15 seconds,
and ambiguous timeout stops with retained UNKNOWN. The ordinary runner
exclusively creates the inert actor at the fixed product fixture executable
path. The harness invokes unchanged rendered Scheduler/3 source/config transport
and the real bound product consumer.

### First hosted failure and bounded correction

The first run `34966004304` of `d6b6cc809f72f213fcf479de5c9955e8e8a82077`
failed in the common `/opt`/`/home` ownership predicate before sudo or any case.
Its generic exception did not identify the actual rejected path, UID or mode;
those observations remain NOT_ACQUIRED. Original logs and candidate are retained.
The corresponding official image-tag script configures writable `/opt`, which
explains the incompatible preset but does not reconstruct that VM's observation:
[runner-images ubuntu24/20260907.300 configure-system.sh](https://github.com/actions/runner-images/blob/ubuntu24/20260907.300/images/ubuntu/scripts/build/configure-system.sh).

The parent explicitly authorized this local diagnostic/provisioning correction
and independent incremental review. No GitHub rerun or automatic execution is
permitted. A subsequent parent-controlled run must bind the reviewed new
candidate and preserve the first failure. The ten cases, fixed product, run-plan,
Owner attachment, workflow and all runtime budgets remain unchanged.

Per case: 45 seconds; whole harness: 1500 seconds plus 15-second timeout cleanup;
CI job: 26 minutes. Compile once: 30-second outer cap, 35-second wait. RLIMIT_NPROC
is actual per-real-UID baseline thread count plus 32, capped at 256; the runner
rechecks at least 16 remaining slots immediately before setting its limit.
This is a finite limit and observation, not a reservation against other runner
processes. Contention stops or produces a retained failure. Other inherited
limits cover individual file size, memory, descriptors, CPU and core dumps.
Inventory checks (4096 entries / 256 MiB) are post-run evidence thresholds, not
a claimed kernel-enforced aggregate filesystem quota.

Each synthetic descendant has a finite self-exit; only exact owned children are
signalled by pinned PID/pidfd and reaped with exact waitpid. Preserve first errors,
cleanup errors, all logs, manifests, case files and drifted originals. Artifacts
include only the fixed supervisor/evidence, actor and ten exact project paths.
No filesystem cleanup is performed by the harness.

`publication_data_root_drift` alters the data root while the actor is held before
reaping. It does not prove deterministic timing between pending-file write and
final hard link. That precise window remains a separate product offline
fault-injection claim, with no ptrace/new synchronization or inventory expansion.
Synthetic host/Q evidence never qualifies a production host or real xTB.

## Local validation

Only `tests.test_audit_ci_contract` and `validation.r4.test_hosted_support`, static
Python/shell parsing and the static CI audit are in this development pass. Tests
cover rehashed trigger/job widening, required-check preservation, rerun/context
rejection, finite thread budget, scope derivation, package identity, duplicate
JSON and fresh-directory/no-follow rejection using private temporary directories. The
incremental cases cover unprivileged writable-parent creation without chown,
permission denial, rejected top identity before leaf creation, actual observation
retention on an open failure, both initial absences and the retained home trust
boundary.
No C compilation, product test rerun, real Linux harness execution, publication
or production qualification is implied. An independent review of the final
HEAD/tree and hashes precedes parent-controlled publication.
