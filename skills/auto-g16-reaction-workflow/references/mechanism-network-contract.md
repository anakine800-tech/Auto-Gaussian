# Auto-G16 W3 Mechanism-Network Contract

Status: first offline implementation slice. This contract grants no Gaussian,
SSH, PBS, deployment, method-selection, calculation-DAG, or live authority.

## Inputs and immutable output

`gaussian-reaction-mechanism-network-review/1` binds the exact payload hashes
of `gaussian-reaction-intake/1`, `gaussian-reaction-species-registry/1`, and
`gaussian-reaction-condition-model/1`. Its exact top-level fields are:

- `schema`, `study_id`, and the three upstream payload hashes;
- `states`, `edges`, `networks`, and `reference_basins`; and
- `review_decision` and `review_notes`.

The builder emits `gaussian-reaction-mechanism-network/1`, binds the exact
upstream files and review source, canonicalizes every ID-keyed collection,
computes diagnostics and blockers, hashes the payload, and refuses overwrite.
The output always has `calculation_ready: false` and
`no_submission_authorization: true`.

## Closed semantics

- A state supplies every atom and registry-atom provenance, a component
  partition, integer charge, positive multiplicity, complete covalent and
  coordination connectivity, stereochemistry review, condition-model binding,
  and an optional reviewed catalyst projection. Every referenced registry
  species must use `atom_scope: explicit_structure_atoms`; its formula must
  equal that explicit inventory, and each registry-bound component instance
  must cover the complete species atom set exactly once.
- An edge supplies a complete one-to-one, element-preserving atom map. The
  declared connection changes must exactly equal the mapped connectivity
  difference. Declared atom transfers must match one broken donor connection
  and one formed acceptor connection.
- Every edge receives independently recomputed element and charge conservation
  diagnostics. Nonconservation remains an explicit blocker.
- The review must retain at least one `primary` and one `competing` network.
- Each network supplies an ordered closure path. The builder composes its atom
  maps and requires the entry and regenerated catalyst projections, every
  connection incident to a projected catalyst atom, and reviewed descriptors
  to close exactly. A retained catalyst–ligand, catalyst–substrate or poisoning
  contact therefore prevents a false regeneration claim.
- Every edge belongs to exactly one reference basin. The validator checks that
  each compared source state has the reference state's element and charge
  inventory; it computes no energy and assumes no equilibration model.

The separately implemented `gaussian-reaction-mechanism-support/1` is a
downstream sidecar. This version-1 network still keeps
`mechanism_support: null`, forbids support claim IDs, and always emits
`mechanism_support_unavailable`; those fields truthfully describe the immutable
network at finalization time. A syntactically valid network therefore remains a
reviewed hypothesis with blockers, never a promoted or proven mechanism.

Later orchestrators must validate and consume the exact `(network, support)`
pair. Writing a support hash back into the network would invalidate the network
payload already bound by the sidecar and create a circular dependency. A new
evidence review creates a new support artifact with an explicit forward-only
supersession binding; a changed network requires a new support artifact. Old
networks and sidecars are never rewritten, and multiple sidecars without an
explicit supersession relation remain ambiguous.

The sidecar may expose only local `downstream_reviewable_edge_ids` derived from
reviewed cells and explicit row promotion. Those IDs do not alter this
network's blocker or gate status and do not prove a mechanism, create a TS map,
select a protocol, create a DAG/input, or authorize calculation. See
`mechanism-support-contract.md`.

Both builder and validator reject unknown fields, including nested contract
objects. The validator semantically validates every bound upstream artifact,
loads the immutable review source, verifies its exact upstream payload hashes,
rebuilds the normalized network from that review, and independently recomputes
diagnostics and blockers. A self-consistent edited output cannot replace its
review source by merely recomputing the payload hash.
