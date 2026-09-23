# Auto-G16 v3 Post-Core Planning and Launch History

Retained from `AUTONOMOUS_DEVELOPMENT.md` at
`b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58` (tree
`e499ddc3435976d7f2c4b2f5dfbe07b7eb6e5216`). Original source:
[Git snapshot](https://github.com/anakine800-tech/Auto-Gaussian/blob/b5a27f4cc77b9f2224dd81a0be5bb5e333a0fd58/docs/v3/AUTONOMOUS_DEVELOPMENT.md).
The two original excerpts below are unchanged. The word “current” in the
first excerpt and the timed instruction in the second are historical labels.
Neither excerpt opens or continues a task today.

[Current rules and frozen contracts](AUTONOMOUS_DEVELOPMENT.md) remain the
entry point. The night task's finite scope, technical invariants, safety and
validation boundaries remain applicable to its delivered surfaces; only its
launch window and then-pending integration disposition are historical.
The later, separately authorized [PR #168](https://github.com/anakine800-tech/Auto-Gaussian/pull/168)
integrated that collection as `dbec1da2fe24731c4e9c5552d0632ad83501d89c`.
It did not convert the 2026-09-11 10:00 Asia/Shanghai deadline into standing
permission, or make local inventory/packet output production qualification.

## Post-foundation sequence snapshot

The current post-foundation execution/composition sequence is:

1. `V30-EXEC-02-COMPOSITION-CONTRACT-01` — integrated
2. `V30-VAL-TRANSPORT-01` — integrated
3. freeze/integrate `V30-TRANSPORT-BOOTSTRAP-CHAIN-03`
4. successor V30-EXEC-02 Transport implementation
5. `V30-A-SYNTHETIC-COMPOSITION-01` test-only integration after Transport main
6. `V30-A-READINESS-01` repeat audit before any live gate

The control structure remains serial at integration:

```text
Integration Owner
└── V30-EXEC-02-COMPOSITION-CONTRACT-01
    -> V30-VAL-TRANSPORT-01
    -> V30-TRANSPORT-BOOTSTRAP-CHAIN-03
    -> V30-EXEC-02 implementation
    -> V30-A-SYNTHETIC-COMPOSITION-01
    -> V30-A-READINESS-01
Live remains NO-GO
```

At most three independent workstreams may be active concurrently. Integration
and merge remain serial. Historical closed contracts below remain authority
for their owned surfaces.

### V31-NIGHT-OFFLINE-CLOSEOUT-20260911

- **Owner scope:** The explicit 2026-09-11 night instruction authorizes bounded
  offline development, self-review, independent review, and serial integration
  into one local collection worktree until 10:00 Asia/Shanghai. The final
  collection waits for the Owner before submission to main. This records the
  authorized development work; it grants no deployment or live authority.
- **Base and status:** Start the collection lanes from exact
  `065d016830240962c0aeb22873d3c82aa2f016d3`. At this baseline #162 and #166
  are integrated; the lanes below are night candidates, not merged-main
  results. The separately authorized Torque text-folding task has its own
  gate and disposition; do not infer its completion from this contract.
- **Class and concurrency:** `BOUNDED-AUTONOMOUS`; at most three active
  workstreams, one unique isolated worktree/branch per implementation, with
  the coordinator performing integration serially. This contract does not
  require BUS publication or manufacture CTRL/approval records.
- **Finite backlog:** A, `V31-SCHEDULER-RAW-EVIDENCE-DURABILITY-01`, adds the
  smallest private audit persistence before scheduler normalization; B,
  `V31-AFFECTED-RUNTIME-REDUCTION-01`, reduces redundant affected carriers
  while preserving safety evidence and fail-closed routing; C,
  `V31-LEVEL2-REQUALIFICATION-HARNESS-01`, prepares an offline candidate review
  packet; D, `V31-PRODUCTION-PROGRAM-QUALIFICATION-TOOLING-01`, inventories
  existing local program/runtime-data bytes; E,
  `V31-STATUS-AUTHORITY-CLOSEOUT-02`, separates product, production, science
  and live authority; F, `V31-STALE-ARTIFACT-PR-AUDIT-01`, only classifies
  historical PR/artifact disposition and recommends closure without closing.
- **Implementation boundary:** A stays in the private successor Transport
  store/driver audit seam and directly required tests; B stays in validation
  ownership/routing and directly required tests without deleting safety
  coverage; C and D stay in their named scripts, focused tests and short
  operator documents. E changes only the minimum V31 status, contract,
  acceptance and context references. F is read-only. No public API/schema,
  scientific policy, parser meaning, required CI context, production profile,
  transport topology or trust root is changed by these lanes.
- **A invariant:** Reuse the existing local append-only immutable machinery;
  retain exact acquired scheduler bytes and complete request/job binding
  before normalization. Audit evidence is neither normalized receipt nor
  terminal/scientific authority. Persist failure stops normalization, and
  `UNKNOWN` never grants retry. See the
  [private audit contract](scheduler-raw-evidence.md).
- **C invariant:** All approval decisions are null candidates. Real
  `ProgramExecutionSnapshot` remains deferred until authorized current Project
  attestation; do not call an effectful snapshot factory, use synthetic
  privilege, or invoke a default-APPROVED factory. The packet remains
  `BLOCKED_ON_LIVE_PREREQUISITES`, with zero current effect budget. See the
  [offline packet contract](level2-requalification-packet.md).
- **D invariant:** Inventory only supplied local no-follow binary/runtime-data
  bytes. Do not launch even a version probe. A missing version is unverified;
  matching captured output remains an unverified claim, never a qualification
  receipt. CREST claims require exactly 3.0.2. See the
  [local inventory contract](program-qualification-tooling.md).
- **Validation and handoff:** Use focused and bounded adjacent offline checks,
  proportional static/link checks, exact file/tree evidence and independent
  findings-first review. The Owner prefers avoiding full/full-CI reruns and
  prioritizing bounded checks for this night work. This preference does not
  waive an existing required gate: if such a gate requires full evidence,
  report the remaining validation gap rather than weakening or bypassing it.
  Do not convert a selector error into full discovery. Recheck
  cross-lane links, route ownership and final collection compatibility after
  assembly. Do not report sibling-only files or unrun checks as a standalone
  publishable PASS. Freeze candidates before integration; leave final main
  submission pending the Owner.
- **Stop:** Missing/conflicting authority, identity/scope drift, unbounded
  redesign, unresolved P0/P1, or any need for live facts outside the supplied
  evidence. No SSH/server reads, installation/upload, remote mkdir, qsub/qdel,
  xTB/CREST/Gaussian execution, real approvals, scientific acceptance,
  automatic retry, deletion or cleanup. Preserve historical incomplete
  scientific evidence and the need for fresh real Level-2 qualification.

<!-- End of verbatim excerpts. -->
