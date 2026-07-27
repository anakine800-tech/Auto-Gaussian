# Auto-G16 v2.6 deterministic local-state binding

`auto-g16-local-state-binding/1` is an additive, read-only path-ownership
contract for a future protected successor. It is not an invocation contract,
adapter, effect, reservation, execution approval, live validation, deployment,
or migration.

The owner accepts typed PR4D protected-submit evidence plus an exact canonical
workspace root and exact ledger path. It does not accept `local_dir`. After
fresh PR4D owner replay, it derives:

```text
<workspace-root>/outputs/<project>/<attempt_id>/
<workspace-root>/outputs/<project>/<attempt_id>/execution-batch-v3.json
```

`project` and `attempt_id` come only from the owner-sealed protected-submit
closure. The exact ledger is read no-follow through repeated stable descriptor
reads, parsed with the existing duplicate-key-rejecting batch owner, validated
as the current execution-batch `/3` by the existing resource owner, and
required to equal the PR4D typed ledger evidence.

The workspace root, derived local directory, and ledger must already exist and
be owned by the current user where required. Every ancestor is opened
no-follow, lexical/realpath drift and case/Unicode aliases are rejected, and
the derived directory must contain only `execution-batch-v3.json`. The
local-state path owner creates no workspace/local-state directory, changes no
existing permission, takes no legacy ledger reservation lock, and writes
no workspace, ledger, or binding state. PR4D keeps its already-reviewed
process-private temporary validation behavior unchanged.

The portable JSON stores one path value only: the strict
`outputs/<project>/<attempt_id>` relative local directory. Its layout version
and `execution-batch-v3.json` basename are fixed; a caller cannot provide a
relative ledger path or choose a basename. The owner derives the full relative
ledger path deterministically. Domain-separated path digests are portable,
but absolute paths never are.

The in-process paths and binding still retain exact canonical `Path` values
and initial inode identities and can assert the same read-only state again
before later use. They carry no command, callback, configuration, backend,
adapter, or effect.

The backend-neutral facade adds only:

- `derive_local_state_paths(*, evidence)`
- `seal_local_state_binding(*, evidence)`

Historical request/authorization `/1` and `/2`, protected-submit bundle `/1`,
the legacy CLI, and historical directories remain frozen with no migration,
rehash, or backfill. A future PR4F must bind the local-state payload hash, and
a later adapter must reassert the binding immediately before any separately
authorized effect.
