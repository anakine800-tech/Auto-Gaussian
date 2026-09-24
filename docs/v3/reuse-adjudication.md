# Auto-G16 v3 Reuse Adjudication

This table records the Phase 0 disposition. It is not a copy of the underlying
v2 design reports or a current runtime dependency graph. Current code and focused
test locations are maintained in [context-map.toml](../../config/context-map.toml).

| Capability | Existing implementation | v3 layer | Science disposition | Behavior disposition | Governance disposition | Data compatibility | Runtime compatibility | Reuse target | Must not carry into v3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Knowledge records and scientific models | `auto-g16-knowledge-base` | Knowledge | **EXTRACT** reviewed models | **REWRITE** clean services around typed data | **DROP** runtime-coupled governance | **PORT** reviewed data through explicit adapters | **DROP** v2 runtime ABI promise | **EXTRACT** models and validated data shapes | Whole v2 runtime and incidental owner machinery |
| Conformer discovery | `auto-g16-conformer-search` | Scientific / Workflow | **EXTRACT** scientific primitives; **REWRITE** sampling, coverage, and DFT policy after benchmarks | **REWRITE** orchestration | **DROP** permanent A/B quota governance | **DEFER** artifact migration until policy review | **DROP** v2 runtime ABI promise | **EXTRACT** freedom analysis, legality checks, matching, and clustering | Historical route quotas as permanent scientific rules |
| Execution authorization and state | v2 execution batch, facade, and protected paths | Execution Safety / Runtime State | **DEFER** to the owning scientific workflow | **EXTRACT** no-overwrite, single-submit, and uncertainty semantics | **DROP** old receipt, owner, and lineage forest | **DEFER** migration by artifact type | **DROP** v2 runtime ABI promise | **REWRITE** safety state around `Attempt` and `ExecutionSnapshot` | Old governance implementation as v3 architecture |
| Direct SSH | v2 direct-SSH offline and production-closure work | Transport | **DEFER**; transport does not decide science | **EXTRACT** safety and runtime lessons | **DROP** private capability-chain implementation | **DEFER** profile migration | **DROP** v2 backend ABI promise | **REWRITE** as thin `OpenSSHTransport` | Old single-use capability and private owner chain |
| Legacy RTwin/PBS | `legacy_rtwin_pbs` and legacy adapters | Transport / Program Adapter | **PORT** only already reviewed scientific inputs | **WRAP** the existing running path | **DROP** authority over the clean core | **PORT** only explicitly mapped artifacts | **WRAP**, not a v3 ABI | **WRAP** as a legacy adapter and reuse source | Legacy backend internals in Core |
| CI and validation tooling | v2 test runners, static audits, and workflows | Developer Control Plane | **DEFER** science matrices to owning workflows | **EXTRACT** useful tooling; **REWRITE** change selection | **DROP** duplicated full-run topology | **PORT** sanitized fixtures when still meaningful | **DROP** v2 CI topology as a contract | **EXTRACT** focused runners and static checks | Unchanged v2 full-validation topology |
| Minimal Workflow DAG | reaction-workflow calculation DAG plus public Core records | Workflow | **DEFER** chemistry-specific stages and policy | **EXTRACT** finite-DAG invariants; **REWRITE** typed graph/projection | **DROP** file-carried execution/readiness authority | **WRAP** reviewed scientific plans through explicit mapping | **PORT** only public Core records/APIs | **PORT** Core identities; **EXTRACT** graph tests; **WRAP** legacy plans | Chemistry stage matrix, embedded execution state, executable flags, callbacks, and hash authority |
| Generic compatibility capsule framework | No required v3 capability | None | **DROP** | **DROP** | **DROP** | **DEFER** only concrete migrations | **DROP** | **DROP** | Any generic capsule framework |

The following distinctions describe the retained relationships; they do not add
schema fields or supersede the Phase 0 dispositions:

- **CURRENT_IMPLEMENTATION:** `auto_g16/**` owns the implemented v3 product
  surfaces. In particular, `auto_g16/conformer/` contains SamplingProfile and
  ConformerEnsemble records, CREST ingest, audit/clustering, post-DFT refinement
  and final integration. `auto_g16/thermochemistry/` contains Gaussian facts,
  the GoodVibes functional-kernel adapter, normalization/aggregation and
  ThermodynamicEnsemble. Their presence does not close policy rebenchmarking,
  native adapter qualification or scientific acceptance.
- **RUNTIME_DEPENDENCY:** an actual import/load relationship in its named
  consumer, not merely a reuse reference. For example, thermochemistry consumes
  conformer refinement provenance and loads the pinned GoodVibes kernels;
  `scripts/python_environment.py` loads the root `scripts/runtime_config.py`,
  not the Skill file with the same name. The legacy
  `skills/auto-g16-rtwin-pbs/scripts/gaussian_rtwin_pbs.py` wrapper dynamically
  compiles/executes `legacy_rtwin_pbs.py` in its compatibility namespace.
