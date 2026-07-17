# Auto-G16 2.4.0 Release Checklist

Status: release metadata preparation, local commits, exact synchronization of
`auto-g16-chemdraw-pipeline` and `auto-g16-view-rt-win`, branch push, and Draft
PR creation were explicitly authorized on 2026-07-18. The user subsequently
authorized converting PR #38 to Ready and merging it into `main` while `/4`
and `/5` remain blocked/not authorized. Tag `v2.4.0`, GitHub Release, any other
Skill deployment, live smoke, SSH/PBS/Gaussian work, retry, cancellation, and
server cleanup are not authorized.

## Candidate scope

- Confirmed base: `origin/main` commit
  `69222eb40fc4485392c753b240989719fcec56a4`.
- Immutable prior release: annotated tag `v2.3.0`, dereferenced commit
  `3125b46eec8176812d5e927ef2dbddd86d2c936b`.
- Delta from `v2.3.0`: 58 commits and 235 changed files before release-metadata
  preparation.
- PR scope: #29, #30, and #32–#37.
- Release content: metal TS P0–P5 readiness and candidate closure; offline
  dual-route conformer search; main-group open-shell state/minimum contracts;
  multiplicity families; same-spin open-shell TS/Freq/IRC; open-shell reaction
  networks; scientific-maturity gates; input receipts `/2` and `/3`; and
  prospective live approvals `/4` and `/5`.

## Compatibility and safety review

- [x] `pyproject.toml`, README current-release text, changelog current release,
      repository status, checklist, and release-hygiene expectations identify
      2.4.0.
- [x] The complete 2.3.0 changelog entry, compare link, checklist, README
      release-candidate record, and all earlier release history remain intact.
- [x] No versioned scientific schema or immutable record was renamed or
      rewritten for the release.
- [x] Historical receipt `/1` and live approval `/1`–`/3` semantics remain
      unchanged. Receipt `/2` plus live `/4` is a distinct single-stage path;
      receipt `/3` plus live `/5` is a distinct two-stage path.
- [x] All new scientific and input artifacts remain offline and
      non-authorizing unless an exact separate live approval is later supplied.
- [x] The fixed `/home/user100/SDL` server boundary, fresh-project and
      non-overwrite rules, exact job-ID cancellation gate, and no-deletion
      policy are unchanged.

## Merge authorization boundary

- [x] The user explicitly authorized Ready conversion and merge of PR #38 on
      2026-07-18 with `/4` and `/5` still blocked/not authorized.
- [x] This is a release-integration decision for the exact six-file 2.4.0
      preparation scope. It does not treat a blocked live-smoke path as passed,
      remove a scientific/input/live gate, or authorize a future calculation.
- [x] Final merge still requires the updated PR head to pass the repository's
      required GitHub checks and remain mergeable against `main`.
- [x] Merge authorization is not tag, GitHub Release, deployment, SSH, PBS,
      Gaussian, submission, retry, cancellation, cleanup, `/4`, or `/5`
      authorization.

## Named-Skill synchronization evidence

The repository copies were validated through the named-Skill synchronizer's
read-only plan mode on 2026-07-18. The summaries below contain only
repository-relative names and public SHA-256 evidence. After both current plans
exactly matched these reviewed summaries and hashes, the user explicitly
authorized applying only these two named Skills with the synchronizer's exact
`--apply --confirmed --plan-sha256` gate.

- `auto-g16-chemdraw-pipeline`: 0 missing, 1 changed, 0 extra. Planned change:
  `scripts/make_gaussian_input.py`, authoritative source SHA-256
  `d9d02c19b9b8ba6f2f3ba1e9ecbd954b7674f9ecd37f76d55d552ec712f04dd5`.
  Plan SHA-256:
  `0cddc482aae9757b176d267c60b99d3eb9d8fa9cee6a810d2b771efac75d58bd`.
- `auto-g16-view-rt-win`: 0 missing, 2 changed, 0 extra. Planned changes:
  `SKILL.md` (source SHA-256
  `ab0db0f63017084560ccd23039c8cda9c551790bc34d22149d029e8e7bc7e743`)
  and `references/conformer-workflow.md` (source SHA-256
  `626b3a944b6a387d58c5ae2555b9d99237e22d7f224201665ebda244b049ae3c`).
  Plan SHA-256:
  `034eab0075ba0a91dc650ed85f7c13f94629c52775ce1e52da716d0b3cf7ad45`.
