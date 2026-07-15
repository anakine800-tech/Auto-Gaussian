# Auto-G16 Reaction Literature Search and Evidence Protocol

## Contents

1. Intake contract
2. Search design
3. Source hierarchy and screening
4. Evidence extraction
5. Claim levels and handoff
6. API and copyright constraints
7. Mechanism-support and TS-precedent translation

## 1. Intake contract

Use schema `gaussian-reaction-literature-request/1`. The planner requires the
following shape; optional lists may be empty.

```json
{
  "schema": "gaussian-reaction-literature-request/1",
  "request_id": "stable-local-id",
  "scientific_question": "Which reported pathways and TS models are relevant?",
  "reaction": {
    "transformation_class": "reviewed transformation label",
    "components": [
      {"role": "substrate", "name": "reviewed name", "identifiers": {}}
    ],
    "catalyst_states": [],
    "bond_changes": [],
    "unresolved": []
  },
  "search_terms": {
    "exact_phrases": [],
    "catalyst_terms": [],
    "substrate_terms": [],
    "transformation_terms": [],
    "mechanism_terms": [],
    "exclusions": []
  },
  "mechanism_hypotheses": [
    {"hypothesis_id": "h1", "label": "unselected hypothesis", "keywords": []}
  ],
  "target_evidence": ["proposed_mechanism", "transition_state_model"],
  "known_citations": [{"doi": "10.xxxx/example", "role": "seed"}],
  "publication_years": {"from": 1990, "until": 2026},
  "review_status": "reviewed_for_search_only"
}
```

Add `upstream_artifacts` with `reaction_intake`, `species_registry`,
`condition_model`, and `knowledge_snapshot` bindings when the search belongs to
the W2 reaction workflow. Each non-null binding must carry `path`, exact file
`sha256`, versioned `schema`, and `payload_sha256`. Missing bindings do not stop
standalone discovery, but they block mechanism-support or TS-precedent promotion.

Allowed target-evidence values are `proposed_mechanism`, `alternative_pathway`,
`active_catalyst_state`, `elementary_step`, `transition_state_model`,
`computational_protocol`, `barrier_or_energy_profile`, `normal_mode`, `irc`,
`selectivity_model`, and `coordinates`.

Names and synonyms are identity assertions. Check them against the reviewed
reaction package. Do not generate synonyms from a structure unless that
identity work is separately reviewed. Put both abbreviations and expanded
names in the intake when each is genuinely used in the literature.

## 2. Search design

Use multiple lanes because no single query balances precision and recall:

1. **Exact system:** exact title fragments, named reaction, catalyst, and key
   substrate pair. This gives precision but often misses mechanistic papers.
2. **Catalyst plus transformation:** preserve the catalyst family while
   relaxing individual substrates.
3. **Substrate plus transformation:** find uncatalyzed or differently catalyzed
   analogies without treating them as direct precedents.
4. **Mechanism terms:** use only reviewed hypothesis labels and their explicit
   synonyms.
5. **TS/computational terms:** add transition state, computational, DFT,
   activation barrier, energy profile, or IRC as discovery words.
6. **Elementary-step analogy:** drop the target catalyst or substrate while
   preserving the reviewed bond-making, bond-breaking, insertion, transfer,
   elimination, or rearrangement class.
7. **Reviews:** use reviews for vocabulary, historical context, and seed
   citations, not for candidate-specific computational facts.
8. **Citation chaining:** inspect references and citing works from a verified
   seed. Record whether each candidate is backward, forward, author, or
   related-work discovery.

Run broad and narrow lanes. A zero-result exact query does not justify a zero-
precedent conclusion. Record database coverage, date, API failures, language
limits, access limits, and whether structure/substructure searching was absent.

## 3. Source hierarchy and screening

Use this evidence order:

1. primary article plus its version-matched supporting information;
2. correction, retraction, expression of concern, or version notice;
3. repository author manuscript or lawful open full text;
4. review article for terminology and citation discovery;
5. Crossref/OpenAlex metadata and search snippets for discovery only.

Resolve DOI variants and duplicates before review. Prefer DOI as the identity
key. Otherwise use normalized title and publication year and retain uncertainty.
Do not merge a preprint and version of record silently; record their relation.

Screen on relevance dimensions rather than one opaque score:

- same reaction components;
- same catalyst or credible catalyst-state family;
- same transformation and elementary step;
- same stereochemical question;
- actual computational or kinetic evidence; and
- accessible primary/SI evidence.

Citation count is affected by age and field. It may help discover influential
seeds but cannot establish correctness or direct relevance.

## 4. Evidence extraction

For every retained candidate record the bibliographic identity, access date,
article/SI version relation, and exact source location. Use short paraphrases.
If a brief exact quote is necessary, keep it within applicable copyright limits
and attach it to the locator.

### Mechanism

Separate author proposal, experimental support, computational comparison, and
reviewer inference. Record alternative pathways that were actually tested and
those merely mentioned. Do not equate the lowest reported structure in an
incomplete set with a validated mechanism.

### Active catalyst state

