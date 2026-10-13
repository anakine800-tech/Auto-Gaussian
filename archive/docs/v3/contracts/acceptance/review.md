# Auto-G16 v3 acceptance: review

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:655-795 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-REVIEW-MIN-CONTRACT-01: Minimum Deterministic ReviewBundle

**Status: CONTRACT FREEZE CANDIDATE; IMPLEMENTATION WAIT.** These conditions
freeze the smallest v3.0 presentation/projection layer. They create no
ScientificAcceptance, execution authority, retry authority, product code,
selector change, external-viewer action, or live effect:

1. `auto_g16.review` is the sole future public package and
   `tests/v3/review/` its focused-test package. Its public inventory is exactly
   `ReviewAcceptanceState`, `ReviewBundle`, `ReviewBundleError`,
   `build_review_bundle`, and `render_review_bundle_json`.
2. Review depends only on public Core, Result, and ScientificValidation
   surfaces. It does not import Execution to reproduce snapshot semantics, and
   Core, Result, ScientificValidation, Approval, Execution, and Workflow never
   import Review.
3. The exact `ReviewBundle` field/type inventory in `boundary-spec.md` is
   immutable, keyword-only, service-created, and deeply closed. A caller
   cannot add an authority field or directly choose `review_bundle_id`.
4. The builder loads the exact persisted CalculationPlan, Attempt,
   MinimumValidationOutcome, and each explicitly named ScientificAcceptance;
   it proves the supplied InputBinding, OutputEnvelope, and ParseOutcome are
   exact persisted same-Attempt records rather than trusting a mapping copy.
5. The plan ID/revision/task, Attempt/task, InputBinding observation, envelope
   observation, parse Result ID/tuple, policy ID/version, and outcome binding
   must all close. Any missing, stale, or cross-plan/cross-Task/cross-Attempt/
   cross-input/cross-envelope/cross-Result/cross-policy/cross-outcome splice
   fails before projection.
6. InputBinding and OutputEnvelope must carry the same exact
   `execution_snapshot_id`. Review exposes that identity only; it does not
   reconstruct, authenticate, mutate, or reinterpret an ExecutionSnapshot.
7. `selected_final_geometry`, `selected_frequency_blocks`, and
   `selected_frequencies_cm1` are exact immutable copies of the persisted
   MinimumValidationOutcome fields. Review never reads raw Gaussian bytes,
   parses a span, chooses another geometry, shortens/reorders a frequency
   suffix, changes a tolerance, or invents a fact.
8. `minimum_validation_classification` and `primary_reason_code` exactly equal
   the outcome classification and single reason. Review cannot add warnings,
   secondary reasons, scientific recommendations, or an alternative
   classification.
9. A non-`VALIDATED_MINIMUM` outcome accepts no ScientificAcceptance IDs and
   projects only `INELIGIBLE`. A `VALIDATED_MINIMUM` with an empty explicit set
   projects `ELIGIBLE_UNACCEPTED`; with one or more exact acceptances for that
   outcome it projects `ACCEPTED`.
10. Acceptance IDs are explicit, finite, distinct, and sorted lexically only
    for deterministic projection. Duplicate, missing, wrong-outcome, stale, or
    conflicting acceptance evidence fails. Multiple valid acceptances remain
    separate complete mappings; no latest/current/preferred reviewer is
    inferred.
11. Exact unchanged source records and explicit acceptance set produce the
    same complete bundle, UUIDv5 identity, and JSON text across supported
    Python minors and caller mapping order.
12. Schema version, the exact Review namespace/domain in `boundary-spec.md`,
    and the frozen tagged canonical encoding are source-controlled and not
    caller-selectable. Boolean/integer distinction, lexical mapping-key order,
    sequence order, non-finite rejection, cycle rejection, and complete-payload
    identity are adversarially fixed.
13. Any projected source record, selected evidence, classification, primary
    reason, acceptance mapping, or acceptance-state change changes bundle
    identity. A forged/stale ID fails closed before rendering.
14. JSON rendering recomputes identity and emits exactly the complete public
    payload with the frozen JSON options and one final LF. Two renders of the
    same bundle are byte-identical and contain no hidden field, timestamp,
    local path, current-state query result, or free-form scientific inference.