- **VALIDATION_DEPENDENCY:** the existing
  [validation selection](../../config/validation-selection.json) retains legacy
  safety tests alongside modern coverage. Its `v31-conformer` route includes
  `tests.test_conformer_search`; `v31-thermochemistry` includes conformer tests
  and `tests.test_scientific_closure_lineage`. Execution/Transport routes retain
  authorization, descriptor/root, qstat and resource-monitor safety tests.
  These tests do not make the legacy implementation a v3 runtime dependency.
  Changes to this page or `context-map.toml` select the bounded `v3-full`
  inventory, not legacy complete-full discovery.
- **PACKAGING_DEPENDENCY:** named-Skill `deployment-package.json` manifests
  and `config/deployment-package-supplements/` include root scripts and resources
  through `scripts/skill_package.py` and `scripts/sync_named_skill.py`. For
  example, the RTwin/PBS `direct-ssh-pbs-offline.json` supplement includes
  `scripts/direct_ssh_pbs_offline.py` and its reference document. Package
  membership is separate from the v3 import graph and from deployment authority.
- **REUSE_SOURCE:** legacy Skill primitives, Direct/protected safety lessons
  and adjacent tests inform reviewed extraction or rewrite. Listing them beside
  modern paths in the context map does not assert an import. The static Python
  import audit found no direct `auto_g16` import of legacy Skill, `direct_*` or
  `protected_*` modules; it does not exclude dynamic loading or packaging use.
- **LEGACY_PRODUCT / MAINTENANCE_ONLY:** `legacy_rtwin_pbs.py` remains a retained
  product behind its compatibility entrypoint, with bug/security maintenance.
  It is not a destination for new v3 capabilities or architectural beautification.
  This disposition means neither deprecated nor safe to delete.
- **HISTORICAL_ONLY:** dated launch/status snapshots and superseded design
  evidence preserve provenance; they do not grant current execution authority.
  This label cannot be applied to executable legacy code just because an import
  search finds no callers. Deletion needs a separate dependency and product decision.

A semantic refactor preserves behavior; a qualification-affecting refactor also
changes identities checked by the publisher/collector. Existing checks in
`scripts/run_v31_publisher_pilot.py` and `auto_g16/transport/_program_rtwin.py`
bind module paths, source inventories/hashes and loaded-module identities.
Moving a helper can therefore preserve semantics while invalidating prior
qualification identity. Existing qualification contracts determine the required
new evidence; this map changes no hash/approval model or live-ready status.

## V30-WF-CONTRACT-01 Narrow Reuse Adjudication

The Workflow audit is intentionally limited to
`skills/auto-g16-reaction-workflow/scripts/calculation_dag.py`, its adjacent
contract/tests, and the public Core WorkflowRun/Task/Attempt/CalculationPlan
surface. It does not make the legacy reaction DAG executable authority.

- **PORT:** public Core `WorkflowRun`, `Task`, `Attempt`, `CalculationPlan`, and
  the existing `SQLiteRuntimeStore` store/load, Attempt-state, parent, and
  explicit child APIs. Core identity, one-root, terminal-child, conflict, and
  `UNKNOWN` rules remain unchanged.
- **EXTRACT:** finite graph closure, missing/self/cycle rejection, deterministic
  lexical topological order, producer/role consistency, independent readiness
  axes, read-only projection, and their adjacent adversarial tests.
- **WRAP:** `gaussian-reaction-calculation-plan/1` only as a validated external
  scientific-plan artifact mapped explicitly from `{study_id, plan_id,
  node_id}` to exact v3 WorkflowRun, Task, and CalculationPlan identities.
- **REWRITE:** typed v3 graph validation and run projection. The reusable logic
  currently lives in private dictionary functions such as `_topological_order`,
  `_validate_graph_relations`, and `_derive_index`, which mix generic graph
  behavior with chemistry stages, alternatives, supersession, file bindings,
  and legacy readiness. Direct porting would preserve the wrong authority.
- **DROP:** file-carried `execution_state`, `executable`,
  `calculation_ready`, resume status, hash lineage, owner/receipt machinery,
  and any implicit conversion of a scientific DAG node into an Attempt or
  submission.
- **DEFER:** alternatives, supersession policy, chemistry node/stage matrices,
  mechanism continuity, W1/W2/W3 production, TS/IRC/thermochemistry policy,
  scientific acceptance, validation caching, input rendering, transport, PBS,
  Gaussian, and live work.

Core has no public Task/Attempt enumeration or current-plan selection API.
V30-4 therefore uses explicit finite IDs and an exact node-to-Attempt mapping;
it does not add a Core API or guess a current plan. A ready node remains a
non-effectful proposal.
