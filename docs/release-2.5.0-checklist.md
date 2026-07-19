# Auto-G16 2.5.0 Release Checklist

Status: the user explicitly authorized the complete 2.5.0 software release on
2026-07-19: isolated branch creation, release metadata, offline validation,
commit, push, draft PR, CI inspection and release-only fixes, Ready conversion,
merge, post-merge CI, annotated tag `v2.5.0`, and a normal latest GitHub
Release. This authorization excludes every Skill deployment, SSH, RTwin, PBS,
Gaussian, live scientific smoke, submission, retry, cancellation, server
cleanup, and broader scientific operation.

## Candidate scope

- Confirmed release-preparation base: fetched `origin/main` commit
  `c46301bdcfc08fef4292abf17cfed256963cc5f1`, equal to clean local `HEAD` and
  local `main` with ahead/behind `0/0` before branch creation.
- Immutable prior release: annotated tag `v2.4.0`, dereferenced commit
  `48e5398bd4f0ddb47edf553626e232319a00b78f`.
- Delta from `v2.4.0`: 14 commits and 46 changed files before release-metadata
  preparation.
- Integrated PR scope: #40 updates the pinned GitHub Actions runtimes; #41
  integrates the six release slices.
- Release content:
  - method-evidence database contracts and evidence-bound method selection;
  - human scientific mechanism/method decisions, operator action cards, and
    immutable learning updates;
  - bounded hash-bound TS-seed candidates and 1+1 portfolios;
  - closure-priority planning over evidence, seed quality, closure likelihood,
    information value, and practical compute cost;
  - PBS execution-batch governance, ten-task accounting, and read-only
    immediate/60-minute summaries; and
  - a cross-Skill non-authorizing owner-validation overlay.

## Compatibility and safety review

- [x] `pyproject.toml`, README current-release text, changelog current release,
      repository status, checklist, and release-hygiene expectations identify
      2.5.0.
- [x] The complete 2.4.0 changelog entry, compare link, checklist, README
      release-preparation record, and all earlier release history remain
      present.
- [x] No versioned scientific schema, historical immutable record, Gaussian
      term, server boundary, cancellation rule, or no-deletion rule was renamed
      or rewritten for release branding.
- [x] Planning/review artifacts remain `calculation_ready: false`, calculation
      nodes remain `executable: false`, and the integration overlay is
      non-authorizing.
- [x] Exact structure, stereochemistry, charge, multiplicity, method, input,
      resource, server-directory, stage-dependency, and fresh live approvals
      remain separate requirements for future execution.
- [x] Release publication makes no claim of a successful real reaction study,
      accepted minimum, TS/IRC closure, real PBS/Gaussian validation, or any
      scientific success probability.

## Deployment evidence and boundary

- [x] The delegated baseline records exact synchronization on 2026-07-19 of
      `auto-g16-knowledge-base`, `auto-g16-reaction-workflow`,
      `auto-g16-rtwin-pbs`, and `auto-g16-ts-seed` after their v2.5 changes.
- [x] The same delegated baseline records a subsequent read-only result of all
      14 repository/deployed named-Skill pairs synchronized.
- [x] The release worktree's fresh `./scripts/python check --skill-sync`
      read-only comparison reports both Python profiles healthy and all 14
      named-Skill pairs synchronized.
- [x] Deployed-copy `--help` entry points for method evidence, v2.5 integration,
      execution-batch governance, and TS seeds return successfully without
      network or server actions. The non-executable script files were loaded
      through the project-selected core interpreter; all four exposed their
      offline, non-authorizing command surfaces successfully.
- [x] Release metadata changes do not alter repository Skill packages. No
      deployment is planned or authorized. Any observed drift requiring a
      write is a stop condition.

## Offline release evidence

- [x] Exact diff inspection and `git diff --check` pass.
- [x] Complete core unittest suite passes under the project-selected
      interpreter: 564 tests passed under Python 3.13.13 in 590.954 seconds
      (593.23 seconds wall clock).
- [x] All 9 focused release-hygiene tests passed in 1.474 seconds without
      weakening historical, portability, secret, or public-study assertions.
- [x] Python `compileall` passes for `scripts`, `skills`, and `tests`.
- [x] Tracked shell/template `bash -n` validation passes for the same entry
      points used by GitHub Offline tests.
- [x] `./scripts/python check --skill-sync` passes without writing deployed
      copies.
- [x] A source copy containing the release metadata and no `.git` directory
      passes the same 564-test offline regression in 586.839 seconds (590.36
      seconds wall clock). The temporary validation copy is not a release
      artifact and is not committed.
- [x] The final six intended release files passed staged-diff and whitespace
      checks plus a
      credential/private-key/host-secret/raw Gaussian output/checkpoint/job-ID
      scan; no logs, machine paths, private data, Gaussian outputs,
      checkpoints, or scratch are committed.

The full regressions emitted expected fail-closed diagnostics from adversarial
tests; every corresponding test completed `ok`. Neither regression contacted
RTwin, PBS, Gaussian, or another live scientific system.

## PR, merge, and publication authorization

- [x] The user explicitly authorized pushing only
      `codex/release-2.5.0-prep` and opening a draft PR targeting `main` with a
      complete release/safety/validation description.
- [x] The user explicitly authorized inspecting all required checks and fixing
      only release-preparation failures while preserving tests and safety
      gates.
- [x] The user explicitly authorized marking the PR Ready and merging it only
      after it is clean, mergeable, and all required checks pass.
- [x] The user explicitly authorized waiting for post-merge `main` CI, then
      creating and pushing annotated tag `v2.5.0` on exactly the clean release
      commit.
- [x] The user explicitly authorized a normal, non-prerelease GitHub Release
      titled `Auto-Gaussian 2.5.0`, using the finalized changelog and marked
      latest.
- [x] Publication authority does not authorize deployment, SSH, RTwin, PBS,
      Gaussian, live smoke, submission, retry, cancellation, cleanup, or any
      different scientific operation.

## Authorized publication procedure

After the local evidence above passes, commit only the intended release files,
push the exact release branch, and open the draft PR. Inspect every required
check; make only evidence-backed release fixes. Mark Ready and merge only when
the PR is clean, mergeable, and green. Wait for post-merge `main` Offline tests
and CodeQL, fetch, and verify local/remote/GitHub `main` identify the same exact
release commit. Create annotated tag `v2.5.0` on that commit, push only the tag,
publish a normal latest GitHub Release from the finalized 2.5.0 changelog, and
verify the dereferenced tag, target commit, release URL, and main
synchronization. Do not deploy, delete branches/worktrees, archive this task,
or perform any live scientific operation.
