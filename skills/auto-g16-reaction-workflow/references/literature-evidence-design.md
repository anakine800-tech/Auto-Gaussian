# Literature Evidence and Transition-State Precedent Design

Status: W2 design plus implemented mechanism-support and TS-precedent/de novo
planning slices.
`auto-g16-reaction-literature` implements query, metadata retrieval, screening,
and editable/finalized evidence-record stages. `auto-g16-reaction-workflow`
implements strict offline `gaussian-reaction-mechanism-support/1` and
`gaussian-ts-precedent-map/1` slices. Automated full-text extraction and
seed-geometry construction remain unimplemented.

Every artifact described here must retain:

- `calculation_ready: false`; and
- `no_submission_authorization: true`.

Literature similarity does not prove the current mechanism, validate a
transition state, select a computational method, or authorize Gaussian work.

## Contents

1. Purpose and boundary
2. Planned artifact chain
3. Search strategy
4. Source and evidence requirements
5. Computational-detail extraction
6. Applicability assessment
7. Mechanism support
8. Transition-state precedent map
9. Human review gates
10. Failure and uncertainty semantics
11. Future implementation acceptance

## 1. Purpose and boundary

Transition-state initial guesses are scientific models, not generic 3D
embeddings. The future literature layer should find and understand primary
sources that can support:

- active-catalyst and resting-state hypotheses;
- plausible elementary-step classes and competing mechanisms;
- forming, breaking, and transferring atom pairs;
- coordination, ion-pair, additive, and stereochemical approach models;
- published TS geometries or geometry constraints; and
- candidate methods and validation practices used for related chemistry.

The layer is evidence acquisition and translation. It must stop before
mechanism promotion, geometry generation, method selection, Gaussian input
rendering, or live execution.

## 2. Planned artifact chain

The four-artifact design is split across owning Skills. The literature Skill
emits the first two; reaction workflow emits the third and fourth as separate
offline review stages:

| Artifact | Required role |
| --- | --- |
| `gaussian-reaction-literature-query/1` | records the decomposed scientific question, search ladder, databases, exact queries, dates, filters, and coverage limits |
| `gaussian-reaction-literature-evidence/1` | records primary sources, exact source locations, extracted claims, computational details, structures, contradictory evidence, and extraction confidence |
| `gaussian-reaction-mechanism-support/1` | implemented edge/channel classification with exact claim/location bindings and separate hypothesis-exploration and mechanism-claim-support decisions |
| `gaussian-ts-precedent-map/1` | implemented offline translation of reviewed edges/evidence plus clearly labeled de novo planning for exploration-eligible novel hypotheses |

Each child artifact must bind the exact payload hashes of the reaction intake,
species registry, condition model, applicable
`auto-g16-knowledge-snapshot/1`, and its direct literature parent. Search the
reviewed literature/book registry before external discovery. Later mechanism-
network or TS-candidate artifacts may reference accepted evidence; they must
not copy an unsupported conclusion into a stronger evidence state. New sources
or extracted claims may enter `auto-g16-knowledge-base` only through its
separate identity, anchor, applicability, permission, and revision review.

## 3. Search strategy

### 3.1 Query decomposition

Build the search specification from reviewed fields rather than one natural-
language sentence:

- net transformation and named reaction, when known;
- proposed elementary-step class;
- forming, breaking, and transferring atom types or mapped atoms;
- substrate and functional-group motifs;
- catalyst, ligand, precatalyst, and plausible active-state families;
- oxidation, charge, spin, coordination, and aggregation hypotheses;
- solvent, counterion, additive, base/acid, atmosphere, and temperature;
- regio-, diastereo-, and enantioselective channels;
- experimental-mechanism terms such as kinetics, isotope effects, labeling,
  poisoning, trapping, and intermediate observation; and
- computational terms such as DFT, mechanism, transition state, IRC,
  coordinates, supporting information, and potential-energy surface.

Unresolved reaction-intake fields must remain explicit query branches or
blockers. The search tool must not silently choose an active catalyst or named
mechanism to make the query easier.

### 3.2 Search ladder

Search and report coverage in this order:

1. exact transformation with the exact catalyst or catalyst family;
2. close substrate transformation with the same catalyst family;
3. the same elementary step with a closely related catalyst or active state;
4. a broader computational or structural precedent for the intended TS class;
5. experimental mechanistic studies that constrain the computed hypothesis;
6. reviews used only to discover terminology and primary sources; and
7. contradictory, alternative-mechanism, failed-computation, correction, or
   retraction evidence.

