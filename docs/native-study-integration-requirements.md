# Auto-G16 study readonly integration requirements

Status: frontend requirements proposal, 2026-10-12. Not a frozen backend
contract, implemented API, deployment receipt or fresh-execution acceptance.
Continue the existing lifecycle/populations candidate in this isolated branch.
The parent owns actual study execution and recovery. This frontend owns only
trusted registration, public GET projection and display. Broader user authority
includes integration/deployment after joint version freeze, independent review
and required CI; it does not permit premature service switching.

## Current implementation and gaps

- `autog_frontend/api.py` forwards NativeQuery projects, attempts, detail,
  lifecycle, thermodynamics and populations. There is no public readonly study
  owner registered for frontend use or study HTTP route. The existing CLI query
  and legacy project-library groups are different interfaces.
- `native_sources.py` reads pinned startup /1–/5 registrations once. A page
  refresh does not discover new source registrations or replace pinned execution
  snapshots. The new study needs an explicit owner-controlled publication and
  read protocol for newly materialized stages, attempts and saved results.
- `NativePanel` shows source → Project → WorkflowRun → Task → Attempt. It does
  not show planned-but-unmaterialized stage slots, study edges or recovery.
  The global refresh button remounts the panel; it is not a recovery command.
- Current backend `study.service.operate` rejects `run` with
  `execution-contract-not-frozen`. Its implemented /1 response describes local
  creation and historical reuse, with a new PLANNED attempt and execution false.
  Its local Core section contains private physical bindings; this CLI response
  must not be forwarded wholesale to HTTP or rendered as JSON in the browser.
- Historical saved-result joint acceptance remains valid only for its pinned
  historical candidate. It cannot qualify new study progress or new execution.

## Required owner interface to freeze

Names below are proposed wire names for review. The backend must supply the
public owning methods/loaders, closed schemas, bounds, error mapping, example
fixtures and a frozen code identity before frontend implementation consumes them.
All successful DTOs must be detached after source locks and exit checks finish.

1. **Trusted study registry and discovery.** Register a bounded set of studies
   from operator-only configuration. Each public entry has a safe registry key,
   `study_id`, `project_id`, `workflow_run_id`, title, execution mode and current
   public revision. No browser-supplied path, command, driver or callback.
   Define how a newly created study becomes visible without relaxing /1–/5
   pins: either a new narrowly owned startup reader of an append-only manifest,
   or an explicitly installed new registry generation. Pick one and freeze it.
   Do not overwrite a historical registration or silently fall back to it.

2. **Small study overview.** Proposed GET `/api/v1/native/studies` and
   `/api/v1/native/studies/{study_id}`. Proposed schema
   `auto-g16-native-study-query/1`, envelope exactly `{schema,kind,data}`;
   kind `studies` or `study`. List data: `{items,sources,consistency}`; each
   source has availability and reason so unavailable is not an empty success.
   Detail data must bind `study_id`, project/run IDs, request digest, mode,
   `revision`, `as_of_event_id`, management state, ordered stages, edges,
   recovery state and the distinct completion/acceptance claims below.
   Final exact nested keys, allowed reason codes and maximum lengths are a
   backend contract deliverable, not permission for arbitrary nested JSON.
   List/overview must not trigger all expensive scientific readers each refresh.

3. **Stage identity and materialization.** Eight current roles are `xtb`,
   `crest`, `anti_opt`, `anti_freq`, `gauche_opt`, `gauche_freq`,
   `thermochemistry`, `populations`. Each stage needs a stable stage ID/role,
   dependencies, backend status and reason, materialization state,
   reserved identity slots separately from actual task/attempt IDs, current
   attempt selection and attempt history. Uncreated is not failed or queued.
   Thermochemistry/populations may be local derived-artifact stages: do not
   invent PBS jobs, Tasks or Attempts when their owner does not create them.
   All ordering and dependency edges come from the reviewed study plan, not
   array position, filename, timestamp or frontend inference.

4. **Attempt association and three independent axes.** Existing detail and
   lifecycle routes may be reused only when the study owner binds each attempt
   to its exact public source ID and registered snapshot. Specify whether new
   attempt DTOs extend the owner contract or use a new schema. Preserve raw
   Core state independently of program completion, PBS presence/state and
   collection. PLANNED, submit intent and UNKNOWN must remain meaningful before
   a job snapshot exists. A stage with no job is not a read failure. No inferred
   PBS R, observation timestamps, Gaussian termination or scientific success.
   Any changed lifecycle schema requires additive validation; historical /1
   closed validation must not be widened to accept future fields accidentally.

5. **Fresh execution versus historical reuse.** Freeze explicit study mode
   (proposed `fresh-execution` / `historical-reuse` / `mixed`) and origin per
   stage, attempt and result (proposed `new-execution` / `historical-reuse` /
   `new-derived` / `not-produced`). A new derived artifact must retain origins
   of every dependency. Expose current study IDs separately from original
   source Project/Run/Task/Attempt/result IDs and content hashes. A new local
   Project around old results remains reuse. Never relabel old attempts as new.
   Backend must supply evidence-bound `execution_performed`, stage completion,
   fresh-execution acceptance and scientific acceptance as separate claims.
   Unknown/unavailable claims stay explicit; UI never computes an E2E verdict.

