# Auto-G16 v3 Reuse Adjudication

This table records the Phase 0 disposition. It is not a copy of the underlying
v2 design reports.

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
