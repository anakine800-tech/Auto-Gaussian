# Auto-G16 native read-only query candidate

Task: V31-NATIVE-READONLY-QUERY-01.
Class: feature development, BOUNDED-AUTONOMOUS. Base/HEAD at intake:
`0babf19a72d53c417e04df147c1aca77004f45b1`; clean linked worktree;
branch `codex/v31-native-readonly-query`. Startup preflight passed (7 checks).

## Current authorization and delivery scope

Owner authorized implementation, offline validation, isolated local preview,
read-only comparison with explicitly configured existing sources, and then
local commit freeze, formal integration validation and local installation
preparation. A local frontend switch is authorized only after the applicable
formal integration gates pass. Push and updates to the same Draft PR are authorized; merge remains unapproved;
required PR-owned full validation cannot be replaced by a local full run.
No SSH, new monitor, scheduler, execution provider, business/approval migration,
scientific execution or parsing on reads is authorized.

The source-candidate implementation and bounded acceptance are complete.
`ProgramReadQuery` supplies the owning detached native reader described below;
exact query validation ownership exists. Clean commit selection, required CI,
integration and installed acceptance are distinct subsequent evidence gates.

The private ledger retains the prior cumulative ten repair cycles and failed
integration evidence. Owner subsequently approved at most four new cycles or
30 active diagnosis/editing minutes to correct three exact CI failures, review
the actual increment, create a successor commit, update the same Draft PR and
run its prescribed CI once. Test, CI and independent-review waiting is excluded;
unused browser-diagnostic allowance is not pooled into this scope. The three
repairs are conservative document routing, OD-35's exact downstream Observe
consumer, and fault injection at the real read-only schema validation entry.
No runtime implementation change is required by these repairs.

## Narrow contract and reuse

PORT the installed query candidate's `auto_g16/query/{models,service,__init__}.py`,
Result-owned `GaussianResultQuery`, and Core's public `read_snapshot` plus four
enumerators from wheel SHA-256
`3c42840fdd740f45c31edbecabbf53b18b140f02e04a5462feb0fcfb3e78e5e4`.
The Core delta is additive, no schema/data migration; it separates readonly
schema validation from constructor initialization. It requires Core boundary
review before integration. Result query reuse requires Result domain review.
Existing V30 `auto-g16-query/1` and `gaussian-result-summary/1` DTOs retain shape.
The first source preview used frontend commit
`33e1da1427f130a1c585ee26d28730f70d3b2efc`. Installation preparation must port only
the needed increment onto the currently accepted frontend commit, rebind its
actual loader and preserve all existing navigation, drafts and local data.
A prior frontend archive is not authority to replace a newer installation.

Add `NativeQueryService` with immutable startup `NativeSource` registrations
(source alias + canonical absolute Core database path). Filesystem source
locators cross HTTP only as aliases; normal domain record IDs remain visible. No directory discovery, caller paths, implicit newest source, cross-store
joins or archive/native identity conflation. Duplicate aliases/paths fail.
One source failure is a source status, not a fabricated empty successful list.
Duplicate project identities across sources remain separate with explicit
project collision markers. Attempts retain source-qualified identities; no
winning source or cross-source Attempt collision flag is inferred.

`auto-g16-native-query/1` supplies source-scoped Project -> WorkflowRun -> Task
-> Attempt list/detail projections. Every fact field uses availability
(available/missing/unavailable), value, source, reason and units where relevant.
Source alias + native Attempt identity is the query identity. List and detail
use the same projector. Execution state is Core only; capture, Result,
validation and review are independent. No clock or scheduler freshness inferred.

Field sources:

- hierarchy, state, record identities/types: public Core snapshot methods;
- V30 persisted Observe axes: OD-35 permits only `query/service.py` to consume
  public `OBSERVATION_TYPE`, `ObserveBoundaryError`, and
  `project_attempt_observations` within the exact Core read snapshot. No append,
  private decoding, freshness recomputation or acquisition is permitted;
- V30 exact InputBinding, plan revision, capture/envelopes, attributed results:
  public ResultProvenanceService and GaussianResultQuery;
- Gaussian energy (hartree), geometry (angstrom), frequencies (cm^-1): only
  exact attributed Gaussian Result tuples validated by Result; preserve all
  result/capture identities and selection reason, no cross-capture splicing;
- V31 execution generation: recognized native record-type inventory only,
  explicitly labelled inventory evidence; mixed generations are a conflict;
- native program, exact plan/snapshot/input and captured-artifact metadata:
  Execution-owned `ProgramReadQuery`, bound to the registered historical
  snapshot and caller-owned Core view;
