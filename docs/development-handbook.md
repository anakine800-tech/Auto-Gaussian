# Auto-G16 development handbook

This handbook is the operating sequence for repository development. It links
the binding rules and specialist designs instead of restating their technical
contracts. If this handbook conflicts with [`AGENTS.md`](../AGENTS.md), the
repository rules win. Engineering internals remain in
[`engineering-maintenance.md`](engineering-maintenance.md), and a release uses
the applicable versioned checklist such as
[`release-2.5.2-checklist.md`](release-2.5.2-checklist.md).

## 1. Classify the task before changing files

Choose exactly one primary class and record it in the task and pull request:

- **Feature development** changes behavior, contracts, schemas, commands, or
  developer workflow. It uses one isolated task under section 2, one linked worktree,
  and one unique `codex/` branch.
- **Maintenance patch** preserves intended behavior while fixing a defect,
  dependency, security, compatibility, documentation, or release-hygiene
  issue. It follows the same isolation unless it is a tiny related follow-up
  in the existing feature task.
- **Scientific workflow or run task** prepares, submits, monitors, fetches, or
  interprets a study. Operational inputs, private data, job evidence, logs,
  checkpoints, and approvals stay outside public versioned development unless
  an existing schema explicitly defines a sanitized repository artifact.

Versioned code review and live/private operations are separate authority
domains. A branch, commit, PR, CI result, review, merge, tag, or release never
authorizes Skill deployment, SSH, RTwin, PBS, Gaussian, submission, retry,
qdel, cleanup, scientific acceptance, private-data migration apply, or a live
smoke. Follow the exact scientific and server gates in `AGENTS.md` and the
owning Skill.

## 2. Bind task, worktree, branch, and integration

The normal mapping is one-to-one:

1. one independently reviewable change = one Codex app task, or one qualified
   Executor task/run under the conditional route below;
2. that task = one linked Git worktree;
3. that worktree = one unique short-lived `codex/<purpose>` branch;
4. that branch = one PR and one review/integration decision.

For BUS-managed development, bind **1 Control Issue + 1 task/run + 1
worktree + 1 `codex/` branch + 0/1 PR + 1 integration disposition**. Subject
to repository contracts and Owner authority, the latest valid CTRL is the
Executor's mutation authority. EXEC is execution evidence, not authority for
another mutation; REVIEW PASS is evidence, not merge authority; and a FIX
requires a new CTRL. Chat history is not canonical project state: the Control
Issue remains the control ledger, while the PR remains the diff and evidence
surface.

An independently testable subtask receives its own task/worktree/branch. A
small related follow-up remains in the original feature context. Do not reuse
one branch in active worktrees, switch a shared checkout to simulate
isolation, or carry unnamed uncommitted changes. Integration occurs from the
stable checkout only after the feature commit and evidence are frozen.

Archive or close the Codex task only after its final state, commit, integration
disposition, and residual blockers are recorded. Worktree removal and branch
deletion are explicit local cleanup actions after integration or abandonment;
neither authorizes remote branch deletion.

### Conditional qualified Executor CLI route

Conversational requests for a new isolated task continue to use the Codex app
worktree route in `AGENTS.md`. An unavailable app capability is a reported
limitation, not permission to fall back to CLI or switch the stable checkout.
The route below is only for a separately qualified development Executor with
explicit Owner-approved installation, configuration, and permissions
qualification and a separately bounded pilot. This governance document neither
qualifies a current host/dispatcher nor activates production. It specifies
required outcomes, not the host dispatcher's internal implementation.

Before any development effect, the Executor must:

1. Verify repository name and numeric identity, read the complete canonical
   Control Issue body and all comments, and independently read packet comment
   IDs to compare exact bytes. Validate the latest canonical CTRL, including
   task, lane, epoch, consumes chain, base, exact branch, allowed files and
   finite actions against the higher-priority contracts and Owner Gate. Stop
   on missing, malformed, edited, stale, ambiguous, or terminal authority.
2. Pin actual remote `main` and the approved base; verify the stable checkout
   is clean and at that base. Bind exactly one real Executor-owned task/run ID
   to the Control Issue/CTRL, one uniquely owned physical linked worktree, one
   unique `codex/` branch, and at most one PR. Persist this mapping; do not
   invent a Codex app task ID. CLI creation is limited to the exact authorized
   fresh worktree and branch, never a shared-checkout branch switch or reuse
   of another task's worktree. Before candidate work starts, verify its branch,
   HEAD/tree, clean state, physical containment, and no-follow identities.
   Unknown identity, main/base drift, dirty or detached state, symlinks, and
   existing ambiguous branch/worktree ownership fail closed. Do not reset,
   rebase, relaunch, or repair these conditions automatically.
