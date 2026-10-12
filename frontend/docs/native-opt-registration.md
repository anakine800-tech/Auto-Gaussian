# Auto-G16 native Opt startup registration

The explicit `--native-sources` / `--native-sources-sha256` pair remains the
sole startup entry. Registry version 1 retains its exact fields and behavior.
Version 2 requires an `opt_readout` field on each source: `null` for the prior
reader, or an exact `{path, sha256}` descriptor for a bounded Opt registration.

The frontend checks the file with the existing no-follow digest reader and
delegates the closed registration to `Conformer.load_opt_readout`. The owning
backend checks pinned Snapshot identity at startup and replays original proof,
parsed revisions and native refinement when queried. No HTTP parameter supplies
paths, source selection or an execution provider.

Keep existing sources when adding new Opt sources. Independent stores retain
their own namespaces, even when their Project IDs match. The existing native
view renders the verified electronic-energy units, geometry blocks, parser and
artifact provenance, PBS job identity and Opt-only assessment. Missing frequency
evidence remains missing, and optimization does not establish a minimum.

Install a frozen backend/frontend wheel pair in a new directory. Preserve old
installations and data. Before replacing the normal launcher, verify runtime
bytes and exact source registration, finish independent review, stop only the
identified old local service, and ensure its monitor/queue ownership is released.
Preview tests must not run duplicate background monitors or archive workers.
