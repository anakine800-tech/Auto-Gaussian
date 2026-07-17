# Auto-G16 Exact Live Submission Approval

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
The submit path validates `/3` against the unique captured input snapshot and
uses the same stable receipt read for both JSON validation and receipt SHA-256.
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

Every new live submission requires `auto-g16-live-submission-approval/3`.
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

`/3` is currently prospective-live capable only for ordinary and minimum work.
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
