# Auto-G16 v3 Acceptance Cases

These are feature-expansion stop conditions, not authority for a live run.


## Component reading map

This entry and its linked component pages form the same versioned authority
document. The authority order in [AGENTS.md](../../AGENTS.md#version-and-authority-routing)
is unchanged. Read only the relevant component and its cited dependencies;
the split does not relax technical, safety, validation or review requirements.
Historical hashes and line-number citations still describe their original
commit, not these relocated bytes. The source ranges below refer to the
[pre-split snapshot](https://github.com/anakine800-tech/Auto-Gaussian/blob/394e88bbac54a15d42973cf8b607e515343b1814/docs/v3/acceptance.md).

| Component | Sections in the pre-split snapshot |
| --- | --- |
| [core](contracts/acceptance/core.md) | L5–L71 |
| [approval](contracts/acceptance/approval.md) | L72–L140 |
| [execution](contracts/acceptance/execution.md) | L141–L179 |
| [result](contracts/acceptance/result.md) | L180–L501 |
| [scientific-validation](contracts/acceptance/scientific-validation.md) | L502–L654, L1521–L1529 |
| [review](contracts/acceptance/review.md) | L655–L795 |
| [workflow](contracts/acceptance/workflow.md) | L796–L929 |
| [observe](contracts/acceptance/observe.md) | L930–L1025 |
| [transport-composition](contracts/acceptance/transport-composition.md) | L1026–L1162 |
| [transport-bootstrap](contracts/acceptance/transport-bootstrap.md) | L1163–L1390 |
| [transport-resources](contracts/acceptance/transport-resources.md) | L1391–L1520, L1931–L1961 |
| [v31-ensemble](contracts/acceptance/v31-ensemble.md) | L1530–L1632 |
| [reaction](contracts/acceptance/reaction.md) | L1633–L1641 |
| [transport-launcher](contracts/acceptance/transport-launcher.md) | L1642–L1881 |
| [transport-proxyjump](contracts/acceptance/transport-proxyjump.md) | L1882–L1930 |
| [v31-offline](contracts/acceptance/v31-offline.md) | L1962–L2007 |
| [v31-file-completion](contracts/acceptance/v31-file-completion.md) | L2008–L2091 |
| [v31-successors](contracts/acceptance/v31-successors.md) | L2092–L2154 |

## Original section links

Existing fragment links remain valid below. Follow the linked heading for its
complete contract text; this list contains no replacement policy.

<a id="v30-core-01-clean-runtime-core"></a>

- [V30-CORE-01: Clean Runtime Core](contracts/acceptance/core.md#v30-core-01-clean-runtime-core)

<a id="v30-3a-approval-authority-and-invalidation-contract"></a>

- [V30-3A: Approval Authority and Invalidation Contract](contracts/acceptance/approval.md#v30-3a-approval-authority-and-invalidation-contract)

<a id="v30-exec-01-frozen-offline-execution-boundary"></a>

- [V30-EXEC-01: Frozen Offline Execution Boundary](contracts/acceptance/execution.md#v30-exec-01-frozen-offline-execution-boundary)

<a id="v30-result-01-frozen-result-provenance-boundary"></a>

- [V30-RESULT-01: Frozen Result Provenance Boundary](contracts/acceptance/result.md#v30-result-01-frozen-result-provenance-boundary)

<a id="v30-result-section-attribution-additive-gaussian-job-facts"></a>

- [V30-RESULT-SECTION-ATTRIBUTION: Additive Gaussian Job Facts](contracts/acceptance/result.md#v30-result-section-attribution-additive-gaussian-job-facts)

<a id="v30-a-gaussian-optfreq-composite-job-result-successor"></a>

- [V30-A Gaussian Opt/Freq Composite Job Result Successor](contracts/acceptance/result.md#v30-a-gaussian-optfreq-composite-job-result-successor)

<a id="v30-min-validate-contract-01-minimum-scientific-validation"></a>

- [V30-MIN-VALIDATE-CONTRACT-01: Minimum Scientific Validation](contracts/acceptance/scientific-validation.md#v30-min-validate-contract-01-minimum-scientific-validation)

<a id="v30-review-min-contract-01-minimum-deterministic-reviewbundle"></a>

- [V30-REVIEW-MIN-CONTRACT-01: Minimum Deterministic ReviewBundle](contracts/acceptance/review.md#v30-review-min-contract-01-minimum-deterministic-reviewbundle)

<a id="v30-wf-contract-01-minimal-deterministic-workflow"></a>

- [V30-WF-CONTRACT-01: Minimal Deterministic Workflow](contracts/acceptance/workflow.md#v30-wf-contract-01-minimal-deterministic-workflow)

<a id="v30-obs-min-contract-01-minimal-read-only-observe"></a>

- [V30-OBS-MIN-CONTRACT-01: Minimal Read-Only Observe](contracts/acceptance/observe.md#v30-obs-min-contract-01-minimal-read-only-observe)

<a id="v30-exec-02-composition-contract-01-rtwin-first-v30-a-composition"></a>

- [V30-EXEC-02-COMPOSITION-CONTRACT-01: RTwin-First V30-A Composition](contracts/acceptance/transport-composition.md#v30-exec-02-composition-contract-01-rtwin-first-v30-a-composition)

<a id="v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain"></a>

- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03: Deployment Manifest and Closed Command Chain](contracts/acceptance/transport-bootstrap.md#v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain)

<a id="v30-transport-bootstrap-source-clarify-01"></a>

- [`V30-TRANSPORT-BOOTSTRAP-SOURCE-CLARIFY-01`](contracts/acceptance/transport-bootstrap.md#v30-transport-bootstrap-source-clarify-01)

<a id="v30-exec-resource-enactment-contract-01"></a>

- [`V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`](contracts/acceptance/transport-resources.md#v30-exec-resource-enactment-contract-01)

<a id="v30-pbs-torque-dialect-01-exact-production-torque-renderer"></a>

- [`V30-PBS-TORQUE-DIALECT-01`: exact production Torque renderer](contracts/acceptance/transport-resources.md#v30-pbs-torque-dialect-01-exact-production-torque-renderer)

<a id="v30-closed-shell-minimum"></a>

- [v3.0: Closed-Shell Minimum](contracts/acceptance/scientific-validation.md#v30-closed-shell-minimum)

<a id="v31-flexible-molecule-ensemble"></a>

- [v3.1: Flexible-Molecule Ensemble](contracts/acceptance/v31-ensemble.md#v31-flexible-molecule-ensemble)

<a id="v32a-representative-reaction"></a>

- [v3.2a: Representative Reaction](contracts/acceptance/reaction.md#v32a-representative-reaction)

<a id="v30-transport-ssh-config-effect-seam-01-acceptance"></a>

- [V30-TRANSPORT-SSH-CONFIG-EFFECT-SEAM-01 acceptance](contracts/acceptance/transport-launcher.md#v30-transport-ssh-config-effect-seam-01-acceptance)

<a id="v30-transport-rtwin-launcher-chain-02-acceptance"></a>

- [V30-TRANSPORT-RTWIN-LAUNCHER-CHAIN-02 acceptance](contracts/acceptance/transport-launcher.md#v30-transport-rtwin-launcher-chain-02-acceptance)

<a id="v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01-acceptance"></a>

- [V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01 acceptance](contracts/acceptance/transport-launcher.md#v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01-acceptance)

<a id="v30-transport-agv3-eof-independent-forwarding-01-acceptance"></a>

- [V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01 acceptance](contracts/acceptance/transport-launcher.md#v30-transport-agv3-eof-independent-forwarding-01-acceptance)

<a id="v30-transport-windows-openssh-redirected-output-completion-contract-01-acceptance"></a>

- [V30-TRANSPORT-WINDOWS-OPENSSH-REDIRECTED-OUTPUT-COMPLETION-CONTRACT-01 acceptance](contracts/acceptance/transport-launcher.md#v30-transport-windows-openssh-redirected-output-completion-contract-01-acceptance)

<a id="v30-a-option1-mac-proxyjump-product-integration-01-acceptance"></a>

- [V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01 acceptance](contracts/acceptance/transport-proxyjump.md#v30-a-option1-mac-proxyjump-product-integration-01-acceptance)

<a id="v30-exec-pbs-workdir-enactment-contract-01"></a>

- [V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01](contracts/acceptance/transport-resources.md#v30-exec-pbs-workdir-enactment-contract-01)

<a id="v31-private-offline-closeout-acceptance"></a>

- [V31 private offline closeout acceptance](contracts/acceptance/v31-offline.md#v31-private-offline-closeout-acceptance)

<a id="v31-pbs-compat-file-completion-01-candidate-acceptance"></a>

- [V31-PBS-COMPAT-FILE-COMPLETION-01 candidate acceptance](contracts/acceptance/v31-file-completion.md#v31-pbs-compat-file-completion-01-candidate-acceptance)

<a id="c3-rendering-material-candidate-vectors"></a>

- [C3 rendering-material candidate vectors](contracts/acceptance/v31-file-completion.md#c3-rendering-material-candidate-vectors)

<a id="c4-native-controller-guard-proposed-vectors"></a>

- [C4 native controller guard proposed vectors](contracts/acceptance/v31-file-completion.md#c4-native-controller-guard-proposed-vectors)

<a id="v31-publisher-r4-offline-acceptance"></a>

- [V31 publisher R4 offline acceptance](contracts/acceptance/v31-successors.md#v31-publisher-r4-offline-acceptance)

<a id="v31-same-attempt-collection-recovery-acceptance"></a>

- [V31 same-Attempt collection recovery acceptance](contracts/acceptance/v31-successors.md#v31-same-attempt-collection-recovery-acceptance)

<a id="v31-crest-completion-successor-acceptance"></a>

- [V31 CREST completion successor acceptance](contracts/acceptance/v31-successors.md#v31-crest-completion-successor-acceptance)

<a id="v31-exact-observed-job-recovery-acceptance"></a>

- [V31 exact observed-job recovery acceptance](contracts/acceptance/v31-successors.md#v31-exact-observed-job-recovery-acceptance)

<a id="v31-crest-short-entry-delivery-acceptance"></a>

- [V31 CREST short-entry delivery acceptance](contracts/acceptance/v31-successors.md#v31-crest-short-entry-delivery-acceptance)
