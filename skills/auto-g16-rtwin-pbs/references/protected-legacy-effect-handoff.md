# Auto-G16 protected legacy effect handoff

`auto-g16-protected-legacy-effect-handoff/1` is a non-executable PR4N
readiness contract.

- Input: one exact, current `SealedProtectedLocalMaterialization`.
- Internal witness: one exact module-issued PR4M lifecycle readiness value.
- Output: an owner-sealed typed handoff plus a portable structural projection.
- Effects: none.

The owner does not accept mappings, JSON documents, paths, runtime
configuration, clocks, adapters, backends, callbacks, commands, or runners.
It does not create a legacy transaction plan, effect plan, raw owner, or
registry entry. Its projection keeps effect, adapter, qsub, runtime binding,
retry, cancel, cleanup, and deletion flags false.

Schema validation is structural only. Owner acceptance additionally requires
exact predecessor class/module/source identity, PR4L `assert_current()`, the
module-issued witness, and owner recomputation of all hashes. PR4D/G/F/K/L and
historical records remain frozen; no migration, rehash, or backfill exists.

This handoff is not an adapter invocation and grants no live or scientific
execution authority.
