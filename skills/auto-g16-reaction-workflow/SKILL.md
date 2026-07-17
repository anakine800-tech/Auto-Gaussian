---
name: auto-g16-reaction-workflow
description: Build and validate the offline, hash-bound foundation of a whole Gaussian reaction study from reviewed human inputs, including W1 intake, explicit W3 mechanism records, a non-executable calculation DAG and read-only study index, plus narrow immutable calculation-artifact handoffs from exact reviewed candidate, protocol, input-draft and specialist-result artifacts. Use when Codex must build or validate those offline records, export external candidate targets, reproduce an explicitly reviewed closed-shell main-group input, or project blocked/electronic-only energy lineage. This Skill never infers chemistry, mechanisms or methods and never authorizes live work.
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

Before any prospective formal TS input family, create the separate immutable
scientific-maturity overlay described in
[references/scientific-maturity-contract.md](references/scientific-maturity-contract.md).
It binds the exact calculation plan without rewriting it and projects minima-
first blockers onto its DAG nodes.
For owner-evidence enforcement, layer the separate compatibility-preserving `/2`
contract in
[references/scientific-maturity-owner-evidence-v2-contract.md](references/scientific-maturity-owner-evidence-v2-contract.md)
over one exact validated gate `/1`.

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

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" build-intake intake-request.json \
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
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" build-registry reaction-intake.json \
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
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" build-condition-model reaction-intake.json \
  species-registry.json --review condition-review.json \
  --output condition-model.json
```

The builder refuses missing/duplicate decisions, unknown species references,
changed upstream hashes and non-finite values. Unresolved decisions remain
visible blockers.

### 4. Validate and stop at the W1 boundary

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" validate reaction-intake.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" validate species-registry.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$TOOL" validate condition-model.json
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

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$NETWORK_TOOL" build reaction-intake.json species-registry.json \
  condition-model.json --review mechanism-network-review.json \
  --output mechanism-network.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$NETWORK_TOOL" validate mechanism-network.json
```

This upstream W3 slice validates complete reviewed states, exact atom maps,
connectivity changes, element/charge conservation, competing networks,
reference basins and catalyst-projection closure. It does not infer any of
them. The network necessarily precedes its child mechanism-support artifact,
so it retains a null child binding and `mechanism_support_unavailable`; this is
an ordering blocker, not a claim that the child builder is unimplemented.
Network output remains `calculation_ready: false` and grants no mechanism
promotion, calculation DAG, protocol, Gaussian input, or live authority.

### 5. Build the offline calculation plan and study index

Invoke this only after the exact W1 chain, finalized mechanism network and an
explicit human-authored calculation-plan review exist. Read
[references/calculation-dag-contract.md](references/calculation-dag-contract.md)
before using the builder. Finalization hashes the reviewed draft without
changing its scientific decisions:

```bash
DAG_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/calculation_dag.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" finalize-review calculation-plan-review.draft.json \
  --output calculation-plan-review.json
```

Build and validate the non-executable plan:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" build-plan reaction-intake.json species-registry.json \
  condition-model.json mechanism-network.json \
  --review calculation-plan-review.json \
  --output calculation-plan.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" validate-plan calculation-plan.json
```

Every required artifact binding records its relative path, file SHA-256, byte
size, schema and canonical payload SHA-256. The builder and validators use
strict JSON, refuse symlinks, hash drift, unknown fields, graph forgery and
output overwrite, require a pre-existing real output parent, reject divergent
W1/W3 revision chains, and independently recompute graph order, target-
continuous dependencies, readiness, blockers, supersession and coverage.

Bind an exact `gaussian-ts-precedent-map/1` with `--ts-precedent-map FILE`.
The DAG builder calls its owner validator, requires the same exact
W1/network/mechanism-support parents, and clears only the TS-precedent blocker
for edges with a locally accepted, promotion-complete record. Uncovered edges
remain blocked. A supplied `gaussian-reaction-mechanism-support/1` must pass
the origin evidence-gate owner validator and match the selected exact W1 and
network parents. Its eligibility is edge-plus-stereochemical-channel scoped,
while calculation-plan review `/1` carries only edge IDs; therefore the DAG
retains `mechanism_support_channel_mapping_missing` and never collapses channel
decisions into edge-level readiness. If the owner review/gate is blocked or
has blockers, those exact normalized blockers and
`mechanism_support_not_promotable` remain in the plan/index; channel mapping is
not suggested until the owner gate is accepted and clear. Use repeated
`--supersedes-plan FILE` bindings only for exact immutable earlier plans
explicitly superseded by the review; never rewrite an older plan.

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
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" build-index calculation-plan.json \
  --output reaction-study-index.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" validate-index reaction-study-index.json
```

