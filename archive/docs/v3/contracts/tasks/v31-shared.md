# Auto-G16 v3 tasks: v31-shared

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:718-765 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V31-SHARED-CONTRACT-01

- **Outcome:** Freeze the smallest shared v3.1 contract for Project first-use
  physical provisioning, an additive versioned execution successor required
  for xTB/CREST, conformer handoff, thermodynamic handoff, and deterministic
  TS-seed member projection. V30 Gaussian execution remains production-usable;
  V31 acceptance does not require Gaussian migration.
- **Scope:** `OWNER_DECISIONS.md`, the minimum `docs/v3/**` authority documents,
  and `config/context-map.toml` only when required for authoritative routing.
  Contract text may define future public shapes but creates no product or
  schema implementation.
- **Public budget:** At most two new execution-domain public records:
  `ProgramExecutionSpec` and `ProgramExecutionSnapshot`. Provisioning-domain
  `ProjectPhysicalBinding` is separate. ProgramAdapter is a private closed
  registry for exactly Gaussian/xTB/CREST. Ensemble-domain public records are
  `SamplingProfile`, `ConformerEnsemble`, and
  `ThermodynamicEnsemble`; TS-seed projection stays
  `ConformerEnsemble.ts_seed_members`.
- **Generation routing:** One V31 Workflow/Batch may intentionally contain V30
  Gaussian Attempts and successor-generation xTB/CREST Attempts. Each Attempt
  binds exactly one generation before effect authority, never both, with no
  in-place conversion. A future Gaussian successor requires a separate adapter
  implementation/validation gate and is not an initial V31 acceptance target.
- **Preserve:** V30 `PreparedInputBinding`, `PbsTemplateBinding`, and
  `ExecutionSnapshot`; Core Project shape/schema; Transport topology/protocol;
  parser/grammar and Result meanings; V30 vectors; approval/effect/no-overwrite/
  uncertainty semantics.
- **Policy:** SamplingProfile independently freezes all applicable thresholds
  and policies before observations. Thermodynamics separately preserves raw
  RRHO, per-conformer treated qRRHO, and final degeneracy-weighted ensemble
  aggregation with no unverified defaults or duplicated conformational entropy.
- **Autonomy:** `OWNER-GUIDED`, contract-only and zero-effect. The explicit
  Owner boundary authorizes the contract candidate, offline validation,
  independent review, and one local commit only.
- **Validation:** docs/contract-focused checks, authoritative selector result,
  the selector-required v3-full tests once on the frozen candidate, static/CI
  contract/diff/sensitive checks, clean preflight, and fresh independent
  findings-first review. P0/P1 block.
- **Stop rules:** Stop on base/tree drift; a third execution public record;
  public adapter/plugin surface; hard-coded universal threshold/default;
  in-place V30 reinterpretation; any implication that all V31 Gaussian Tasks
  migrate; Core/Transport/parser/vector/product/test mutation; implementation
  or live need; or any P0/P1.
- **Handoff:** Local commit with exact base/head/tree/diff/test/review evidence
  and PR-ready scope. Do not push, create a PR, merge, deploy, provision, run a
  program, submit, retry, clean up, or accept science.