- native parsed optimization/energy/geometry/sampling facts: explicitly missing
  until an attributed scientific Result contract supplies them;
- scientific validation/review: unavailable without their qualified readers.

`program-completion-evidence/1` and effect receipts remain private Execution
contracts. Query/HTTP delegates to public `ProgramReadQuery`; it does not decode
these payloads, call operational readers, create a driver, parse logs, fabricate
InputBindings or change execution/transport/conformer state. The owning reader
checks historical content associations and returns detached, sanitized,
source-attributed facts. Its result is not executable authority, current runtime
qualification, transport dual-source qualification or scientific acceptance.

## Acceptance and handoff gates

Focused tests: schema/sidecars/no-follow/missing DB/zero mutation, stable ordering,
exact bound old plan, multi-source failures/collisions, mixed generations,
unknown protocols, list-detail parity, Gaussian attributed units and provenance.
Affected tests: Core, Result and Observe; old frontend query/result routes. Preview:
GET-only native endpoints using existing frontend boundary, no provider/monitor,
list/detail/missing/source navigation in browser. Real-source comparison binds
configuration and before/after digests plus directory/physical identity;
unavailable unconfigured sources remain gaps, never synthetic acceptance.
Static CI audit before handoff. Core/Result independent review and authoritative
validation selection remain integration gates; new query ownership must be
reviewed, not silently routed around UNMAPPED_MODERN_PATH. This candidate does
not change selector policy or required checks.

## Historical authorization: owning reader continuation, 2026-09-28

This section records the then-current scope; current authorization is above.

Owner explicitly extends this task to the minimal owning Execution/Result readonly
reader, exact validation ownership, and directed existing Gaussian V31 source
location. Implementation, offline tests and isolated preview remain authorized;
commit, publication, integration, activation and live operations remain excluded.
The prior three repair cycles remain consumed; one repair cycle and at least
20 active repair minutes remain. Initial implementation of this newly approved
interface is not a repair cycle. Independent review is required.

Execution owns `ProgramReadQuery` in `execution/readonly.py`. It consumes a
caller-owned Core read view and immutable explicitly registered expanded snapshot
bytes/digest. It returns sanitized detached mappings only, never executable
snapshots or transport authority. Common closed component decoders are extracted
without changing the operational snapshot decoder. Historical scheduler content
hashes and original snapshot/intent identities are checked without regenerating
scripts from today's wrapper. Core supplies a public read of the persisted
submission intent. Exact plan revision and resource/task/project binding remain
mandatory. Gaussian extra startup disclosure is not projected or qualified.

Completion projections check persisted receipt identities, snapshot/input/output
associations and captured byte hashes; they never parse scientific logs or claim
transport dual-source authority, current deployment qualification, or scientific
acceptance. Persisted assessments remain labelled recorded, not independently
recomputed science. Missing parsed native energy/geometry stays missing. A
snapshot mismatch, unknown adapter or ambiguous completion fails closed.

Exact new query/reader/test routes are added to the existing selector;
this contract document retains the conservative `v3-full` document route;
existing owning routes and self-protection remain intact. No full-lane fallback
or required check is weakened. Authoritative clean-commit selection remains a
later gate, now authorized under the current local commit freeze scope.

## Historical authorization: additional repair, 2026-09-28

The exclusions below describe that repair stage; current authorization is above.

Owner approved:
up to four additional offline repair cycles OR 30 active diagnosis/editing
minutes, whichever comes first. Prior four cycles remain consumed. Scope is
measured CREST readonly latency repair, post-capture drift/metadata/terminal
assessment adversarial rejection tests, affected owning regression, real
three-program browser acceptance and independent review. Waiting for tests or
review is excluded from active repair time. A normally running validation must
complete under its existing strategy; repair-budget expiry does not authorize
interruption. The earlier exit-130 run remains incomplete evidence.

All existing source, interface and routing authority remains valid. No Git
publication/integration, deployment/installed-service switch, SSH/PBS/scientific
execution or business/approval writes are authorized. This is continuation of
this exact worktree and candidate, not a reset of prior evidence or budget.

The measured CREST hotspot is repeated canonical serialization of assessment
prefixes. The historical reader uses request-local incremental SHA-256 state
with exactly the existing Execution canonical encoding and checks every original
assessment condition. There is no cross-request/source cache or weaker validation
mode. The operational runtime validator remains unchanged. Its compact assessment
contract is mirrored within the same Execution owner for this read optimization;
future runtime contract changes require updating the reader and its valid/invalid
history differential tests together. Unsupported unused trailing records retain
the operational validator's original behavior.
