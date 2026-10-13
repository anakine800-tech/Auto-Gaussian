# Auto-G16 v3 Documentation Index

This page routes readers to the minimum authoritative material for a v3 task.
Do not recursively read all repository documentation or references by default.
Follow the authority order in [`AGENTS.md`](../../AGENTS.md); this index adds no
new authority and does not replace a current explicit Owner Gate.

| Need | Read |
| --- | --- |
| Accepted design decisions | [`OWNER_DECISIONS.md`](../../OWNER_DECISIONS.md) |
| Dated current integration status and separate production/science/live limits | [`STATUS.md`](STATUS.md) |
| General autonomy, stops and monitoring | [Autonomy Contract](AUTONOMOUS_DEVELOPMENT.md#autonomy-contract), [Execution and Monitoring Rules](AUTONOMOUS_DEVELOPMENT.md#execution-and-monitoring-rules) |
| Frozen surface-specific Task Contracts | [Frozen Post-Core Task Contracts](AUTONOMOUS_DEVELOPMENT.md#frozen-post-core-task-contracts) and the selected component's authority sources |
| Development operation order, validation, review and integration | [`development-handbook.md`](../development-handbook.md) |
| Capability reuse or rewrite disposition | [`reuse-adjudication.md`](reuse-adjudication.md) |
| Stable architecture boundaries and core objects | [`boundary-spec.md`](boundary-spec.md) |
| Explicitly excluded work | [`non-goals.md`](non-goals.md) |
| Versioned acceptance cases and expansion stops | [`acceptance.md`](acceptance.md) |
| Component-specific reading, code, and tests | [`context-map.toml`](../../config/context-map.toml) |

## Component contracts and rule owners

The boundary, acceptance and autonomy entry pages retain every original
heading fragment and route to the component that owns its complete text:

| Needed material | Reading entry |
| --- | --- |
| Runtime boundaries, exact records and safety contracts | [Boundary components](boundary-spec.md#component-reading-map) |
| Component acceptance and expansion stops | [Acceptance components](acceptance.md#component-reading-map) |
| Current autonomy rules and named frozen Task Contracts | [Autonomy rules](AUTONOMOUS_DEVELOPMENT.md#autonomy-contract) / [Task components](AUTONOMOUS_DEVELOPMENT.md#component-reading-map) |
| General development rules and their single owning section | [Rule ownership](../development-handbook.md#rule-ownership-and-references) |

`config/context-map.toml` points directly to the selected component sections.
Component pages retain their parent's authority; a shorter entry is not a
reduced contract. Frozen task-specific obligations and historical evidence
are not duplicate general rules to delete. The existing BUS/Executor material
and review thresholds are unchanged.

## Current rules and historical records

| Original entry / content | Where to read now | Treatment |
| --- | --- | --- |
| General autonomy, repair stops, concurrency, monitoring and handoff | [Autonomy](AUTONOMOUS_DEVELOPMENT.md#autonomy-contract), [execution rules](AUTONOMOUS_DEVELOPMENT.md#execution-and-monitoring-rules), [offline repair budget](AUTONOMOUS_DEVELOPMENT.md#ordinary-offline-repair-budget) and handbook [authorization](../development-handbook.md#development-authorization) / [live-evidence scope](../development-handbook.md#live-evidence-and-merge-scope) | Current general rules. The ordinary offline budget replaces only the general two-failure threshold for new tasks; stricter frozen task stops, review thresholds and scientific/operational gates remain. |
| Frozen post-Core technical contracts | Original named anchors under [Task Contracts](AUTONOMOUS_DEVELOPMENT.md#frozen-post-core-task-contracts), plus higher-priority authority | Still effective for their owned surfaces unless an explicit reviewed successor says otherwise. Completion alone does not revoke a contract. Exact bases, opening permissions and temporary sequencing are historical task context. |
| Former “current” post-foundation sequence | [Post-Core history](post-core-history.md#post-foundation-sequence-snapshot), linked from the original contract entry | Original text retained; no standing queue or implementation permission. |
| `V31-NIGHT-OFFLINE-CLOSEOUT-20260911` | [Original anchor](AUTONOMOUS_DEVELOPMENT.md#v31-night-offline-closeout-20260911) routes to [unchanged timed record](post-core-history.md#v31-night-offline-closeout-20260911) | Launch window expired; technical scope, invariants and safety/validation limits retained. #168 supplies the later integration disposition. |
| `V3-MAINT-TEST-01` selector expand-on-error clause | [Original entry and explicit supersession](AUTONOMOUS_DEVELOPMENT.md#v3-maint-test-01) | Only that clause is superseded by [V31-CHANGE-AWARE-VALIDATION-NO-ACCIDENTAL-FULL-01](AUTONOMOUS_DEVELOPMENT.md#v31-change-aware-validation-no-accidental-full-01), OD-08 and current handbook routing. No new selector semantics or waiver. |
| CI authority and monitoring policy formerly embedded among STATUS milestones | [Retained policy](STATUS.md#retained-ci-and-monitoring-policy) | Verbatim current entry retained, including the condition to re-evaluate after material CI configuration changes; remote settings were not reverified here. |
| Mixed V30/V31 status, old next gates, C2/C3/C4 and recovery checkpoints | [Unchanged status body at b5a27f4](status-history-through-20260916.md) | Historical observations, test/CI claims and permission statements retain their original scope. Current STATUS separately verifies #168 and #173–#175 integration. All former STATUS headings remain compatibility entries. |
| File-completion, publisher R4 and recovery evidence | [Freeze dossier](pbs-file-completion-freeze.md), [R4 dossier](publisher-r4/README.md), [C2 contract](same-attempt-collection-recovery-contract.md), with [later integration links](STATUS.md#verified-integration-evidence) | Original candidate hashes, negative evidence and earlier NOT_ACQUIRED/PARTIAL cutoffs are preserved. Later PR reports are attributed, not substituted for raw evidence or fresh qualification. |

The historical copies name their exact source commit/tree. Relocation does not
reopen a timed or completed authorization, mutate a Control Issue, reinterpret
a versioned schema, change validation selection, or grant operational authority.

## Historical status snapshot provenance

This is the status text retained from `STATUS.md` at
`b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58` (tree
`e499ddc3435976d7f2c4b2f5dfbe07b7eb6e5216`), before the 2026-09-22
maintenance separation. The [archived file](status-history-through-20260916.md) is byte-for-byte identical,
including its
mixed observation dates, pending labels, old next gates and CI claims. It is
not a fresh status audit. Original source:
[Git snapshot](https://github.com/anakine800-tech/Auto-Gaussian/blob/b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58/docs/v3/STATUS.md).

Use [current status](STATUS.md) for the verified integration cutoff and
[the documentation map](INDEX.md#current-rules-and-historical-records) to find
binding contracts. Archiving these observations neither repeals a technical
contract nor renews a historical permission. In particular, “Current”, “next”,
“authorized” and “PASS” in that file refer only to their original task/evidence scope.
The [CI and monitoring policy](STATUS.md#retained-ci-and-monitoring-policy) is
also retained verbatim at the current entry; archiving its surrounding
milestones does not retire it.
Later #168 and #173–#175 integration evidence is indexed in current status;
old scientific failures and incomplete observations remain historical evidence.

The archive retains its original title and relative links to preserve exact
source bytes. Read it through this historical entry; use STATUS for the dated
current integration view. No historical prose becomes a new instruction.
