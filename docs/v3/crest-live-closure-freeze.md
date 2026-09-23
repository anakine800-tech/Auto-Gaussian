# Auto-G16 V31 CREST design freeze

On 2026-09-16 the primary task accepted the independently reviewed
`V31-CREST-LIVE-CLOSURE-01` design under the Owner's explicit delegation to
approve bounded technical decisions. Reviewer `crest_contract_review` is not
the implementation author. Its final independent finding was PASS after the
read-only source-proof, output-chemistry, and legitimate MAINLOOP fixes.

Accepted contract: [crest-live-closure-contract.md](crest-live-closure-contract.md)
SHA-256 `8a42aa6a82b28b13413412073c78802ecb426f26c251686191a0d157fbf5601e`.
This freeze supersedes only that document's candidate status, leaving its
reviewed bytes intact. Base commit
`b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58`, tree
`e499ddc3435976d7f2c4b2f5dfbe07b7eb6e5216`.

This decision enables bounded offline implementation and focused validation.
Source tracing is complete in the separate official-source dossier; current
binary/runtime qualification, candidate review, installation and exact
Scientific/Batch/Operational/live approval remain separate gates. No live
effect, publication or merge follows from this design freeze.

## Accepted bounded deltas

The primary delegate accepts the independently reviewed source-proof and fresh
Project deltas on 2026-09-16. The parent coordination task confirmed that the
fresh Project route is within the Owner delegation; `crest_contract_review`
reviewed its native constraints and the source-proof design/implementation.

- [crest-readonly-source-addendum](crest-readonly-source-addendum.md), SHA-256 `e79ad4fcbee60f3ec786c361fc798ef5f50c3fbea0b65571c9e5431d69f934cb`.
- [crest-fresh-project-addendum](crest-fresh-project-addendum.md), SHA-256 `62bfa8752e2af688896347d8d21e9bd031ad84473347a9ce81933c147f739026`.

These explicitly supersede the original contract's existing-Project reuse
paragraph and extend its narrow allowed scope to the read-only runtime-row
validator in `auto_g16/transport/program.py`. The fresh Project operation and
final Attempt submission have separate exact live gates. They do not grant a
live qualification PASS; dynamic CREST runtime closure remains under review.

## Accepted CREST loader delta

On 2026-09-16 the primary delegate accepts the independently reviewed
[crest-loader-closure-addendum](crest-loader-closure-addendum.md), SHA256
`4af259760f044e0a0640febb58679225bbeb099d8c93f9ce84788b62a30af4ef`.
`crest_contract_review` independently confirmed no remaining P1/P2 for the exact
30478-byte helper source SHA256
`e3567cbac25fd07b5012b1d9782800b236a295bf5992c51914f9ee80604d0c19`, including
the narrowly bounded deduplicated alias rule and lossless failure diagnostics.
The parent coordination task separately accepted the glibc source interpretation
and retained both initial and cache-corrected semantic reviews. The corresponding
context-map entry routes this addendum and its focused loader tests.

This permits the exact helper to be included in a separately reviewed read-only
acquisition packet. It does not qualify the target, rewrite either failed probe,
or approve Project provisioning, an Attempt, submission or science. Final Q2
binds the observed closure, retained raw evidence and loading review, plus the
new exact wrapper/probe source hashes. Q1 remains unchanged.

## Accepted historical database opening delta

The parent delegate accepted the native existing-only read-only opening delta on
2026-09-16. The expanded [source addendum](crest-readonly-source-addendum.md)
SHA256 `503338ecdee4c2858a3416c6b661a40b5ed9a33e8e038d25630627220a641aa1` supersedes its earlier hash above only for
this additional pre-connection protection. The original proof contract remains
unchanged. Core and Transport use private native factories; public writes, DDL
and publisher/loader source bytes retain their existing semantics. The focused
hot-journal, zero-write and failure-exit checks and independent review bind the
new candidate, without relabelling old target observations as new runs.
