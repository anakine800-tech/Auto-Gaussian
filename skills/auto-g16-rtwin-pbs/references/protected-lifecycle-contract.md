# Auto-G16 v2.6 protected lifecycle contract

PR4K is an additive, owner-sealed, read-only contract for a future protected
adapter implementation. It does not reserve, materialize, publish state,
invoke an adapter, run an effect, submit, reconcile, read runtime
configuration, or perform an external action.

The portable document uses
`auto-g16-protected-lifecycle-structural-projection/1`. Its fixed markers say
that validation is structural only, owner replay is required, and Schema
validity grants neither owner acceptance nor a seal.

The standard Draft 2020-12 Schema and
`validate_protected_lifecycle_structure()` have acceptance-set parity only for
Draft-expressible constraints. They do not claim hashing, derived-ID,
cross-field, class-identity, file-origin, artifact-replay, or
normalization-byte parity. Draft and the public structural validator may both
accept an integral JSON number; only the public structural validator
normalizes its returned Python value to an integer. That normalization is not
a semantic-owner operation or proof. Every fixed validation, scope, status,
and legacy-compatibility marker requires an exact boolean; numeric `0` and `1`
are rejected across the complete fixed-field matrix.

The portable projection contains each PR4F summary once. It does not duplicate
the full PR4F document into predecessor or closure fields. A Schema-valid
hash, identity, ledger, or stage splice remains only a structurally valid
document; it cannot be described as verified, owner-accepted, replayed, or
sealed.

The only seal input is exact typed PR4F `ProtectedInvocationEvidence`.
Acceptance uses the real adjacent PR4F module object's class identity and that
module's owner-issued PR4F sealed bundle. There is no lookalike reconstruction
using module/name/fields/snapshot metadata or `co_filename`.

Before semantic seal or storage, PR4K recursively rebuilds two owner snapshots
of the complete typed evidence using only exact adjacent owner dataclasses,
exact builtin `dict`/`list` containers, exact `pathlib` paths, and immutable
builtin leaves. Caller Mapping/container copy, deep-copy, and reduce behavior
is rejected without invocation. A change between or during snapshots fails
closed. Only the owner-owned graph is retained, so later caller nested
mutation cannot change the document or `assert_current()`. Actual owner,
ledger, local-state, or stage drift still fails.

`required_future_implementation_order` remains a recovery gate, not evidence
of execution. PR4D reservation and entry into `submission_uncertain` are one
future atomic result; reconciliation remains a future one-time state change.
All effect/status fields are false.

The PR4J long-process registry gate remains. PR4D/G/F/I/J,
`legacy_rtwin_pbs.py`, historical schemas, and predecessor fixtures remain
frozen. PR4K adds no reserve, materialize, adapter, state-mutation, retry,
cleanup, deployment, synchronization, or live authority.