The index derives stage gates, the last accepted stage, next blockers,
superseded artifacts and active/historical coverage. It does not mutate the
plan or any specialist artifact. The same tool can finalize and validate a
human-reviewed external-target mapping, then build/validate one append-only
`candidate_inventory` node update for an exact `ts_candidate`. The update
binds the exact local plan, feature-3 target import and mapping review; it does
not promote readiness or grant submission/evidence-acceptance authority.

Start from the sanitized draft shape in
`tests/fixtures/reaction_workflow/calculation_target_mapping_review.template.json`,
replace every placeholder with an exact local binding and explicit human
decision, then run:

```bash
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" finalize-target-mapping-review mapping-review.draft.json \
  --output mapping-review.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" validate-target-mapping-review mapping-review.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" build-node-update mapping-review.json \
  --output candidate-node-update.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$DAG_TOOL" validate-node-update candidate-node-update.json
```

The `/1` bridge is closed to `expected_node_kind: ts_candidate`,
`update_kind: candidate_inventory`, and
`artifact_role: candidate_target_import`. `external_target_key` remains an
adapter key and is never interpreted as the DAG `node_id`. DAG references are
relative, exact and non-null even when an encapsulated adapter artifact uses a
broader reference convention.
Its gate order is W1, finalized mechanism network, exact network support,
dependent TS precedent, calculation plan, input review, then live approval;
each emitted stage blocker resolves to the plan's normalized blocker record.

### 6. Use the optional reviewed calculation-artifact adapter

Use this only after the exact upstream candidate, protocol, input review, or
specialist result artifacts already exist. Read
[references/calculation-artifact-adapter-contract.md](references/calculation-artifact-adapter-contract.md)
before use.

This adapter is currently unreleased repository source and has not been
deployed. Run these commands from the repository root during development.
Named deployment must use the repository's reviewed
`scripts/sync_named_skill.py` plan/apply flow: this Skill's closed
`deployment-package.json` maps the authoritative reaction-workflow contracts,
while the asymmetric-catalysis owner's manifest maps its exact validator and
schemas. Direct directory copying is not a complete deployment package.

```bash
ADAPTER="skills/auto-g16-reaction-workflow/scripts/calculation_artifacts.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" export-targets candidate-ledger.json \
  --study asymmetric-study.json --import-id reviewed_target_import \
  --output candidate-target-import.json

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" build-input-handoff promoted-candidate.json \
  --study asymmetric-study.json --options protocol-options.json \
  --selection protocol-selection.json --review exact-input-review.json \
  --output-input reviewed-ts.gjf \
  --output-manifest reviewed-ts.handoff.json

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" project-energy promoted-candidate.json parsed-ts-result.json \
  --review energy-review.json --output-record reviewed-energy.json \
  --output-lineage energy-lineage.json

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" link-attempt \
  --external-target-key asymmetric_candidate:study_id:candidate_id \
  --input-handoff reviewed-ts.handoff.json \
  --sanitized-job sanitized-job-observation.json \
  --terminal-intake terminal-intake.json --parsed-result parsed-ts-result.json \
  --mode-review ts-mode-review.json --scientific-decision ts-mode-decision.json \
  --attempt-link-id reviewed_attempt_link --output calculation-attempt-link.json

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" validate candidate-target-import.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" validate reviewed-ts.handoff.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" validate energy-lineage.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$ADAPTER" validate calculation-attempt-link.json
```

Validate an energy projection through its lineage sidecar. The bare reviewed
energy record intentionally has no standalone source pointers and is refused
by `validate`.

Version 1 accepts only one explicit-Cartesian, restricted closed-shell,
main-group, single-guess TS/Freq family. It delegates final input syntax to
`auto-g16-rtwin-pbs`, delegates single-guess family checks to
`auto-g16-ts-irc`, and also delegates parsed-result/terminal classification
and mode-review geometry consistency to that specialist's
`classify_ts_freq_result_facts`, `classify_ts_freq_terminal_facts`, and
`validate_mode_review_geometry` helpers. Attempt linkage also requires parsed
contiguous indices and ordered elements to match the handoff's reviewed atom
order; parsed results do not carry source atom IDs. It consumes rather than
reparses specialist TS result and scientific-review JSON. Metal, open-shell,
QST, IRC, AllCheck/Check,
`Guess=Read`, Link1, general-basis/ECP and non-empty trailing-section variants
remain refused.

