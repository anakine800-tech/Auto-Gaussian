# Auto-G16 2.5.2 Release Preparation Checklist

Status: on 2026-07-20 the user authorized an isolated 2.5.2 metadata-preparation
branch followed by one final complete offline release validation after the
metadata is frozen. This authorization does not include commit, push, pull
request creation, merge, tag creation, GitHub Release publication, Skill
deployment, SSH, RTwin, PBS, Gaussian, live smoke, submission, retry,
cancellation, cleanup or scientific acceptance.

This file is part of the metadata freeze and intentionally does not predict or
embed the outcome of the later validation run. Exact command results, test
counts, environment identity and candidate SHA must be attached to the task or
pull request before the candidate can be marked ready. Publication remains a
separate authorization after green PR and post-merge `main` checks.

## Candidate identity and version choice

- Preparation baseline: clean local and remote `main` commit
  `4063929df0c4aa97aefbde1f8c73e20c8272aa97`.
- Preceding public release: annotated tag `v2.5.0`, dereferenced commit
  `18d7f62af3b24cdd0fbe5687f4c0e779f243d572`.
- Baseline delta from `v2.5.0`: 23 commits and 110 changed files before the
  release-metadata preparation.
- No public `v2.5.1` tag or GitHub Release exists. Version `2.5.2` is an
  explicitly selected compatibility/safety patch-line identifier; it does not
  imply that a public 2.5.1 artifact is missing.
- The release tag must never be created from this unmerged feature branch. A
  future annotated `v2.5.2` tag must point to the exact green post-merge
  `main` commit.

## Candidate scope

- Fail-closed tri-state scheduler/process/transport evidence, exact zombie
  cleanup classification and immutable allowlisted server-to-Mac result
  snapshots with no-follow path and hash verification.
- Idempotent protected submission and cancellation transactions with stable
  task/attempt identities, one-shot approval consumption, uncertain-outcome
  retention and read-only reconciliation without automatic qsub/qdel retry.
- Exact resource policy, scheduler snapshot, resource gate, accounting,
  terminal receipt, bounded monitoring and incremental immutable fetch reuse.
- Owner-replayed TS/Freq/IRC, endpoint, checkpoint, minimum-lineage and
  TS-result `/2` contracts with complete structure, state and artifact
  provenance.
- Strict runtime configuration, calculation-DAG replay optimization, timed
  tests, progressive static checks, real RDKit CI smoke and private-study
  plan-review-apply migration `/2`.

## Compatibility and safety invariants

- Historical versioned schemas and immutable records retain their original
  replay meaning. New protected work uses explicit successor contracts rather
  than silently changing old semantics.
- The fixed `/home/user100/SDL` boundary, non-empty-directory refusal,
  no-overwrite/no-delete policy, scheduler-spool prohibition and exact job-ID
  cancellation authority remain unchanged.
- Unknown scheduler, process, transport, parser, freshness, termination or
  hash evidence fails closed and cannot release budget, prove interruption,
  authorize cleanup or become a scientific result.
- Planning, migration and validation artifacts grant no deployment, input,
  live-action, retry, cancellation, cleanup or scientific acceptance
  authority.
- Release publication must not claim a successful real reaction study,
  accepted minimum, TS/IRC closure, real PBS/Gaussian validation or a
  scientific success probability.
- Repository files must contain no credentials, private keys, machine-specific
  identities, private study data, raw Gaussian logs, checkpoints, job records
  or server scratch.

## Frozen metadata set

- `pyproject.toml` identifies version `2.5.2`.
- `README.md` identifies the 2.5.2 candidate while preserving the immutable
  2.5.0 and earlier release history.
- `CHANGELOG.md` promotes the reviewed hardening entry to 2.5.2, retains an
  empty Unreleased section and contains exact compare links.
- `docs/repository-status.md` separates candidate, published, historical,
  deployed and live/scientific evidence.
- `tests/test_release_hygiene.py` requires the new metadata and preserves every
  earlier checklist and changelog entry.
- This checklist records the version choice, scope, validation contract and
  authorization boundary without claiming unrun evidence.

## One-time final offline validation contract

After every metadata file above is frozen and reviewed, run the complete
release ladder once on the same candidate bytes:

1. timed complete offline suite on the project-selected core interpreter;
2. complete `.git`-free source-archive replay including the oversized DAG
   pressure case;
3. focused release-hygiene tests;
4. `compileall` for `scripts`, `skills` and `tests`;
5. progressive static quality checks;
6. tracked shell/template `bash -n` checks;
7. JSON/schema syntax, `git diff --check`, intended-file review and a
   credential/private-key/machine-path/private-data/raw-output scan.

Expected fail-closed diagnostics emitted by adversarial unit tests are not
failures when the owning test finishes `ok`. The validation must remain
offline and must not invoke deployment, SSH, RTwin, PBS, Gaussian, qsub, qdel,
upload, cleanup or private-study migration apply.

## Future PR and publication gates

A later explicit authorization is required to commit, push, create a PR, mark
it ready, merge, create or push `v2.5.2`, publish a GitHub Release, deploy a
Skill or perform any live operation. Before tag creation, verify that local,
remote and GitHub `main` identify the same green merge commit and that the
annotated tag targets exactly that commit. A tag or Release never grants live
scientific authority.