15. A bundle for `INCOMPLETE`, `UNSUPPORTED`, or `NOT_MINIMUM` remains a legal
    factual review projection when its exact upstream records close; the
    renderer does not conceal the classification/reason or turn it into an
    accepted result.
16. Projection and rendering cause zero Core/Result/ScientificValidation
    mutation, zero Review persistence, zero filesystem write/read, zero
    transport/scheduler/Gaussian/viewer call, and zero retry, recovery,
    acceptance, or submission authority.
17. The selected geometry mapping retains exact Result source spans, ordered
    atoms, atomic numbers, units, and coordinates. Review does not infer bonds,
    element identity, connectivity, orientation preference, or calculation
    readiness.
18. Existing legacy review/report artifacts, hashes, paths,
    `calculation_ready`, approval decisions, and viewer manifests are never
    imported as Review authority. A narrow reuse report must retain the exact
    PORT/EXTRACT/WRAP/REWRITE/DROP/DEFER disposition and a concrete reason for
    REWRITE.
19. GaussView/external-viewer file generation, inferred bonds, SSH transfer,
    UI load probing, and GUI/rich report work remain deferred. A future wrapper
    may consume only the explicit selected geometry under a separate gate and
    cannot alter the bundle or create authority.
20. ScientificValidation public shape may inform this contract, but no Review
    product code, substitute record, local stub, or unmerged-worktree
    dependency is allowed before ScientificValidation implementation is
    integrated. `V30-VAL-REVIEW-01` and Review implementation require separate
    Owner Gates.

The projected-record key assertions are exact and set-based:

1. InputBinding projection keys equal exactly the 11-key set
   `schema_version`, `observation_id`, `attempt_id`, `calculation_plan_id`,
   `calculation_plan_revision`, `prepared_input_binding_id`,
   `execution_snapshot_id`, `input_format`, `logical_name`, `sha256`, and
   `size_bytes`.
2. OutputEnvelope projection keys equal exactly the 12-key set
   `schema_version`, `observation_id`, `attempt_id`,
   `input_binding_observation_id`, `execution_snapshot_id`,
   `capture_source_id`, `capture_sequence`, `capture_status`,
   `capture_completeness`, `artifacts`, `capture_manifest_sha256`, and
   `captured_at_utc`.
3. Every OutputArtifact projection keys equal exactly `artifact_kind`,
   `logical_name`, `sha256`, and `size_bytes`.
4. ParseOutcome projection keys equal exactly the 10-key set
   `schema_version`, `result_id`, `attempt_id`, `envelope_observation_id`,
   `parser_name`, `parser_version`, `result_kind`, `parse_status`, `facts`, and
   `diagnostics`.

No projected mapping may omit or add a key. Independent adversarial review and
future contract tests must additionally prove all of the following:

1. InputBinding `payload()` omitting `observation_id` cannot cause the
   projection to omit it.
2. OutputEnvelope `payload()` omitting `observation_id` cannot cause the
   projection to omit it.
3. ParseOutcome `payload()` omitting `result_id` cannot cause the projection to
   omit it.
4. A forged or replaced derived authority ID is rejected rather than copied.
5. The same exact typed record always yields a byte-equivalent projected
   mapping.
6. Mapping insertion order cannot change ReviewBundle identity.
7. Enum `repr` or member name cannot replace the exact public enum value.
8. Artifact path, mtime, local source path, or currentness cannot enter the
   projection.
9. Raw Gaussian output or artifact bytes cannot enter the ParseOutcome
   projection.
10. ReviewBundle identity and deterministic rendering consume exactly the same
    projected semantic mappings, including all three derived public authority
    IDs.

Focused future tests must include exact replay under reordered mappings,
every cross-splice axis in condition 5, mismatched ExecutionSnapshot IDs,
incomplete/unsupported/not-minimum bundles, all three acceptance states,
multiple explicit acceptances, duplicate/wrong-outcome acceptance rejection,
geometry/frequency byte-semantic preservation, forged bundle identity,
deterministic JSON, absence of raw-file/parser/viewer imports, and zero-effect
probes. No test may open a Gaussian log, contact SSH/RTwin/PBS/GaussView, or
create authority outside the exact upstream records.
