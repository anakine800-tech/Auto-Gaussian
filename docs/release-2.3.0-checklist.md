# Auto-G16 2.3.0 Release Checklist

Status: release metadata preparation, pull-request integration, and merge to
`main` were explicitly authorized on 2026-07-16. An annotated tag `v2.3.0`, a
GitHub Release, Skill deployment, live smoke, SSH/PBS/Gaussian work,
cancellation, and server cleanup are not authorized by this request.

## Candidate scope

- Base release: immutable tag `v2.2.0`.
- Reviewed feature/content baseline: `main` commit
  `1d730218048c52a395b379cbe4653c9e2b8def97`.
- Delta from `v2.2.0`: 36 commits and 106 changed files.
- Ten repository-owned `auto-g16-*` Skills.
- Offline mechanism-support owner gate and separate downstream support matrix,
  TS-precedent/de novo planning, deterministic non-executable calculation DAG
  and read-only study index, reviewed candidate-target mapping, and narrow
  immutable calculation-artifact adapters.
- Bundled Gaussian learning library, public-repository confidentiality
  guardrails, updated portable-path and historical-status audits, named-Skill
  deployment packaging, and deterministic Python environment management.

## Environment and dependency contract

- [x] `core` resolves to Python 3.13.13 with pip 26.1.2.
- [x] `chem` resolves to Python 3.11.15 with pip 26.1.2.
- [x] The chemistry environment matches the lock: NumPy 2.4.6, Pillow 12.3.0,
      and RDKit 2026.03.3.
- [x] `.python-version`, `pyproject.toml`, both Conda environment files,
      `config/python-environments.json`, and the chemistry lock describe the
      same reviewed environment contract.

## Offline release evidence

- [x] `./scripts/python core -m unittest discover -s tests -v` passes all 288
      tests on the candidate checkout.
- [x] Python `compileall` passes for `scripts`, `skills`, and `tests`.
- [x] Shell `bash -n` passes for the tracked shell/template entry points.
- [x] `git diff --check` passes.
- [x] A `git archive` extracted into a temporary directory with no `.git`
      metadata passes the complete 288-test suite.
- [x] Release-hygiene scans cover secret patterns, private keys, machine paths,
      private addresses, and non-public study markers.
- [x] `./scripts/python check --skill-sync` reports both Python profiles healthy
      and all ten repository/deployed named-Skill packages synchronized. This
      is a read-only comparison observed on 2026-07-16, not deployment
      authorization or proof about another machine or later checkout.

## Remote CI and security evidence

- [x] A fresh fetch on 2026-07-16 confirmed `origin/main` at
      `1d730218048c52a395b379cbe4653c9e2b8def97` before release-metadata work.
- [x] Offline tests, CodeQL, and Dependency Graph completed successfully for
      that exact remote `main` commit.
- [x] Open pull requests, Dependabot alerts, Code Scanning alerts, and Secret
      Scanning alerts were each zero before the release-preparation PR.
- [x] Secret Scanning, push protection, and Dependabot security updates were
      enabled for the public repository.
- [ ] The release-preparation PR checks must complete successfully before merge.
- [ ] After merge, verify the final `main`/`origin/main` identity and final CI.

## Safety and compatibility review

- [x] The release changes no versioned scientific artifact schema names and
      rewrites no historical immutable records.
- [x] The `v2.2.0` changelog entry, compare link, and release checklist remain
      intact as history.
- [x] The calculation plan, support, precedent, mapping, and adapter layers
      remain offline and non-authorizing: no calculation node becomes
      executable and no scientific or live approval gate is weakened.
- [x] No credential, private key, machine-specific configuration, Gaussian
      output/checkpoint, server scratch, or private study data belongs in the
      release-preparation commit.
- [x] No SSH, PBS, Gaussian, deployment, cancellation, cleanup, or live smoke is
      part of candidate validation.

## Authorized integration and withheld publication

1. Review and stage only the release metadata, status documentation, checklist,
   consistency correction, and release-hygiene test files.
2. Run a staged diff review and sensitive-string/private-key scan.
3. Commit, push, open a pull request, wait for all required checks, and merge to
   protected `main` only when the result is safely mergeable.
4. Re-fetch and verify final `main`, `origin/main`, PR state, and CI.
5. Stop after the merge. Do not create annotated tag `v2.3.0` or a GitHub
   Release until the user gives separate explicit authorization.
