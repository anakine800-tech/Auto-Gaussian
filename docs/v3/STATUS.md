# Auto-G16 v3 Status

- **Current phase:** `V30-MIN-VALIDATE-PUBLIC-SHAPE-CLOSEOUT-01` has one exact
  authority candidate from
  `main@f07809d406860c13e0d8d4be4d01eb156a6f901e`. Before that content is
  present on authoritative main, publication/integration remains pending; when
  it is present on authoritative main, the task is
  `CLOSED / FROZEN / INTEGRATED`. The content closes the remaining record,
  service, policy, and identity shape. `V30-VAL-SCI-01` is CLOSED / INTEGRATED;
  ScientificValidation validation ownership is active on main and the
  `config/context-map.toml` routing gap is closed.
  `V30-MIN-VALIDATE-CONTRACT-01` is CLOSED / FROZEN / INTEGRATED, and the
  minimum ScientificValidation contract is active on main.
  `V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01` is CLOSED / FROZEN / INTEGRATED,
  and `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01` is CLOSED / INTEGRATED.
  `GaussianJobParser` and `gaussian-job-facts` are active on main, so the
  Result-attribution dependency is satisfied. ScientificValidation must not
  parse raw Gaussian output. The historical `GaussianLogParser` semantics and
  generic parser-version Result authority are preserved.
  `V30-MIN-VALIDATE-IMPL-01` remains `NO-GO` until this public-shape closeout
  is integrated and a separate Owner Implementation Gate is opened,
  `V30-EXEC-02` remains waiting, and live work remains unauthorized.
- **Completed:** Phase 0 and Phase 0.6 owner decisions are confirmed.
- **Completed:** The minimal documentation control plane is materialized on the
  isolated documentation branch.
- **Completed:** The committed control plane passed the nine-item Phase 0 exit
  review.
- **Completed:** The first Core Interface Review milestone is PASS WITH
  CONDITIONS. The `auto_g16.core` path and immutable keyword-only domain-record
  interface are approved; canonical payload encoding stays private and
  `ExecutionSnapshot` stays excluded.
- **Completed:** Independent Final Core Review is PASS with P0=0, P1=0, P2=0,
  and P3=0; all four earlier P1 findings are closed.
- **Completed:** The four bounded P1 remediations now provide a unique explicit
  concurrent submission winner, persisted single-root enforcement, exact
  schema-v1 reopen identity validation, and semantic public payload views with
  private tagged encoding. Their focused and adversarial offline acceptance
  checks pass on the current candidate.
- **Completed:** Core public boundary freeze is PASS. The reviewed public
  exports, record fields, enums, errors, store methods, schema-v1 contract, and
  private-implementation boundary are frozen.
- **Completed:** V30-CORE-01 was merged to `main` at
  `d8f657d1f31a07f93cc9f58e2fa9cabe2cf8b1c7`; post-merge main CI is PASS on
  that exact SHA.
- **Completed:** `V3-MAINT-TEST-01` was merged by normal merge in PR #63 and is
  integrated on `main` at `a2c092e3a089e8803054e75ab3828c079db185b5`.
  Exact-main post-merge CI is PASS and product findings are `0`.
- **Closed:** `V3-MAINT-TEST-02` is integrated and CLOSED on
  `main@56eee913ca0041ce6b26aa1d2c9b8a807114b078`.
- **Validation disposition:** The PR #63 and exact-main control-plane full
  attestations took approximately 77 minutes as expected. This is integration
  evidence, not a permanent target or a reason for ordinary leaf v3 PRs to run
  the legacy-heavy full suite.
- **Completed candidate:** The Post-Core autonomy policy, three-workstream
  Integration Owner structure, validation policy, and four Task Contracts are
  frozen in [`AUTONOMOUS_DEVELOPMENT.md`](AUTONOMOUS_DEVELOPMENT.md). Planning
  completion does not authorize implementation.
- **Satisfied / integrated:** `V30-RESULT-01` is integrated on
  `main@9b771eb758e80dc8818e2022016bdef9db7075e7`; its exact-main affected CI and
  CodeQL are PASS.
- **Satisfied / integrated:** `V30-EXEC-01` is integrated on
  `main@2911451eb91a63c4c1df7601b4ac49610b6205a3`; its exact-main affected CI
  and CodeQL are PASS.
- **Closed:** `V3-MAINT-TEST-03` and `V30-INTEGRATION-CLOSEOUT-01` are
  integrated on `main@6ab92707d3ff5c2f930c8566b8631684a16d4e22`;
  exact-main `v3-full` CI and CodeQL are PASS.
- **Closed / integrated:** V30-3A and V30-3B are CLOSED. Scientific Approval,
  exact finite-set Batch Submit Approval, and exact ExecutionSnapshot
  Operational Confirmation are integrated under `auto_g16.approval` on
  `main@4a181871b0894161dd74fe91c405aa35e3691fd6`. V30-3 changes no Core
  API/schema and reopens neither the EXEC nor RESULT contract.
- **Closed:** `V30-AUTH-HYGIENE-01` is integrated on
  `main@d3a3626a9b93d5f744e71bfafa60e60e85b11fa1`; the residual v2/v3
  Project-versus-Attempt workspace wording ambiguity is closed.
- **Closed / integrated:** V30-WF-CONTRACT-01 fixes the minimal finite Workflow DAG,
  bounded Map, terminal Attempt-state Condition, HumanGate, append-only
  decision persistence, deterministic replay, Core relationship, and
  zero-effect boundary; the clarified V30-4 implementation is integrated on
  `main@2b89366de5e1b8ead53f480a29194c9dfb3c3185`. It creates no Core/API/schema
  change and grants no live authority.
