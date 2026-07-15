---
name: auto-g16-reaction-workflow
description: Build and validate the offline, hash-bound foundation of a whole Gaussian reaction study from reviewed human inputs. Use when Codex must create W1 reaction-intake artifacts, validate an explicit W3 mechanism network, build a non-executable calculation DAG, derive a read-only study resume index, or report why later work remains blocked. This Skill does not infer chemistry or mechanisms, choose methods, construct geometry, generate Gaussian inputs, or authorize live work.
---

# Auto-G16 Reaction Workflow

## Purpose

Create the first three immutable W1 artifacts of a whole-reaction study:

1. `gaussian-reaction-intake/1`;
2. `gaussian-reaction-species-registry/1`; and
3. `gaussian-reaction-condition-model/1`.

After separate human review, the optional W3 stages may also create:

4. `gaussian-reaction-mechanism-network/1`;
5. `gaussian-reaction-calculation-plan/1`; and
6. `gaussian-reaction-study-index/1`.

Treat every artifact as an offline scientific review or bookkeeping record.
Keep `calculation_ready: false` and `no_submission_authorization: true`
throughout this Skill, and keep every calculation-plan node
`executable: false`. A reviewed intake, network or plan is not a selected
protocol, Gaussian input, batch approval, job, accepted calculation result or
live calculation request.

## Required upstream package

Use `auto-g16-chemdraw-structures` in Strict mode for a reaction drawing containing
reactants, products, arrows, conditions, quantities, catalysts, ligands,
additives, workup, or selectivity. Require its source-exact and normalized
reaction transcription. Do not use a Quick draft as reviewed intake.

The current adapter consumes `normalized_scheme.json` from
`create_reaction_scheme_package.py`. Preserve the original ChemDraw/CDXML/CDX
or source image as a separately hashed source file.

Read [references/intake-contract.md](references/intake-contract.md) before
creating review inputs.

## Workflow

### 1. Scope and build the intake

Prepare `gaussian-reaction-intake-request/1` with the source files, target
question, claim ceiling, explicit non-goals, unresolved transcription and a
review decision. Then run:

```bash
TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/reaction_workflow.py"

python3 "$TOOL" build-intake intake-request.json \
  --scheme normalized_scheme.json --output reaction-intake.json
```

The builder assigns stable step, occurrence and condition IDs, preserves
source-exact values, hashes every source, records blockers and refuses output
overwrite. It does not resolve a label into a molecular identity.

### 2. Build the species registry

Create a separate `gaussian-reaction-species-review/1` bound to the exact
intake payload hash. Give every chemical identity a stable `species_id` and
record its represented form, source occurrences, structure hash, formula,
charge, multiplicity, component count, stereochemistry, protonation,
salt/solvate status and stable atom IDs.

Bind every drawn reactant and product occurrence exactly once. Represent
unshown balance species explicitly; never repair an imbalance by changing a
drawn structure.

```bash
python3 "$TOOL" build-registry reaction-intake.json \
  --review species-review.json --output species-registry.json
```

The builder rejects missing or duplicate occurrence bindings, changed intake
hashes, unknown source/species IDs, symlinked structures and unreviewed required
species. It records unresolved identity, charge, multiplicity, stereochemistry,
protonation, salt/solvate, atom identity or balance as blockers.

### 3. Build the condition model

Create `gaussian-reaction-condition-review/1` bound to both preceding payload
hashes. Give every transcribed condition item exactly one reviewed treatment:

- `explicit_component`;
- `continuum_environment`;
- `chemical_potential`;
- `computational_parameter`;
- `experimental_context_only`;
- `excluded_spectator`;
- `workup_only`; or
- `unresolved`.

Also review standard state, temperature, concentration, pressure and explicit-
component policies. A solvent name does not select a continuum model; a
catalyst or additive does not become a spectator automatically.

```bash
python3 "$TOOL" build-condition-model reaction-intake.json \
  species-registry.json --review condition-review.json \
  --output condition-model.json
```

The builder refuses missing/duplicate decisions, unknown species references,
changed upstream hashes and non-finite values. Unresolved decisions remain
visible blockers.

### 4. Validate and stop at the W1 boundary

