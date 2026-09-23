# Auto-G16 v3 acceptance: transport-resources

Component of [acceptance.md](../../acceptance.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

### Companion sections

The retained text uses directional references from the original combined
document. Read the applicable linked sections with this component; these
links preserve the existing dependencies and successor relationships.

- [V30-TRANSPORT-BOOTSTRAP-CHAIN-03: Deployment Manifest and Closed Command Chain](transport-bootstrap.md#v30-transport-bootstrap-chain-03-deployment-manifest-and-closed-command-chain)

<!-- Moved from docs/v3/acceptance.md:1391-1520 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## `V30-EXEC-RESOURCE-ENACTMENT-CONTRACT-01`

This resource-enactment contract is accepted only when all of the following
hold:

1. The exact identity-closed `ResolvedResourceRequest` inside the current
   `ExecutionSnapshot` is the sole authority for cores, integer MB, integer
   walltime seconds, and optional queue.
2. The private derived enactment repeats exact snapshot/resource IDs and all
   four values; changing any one rejects before qsub.
3. Current-profile canonical runtime content named exactly
   `pbs-resource-enactment-v1.json` has only the frozen schema and one closed
   dialect ID, and its bytes close through the resolved profile and snapshot.
4. Missing, unknown, malformed, aliased, or drifted dialect content rejects.
   The only production dialect is separately qualified by exact read-only
   deployment evidence, never inferred from generic scheduler knowledge.
5. `SUBMIT_QSUB_ONCE` carries the closed nested resource object and PBS
   basename only. Caller argv, argv fragments, shell, eval, format strings,
   executable selection, environment overrides, and fallback defaults are
   impossible or rejected.
   The payload keys are exactly `pbs_basename` and `resource_enactment`; the
   nested seven-key object, queue-null exception, binding equality rules, and
   958-byte canonical request vector replay exactly. The `/2` response has no
   new channel: its exact four-key envelope and one-key `{job_id}` result plus
   123-byte canonical response vector replay exactly.
6. The bootstrap selects only a source-controlled renderer and invokes the
   exact manifest-bound qsub executable with `shell=False`.
7. For the synthetic test dialect, null queue emits no synthetic selector. For
   the qualified production dialect, queue is mandatory and exact. No queue
   substitution, default, or inference occurs.
8. Walltime uses exact integer arithmetic without rounding; memory comes from
   `memory_mb`; cores come from `cores`. Gaussian `%mem` and `%nprocshared`
   neither authorize nor rewrite scheduler resources.
9. Caller PBS `#PBS -l`, `#PBS -q`, and equivalent resource directives remain
   rejected by `PbsTemplateBinding`.
10. Rendered qsub argv is deterministic only from dialect, exact resource
    request, and PBS basename and matches the exact reviewed vector. It is
    mechanical evidence, not persisted mutable authority.
11. Protocol `/2`, table `/2`, and fixed bootstrap-v2 source replace `/1` only
    for this closed request/table change. The seven operations, AGV3 framing,
    trust roots, bounded channels, physical bindings, and no-retry semantics
    remain unchanged.
    The Torque-capable Phase-B bootstrap-v2 successor keeps the exact name and
    is 15597 bytes, 204 LF, zero CR/NUL, with SHA-256
    `b0b1bcaf8ab8697a80676ac1015503a2fb64c21949678f20bf05f3bd849fb10e`.
    Those source bytes replay exactly. The pre-Phase-B integrated source was
    15195 bytes, 201 LF, with SHA-256
    `3f3653a8b13d4cb5a5f5ba6e9caa02c3049caf144af13fd4491674c1fc7eb2f3`
    and remains immutable historical evidence rather than an accepted
    production-Torque source.
12. The offline renderer remains visibly synthetic, has a closed exact vector,
    and both live subprocess driver and bootstrap execution reject it before
    process/qsub creation. Its 114-byte descriptor and digest plus the
    1570-byte table-v2 vector and digest replay exactly. It cannot satisfy
    production live readiness; the separately qualified Torque renderer does
    not reinterpret it.
13. Historical PBS artifacts remain reuse evidence only. Exact non-secret
    read-only deployment evidence, recorded by the separate production Torque
    contract, is required before a production renderer can become live-capable;
    qualification still performs zero qsub and grants no live authority.
14. Snapshot/resource/dialect splicing, queue/memory/time/core drift, request ID
    mismatch, and unexpected renderer tokens fail closed. `REPLAY` yields zero
    qsub; `UNKNOWN` never produces a second qsub.
15. No public Core/Approval/Workflow/Execution/Observe/Result/
    ScientificValidation/Review API or schema changes, and no planner,
    telemetry, retry, qdel, cleanup, deployment, OpenSSH, or live effect occurs.
16. Narrow reuse is recorded as PORT existing resource and no-shell primitives,
    EXTRACT only neutral deployment facts, WRAP the RTwin qsub mechanics,
    REWRITE the resource renderer because current v3 omits enactment and legacy
    governance is not authority, DROP legacy/free-form/default authority, and
    DEFER planning/telemetry/adaptive/multi-node policy.
17. Focused and affected evidence, exact negative vectors, static/diff/
    sensitive checks, and fresh independent contract and implementation review
    each close at `P0/P1/P2/P3 = 0/0/0/0` before integration.

## `V30-PBS-TORQUE-DIALECT-01`: exact production Torque renderer

The production dialect is accepted only when all of the following hold:

1. Read-only deployment evidence identifies Torque `6.1.0`, one 44-processor
   node, and exact first-live queue `batch`; no qsub was performed to obtain
   that evidence.
2. Manifest `server_qsub` is exactly `/usr/local/bin/qsub`, 418920 bytes,
   SHA-256 `f950e7d15287ca125e76ad81e115019e903227e5816b9a21c19967945e292c6d`;
   manifest `server_qstat` is exactly `/usr/local/bin/qstat`, 185656 bytes,
   SHA-256 `3ecac5943864adef1a4d0b9aa235861a5fa573d8c3c7fd2b615694148ba5f85a`.
   Their lack of package-manager ownership creates no invented package
   identity.
3. The only new dialect ID is exactly
   `auto-g16-v3-pbs-resource-enactment/torque-6.1.0-nodes-ppn/1`; the existing
   synthetic ID and vector remain unchanged and non-production.
4. The renderer consumes only exact snapshot-derived `cores`, `memory_mb`,
   `walltime_seconds`, and `queue`, plus the exact portable PBS basename. It
   does not select or return qsub.
5. For values `C`, `M`, `W`, `Q`, `B`, the exact tuple is `("-l",
   "nodes=1:ppn=C,mem=Mmb,walltime=W", "-q", "Q", "B")`; no alternate
   spelling, resource order, split clause, sign, unit conversion, or time
   formatting is accepted.
6. `cores`, `memory_mb`, and `walltime_seconds` are positive non-boolean
   integers. Zero, negative, bool, float, string, or other values reject.
7. Production queue is mandatory and equals exactly `batch`. Null or another
   queue rejects; the scheduler default never satisfies snapshot authority.
8. Queue and basename retain their existing closed portable-token validation;
   no caller-supplied qsub token or resource-list fragment can enter rendering.
9. Current profile canonical descriptor admits only the exact synthetic and
   Torque IDs. Unknown, missing, malformed, aliased, or drifted content rejects
   before process creation, with no detection or fallback.
10. Synthetic remains `live_capable = false`; Torque is mechanically
    `live_capable = true`. Neither flag authorizes a live effect.
11. Active `#PBS -l` and `#PBS -q` staged-template directives remain rejected;
    historical legacy templates are not reinterpreted or modified.
12. Exact positive renderer vectors cover `(1, 1, 1, batch)`,
    `(22, 51200, 43200, batch)`, and one 44-core representative request.
13. Unknown dialect, null/wrong queue, invalid integer/token/basename, resource
    splice, unexpected renderer token, and qsub/qstat path/size/digest drift all
    fail closed before the relevant process call.
14. `REPLAY` performs zero qsub; `UNKNOWN` never permits a second qsub. The
    affected synthetic V30-A composition continues to prove the full authority
    and downstream Result/validation/review chain without a live server.
15. Exact deployment path/size/digest authority stays in the manifest;
    `ResolvedResourceRequest` stays the sole resource authority. No second
    executable, resource, queue, or current/latest authority is introduced.
16. No public Core/Approval/Workflow/Execution/Observe/Result/
    ScientificValidation/Review API/schema changes, live qsub, Gaussian, qdel,
    remote mutation, deployment, retry, deletion, or cleanup occurs.
17. Narrow reuse is PORT/EXTRACT of exact Torque deployment mechanics only;
    v2 governance remains dropped. Focused/affected validation and fresh
    independent contract and implementation review each close at
    `P0/P1/P2/P3 = 0/0/0/0` before integration.

<!-- Moved from docs/v3/acceptance.md:1931-1961 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

## V30-EXEC-PBS-WORKDIR-ENACTMENT-CONTRACT-01

1. The only scheduled-workdir authority is the exact current
   `ExecutionSnapshot.workspace_binding.remote_attempt_dir`.
2. Torque argv begins with exact `("-d", remote_attempt_dir)` and retains the
   reviewed resource, queue, and PBS basename tokens afterward.
3. Caller argv, PBS directives, environment, scheduler default, profile value,
   and payload override cannot select a different workdir.
4. Immediately before qsub, the named path is reopened no-follow, its physical
   token is replayed, and its device/inode equals the retained workspace
   descriptor. Replacement, symlink, splice, or drift rejects before qsub.
5. The qsub client descriptor cwd and scheduled `-d` path equal the same exact
   workspace. No shell, PATH qsub, retry, fallback, or second qsub is added.
6. `SUBMIT_QSUB_ONCE`, AGV3 `/2`, payload schema, manifest schema v2, ten trust
   roots, public APIs, and Result model remain unchanged.
7. Synthetic vectors include the bound workdir and negative vectors cover
   invalid paths, workspace replacement, authority splice, caller override,
   `REPLAY`, and `UNKNOWN`.
8. Fixed source, operation table, and launcher successor identities replay
   exactly: table 1623 bytes /
   `ce3efce070694831c32dbadd71fc2e7991f02cd985055193966666ea19dc9ffc`,
   bootstrap 15926 bytes / 210 LF /
   `a90edecf87916c149e865256d69e6f57820cb29336380bd45d2107c7c00c64f0`,
   and launcher-v5 11790 bytes / 200 LF /
   `184b806c07f05fdd1e51a669e9ff245f43c22b22b2efa17e5578f501d2e2d06d`.
   Live use requires the next profile revision and a fresh authority chain;
   this integration authorizes no deployment or calculation effect.
9. Future scheduler/output acquisitions persist append-only per-acquisition
   sequence, timestamp, operation, bounded raw result identity/bytes, and
   classification. Aggregate terminal summaries do not replace that evidence.
