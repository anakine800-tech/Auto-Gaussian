# Auto-G16 v2.6 protected-submit contract boundary

`auto-g16-protected-submit-bundle/1` is an additive, non-executable authority
contract. It does not change or reinterpret execution request or authorization
`/1` or `/2`. The `/2` pair remains a read-only transport-identity handshake
with no stage or submit authority.

The owner replays the existing exact-input approval, resource-bound live
approval `/9`–`/11`, execution batch `/3`, resource gate `/2`, scheduler
snapshot and transport-identity closure. It then binds the exact project,
scientific task, input hash, deterministic attempt, idempotency-key hash,
resource tuple, fixed `/home/user100/SDL` workspace policy, immutable stage
manifest/bundle hashes, fixed operation order, approval window and single-use
scope.

The backend-neutral facade exposes two typed functions:

- `seal_protected_submit_bundle(*, evidence)` performs non-consuming owner
  replay and returns an owner-sealed value.
- `reserve_protected_submit_bundle_once(*, evidence)` repeats the complete
  closure at the state owner's trusted UTC time and atomically reserves the
  authority before any future effect.

Neither function accepts caller time, consumption state, an effect callback,
an adapter, a backend selector or an executable object. The portable artifact
contains no free command, argv, shell, host, path, configuration, callable or
raw artifact bytes. Its only path-like value is the fixed allowed-root policy.
The facade resolves the owner only from its own adjacent
`protected_submit_contract.py`, verifies the real file/spec origin and restores
the prior same-name module cache exactly.

Draft 2020-12 Schema validation is structural. Timestamp strings use canonical
second-precision `Z` form, while the owner additionally parses real calendar
dates. Draft-integral values such as `1.0` are accepted like `1`, rejected when
boolean, and normalized to one integer representation before the bundle
self-hash. Schema validity alone never issues a seal; both public facade
functions always replay the exact owner.

Reservation publishes `submission_uncertain` before any future effect and
permits no automatic retry. PR4D provides no stage, submit, status, fetch,
cancel, cleanup, delete or reconciliation implementation and never calls
`LegacyTransportAdapter`. The existing fail-closed placeholder remains
unchanged.

PR4I mechanically places the historical CLI transaction behind one private
sealed-plan owner. That extraction adds no protected-submit factory or adapter
authority: `LegacyTransportAdapter.invoke_reserved_once` still fails closed,
and the CLI factory remains the only plan source.

The public Schema is
`contracts/execution/protected-submit-bundle.schema.json`; the packaged owner
is `scripts/protected_submit_contract.py`. Passing placeholder-only offline
tests proves local contract behavior, not RTwin, SSH, PBS, Gaussian, adapter or
live validation. The exact-pinned Draft validator is a dedicated test-only
dependency and is not part of core, chemistry, adapter or execution runtime.
An independent L3 review and a separate future adapter task remain mandatory.