```bash
python3 "$TOOL" validate reaction-intake.json
python3 "$TOOL" validate species-registry.json
python3 "$TOOL" validate condition-model.json
```

Report each gate as `reviewed`, `reviewed_with_blockers`, or `blocked`, together
with the blocker list and the next safe offline action.

Stop after the condition model. W1 does not create active-catalyst hypotheses,
mechanism networks, atom correspondence between states, reference basins,
candidate structures, protocols, Gaussian inputs, server projects, jobs,
retries, cancellations or reports of mechanism/selectivity.

### Optional W3 mechanism-network slice

Invoke this only as a separate offline stage after an immutable W1 chain and
an explicit human-authored network review exist. Read
[references/mechanism-network-contract.md](references/mechanism-network-contract.md),
then run:

```bash
NETWORK_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_network.py"

python3 "$NETWORK_TOOL" build reaction-intake.json species-registry.json \
  condition-model.json --review mechanism-network-review.json \
  --output mechanism-network.json
python3 "$NETWORK_TOOL" validate mechanism-network.json
```

This first W3 slice validates complete reviewed states, exact atom maps,
connectivity changes, element/charge conservation, competing networks,
reference basins and catalyst-projection closure. It does not infer any of
them. Because `gaussian-reaction-mechanism-support/1` remains unimplemented,
every output retains `mechanism_support_unavailable`, remains
`calculation_ready: false`, and grants no mechanism promotion, node execution,
protocol, Gaussian input, or live authority. The later calculation-plan stage
may preserve this exact network and its blocker as planning input; doing so
does not promote the network or make any node executable.

### 5. Build the offline calculation plan and study index

Invoke this only after the exact W1 chain, finalized mechanism network and an
explicit human-authored calculation-plan review exist. Read
[references/calculation-dag-contract.md](references/calculation-dag-contract.md)
before using the builder. Finalization hashes the reviewed draft without
changing its scientific decisions:

```bash
DAG_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/calculation_dag.py"

python3 "$DAG_TOOL" finalize-review calculation-plan-review.draft.json \
  --output calculation-plan-review.json
```

Build and validate the non-executable plan:

```bash
python3 "$DAG_TOOL" build-plan reaction-intake.json species-registry.json \
  condition-model.json mechanism-network.json \
  --review calculation-plan-review.json \
  --output calculation-plan.json
python3 "$DAG_TOOL" validate-plan calculation-plan.json
```

Every required artifact binding records its relative path, file SHA-256, byte
size, schema and canonical payload SHA-256. The builder and validators use
strict JSON, refuse symlinks, hash drift, unknown fields, graph forgery and
output overwrite, require a pre-existing real output parent, reject divergent
W1/W3 revision chains, and independently recompute graph order, target-
continuous dependencies, readiness, blockers, supersession and coverage.

When implemented exact `gaussian-reaction-mechanism-support/1` or
`gaussian-ts-precedent-map/1` artifacts exist, bind them with
`--mechanism-support FILE` or `--ts-precedent-map FILE`. On the current
baseline they are absent, so the builder records explicit blockers. If such a
file is supplied before its specialist-owned schema and semantic validator are
integrated, it is exact-bound only as `bound_unvalidated` provenance and still
cannot clear any readiness gate. Use repeated `--supersedes-plan FILE`
bindings only for exact immutable earlier plans explicitly superseded by the
review; never rewrite an older plan.

The plan supports explicit logical needs for minima, conformers, complexes,
TS candidates, TS/Freq, forward and reverse IRC, endpoints, single points,
thermochemistry and sensitivity. It validates stable node IDs, dependencies,
alternatives, supersession and stage order while retaining failed, rejected,
skipped and historical work. Every target state, edge, network, reference basin
and atom reference must exist in the finalized mechanism network. Stages that
need an exact charge, multiplicity or atom order remain scientifically blocked
when the reviewed plan omits one. Scientific, input-review and live-approval
readiness are independent from execution state and evidence acceptance.
State-targeted single points require minimum/endpoint lineage; edge-targeted
single points require TS/Freq lineage, and every edge-targeted node directly
retains the TS-precedent blocker. Superseded-plan ancestry deeper than 128
artifacts is refused with a controlled offline contract error.

