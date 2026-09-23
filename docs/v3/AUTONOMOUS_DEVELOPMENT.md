# Auto-G16 v3 Autonomous Development

This page separates current general autonomy rules from frozen Task Contracts
and links historical planning/launch records. It does
not replace [`AGENTS.md`](../../AGENTS.md) or the
[`development handbook`](../development-handbook.md), change a public
contract, or authorize implementation, integration, live work, or deployment.

## Autonomy Contract

| Class | Autonomous breakdown | Modification boundary | Validation, review, and handoff | Stop and request Owner |
| --- | --- | --- | --- | --- |
| `OWNER-GUIDED` | Break the named task into analysis, implementation, and validation checkpoints only; do not create another lane. | Change only owner-approved paths and behavior inside the frozen Task Contract. | Use focused/affected feedback, author findings-first review, then the named Owner or independent gate; hand off each boundary decision. | When a public contract, schema, invariant, security/live boundary, dependency or scope decision is missing or would differ from the approved Task Contract; also on any general stop below. |
| `BOUNDED-AUTONOMOUS` | Split independently testable work inside the frozen outcome and scope, subject to the global workstream limit. | Make the smallest coherent changes expressly allowed by the Task Contract; no adjacent cleanup or new framework. | Use focused/affected feedback and author findings-first review; freeze one candidate for independent review and Integration Owner handoff. | When the contract no longer determines a safe choice, a boundary would change, the scope would expand, or any general stop applies. |
| `MAINTENANCE` | Diagnose and apply a minimal behavior-preserving repair within the named maintenance boundary. | Documentation, compatibility, dependency, security, or release hygiene only where intended behavior is already explicit. | Reproduce where applicable, validate the changed and affected surface, self-review, and hand off residual risk. | If intended behavior is unclear, product behavior would change, or a security/live semantic would be weakened or redefined. |

