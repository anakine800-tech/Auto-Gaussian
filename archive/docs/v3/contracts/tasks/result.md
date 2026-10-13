# Auto-G16 v3 tasks: result

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:222-247 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V30-RESULT-01

- **Outcome:** Materialize typed, provenance-bearing result observations from a
  frozen program-adapter output boundary without turning parsing into scientific
  acceptance.
- **Scope:** After the input/result boundary is explicitly frozen, implement the
  bounded offline result interpretation and persistence slice against synthetic
  artifacts; use the existing Core types without changing their contract.
- **Explicit non-goals:** No execution or transport, no Gaussian/PBS/RTwin live
  work, no scientific minimum/TS/IRC acceptance, no new schema/framework, and no
  Core public-boundary change.
- **Dependencies:** Core `CLOSED`; owner-frozen adapter input and result
  acceptance contract. Synthetic boundary fixtures keep this lane independent
  from completion of `V30-EXEC-01` until serial integration.
- **Autonomy:** `BOUNDED-AUTONOMOUS` after the dependency contract is frozen.
- **Stop rules:** Stop rather than invent adapter fields, result states,
  provenance, invariants, or scientific meaning; also stop for public-boundary,
  scope, dependency, or security/live changes and two same-class failures.
- **Acceptance/validation:** Focused/affected offline checks cover complete,
  partial, malformed, and conflicting synthetic results, identity/provenance,
  append-only persistence, and the separation between observation and
  scientific acceptance. Independent review is required before integration.
- **Handoff:** Freeze input/output contract identity, scope, findings,
  validation evidence, unresolved scientific decisions, and Integration Owner
  next gate.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:292-367 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01

- **Outcome:** Freeze the minimum additive Result-owned parser and fact schema
  that can distinguish machine-emitted Gaussian job output from
  user-controlled echo and attribute every downstream scientific evidence
  group to exact bytes.
- **Scope:** Contract authority only. Preserve `GaussianLogParser` v1 and
  existing `gaussian-log-facts` history unchanged; add the public
  `GaussianJobParser` tuple, exact-byte single-job grammar, strict attributed
  facts/spans, all recognized generic geometry blocks, parser status matrix,
  durable reopen checks, acceptance matrix, and narrow reuse adjudication.
- **Explicit non-goals:** No Result or ScientificValidation implementation,
  tests, selector mutation, Core/API/schema change, Execution/Approval/Workflow
  change, multi-job selection, checkpoint dependence, scientific minimum/TS/
  IRC decision, transport, SSH, RTwin/PBS/Gaussian, retry, deployment, or live
  work.
- **Dependencies:** `V30-RESULT-01` and V30-4 are integrated. The public
  adversarial replay proving whole-log echo contamination is the root-cause
  evidence. The failed one-section ScientificValidation candidates remain
  immutable evidence and grant no implementation authority.
- **Autonomy:** `OWNER-GUIDED`. Work may include only narrow parser/reuse
  inspection, authority drafting, offline document consistency checks,
  self-review, and the named independent adversarial contract review.
- **Stop rules:** Stop if safe attribution requires a Core change, a change to
  existing Result identity or `GaussianLogParser` v1 semantics, an Execution/
  Approval/Workflow change, a nondeterministic heuristic, external rerun or
  checkpoint authority, product/test/selector edits, scope expansion, or two
  same-class repairs.
- **Acceptance/validation:** Prove exact tuple-dispatched outer schema-v1
  compatibility, unchanged historical reopen, the normative raw-byte
  LF/CRLF tokenizer, literal/closed-regex FSM transitions and echo suppression,
  the exact artifact/status matrix, one-primary-diagnostic fail-fast ownership,
  disjoint orphan/block/row/numeric/EOF precedence, zero-based half-open spans
  bound to one envelope artifact, strict store/reopen attestation,
  thermochemistry structure/key/numeric/finite validation before a
  prior-committed same-key duplicate check and the full-current-line duplicate
  span,
  complete ordered frequency and geometry blocks with malformed-block fail
  closure, no cross-source splicing, identity conflict behavior, scientific
  neutrality, and the full offset-asserting adversarial matrix in
  `acceptance.md`.
- **Handoff:** Freeze base/head/tree and exact authority-file scope, reuse
  adjudication, P0-P3 findings, validation evidence, and the independent
  Contract Review. Completion authorizes neither publication nor
  `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01`.

### V30-A-GAUSSIAN-OPTFREQ-COMPOSITE-JOB-RESULT-CONTRACT-PARSER-REPAIR-01

- **Outcome:** Add parser `1.1.0` / grammar-2 support for one external Gaussian
  invocation with a closed contiguous internal-step chain, then let existing
  ScientificValidation consume the unchanged attributed fact shape.
- **Scope:** `auto_g16.result` parser/model tuple dispatch,
  `auto_g16.scientific_validation` tuple-aware terminal and evidence
  selection, focused/affected offline tests, the named authority documents,
  exact immutable-capture qualification, independent review, PR, CI, merge,
  and exact-main zero-network replay.
- **Compatibility:** `1.0.0` / grammar-1 remains readable and keeps its exact
  semantics. The new tuple changes Result identity naturally; no old Result,
  envelope, input binding, or public schema is mutated.
- **Autonomy:** `OWNER-GUIDED`, with implementation, normal PR, and merge
  explicitly authorized by the current Owner Gate after zero findings and
  green required checks.
- **Stop rules:** Stop for a second external job, `--Link1--` workflow,
  non-contiguous or ambiguous internal steps, schema/API/reason-vocabulary
  change, raw-byte interpretation in ScientificValidation, artifact-specific
  special casing, an exact-capture parse failure after the narrow repair, or
  any network/live/deployment/effect requirement.
- **Acceptance:** Prove the complete negative and positive grammar matrix,
  legacy reopen, exact two-terminal capture facts, unchanged minimum policy,
  exact three-mode positive frequencies, three-atom selected geometry,
  deterministic append-only identities, and zero product effects.
- **Handoff:** After merge, preserve old and new ParseOutcomes, select the new
  current Result, terminalize Core only through its public lifecycle if the
  composite is all-normal, record minimum validation and an eligible but
  unaccepted ReviewBundle, and return for Owner scientific acceptance.
