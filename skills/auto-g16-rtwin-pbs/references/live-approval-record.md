# Auto-G16 Exact Live Submission Approval

## Resource-bound protected submission contracts `/9`-`/12`

`/3`-`/5` and package-2 `/6`-`/8` remain historical/offline replay contracts.
They do not satisfy a new package-4 live submit. Their resource-bound
successors are `/9` for the generic receipt, `/10` for the owner-replayed
open-shell receipt, `/11` for one open-shell family stage receipt, and `/12`
for the fixed-coordinate non-scan constrained-preoptimization receipt `/4`.
Generic `/9` ordinary scope is singlet-only. An ordinary multiplicity greater
than one is blocked by `input_approval_compatibility` before receipt completion
as `blocked_unsupported_open_shell_ordinary`; no specialist owner/schema is
currently available, and `/9` must not be extended silently.

Every `/9`-`/12` record is closed, retains these package-2 fields:

```json
{
  "approval_id": "one-time-operator-decision-id",
  "approver_identity": "reviewed-operator-principal",
  "approved_at": "2026-07-19T08:00:00Z",
  "expires_at": "2026-07-19T09:00:00Z",
  "revocation": {"revoked": false, "revoked_at": null, "reason": null},
  "consumption": {"single_use": true, "consumed": false}
}
```

Its exact scope includes `operation: "submit"` and an `execution` object binding
batch/review hash, stable scientific task, deterministic attempt ID,
idempotency key, estimated core-hours, and the estimate evidence source/hash.
The execution scope additionally binds the exact resource policy ID/hash, gate
ID/hash, resource tier, cores, memory and explicitly reviewed walltime.
Approval validation occurs before reservation; reservation consumes the unique
approval ID/hash under the `/3` ledger lock and writes an immutable local
consumption receipt before network access. Expired, revoked, already consumed,
reused, future-dated, legacy no-time, or scope-mismatched approvals fail closed.
The submitter performs a fresh stable file read/hash/scope/time/revocation
replay after local staging immediately before reservation, then repeats the
replay immediately before qsub. Approval drift or expiry at the second point
reconciles the reserved attempt as definitely not submitted; uploaded evidence
may remain under the no-delete policy, but qsub is not invoked.

Use `auto-g16-exact-cancellation-approval/1` separately for active qdel. It
binds approver and time window, exact project/job ID, current derived
`job.json` state hash, exact execution attempt hash, and one-time consumption.
`--confirmed` is never a substitute and the cancellation record grants no
retry, cleanup or deletion authority.

Before any qstat or qdel, cancellation atomically publishes one immutable
`cancellation-intent.json` with the exact approval/job/attempt hashes and adds
the reservation to the append-only job event log. Any existing intent blocks
every later qdel invocation, including after transport loss or local outcome-
receipt failure. Once qdel invocation starts, every non-success result is
`cancellation_uncertain` and cannot be retried automatically.
`reconcile-cancellation` is remote read-only: it classifies the exact job as
`active`, `absent`, or `unknown`, never issues qdel, and never converts an old
intent into new cancellation authority.

Create this record only after showing and approving the exact structure,
stereochemistry, charge, multiplicity, route, memory, cores, input SHA-256,
fresh project name and `/home/user100/SDL/<project>` directory.

```json
{
  "schema": "auto-g16-live-submission-approval/1",
  "decision": "approved",
  "explicit_confirmation": true,
  "scope": {
    "project": "reviewed_project",
    "remote_workdir": "/home/user100/SDL/reviewed_project",
    "input_sha256": "<64-lowercase-hex>",
    "route": "<exact route from preflight>",
    "mem": "12GB",
    "nprocshared": 8,
    "charge": 0,
    "multiplicity": 1
  },
  "authorizations": {
    "create_server_directory": true,
    "submit": true,
    "retry": false,
    "cancel": false,
    "cleanup": false,
    "delete_server_data": false
  }
}
```

The record authorizes one submission of the exact scope only. It does not
authorize a retry, changed chemistry, changed resources, active-job
cancellation, scheduler cleanup, or server-file deletion. A dry run may omit
the record because it performs no SSH, directory creation, upload, PBS or
Gaussian action.

Both `gaussian_auto.py auto` and the low-level `gaussian_rtwin_pbs.py submit`
use the shared transport validator before any live transport. `--confirmed`
never substitutes for a receipt. A dry run may omit receipts and then reports
`live_submission_ready: false`. A supplied live receipt is evaluated only after
the exact input-approval receipt has validated, so an old or unrelated live
record cannot elevate an unreviewed input.
The submit path validates `/3` or `/4` against the unique captured input
snapshot and uses the same stable receipt read for both JSON validation and
receipt SHA-256.
It rechecks staged bytes and upload-file hashes before any network action.

