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
`valid_until`, ordered nodes with `priority`, `status`, `reason` and `options`.
Each option has `fraction`, `cores`, `mem_gb` and a matching configured `tier`, or
null if no tier fits. Failed/expired snapshots never authorize preparation.
The normal monitor adds consistency fields for opted-in nodes using its existing
PBS node/job queries; no extra per-node SSH is used. The first upgraded snapshot
is required; older snapshots without consistency evidence remain unknown.

Prepare requires `--target-node NAME` and accepts `--node-fraction 1/2` (default)
or `1/4`. Half/quarter of registered slots must divide exactly, with two GB per
core, and must equal the requested existing tier. No arbitrary resource expression
or automatic node choice is accepted. A new manifest binds name, fraction, slots
and queue under `node_target`; the rendered script binds these plus cores/memory
into the existing bundle hash. The confirmation displays the full target request.
Standing policies do not replace explicit node-bound approval or a dialog.

Submit admits one targeted Attempt only. It checks fresh all-job and node views
after confirmation before consuming approval/Claim, then again after uploading
the verified bytes and before qsub. A changed node, queued named request, missing
capacity, conflicting allocation, restriction or invalid identity refuses the
request; no node substitution or automatic retry occurs. A late failure retains
the consumed Claim and failed-presubmit state, as in the existing lifecycle.

After scheduler acceptance the job binding is retained even if the placement
query fails. `node_placement` in status is pending while queued, verified only
when exact exec_host names and slot counts match, and mismatch/unverified when
the evidence is wrong or insufficient. Mismatch stops later status processing;
no automatic cancellation is added. Program launch also checks the scheduler's
PBS_NODEFILE before creating scratch or starting Gaussian. Unknown short-lived
jobs without observed placement are not declared placement-verified.

## Limits requiring separate site acceptance

Read/check/qsub cannot atomically reserve a node across two computers or prevent
another scheduler client from acting after the last read. Tests reject a competing
request once visible; they do not establish global exclusion. No SSH or real
submission is authorized during this development round. Before production use,
check the site's named-node and sharing behavior with an explicitly approved
non-research job. Do not silently add a whole-node exclusive request: it can
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
