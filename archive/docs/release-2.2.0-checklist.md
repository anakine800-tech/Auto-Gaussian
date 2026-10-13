# Auto-G16 2.2.0 Release Checklist

Status: merge and publication were explicitly authorized on 2026-07-15. This
authorization covers PR #14, annotated tag `v2.2.0`, and its GitHub Release;
it does not authorize a live calculation, cancellation, additional deployment,
or server-file action.

## Candidate scope

- Base release: `v2.1.0`.
- Candidate baseline after the transition-metal merge: `6dc36b4`.
- Nine repository-owned `auto-g16-*` Skills.
- W2 immutable knowledge contracts, deterministic store/index, reviewed
  import/export and permission-filtered offline queries.
- W3 offline mechanism-network contract and deterministic builder.
- Transition-metal M1/M2a/M2b/M2c/M2d preview contracts with execution,
  promotion and submission still refused.
- Unicode GaussView path correction, optional chemistry dependency metadata,
  GitHub source-archive testing and security-scanning configuration.

## Required release evidence

- [x] Full offline suite passes under Python 3.11 and 3.12 in GitHub Actions.
- [x] Full local offline suite passes under Python 3.13 (185 tests).
- [x] Python compilation and shell syntax checks pass.
- [x] GitHub-style source archive runs the complete 185-test offline suite without
      `.git` metadata.
- [x] Optional NumPy, Pillow and RDKit dependencies install and import in a
      clean environment.
- [x] All nine named repository/deployed Skill pairs are synchronized after
      exact diff review.
- [x] Secret-pattern, private-key, machine-path and private-address scans pass.
- [x] CodeQL, Secret Scanning and Dependabot have no open alerts.
- [x] `main` protection still requires Python 3.11 and 3.12 checks and refuses
      force-push and deletion.
- [x] GitHub Support ticket #4564946 remains `Pending`; the repository owner
      explicitly accepted this external cleanup as a post-release follow-up on
      2026-07-15. The ticket is not represented as closed.

## Already satisfied transition-metal gate

- [x] PR #12 merged only after Python 3.11/3.12 CI, CodeQL and dependency jobs
      passed.
- [x] `auto-g16-asymmetric-catalysis` was synchronized as one exact named
      Skill after diff review.
- [x] The explicitly approved deployed-copy fixture smoke retained
      `runtime_support_status: unsupported_requires_extension`,
      `submission_decision: refused`, `calculation_ready: false`, and
      `live_actions: false`.
- [x] No SSH, PBS, Gaussian, cancellation or server operation was performed.

## Final publication steps (authorized 2026-07-15)

1. Merge the release-preparation pull request into protected `main` after all
   checks pass.
2. Re-run the release evidence above from the resulting `main` commit.
3. Create annotated tag `v2.2.0` from the verified merge commit.
4. Create the GitHub Release from the verified tag and attach no private or
   machine-local artifacts.
