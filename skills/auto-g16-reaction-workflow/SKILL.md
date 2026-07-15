---
name: auto-g16-reaction-workflow
description: Build the offline, hash-bound foundation of a whole Gaussian reaction study from a reviewed ChemDraw reaction package. Use when Codex must scope a reaction-computation study, convert strict reaction transcription into a reaction intake, bind every drawn reactant/product to a reviewed species registry, map every condition to an explicit computational treatment or blocker, or report why a reaction is not ready for mechanism or calculation planning. This Skill does not infer mechanisms, choose methods, generate Gaussian inputs, or authorize live work.
---

# Auto-G16 Reaction Workflow

## Purpose

Create the first three immutable artifacts of a whole-reaction study:

1. `gaussian-reaction-intake/1`;
2. `gaussian-reaction-species-registry/1`; and
3. `gaussian-reaction-condition-model/1`.

Treat these as offline scientific review records. Keep every artifact
`calculation_ready: false` and `no_submission_authorization: true`. A reviewed
intake is not a mechanism, protocol, Gaussian input, batch approval, or live
calculation request.

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
`calculation_ready: false`, and grants no mechanism promotion, calculation DAG,
protocol, Gaussian input, or live authority.

### 5. Preserve the W2 knowledge and literature gates

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
retrieval, screening and source-evidence stages. This Skill now also owns a
small separate offline TS-precedent-map builder described below; mechanism
support remains unimplemented. This W1 builder still performs none of those
actions. Do not claim that a database was queried or updated, claim that a
search was performed without its immutable artifacts, infer a mechanism from a
citation, or transfer an unreviewed structure/geometry. A database match and
literature similarity do not prove the target mechanism or TS and grant no
calculation authorization.

### Optional reviewed TS-precedent map

Invoke this only after an immutable W1 chain, reviewed mechanism-network
artifact, reviewed knowledge snapshot, finalized literature evidence with all
four W1/knowledge bindings, and an explicit human-authored precedent review
exist. Read
[references/ts-precedent-map-contract.md](references/ts-precedent-map-contract.md),
then run:

```bash
PRECEDENT_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/ts_precedent_map.py"

python3 "$PRECEDENT_TOOL" build mechanism-network.json knowledge-snapshot.json \
  literature-evidence.json --review ts-precedent-review.json \
  --output ts-precedent-map.json
python3 "$PRECEDENT_TOOL" validate ts-precedent-map.json
```

This converts reviewed edges and evidence into immutable atom-correspondence,
geometry-transfer-scope and seed-strategy review records. It copies no
coordinates and constructs no geometry. Since
`gaussian-reaction-mechanism-support/1` is still unavailable, every output is
non-promotable even when a precedent's local promotion prerequisites are
complete.

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
  extraction, applicability review and TS-precedent design. The query and
  evidence stages are implemented by `auto-g16-reaction-literature`; the
  smallest offline TS-precedent-map slice is implemented here; mechanism
  support remains design-only.
- `references/ts-precedent-map-contract.md`: implemented immutable-parent,
  atom-correspondence, geometry-transfer, strategy and fail-closed promotion
  rules for `gaussian-ts-precedent-map/1`.
- `references/mechanism-network-contract.md`: implemented first W3 offline
  review/output semantics, fail-closed diagnostics and mandatory evidence
  blocker.
- `scripts/mechanism_network.py`: standard-library-only deterministic W3
  mechanism-network builder and validator; no calculation or live path.
- `scripts/ts_precedent_map.py`: standard-library-only deterministic TS
  precedent-map builder and validator; no coordinate or input construction.
- `contracts/reaction-workflow/` in the repository: Draft 2020-12 output
  schemas for intake, registry, condition-model, mechanism-network and TS-
  precedent-map artifacts.
