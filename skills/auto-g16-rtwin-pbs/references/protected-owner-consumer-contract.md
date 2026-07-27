# Auto-G16 protected owner consumer boundary

The additive owner-consumer contract accepts only the exact current protected
runtime/state capability. It keeps the PR4L directory frozen, creates one
sibling upload bundle containing the sealed non-checksum stage bytes, a
successor submission intent and a replacement checksum manifest, then records
runtime consumption and durable uncertainty before exposing local effect-plan
inputs.

The protected reservation, legacy execution ledger and runtime journal remain
distinct authorities. The intent explicitly records that no legacy ledger
reservation is present. The owner never constructs the legacy effect plan or
raw owner, calls an adapter or runner, performs transport/PBS/Gaussian, reads
remote state, retries, cancels, cleans up, deletes, migrates or backfills.

After uncertainty, recovery is read-only reconciliation only. Schema validity
is structural and never substitutes for exact owner replay or the non-copyable
in-process seal. See
[`docs/v2.6-protected-owner-consumer-contract.md`](../../../docs/v2.6-protected-owner-consumer-contract.md)
for the exact ownership matrix, upload bytes and remaining effect-time gate.
