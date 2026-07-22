# Auto-G16 execution authorization

## Authority boundary

`auto-g16-execution-request/1` is intent only. Its fixed markers say that it is
a proposal, is not calculation-ready, and contains no execution authorization.
No request, plan, profile, receipt, resource gate, batch record, or readiness
result authorizes a live operation.

`auto-g16-execution-authorization/1` is the final immutable human approval
record. It does not point at an unowned decision hash. The artifact itself
closes the approving principal, approval and validity times, active revocation
and single-use state, exact request and input, scientific owner receipt,
profile/backend/transport/target, workspace and runtime bindings, exact resource
tuple and resource evidence, batch/task/attempt/idempotency, typed attestation
operations and nonces, and the exact three one-time operations. Only a human may
issue this artifact. The validator validates an existing record; it never
creates or infers approval.

Schema timestamp patterns provide only a second-precision `Z` lexical shape.
The Python owner validates real UTC calendar dates, ordering and active windows;
no JSON Schema `format` engine is assumed. Specialist scientific receipts `/2`
and `/3` are closed to `minimum`; `ordinary` is accepted only with receipt `/1`.

## Offline gate

`scripts/execution_authorization.py` strictly decodes the two new contracts and
replays the existing PR2, scientific input, resource and execution-batch owners.
It does not copy or relax those owners. Its only successful gate status is
`closure_valid_offline`; `live_ready`, `calculation_ready`, network, mutation
and submission flags are always false. The module has no CLI, transport or
scheduler action and creates no command or transfer plan.

The caller-supplied registry snapshot is untrusted negative evidence. A known
authorization ID, consumed ID or attestation nonce rejects. An empty snapshot
or a miss never proves global uniqueness, availability, or single-use. The API
accepts neither a callback nor a caller assertion that a snapshot is trusted.

## Future owner gap

Runtime and workspace do not yet have a trusted live owner. Before any future
mutation, PR4 or PR6 must replay this full closure against trusted current
state, prove the authorization and nonces globally unused, and atomically
consume the one-time authorization. PR3 implements neither persistent storage
nor consumption and makes no anti-replay claim for a stateless validator.

## Compatibility and rollback

Historical live approvals retain only their existing legacy or in-flight
interpretation. They cannot be backfilled, re-hashed, or admitted to the new
profile/direct gate. Adoption is additive: producers may continue the old path
unchanged, while new profile-mode work must issue both new artifacts. Rollback
removes the PR3 schema/owner package and returns callers to the unchanged legacy
path; it does not rewrite historical artifacts. PR4 must not begin until PR3 is
merged and independently reviewed.
