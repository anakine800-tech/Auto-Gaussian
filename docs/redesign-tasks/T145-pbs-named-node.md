# T145 — Explicit PBS node targeting

Status: implementation; no live deployment or calculation authorized.

## Problem and scope

An opt-in PBS entry needs an explicitly selected, idle named node. A node marked
free may already contain allocated slots. A monitor recommendation is not a live
admission check, and qsub acceptance is not proof of execution placement.

Allowed paths: ag/src/ag/{config,attempt,render,submit,status,cli,clusters,route,pbs,monitor,remote,approval,submission,node_targeting}.py,
ag/templates/node-target.pbs, ag/tests/**, docs/redesign-tasks/T145-pbs-named-node.md,
docs/T145-node-targeting.md, docs/DEVELOPING.md, docs/LESSONS.md.
No version change, production config, private identifiers, old manifest mutation,
remote permission changes, automatic cancellation, retry or scheduler fallback.

## Behavior

- Per-entry generic allowlist, denylist, ordered priority groups and restricted
  nodes; strict names, exact identities, no shell/resource expressions.
- Only new Gaussian Attempts on enabled PBS entries require an explicit node.
  One targeted Attempt per submit. Half of registered slots by default, quarter
  by explicit choice; two GB per core, matching an existing configured tier.
- Bind target, fraction, registered capacity and queue in new manifests; render
  a named-node request. Bind resources and these choices in the hashed script.
- Recommend only fresh, unambiguous, free nodes with zero allocation and known
  sufficient capacity. Never select automatically. Special CPU restrictions
  remain disabled until separately verified; ppn does not select CPU indices.
- Requery nodes and all jobs after confirmation, before consuming approval or
  claim, and again before qsub. Fail closed on ambiguity/occupation. No fallback.
- Record Q/H/W/T placement as pending even with exec_host. Verify only R/E/S/C
  with exact complete allocation; missing/abnormal state never verifies.
  Mismatch or unverified blocks further automatic operations, retains evidence and
  never cancels. Guard program launch against an unexpected PBS node file.
- A read/check/qsub sequence is not an atomic cross-client reservation. Test
  observed races and retain the remaining scheduler race as a live acceptance
  limitation; do not assert an unverified site exclusive-access policy.

## Frontend interface

`ag clusters --json` optionally advertises `node_targeting` with
`default_fraction: "1/2"` and `fractions: ["1/2", "1/4"]`.
`ag nodes --cluster ENTRY --json` reads only local monitor cache and returns
`schema: "ag-node-targets/1"`, `cluster`, `fresh`, `sampled_at`, `valid_until`, and ordered `nodes`.
Each node has `name`, `priority_group` (original 1-based group, null for deny-only
names), `order` (1-based total order preserving group member order), `priority`
(compatibility alias of order, not a group), `status`, `reason`, and `options`.
Options contain `fraction`, `cores`, `mem_gb`, `tier` (null when unavailable).
Statuses: available, occupied, insufficient, stale, restricted, forbidden,
unknown. CLI prepare accepts `--target-node` and `--node-fraction`.
Manifest optional `node_target` is immutable; old manifests/scripts stay intact.

## Validation and delivery

Synthetic tests cover policy names/order, half/quarter of heterogeneous nodes,
stale/unknown/conflicting observations, occupation changes during confirmation,
two-client competition, missing targets, special restrictions, integrity before
failure, post-submit allocation mismatch, queued exec_host remaining pending,
group/member order, strict parsing failure preserving read-only monitoring while
targeting fails closed, and legacy byte parity.
Full backend tests, effective private-term scan, diff review, exact HEAD and CI.
Separate backend/frontend PRs; no merge, release or live testing this round.
Owner's current instruction explicitly schedules approved real smoke after
review, paired release and development-machine deployment, overriding older
pre-merge live-test instructions. Site CPU mapping and scheduler semantics are
unverified. Private configuration proposals/audits stay outside this repository.