Historical TS records use `auto-g16-live-submission-approval/2`. Keep every `/1`
field and add this exact object to `scope`:

```json
"scientific_maturity": {
  "edge_id": "reviewed_edge",
  "node_id": "reviewed_pilot_or_formal_node",
  "pilot": true,
  "maturity_gate_sha256": "<exact-file-sha256>",
  "maturity_gate_payload_sha256": "<exact-payload-sha256>",
  "scientific_action_authorization_sha256": "<exact-file-sha256>",
  "scientific_action_authorization_payload_sha256": "<exact-payload-sha256>"
}
```

The PBS submission path independently revalidates that gate. `/2` still grants
only one exact submission and does not weaken the separate protocol, input,
retry, cancellation, cleanup or server-data boundaries.

Before creating `/2`, protected TS/scan submission preflight also requires a
valid `gaussian-scientific-action-authorization/1` for the exact DAG node,
input hash, project, work kind, resource tier and budget request. That offline
artifact always has `no_submission_authorization: true`; it is evidence for
scope consistency and never substitutes for this live approval record.

## New live approval `/3`

Every new receipt `/1` live submission requires
`auto-g16-live-submission-approval/3`.
Its scope keeps the exact project, server directory, input hash, route,
resources, charge and multiplicity fields above, and adds:

```json
{
  "work_kind": "ordinary",
  "input_approval": {
    "schema": "gaussian-input-approval-receipt/1",
    "sha256": "<exact receipt file SHA-256>",
    "payload_sha256": "<exact receipt payload SHA-256>",
    "input_sha256": "<exact Gaussian input SHA-256>",
    "work_kind": "ordinary"
  }
}
```

`/3` is currently prospective-live capable only for ordinary and closed-shell
minimum work.
Protected TS/scan/IRC work must not combine a maturity `/1` action check,
generic input receipt and live `/3`; that is a mixed-generation chain.
Maturity gate `/1` and historical live `/2` remain replay-only. Current
maturity `/2` remains blocker-only, so a protected prospective-live chain is
not yet reachable. Future integration requires an exact maturity action `/2`,
action authorization `/2`, and specialist input receipt before a matching live
contract can be introduced. Missing work kind never defaults to `ordinary`.
Historical `/1` and `/2` records remain independently replayable by the shared
validator when checked against their historical summaries; they are not
silently granted the new input-receipt binding or accepted for a new live
submission.

## Main-group open-shell minimum live approval `/4`

`auto-g16-live-submission-approval/4` is the only prospective-live contract
for a fully owner-replayed `gaussian-input-approval-receipt/2`. It is restricted
to `work_kind: minimum`, multiplicity 2 or 3, and reference family `U` or `RO`.
Its closed scope binds the exact project and `/home/user100/SDL/<project>`, input
SHA-256, route, memory, cores, charge, multiplicity, receipt file/payload/input
hashes, owner workflow, electronic-state-review/input-handoff/input-audit and
selected-option payload hashes, reference family, resource tier and
`owner_replay_passed: true`.

## Fixed-coordinate constrained-preoptimization live approval `/12`

`auto-g16-live-submission-approval/12` is the only live contract for
`gaussian-input-approval-receipt/4`. It requires the resource-bound protected
execution scope and is restricted to `work_kind: minimum`, multiplicity 1, one
explicit Cartesian route, and the owner-replayed
`closed_shell_fixed_coordinate_preoptimization_v1` workflow.

Its closed scope adds `fixed_constraint_owner`, binding the specialist audit
payload, selected-option payload, exact input hash and route, charge,
multiplicity, exact resource tier/cores/memory, canonical constraint-set hash,
constraint count and `owner_replay_passed: true`. The constraint count is
1–64. `/9`, `/10`, or `/11` cannot substitute for `/12`, and `/12` cannot
approve generic, open-shell, frequency, TS/QST, scan, IRC, checkpoint or Link1
inputs. It retains one-time/time-window/revocation/consumption fields and the
same no-retry, no-cancel, no-cleanup and no-delete boundary as `/9`–`/11`.

`/2` receipt plus `/3`, `/1` receipt plus `/4`, protected maturity evidence,
TS/IRC/scan/QST/Link1/checkpoint inputs, metals, open-shell singlets, broken
symmetry and multireference states all fail closed. Authorizations remain
exactly directory creation and one submission `true`; retry, cancellation,
cleanup and server-data deletion are `false`. Offline prepare and dry-run emit
only a scope proposal and required schema. They do not emit an approved `/4`.
