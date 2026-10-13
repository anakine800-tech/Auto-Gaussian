# Auto-G16 native Opt readout

Concurrent Opt requests in one consumer process share a read slot across all
registrations. Waiting is bounded to 30 seconds; expiry returns the existing
`store-unavailable` query error without starting proof replay. The slot is
released after success or failure. This coordinates reads around the retained
Transport owner's exclusive guards; it neither relaxes those guards nor retries
failed evidence reads. Independent consumer processes can still contend for the
underlying Transport owner and must preserve that owner's rejection.

This offline slice consumes completed Gaussian Opt evidence under the accepted
[successor refinement contract](proposals/gaussian-successor-result-refinement.md)
and [immutable destination adjustment](proposals/gaussian-successor-destination-addendum.md).
It grants no live execution, installation, frequency calculation or scientific
acceptance authority.

The source catalogue in Execution is scoped to the current request context.
Each entry selects one exact original Snapshot, Core and Transport database,
including physical file identity, content hash and original bootstrap identity.
An active catalogue never falls back to the historical singleton registration.
Without a catalogue, existing singleton readers behave as before.

`Conformer.OptReadout` is registered at trusted local startup. It pins the parsed
revision and the profile/prior/refined material, reopens original proof read-only,
and replays source validation, parsing, Opt assessment, member audit and joint
deduplication. The retained refined payload must exactly equal native replay.
The query snapshot must equal the registered parsed revision. No request can
choose a path, infer a latest revision or write a record.

`load_opt_readout(content, digest)` accepts the closed, hash-bound
`auto-g16-opt-readout-registration/1` startup document. It contains a pinned
material binding and 1–32 uniquely identified member sources. Each source names
the original Core/Transport and bootstrap identities, the fully pinned Snapshot
file, parsed revision, transport root and explicit parser version. Startup only
opens pinned Snapshot files; query-time proof owns all business-store checks.
Unknown fields, duplicate keys/identities, changed Snapshot identities and
unsupported parser versions are rejected. This document grants no live authority.

The existing Native Query source registration optionally receives this owning
reader. Result projects the verified facts; Query consumes its detached values
without decoding private execution receipts. Existing HTTP routes and fact DTOs
remain unchanged. Energy is electronic energy in hartree, geometry is angstrom,
and absent frequency evidence remains missing. Source observation, parsed Result,
parser version, input/output hashes, CREST member and superseded ensemble remain
traceable. Independent stores keep their source namespaces even when Project IDs
match.

Opt geometry acceptance is `INCOMPLETE` with `incomplete-mode-count`. Refined
members may be `optimized_frequency_pending`; thermodynamic and TS eligibility
remain empty. Displaying these facts does not constitute minimum validation.
The existing generic UI renders geometry and ensemble evidence as text; this
slice does not add a 3D viewer or trajectory controls.

## Validation and integration scope

Reuse receipt-source, successor Result/Opt/revision and native-query tests.
Supplement catalogue lifecycle/concurrency tests with exact real two-source
replay, fresh-process reopening, list/detail equality and rejection of altered
material, parsed facts, original identity or a substituted revision. Verify the
existing UI in an isolated loopback preview and retain original file digests.

The change only reads historical local artifacts. No live transport, scheduler
or Gaussian operation is introduced, so validation uses local native SQLite and
filesystem evidence. Source integration and replacement of an installed
workbench remain separate actions; a candidate preview is not an installation.