3. Persist run/state and launch intent before starting a child. Reconcile the
   canonical ledger and durable local evidence first: an existing EXEC or a
   terminal GATE cannot cause an automatic task restart; UNKNOWN retains all
   evidence and never authorizes retry. A new process or run ID cannot erase
   these stop conditions. FIX still requires a new CTRL; a terminal task needs
   a new explicit Owner Gate establishing a new task under section 9.

Qualification must keep model commands and candidate tests/hooks isolated from
the original Git metadata, stable and sibling worktrees, Publisher/Relay
secrets and state, and network access. Repository writes remain limited to the
exact authorized files. Candidate tests/hooks may use only separately approved,
credential-free scratch that preserves the same isolation boundaries; scratch
approval grants no additional repository-write or publication authority.
Finite Git/publication effects belong only to the qualified
Executor under CTRL; they do not give model commands or candidate code those
capabilities. Required hooks must run unchanged and cannot be skipped or
replaced by a claimed equivalent check. Hook isolation and the exact signing
and Git configuration need separate qualification; incompatibility is a
blocker, not authority to disable hooks, signing, or configuration protections.

Use the existing preflight, staged sensitive/private scan, exact-base/head
selector and owned validation, review, CI, integration, terminal disposition,
and explicit cleanup rules in this handbook unchanged. Freeze the candidate
before authoritative selection, retain proportional validation and full-run
deduplication, and never turn a selector error into full discovery. The
Executor may perform only finite CTRL-authorized development effects. It must
independently verify exact commit/tree, remote ref, PR identity and canonical
EXEC readback, then stop after EXEC. It cannot automatically produce REVIEW,
FIX CTRL, merge, terminal GATE, or cleanup; those remain with their separately
authorized owners.

This route changes no Relay behavior, BUS packet kinds or serialization,
database, runner implementation, CI architecture, validation selection,
historical Control Issues, or scientific/runtime/deployment/live authority.
Qualification and pilot evidence remain separate from this document's review
and merge; neither substitutes for the other.

## 3. Development preflight

Before editing, read `AGENTS.md` completely. From the repository root run:

```bash
./scripts/python core scripts/dev_preflight.py
./scripts/python core scripts/dev_preflight.py --json
./scripts/python core scripts/dev_preflight.py --require-clean
```

The script locates the Git root when `--repo` names any subdirectory inside the
worktree; callers outside the root may invoke the script by absolute path.

The preflight is offline, read-only, and deterministic. It checks the branch,
linked-worktree status, staged/unstaged/untracked classification, required
development files, risky private/runtime path classes, known test modifiers,
and live/deploy/submit-like environment-variable names without reading their
values. Exit `0` means no blocker (warnings may remain), `1` means a policy
blocker, and `2` means the repository could not be inspected safely.
Use `--require-clean` for a clean-tree handoff gate; it promotes any staged,
unstaged, or untracked entry from the normal ownership warning to a blocker.

Record the starting commit and clean/dirty classification. A dirty tree is not
automatically discarded: identify ownership, refuse unrelated changes, and
move the new task to a clean isolated worktree if ownership is unclear.

## 4. Configuration and test isolation

- Keep real credentials, host configuration, private studies, raw outputs,
  checkpoints, job evidence, scratch, and machine-specific paths outside Git.
  Use only placeholder `config/*.example` files in the repository.
- Use `./scripts/python core ...` for standard-library development and the
  explicit `chem` profile only when RDKit/NumPy/Pillow coverage is required.
  Record any coverage modifiers such as `AUTO_G16_SKIP_PRESSURE_TESTS`.
- Run `./scripts/python check --profile core` (and `--profile chem` when that
  profile is in scope) to prove an installed local profile. Run
  `./scripts/python core scripts/audit_python_contract.py` separately to audit
  the static supported-minor, registry, environment, lock, CI, and required-
  check declarations. The static audit does not prove interpreter availability,
  remote protection, or a successful CI run. If Python 3.12 is unavailable
  locally, record that gap explicitly and require the 3.12 PR matrix result;
  do not install it from the network solely to complete local evidence.
