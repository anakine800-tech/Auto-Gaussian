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
  developer workflow. It uses one isolated Codex task, one linked worktree,
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

1. one independently reviewable change = one Codex task;
2. that task = one linked Git worktree;
3. that worktree = one unique short-lived `codex/<purpose>` branch;
4. that branch = one PR and one review/integration decision.

An independently testable subtask receives its own task/worktree/branch. A
small related follow-up remains in the original feature context. Do not reuse
one branch in active worktrees, switch a shared checkout to simulate
isolation, or carry unnamed uncommitted changes. Integration occurs from the
stable checkout only after the feature commit and evidence are frozen.

Archive or close the Codex task only after its final state, commit, integration
disposition, and residual blockers are recorded. Worktree removal and branch
deletion are explicit local cleanup actions after integration or abandonment;
neither authorizes remote branch deletion.

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

Typical commands are:

```bash
./scripts/python core -m compileall -q scripts tests
./scripts/python core scripts/static_quality.py
./scripts/python core scripts/audit_ci_contract.py
./scripts/python core scripts/audit_python_contract.py
./scripts/python core scripts/run_tests.py tests.test_dev_preflight tests.test_audit_ci_contract
./scripts/python core scripts/run_tests.py --top-slow 20 --slow-threshold 1.0
bash -n scripts/check_rtwin_connection.sh scripts/probe_gaussian_server.sh templates/g16_job.pbs.template
git diff --check
```

Do not multiply equivalent evidence. Matrix compatibility runs exclude the
large pressure case with a recorded modifier; the Python 3.13 source-archive
release job owns the complete pressure replay. Once release metadata and the
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

## 9. Merge and local synchronization

Merge only the reviewed feature commit(s) into the intended stable branch,
with required checks green and no blockers. Record the PR, head SHA, merge SHA,
strategy, and check evidence. Then update the stable local checkout using the
approved non-destructive Git flow and verify that its HEAD equals the intended
merge commit. Do not fold Skill synchronization, deployment, a tag, release,
or live smoke into merge authority.

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