The output `.gjf` is only a reproducible offline handoff. Every companion,
target, energy, and observation artifact keeps `calculation_ready: false` and
`no_submission_authorization: true`. The adapter has no stage, submit, retry,
cancel, cleanup, DAG mutation, or resume command.

### Optional immutable recalculation-decision sidecar

Use this only after one failed attempt and its exact input, protocol, result,
and terminal evidence have already been preserved. Read
[references/recalculation-decision-contract.md](references/recalculation-decision-contract.md),
then finalize and validate the human review inside one portable package root:

```bash
DECISION_TOOL="skills/auto-g16-reaction-workflow/scripts/recalculation_decision.py"

python3 "$DECISION_TOOL" finalize --root decision-package review.draft.json \
  --attempt evidence/attempt.json --input evidence/input.json \
  --protocol evidence/protocol.json --result evidence/result.json \
  --terminal-evidence evidence/terminal-intake.json \
  --output recalculation-decision.json
python3 "$DECISION_TOOL" validate --root decision-package \
  recalculation-decision.json
```

`gaussian-recalculation-decision/1` is an immutable evidence-only decision
record. It never changes an input or upstream job/result, creates a proposal,
retries, submits, cancels or cleans up. Even its single approving decision only
selects one exact human-authored proposal for later independent protocol,
scientific-maturity, input and live-approval gates. It fixes
`calculation_ready: false`, `no_submission_authorization: true` and
`no_automatic_retry: true`.

### 6a. Close scientific maturity before TS input review

Use `scripts/scientific_maturity.py` after the exact calculation plan exists.
The review requires the complete literature/user-hypothesis intake and search-
saturation ledger, exact edge/channel decisions, two accepted Gaussian minima
per TS edge, pilot/resource budget, TS/IRC evidence state, common-reference
thermochemistry policy and the closed stop-condition set.

```bash
MATURITY="skills/auto-g16-reaction-workflow/scripts/scientific_maturity.py"
python3 "$MATURITY" finalize-review maturity-review.draft.json --output maturity-review.json
python3 "$MATURITY" build calculation-plan.json --review maturity-review.json --output maturity-gate.json
python3 "$MATURITY" check-action maturity-gate.json --edge-id edge_id --action ts_input --pilot
python3 "$MATURITY" authorize-action maturity-gate.json --input pilot.gjf \
  --edge-id edge_id --node-id pilot_node --action ts_submission --pilot \
  --resource-tier simple --project fresh_project --work-kind ts_pilot \
  --task-count 1 --estimated-core-hours 8 --planned-concurrency 1 \
  --output scientific-action-authorization.json
```

Formal TS input remains blocked unless the exact plan already binds the owner-
validated mechanism-support and TS-precedent artifacts and the overlay supplies
the explicit edge/channel mapping. Without direct precedent, only one simple-
tier pilot may pass after both minima; it remains an internal hypothesis.
Minimum acceptance binds the raw log and replays it through the RTwin/PBS
Gaussian parser; a rehashed result JSON cannot substitute for that owner
evidence. Passing this gate grants neither input approval nor live authority.
The action-authorization command is also offline-only: it prevents reuse across
a different input, project, node or budget scope, but still grants no staging
or submission authority.

When owner-evidence overlay `/2` is required, use
`scripts/scientific_maturity_v2.py` after the immutable `/1` gate. It replays
the public plan, mechanism-support, precedent, conformer-handoff, applicable
main-group open-shell, and manual-receipt validators. It emits a separate
evidence receipt, gate, and exact-scope science action; it does not alter `/1`
semantics. Manual evidence remains supporting-only, and `ts_input`,
`ts_submission`, and `irc_input` still require separate input review. The
current owner set cannot bind a selected conformer through exact input approval
to the accepted minimum result/log, so all `/2` minimum gates and actions remain
fail-closed. IRC and formal reporting additionally require future exact owner
TS-mode and complete thermochemistry/energy artifacts; `/1` booleans do not
provide `/2` authority.

