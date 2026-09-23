# Auto-G16 v3 tasks: v31-file-completion

Component of [AUTONOMOUS_DEVELOPMENT.md](../../AUTONOMOUS_DEVELOPMENT.md); it retains that document's
authority and unchanged technical requirements. Read the selected component,
its cited dependencies and applicable Owner decisions together. Relocation
does not reopen historical permissions or replace a reviewed successor.

<!-- Moved from docs/v3/AUTONOMOUS_DEVELOPMENT.md:766-884 at 394e88bbac54a15d42973cf8b607e515343b1814. -->

### V31-PBS-COMPAT-FILE-COMPLETION-01

The phase and candidate labels below are retained checkpoints, not the current
implementation status. [PR #173 integration](../../STATUS.md#file-completion-implementation-checkpoint)
and the [freeze dossier](../../pbs-file-completion-freeze.md) record the later
C2/C3/C4 implementation and evidence cutoffs. No contract or acceptance vector
is retired, and the historical opening instruction is not renewed.

- **Class / autonomy:** Feature development; v3; OWNER-GUIDED. Ordinary Codex
  app isolated task, not a BUS Executor; no CTRL/Control Issue is created.
- **Outcome:** Freeze OD-32 and the exact receipt-on-absence boundary for new
  xTB successor Attempts, then perform the smallest offline implementation
  only after actual independent review and repository Owner L3 freeze.
- **Current authority:** User authorized this ordered contract-first work,
  local documentation, necessary review and local freeze commit. This grants
  no generic permission to choose an unresolved safety contract or to claim
  that Owner reviewed the eventual content. No further user task is created.
- **Phase 1 allowed paths:** `OWNER_DECISIONS.md`,
  `docs/v3/boundary-spec.md`, `docs/v3/acceptance.md`,
  `docs/v3/AUTONOMOUS_DEVELOPMENT.md`, `docs/v3/STATUS.md`,
  `config/context-map.toml`, and
  `docs/v3/pbs-file-completion-freeze.md` (content manifest, review and handoff).
- **Phase 2 proposed paths (inactive until freeze):**
  `auto_g16/execution/program.py`, `auto_g16/execution/program_runtime.py`,
  new private `auto_g16/execution/_program_completion.py` and
  `auto_g16/execution/_program_completion_wrapper.py`,
  `auto_g16/transport/program.py`, `auto_g16/transport/_program_rtwin.py`,
  `tests/v31/transport/test_program_composition.py`,
  `tests/v31/transport/test_rtwin_successor_bridge.py`,
  new `tests/v31/transport/test_program_completion.py`, and the phase-1 docs
  for evidence only. Existing marker/bootstrap protocol and schemas do not
  change. Any newly discovered required path is an explicit scope decision.
  Real receipt-mode drivers/evaluation stay hard-disabled pending a separate
  publisher qualification contract/gate; synthetic offline completion only is
  acceptance scope for this implementation. Existing strict production is
  unchanged. No user-selectable qualification override is added.
- **Dependencies / reuse:** REWRITE only mode/rendering/receipt evaluator;
  WRAP existing STAT/FETCH and raw acquisition; EXTRACT existing canonical
  identity and no-follow/exclusive publication primitives; keep Core,
  Approval, Result, Observe schemas and existing successor composition owners.
  No legacy v2 owner/capability framework, new public record or extension bag.
- **Compatibility / migration:** Default strict and historical serialized IDs
  remain exact; new adapter version is opt-in on fresh Attempts. No migration
  command, historic job read, historic result rewrite, CREST integration or
  Gaussian generation change. Unsupported downstream consumers reject `/2`.
- **Review / stop:** L3 scheduler/security boundary. Independent technical
  review is required but does not replace repository Owner review. Freeze
  exact six authority-file hashes plus a local candidate commit and preserve
  review evidence in the dossier. P0/P1, mismatched hashes, Owner decision
  missing, drift or an unclosed dependency stops before product edits. The
  Owner decides the publisher trust model, absence/terminal conflict policy,
  and execution-output/scientific boundary by accepting the exact candidate.
- **Sequencing:** The implementation is the second checkpoint of this same
  task/worktree, not a separately developed lane; no prior merge is required
  by this task. If review instead requires independently isolated code work
  or prior integration, hand off exact frozen material and that blocker, and
  stop without creating a new user task or modifying shared main.
- **Validation:** preflight before edits; contract static/link/TOML/diff and
  CI audit; focused/affected implementation vectors FC01–FC15 after freeze.
  No blind full, remote CI, pressure test or live test. Handoff distinguishes
  static evidence, independent review, Owner freeze, implementation and live.
- **Forbidden:** push, PR, merge, deployment, release, SSH, RTwin, PBS,
  xTB/CREST/Gaussian execution, qsub/qdel, remote writes, cleanup or scientific
  acceptance. Synthetic offline wrapper process tests may use only inert
  fixture children; they grant no program/live authority.
- **Disposition:** CANDIDATE; repository Owner exact-candidate freeze pending.
  Local worktree/branch retained; cleanup and archival are not authorized.

#### C3 material-derivation checkpoint

Historical checkpoint; see the [later implementation disposition](../../STATUS.md#file-completion-implementation-checkpoint).
The material-derivation requirement remains part of the accepted contract.

C2 Owner acceptance activates phase 2, but implementation discovery of the
manifest-content gap stops the dependent renderer at a P1 contract boundary.
C3 proposes only the private material input/data-line/prebinding delta defined
in the boundary supplement, within the existing allowed paths. No public
record, Transport operation, deployment, production qualification or live
permission is added. C3 remains an exact Owner review checkpoint; it is not
an autonomous reinterpretation of accepted C2. Isolated pure receipt grammar
work already started is retained as incomplete work, not an implementation
PASS. Do not activate C3-dependent code before the new review closes.


#### Authorized A/B follow-up and proposed C4 activation

Historical A/B opening and C4 proposal checkpoint; see the
[later C4 disposition](../../STATUS.md#v31-file-completion-c4-proposal-status).
The original conditional gate below is retained, not reopened.

The Owner authorized this same task to repair only
`config/validation-selection.json`, `tests/test_validation_selector.py` and
necessary evidence docs (A); and to prepare/review the C4 proposal in the six
phase-1 authority files and dossier, with credential-free local native probes
(B). Selector/runner/workflows/required checks remain immutable. Necessary
local checkpoint commits use normal hooks and staged scans; no automatic full
run, push, PR, merge, deployment, live operation or cleanup is authorized.

**C4: PROPOSED / OWNER ACCEPTANCE PENDING.** B does not accept an unwritten
contract. After independent review, freeze exact six-file hashes and a local
candidate commit for Owner decision. On explicit acceptance of those exact
bytes, the proposed next phase is only the C4 offline implementation in
`auto_g16/transport/program.py`, `auto_g16/execution/program_runtime.py`,
`tests/v31/transport/test_program_completion.py`,
`tests/v31/transport/test_program_composition.py`, plus phase-1 evidence docs.
Reuse public Core calls and existing transport authority; no new module, public
API/schema, factory default change, VFS override or product provisioning path.
The only new persistent schema is the exact private `/2` store described by C4.
Any additional necessary product path or unresolved design change stops for a
bounded scope/contract decision. Prior C2/C3 product bytes stay frozen during B.

Use focused C4 vectors on the native Mac with inert fixtures and default SQLite,
adjacent strict compatibility and exact-base/head selection; obtain independent
review of exact product bytes. No full acceptance claim from primitive probes,
no old-store migration and no production qualification override. C4 acceptance
would authorize this bounded offline implementation, not creation of real
operational stores, live tests or acceptance of eventual implementation results.
