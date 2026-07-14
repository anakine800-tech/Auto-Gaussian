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