### 7. Preserve the W2 knowledge and literature gates

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
`auto-g16-reaction-literature` Skill implements the query, metadata retrieval,
screening and source-evidence stages. This Skill now also owns separate offline
mechanism-support and TS-precedent-map builders described below. This W1
builder still performs none of those
actions. Do not claim that a database was queried or updated, claim that a
search was performed without its immutable artifacts, infer a mechanism from a
citation, or transfer an unreviewed structure/geometry. A database match and
literature similarity do not prove the target mechanism or TS and grant no
calculation authorization.

### Optional reviewed mechanism-support gate

Invoke this only after the immutable W1/network chain, knowledge snapshot,
finalized literature evidence and a human-authored edge/channel review exist.
Read
[references/mechanism-support-contract.md](references/mechanism-support-contract.md),
then run:

```bash
SUPPORT_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_support.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$SUPPORT_TOOL" build mechanism-network.json knowledge-snapshot.json \
  literature-evidence.json --review mechanism-support-review.json \
  --output mechanism-support.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$SUPPORT_TOOL" validate mechanism-support.json
```

The artifact keeps evidence classification separate from two independent
decisions. A reviewed novel edge may be `hypothesis_exploration_eligible` when
no direct precedent was found, but it remains not literature-supported and not
mechanism-validated. Direct evidence, analogy, internal rationale,
contradictions and missing precedent remain distinct. Every output remains
offline and non-authorizing.

### Optional mechanism-support matrix view

Use this only after the exact owner-validated
`gaussian-reaction-mechanism-support/1` artifact exists and a separate human-
authored matrix review is complete. Read
[references/mechanism-support-matrix-contract.md](references/mechanism-support-matrix-contract.md),
then run:

```bash
MATRIX_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/mechanism_support_matrix.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$MATRIX_TOOL" build mechanism-support.json \
  --review mechanism-support-matrix-review.json \
  --output mechanism-support-matrix.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$MATRIX_TOOL" validate mechanism-support-matrix.json
```

`gaussian-reaction-mechanism-support-matrix/1` is a distinct comparison view,
not a new version or alias of the evidence gate. Its rows and cross-evidence
cells cannot change owner support records or either owner decision. A matrix
row becomes downstream-reviewable only when its reviewed comparison disposition
and the unchanged owner exploration gate both permit another offline review.
It never proves a mechanism, creates a TS seed or executable DAG node, selects
a protocol, authorizes calculation, or mutates an upstream artifact.

### Optional reviewed TS-precedent and de novo seed map

Invoke this only after an immutable W1 chain, reviewed mechanism-network
artifact, reviewed knowledge snapshot, finalized literature evidence with all
four W1/knowledge bindings, and an explicit human-authored precedent review
exist. Read
[references/ts-precedent-map-contract.md](references/ts-precedent-map-contract.md),
then run:

```bash
PRECEDENT_TOOL="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/ts_precedent_map.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$PRECEDENT_TOOL" build mechanism-network.json knowledge-snapshot.json \
  literature-evidence.json mechanism-support.json \
  --review ts-precedent-review.json \
  --output ts-precedent-map.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$PRECEDENT_TOOL" validate ts-precedent-map.json
```

This converts reviewed edges and evidence into immutable atom-correspondence,
geometry-transfer-scope and seed-strategy review records. It copies no
coordinates and constructs no geometry. The exact mechanism-support edge and
channel must be exploration-eligible. A novel edge with no direct precedent
may use a separate de novo endpoint/QST, scan or reviewed-rebuild plan with
`source_precedent: null` and `source_coordinates_used: false`; that does not
make the mechanism claim literature-supported or validated.

### Reaction thermochemistry readiness audit

Read
[references/thermochemistry-readiness-contract.md](references/thermochemistry-readiness-contract.md)
before auditing a prospective comparison package. This is a blocker audit, not
a thermochemistry comparator:

```bash
READINESS="$HOME/.codex/skills/auto-g16-reaction-workflow/scripts/thermochemistry_readiness.py"

"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$READINESS" build readiness-request.json \
  --root package-root --output readiness-audit.json
"${AUTO_G16_CORE_PYTHON:-$HOME/miniforge3/bin/python3}" "$READINESS" validate readiness-audit.json \
  --root package-root
```

