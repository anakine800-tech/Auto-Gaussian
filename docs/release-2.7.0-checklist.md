# Auto-G16 2.7.0 Release Preparation Checklist

Status: local offline-only release-package closure on 2026-08-06. The future
tag target is unresolved and must be filled only after merge as
`FINAL_POST_MERGE_MAIN_COMMIT` and `FINAL_POST_MERGE_MAIN_TREE`. This checklist
does not claim a 2.7.0 tag, GitHub Release, deployment, Skill synchronization,
remote operation, live smoke, or scientific acceptance.

## Task identity and frozen scope

- Task class: maintenance patch / L3 release hygiene.
- Include the already collected v2.7 offline direct-root boundary,
  `direct_ssh_pbs` synthetic transaction, closed Schema/state surfaces, W1
  observer, W2 durable journal, W3 replay ingress, W4 process-isolated helper,
  offline onboarding, migration guide, support matrix, named-Skill package
  mapping, and this release-package closure.
- Preserve implementation, scientific logic, versioned Schemas, owner
  semantics, historical artifacts, and every fail-closed gate unchanged.
- Freeze the exact candidate scope from the final Git diff and record its path
  manifest and byte hash in handoff evidence. Do not maintain a duplicated,
  hard-coded path count in this checklist.
- Derive the named-Skill package inventory from
  `package_files_with_supplements`; do not freeze a target count in prose. The
  machine name, base manifest, supplements, mapped scripts/references and
  `SKILL.md` owner index must remain closed under offline package regression.
- The canonical ordered Draft 2020-12 inventory remains owned by the static
  Python/CI contract. Missing, extra, reordered, skipped or otherwise drifted
  coverage fails closed without a duplicated module count here.

## Truthful capability boundary

- `direct_ssh_pbs` has exactly the statuses `offline_synthetic`,
  `production_blocked`, and `live_not_ready`. It is not `backend_supported`,
  production-ready, transport-authorized, or live-ready.
- The local package collection includes separately reviewed W1 observer, W2
  durable journal, W3 resource/live replay ingress, and W4 process-isolated
  fixed descriptor-relative helper components. It also includes direct
  onboarding/support, mutation-boundary and offline-backend surfaces.
- W4B fixed trusted server-local session composition is present in the local
  collection and joins W1-W4 in one clean-exec process, but it is a
  non-authorizing seam rather than a production adapter. W5, W6, and W7 are not
  present; direct transport/upload, `qsub`, inspect/fetch, reconciliation and
  separately authorized live-smoke evidence remain blockers. The W3 ingress policy records
  `production_closure=false` and
  `arbitrary_same_process_reflection_isolated=false`.
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
   execute the canonical ordered Draft 2020-12 module inventory,
   including `tests.test_direct_effect_time_replay_ingress_schema_draft202012`,
   `tests.test_direct_root_fixed_mutation_schema_draft202012`, and
   `tests.test_direct_root_mutation_boundary_schema_draft202012`.
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
