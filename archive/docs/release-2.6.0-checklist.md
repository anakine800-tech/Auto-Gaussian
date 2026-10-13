# Auto-G16 2.6.0 Release Preparation Checklist

Status: local candidate preparation on 2026-07-31. The candidate starts from
exact integration commit `c190fbc00c8cef361decf5b36c2977bfe62f523f`, tree
`47bd5042ce2e8797336ad775383572e1ef358d7f`. This checklist does not claim a
tag, push, pull request, merge, GitHub Release, deployment, Skill sync, remote
operation, or live smoke.

## Frozen scope

- Include only the offline v2.6 foundation already covered by local independent
  L3 evidence: legacy characterization; platform/profile and execution-
  authorization contracts; protected owner/capability successors;
  deterministic local state; and fail-closed legacy-effect handoff and
  coordination records.
- PR4 real production adapter wiring and production provider, PR6 direct
  SSH/PBS, dependent onboarding/runtime support, and all live smoke are
  deferred to 2.6.1.
- Do not modify implementation, connect an adapter, invent authority, or lower
  a fail-closed gate as part of release closure.

## Truthful capability boundary

- The candidate does not provide or claim an executable production provider,
  connected production adapter, direct SSH/PBS support, or non-SDL legacy
  operation.
- The legacy backend remains permanently below `/home/user100/SDL`. New-root
  contracts do not authorize a backend or remote mutation.
- Offline tests, local L3 evidence, a release commit, tag, or publication never
  authorize deployment, SSH, RTwin, PBS, Gaussian, qsub, upload, retry, qdel,
  cleanup, result acceptance, or scientific acceptance.

## Frozen metadata set

- `pyproject.toml` declares `2.6.0`.
- `CHANGELOG.md` places `2.6.0` after the empty Unreleased section and records
  the reduced scope and compare links without claiming publication.
- `README.md` and `docs/repository-status.md` distinguish the local 2.6.0
  candidate from the latest published 2.5.4 release.
- `docs/v2.6-platform-portability-rfc.md` retains the original comprehensive
  gate as historical provenance and records the 2026-07-31 scope revision.
- `tests/test_release_hygiene.py` enforces those distinctions and preserves all
  earlier release history.

## Frozen-candidate validation

Before commit, bind the exact staged tree and retain terminal evidence for:

1. focused release-hygiene and release-consistency checks;
2. existing Python 3.11 and 3.13 environments where available, with no
   dependency installation;
3. static quality, CI-contract audit, syntax/diff checks, and staged sensitive-
   information/private-key scan;
4. exactly one final complete offline suite after the global heavy lock is
   granted, recording `Ran`, `OK`, skips, failures, errors, exit, wall time, and
   log SHA-256.

Any candidate-byte change invalidates the frozen-tree evidence. P0/P1, unclear
dirty ownership, failed required evidence, or a need to expand scope stops the
closure.

## Actions still requiring separate authority

Commit is permitted only after every required local check passes. Push, pull
request creation, merge, tag creation/push, GitHub Release publication,
deployment, Skill synchronization, and every live operation remain prohibited
and require their own later authorization. The release author cannot serve as
the final independent L3 reviewer and must not locally merge this branch.