Record metal oxidation/spin hypotheses, ligand count, coordination, hapticity,
protonation, counterion, aggregation, boron coordination state, additives, and
substrate binding only when the source specifies them. Label precatalyst-to-
active-species transfer as unresolved unless supported.

### Computational protocol

Extract optimization/frequency and single-point methods separately. Record
basis/ECP by element, dispersion, solvent model and identity, explicit solvent,
SCF/spin treatment, temperature, standard state, low-frequency correction,
quasiharmonic treatment, and program/version. `not_found` is evidence about
reporting completeness, not permission to choose a value.

### Transition-state and path evidence

Record each TS label, modeled elementary step, atom inventory, charge,
multiplicity, truncation, conformation, binding mode, reported imaginary
frequency, and whether the source interprets the corresponding normal mode.
Record IRC direction and structurally identified endpoint separately. Statements
such as “IRC calculations were performed” do not establish candidate-specific,
bidirectional endpoint identity.

### Energies and selectivity

Record electronic energy, enthalpy, Gibbs energy, reference state, balanced
cycle, standard state, temperature, degeneracy, and ensemble coverage. Do not
compare barriers that lack a common reference. Distinguish lowest-TS-only,
Boltzmann TS ensemble, Curtin-Hammett, microkinetic, and qualitative models.

## 5. Claim levels and handoff

- `metadata_candidate`: found in a discovery source; no scientific claim.
- `source_checked_background`: primary or review source checked but only
  background relevance established.
- `source_reports_analogy`: source-located evidence for an explicitly different
  catalyst, substrate, elementary step, or stereochemical problem.
- `source_reports_direct_precedent`: source-located evidence matches all stated
  directness dimensions. This is still a report about the publication.
- `local_reproduction_candidate`: exact reported structure/protocol evidence is
  sufficiently complete to propose a separate benchmark review. It does not
  approve a method or calculation.

Never emit `validated_mechanism`, `validated_ts`, or `calculation_ready` from
literature retrieval. Local TS claims still require exactly one raw imaginary
frequency, explicit normal-mode review, and, for path validation, two completed
directions with structurally identified endpoints under the owning Skills.

Failure to find a direct precedent in a bounded search is an evidence gap, not
an automatic prohibition on exploring a reviewed novel organic mechanism. The
downstream mechanism-support artifact must keep that gap separate from analogy,
internal rationale, contradiction, and later experimental or computational
evidence. It may approve bounded hypothesis exploration independently, but
literature analogy or absence of contradiction never validates the mechanism
claim.

## 6. API and copyright constraints

Crossref exposes deposited bibliographic metadata through a public REST API.
Use the `/works` endpoint, small result sets, caching, backoff, a descriptive
user agent, and a contact email for the polite pool. Some deposited abstracts
may remain copyrighted.

OpenAlex basic work search covers titles, abstracts, and indexed full text. Its
API has usage budgets and optional API keys; record failures and truncated
coverage. Do not store or print the key. Do not use the content-download API in
this Skill.

Current provider documentation:

- Crossref REST API: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>
- OpenAlex search: <https://developers.openalex.org/guides/searching>
- OpenAlex authentication and budgets:
  <https://developers.openalex.org/guides/authentication>

API results may be incomplete, stale, duplicated, or wrongly linked. Always
open the DOI/publisher record and version-matched SI before accepting a
candidate-specific claim. Never bypass authentication, robots rules, or
publisher access controls.

## 7. Mechanism-support and TS-precedent translation

Hand a finalized `gaussian-reaction-literature-evidence/1` artifact to the
separate `mechanism_support.py` and `ts_precedent_map.py` tools owned by
`auto-g16-reaction-workflow`. This literature Skill does not run those
translations or make their promotion decisions. Both tools require exact
hash-bound W1, knowledge-snapshot, and mechanism-network parents.

The mechanism-support review must bind each source claim by deterministic
candidate/claim/location identities and canonical payload hashes. Every
reviewed mechanism edge and stereochemical channel requires an explicit
record, including exact atom correspondence, all applicability dimensions,
alternatives, falsifiers, contradictions, and two separate decisions:
`hypothesis_exploration_eligible` and `mechanism_claim_supported`. A changed
claim, location, edge, channel, or cross-target substitution fails validation.

The TS-precedent review must bind each record to a network edge and its reviewed
stereochemical channel. Forming/breaking/transferring atom sets must match the
edge. Coordinate-based entries require a frozen XYZ hash, explicit source atom
order, complete bijective source-to-target atom map, element agreement, and
reviewed provenance. Missing coordinates may support topology but cannot be
materialized as published-coordinate seeds.

The TS map may open candidate construction for a locally complete accepted
precedent or de novo plan only when its exact edge/channel is explicitly
exploration-eligible. Missing precedent may justify a clearly source-free de
novo plan but never mechanism-claim support. Both output validators reload
parents and review sources and independently rebuild their artifacts. Neither
artifact proves a mechanism, selects a computational protocol, creates a
Gaussian input, validates a local TS, or authorizes a calculation.