- For real local Draft 2020-12 coverage, use the reviewed test-only entrypoint
  in [`local-draft-validation.md`](local-draft-validation.md). It discovers
  only explicit or conventional existing isolated environments, verifies all
  exact pins in `requirements/schema-validation.lock.txt`, and then runs the
  ordered inventory owned by CI with `AUTO_G16_REQUIRE_JSONSCHEMA=1`. A missing
  or drifted environment is `BLOCKED`, never a skipped or inferred pass. The
  entrypoint never creates an environment, installs a package, or adds the
  validator to `core` or `chem`.
- Tests and fixtures must be offline and synthetic or release-cleared. A unit
  test must never contact SSH/RTwin/PBS/Gaussian, deploy, submit, cancel,
  migrate private data, or clean a server.
- A live smoke is not a test-suite side effect. It requires separate exact
  approval for target, input/hash, resources, side effects, success/stop
  criteria, retained evidence, and cleanup policy.

## 5. Implement the smallest coherent slice

Preserve versioned schema semantics and reuse the owning validator or Skill;
do not copy or weaken safety gates. Include behavior, focused regression tests,
and documentation in the same feature. Keep compatibility changes explicit
and keep unrelated formatting or refactoring out of the diff.

## 6. Validation ladder and deduplication

Use the least costly check that can falsify the change, in order:

1. syntax/config parsing and `git diff --check`;
2. focused unit tests for changed behavior and adversarial boundaries;
3. adjacent tests for the owning helper, policy, release hygiene, or workflow;
4. offline integration/regression fixtures and dry runs;
5. the full offline suite when risk or release readiness warrants it;
6. an explicitly approved live smoke only when offline evidence cannot close
   a named live-only gap.

Focused and affected validation are the default development feedback. Full
regression is integration/release attestation, not the routine loop for an
ordinary v3 edit. Selector, control-plane, or safety-evidence changes may
conservatively escalate to `legacy-release` full validation. Selection remains
fail-closed: unknown modern ownership and invalid or non-authoritative
selector inputs stop before tests. Reviewed conservative routes can require
`legacy-release`, but an error never authorizes full discovery. Do not repeat full validation for the same frozen
candidate. A running, silent, or slow runner is not failed and does not
authorize a rerun.

Typical commands are:

```bash
./scripts/python core -m compileall -q scripts tests
./scripts/python core scripts/static_quality.py
./scripts/python core scripts/audit_ci_contract.py
./scripts/python core scripts/audit_python_contract.py
./scripts/python core scripts/run_tests.py tests.test_dev_preflight tests.test_audit_ci_contract
./scripts/python core scripts/run_tests.py --full --top-slow 20 --slow-threshold 1.0
bash -n scripts/check_rtwin_connection.sh scripts/probe_gaussian_server.sh templates/g16_job.pbs.template
git diff --check
```

Do not multiply equivalent evidence. All three Python matrix jobs run bounded selected compatibility evidence.
For an authoritative `legacy-release` decision only, the Python 3.13
`source-archive-release` job is the sole complete-full owner on pull requests.
Complete full attests the PR candidate; post-merge main pushes retain bounded
compatibility, static archive verification, and chemistry checks but never
repeat complete discovery. The runner
requires explicit `--full` for complete discovery (including a legacy
selection); `--compatibility --selection ... --base ... --head ...` selects
the bounded compatibility inventory for a legacy candidate. Unsupported CI
events or missing exact identities fail fast without running tests. Once release metadata and the
candidate bytes are frozen, run the versioned checklist's **final complete
release validation exactly once**. If bytes change afterward, that evidence is
invalidated: review the delta and schedule one new final run for the new frozen
candidate, rather than repeatedly running the heavy ladder while editing.

For every run record exact command, interpreter/profile, commit or tree hash,
start time, exit code, test total/skip/failure counts, wall time, and coverage
modifiers. Historical README, task, or PR totals are context, never current
evidence.

## 7. Review levels, duties, and blockers

Select the highest applicable review level:

- **L1 — local:** documentation, tests, or low-risk tooling with no contract,
  security, live, private-data, or release effect. Author self-review plus
  focused and adjacent evidence is sufficient before normal PR review.
- **L2 — contract/compatibility:** schemas, validators, CI, configuration,
  immutable artifacts, migrations, packaging, or cross-Skill behavior. Require
  an independent reviewer, compatibility analysis, adversarial tests, and full
  offline validation when the affected surface is broad.