Build the immutable read-only resume view only from an exact validated plan:

```bash
python3 "$DAG_TOOL" build-index calculation-plan.json \
  --output reaction-study-index.json
python3 "$DAG_TOOL" validate-index reaction-study-index.json
```

The index derives stage gates, the last accepted stage, next blockers,
superseded artifacts and active/historical coverage. It does not mutate the
plan or any specialist artifact. This slice implements no external node-update
envelope; such an envelope is a future adapter boundary and could not itself
grant submission or evidence-acceptance authority.
Its gate order is W1, finalized mechanism network, exact network support,
dependent TS precedent, calculation plan, input review, then live approval;
each emitted stage blocker resolves to the plan's normalized blocker record.

### 6. Preserve the W2 knowledge and literature gates

The second scientific-modeling round must first query a reviewed reusable
knowledge layer and bind an immutable per-study snapshot. Read
[references/knowledge-database-design.md](references/knowledge-database-design.md)
when binding the implemented offline structure, method, and literature/book
registries.

Then obtain reproducible literature evidence before promoting mechanism
networks or TS seed strategies. Read
[references/literature-evidence-design.md](references/literature-evidence-design.md)
when planning that future layer.

The separate `auto-g16-knowledge-base` Skill implements the offline immutable
registry, permission-filtered index, typed-link and snapshot MVP. This W1
builder does not invoke it automatically or fabricate a snapshot. The separate
`auto-g16-reaction-literature` Skill implements the query, metadata
retrieval, screening and source-evidence stages, but not the planned mechanism-
support or TS-precedent-map stages. This W1 builder still performs none of those
actions. Do not claim that a database was queried or updated, claim that a
search was performed without its immutable artifacts, infer a mechanism from a
citation, or transfer an unreviewed structure/geometry. A database match and
literature similarity do not prove the target mechanism or TS and grant no
calculation authorization.

## Scientific boundaries

- Preserve source-exact values beside normalized values. Never turn `rt`,
  `overnight`, `trace`, unreadable quantities or an omitted species into an
  invented number or identity.
- Distinguish one chemical identity from its conformers and coordination,
  association, ion-pair, protonation, oxidation and solvation states.
- Do not infer an active catalyst from a precatalyst drawing.
- Do not call a synthetic equation element/charge balanced when workup,
  counterions, bases, gases or byproducts remain unrepresented.
- Do not infer a functional, basis/ECP, solvent model, temperature correction,
  standard state, mechanism, TS algorithm or resource tier.
- Do not treat scientific readiness, input review, live approval, execution or
  evidence acceptance as interchangeable states.
- Keep transition-metal, open-shell, broken-symmetry, multireference and
  ambiguous coordination cases blocked for later specialist review.

## Bundled resources

- `scripts/reaction_workflow.py`: standard-library-only deterministic W1
  builders and validator.
- `references/intake-contract.md`: required review-input fields, semantics and
  blocker rules.
- `references/knowledge-database-design.md`: W2 structure, method, and
  literature/book registry, immutable snapshot, permission and storage/index
  contract implemented offline by `auto-g16-knowledge-base`; multi-user service
  and raw legacy migrations remain future work.
- `references/literature-evidence-design.md`: W2 reproducible search, evidence
  extraction, applicability review and TS-precedent contract. The query and
  evidence stages are implemented by `auto-g16-reaction-literature`; later
  mechanism-support and TS-precedent stages remain design-only.
- `references/mechanism-network-contract.md`: implemented first W3 offline
  review/output semantics, fail-closed diagnostics and mandatory evidence
  blocker.
- `scripts/mechanism_network.py`: standard-library-only deterministic W3
  mechanism-network builder and validator; no calculation or live path.
- `references/calculation-dag-contract.md`: implemented offline calculation-
  plan and study-index semantics, dependency/readiness rules, immutable
  bindings, supersession and specialist ownership boundaries.
- `scripts/calculation_dag.py`: standard-library-only deterministic review
  finalizer, calculation-plan builder/validator and study-index
  builder/validator; no input rendering, execution or live path.
- `contracts/reaction-workflow/` in the repository: Draft 2020-12 output
  schemas for intake, registry, condition-model, mechanism-network,
  calculation-plan and study-index artifacts.
