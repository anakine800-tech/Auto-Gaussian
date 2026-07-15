# Auto-G16 TS Precedent Map Contract

Status: smallest coherent offline implementation of `gaussian-ts-precedent-map/1`.
It records reviewed precedent translations; it does not construct a seed
geometry, validate a mechanism or TS, select a protocol, create Gaussian input,
or authorize live work.

## Immutable parents

The builder consumes four exact parent records:

1. an independently valid `gaussian-reaction-mechanism-network/1`;
2. a reviewed `auto-g16-knowledge-snapshot/1` whose exact parent is the same
   reaction intake;
3. finalized `gaussian-reaction-literature-evidence/1` with exact, non-null
   reaction-intake, species-registry, condition-model and knowledge-snapshot
   bindings; and
4. a human-authored `gaussian-ts-precedent-map-review/1` bound to the three
   direct scientific-parent payload hashes.

The output separately records the file SHA-256, byte size and payload SHA-256
of the W1 chain, mechanism network, knowledge snapshot and literature evidence,
plus the exact review-source file. Validation resolves every parent again,
validates its owning contract, and rebuilds the normalized records from the
immutable review. Rehashing an edited output cannot replace that review.

## Review records

Every record names one mechanism edge and the edge's exact from/to state IDs,
stereochemical channel, atom map, forming/breaking pairs and transfers. The
builder accepts no invented atom or changed atom correspondence. Eligibility
and channel review are explicit; an `accepted_for_candidate_construction`
disposition additionally requires an unblocked `reviewed_hypothesis` edge.

The source side binds one finalized literature candidate, source-located claim,
bounded use and all nine decomposed applicability dimensions. Relationships
remain `exact`, `close`, `remote` or `unusable`; rejected, blocked and negative
records remain in the map.

Any transferable geometry item requires reviewed source atom ordering and an
explicit one-to-one source/from-state/to-state correspondence consistent with
the edge atom map; every transferred target atom reference must occur in that
correspondence. Known source elements must be preserved. Target-context
formal charge and multiplicity must equal both reviewed endpoint states.
Geometry items separate `transferable` from `rebuild_required`. Quantitative
distance/angle/dihedral/contact items carry exactly one finite value or bounded
range; qualitative topology/facial/orientational/conformer items instead carry
an explicit descriptor and no numeric surrogate. Rebuild-required items carry
no descriptor, value, range or transferable unit. Every item retains stable
target atom references, exact provenance, applicability and limitations.
Approximate figure/topology evidence may contribute a qualitative descriptor
or a finite, increasing quantitative range; it never supplies a precise
coordinate or value.

Published coordinates are never copied into the map. Their use requires a
non-symlinked exact source object, coordinate-block anchor, and explicit
candidate/location provenance identical to the record's finalized literature
evidence, plus complete atom order and mapping and reviewed identity, order,
stereochemistry, charge, multiplicity and coordination audits. Figure/topology
structure provenance is likewise tied to its exact evidence candidate/location
but carries no coordinate object or anchor. Schematic figures cannot satisfy
the published-coordinate gate.

## Seed strategies and promotion

The closed strategy enum is:

- `published_coordinates`;
- `reviewed_structure_rebuild`;
- `endpoint_qst_family`;
- `relaxed_scan`;
- `hessian_guided_guess`; and
- `unsupported`.

Each locally accepted record must satisfy its strategy prerequisites, completed
applicability review, explicit uncertainties and alternatives, and an approved
promotion review. It must have no record blocker and its evidence bounded use
must be `geometry_seed_support` or `ts_topology_support`. Rejected, blocked and
unusable records retain explicit negative evidence. All prerequisite geometry
and endpoint IDs are checked against the target record, while source objects
and anchors are required as a pair. Published-coordinate and Hessian/endpoint
object references are hash bound; endpoint/QST records require both exact
endpoint state IDs and a reviewed exact endpoint-geometry package.
`unsupported` can never be locally accepted.

## Unintegrated mechanism-support stage

A standalone `gaussian-reaction-mechanism-support/1` sidecar is implemented,
but this version-1 TS-precedent contract does not bind or consume it. The map
does not reinterpret a reviewed mechanism-network hypothesis or independently
located support sidecar as accepted mechanism support. Every artifact therefore
retains its historical `mechanism_support_unavailable` blocker, sets
`candidate_construction_promotable: false`, and marks even a locally complete
accepted precedent as `blocked_pending_mechanism_support`. The serialized
`unavailable_unimplemented` status means that support integration is unavailable
in this contract version; it no longer means that no standalone support
artifact exists in the repository.

All outputs unconditionally retain `calculation_ready: false` and
`no_submission_authorization: true`. No field is a Gaussian route, method,
resource, server, job or submission approval.

## Commands

```bash
python3 skills/auto-g16-reaction-workflow/scripts/ts_precedent_map.py build \
  mechanism-network.json knowledge-snapshot.json literature-evidence.json \
  --review ts-precedent-review.json --output ts-precedent-map.json

python3 skills/auto-g16-reaction-workflow/scripts/ts_precedent_map.py validate \
  ts-precedent-map.json
```

Both commands are standard-library-only and offline. Output paths are never
overwritten.
