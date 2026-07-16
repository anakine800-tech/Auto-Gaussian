# Auto-G16 reaction orchestration and analysis contract

## Contents

1. Scope and authority
2. Candidate materialization
3. Finite calculation DAG
4. Derived study index
5. Normalized energy records
6. Thermochemistry, kinetics, and uncertainty
7. Bounded report
8. Validation and failure semantics

## 1. Scope and authority

`reaction_orchestrator.py` and `reaction_analysis.py` connect immutable
scientific decisions. They do not infer structures, mechanisms, methods,
resources, thermochemical conventions, or activity models. They use only local
files and never invoke Gaussian, SSH, PBS, deployment, cancellation, or cleanup.

Every artifact sets `calculation_ready: false` and
`no_submission_authorization: true`; orchestration and analysis artifacts also
set `execution_authorized: false`. These flags cannot be changed by a review.

## 2. Candidate materialization

`gaussian-reaction-candidate-materialization/1` binds one accepted
TS-precedent entry whose exact mechanism-support gate is
`candidate_construction_eligible`. Version 1 materializes only a frozen XYZ
source with:

- exact file SHA-256 and size;
- complete source atom order;
- a bijective, element-preserving source-to-target atom map;
- complete coverage of the reviewed source-state inventory;
- a reviewed mechanism edge and stereochemical channel; and
- no sub-0.3 Å contact.

`gaussian-reaction-state-candidate-materialization/1` similarly binds a
reviewed state. A `minimum_seed` requires a single-component state and reviewed
single-structure coordinates. A `complex_seed` requires a multi-component
state and explicit reviewed complex coordinates; it cannot be assembled by an
automatic packing guess. A single-atom minimum uses a null interatomic-distance
diagnostic because that check is not applicable. Both artifacts require later
visible review and remain unoptimized seeds. Both builders refuse
transition-metal atom inventories. Eligible `de_novo_seed_plans` remain visible
in the study index but require a separate future construction contract; this
builder does not reinterpret them as published-coordinate precedents.

## 3. Finite calculation DAG

`gaussian-reaction-calculation-dag/1` contains a reviewed finite set of nodes:

- minimum Opt/Freq, TS Opt/Freq, single-point, forward/reverse IRC, and endpoint
  Opt/Freq computation nodes; and
- thermochemistry, kinetics, and report analysis nodes.

Every node binds one network state, edge, or the study, plus optional candidate
and protocol-selection artifacts, dependencies, completion state, evidence,
and explicit review blockers. Dependency cycles are rejected. IRC/endpoint
nodes require a TS/Freq node for the same edge. Kinetics must depend on
thermochemistry.

Legacy Gaussian result JSON may be bound by exact full-file SHA-256, size, and
schema even when it predates the internal payload-hash convention. Payload-
aware artifacts retain the stronger payload binding. Neither evidence form can
grant calculation or submission authority.

Evidence whose schema belongs to the formal `calculation_artifacts.py` adapter
must also pass that adapter's public validator and deterministic reconstruction;
a locally rehashed imitation is refused. A validated target-import envelope is
still not a network-state/edge mapping, and this DAG version does not invent
that external-target binding. Until such a reviewed mapping exists, formal
adapter evidence may be retained only on a `not_started` node, creates an
explicit review blocker, and cannot establish completed, failed, or superseded
node state. A formal electronic-only energy lineage remains visible as blocked
thermochemistry evidence rather than a comparison energy.

Readiness is derived. A computation node cannot become
`ready_for_exact_input_review` without both candidate and protocol bindings;
terminal completion requires immutable evidence. TS mode acceptance and each
IRC direction remain separate scientific gates.

## 4. Derived study index

`gaussian-reaction-orchestration-index/1` binds exactly one mechanism-support artifact,
mechanism network, TS-precedent map, and calculation DAG, plus zero or more
candidate materializations. It derives gates, completed nodes, candidate
coverage, and next safe offline actions. No caller can set an editable project
status.

This is a legacy-compatible experimental view. It is not the authoritative
`gaussian-reaction-study-index/1` owned by `calculation_dag.py`, and it cannot
replace, mutate, update, or promote the authoritative calculation plan or
study index.