- [x] `auto-g16-chemdraw-pipeline` applied exactly plan SHA-256
      `0cddc482aae9757b176d267c60b99d3eb9d8fa9cee6a810d2b771efac75d58bd`;
      the synchronizer's deployment-after-write comparison passed.
- [x] `auto-g16-view-rt-win` applied exactly plan SHA-256
      `034eab0075ba0a91dc650ed85f7c13f94629c52775ce1e52da716d0b3cf7ad45`;
      the synchronizer's deployment-after-write comparison passed.
- [x] `./scripts/python check --skill-sync` subsequently reported both Python
      profiles healthy and all 13 repository/deployed named-Skill packages
      synchronized.
- [x] No other Skill was synchronized, no extra file was deleted, and no
      deployed file was copied back into the repository. Any future deployment
      requires a new reviewed dry-run and separate exact authorization.

## Live-smoke approval preparation

Overall status: **blocked / not authorized**. This release preparation supplies
no live input, project, server directory, resource request, or exact user
approval. It performed no SSH, PBS, Gaussian, submission, retry, cancellation,
or cleanup action. The separately authorized PR merge does not change this
status and cannot be replayed as live authority.

### Single-stage open-shell minimum — `/4`

- [ ] Supply and review one exact receipt `/2` with structure identity,
      stereochemistry, charge, multiplicity, U/RO reference, route, resources,
      server project, fresh-directory evidence, and Gaussian input SHA-256.
- [ ] Review the exact `/4` proposal and authorize that one input, project,
      resource tier, memory/core request, and intended single-stage operation.
- [ ] Record stop conditions, retained evidence, non-overwrite policy, and the
      prohibition on automatic retry/cancellation/cleanup.
- Status: **blocked / not authorized** because no exact receipt `/2`, rendered
  input hash, project/resource scope, or `/4` authorization was supplied.

### Two-stage open-shell minimum — `/5`

- [ ] Stage 1 requires its own exact receipt `/3`, input/hash/project/resource
      review, `/5` proposal, and explicit authorization for Opt/Freq only.
- [ ] Stage 2 remains blocked until stage 1 is accepted and its final checkpoint
      continuity is reviewed. Stage 2 then requires a different exact receipt
      `/3`, coordinate-free `Stable=Opt Geom=AllCheck Guess=Read` input/hash,
      `/5` proposal, and separate explicit authorization.
- [ ] Neither stage approval authorizes the other, and neither authorizes a
      retry, cancellation, cleanup, different input, or broader workflow.
- Status: **blocked / not authorized** because neither stage has the required
  exact inputs, hashes, accepted continuity evidence, project/resource scope,
  or stage-specific `/5` authorization.

## Offline release evidence

- [x] Complete core unittest suite: 522 tests passed under Python 3.13.13 in
      328.290 seconds.
- [x] Python `compileall` passed for `scripts`, `skills`, and `tests`.
- [x] A candidate source archive containing the working-tree release metadata
      and no `.git` directory passed the same 522 tests in 294.325 seconds.
- [x] Tracked shell/template `bash -n` validation passed.
- [x] `git diff --check` passed.
- [x] All 9 release-hygiene tests passed, including current metadata, historical
      release presence, portable paths, secret patterns and public-study rules.
- [x] Offline environment checks passed: core Python 3.13.13/pip 26.1.2; chem
      Python 3.11.15/pip 26.1.2 with NumPy 2.4.6, Pillow 12.3.0, and RDKit
      2026.03.3 matching the reviewed configuration and lock.
- [x] Final diff and candidate-file sensitive-string/private-key review passed;
      the 2.3.0 changelog section exactly matched the published tag with
      SHA-256 `2b16f2c8f158e3eca4c36a293e486390c2c862c9a0f49b820691491495628a86`.
      The final six-file staged set passed `git diff --cached --check`, full
      staged-diff review, and the same sensitive-string/private-key scan.
- [x] The post-synchronization checklist update passed all 9 focused release-
      hygiene tests, `git diff --check`, and the sensitive-string/private-key
      scan before its separate follow-up commit.

## Authorized PR integration and withheld publication

After the updated PR head passes all required checks, PR #38 may be converted
to Ready and merged into protected `main` under the explicit 2026-07-18
authorization. Stop after verifying the merge and synchronizing local `main`.
Do not create tag `v2.4.0`, a GitHub Release, another deployment, or any live
operation without a separate explicit request; every scientific and server
approval gate remains in force.
