# Native Opt to Freq registration

Startup schema `autog-native-source-registration/3` adds the mandatory nullable
`freq_readout` descriptor alongside `opt_readout`. At most one is non-null for a
source. Versions 1 and 2 retain their original closed fields. Paths and hashes
are supplied only by trusted local startup, never HTTP.

The owning `auto-g16-freq-readout-registration/1` binds the original Opt and Freq
sources plus immutable parsed revisions and ensemble material. Every read
replays both sources, the native parser, exact Cartesian association and all
retained ensemble progress. Opt and Freq share one bounded process read slot.

The UI displays units, mode/negative/zero counts, parser version and the distinct
Attempt links. Zero modes remain visible. This is machine evidence, not human
ScientificAcceptance, thermodynamic eligibility or permission to run anything.

Candidate only: no installation or service restart is included.

## Native read deadline amendment r1

Owner accepted the reviewed frontend deadline proposal on 2026-10-06
(SHA-256 `1fcda462b26f45ef5c743ba3c2751f22a1c9f9b4f9d24fb327e10f9c19de71ca`)
for limited offline repair, validation, independent review and local commit.
Installation and publication require their separate authorization.

NativePanel explicitly selects a 120-second transport deadline; ordinary
requests retain 15 seconds. The deadline starts after acquiring a page-wide
query slot, not while waiting in the queue. The shared two-slot budget remains
in force. Leaving a route abandons its consumer but keeps its HTTP slot until
the transport settles or times out; stale responses cannot populate a new
route. Timeout is distinct from navigation cancellation and HTTP errors, with
no automatic retry. A client timeout does not guarantee server work has stopped.
Complete scientific source replay, the server read lock, units and acceptance
semantics are unchanged. Offline timing tests are not real-page acceptance.