6. **Revision and coherent refresh.** Freeze what `revision` identifies (e.g.
   committed study journal prefix), how clients request/read that revision,
   and how concurrent stage publication is detected. Multi-endpoint results
   must carry a comparable revision or exact immutable binding. Mixed revisions
   cannot yield a merged success screen. Return a stable conflict/busy response
   or explicitly independent snapshots; never substitute old success silently.
   Saved artifact and source-pair hashes remain the scientific binding checks.
   Reading during append/publication must never repair or complete a journal.

7. **Exception and recovery readout.** Expose a closed, public projection of
   failure domain, stable code, unresolved stage/attempt, last committed event,
   recovery state and evidence references. Distinguish busy/source-unavailable,
   invalid evidence, initialization unresolved, submission unknown, missing
   collection and process failure. A recovery proposal is not a recovery receipt.
   Actual successful/failed recovery needs owner event identity and unchanged
   attempt/submission binding where applicable. No browser recovery/submit/
   cancel/reconcile action or automatic retry. Owner guidance may be shown as
   text only, without paths, commands, exception strings or sensitive receipts.

8. **Saved result links.** Stages must provide exact source/attempt/member and
   saved artifact associations for existing Opt/Freq, thermodynamics and
   populations panels, plus unavailable reasons before publication. Reuse the
   existing closed result DTOs; do not compute G, ΔG, populations, eligibility,
   ensemble selection or chemistry in the frontend. Lifecycle/status should be
   usable even when a scientific result reader fails or is not yet available.

## Refresh and HTTP behavior proposed for first implementation

- Preserve GET-only boundary, auth/origin checks, no-store, response caps,
  token/navigation isolation and safe error DTOs. Do not call study CLI through
  subprocess; consume an explicit readonly backend owner from trusted registry.
- Start with explicit manual refresh. Display last successfully read revision
  and local read time labelled as client time, not calculation observation time.
  Failed refresh shows the failure and clearly marks retained data as previous;
  it never preserves a current-success badge. Unknown schema fails closed.
- Keep the page-wide two-request budget and 120-second scientific-read deadline.
  A timed-out browser request does not prove server cancellation. Shared source
  locks may require serial scientific reads; the frozen backend must state
  concurrency/cost limits before automatic polling is considered. No periodic
  deep reads or automatic error retry is introduced by this proposal.
- Existing `#/native` and legacy archive routes remain intact. Proposed study
  list/detail routes are `#/studies` and `#/studies/{study_id}`, linked from the
  native projects entry. A prominent origin label and stage list are required.
  The legacy “new calculation” entry is not the new direct-backend executor;
  readonly deployment must not enable legacy task submission options.

## Freeze deliverables and blockers

| ID | Owner deliverable | What it blocks |
|---|---|---|
| B1 | Public study readonly owner + exact DTO schemas/fixtures | HTTP projection, browser decoding and stage UI |
| B2 | Registry discovery/publication protocol and stable revision semantics | New studies, refresh, consistent multi-stage display |
| B3 | Actual-run stage/attempt/source mappings and explicit result origins | New execution versus reuse evidence |
| B4 | Public exception/recovery codes and receipts, no-effect query guarantee | Failure/restart/recovery display |
| B5 | Frozen backend commit/tree or candidate manifest; installable artifact and dependency identity | Joint tests, CI backend pin and release build |
| B6 | Frontend publication repository/remote and required CI/branch protection identity | Push/PR/merge; this checkout currently has no Git remote |
| B7 | Reviewed joint deployment entry, config, rollback and source registry identities | Installation/service switch and new-study browser acceptance |

Current CI backend pin is `afffc8c578fa541c8af1d9af39e861146e399b4d`;
README still names `e0d239e41529649e25610eef6312d69714cf44e5`; locally reviewed
evolving backend is based on `b4c7ccb5faab0bb412946c226e834c196068e826`.
These are different identities. Do not update a CI pin to an uncommitted tree
or treat old CI as validating a new study owner. Align README/pin/artifacts
after joint freeze. The distribution version alone is not sufficient.

## Validation and acceptance ladder

1. Closed public DTO unit/HTTP tests: extra/private fields, cross-study/source/
   attempt mismatch, duplicate IDs, uncreated slots, errors versus unavailable,
   revisions, old /1–/5 compatibility and GET-only mutation tripwires.
2. Synthetic browser scenarios: initial Project, planned stages, queued/running,
   program/PBS/collection divergence, partial result publication, UNKNOWN,
   failed read, explicit refresh, late response after navigation/token change,
   restart with stable IDs, recovery pending/completed and mixed origins.
3. Exact backend candidate registry→owner→HTTP integration using synthetic
   stores; no builder/saver/remote effects during reads. Preserve failures.
4. Independent review and mandatory CI on frozen frontend/backend versions;
   source review, CI success, installation and scientific acceptance recorded
   separately. Integration authorization is already present; prerequisites
   remain unsatisfied until evidenced.
5. Parent-owned new butane execution, followed through the installed readonly
   entry from new Project and materialized stages to saved results, including
   approved failure/recovery scenarios. Bind input/plan/attempt/job/artifact
   IDs and versions. Do not rerun calculations from this frontend task or use
   the old historical preview PASS as evidence for this final acceptance.

Preparatory repair: CI now selects `native-reliability.spec.ts` alongside the
existing synthetic suites. No study routes, speculative DTO adapters, execution
controls or scientific algorithms are implemented before owner freeze.