- **L3 — release/security/live boundary:** branch protection, release
  publication, credentials/permissions, deployment, private data, server or
  scheduler behavior, or scientific execution/acceptance. Require repository
  owner review plus every domain-specific approval; PR review cannot grant the
  operational action.

The author owns scope, implementation, tests, sanitized evidence, rollback
plan, and cleanup record. Reviewers verify claims against the diff and current
evidence. The integrator verifies required checks and merge identity. A release
owner separately freezes, validates once, tags, and publishes only under
explicit authority. The live operator/scientific reviewer retains exact
execution and acceptance authority.

Classify findings as P0 (active safety, security, data-loss, or unauthorized
live risk), P1 (incorrect contract/result, branch-protection gap, or merge/
release blocker), P2 (important maintainability, evidence, or compatibility
defect), and P3 (non-blocking improvement). P0/P1 block merge. Failing or
missing required checks, unresolved requested changes, CI-name drift, stale or
unbound evidence, sensitive/private material, unexplained generated files,
dirty integration state, and unapproved live/deploy dependencies also block.

## 8. Pull request and CI contract

Use [the PR template](../.github/pull_request_template.md). Stage only intended
files, inspect the staged diff, and scan staged paths/content for credentials,
private keys, machine paths, private data, Gaussian runtime artifacts, and
checkpoints before committing.

[`config/required-checks.json`](../config/required-checks.json) freezes the
expected required contexts observed from a successful main run and maps them
to the local workflow/job/matrix declarations. Run:

```bash
./scripts/python core scripts/audit_ci_contract.py
./scripts/python core scripts/audit_ci_contract.py --json
```

Exit `0` proves only that the supported local YAML declarations expand exactly
to the contract; warnings may report a historical remote snapshot mismatch.
Exit `1` means declaration drift; exit `2` means invalid config or unsupported
YAML, which fails closed. The script cannot prove current GitHub branch
protection, permissions, required contexts, or actual CI success.

Before merge, independently verify current GitHub settings and successful
checks. The expected stable contexts are `python-compatibility (3.11)`,
`python-compatibility (3.12)`, `python-compatibility (3.13)`,
`source-archive-release`, and `chemistry-dependencies`. The date-bound
2026-07-21 read-only snapshot in the contract records those five contexts as
aligned at that time. It remains historical evidence: the static audit cannot
prove current branch protection or CI success, which must be independently
verified before merge. CI permission failure is a blocker/limitation to report,
never a reason to claim green status.

Change-aware routing may vary the evidence executed inside these jobs, but it
must not rename or remove the required contexts.

## 9. Merge and local synchronization

Merge only the reviewed feature commit(s) into the intended stable branch,
with required checks green and no blockers. Record the PR, head SHA, merge SHA,
strategy, and check evidence. Then update the stable local checkout using the
approved non-destructive Git flow and verify that its HEAD equals the intended
merge commit. Do not fold Skill synchronization, deployment, a tag, release,
or live smoke into merge authority.

### BUS terminal integration disposition

For a BUS-managed task, preserve the bootstrap `GATE` at epoch `0` as the
opening gate. A terminal integration GATE uses the existing `GATE` kind, not a
new packet kind. Emit it only **after** the integration disposition is known
and independently verified, at the next monotonic epoch after the latest
`REVIEW`, consuming that exact REVIEW. It records the completed disposition;
it does not authorize the integration action in advance.

The terminal disposition is exactly one of:

- **`MERGED`:** record the PR number, reviewed HEAD SHA, merge SHA, resulting
  main SHA, merge method, cleanup state, and residual blockers. Verify these
  identities against the review and actual integration evidence before
  emitting the terminal GATE.
- **`ABANDONED`:** record the verified abandonment disposition, cleanup state,
  and residual blockers. Do not fabricate merge evidence or represent an
  abandoned task as merged.

Cleanup state is **`COMPLETE`** or **`PENDING`**. `PENDING` must name the
responsible owner and/or the blocker. Recording either state grants no cleanup
permission: worktree removal and branch deletion remain explicit local actions
under their existing authority, never effects implied by the terminal GATE.

