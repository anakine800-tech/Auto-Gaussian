# Auto-G16 2.6.1 Release Preparation Checklist

Status: local metadata closure on 2026-08-02. The closure starts from exact B1
integration commit `66afc5fd808993901a4a616d423fd185c35f8ffa`, tree
`4f6267255ebe9ff6130762901cd390bfb65795ff`. This checklist reflects a release
candidate whose target, `v2.6.1`, has now been published. It does not request
additional live or deployment authority.

## Frozen scope

- Include the independently reviewed v2.6 offline foundation and the minimum
  B1 legacy RTwin/PBS production path only.
- Keep exactly one production entry, one legacy transaction/effect-owner chain
  and one `qsub` site. Bind project, input SHA-256, resources, walltime and the
  exact one-shot approval before any remote mutation.
- Keep the legacy root permanently fixed at `/home/user100/SDL`; refuse an
  existing project directory and never overwrite, retry, cancel, `qdel`, clean
  up or delete automatically.
- Keep uncertain submission in durable `submission_uncertain` state with
  read-only reconciliation. Monitor, fetch and analyze only the exact job and
  allowlisted result artifacts.
- Resolve the fixed local authorization-state directory only when constructing
  a production owner. Explicit testing roots remain relocation-safe; callers
  still cannot override the production state root.
- PR6 direct SSH/PBS, non-SDL roots, multi-backend generalization,
  interpreter-tamper hardening and unrelated architecture are deferred beyond 2.6.1.

## Evidence boundary

- The exact B1 candidate passed practical independent L3 with P0-P3 all zero.
- Its one frozen offline full suite ran 1228 tests with 81 skips and no
  failures or errors.
- A separately approved H2 smoke made one `qsub`, reached one normal Gaussian
  termination, and completed allowlist-bound fetch and local analysis with
  per-hop SHA-256 verification. That machine-local evidence is not committed,
  is not scientific validation for another molecule, and grants no further
  live authority.
- Auto-Gaussian 2.6.1 is the latest published release. `2.5.4` is the
  historical published release immediately before it.

## Metadata set

- `pyproject.toml` declares `2.6.1`.
- `CHANGELOG.md` places 2.6.1 after the empty Unreleased section, preserves the
  2.6.0 entry and all earlier public history, and advances compare links.
- `README.md` and `docs/repository-status.md` distinguish 2.6.1's published state
  from historical releases including 2.5.4.
- `tests/test_release_hygiene.py` enforces those cross-file identities and the
  continued presence of the immutable 2.6.0 checklist.

## Local closure validation

Before commit, bind the exact staged tree and retain terminal evidence for:

1. focused release-hygiene and current-version consistency checks;
2. available pinned Python 3.11 and 3.13 environments without installation;
3. syntax, static quality, Python/CI contract audits, `git diff --check`, and a
   staged sensitive-information/private-key scan;
4. exactly one final complete offline suite for the frozen metadata candidate,
   recording `Ran`, `OK`, skips, failures, errors, exit code, wall time and log
   SHA-256.

Any candidate-byte change invalidates the frozen-tree evidence. P0/P1, unclear
dirty ownership, failed required evidence or scope expansion stops the closure.

## Actions still requiring separate authority

Local commit and candidate freezing do not authorize push, pull request,
merging into `main`, tag creation or push, GitHub Release publication, formal
release, deployment, Skill synchronization, SSH, RTwin, PBS, Gaussian, upload,
submission, retry, cancellation, `qdel`, cleanup, deletion, result acceptance
or another live smoke.