Absence of an exact precedent is a result and must not be hidden by presenting
a remote analogy as an exact match.

### 3.3 Reproducibility

Record database or search provider, exact query string, query date, filters,
result identifiers, deduplication decisions, inclusion/exclusion rationale,
language limits, access limits, and the last result page reviewed. A later
search run creates a new artifact; it does not overwrite the old search.

## 4. Source and evidence requirements

Prefer evidence in this order:

1. primary article and its supporting information;
2. correction, retraction, data repository, or author-supplied coordinates;
3. dissertation, preprint, or repository copy when it contains otherwise
   unavailable computational detail; and
4. review or database summary for discovery only.

For every retained source, record DOI or stable identifier, complete
bibliographic identity, source URL or repository identifier, version, access
date, source-file SHA-256 when legally retained, and exact page, section,
scheme, figure, table, or supporting-information anchors.

Separate verbatim source statements from reviewer interpretation. Respect
publisher access and copyright constraints; store structured facts, citations,
short necessary excerpts, and hashes rather than redistributing full texts.

Claims without a primary-source location remain `unverified_secondary` and
cannot support a TS seed promotion.

## 5. Computational-detail extraction

Extract, when reported:

- program and revision;
- geometry, frequency, single-point, and composite-energy levels;
- functional, basis set by element, ECP, dispersion, and solvation model;
- integration grid, SCF, optimization, relativistic, and wavefunction policy;
- charge, multiplicity, oxidation state, spin state, and broken-symmetry use;
- temperature, pressure, standard state, concentration correction,
  low-frequency treatment, entropy treatment, and quasi-harmonic policy;
- conformer, catalyst-state, ion-pair, explicit-solvent, and additive coverage;
- TS search route, initial-guess source, QST/scan/path settings, constraints,
  and Hessian use;
- raw imaginary frequency, normal-mode assignment, IRC or endpoint evidence;
- relative electronic, enthalpic, and free energies with their reference zero;
- atom ordering, Cartesian coordinates, key bond distances/angles/dihedrals,
  coordination contacts, and figure-view limitations; and
- failed searches, alternative saddles, or sensitivity calculations.

Mark every field as `reported`, `derived`, `ambiguous`, `not_reported`, or
`not_applicable`. Do not fill a missing method or geometry field from common
practice.

## 6. Applicability assessment

Do not collapse relevance into one opaque similarity score. Compare the target
and precedent explicitly across:

- net transformation;
- elementary-step class and atom correspondence;
- substrate electronics, sterics, and functional groups;
- catalyst identity, ligand environment, and active-state hypothesis;
- atom inventory, association state, charge, multiplicity, and spin surface;
- coordination, ion pairing, explicit additives, and solvent participation;
- stereochemical approach and product channel;
- experimental conditions; and
- computational protocol and validation evidence.

For each dimension record `exact`, `close`, `remote`, `contradictory`,
`unknown`, or `not_applicable`, with a rationale and source anchor. A reviewer
then assigns the bounded use: `discovery_only`, `mechanism_support`,
`ts_topology_support`, `geometry_seed_support`, `protocol_candidate_support`,
or `not_applicable_to_target`.

## 7. Mechanism support

The implemented mechanism-support artifact makes a matrix whose rows are proposed
active states or elementary edges and whose columns are evidence records. For
each intersection record:

- the exact claim supported or contradicted;
- direct versus analogous evidence;
- experimental versus computational evidence;
- applicability dimensions and important mismatches;
- alternative explanations;
- confidence and reviewer decision; and
- whether the hypothesis remains mandatory, optional, contradicted, or
  unresolved in the planned network.

The artifact proposes a bounded hypothesis space. It does not establish which
mechanism operates in the target reaction. In organic methodology, absence of
a direct precedent is expected for some genuinely new hypotheses and is
recorded as `novel_hypothesis_no_direct_precedent`, not treated automatically
as exclusion.

Two gates remain independent. `hypothesis_exploration_eligible` may be true
when atom/charge/state bookkeeping, elementary-step definition, active-state
assumptions, stereochemical channel, alternatives, uncertainty,
contradictions, falsifiers and reviewer approval are complete. Known unresolved
contradictions or scientific defects can still block exploration.
`mechanism_claim_supported` requires reviewed direct evidence and never follows
from analogy or internal rationale. `mechanism_claim_validated` remains false
through this layer.

