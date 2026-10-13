# Auto-G16 v3 acceptance: v31-ensemble

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/acceptance.md:1530-1632 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## v3.1: Flexible-Molecule Ensemble

`V31-SHARED-CONTRACT-01` is accepted only when all of the following are true:

1. The candidate is contract-only and changes only the minimum v3 authority
   and context documents. No product, Core schema, execution schema, parser,
   Transport, test/vector, deployment, or live byte changes.
2. The disposition is explicit: KEEP Core/approval/safety semantics; ADD
   provisioning and ensemble contracts; use VERSIONED SUCCESSOR execution
   records; DO NOT TOUCH the named V30/Core/Transport/parser/vector surfaces.
3. Core `Project` remains exactly `{project_id}` and its SQLite schema is
   unchanged. Project physical state lives outside Core.
4. The only new execution-domain public records are `ProgramExecutionSpec` and
   `ProgramExecutionSnapshot`. Provisioning-domain `ProjectPhysicalBinding`
   does not consume this budget. No public ProgramAdapter, plugin protocol,
   third execution record, or extension bag is introduced.
5. Project provisioning has exactly three branches: absent target permits one
   exact nonrecursive no-follow mkdir plus durable binding; already Product-
   bound existing permits exact physical re-attestation and idempotent reuse
   with no second mkdir; existing without Product binding returns
   `UNBOUND_EXISTING`, performs zero effects, and stops for a later Owner
   migration/adoption decision. Implicit adoption is forbidden.
6. Provisioning never overwrites, truncates, recursively replaces, deletes, or
   cleans a path; a concurrent loser performs zero effects; confirmed reuse
   requires the exact current physical identity.
7. The private closed ProgramAdapter registry accepts exactly `gaussian`,
   `xtb`, and `crest` under exact adapter versions. Unknown programs or versions
   fail closed and no public registry mutation exists. Initial V31
   implementation acceptance requires successor adapters for xTB and CREST
   only. The Gaussian discriminant neither implements a Gaussian successor nor
   requires migration from the production-usable V30 Gaussian generation.
8. `ProgramExecutionSpec` binds program identity, adapter/version, every exact
   immutable input, closed program data, executable identity, argv tokens,
   stdin/data, closed environment, and disjoint exact required/optional output
   declarations. `ProgramExecutionSnapshot` binds that exact spec to the
   Project physical binding, Attempt/workspace, plan revision, resources/target,
   cwd, and derived scheduler artifacts.
9. Primary invocation meaning is closed typed data and tokenized argv with
   non-shell process semantics. Caller shell-command strings, ambient PATH/env,
   undeclared files, and script-as-second-authority cases are rejected.
   For xTB adapter contract version 2, this additionally requires one canonical
   resolved-profile `xtb_data_path`, one canonical
   `xtb-runtime-data-manifest-v1.json` runtime identity, and exactly the two
   environment declarations `OMP_NUM_THREADS` from resolved resources and
   `XTBPATH` from that resolved profile path. Equivalent JSON formatting or key
   order has one identity; any manifested file path, size, or SHA-256 drift
   changes it. Missing authority and caller-provided environment values reject,
   and the current CREST adapters remain unchanged.
10. A V31 Workflow or Batch may intentionally contain V30-generation Gaussian
    Attempts together with successor-generation xTB/CREST Attempts. For each
    individual Attempt, the exact generation is fixed before effect authority:
    exactly one generation is bound, never both, and no in-place conversion is
    permitted. V30 `PreparedInputBinding`, `PbsTemplateBinding`, and
    `ExecutionSnapshot` remain unchanged and production-usable for Gaussian DFT
    SP/Opt/Freq/Opt+Freq. xTB and CREST must use `ProgramExecutionSpec` plus
    `ProgramExecutionSnapshot`. A future Gaussian successor is optional and
    requires separate adapter implementation and validation; V31 acceptance
    does not require any Gaussian Task or Attempt to migrate.
11. `SamplingProfile` is independently identified and frozen before
    observations. It owns every applicable route/quota, legality,
    cluster/dedup, coverage, thermodynamic-eligibility, and TS-seed-eligibility
    parameter. An ensemble cannot override it.
12. No universal 6 kcal/mol, Top-N, RMSD, route quota, temperature,
    low-frequency, or other numeric default is frozen. Missing policy blocks;
    explicit inapplicability is tagged with rationale.
13. `ConformerEnsemble` closes species/electronic state, stereochemistry,
    provenance, geometry, sampling observations, complete audit/negative
    evidence, clusters/dedup, coverage, and both ordered eligibility
    projections. Cross-state ranking and silent stereo/category merges reject.
14. `thermodynamic_eligible_members` and `ts_seed_members` are deterministic
    filters of canonical member order under the exact SamplingProfile and
    evidence. Missing audit, coverage, minimum, state/stereo, lineage, or
    independent-backend evidence cannot be bypassed by a fallback subset.
15. TS-seed handoff is `ConformerEnsemble.ts_seed_members`; V31 adds no separate
    TS-seed lifecycle. The projection grants no TS, method, reaction,
    portfolio, input, or execution claim; later TS-seed review remains required.
16. `ThermodynamicEnsemble` binds one exact complete eligible member set,
    temperature, standard state, low-frequency scheme and all parameters,
    implementation identity, method compatibility, degeneracy conventions,
    per-member provenance, and partition/population evidence.
17. Every conformer retains distinct raw RRHO and treated qRRHO terms. All
    included members are compatible under one exact method binding; missing or
    incompatible eligible members block instead of silently renormalizing.
18. Populations and ensemble free energy are reproduced from the frozen
    degeneracy-weighted partition formula. Degeneracy does not duplicate
    symmetry factors, and conformational mixing represented in the partition
    sum is not added again as a separate entropy correction.
19. Authoritative selector output for the frozen commit is `v3-full` with
    `fail_closed=false`; its exact selected offline tests and required static,
    CI-contract, diff, sensitive-data, and clean-preflight checks pass.
20. Fresh independent findings-first review binds base/head/tree/scope and
    reports P0/P1/P2/P3. Any P0/P1 blocks handoff. A local commit and PR-ready
    handoff grant no push, PR, merge, implementation, provisioning, xTB, CREST,
    Gaussian, Transport/PBS, deployment, retry, cleanup, or scientific authority.

A future real flexible molecule may then be proposed through:

`xTB preopt -> CREST -> audit -> DFT -> Freq -> qRRHO -> ensemble`

Every arrow remains separately gated. Contract acceptance does not execute the
case. When a later reviewed implementation and one authorized real case meet
their own acceptance criteria, stop v3.1 feature expansion.
