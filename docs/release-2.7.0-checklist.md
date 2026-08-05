# Auto-G16 2.7.0 Release Preparation Checklist

Status: local offline-only metadata closure on 2026-08-05. The closure starts
from exact merged `main` commit
`5b125a0b233b8815166c745e3654ba0053773333`, tree
`53fb0d1ddbc9c7334fc3aa2db8d3b70379dec1f8`. This checklist does not claim a
2.7.0 tag, GitHub Release, deployment, Skill synchronization, remote operation,
live smoke, or scientific acceptance.

## Task identity and frozen scope

- Task class: maintenance patch / L3 release hygiene.
- Include only the already merged v2.7 offline direct-root boundary,
  `direct_ssh_pbs` synthetic transaction, closed Schema/state surfaces,
  offline onboarding, migration guide, support matrix, and this release
  metadata closure.
- Preserve implementation, scientific logic, versioned Schemas, owner
  semantics, historical artifacts, and every fail-closed gate unchanged.
- The metadata candidate changes only `pyproject.toml`, `CHANGELOG.md`,
  `README.md`, `docs/repository-status.md`, this checklist,
  `tests/test_release_hygiene.py`, and the three merged-state v2.7 documents.

## Truthful capability boundary

- `direct_ssh_pbs` has exactly the statuses `offline_synthetic`,
  `production_blocked`, and `live_not_ready`. It is not `backend_supported`,
  production-ready, transport-authorized, or live-ready.
- Version 2.7.0 delivers offline interfaces, Schemas, states, synthetic
  transactions, onboarding, migration guidance, and support reporting only.
- Real no-follow observer/helper behavior, durable cross-process consumption
  and uncertain-outcome storage, direct resource/live replay ingress, real
  transport, `qsub`, inspect, fetch, and separately authorized live-smoke
  evidence remain blockers.
- The existing `legacy_rtwin_pbs` production backend remains permanently fixed
  below `/home/user100/SDL`. Direct profile/root contracts do not relocate,
  generalize, or authorize that legacy backend.
- Offline validation, a local commit, CI, a merge, a tag, or publication cannot
  grant deployment, server, scheduler, live, or scientific authority.

## Version and documentation consistency

- `pyproject.toml` declares `2.7.0`.
- `CHANGELOG.md` places 2.7.0 immediately after the empty Unreleased section,
  preserves 2.6.1 and all earlier history, and advances compare links.
- `README.md` and `docs/repository-status.md` identify 2.7.0 as the local
  offline-only source candidate and 2.6.1 as the latest published release.
- The three v2.7 milestone documents describe their merged source state rather
  than presenting an old feature branch/base as current.
- `tests/test_release_hygiene.py` enforces the cross-file identity, offline-only
  capability boundary, merged document status, and older release history.

## One-time frozen-byte validation

Complete focused falsification and diff review while editing. Then stage only
the nine intended paths and record the frozen staged tree. No candidate byte
may change after that point.

On those exact frozen bytes, run the complete offline regression exactly once:

```bash
./scripts/python core scripts/run_tests.py --top-slow 20 --slow-threshold 1.0 --verbosity 1
```

Record the exact command, interpreter/profile, baseline and frozen tree,
coverage modifiers, UTC start/end, exit code, `Ran`, `OK`, skips, failures,
errors, wall time, and retained log SHA-256. A failure stops without retry,
byte change, or commit.

On the same frozen bytes, run the applicable compileall, static-quality,
Python-contract, CI-contract, release-hygiene, exact pinned Draft 2020-12
`jsonschema==4.26.0`, JSON parsing, diff-check, staged-diff review, and
sensitive/private-key/machine-path/raw-output scans. Missing pinned jsonschema
is a reported P2 blocker, never a skip presented as a pass. Static CI audit is
not proof of remote branch protection or a successful GitHub run.

## Publication and authority gates

This task authorizes one local commit, branch push, and Draft pull request only
after every local gate passes. The PR must state no live, deployment, tag,
Release, or scientific authority. Merge, tag creation/push, GitHub Release,
formal release, Skill deployment/synchronization, SSH, RTwin, PBS, Gaussian,
upload, submission, retry, cancellation, `qdel`, cleanup, deletion, inspect,
fetch, result acceptance, and live smoke remain separately authorized actions.