## 5. Normalized energy records

`gaussian-reaction-energy-record/1` uses reviewed JSON Pointers to extract from
one immutable source result:

- electronic energy and thermal Gibbs correction in hartree;
- temperature and standard state;
- optimization/termination status; and
- raw imaginary-frequency count.

It records separate standard-state and low-frequency corrections in kcal/mol,
their policy and comparison definition, conformer identity, degeneracy, energy
model, candidate, protocol, and DAG node. The normalized total is

`G = E_elec + G_thermal + (correction_standard + correction_low_frequency) / 627.5094740631`.

Do not double-count a correction already included in the extracted source
value; describe the exact comparison definition in the review.

A real minimum record is claim-eligible only when the exact source result is
evidence on a terminal DAG node with candidate and protocol bindings, normal
termination, successful optimization, and zero imaginary frequencies. A real
TS record additionally requires exactly one imaginary frequency and separate
hash-bound `gaussian-ts-mode-review/1` and accepted/confirmed
`gaussian-ts-mode-decision/1` files. Synthetic sources are always retained as
`scientific_claim_eligible: false`.

The formal adapter artifacts `gaussian-reviewed-energy-record/1` and
`gaussian-energy-lineage/1` are deliberately outside this normalization input:
their V1 contract omits thermal Gibbs, standard-state, low-frequency, and
common-reference definitions and fixes `comparison_eligible: false`. The
analysis builder validates a supplied formal lineage through its owning
adapter and then refuses promotion. It never treats an absent thermal
correction as zero.

## 6. Thermochemistry, kinetics, and uncertainty

`gaussian-reaction-analysis/1` rejects mixed temperature, standard state, or
energy-model records. For conformers with degeneracy `d_i`, it computes

`G_ensemble = G_min - RT ln Σ_i d_i exp[-(G_i - G_min)/RT]`.

State profiles use one explicit reference state. Each edge barrier uses the
TS ensemble minus its reviewed source-state ensemble. Eyring rates use

`k = (k_B T / h) exp(-ΔG‡/RT) × activity_product`.

The activity product is mandatory for every edge in a reviewed selectivity
group; no concentration or molecularity assumption is invented. Competing
edges in one selectivity group must share one source state. Their normalized
rates give channel fractions. A negative barrier is retained as a diagnostic
but receives no Eyring rate until the reference and kinetic model are reviewed.

Uncertainty scenarios apply explicit per-energy-record offsets in kcal/mol and
recompute ensembles, barriers, rates, and selectivities. The output reports the
range across baseline and all reviewed scenarios. This is sensitivity analysis,
not an automatic estimate of method error. A scenario that creates a negative
barrier or blocks a reviewed selectivity group becomes an analysis blocker; it
cannot be silently omitted from the claimed uncertainty envelope.

Claim ceilings are:

- `contract_fixture_only` when any source record is synthetic;
- `incomplete_hypothesis_only` when real evidence is not claim-eligible or the
  analysis still has coverage/model blockers; and
- `bounded_computational_comparison` only when all records and analysis gates
  pass.

No ceiling means `mechanism_proven`.

## 7. Bounded report

`gaussian-reaction-bounded-report/1` binds the study index, analysis, report
review, and deterministic Markdown file. It includes scope, state profile,
edge barriers/rates, selectivity, uncertainty, blockers, and explicit
non-claims. The Markdown hash is part of the artifact. Report validation
re-renders the content and rejects any textual or hash drift.

## 8. Validation and failure semantics

Each validator checks exact fields, parent file and payload identities, review
source identity, safety constants, and semantic invariants, then independently
rebuilds deterministic output where applicable. Builders refuse overwrite.

Retain rather than erase:

- missing candidate/protocol/evidence;
- unmaterialized accepted precedents;
- incomplete state or edge energy coverage;
- mixed or ambiguous thermochemical definitions;
- failed stationary-point or mode evidence;
- negative barriers and blocked selectivity groups; and
- synthetic or otherwise non-claim-eligible results.

Fix a source or review by creating a new immutable revision and rebuilding its
descendants. Never edit a derived status or recompute a payload hash to disguise
source drift.