- **Validation ownership integrated:** `V30-VAL-WF-01` is integrated on
  `main@999d8ffb823dc52298d6a882c96a9f663ce5e51e`; this does not authorize
  Workflow implementation.
- **Closed / integrated:** `V30-WF-ID-CLARIFY-01` distinguishes local
  definition-scoped component IDs from WorkflowDefinition and decision UUIDv5
  authority records. `V30-RTWIN-MIN-01` is also integrated as an offline
  Execution slice; neither integration grants RTwin/PBS/Gaussian live authority.
- **Closed / frozen / integrated:** The additive `GaussianJobParser` contract
  is active on `main@717f5b12bc80d78ac92c5110d5a3f12901f10358` and keeps
  `GaussianLogParser` v1 history unchanged and owns a normative original-byte
  LF/CRLF tokenizer, literal/closed-regex FSM, section-local machine facts,
  half-open source spans, generic geometry blocks, and strict single-primary
  fail-fast diagnostic ownership. Thermochemistry candidates validate
  structure, canonical key, numeric grammar, and finite conversion before
  duplicate cardinality against prior committed same-key evidence; a valid
  duplicate owns its full current raw-byte line. The failed one-section
  ScientificValidation workaround is closed; its candidates remain immutable
  failed evidence.
- **Closed / integrated:** `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01` is
  integrated in PR #84 on
  `main@95e8f89a3322a30e785ca2000fc1f0e237c2d5d8`.
  `GaussianJobParser` and `gaussian-job-facts` are active on main; historical
  `GaussianLogParser` semantics and generic parser-version Result authority
  remain preserved.
- **Closed / frozen / integrated:** `V30-MIN-VALIDATE-CONTRACT-01` consumes the
  integrated attributed Result facts and freezes exactly four machine
  classifications: `VALIDATED_MINIMUM`, `NOT_MINIMUM`, `INCOMPLETE`, and
  `UNSUPPORTED`. Its closed 15-code primary-reason vocabulary emits exactly one
  reason under first-applicable precedence. Previous failed candidates remain
  immutable negative evidence.
- **Public-shape closeout:** The exact two-record fields/types, four service
  signatures, store signatures, three-error hierarchy, source-controlled
  policy constants, UUIDv5 domains, and tagged canonical encoding are frozen
  by `V30-MIN-VALIDATE-PUBLIC-SHAPE-CLOSEOUT-01`. When this exact authority
  content is present on main, ScientificValidation is
  `FROZEN / INTEGRATED / PUBLIC SHAPE COMPLETE`; implementation remains
  unauthorized pending its separate Owner gate.
- **ReviewBundle contract candidate:** `V30-REVIEW-MIN-CONTRACT-01` freezes a
  future `auto_g16.review` projection over exact persisted Core, Result, and
  ScientificValidation authority. Its exact public inventory is
  `ReviewAcceptanceState`, `ReviewBundle`, `ReviewBundleError`,
  `build_review_bundle`, and `render_review_bundle_json`. The candidate creates
  no scientific fact, current/latest selection, acceptance, persistence,
  viewer action, execution authority, or live effect. Its InputBinding,
  OutputEnvelope, and ParseOutcome projections explicitly include their exact
  validated public `observation_id`, `observation_id`, and `result_id`; the
  same closed mappings bind deterministic bundle identity and rendering.
  Product implementation remains `WAIT` until ScientificValidation
  implementation is integrated and separate Review contract publication,
  validation-ownership, and implementation gates are approved.
- **Frozen v3.0 scientific policy:** Minimum validation covers ordinary
  nonlinear systems only, requires `N >= 3`, rejects dummy atomic-number-0
  centers, and requires exactly `3N - 6` modes. Every finite frequency below
  `0.0` is imaginary: zero negatives yields `VALIDATED_MINIMUM`, one or more
  yields `NOT_MINIMUM`, and error termination yields `INCOMPLETE`.
  `ScientificAcceptance` remains separate immutable human authority.
- **Validation ownership integrated:** `V30-VAL-SCI-01` establishes reviewed
  change-aware ownership for `auto_g16/scientific_validation/**` and
  `tests/v3/scientific_validation/**`. `config/context-map.toml` is now owned
  by the v3 control-document route; its earlier conservative
  `legacy-release / fail_closed=true` fallback gap is closed.
- **Wait:** `V30-EXEC-02 = WAIT`; no work is authorized.
- **Live:** `NO-GO`; integration grants no SSH, PBS, Gaussian, deployment, or
  other live-effect authority.
- **Next gate:** Before public-shape integration, the
  `V30-MIN-VALIDATE-PUBLIC-SHAPE-CLOSEOUT-01` Publish Owner Gate. Once the exact
  closeout is integrated and its exact-main gate passes, the next gate is the
  `V30-MIN-VALIDATE-IMPL-01` Owner Implementation Gate. ScientificValidation
  product implementation remains `NO-GO` until that separate gate is opened.
- **CI authority:** Under the current branch-protection and code-scanning
  configuration, the five required PR contexts are merge authority. Dynamic
  CodeQL is a post-merge exact-main attestation. Any material configuration or
  required-context change requires this policy to be re-evaluated.
- **CI monitoring:** GitHub `Z` timestamps are UTC; owner-facing reports convert
  them to local time. Do not report unchanged status minute by minute, rerun a
  still-running job, impose an unapproved timeout, or classify a slow harness
  as a product failure. Report state changes, anomalies, and terminal status.
- **Do not start:** ScientificValidation implementation,
  `V30-MIN-VALIDATE-IMPL-01`, `V30-EXEC-02`, Observe, ReviewBundle, production
  changes, deployment, live smoke, and SSH/PBS/Gaussian operations remain
  unauthorized.