A terminal GATE grants zero mutation, merge, live, deployment, release, SSH,
RTwin, PBS, Gaussian, qsub, or qdel authority. After it becomes canonical,
later `CTRL`, `EXEC`, or `REVIEW` packets for the same task are invalid.
Continuation requires a new explicit Owner Gate establishing a **new task**;
it cannot resume the terminal task's packet chain.

GitHub Issue open/closed state is non-authoritative UI lifecycle metadata.
Closing or reopening the Issue cannot create, restore, revoke, or alter BUS
or packet authority. Close the Control Issue only after the terminal GATE is
canonical. Issue closure is not a substitute for that GATE, and reopening is
not a continuation gate. These rules add no Relay behavior or packet
serialization change; the Control Issue remains the canonical ledger.

After integration, confirm both stable and feature worktrees are clean. Archive
the Codex task, remove the linked worktree, and delete the local feature branch
only after its result is reachable from the intended integration commit or its
abandonment is documented. List remaining worktrees/branches/tasks so cleanup
omissions are visible.

## 10. Deployment and live smoke

Deployment and live smoke are separate from each other and from development.
For a named Skill deployment, validate the repository copy, review the exact
sync plan/hash, obtain deployment approval, and synchronize only that Skill.
For a live smoke, use the owning domain Skill and obtain exact scope approval
described in section 4. PR/CI/merge success is evidence for code quality only.

Never infer permission to upload, submit, retry, qdel, delete, clean remote
data, accept a minimum/TS/IRC, or broaden a smoke after failure. Stop at the
approved boundary and retain the prescribed sanitized evidence.

## 11. Incident, rollback, and evidence record

For a development or release incident, stop mutation, preserve logs/receipts/
hashes, revoke or pause affected publication/deployment authority where the
owner directs, and make no automatic server cleanup or destructive rollback.
Assess whether rollback is compatible with immutable schemas and later data;
prefer a reviewed forward fix when history or data makes rollback unsafe.
Revert/rollback, force-push, branch deletion, release withdrawal, deployment
rollback, qdel, and data cleanup each require their own authority.

Use this concise record:

```text
incident/task id and UTC time:
classification and severity:
commit/tree/artifact hashes:
environment and authority held:
observed fact (not inference):
impact and affected boundary:
commands/actions with exit status:
retained sanitized evidence:
containment and stop condition:
rollback/forward-fix decision and approver:
remaining blockers and owner:
cleanup/archive state:
```

## 12. Checklists

### Before commit

- [ ] Task class, scope, non-goals, review level, base SHA, worktree, and branch recorded.
- [ ] Preflight reviewed; unrelated dirty changes and private/live risks absent.
- [ ] Focused and adjacent offline tests pass with exact current evidence.
- [ ] Diff and compatibility/self-review complete; no weakened approval gate.
- [ ] Only intended files staged; staged diff and sensitive/private scan clean.

### Pull request

- [ ] PR template complete; claims distinguish fact, inference, and untested gaps.
- [ ] Required-check static audit passes; dated remote mismatch is disclosed.
- [ ] Current GitHub branch protection and all required contexts independently verified.
- [ ] Review findings resolved by severity; rollback and cleanup plans present.
- [ ] PR explicitly states no live, deployment, release, or scientific authority.

### After merge

- [ ] Merge SHA and green check evidence recorded; stable checkout synchronized and clean.
- [ ] No tag, release, deployment, or live action performed without separate approval.
- [ ] Feature worktree/branch and Codex task archived or cleanup blocker assigned.

### Before release

- [ ] Versioned release checklist selected; exact candidate bytes and authority frozen.
- [ ] Final complete offline release validation run once on that candidate and recorded.
- [ ] Current remote required checks/permissions verified; no CI permission or name-drift blocker.
- [ ] Rollback/incident ownership and compatibility impact reviewed.
- [ ] Tag, GitHub Release, Skill deployment, and live smoke each have separate exact approval.

## Recurrence guards

- **CI check-name drift:** explicit job names, a versioned exact mapping, static
  matrix expansion, and current remote verification before merge/release.
- **Restricted CI permissions:** report the inaccessible evidence and block the
  claim; do not substitute a local pass for remote success.
- **Historical totals presented as current:** bind every test count to command,
  time, commit/tree, exit code, and duration.
- **Worktree/task cleanup omitted:** include cleanup state in PR, merge handoff,
  and incident records; verify the inventory after integration.
- **Heavy release validation repeated:** run lighter falsification checks while
  editing and the complete final ladder once only after candidate freeze.
