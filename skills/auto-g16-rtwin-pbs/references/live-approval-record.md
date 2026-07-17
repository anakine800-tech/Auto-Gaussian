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

For a TS/QST route use `auto-g16-live-submission-approval/2`. Keep every `/1`
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
