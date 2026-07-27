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

For new legacy PR4B submissions, published `/1` is replay-only and cannot
express the second-hop handshake authority or both adapter-owned config refs.
The permanent non-authorizing `auto-g16-execution-request/2` is the new intent
artifact. It directly binds `execution-profile/2`, both hash-only config
references, exact two-hop identity, project and all three requested operations.
The additive `auto-g16-execution-authorization/2` references that exact request
ID and canonical digest. Historical `/1` request/authorization references are
provenance only and must close against the actual owner-validated artifacts. Its
authority delta explicitly denies stage, submit, cancel, fetch and arbitrary
commands. Neither version is executable in this prerequisite patch.

Schema timestamp patterns provide only a second-precision `Z` lexical shape.
The Python owner validates real UTC calendar dates, ordering and active windows;
no JSON Schema `format` engine is assumed. Specialist scientific receipts `/2`
and `/3` are closed to `minimum`; `ordinary` is accepted only with receipt `/1`.

## Offline gate

`scripts/execution_authorization.py` strictly decodes the two new contracts and
replays the existing PR2, scientific input, resource and execution-batch owners.
It does not copy or relax those owners. The supplied resource gate is fully
recomputed by the original `resource_efficiency.evaluate_gate` using the exact
policy, scheduler snapshot, ledger, execution scope, resource tuple, evidence,
ID and time; the recomputed and supplied gate documents must be identical.

Every pathname input is captured once with `O_NOFOLLOW` semantics. Only PR2,
scientific, resource and batch artifacts that an existing path-based owner must
read again are copied into a fresh private `0700` temporary validation
directory with `O_EXCL`/`0400` files; those owners read only these snapshots,
and refs come from the same captured bytes. PR3-native request, authorization
and registry documents are validated directly in memory from their captured
bytes and are not reopened by a second owner. The directory is removed on
exit. This is an ephemeral local validation write, so the result reports
`ephemeral_validation_copy_performed=true` while external and persistent
mutation, network and submission remain false.

The owner bundle selects exact local origins and deterministic dependency
identity for the platform, batch, resource, Gaussian, log, protocol and runtime
owners under import/reentrant locks, temporarily isolates their generic module
names, then restores every preexisting cache object. This removes repository/
packaged `runtime_config` import-order dependence without accepting a cached
module as authority. Specialist scientific owner dependencies are
also origin checked. Its only successful gate status is
`closure_valid_offline`; `live_ready` and `calculation_ready` remain false. The
module has no CLI, transport or scheduler action and creates no command or
transfer plan.

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
path; it does not rewrite historical artifacts or retain temporary validation
copies. PR4 must not begin until PR3 is merged and independently reviewed.