It replays supplied public owner validators, requires all direct and transitive
bindings to be relative to the explicit readiness package root, and emits only
structured blockers. Historical artifacts using another path convention need
a separately reviewed owner rebuild/repackage; the audit does not rewrite or
promote them. Maturity `/1` remains insufficient and is always blocked pending
an owner-evidence `/2`. No barrier arithmetic or live action is available.

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
  extraction, applicability review, mechanism-support and TS-precedent design.
  The query and evidence stages are implemented by
  `auto-g16-reaction-literature`; the strict offline mechanism-support and
  TS-precedent/de novo-planning slices are implemented here.
- `references/mechanism-support-contract.md`: implemented immutable-parent,
  edge/channel evidence classification, independent exploration and claim-
  support decisions, contradiction handling and fail-closed rules.
- `references/mechanism-support-matrix-contract.md`: separate immutable matrix-
  view ownership, exact support/network binding, complete row-by-record
  coverage, evidence-gate compatibility and explicit PR #19 migration rules.
- `references/ts-precedent-map-contract.md`: implemented immutable-parent,
  atom-correspondence, geometry-transfer, strategy and fail-closed promotion
  rules for `gaussian-ts-precedent-map/1`.
- `references/mechanism-network-contract.md`: implemented first W3 offline
  review/output semantics, fail-closed diagnostics and mandatory evidence
  blocker.
- `scripts/mechanism_network.py`: standard-library-only deterministic W3
  mechanism-network builder and validator; no calculation or live path.
- `scripts/mechanism_support.py`: standard-library-only deterministic evidence
  classification and two-gate builder/validator; no calculation or live path.
- `scripts/mechanism_support_matrix.py`: standard-library-only deterministic
  comparison-view builder/validator over the exact owner support artifact; no
  chemistry inference, DAG mutation, calculation or live path.
- `scripts/ts_precedent_map.py`: standard-library-only deterministic TS
  precedent-map builder and validator; no coordinate or input construction.
- `references/calculation-dag-contract.md`: implemented offline calculation-
  plan and study-index semantics, dependency/readiness rules, immutable
  bindings, supersession and specialist ownership boundaries.
- `scripts/calculation_dag.py`: standard-library-only deterministic review
  finalizer, calculation-plan builder/validator and study-index
  builder/validator; no input rendering, execution or live path.
- `scripts/scientific_maturity.py`: standard-library-only immutable maturity
  review/gate builder, deterministic DAG-node projection and fail-closed action
  check reused by TS and PBS owners; no route, input or live authority.
- `scripts/scientific_maturity_v2.py`: compatibility-preserving owner-evidence
  receipt/review/gate/action overlay over one exact validated maturity gate `/1`;
  no route, input, submission or live authority.
- `references/scientific-maturity-contract.md`: prospective literature,
  mechanism, minima-first, pilot/budget, TS/IRC, reference-state and migration
  contract.
- `references/scientific-maturity-owner-evidence-v2-contract.md`: exact owner
  replay, conformer/open-shell/manual projection, action interface and `/1`
  compatibility boundary.
- `scripts/calculation_artifacts.py`: standard-library-only target-import,
  exact input-handoff, blocked/electronic-only energy-lineage and immutable
  attempt-link adapters; no live path.
- `references/calculation-artifact-adapter-contract.md`: exact source,
  authority, refusal, energy-lineage and DAG-owned importer boundary.
- `scripts/recalculation_decision.py`: standard-library-only portable-package
  finalizer and replay validator for immutable, non-authorizing recalculation
  decisions; no input mutation or live path.
- `references/recalculation-decision-contract.md`: evidence-role allowlists,
  package-root portability, integrity-versus-owner authority, exact proposal,
  decision-enumeration and atomic-publication contract.
- `scripts/thermochemistry_readiness.py`: standard-library-only owner-replay
  readiness audit with atomic no-clobber publication; it emits blockers and no
  formal comparison or barrier.
- `references/thermochemistry-readiness-contract.md`: exact package-relative
  reference, owner-registry, blocker, repackaging and authority contract.
- `contracts/reaction-workflow/` in the repository: Draft 2020-12 output
  schemas for intake, registry, condition-model, mechanism-network,
  mechanism-support, mechanism-support-matrix review/output, TS-precedent-map,
  calculation-plan, study-index, scientific-maturity `/1` review/gate,
  owner-evidence `/2` review/receipt/gate/action, and the calculation-artifact
  adapter family.
