## Scope and classification

- Task class: <!-- feature / maintenance / scientific-workflow code only -->
- Review level: <!-- L1 / L2 / L3 -->
- Codex task, worktree, branch, base SHA:
- Intended outcome and non-goals:
- Changed contracts/schemas/commands:

## Safety and authority boundary

- [ ] Versioned development is separated from private/live operational work.
- [ ] This PR, its CI, review, and merge do **not** authorize deployment, Skill sync, SSH, RTwin, PBS, Gaussian, qsub/qdel, retry, cleanup, private-data apply, or scientific acceptance.
- [ ] No existing server, scientific, immutable-artifact, or human-approval gate is weakened.

## Configuration and data isolation

- [ ] Only placeholders/synthetic or release-cleared fixtures are committed.
- [ ] No credentials, private keys, machine paths, private studies, raw outputs, checkpoints, job evidence, scratch, or real local config is included.
- Test profile and coverage-modifier environment variable **names** (never values):

## Validation evidence

For each run provide command, interpreter/profile, commit/tree, date/time, exit code, total/skips/failures, duration, and modifier names. Do not reuse historical totals.

- Focused:
- Adjacent:
- Offline integration/regression:
- Full offline suite, if warranted:
- Uncovered or blocked surfaces:

## Review and CI contract

- Findings by severity (P0/P1/P2/P3) and disposition:
- [ ] `scripts/audit_ci_contract.py` passes local declaration audit.
- [ ] Current remote branch protection and the five expected required contexts were separately verified, or the exact blocker is reported.
- [ ] CI permission limitations and run state are reported without claiming success.

## Rollback, incident, and compatibility

- Compatibility/migration impact:
- Rollback or forward-fix plan and required authority:
- Incident containment/evidence owner, if applicable:

## Integration, cleanup, and release deduplication

- [ ] Only intended files were staged; staged diff and sensitive/private scan were reviewed.
- [ ] Worktree, local branch, and Codex task cleanup/archive owner is named.
- [ ] Final complete release validation has not been duplicated; if release-bound, it will run once after exact candidate freeze.
- [ ] Tag, release, deployment, and any live smoke remain separate exact approvals.
