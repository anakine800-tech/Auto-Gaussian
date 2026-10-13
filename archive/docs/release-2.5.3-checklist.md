# Auto-G16 2.5.3 Release Preparation Checklist

Status: on 2026-07-22 the user authorized an isolated 2.5.3 metadata-preparation
branch and one final complete offline release validation after the metadata is
frozen. This authorization does not include commit, push, pull request
creation or readiness, merge, tag creation, GitHub Release publication, Skill
deployment, SSH, RTwin, PBS, Gaussian, live smoke, submission, retry, qdel,
cleanup or scientific acceptance.

This checklist is part of the metadata freeze. It defines the validation
contract but does not predict or embed the later run's result. Exact commands,
interpreter, candidate tree, worktree state, exit codes, totals, skips, elapsed
time and coverage modifiers must be attached to the task or a later authorized
pull request without editing the frozen candidate afterward.

## Candidate identity and published baseline

- Preparation baseline: clean local `main`, `origin/main` and initial worktree
  HEAD at `042f8aeef665f524ac2c0cbdc47ccbf11a208d2e` after a fresh fetch.
- Latest published release: GitHub Release `Auto-Gaussian 2.5.2`, published
  2026-07-20, with annotated tag object
  `4aead58529a7786968aea8e9cd7ee10f6e0c8553` resolving to release commit
  `09a3cad13b07afdab86a70488d4e0ab78aa6c2d9`.
- The first-parent baseline delta from `v2.5.2` is exactly two merge commits:
  PR #45 at `98358c8869f6001fd53756a42344c699cb16ab63` and PR #46 at
  `042f8aeef665f524ac2c0cbdc47ccbf11a208d2e`.
- Before metadata preparation that delta changes 20 files with 3136 insertions
  and 56 deletions. Counts describe Git source delta, not test or scientific
  results.
- A future `v2.5.3` tag must never be created from this unmerged branch. It may
  target only the exact reviewed, green post-merge `main` commit under separate
  release authority.

## Candidate scope

- PR #45: repository development handbook, isolated-worktree preflight,
  pull-request template, versioned required-check contract, Python environment
  and CI contract audits, workflow alignment and focused offline tests.
- PR #46: RTwin terminal snapshot handling for PBS `qstat` return code 153 and
  staged result-fetch handling with finite size-derived timeouts, explicit
  sanitized stage evidence, retained partial state and no automatic retry.
- No other feature, deployment, scientific workflow, study, Gaussian result or
  private operational artifact belongs to the 2.5.3 release increment.

## Compatibility and safety invariants

- The patch is additive or fail-closed. Historical schemas, immutable records,
  approvals and release artifacts retain their original replay meaning.
- Python support remains `>=3.11,<3.14`; the versioned CI contract continues to
  declare Python 3.11, 3.12 and 3.13 plus source-archive and chemistry jobs.
- Static CI/Python audits prove only local declaration consistency. They do not
  prove current GitHub settings, branch protection, permissions or successful
  remote checks.
- Fetch hardening does not broaden paths, retry a transfer automatically,
  overwrite a partial target, weaken hash verification or authorize SSH/RTwin/
  PBS/Gaussian access.
- Repository material must contain no credentials, private keys, machine paths,
  private research data, raw Gaussian logs, checkpoints, job records, server
  scratch or `reports/` output.
- Release metadata makes no claim of deployment, live validation, a successful
  calculation, accepted minimum, TS/IRC closure or scientific success.

## Frozen metadata set

- `pyproject.toml` identifies version `2.5.3`.
- `CHANGELOG.md` contains the bounded PR #45/#46 2.5.3 entry, an empty
  Unreleased section and exact compare links while preserving 2.5.2 and older
  entries.
- `README.md` identifies 2.5.3 as the prepared candidate and 2.5.2 as the latest
  published release without rewriting older release history.
- `docs/repository-status.md` separates current source, published release,
  historical, test, deployment, remote-CI and live/scientific evidence.
- `tests/test_release_hygiene.py` enforces the new metadata and preserves every
  older versioned checklist and changelog entry.
- This checklist records scope, validation, compatibility and authority without
  claiming unrun evidence.

## One-time final complete offline release validation

After all six metadata files are frozen and reviewed, derive one candidate tree
from the exact working bytes using a temporary Git index. Record its SHA, the
baseline HEAD and `git status --short`, then run this ladder exactly once:

1. identify and check the core interpreter with `./scripts/python check
   --profile core` and record all active coverage modifiers;
2. run `./scripts/python core scripts/run_tests.py --top-slow 20
   --slow-threshold 1.0` in the worktree;
3. create one `.git`-free archive from that exact candidate tree and run the
   same complete suite there, including the oversized DAG pressure case;
4. run the focused release hygiene, development preflight, CI-contract,
   Python-contract and RTwin fetch/snapshot regression modules;
5. run `compileall`, progressive static quality, tracked shell/template
   `bash -n`, and JSON parsing checks;
6. run `scripts/audit_ci_contract.py` and
   `scripts/audit_python_contract.py`, retaining their limitation that static
   audit is not remote evidence;
7. run `git diff --check`, review every intended path and diff, and scan for
   credentials, private keys, machine paths, private research, `reports/`, raw
   Gaussian output/checkpoint files and server scratch.

For every command record the exact invocation, interpreter/profile, baseline
and candidate tree SHA, start time, exit code, test total, skips/failures,
elapsed time and modifiers. Expected fail-closed diagnostics emitted by passing
adversarial tests are not failures. The ladder is offline and must not invoke
deployment, network installation, SSH, RTwin, PBS, Gaussian, qsub, qdel,
submission, retry, cleanup or private-migration apply.

If any frozen byte changes after the final run, the evidence is invalid. Review
the delta and schedule one new final run for the new candidate rather than
reusing or combining evidence.

## Future authorization gates

Commit, push, pull request creation or readiness, merge, tag, GitHub Release,
Skill deployment and live smoke each require separate explicit authorization.
Before merge or release, independently verify current remote required checks,
branch protection, permissions and exact commit identity. Neither local tests,
CI, a tag nor a Release grants operational or scientific authority.
