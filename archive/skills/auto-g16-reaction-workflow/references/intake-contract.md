# W1 reaction-intake contract

## Scope

This contract records what is known from the experimental reaction package and
what must remain blocked. It does not create a mechanism or calculation plan.
All IDs use lowercase letters, digits and underscores, start with a letter and
contain 3–64 characters. Every output is immutable and hash-bound.

## Intake request

Use schema `gaussian-reaction-intake-request/1` with exactly:

- `study_id`;
- `source_files`;
- `claim_scope`;
- `unresolved_transcription`;
- `review_decision`; and
- `review_notes`.

Each source file requires `source_id`, local non-symlink `path`, `role` and
`description`. Include at least one `chemdraw_source` or `scheme_image`.
Supported roles are `chemdraw_source`, `scheme_image`,
`normalized_transcription`, `supporting_information`,
`experimental_reference` and `other`.

`claim_scope.questions` may contain `feasibility`, `thermodynamics`,
`elementary_barrier`, `mechanism_comparison`, `selectivity`,
`catalytic_turnover`, `literature_reproduction` or `custom`. Record a claim
ceiling and non-goals. A custom question also requires `custom_question`.

Each unresolved transcription entry requires:

```json
{
  "blocker_id": "unreadable_loading",
  "scope": "step_001",
  "description": "Catalyst loading is unreadable.",
  "required_for": ["condition_model"]
}
```

Use `accepted`, `accepted_with_blockers` or `blocked` as the review decision.
Acceptance records the source package for intake; it does not accept its
chemistry for calculation.

## Species review

Use schema `gaussian-reaction-species-review/1`. Bind `study_id` and
`intake_payload_sha256` to the exact intake. Include `species`,
`source_bindings`, `balance_review`, `review_decision` and `review_notes`.

Every species entry requires:

- stable `species_id` and `preferred_label`;
- `origin`: `drawn_species`, `condition_component`, `unshown_species`,
  `workup_species` or `model_species`;
- `required_for_claim`;
- all intake `source_refs` represented by the species;
- exact `represented_form`;
- a local non-symlink structure or `null`;
- formula, integer formal charge, positive multiplicity and component count,
  or explicit `null`;
- stereochemistry, protonation, salt/solvate and overall review status;
- stable atom identity; and
- explicit blockers and notes.

Use `reviewed`, `not_applicable`, `not_assessed`, `unresolved` or `blocked` for
the review-status fields. Required species pass only when structure, formula,
charge, multiplicity, component count and stable atom identity are present and
all chemical-form fields are reviewed or not applicable.

Atom identity records contiguous one-based structure indices and stable atom
IDs. `atom_scope` is `explicit_structure_atoms`, `heavy_atoms_only` or
`not_assessed`. Heavy-atom-only identity is permissible as an explicit W1
limitation; later proton/hydride-transfer work must expand the relevant
hydrogens before atom mapping.

Every drawn reactant/product `occurrence_id` must appear exactly once in
`source_bindings`, with an explicit positive integer stoichiometric
`coefficient`. A condition component may remain unbound to a species only
when the later condition model treats it without an explicit molecular
component. An unshown species is never a license to hide an unexplained
imbalance.

`balance_review` records overall, elemental and charge status separately. Each
unshown species record supplies `species_id`, `step_id`, `side` and positive
integer `coefficient`. The builder independently recomputes per-step elemental
and charge deltas from formulas, charges and coefficients. It refuses a
reviewed `passed` claim when the recomputed result differs. Version 1 accepts
simple molecular formulas such as `C6H10`; parentheses, dot adducts and other
formula syntax must remain blocked until normalized into explicit components.
Use `passed`, `blocked`, `not_assessed` or `not_applicable`; progression to a
reaction network requires reviewed balance or an explicit network-level
blocker.

## Condition review

Use schema `gaussian-reaction-condition-review/1`. Bind the exact intake and
registry payload hashes. Include `global_model`, one decision per condition
ID, a review decision and notes.

The global model contains exactly:

- `standard_state`;
- `temperature_policy`;
- `concentration_policy`;
- `pressure_policy`; and
- `explicit_component_policy`.

Each policy records `status`, `value`, `unit`, `model` and `rationale`. Use
`reviewed`, `not_applicable`, `unresolved` or `blocked`. Do not silently treat
missing experimental concentration or pressure as a reviewed default.

Each condition decision records:

- exact `condition_id`;
- one treatment;
- explicit target `species_ids` only for `explicit_component`;
- a model object when using continuum, chemical-potential or computational-
  parameter treatment;
- rationale; and
- `reviewed` or `blocked` status.

Yield, selectivity and reaction time normally remain
`experimental_context_only` unless a later kinetic model explicitly consumes
them. Workup and purification normally remain `workup_only`; they must not be
inserted into the catalytic reaction state without a reviewed reason.

## Gate semantics

- `reviewed`: no W1 blocker remains for the declared scope.
- `reviewed_with_blockers`: the artifact is valid and useful, but at least one
  downstream prerequisite remains unresolved.
- `blocked`: the reviewer rejected progression at this layer.

All three states remain offline and non-authorizing. A `reviewed` W1 chain may
advance only to future mechanism-network and calculation-planning review; it
does not authorize protocol selection or Gaussian execution.
