# Auto-G16 v2.6 protected lifecycle contract

`auto-g16-protected-lifecycle-contract/1` is an additive, owner-sealed,
read-only contract for a future protected adapter implementation. It does not
reserve, materialize, publish state, invoke an adapter, run an effect, submit,
reconcile, read runtime configuration, or perform an external action.

The only public owner input is exact typed PR4F
`ProtectedInvocationEvidence`. The fixed adjacent PR4F owner is stable-read
no-follow, loaded from the captured bytes, checked for exact origin and class
identity, and removed from the temporary import cache afterward. Callers
cannot provide a sealed predecessor, mapping, path, stage list/bytes, backend,
runner, callback, command, clock, or runtime override.

The portable document retains the complete PR4F document, duplicate
identity/local/ledger/resource/transport/stage projections, the PR4D and PR4F
orders, PR4J's six fixed effect names, and a
`required_future_implementation_order`. That field is a recovery requirement,
not evidence of execution. Every effect/status field remains false.

PR4D reservation and entry into `submission_uncertain` are one owner-issued
atomic result, represented as one future step. Reconciliation is a future
state-changing `reconcile_exact_attempt_once`, never a read-only operation.
PR4K does not solve local materialization, state publication, outcome/receipt
handling, reconciliation, or adapter wiring.

The legacy pre-reservation stage, caller CLI path/command state, raw effect
owner and job/reconciliation state strategies are not reusable protected
owners. Any future long-running adapter remains blocked until the PR4J
strong-reference registries are removed or a bounded process/object lifetime
is proved. `LegacyTransportAdapter.invoke_reserved_once` remains fail closed.

The in-process result exposes only `document()`, `assert_owner_sealed()` and
`assert_current()`. Production uses a fresh owner UTC time for each replay;
the fixed clock is private test-only state. Offline validity is not live
approval, reservation, adapter validation, execution authority, or permission
for SSH, RTwin, PBS, Gaussian, retry, qdel, cleanup, deployment, or release.
