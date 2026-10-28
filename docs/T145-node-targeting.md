# Explicit PBS node targeting

This feature is opt-in per entry. A `node_targeting` table contains four required
fields: `allowed_nodes`, `denied_nodes`, `priority` (ordered groups of names), and
`restricted_nodes`. The priority groups cover each allowed name exactly once;
group order and order within a group are preserved. Deny takes precedence, and
restricted nodes cannot be submitted. No actual site configuration belongs in Git.

Only Gaussian on PBS is initially supported. Other entries retain their original
scripts, preparation, approvals and scheduling behavior. Do not enable the table
over old prepared Attempts expecting their manifests or scripts to be rewritten.
An old unbound Attempt is refused on a newly opted-in entry, leaving it unchanged.

`ag nodes --cluster ENTRY --json` reads the local monitor cache without SSH or
writes. Its `ag-node-targets/1` response includes `fresh`, `sampled_at`,
`valid_until`, ordered nodes with `priority_group`, `order`, `priority`, `status`,
`reason` and `options`. `priority_group` is the original 1-based configured group;
deny-only names appended after the allowlist have null group. `order` is the
1-based overall sequence, preserving order within each group. `priority` remains
an alias of `order` for compatibility; it is not a group number. For synthetic
groups `[A,B,C], [D], [E], [F,G], [H]` and deny-only `I`, groups are
`1,1,1,2,3,4,4,5,null` and order is `1..9`. Deny wins even for grouped names.
Each option has `fraction`, `cores`, `mem_gb` and a matching configured `tier`, or
null if no tier fits. Failed/expired snapshots never authorize preparation.
T157 adds `selectable` and `selectable_reason` to each node and each option.
A node is selectable when at least one option passes; prepare also checks the
specific requested fraction/tier. Each option's `capacity` is the unchanged
T156 `capacity.evaluate_node` result for its `cores`/`mem_gb` request, including
`fits_total`, `availability`, `reasons`, `cpu_source` and `memory_source`.
The enclosing response supplies its sample time and validity window; evaluation
uses the same snapshot rows rather than rereading the cache for each option.
Legacy `status`/`reason` and display-based tier mapping remain display fields:
unknown exact capacity does not become `insufficient` or erase a configured tier.
Use the option's `selectable` for eligibility; the display can round memory at a
boundary that exact capacity rejects. An occupied node stays occupied
even when selectable. Consumers without `selectable` keep their old status-based
behavior. Priority and fraction order are unchanged; no node is selected automatically.
The normal monitor adds consistency fields for opted-in nodes using its existing
PBS node/job queries; no extra per-node SSH is used. The first upgraded snapshot
is required; older snapshots without consistency or exact total-memory evidence
remain unknown. Missing assigned-memory information alone is only capacity advice.
If strict targeting parsing fails, the ordinary read-only node display and its
hardware fields are retained with a diagnostic note. All retained nodes are
marked inconsistent for targeting; neither recommendations nor live admission
can use this fallback to authorize a submission. No extra query is introduced.

Prepare requires `--target-node NAME` and accepts `--node-fraction 1/2` (default)
or `1/4`. Half/quarter of registered slots must divide exactly, with two GB per
core, and must equal the requested existing tier. No arbitrary resource expression
or automatic node choice is accepted. A new manifest binds name, fraction, slots
and queue under `node_target`; the rendered script binds these plus cores/memory
into the existing bundle hash. The confirmation displays the full target request.
Standing policies do not replace explicit node-bound approval or a dialog.

Candidates, prepare and live admission share the same policy. Supported PBS
states are exactly `free`, `job-busy` and `job-exclusive`, matching T156's capacity
interpretation; offline, down, unknown and unsupported compound states reject.
Existing jobs from this account or other accounts, allocated CPU/memory and
named queued requests do not reserve the whole node. A request that fits total
specifications may queue even when current free resources are insufficient.
Half/quarter mapping always uses registered total slots, never the remaining slots.
Total memory uses T156's exact byte evidence, not rounded GB display values.
Unknown assigned memory yields capacity `unknown` without a new submit ban;
missing total capacity, contradictory allocation evidence and policy restrictions
still reject. This policy applies only to opted-in targeting, not ordinary entries.

Submit admits one targeted Attempt only. It checks fresh all-job and node views
after confirmation before consuming approval/Claim, then again after uploading
the verified bytes and before qsub. New occupation alone passes both checks.
Changed registered slots, insufficient/unknown total memory, conflicting evidence,
restriction or invalid identity still refuse the request; no node substitution
or automatic retry occurs. Account limits and shared-entry minimum caps remain
in their existing positions. A late failure retains
the consumed Claim and failed-presubmit state, as in the existing lifecycle.

After scheduler acceptance the job binding is retained even if the placement
query fails. `node_placement` is pending for Q/H/W/T, even when exec_host already
appears. Only R/E/S or completed C with complete scheduler allocation history
can be verified, and exact exec_host names and slot counts must match. Missing
allocation or missing/abnormal job state is unverified; conflicting allocation
is mismatch. Both mismatch and unverified stop later status processing;
no automatic cancellation is added. Program launch also checks the scheduler's
PBS_NODEFILE before creating scratch or starting Gaussian. Unknown short-lived
jobs without observed placement are not declared placement-verified.
Previously verified execution evidence is retained after scheduler disappearance
or a C record without allocation; a malformed present record is not disappearance.

## Limits requiring separate site acceptance

Read/check/qsub cannot atomically reserve a node across two computers or prevent
another scheduler client from acting after the last read. Visible occupation is
accepted when total specifications and consistency checks pass; tests do not
establish that the scheduler will start jobs together. This development round
submits no test calculations and performs no additional remote queries.
Two supplied historical PBS snapshots were copied and hash-verified locally:
expired candidates remain unselectable, and missing exact capacity fields remain
unknown without changing timestamps or reconstructing byte values. A `free` state
coexisted with allocation evidence; state alone does not establish an idle node.
The supplied occupied targeting rows had inconsistent evidence. A fresh, consistent
shared-node positive case and scheduler parallel execution were not observed;
those admission paths are covered by synthetic records and fake Transport only.
Future site checks require explicit scope/authorization for the existing fixed
`qstat -f` and `pbsnodes -a` queries; no test job is authorized by this document.
Do not silently add a whole-node exclusive request: it can
change scheduler accounting and is not equivalent to requesting half the slots.

Torque documents named-host requests and an exclusive-access option, but notes
that the latter depends on compatible schedulers/cpusets. This is documentation,
not evidence about a particular deployment:
[Torque qsub](https://docs.adaptivecomputing.com/torque/6-0-1/Content/topics/torque/commands/qsub.htm).
No exclusive-access command is rendered here. A special CPU subset remains in
the restricted list until index numbering, physical/PBS mapping and scheduler
allocation can be demonstrated. A ppn count never proves CPU-index affinity.

Delivery is a reviewed backend PR plus a separate frontend PR. Version remains
unchanged. All tests use synthetic nodes, queues and jobs. Paired release,
development-machine deployment, real smoke and research-machine deployment each
remain later owner-controlled stages; CI success is not site acceptance.