An autonomy class alone grants no push, PR, merge or operational authority.
Use the handbook's [Development authorization](../development-handbook.md#development-authorization)
for the exact authorized steps, retained permission and escalation rules, and
its [task classification](../development-handbook.md#1-classify-the-task-before-changing-files)
for the separate operational and scientific gates.

## Execution and Monitoring Rules

- Stop and request Owner when a required contract is missing or conflicts with
  another contract; do not guess the missing API, schema, field, invariant,
  dependency, test, or acceptance rule.
- Stop before an unapproved change to a public API, schema, invariant, security
  or live boundary, required check, workflow contract, or branch protection.
  An explicitly approved change still follows its named contract freeze,
  independent review and implementation gates; do not ask for the same
  decision again or infer that a planning gate authorizes implementation.
- Stop when scope or dependencies must expand. For an ordinary offline repair,
  use the [bounded diagnostic budget](#ordinary-offline-repair-budget) instead
  of the former general two-failure threshold. Preserve stricter task-specific
  stops and all scientific, live, BUS and uncertainty boundaries.
- Maximum parallelism is three workstreams. The Integration Owner alone merges
  or integrates them, serially. Planning does not create a fourth workstream.
- GitHub timestamps ending in `Z` are UTC; convert them to the Owner's local
  time in Owner-facing reports. Report only a state change, anomaly, or terminal
  state. No-change polling is silent.
- `running` is not `failed`. A slow runner or harness that is still running must
  not be failed, rerun, or given an unapproved timeout.
- Follow the handbook's [validation ladder and deduplication](../development-handbook.md#6-validation-ladder-and-deduplication)
  for focused feedback, full-validation ownership and reuse of frozen evidence.
- Every handoff is compact and contains: `task`, `base`, `head`, `scope`,
  `autonomy`, `status`, `findings`, `validation`, `blocker`, and `next gate`.

### Ordinary offline repair budget

For new ordinary offline repairs whose intended behavior is already defined
by the approved task contract, record a default budget of **four repair cycles
or 30 minutes of active diagnosis/editing, whichever is reached first**.
A cycle states one hypothesis,
makes its bounded repair and runs the relevant check; record the evidence and
remaining budget. Stop further diagnosis/editing at the active-time limit and
do not start another cycle after the recorded count is exhausted if the
problem remains unresolved. An Owner may explicitly set a different finite
budget at intake or approve an extension after reviewing the evidence.

Waiting for an already-running test, CI, or Owner reply does not consume active
diagnosis time. This is not a test timeout: let a running check finish under
its existing policy, and reuse its result. Successful repair proceeds to the
required validation/review; required checks are not skipped to fit the budget.
Do not repeat a failed approach without new evidence or a changed hypothesis.
Missing authority, contract conflict, identity drift or scope expansion stops
immediately, even with budget remaining.

Count across the task's related failures, turns and handoffs; record consumed
cycles/time rather than resetting them for a new error label or process.
Exhaustion requires an Owner decision before further repair. This replaces
only the general two-failure rule for these new tasks: explicit two-failure
stops in frozen Task Contracts remain until separately superseded. It grants
no automatic BUS restart/FIX, remote-operation retry, additional submission
or scientific-method change. Real `UNKNOWN` remains reconciliation-only with
no automatic retry; no diagnostic budget can reopen a consumed Attempt.

## Frozen Post-Core Task Contracts

Read the linked component sections as frozen, surface-specific contracts, not a current
execution queue. Closing a task does not retire its technical invariants,
compatibility requirements, validation obligations or review thresholds.
Opening gates, exact historical bases, temporary scope and then-current next
steps record their original tasks; they do not authorize a new task or resume
a completed one. Use [STATUS](STATUS.md) for verified integration evidence and
the current explicit Owner Gate for any new action.

| Material | Role and entry |
| --- | --- |
| General autonomy, stop, monitoring and handoff rules | [Autonomy Contract](#autonomy-contract) and [Execution and Monitoring Rules](#execution-and-monitoring-rules), with the [handbook](../development-handbook.md) operation order. |
| Frozen technical Task Contracts | The named component sections and their higher-priority Owner/boundary/acceptance sources; existing anchors are retained. |
| Former “current” post-foundation sequence | [Unchanged planning snapshot](post-core-history.md#post-foundation-sequence-snapshot); no longer the current work queue. |
| Night instruction with a 2026-09-11 deadline | [Original scope, window and invariants](post-core-history.md#v31-night-offline-closeout-20260911); later integration is recorded in STATUS. |
| Superseded selector error clause | [V3-MAINT-TEST-01 entry](#v3-maint-test-01) explicitly routes to its reviewed successor; unaffected requirements remain. |
| C2/C3/C4 proposal and recovery checkpoints | Their original contract text remains in the linked component sections; [current integration evidence](STATUS.md#verified-integration-evidence) separates those checkpoints from later #173–#175 integration. |


## Component reading map

This entry and its linked component pages form the same versioned authority
document. The authority order in [AGENTS.md](../../AGENTS.md#version-and-authority-routing)
is unchanged. Read only the relevant component and its cited dependencies;
the split does not relax technical, safety, validation or review requirements.
Historical hashes and line-number citations still describe their original
commit, not these relocated bytes. The source ranges below refer to the
[pre-split snapshot](https://github.com/anakine800-tech/Auto-Gaussian/blob/394e88bbac54a15d42973cf8b607e515343b1814/docs/v3/AUTONOMOUS_DEVELOPMENT.md).

| Component | Sections in the pre-split snapshot |
| --- | --- |
| [validation](contracts/tasks/validation.md) | L100–L196 |
| [execution](contracts/tasks/execution.md) | L197–L221, L410–L453 |
| [result](contracts/tasks/result.md) | L222–L247, L292–L367 |
| [workflow](contracts/tasks/workflow.md) | L248–L291 |
| [scientific-validation](contracts/tasks/scientific-validation.md) | L368–L409 |
| [transport-bootstrap](contracts/tasks/transport-bootstrap.md) | L454–L533 |
| [transport](contracts/tasks/transport.md) | L534–L717 |
| [v31-shared](contracts/tasks/v31-shared.md) | L718–L765 |
| [v31-file-completion](contracts/tasks/v31-file-completion.md) | L766–L884 |
| [v31-successors](contracts/tasks/v31-successors.md) | L885–L950 |

## Original section links

Existing fragment links remain valid below. Follow the linked heading for its
complete contract text; this list contains no replacement policy.

<a id="v31-night-offline-closeout-20260911"></a>

- [V31-NIGHT-OFFLINE-CLOSEOUT-20260911](contracts/tasks/validation.md#v31-night-offline-closeout-20260911)

<a id="v31-change-aware-validation-no-accidental-full-01"></a>

- [V31-CHANGE-AWARE-VALIDATION-NO-ACCIDENTAL-FULL-01](contracts/tasks/validation.md#v31-change-aware-validation-no-accidental-full-01)

<a id="v3-maint-test-01"></a>

- [V3-MAINT-TEST-01](contracts/tasks/validation.md#v3-maint-test-01)

<a id="v30-exec-01"></a>

- [V30-EXEC-01](contracts/tasks/execution.md#v30-exec-01)

<a id="v30-result-01"></a>

- [V30-RESULT-01](contracts/tasks/result.md#v30-result-01)

<a id="v30-wf-contract-01"></a>

- [V30-WF-CONTRACT-01](contracts/tasks/workflow.md#v30-wf-contract-01)

<a id="v30-result-section-attribution-contract-01"></a>

- [V30-RESULT-SECTION-ATTRIBUTION-CONTRACT-01](contracts/tasks/result.md#v30-result-section-attribution-contract-01)

<a id="v30-a-gaussian-optfreq-composite-job-result-contract-parser-repair-01"></a>

- [V30-A-GAUSSIAN-OPTFREQ-COMPOSITE-JOB-RESULT-CONTRACT-PARSER-REPAIR-01](contracts/tasks/result.md#v30-a-gaussian-optfreq-composite-job-result-contract-parser-repair-01)

<a id="v30-min-validate-contract-01"></a>

- [V30-MIN-VALIDATE-CONTRACT-01](contracts/tasks/scientific-validation.md#v30-min-validate-contract-01)

<a id="v30-exec-02"></a>

- [V30-EXEC-02](contracts/tasks/execution.md#v30-exec-02)

<a id="v30-transport-bootstrap-chain-03"></a>

- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03](contracts/tasks/transport-bootstrap.md#v30-transport-bootstrap-chain-03)

<a id="v30-exec-resource-enactment-contract-01"></a>

- [`V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`](contracts/tasks/transport.md#v30-exec-resource-enactment-contract-01)

<a id="v30-pbs-torque-dialect-01"></a>

- [`V30-PBS-TORQUE-DIALECT-01`](contracts/tasks/transport.md#v30-pbs-torque-dialect-01)

<a id="v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01"></a>

- [`V30-TRANSPORT-RTWIN-LAUNCHER-MULTILINE-BOOTSTRAP-QUOTING-REPAIR-01`](contracts/tasks/transport.md#v30-transport-rtwin-launcher-multiline-bootstrap-quoting-repair-01)

<a id="v30-transport-agv3-eof-independent-forwarding-01"></a>

- [`V30-TRANSPORT-AGV3-EOF-INDEPENDENT-FORWARDING-01`](contracts/tasks/transport.md#v30-transport-agv3-eof-independent-forwarding-01)

<a id="v30-a-option1-mac-proxyjump-product-integration-01"></a>

- [`V30-A-OPTION1-MAC-PROXYJUMP-PRODUCT-INTEGRATION-01`](contracts/tasks/transport.md#v30-a-option1-mac-proxyjump-product-integration-01)

<a id="v30-exec-pbs-workdir-enactment-contract-01"></a>

- [V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01](contracts/tasks/transport.md#v30-exec-pbs-workdir-enactment-contract-01)

<a id="v31-shared-contract-01"></a>

- [V31-SHARED-CONTRACT-01](contracts/tasks/v31-shared.md#v31-shared-contract-01)

<a id="v31-pbs-compat-file-completion-01"></a>

- [V31-PBS-COMPAT-FILE-COMPLETION-01](contracts/tasks/v31-file-completion.md#v31-pbs-compat-file-completion-01)

<a id="c3-material-derivation-checkpoint"></a>

- [C3 material-derivation checkpoint](contracts/tasks/v31-file-completion.md#c3-material-derivation-checkpoint)

<a id="authorized-ab-follow-up-and-proposed-c4-activation"></a>

- [Authorized A/B follow-up and proposed C4 activation](contracts/tasks/v31-file-completion.md#authorized-ab-follow-up-and-proposed-c4-activation)

<a id="v31-publisher-r4-offline-implementation-01"></a>

- [V31-PUBLISHER-R4-OFFLINE-IMPLEMENTATION-01](contracts/tasks/v31-successors.md#v31-publisher-r4-offline-implementation-01)

<a id="v31-same-attempt-collect-recovery-01"></a>

- [V31-SAME-ATTEMPT-COLLECT-RECOVERY-01](contracts/tasks/v31-successors.md#v31-same-attempt-collect-recovery-01)

<a id="v31-crest-live-closure-01"></a>

- [V31-CREST-LIVE-CLOSURE-01](contracts/tasks/v31-successors.md#v31-crest-live-closure-01)

<a id="v31-crest-695-markerless-recovery-01"></a>

- [V31-CREST-695-MARKERLESS-RECOVERY-01](contracts/tasks/v31-successors.md#v31-crest-695-markerless-recovery-01)
