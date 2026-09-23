# Auto-G16 v3 Boundary Specification

This document fixes stable dependency and data boundaries only. It does not
select implementation techniques.


## Component reading map

This entry and its linked component pages form the same versioned authority
document. The authority order in [AGENTS.md](../../AGENTS.md#version-and-authority-routing)
is unchanged. Read only the relevant component and its cited dependencies;
the split does not relax technical, safety, validation or review requirements.
Historical hashes and line-number citations still describe their original
commit, not these relocated bytes. The source ranges below refer to the
[pre-split snapshot](https://github.com/anakine800-tech/Auto-Gaussian/blob/394e88bbac54a15d42973cf8b607e515343b1814/docs/v3/boundary-spec.md).

| Component | Sections in the pre-split snapshot |
| --- | --- |
| [foundation](contracts/boundary/foundation.md) | L6–L128, L4293–L4316 |
| [approval](contracts/boundary/approval.md) | L129–L292 |
| [execution](contracts/boundary/execution.md) | L293–L538 |
| [result](contracts/boundary/result.md) | L539–L685, L1302–L1355 |
| [result-attribution](contracts/boundary/result-attribution.md) | L686–L1301 |
| [scientific-validation](contracts/boundary/scientific-validation.md) | L1356–L1825 |
| [review](contracts/boundary/review.md) | L1826–L2113 |
| [workflow](contracts/boundary/workflow.md) | L2114–L2350 |
| [observe](contracts/boundary/observe.md) | L2351–L2563 |
| [transport-composition](contracts/boundary/transport-composition.md) | L2564–L3003, L3629–L3718 |
| [transport-resources](contracts/boundary/transport-resources.md) | L3004–L3186, L4825–L4859 |
| [transport-bootstrap-v1](contracts/boundary/transport-bootstrap-v1.md) | L3187–L3628 |
| [transport-bootstrap](contracts/boundary/transport-bootstrap.md) | L3719–L4292 |
| [transport-ssh-config](contracts/boundary/transport-ssh-config.md) | L4317–L4506 |
| [transport-launcher](contracts/boundary/transport-launcher.md) | L4507–L4778 |
| [transport-proxyjump](contracts/boundary/transport-proxyjump.md) | L4779–L4824 |
| [v31-shared](contracts/boundary/v31-shared.md) | L4860–L5148 |
| [v31-offline](contracts/boundary/v31-offline.md) | L5149–L5190 |
| [v31-file-completion](contracts/boundary/v31-file-completion.md) | L5191–L5663 |
| [v31-controller-guard](contracts/boundary/v31-controller-guard.md) | L5664–L5848 |
| [v31-successors](contracts/boundary/v31-successors.md) | L5849–L5917 |

## Historical line-number references

The retained publisher design records cite the following lines at their original
base `3116d1f1919eff164ef3593171d0ed7f42c778b5`. Their historical text and hashes
are unchanged. Use the immutable snapshot to audit the old citation, and the
component link to read the corresponding current contract. The same passages
are present in the pre-split snapshot named above; old line numbers do not
refer to this shorter entry page.

| Original line citation | Immutable historical source | Current component section |
| --- | --- | --- |
| boundary:27-32 | [original L27–L32](https://github.com/anakine800-tech/Auto-Gaussian/blob/3116d1f1919eff164ef3593171d0ed7f42c778b5/docs/v3/boundary-spec.md#L27-L32) | [contract section](contracts/boundary/foundation.md#dependency-direction) |
| boundary:237-274 | [original L237–L274](https://github.com/anakine800-tech/Auto-Gaussian/blob/3116d1f1919eff164ef3593171d0ed7f42c778b5/docs/v3/boundary-spec.md#L237-L274) | [contract section](contracts/boundary/approval.md#v30-3a-frozen-approval-authority-contract) |
| boundary:5260-5276 | [original L5260–L5276](https://github.com/anakine800-tech/Auto-Gaussian/blob/3116d1f1919eff164ef3593171d0ed7f42c778b5/docs/v3/boundary-spec.md#L5260-L5276) | [contract section](contracts/boundary/v31-file-completion.md#publisher-trust-and-wrapper-ownership) |
| boundary:5277-5281 | [original L5277–L5281](https://github.com/anakine800-tech/Auto-Gaussian/blob/3116d1f1919eff164ef3593171d0ed7f42c778b5/docs/v3/boundary-spec.md#L5277-L5281) | [contract section](contracts/boundary/v31-file-completion.md#publisher-trust-and-wrapper-ownership) |

## Original section links

Existing fragment links remain valid below. Follow the linked heading for its
complete contract text; this list contains no replacement policy.

<a id="dependency-direction"></a>

- [Dependency Direction](contracts/boundary/foundation.md#dependency-direction)

<a id="core-objects"></a>

- [Core Objects](contracts/boundary/foundation.md#core-objects)

<a id="v30-core-01-runtime-contract"></a>

- [V30-CORE-01 Runtime Contract](contracts/boundary/foundation.md#v30-core-01-runtime-contract)

<a id="v30-3a-frozen-approval-authority-contract"></a>

- [V30-3A Frozen Approval Authority Contract](contracts/boundary/approval.md#v30-3a-frozen-approval-authority-contract)

<a id="scientific-approval"></a>

- [Scientific Approval](contracts/boundary/approval.md#scientific-approval)

<a id="batch-submit-approval"></a>

- [Batch Submit Approval](contracts/boundary/approval.md#batch-submit-approval)

<a id="exact-operational-confirmation"></a>

- [Exact Operational Confirmation](contracts/boundary/approval.md#exact-operational-confirmation)

<a id="effect-gate-replay-and-invalidation"></a>

- [Effect gate, replay, and invalidation](contracts/boundary/approval.md#effect-gate-replay-and-invalidation)

<a id="v30-exec-01-frozen-execution-contract"></a>

- [V30-EXEC-01 Frozen Execution Contract](contracts/boundary/execution.md#v30-exec-01-frozen-execution-contract)

<a id="package-placement-and-identity"></a>

- [Package placement and identity](contracts/boundary/execution.md#package-placement-and-identity)

<a id="serverprofile-resolution-and-immutable-bytes"></a>

- [ServerProfile resolution and immutable bytes](contracts/boundary/execution.md#serverprofile-resolution-and-immutable-bytes)

<a id="executionsnapshot-and-workspaces"></a>

- [ExecutionSnapshot and workspaces](contracts/boundary/execution.md#executionsnapshot-and-workspaces)

<a id="submission-and-effect-semantics"></a>

- [Submission and effect semantics](contracts/boundary/execution.md#submission-and-effect-semantics)

<a id="v30-result-01-frozen-result-provenance-contract"></a>

- [V30-RESULT-01 Frozen Result Provenance Contract](contracts/boundary/result.md#v30-result-01-frozen-result-provenance-contract)

<a id="deterministic-record-identities"></a>

- [Deterministic record identities](contracts/boundary/result.md#deterministic-record-identities)

<a id="envelope-parsing-and-durable-views"></a>

- [Envelope, parsing, and durable views](contracts/boundary/result.md#envelope-parsing-and-durable-views)

<a id="additive-gaussian-job-attribution-contract"></a>

- [Additive Gaussian job attribution contract](contracts/boundary/result-attribution.md#additive-gaussian-job-attribution-contract)

<a id="exact-byte-grammar-and-capability-boundary"></a>

- [Exact-byte grammar and capability boundary](contracts/boundary/result-attribution.md#exact-byte-grammar-and-capability-boundary)

<a id="primary-diagnostic-ownership-and-precedence"></a>

- [Primary diagnostic ownership and precedence](contracts/boundary/result-attribution.md#primary-diagnostic-ownership-and-precedence)

<a id="closed-attributed-facts-schema"></a>

- [Closed attributed facts schema](contracts/boundary/result-attribution.md#closed-attributed-facts-schema)

<a id="narrow-reuse-adjudication"></a>

- [Narrow reuse adjudication](contracts/boundary/result-attribution.md#narrow-reuse-adjudication)

<a id="composite-internal-step-gaussian-job-successor"></a>

- [Composite internal-step Gaussian job successor](contracts/boundary/result.md#composite-internal-step-gaussian-job-successor)

<a id="v30-min-validate-contract-01-minimum-scientific-validation-contract"></a>

- [V30-MIN-VALIDATE-CONTRACT-01 Minimum Scientific Validation Contract](contracts/boundary/scientific-validation.md#v30-min-validate-contract-01-minimum-scientific-validation-contract)

<a id="public-boundary-and-exact-provenance"></a>

- [Public boundary and exact provenance](contracts/boundary/scientific-validation.md#public-boundary-and-exact-provenance)

<a id="exact-public-shape-and-identity-constants"></a>

- [Exact public shape and identity constants](contracts/boundary/scientific-validation.md#exact-public-shape-and-identity-constants)

<a id="deterministic-attributed-evidence-selection"></a>

- [Deterministic attributed-evidence selection](contracts/boundary/scientific-validation.md#deterministic-attributed-evidence-selection)

<a id="v30-classification-policy"></a>

- [V3.0 classification policy](contracts/boundary/scientific-validation.md#v30-classification-policy)

<a id="identity-acceptance-and-persistence"></a>

- [Identity, acceptance, and persistence](contracts/boundary/scientific-validation.md#identity-acceptance-and-persistence)

<a id="reuse-disposition-and-non-goals"></a>

- [Reuse disposition and non-goals](contracts/boundary/scientific-validation.md#reuse-disposition-and-non-goals)

<a id="v30-review-min-contract-01-minimum-reviewbundle-contract"></a>

- [V30-REVIEW-MIN-CONTRACT-01 Minimum ReviewBundle Contract](contracts/boundary/review.md#v30-review-min-contract-01-minimum-reviewbundle-contract)

<a id="exact-public-boundary"></a>

- [Exact public boundary](contracts/boundary/review.md#exact-public-boundary)

<a id="deterministic-identity-and-rendering"></a>

- [Deterministic identity and rendering](contracts/boundary/review.md#deterministic-identity-and-rendering)

<a id="narrow-reuse-and-ownership-preparation"></a>

- [Narrow reuse and ownership preparation](contracts/boundary/review.md#narrow-reuse-and-ownership-preparation)

<a id="v30-wf-contract-01-frozen-minimal-workflow-contract"></a>

- [V30-WF-CONTRACT-01 Frozen Minimal Workflow Contract](contracts/boundary/workflow.md#v30-wf-contract-01-frozen-minimal-workflow-contract)

<a id="package-and-public-record-boundary"></a>

- [Package and public record boundary](contracts/boundary/workflow.md#package-and-public-record-boundary)

<a id="finite-graph-mapping-and-branch-semantics"></a>

- [Finite graph, mapping, and branch semantics](contracts/boundary/workflow.md#finite-graph-mapping-and-branch-semantics)

<a id="canonical-state-persistence-and-replay"></a>

- [Canonical state, persistence, and replay](contracts/boundary/workflow.md#canonical-state-persistence-and-replay)

<a id="authority-and-failure-boundaries"></a>

- [Authority and failure boundaries](contracts/boundary/workflow.md#authority-and-failure-boundaries)

<a id="narrow-reuse-boundary"></a>

- [Narrow reuse boundary](contracts/boundary/workflow.md#narrow-reuse-boundary)

<a id="v30-obs-min-contract-01-frozen-minimal-observe-contract"></a>

- [V30-OBS-MIN-CONTRACT-01 Frozen Minimal Observe Contract](contracts/boundary/observe.md#v30-obs-min-contract-01-frozen-minimal-observe-contract)

<a id="package-and-exact-public-inventory"></a>

- [Package and exact public inventory](contracts/boundary/observe.md#package-and-exact-public-inventory)

<a id="deterministic-identity-and-core-persistence"></a>

- [Deterministic identity and Core persistence](contracts/boundary/observe.md#deterministic-identity-and-core-persistence)

<a id="authority-replay-and-failure-boundaries"></a>

- [Authority, replay, and failure boundaries](contracts/boundary/observe.md#authority-replay-and-failure-boundaries)

<a id="narrow-reuse-adjudication-and-non-goals"></a>

- [Narrow reuse adjudication and non-goals](contracts/boundary/observe.md#narrow-reuse-adjudication-and-non-goals)

<a id="v30-exec-02-composition-contract-01-rtwin-first-composition-contract"></a>

- [V30-EXEC-02-COMPOSITION-CONTRACT-01 RTwin-First Composition Contract](contracts/boundary/transport-composition.md#v30-exec-02-composition-contract-01-rtwin-first-composition-contract)

<a id="single-effect-owner-and-rtwin-first-boundary"></a>

- [Single effect owner and RTwin-first boundary](contracts/boundary/transport-composition.md#single-effect-owner-and-rtwin-first-boundary)

<a id="exact-minimum-transport-public-inventory"></a>

- [Exact minimum Transport public inventory](contracts/boundary/transport-composition.md#exact-minimum-transport-public-inventory)

<a id="canonical-transport-evidence-identity"></a>

- [Canonical transport evidence identity](contracts/boundary/transport-composition.md#canonical-transport-evidence-identity)

<a id="snapshot-derived-pbs-resource-enactment"></a>

- [Snapshot-derived PBS resource enactment](contracts/boundary/transport-resources.md#snapshot-derived-pbs-resource-enactment)

<a id="exact-torque-610-production-dialect"></a>

- [Exact Torque 6.1.0 production dialect](contracts/boundary/transport-resources.md#exact-torque-610-production-dialect)

<a id="historical-bootstrap-1-source-controlled-operation-construction"></a>

- [Historical bootstrap /1 source-controlled operation construction](contracts/boundary/transport-bootstrap-v1.md#historical-bootstrap-1-source-controlled-operation-construction)

<a id="historical-bootstrap-1-canonical-deployment-manifest-vector"></a>

- [Historical bootstrap /1 canonical deployment-manifest vector](contracts/boundary/transport-bootstrap-v1.md#historical-bootstrap-1-canonical-deployment-manifest-vector)

<a id="historical-bootstrap-1-fixed-source-and-remote-shell-grammars"></a>

- [Historical bootstrap /1 fixed source and remote-shell grammars](contracts/boundary/transport-bootstrap-v1.md#historical-bootstrap-1-fixed-source-and-remote-shell-grammars)

<a id="observe-result-and-full-synthetic-composition"></a>

- [Observe, Result, and full synthetic composition](contracts/boundary/transport-composition.md#observe-result-and-full-synthetic-composition)

<a id="narrow-reuse-adjudication-and-follow-on-ownership"></a>

- [Narrow reuse adjudication and follow-on ownership](contracts/boundary/transport-composition.md#narrow-reuse-adjudication-and-follow-on-ownership)

<a id="v30-transport-bootstrap-chain-03-physical-and-bootstrap-authority-closeout"></a>

- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03 Physical and Bootstrap Authority Closeout](contracts/boundary/transport-bootstrap.md#v30-transport-bootstrap-chain-03-physical-and-bootstrap-authority-closeout)

<a id="public-surface-and-ownership"></a>

- [Public surface and ownership](contracts/boundary/transport-bootstrap.md#public-surface-and-ownership)

<a id="exact-threat-model"></a>

- [Exact threat model](contracts/boundary/transport-bootstrap.md#exact-threat-model)

<a id="exact-sqlite-schema-v1"></a>

- [Exact SQLite schema-v1](contracts/boundary/transport-bootstrap.md#exact-sqlite-schema-v1)

<a id="store-identity-and-replay"></a>

- [Store identity and replay](contracts/boundary/transport-bootstrap.md#store-identity-and-replay)

<a id="replacement-safe-remote-physical-authority"></a>

- [Replacement-safe remote physical authority](contracts/boundary/transport-bootstrap.md#replacement-safe-remote-physical-authority)

<a id="bootstrap-trust-and-fixed-command-construction"></a>

- [Bootstrap trust and fixed command construction](contracts/boundary/transport-bootstrap.md#bootstrap-trust-and-fixed-command-construction)

<a id="frozen-adversarial-implementation-matrix"></a>

- [Frozen adversarial implementation matrix](contracts/boundary/transport-bootstrap.md#frozen-adversarial-implementation-matrix)

<a id="context-boundaries"></a>

- [Context Boundaries](contracts/boundary/foundation.md#context-boundaries)

<a id="artifact-identity"></a>

- [Artifact Identity](contracts/boundary/foundation.md#artifact-identity)

<a id="v30-transport-ssh-config-effect-seam-01"></a>

- [V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01](contracts/boundary/transport-ssh-config.md#v30-transport-ssh-config-effect-seam-01)

<a id="exact-profile-bound-configuration-inventory"></a>

- [Exact profile-bound configuration inventory](contracts/boundary/transport-ssh-config.md#exact-profile-bound-configuration-inventory)

<a id="closed-ssh-config-grammar"></a>

- [Closed SSH config grammar](contracts/boundary/transport-ssh-config.md#closed-ssh-config-grammar)

<a id="exact-command-and-attestation-seam"></a>

- [Exact command and attestation seam](contracts/boundary/transport-ssh-config.md#exact-command-and-attestation-seam)

<a id="v30-transport-rtwin-launcher-chain-02-current-live-launch-contract"></a>

- [V30-TRANSPORT-RTWIN-LAUNCHER-CHAIN-02 current live-launch contract](contracts/boundary/transport-launcher.md#v30-transport-rtwin-launcher-chain-02-current-live-launch-contract)

<a id="v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01-boundary"></a>

- [V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01 boundary](contracts/boundary/transport-launcher.md#v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01-boundary)

<a id="v30-transport-agv3-eof-independent-forwarding-01-boundary"></a>

- [V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01 boundary](contracts/boundary/transport-launcher.md#v30-transport-agv3-eof-independent-forwarding-01-boundary)

<a id="v30-transport-windows-openssh-redirected-output-completion-contract-01-boundary"></a>

- [V30-TRANSPORT-WINDOWS-OPENSSH-REDIRECTED-OUTPUT-COMPLETION-CONTRACT-01 boundary](contracts/boundary/transport-launcher.md#v30-transport-windows-openssh-redirected-output-completion-contract-01-boundary)

<a id="v30-a-option1-mac-proxyjump-product-integration-01-boundary"></a>

- [V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01 boundary](contracts/boundary/transport-proxyjump.md#v30-a-option1-mac-proxyjump-product-integration-01-boundary)

<a id="scheduled-job-working-directory-enactment"></a>

- [Scheduled job working-directory enactment](contracts/boundary/transport-resources.md#scheduled-job-working-directory-enactment)

<a id="v31-shared-contract-01-shared-execution-and-ensemble-contract"></a>

- [V31-SHARED-CONTRACT-01 shared execution and ensemble contract](contracts/boundary/v31-shared.md#v31-shared-contract-01-shared-execution-and-ensemble-contract)

<a id="exact-change-disposition"></a>

- [Exact change disposition](contracts/boundary/v31-shared.md#exact-change-disposition)

<a id="project-first-use-physical-provisioning"></a>

- [Project first-use physical provisioning](contracts/boundary/v31-shared.md#project-first-use-physical-provisioning)

<a id="additive-versioned-multi-program-execution-successor"></a>

- [Additive versioned multi-program execution successor](contracts/boundary/v31-shared.md#additive-versioned-multi-program-execution-successor)

<a id="independent-samplingprofile-policy-record"></a>

- [Independent SamplingProfile policy record](contracts/boundary/v31-shared.md#independent-samplingprofile-policy-record)

<a id="conformerensemble-minimum-public-shape"></a>

- [ConformerEnsemble minimum public shape](contracts/boundary/v31-shared.md#conformerensemble-minimum-public-shape)

<a id="thermodynamicensemble-handoff"></a>

- [ThermodynamicEnsemble handoff](contracts/boundary/v31-shared.md#thermodynamicensemble-handoff)

<a id="zero-effect-and-compatibility-boundary"></a>

- [Zero-effect and compatibility boundary](contracts/boundary/v31-shared.md#zero-effect-and-compatibility-boundary)

<a id="v31-private-offline-closeout-boundary"></a>

- [V31 private offline closeout boundary](contracts/boundary/v31-offline.md#v31-private-offline-closeout-boundary)

<a id="v31-pbs-compat-file-completion-01-candidate-boundary"></a>

- [V31-PBS-COMPAT-FILE-COMPLETION-01 candidate boundary](contracts/boundary/v31-file-completion.md#v31-pbs-compat-file-completion-01-candidate-boundary)

<a id="mode-and-non-circular-execution-binding"></a>

- [Mode and non-circular execution binding](contracts/boundary/v31-file-completion.md#mode-and-non-circular-execution-binding)

<a id="publisher-trust-and-wrapper-ownership"></a>

- [Publisher trust and wrapper ownership](contracts/boundary/v31-file-completion.md#publisher-trust-and-wrapper-ownership)

<a id="closed-receipt-bytes-and-evidence-types"></a>

- [Closed receipt bytes and evidence types](contracts/boundary/v31-file-completion.md#closed-receipt-bytes-and-evidence-types)

<a id="acquisition-ordering-and-final-reduction"></a>

- [Acquisition, ordering and final reduction](contracts/boundary/v31-file-completion.md#acquisition-ordering-and-final-reduction)

<a id="operation-closure-and-dependency-direction"></a>

- [Operation closure and dependency direction](contracts/boundary/v31-file-completion.md#operation-closure-and-dependency-direction)

<a id="c3-rendering-material-supplement-candidate"></a>

- [C3 rendering-material supplement candidate](contracts/boundary/v31-file-completion.md#c3-rendering-material-supplement-candidate)

<a id="c4-native-controller-directory-guard-proposal"></a>

- [C4 native controller directory guard proposal](contracts/boundary/v31-controller-guard.md#c4-native-controller-directory-guard-proposal)

<a id="exact-delta-and-private-identity"></a>

- [Exact delta and private identity](contracts/boundary/v31-controller-guard.md#exact-delta-and-private-identity)

<a id="creation-opening-and-compatibility"></a>

- [Creation, opening and compatibility](contracts/boundary/v31-controller-guard.md#creation-opening-and-compatibility)

<a id="ownership-lifecycle-and-effect-ordering"></a>

- [Ownership, lifecycle and effect ordering](contracts/boundary/v31-controller-guard.md#ownership-lifecycle-and-effect-ordering)

<a id="v31-publisher-r4-private-offline-boundary"></a>

- [V31 publisher R4 private offline boundary](contracts/boundary/v31-successors.md#v31-publisher-r4-private-offline-boundary)

<a id="v31-same-attempt-collection-recovery-boundary"></a>

- [V31 same-Attempt collection recovery boundary](contracts/boundary/v31-successors.md#v31-same-attempt-collection-recovery-boundary)

<a id="v31-crest-completion-successor-boundary"></a>

- [V31 CREST completion successor boundary](contracts/boundary/v31-successors.md#v31-crest-completion-successor-boundary)

<a id="v31-exact-observed-job-recovery-boundary"></a>

- [V31 exact observed-job recovery boundary](contracts/boundary/v31-successors.md#v31-exact-observed-job-recovery-boundary)

<a id="v31-crest-short-entry-delivery-boundary"></a>

- [V31 CREST short-entry delivery boundary](contracts/boundary/v31-successors.md#v31-crest-short-entry-delivery-boundary)
