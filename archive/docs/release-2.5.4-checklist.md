# Auto-G16 2.5.4 Release Preparation Checklist

Status: on 2026-07-22 the user authorized preparation and publication of
Auto-Gaussian 2.5.4, including the metadata branch, commit, push, pull request,
merge to stable `main`, annotated `v2.5.4` tag and GitHub Release. This does not
authorize Skill deployment, SSH, RTwin, PBS, Gaussian, live smoke, submission,
retry, qdel, cleanup or scientific acceptance.

This checklist is part of the frozen release metadata. Exact test evidence is
recorded outside the frozen candidate so the candidate bytes do not change
after final validation.

## Candidate identity and published baseline

- Preparation baseline: clean `origin/main` at
  `648819911e9f95a7085346ce11f916ad5d8118a1`, tree
  `86e98e3ae0578f3bc350e2860a89087c83b662e9`, after PR #48 merged.
- Latest prior release: `Auto-Gaussian 2.5.3`, published 2026-07-22. Annotated
  tag object `20cea7e040ef6649f9f695381c802abc8aa7aba0` resolves to immutable release
  commit `bc67fded270ee5fc52efecfafdfc817073430b7a`.
- The first-parent delta from `v2.5.3` to the preparation baseline is exactly
  PR #48 at `648819911e9f95a7085346ce11f916ad5d8118a1`: four files, 50 insertions
  and 29 deletions.
- A `v2.5.4` tag may target only the exact reviewed, required-check-green
  post-metadata-merge `main` commit. Never move or replace `v2.5.3`.

## Candidate scope

- PR #48 reconciles the public 2.5.3 status, excludes root `reports/` from Git
  and source-release material, and adds release-hygiene regression coverage.
- The 2.5.4 metadata slice changes only `pyproject.toml`, `CHANGELOG.md`,
  `README.md`, `docs/repository-status.md`, this checklist and
  `tests/test_release_hygiene.py`.
- Historical checklists, tags, Releases, schemas and scientific records retain
  their exact existing bytes and meaning.

## Version-consistency contract

- `pyproject.toml` declares `2.5.4`.
- The first release after the empty Unreleased section is `2.5.4`, with
  `[Unreleased]` comparing from `v2.5.4` and `[2.5.4]` comparing
  `v2.5.3...v2.5.4`.
- The README title, current-release heading and latest-published sentence all
  identify 2.5.4 while retaining 2.5.3 as historical.
- `docs/repository-status.md` identifies 2.5.4 as current and does not present
  2.5.3 as latest.
- This checklist exists at the version-derived path and its title matches the
  package version.
- The annotated tag must be exactly `v2.5.4`; the GitHub Release must be named
  `Auto-Gaussian 2.5.4`, non-draft and non-prerelease, and resolve to the same
  exact post-merge `main` commit.
- The forward publication wording in the candidate becomes externally true
  only when tag and Release publication complete. A failed publication blocks
  task completion and requires explicit reconciliation rather than leaving
  another silently stale current-version surface.

## Compatibility and safety invariants

- This is documentation, version metadata and release-hygiene test coverage;
  no scientific schema, API, runtime command, stored record or migration
  meaning changes.
- Python support remains `>=3.11,<3.14`; required CI contexts remain Python
  3.11/3.12/3.13, source-archive-release and chemistry-dependencies.
- Static audits do not prove remote branch protection or CI success; verify
  both independently before merge and again on post-merge `main` before tag.
- Repository material contains no credentials, private keys, machine paths,
  private research, raw Gaussian output, checkpoints, job records, server
  scratch or `reports/` output.
- Release publication grants no deployment, live or scientific authority.

## Final frozen-candidate validation

After all six metadata paths are frozen and reviewed, derive one candidate
tree from the exact working bytes with a temporary Git index. Record its SHA,
baseline HEAD, clean/dirty status, interpreter/profile, coverage modifiers,
command exit codes, totals, skips and elapsed time. Run exactly once:

1. `./scripts/python check --profile core`;
2. the complete worktree suite with slow-test reporting;
3. the same complete suite from one `.git`-free archive of that exact tree;
4. release hygiene, development preflight, CI/Python contract and affected
   reports-boundary regression tests;
5. compileall, progressive static quality, tracked shell/template syntax and
   JSON parsing;
6. CI and Python contract audits;
7. diff review plus credentials, private-key, machine-path, private-data,
   `reports/`, Gaussian-output/checkpoint and server-scratch scans.

Expected fail-closed diagnostics from passing adversarial fixtures are not
failures. No validation step may deploy, install from the network, contact
SSH/RTwin/PBS/Gaussian, submit, retry, qdel, clean remote data or apply a
private migration. If any candidate byte changes afterward, invalidate the
evidence and run one new final validation for the new exact tree.

## Publication gates

1. Merge only the reviewed metadata PR with all five required contexts green.
2. Fetch and verify post-merge `main` has the frozen candidate tree and the
   expected merge ancestry.
3. Wait for all five required contexts on that exact post-merge `main` commit.
4. Create one signed annotated `v2.5.4` tag at that commit and verify both tag
   object and peeled commit before pushing the tag.
5. Publish a non-draft, non-prerelease GitHub Release named
   `Auto-Gaussian 2.5.4` from that exact tag.
6. Re-read `main`, package version, changelog, README, status, checklist, remote
   tag and Release; every current-version surface must report 2.5.4 and the tag
   must peel to the exact released `main` commit.

Tagging, GitHub Release publication and any future Skill deployment remain
separate operations even though this task authorizes the first two. No live or
scientific action is authorized.