## 8. Transition-state precedent map

The offline implementation is normative in `ts-precedent-map-contract.md`. It
requires exact W1, knowledge, literature, mechanism-network and mechanism-
support bindings and independently recomputes every record. Candidate
construction requires the exact edge/channel exploration gate.

For every proposed mechanism edge and stereochemical channel, record:

- target state IDs and stable atom IDs;
- forming, breaking, and transferring atom pairs;
- catalyst state, coordination, ion-pair/additive placement, charge, and spin;
- approach topology, facial/orientational relationship, and conformer family;
- precedent source and exact structure/figure/coordinate anchor;
- available atom ordering and a reviewed source-to-target atom correspondence;
- reported key distances, angles, dihedrals, or coordination contacts;
- proposed seed route: published coordinates, reviewed structure rebuild,
  endpoint/QST family, relaxed scan, Hessian-guided guess, or unsupported;
- information that may be transferred and information that must be rebuilt;
- uncertainty, conflicting precedents, and missing alternatives; and
- reviewer disposition: `proposed`, `accepted_for_candidate_construction`,
  `rejected`, or `blocked`.

Published coordinates may be reused only after identity, atom-order,
stereochemistry, charge, multiplicity, coordination, and source-hash audit.
The source-structure coordinate provenance and each transferred geometry item
must name the same finalized literature candidate and source location; a
coordinate object additionally requires its exact file hash and coordinate
block anchor. Figure/topology provenance carries no coordinate object or
anchor.
Coordinates unavailable from the source must not be fabricated by reading
precise 3D positions from a schematic figure. A figure may support topology
and approximate relationships only, with that limitation recorded. Numeric
geometry is represented by a finite value or bounded range, whereas topology,
facial/orientational relationships, and conformer families use explicit
qualitative descriptors rather than invented numbers. Target-context charge
and multiplicity are checked against both mechanism-edge endpoints.

An exploration-eligible novel edge may instead carry a separate de novo
endpoint/QST, relaxed-scan or reviewed-rebuild plan. That record has no source
precedent and uses no source coordinates. It opens only the next offline
candidate-construction stage and does not make the mechanism literature-
supported or validated.

## 9. Human review gates

Four distinct approvals are required:

1. search-scope review: query decomposition and coverage limits are adequate;
2. evidence-extraction review: the source anchors and extracted facts are
   accurate;
3. applicability review: similarities and mismatches justify the bounded use;
4. promotion review: one mechanism hypothesis or TS seed strategy may enter
   the next offline construction stage.

None of these approvals selects a Gaussian protocol or authorizes a job. Exact
structure, method, resources, server directory, rendered input hash, and live
scope retain their later independent gates.

## 10. Failure and uncertainty semantics

Retain and distinguish:

- `no_exact_precedent_found`;
- `search_access_incomplete`;
- `primary_source_unavailable`;
- `supporting_information_missing`;
- `computational_details_incomplete`;
- `coordinates_unavailable`;
- `atom_mapping_ambiguous`;
- `analogy_too_remote`;
- `contradictory_evidence`;
- `reported_ts_not_path_validated`;
- `reported_method_not_transferable`; and
- `candidate_construction_blocked`.

A failed or negative precedent is evidence and remains in the ledger. The tool
must not rank it out of view merely because it does not yield a usable seed.

## 11. Implementation acceptance and remaining work

The implemented mechanism-support slice has offline tests for direct,
analogous, unsupported, contradictory and missing evidence; exact edge/channel
and claim/location binding; novel-hypothesis exploration without direct
precedent; bounded-use misuse; immutable drift/forgery; closed schemas; and
unconditional safety constants.

The implemented TS-precedent slice has offline tests for exact, close, remote
and unusable analogies; stable atom/ref and source-to-target mapping failures;
coordinate provenance and approximate-range refusal; all six strategy states;
immutable binding drift/forgery; overwrite refusal; deterministic output; and
unconditional safety constants.

Remaining work includes:

- correction/retraction and version links across the full evidence chain;
- any future lawful automated full-text extraction with reported/derived/
  interpretation separation and preserved access limits;
- regression evidence that later candidate construction still cannot create a
  geometry, select a protocol, or authorize calculation without its own gates.

Only after those offline gates pass should a separately approved real-reaction
search smoke be proposed. A literature search smoke is not a Gaussian live
smoke and authorizes no calculation.
