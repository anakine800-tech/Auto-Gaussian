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
- The exact base-to-final candidate scope contains these 12 paths and no
  others:
  - `.github/workflows/offline-tests.yml`
  - `CHANGELOG.md`
  - `README.md`
  - `docs/release-2.7.0-checklist.md`
  - `docs/repository-status.md`
  - `docs/v2.7-direct-onboarding-support.md`
  - `docs/v2.7-direct-root-mutation-boundary.md`
  - `docs/v2.7-direct-ssh-pbs-offline-backend.md`
  - `pyproject.toml`
  - `scripts/audit_python_contract.py`
  - `tests/test_audit_python_contract.py`
  - `tests/test_release_hygiene.py`
- The original nine paths close release metadata, merged-state documentation,
  and release-hygiene tests. The three successor paths
  `.github/workflows/offline-tests.yml`, `scripts/audit_python_contract.py`,
  and `tests/test_audit_python_contract.py` close the related CI-contract gap:
  they bind the complete ordered 17-module Draft 2020-12 inventory and fail
  closed on missing, extra, reordered, or otherwise drifted coverage.

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

## Evidence layering and exact-head validation

The local complete regression belongs only to the predecessor metadata commit
`93cdee22bec22c60bcce9acaa826be1a41e4a520`, tree
`a3a71f6d4462af168e2fd6aefd3f3e7637e01799`. On those predecessor bytes,
core Python 3.13.13 ran:

```bash
./scripts/python core scripts/run_tests.py --top-slow 20 --slow-threshold 1.0 --verbosity 1
```

It exited 0 with `Ran 1272 tests in 3195.075s` and `OK (skipped=83)`;
failures and errors were zero. This is historical predecessor evidence only.
It is not complete-regression evidence for the final exact PR head, and its
Draft-related skips are not a pinned Draft 2020-12 pass.

Before release handoff, the release owner must record the exact final commit
and tree in the handoff evidence. Do not put a self-referential or provisional
final commit hash in this versioned checklist. The following gates must all
pass on that same recorded final commit:

1. `source-archive-release` must run the final complete offline regression from
   the source archive successfully. This exact-head CI result, not the
   predecessor local total, is the final complete-regression evidence.
2. `chemistry-dependencies` must install the locked
   `requirements/schema-validation.txt` dependency set, including
   `jsonschema==4.26.0`, set `AUTO_G16_REQUIRE_JSONSCHEMA=1`, and successfully
   execute the canonical ordered set of all 17 current Draft 2020-12 modules,
   including `tests.test_direct_root_mutation_boundary_schema_draft202012`.
3. The other required contexts, `python-compatibility (3.11)`,
   `python-compatibility (3.12)`, and `python-compatibility (3.13)`, must also
   succeed on the same final commit.

Only after both exact-head hard gates and every other required context pass may
the PR move from Draft to Ready or be considered for merge. Missing pinned
jsonschema, a skipped Draft layer, ordinary green checks on a different SHA,
or static declaration audits cannot substitute for this evidence. Static CI
audit is not proof of remote branch protection or a successful GitHub run.

For every focused or final run, record the exact command, interpreter/profile,
commit and tree, coverage modifiers, UTC start/end, exit code, `Ran`, `OK`,
skips, failures, errors, wall time, and retained sanitized evidence. A required
gate failure remains a blocker and does not authorize retry, byte changes,
deployment, or live work.

## Publication and authority gates

This maintenance chain authorizes local commits, branch pushes, and a Draft
pull request only after the applicable local focused gates pass. It does not
authorize marking the PR Ready or merging before the same-head CI gates above
close. The PR must state no live, deployment, tag, Release, or scientific
authority. Merge, tag creation/push, GitHub Release, formal release, Skill
deployment/synchronization, SSH, RTwin, PBS, Gaussian, upload, submission,
retry, cancellation, `qdel`, cleanup, deletion, inspect, fetch, result
acceptance, and live smoke remain separately authorized actions.
