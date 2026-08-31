# Auto-G16 v3 Status

- **Current closeout:** Exact finite-path reconciliation for historical
  `680.master` proves a workdir-related failure: the physically bound
  Attempt-03 workspace retains the exact staged GJF while the exact Torque
  stdout reports that Gaussian could not open that relative input. Attempt-03
  remains consumed historical evidence and is not backfilled or retried.
  `V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01` is the active bounded successor:
  Torque must receive exact `-d <snapshot-bound Attempt workspace>` and the
  bootstrap must replay the named workspace physical identity immediately
  before qsub. Integration authorizes no deployment, new Attempt, staging,
  scheduler read, fetch, qsub, Gaussian, qdel, or cleanup.

- **Current phase:** `V30-EXEC-02-COMPOSITION-CONTRACT-01`,
  `V30-TRANSPORT-BOOTSTRAP-CHAIN-03`,
  `V30-TRANSPORT-BOOTSTRAP-SOURCE-CLARIFY-01`, and
  `V30-TRANSPORT-BOOTSTRAP-SOURCE-IDENTITY-CLOSEOUT-01` are
  `CLOSED / FROZEN / INTEGRATED`. `V30-VAL-TRANSPORT-01` is
  `CLOSED / INTEGRATED`, and Transport change-aware ownership is active as
  `affected / fail_closed=false`. `V30-RTWIN-REAL-01` and
  `V30-ACQUIRE-FETCH-MIN-01` are `CLOSED / INTEGRATED`; the reviewed
  `TransportStore`, fixed bootstrap trust/source chain, scheduler acquisition,
  and exact fetch capability are active on authoritative main.
  `V30-A-SYNTHETIC-COMPOSITION-01` is `CLOSED / INTEGRATED`; its product-level
  synthetic composition and adversarial matrix are active on authoritative
  main. `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01` and its reviewed
  implementation are `CLOSED / FROZEN / INTEGRATED`; the qsub seam now derives
  exact scheduler-resource enactment only from the current
  `ExecutionSnapshot.resolved_resource_request`. The affected synthetic
  composition evidence has been rerun on exact integrated main, so V30-A
  OFFLINE readiness remains `PASS`. `V30-PBS-TORQUE-DIALECT-01` is
  `CLOSED / FROZEN / INTEGRATED`; the exact Torque `6.1.0` production renderer
  is qualified on authoritative main. The
  `V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01` contract freezes exact enactment of
  the two profile-bound SSH configs and known-host files. When this exact
  authority content is present on authoritative main, that contract is
  `CLOSED / FROZEN / INTEGRATED`, its bounded Transport implementation is the
  next gate, and the pre-repair resolved profile remains unusable failed
  evidence. No Attempt exists for the first live packet. V30-A LIVE execution
  remains `NO-GO` pending implementation integration, a new profile revision
  and resolved identity, and the later exact Live Owner Gate.
  `V30-MIN-VALIDATE-IMPL-01` is
  `CLOSED / INTEGRATED`, and the ScientificValidation implementation is active
  on authoritative main.
  `V30-MIN-VALIDATE-CONTRACT-01` and
  `V30-MIN-VALIDATE-PUBLIC-SHAPE-CLOSEOUT-01` remain
  `CLOSED / FROZEN / INTEGRATED`; `V30-VAL-SCI-01` remains
  `CLOSED / INTEGRATED`, ScientificValidation validation ownership is active,
  and the `config/context-map.toml` routing gap remains closed.
  `V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01` is CLOSED / FROZEN / INTEGRATED,
  and `V30-RESULT-SECTION-ATTRIBUTION-IMPL-01` is CLOSED / INTEGRATED.
  `GaussianJobParser` and `gaussian-job-facts` are active on main, so the
  Result-attribution dependency is satisfied. ScientificValidation must not
  parse raw Gaussian output. The historical `GaussianLogParser` semantics and
  generic parser-version Result authority are preserved.
  `V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01` selects the qualified
  Mac OpenSSH + RTwin ProxyJump production successor and integrates its minimal
  private Transport seam. ServerProfile revision 8 is the first Option-1
  profile. Deployment, retry, qdel/delete/cleanup, and live calculation work
  remain unauthorized.
- **Observe contract and implementation integrated:**
  `V30-OBS-MIN-CONTRACT-01` is
  `CLOSED / FROZEN / INTEGRATED`. It freezes only read-only exact-Attempt
  source observations, append-only Core persistence, deterministic per-axis
  projection, explicit `unknown`, and zero retry/effect/scientific authority.
  `V30-VAL-OBS-01` is `CLOSED / INTEGRATED`, and Observe validation ownership
  is active on main. `V30-OBS-MIN-IMPL-01` is `CLOSED / INTEGRATED`, and the
  minimal Observe implementation is active on
  `main@301c97d2e664ffbdea79764aae264b97e0e53552`.
- **ReviewBundle contract integrated:** `V30-REVIEW-MIN-CONTRACT-01` is
  `CLOSED / FROZEN / INTEGRATED`, and the ReviewBundle contract is active on
  main. `V30-VAL-REVIEW-01` is `CLOSED / INTEGRATED`, and Review validation
  ownership is active on main. `V30-REVIEW-MIN-IMPL-01` is
  `CLOSED / INTEGRATED`, and ReviewBundle is active on main.
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
  `FROZEN / INTEGRATED / PUBLIC SHAPE COMPLETE`. The later separately
  authorized `V30-MIN-VALIDATE-IMPL-01` is now `CLOSED / INTEGRATED`; the
  public-shape closeout itself granted no implementation authority.
- **ReviewBundle contract integrated:** `V30-REVIEW-MIN-CONTRACT-01` freezes an
  `auto_g16.review` projection over exact persisted Core, Result, and
  ScientificValidation authority. Its exact public inventory is
  `ReviewAcceptanceState`, `ReviewBundle`, `ReviewBundleError`,
  `build_review_bundle`, and `render_review_bundle_json`. The contract creates
  no scientific fact, current/latest selection, acceptance, persistence,
  viewer action, execution authority, or live effect. Its InputBinding,
  OutputEnvelope, and ParseOutcome projections explicitly include their exact
  validated public `observation_id`, `observation_id`, and `result_id`; the
  same closed mappings bind deterministic bundle identity and rendering.
  `V30-VAL-REVIEW-01` is `CLOSED / INTEGRATED`, Review validation ownership is
  active on main, and `V30-REVIEW-MIN-IMPL-01` is `CLOSED / INTEGRATED`.
  ReviewBundle is active on main.
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
- **Transport trust and implementation integrated:**
  `V30-TRANSPORT-BOOTSTRAP-CHAIN-03` preserves the independent append-only
  `TransportStore`, one-time nonce plus exact store/instance identities,
  persisted workspace/artifact/job/receipt physical bindings, and practical
  descriptor-relative/no-follow replacement detection under an explicit threat
  model. The exact canonical runtime content
  `transport-deployment-manifest-v1.json` is final pre-start authority within
  the model and is closed against the current profile and snapshot. Its exact
  nine roots include both real remote shells. `server_python` does not establish
  its own pre-start trust; it may only detect post-start drift and process the
  fixed bootstrap plus closed data packets. The Windows grammar is explicit,
  never detected or silently changed, and the POSIX inner shell is also a named
  deployment root. Commits `798d3559d7c5ee6211a0b29977310f8adb871a5f`,
  `e49136e23c564cc9e0d9d97b905e43c45db73adc`, and
  `44db04180af8222c6e4619accfab0049e89bd3e0` remain immutable negative
  evidence. The last lacked exact seven-operation request/response schemas and
  one realizable fetch response channel; the integrated successor closes both.
  `V30-TRANSPORT-BOOTSTRAP-SOURCE-CLARIFY-01` separates fixed source bytes from
  variable tokens, and
  `V30-TRANSPORT-BOOTSTRAP-SOURCE-IDENTITY-CLOSEOUT-01` closes the exact
  integrated source identity without changing bootstrap protocol v1.
  `V30-RTWIN-REAL-01` and `V30-ACQUIRE-FETCH-MIN-01` implement the reviewed
  RTwin-first adapter, durable Transport bindings, read-only scheduler
  acquisition, and exact output fetch on main. The integration preserves the
  RTwin-first composition contract: the Controller validates the current
  approval chain and calls `execute_once(...)` without pre-claiming; that
  entrypoint alone owns `record_submission_intent(...)`, and only `WINNER`
  enters the first effect boundary.
- **Resource enactment:** `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01` freezes the
  snapshot-only scheduler-resource authority, closed dialect descriptor,
  structured qsub rendering, protocol/table v2 successor, and exact
  REPLAY/UNKNOWN behavior. Its reviewed implementation is integrated and the
  affected exact-main evidence is `PASS`. The accepted read-only preflight now
  closes the exact Torque `6.1.0`, single-node `nodes=1:ppn`, integer-MB,
  integer-seconds, explicit-`batch` production dialect contract.
  `V30-PBS-TORQUE-DIALECT-01` is `CLOSED / FROZEN / INTEGRATED`; its exact
  source-controlled renderer and deployment-evidence checks are qualified on
  authoritative main. This qualification grants no live qsub authority.
- **Current gate:** `V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01` is
  `CLOSED / INTEGRATED`. The selected route is Mac `/usr/bin/ssh` -> exact
  private config -> RTwin `ProxyJump` -> final server. Real qualification
  proved exact 12-byte DATA and EOF, with zero write, retry, or residual.
  Windows ProcessStartInfo and STARTUPINFOEX stdin routes are rejected for real
  DATA; file-backed Windows stdin remains historical unqualified evidence and
  none is an Option-1 fallback. ServerProfile revision 8 binds the qualified
  OpenSSH 10.3p1 identity, explicit RTwin/final trust, and dedicated final-key
  fingerprint without reading private key bytes. Its resolved profile ID is
  `44f3b829-e2d1-5500-b463-5acd8851d279`, effective config SHA-256 is
  `110bac5e2fbcecd2a01a81f8df5004f797cb191b2089b620b4379db28a7cb99d`,
  and its exact ten-root manifest is 3294 bytes with SHA-256
  `bf422724e83cc16031136783fb042207959cb0cd7f602e7d0f63df787350019e`.
  The successor profile additionally binds the exact 120-byte public-key
  artifact (SHA-256 `aca9b1b823ea36c501e76fd755a2acff4f3bd38dafc0f5fa436f4c59ab565f67`)
  and the qualified private key's physical metadata without reading private
  bytes. Both hops bind `CertificateFile none`, disabling implicit sibling
  user-certificate loading. Earlier revision-8 drafts without the public-key
  artifact or this certificate closure are rejected historical evidence and
  grant no authority.
- **Live:** calculation execution remains `NO-GO`. Product integration and
  merge authorize no production config deployment, Attempt workspace, staging,
  qstat/qsub, PBS, Gaussian, cleanup, retry, or other calculation effect. The
  next Owner decision is `OPTION-1 PRODUCTION DEPLOYMENT + PRODUCTION
  QUALIFICATION`.
- **Readiness:** `V30-A-SYNTHETIC-COMPOSITION-01` is `CLOSED / INTEGRATED`.
  The exact integrated composition proves the complete offline authority chain,
  the required negative paths, `WINNER`/`REPLAY` sequencing, explicit
  `UNKNOWN` with no automatic retry, exact scheduler/fetch/capture bindings,
  and zero live effects. When this exact status content is present on
  authoritative main after exact-main validation, `V30-A-READINESS-01` is
  `PASS` for the complete OFFLINE chain including scheduler resource
  enactment. The production renderer and exact-main evidence are closed.
  LIVE remains `NO-GO`; the selected OpenSSH route is integrated but production
  deployment and production qualification remain pending separate Owner
  authority.
- **CI authority:** Under the current branch-protection and code-scanning
  configuration, the five required PR contexts are merge authority. Dynamic
  CodeQL is a post-merge exact-main attestation. Any material configuration or
  required-context change requires this policy to be re-evaluated.
- **CI monitoring:** GitHub `Z` timestamps are UTC; owner-facing reports convert
  them to local time. Do not report unchanged status minute by minute, rerun a
  still-running job, impose an unapproved timeout, or classify a slow harness
  as a product failure. Report state changes, anomalies, and terminal status.
- **Do not start after integration:** further roadmap work, deployment, live
  qualification, recovery Attempt, or V30-A calculation execution. Real
  SSH/RTwin deployment and all PBS/Gaussian operations remain unauthorized.
